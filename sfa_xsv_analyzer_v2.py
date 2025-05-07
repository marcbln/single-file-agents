#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "litellm>=1.38.5", # For LLM abstraction and tool calling
#   "openai>=1.0.0",   # For OpenAI models, targeted for initial dev
#   "rich>=13.7.0",    # For enhanced console output
# ]
# ///
"""
Single-File Agent: XSV Analyzer v2 (sfa_xsv_analyzer_v2.py)

Purpose:
This agent leverages Large Language Models (LLMs) via litellm to analyze
CSV (and other delimiter-separated value) files using the 'xsv' command-line tool.
It takes a natural language query, incorporates general xsv help, allows the LLM
to request specific subcommand help using tool-calling, translates the query into
an appropriate 'xsv' command, executes it, and returns the result.

Based on the plan: ai_docs/plans/PLAN_sfa_xsv_analyzer_v2.md

Example CLI Usage:
  uv run sfa_xsv_analyzer_v2.py "show first 5 rows" -f data.csv
  uv run sfa_xsv_analyzer_v2.py "count unique values in 'city' column" --file data.csv --model gpt-4o-mini
  uv run sfa_xsv_analyzer_v2.py "filter rows where 'age' > 30 and select 'name', 'email'" -f users.tsv -d "\t"
"""

import os
import sys
import argparse
import subprocess
import json
import textwrap
import csv
import time # For retry logic
from typing import Tuple, Optional, List, Dict, Any

import litellm
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

# --- Initialize Rich Console ---
console = Console()

# --- Constants ---
DEFAULT_MODEL_LITELLM = "gpt-4o-mini" # Target for initial development
XSV_OUTPUT_MAX_CHARS = 4000
XSV_TRUNCATION_MESSAGE = "... [Output truncated]"
 
# API call settings (can be refined or use litellm's defaults)
API_MAX_RETRIES = 3 # For litellm calls, litellm has its own retry logic too.
API_RETRY_WAIT = 5  # seconds
MAX_INTERACTION_TURNS = 5 # Max LLM interactions (tool calls) to prevent loops

# Token tracking (global for simplicity in this SFA)
TOTAL_INPUT_TOKENS = 0
TOTAL_OUTPUT_TOKENS = 0

# Global to store main xsv help output
XSV_MAIN_HELP_OUTPUT: Optional[str] = None

# --- Tool Definition for litellm ---
TOOL_GET_XSV_SUBCOMMAND_HELP = {
    "type": "function",
    "function": {
        "name": "get_xsv_subcommand_help",
        "description": (
            "Fetches the help documentation for a specific xsv subcommand "
            "(e.g., 'stats', 'slice', 'search', 'count', 'headers', 'frequency', 'join', 'select', 'sort', 'split'). "
            "Use this if you need more details about a subcommand's options or usage, "
            "especially if the main `xsv -h` output is insufficient for the user's query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subcommand_name": {
                    "type": "string",
                    "description": "The name of the xsv subcommand to get help for (e.g., 'stats', 'count'). Must be a single word."
                }
            },
            "required": ["subcommand_name"]
        }
    }
}

# --- Fetching and Managing `xsv` Help Content ---

def get_xsv_main_help() -> Optional[str]:
    """
    Executes `xsv -h` to get the main help text for the xsv tool.
    Caches the result in a global variable to avoid repeated calls.

    Returns:
        The standard output (help text) as a string, or None if an error occurs.
    """
    global XSV_MAIN_HELP_OUTPUT
    if XSV_MAIN_HELP_OUTPUT is not None:
        # console.log("Returning cached `xsv -h` output.") # Can be verbose
        return XSV_MAIN_HELP_OUTPUT

    console.log("Fetching `xsv -h` output (once)...")
    try:
        process = subprocess.run(
            ["xsv", "-h"],
            capture_output=True,
            text=True,
            check=False # Handle non-zero exit codes manually
        )
        if process.returncode == 0:
            XSV_MAIN_HELP_OUTPUT = process.stdout.strip()
            console.log("`xsv -h` fetched successfully.")
            return XSV_MAIN_HELP_OUTPUT
        else:
            stderr_msg = process.stderr.strip() if process.stderr else "No stderr output."
            console.print(Panel(
                f"Error: `xsv -h` command failed with return code {process.returncode}.\n"
                f"Stderr: {stderr_msg}\n"
                "Please ensure 'xsv' is installed and in your PATH.",
                title="[bold red]xsv Main Help Error[/bold red]",
                expand=False
            ))
            return None
    except FileNotFoundError:
        console.print(Panel(
            "Error: 'xsv' command not found. Please ensure it is installed and in your system's PATH.",
            title="[bold red]xsv Not Found[/bold red]",
            expand=False
        ))
        return None
    except Exception as e:
        console.print(Panel(
            f"An unexpected error occurred while executing `xsv -h`: {e}",
            title="[bold red]Unexpected xsv Error[/bold red]",
            expand=False
        ))
        return None

def execute_get_xsv_subcommand_help(subcommand_name: str) -> str:
    """
    Executes `xsv <subcommand_name> -h` to get help for a specific subcommand.
    This function is called by the LLM when it uses the 'get_xsv_subcommand_help' tool.

    Args:
        subcommand_name: The name of the xsv subcommand (e.g., "stats", "slice").

    Returns:
        The help text for the subcommand, or an error message if it fails.
    """
    if not subcommand_name or not isinstance(subcommand_name, str) or " " in subcommand_name:
        error_msg = f"Invalid subcommand_name: '{subcommand_name}'. Must be a single word."
        console.log(error_msg, style="bold red")
        return error_msg

    console.log(f"Tool Call: Fetching help for xsv subcommand: '{subcommand_name}'...")
    try:
        process = subprocess.run(
            ["xsv", subcommand_name, "-h"],
            capture_output=True,
            text=True,
            check=False
        )
        if process.returncode == 0:
            help_text = process.stdout.strip()
            console.log(f"Help for 'xsv {subcommand_name} -h' fetched successfully for tool call.")
            return help_text if help_text else f"No help output for 'xsv {subcommand_name} -h'."
        else:
            stderr_msg = process.stderr.strip() if process.stderr else f"No stderr output. Command 'xsv {subcommand_name} -h' failed."
            console.log(f"Error fetching help for 'xsv {subcommand_name} -h' (tool call): {stderr_msg}", style="yellow")
            return f"Error: Could not get help for 'xsv {subcommand_name}'. Stderr: {stderr_msg}"
    except FileNotFoundError:
        error_msg = "Error: 'xsv' command not found. Please ensure it is installed and in your system's PATH."
        console.log(error_msg, style="bold red")
        return error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred while executing `xsv {subcommand_name} -h` (tool call): {e}"
        console.log(error_msg, style="bold red")
        return error_msg

# --- UTF-8 Conversion Function (from v1) ---
def ensure_utf8_file(original_file_path: str) -> Tuple[str, Optional[str], bool]:
    """
    Ensures the file is UTF-8 encoded. If not, converts it and saves a new .utf8.[ext] file.
    Returns the path to the file to be processed (either original or the new .utf8 version),
    the detected original encoding, and a boolean indicating if conversion occurred.
    """
    console.log(f"Ensuring UTF-8 encoding for: {original_file_path}")
    detected_encoding = None
    was_converted = False
    path_to_process = original_file_path
    ENCODING_DETECT_CHUNK_SIZE = 4096

    try:
        encodings_to_try = ['utf-8', 'utf-8-sig', 'latin-1', 'windows-1252']
        for enc in encodings_to_try:
            try:
                with open(original_file_path, 'rb') as f_test:
                    chunk = f_test.read(ENCODING_DETECT_CHUNK_SIZE)
                chunk.decode(enc)
                detected_encoding = enc
                console.log(f"Detected encoding for '{original_file_path}' as: {detected_encoding}")
                break
            except UnicodeDecodeError:
                continue
            except FileNotFoundError:
                 console.print(Panel(f"Error: Input file not found at '{original_file_path}' during encoding check.", title="[bold red]File Not Found[/bold red]", expand=False))
                 return original_file_path, None, False
        
        if detected_encoding is None:
            console.log(f"Could not determine encoding for '{original_file_path}'. Assuming UTF-8 or binary.", style="yellow")
            return original_file_path, None, False

        if detected_encoding.lower() not in ['utf-8', 'utf-8-sig']:
            base, ext = os.path.splitext(original_file_path)
            new_utf8_file_path = f"{base}.utf8{ext}"
            console.log(f"Converting '{original_file_path}' (from {detected_encoding}) to UTF-8 at '{new_utf8_file_path}'")
            with open(original_file_path, 'r', encoding=detected_encoding, errors='replace') as f_in, \
                 open(new_utf8_file_path, 'w', encoding='utf-8') as f_out:
                for line in f_in:
                    f_out.write(line)
            path_to_process = new_utf8_file_path
            was_converted = True
            console.log(f"Conversion successful. Processing will use: '{path_to_process}'")
        else:
            console.log(f"File '{original_file_path}' is already {detected_encoding}. No conversion needed.")
    except FileNotFoundError:
        console.print(Panel(f"Error: Input file not found at '{original_file_path}'", title="[bold red]File Not Found[/bold red]", expand=False))
        return original_file_path, None, False
    except Exception as e:
        console.log(f"An unexpected error occurred during encoding check/conversion: {e}", style="bold red")
        return original_file_path, detected_encoding, False
    return path_to_process, detected_encoding, was_converted

# --- Delimiter Detection Function (from v1, simplified) ---
def detect_delimiter(file_path: str, num_lines_to_sample: int = 5, default_delimiter: str = ',') -> str:
    """
    Detects the delimiter of a UTF-8 encoded CSV/TSV file by sniffing a sample of its content.
    Assumes file_path is already UTF-8 encoded.
    """
    console.log(f"Attempting to detect delimiter for UTF-8 file: {file_path}")
    try:
        with open(file_path, 'r', newline='', encoding='utf-8') as f:
            sample_lines = "".join([f.readline() for _ in range(num_lines_to_sample)])
        if not sample_lines:
            console.log(f"File '{file_path}' is empty. Using default delimiter '{default_delimiter}'.", style="yellow")
            return default_delimiter
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample_lines, delimiters=',;\t|')
        detected_delimiter_char = dialect.delimiter
        console.log(f"Detected delimiter: '{repr(detected_delimiter_char)}' for '{file_path}'", style="green")
        return detected_delimiter_char
    except FileNotFoundError:
        console.log(f"File not found: '{file_path}'. Using default: '{default_delimiter}'.", style="bold red")
        return default_delimiter
    except csv.Error:
        console.log(f"Sniffer could not detect delimiter for '{file_path}'. Using default: '{default_delimiter}'.", style="yellow")
        return default_delimiter
    except Exception as e:
        console.log(f"Error during delimiter detection for '{file_path}': {e}. Using default: '{default_delimiter}'.", style="bold red")
        return default_delimiter

# --- XSV Command Execution (from v1) ---
def execute_xsv_command(xsv_command_str: str) -> Tuple[bool, str, str]:
    """Executes a given xsv command string using subprocess."""
    console.log(f"Executing xsv command: '{xsv_command_str}'")
    try:
        process = subprocess.run(
            xsv_command_str, shell=True, capture_output=True, text=True, check=False
        )
        stdout_str = process.stdout.strip() if process.stdout else ""
        stderr_str = process.stderr.strip() if process.stderr else ""

        if process.returncode == 0 and stdout_str and len(stdout_str) > XSV_OUTPUT_MAX_CHARS:
            cutoff_point = XSV_OUTPUT_MAX_CHARS - len(XSV_TRUNCATION_MESSAGE)
            if cutoff_point < 0: # Should not happen with reasonable XSV_OUTPUT_MAX_CHARS
                cutoff_point = 0
            stdout_str = stdout_str[:cutoff_point] + XSV_TRUNCATION_MESSAGE
            console.log(f"xsv command output truncated to {XSV_OUTPUT_MAX_CHARS} chars.")

        if process.returncode != 0:
            console.log(f"xsv command failed (code {process.returncode}). Stderr: {stderr_str or '(empty)'}")
            return False, stdout_str, stderr_str
        console.log("xsv command executed successfully.")
        return True, stdout_str, stderr_str
    except FileNotFoundError:
        stderr_str = "Error: 'xsv' command not found. Ensure it's installed and in PATH."
        console.log(stderr_str, style="bold red")
        return False, "", stderr_str
    except Exception as e:
        stderr_str = f"Unexpected error executing xsv command '{xsv_command_str}': {type(e).__name__}: {e}"
        console.log(stderr_str, style="bold red")
        return False, "", stderr_str

# --- Main Agent Logic ---
def run_xsv_analyzer_agent_v2(
    user_query: str,
    csv_file_path: str,
    model_name: str,
    output_file_path: Optional[str] = None,
    user_specified_delimiter: Optional[str] = None
):
    """
    Main logic for the XSV Analyzer Agent v2.
    """
    global TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS

    console.rule("[bold blue]XSV Analyzer Agent v2 Starting[/bold blue]")

    # 1. Get main xsv help (cached)
    main_xsv_help = get_xsv_main_help()
    if not main_xsv_help:
        console.print("[bold red]Fatal: Could not retrieve main xsv help. Agent cannot continue.[/bold red]")
        return

    # 2. Ensure file is UTF-8
    processed_file_path, original_encoding, was_converted = ensure_utf8_file(csv_file_path)
    if not os.path.exists(processed_file_path): 
        console.print(f"[bold red]Fatal: Input file '{processed_file_path}' not found or accessible. Agent cannot continue.[/bold red]")
        return

    # 3. Detect delimiter
    if user_specified_delimiter:
        # Handle escaped delimiters like \t
        actual_delimiter = bytes(user_specified_delimiter, "utf-8").decode("unicode_escape")
        console.log(f"User specified delimiter: '{repr(actual_delimiter)}' (raw: '{user_specified_delimiter}')")
    else:
        actual_delimiter = detect_delimiter(processed_file_path)
    
    console.log(f"Using delimiter: '{repr(actual_delimiter)}' for file '{processed_file_path}'")

    # 4. Construct System Prompt
    system_prompt = textwrap.dedent(f"""
    You are an expert in using the 'xsv' command-line tool for analyzing CSV and other delimiter-separated value files.
    Your primary goal is to translate a user's natural language query about a file into a single, correct, and efficient 'xsv' command.

    Key Information:
    - User's target file: '{os.path.basename(processed_file_path)}' (Full path for command: '{processed_file_path}')
    - Pre-detected delimiter for this file: '{repr(actual_delimiter)}' (e.g., '\\t' for tab).
      You MUST use this delimiter in your 'xsv' command by including the `-d "{actual_delimiter}"` option
      IF AND ONLY IF the detected delimiter is NOT a comma (',').
      If the delimiter is a comma, `xsv` uses it by default, so you don't need `-d ','`.
      For example, if detected_delimiter is a tab character ('\\t'), use `xsv ... -d "\\t" ...`.
      If the user's query *explicitly* specifies a different delimiter, prioritize that.

    Tool Available:
    - `get_xsv_subcommand_help`: Use this tool if you need detailed help for a specific xsv subcommand
      (e.g., 'stats', 'slice', 'search') to understand its options better.
      The main `xsv -h` output below provides an overview, but this tool gives specifics.

    Instructions:
    1. Analyze the user's query, the file context, and the delimiter.
    2. If the main `xsv -h` (provided below) is not enough, use the `get_xsv_subcommand_help` tool to get more details.
    3. Once you have sufficient information, construct the complete 'xsv' command string.
    4. The command MUST include the actual file path: '{processed_file_path}'. Do not use placeholders like 'data.csv'.
    5. Respond ONLY with the raw 'xsv' command string when you are ready to provide it. No explanations or other text.
    6. If the query is ambiguous or cannot be translated into a single 'xsv' command even after using tools,
       respond with a brief message starting with "ERROR:" explaining the issue.
    7. IMPORTANT: The output from any executed 'xsv' command will be truncated if it exceeds {XSV_OUTPUT_MAX_CHARS} characters.
       When truncated, the output will end with "{XSV_TRUNCATION_MESSAGE}".
       Be mindful of this when constructing commands, especially for operations that might produce very large outputs
       (e.g., viewing entire large files). Use the `get_xsv_subcommand_help` tool to explore commands or options
       that might provide more summarized or targeted information if a full dump is likely to be truncated.
 
    Main `xsv -h` Output:
    ---
    {main_xsv_help}
    ---
    """).strip()

    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    
    initial_user_content = (
        f"User query: \"{user_query}\"\n"
        f"File to analyze: '{processed_file_path}'\n"
        f"Effective delimiter to use: '{repr(actual_delimiter)}'"
    )
    messages.append({"role": "user", "content": initial_user_content})

    final_xsv_command = None

    # 5. Main Interaction Loop with litellm
    for turn in range(MAX_INTERACTION_TURNS):
        console.rule(f"[bold cyan]LLM Interaction Turn {turn + 1}/{MAX_INTERACTION_TURNS}[/bold cyan]")
        # console.print(f"Sending messages to LLM ({model_name}):") # Can be verbose
        # for i, msg in enumerate(messages):
        #     # (Display logic omitted for brevity, was present in previous step)

        try:
            response = litellm.completion(
                model=model_name,
                messages=messages,
                tools=[TOOL_GET_XSV_SUBCOMMAND_HELP],
                tool_choice="auto", 
                max_tokens=300, 
                temperature=0.1 
            )
            
            current_input_tokens = response.usage.prompt_tokens or 0
            current_output_tokens = response.usage.completion_tokens or 0
            TOTAL_INPUT_TOKENS += current_input_tokens
            TOTAL_OUTPUT_TOKENS += current_output_tokens
            console.log(f"LLM call successful. Input tokens: {current_input_tokens}, Output tokens: {current_output_tokens}")

            response_message = response.choices[0].message
            messages.append(response_message.model_dump(exclude_none=True)) 

            if response_message.tool_calls:
                console.log("LLM requested tool call(s):")
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args_str = tool_call.function.arguments
                    console.log(f"  Tool: {function_name}, Args: {function_args_str}")

                    if function_name == "get_xsv_subcommand_help":
                        try:
                            args = json.loads(function_args_str)
                            subcommand_name = args.get("subcommand_name")
                            if subcommand_name:
                                tool_response_content = execute_get_xsv_subcommand_help(subcommand_name)
                            else:
                                tool_response_content = "Error: 'subcommand_name' not provided in tool call arguments."
                        except json.JSONDecodeError:
                            tool_response_content = f"Error: Invalid JSON in tool call arguments: {function_args_str}"
                        
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": tool_response_content,
                        })
                    else: # Unknown tool
                        messages.append({
                            "tool_call_id": tool_call.id, "role": "tool", "name": function_name,
                            "content": f"Error: Tool '{function_name}' is not available.",
                        })
                continue 
            
            final_content = response_message.content
            if isinstance(final_content, str):
                final_content = final_content.strip()
                if final_content.startswith("ERROR:"):
                    console.print(Panel(final_content, title="[bold red]LLM Error[/bold red]", expand=False))
                    return 
                elif "xsv" in final_content and processed_file_path in final_content: 
                    final_xsv_command = final_content
                    console.log(f"LLM provided final xsv command: '{final_xsv_command}'")
                    break 
                else:
                    console.log(f"LLM response not a command/error: '{final_content}'. Continuing.", style="yellow")
            else:
                console.log("LLM response content not string or empty.", style="yellow")

        except litellm.exceptions.APIError as e:
            console.print(Panel(f"LiteLLM API Error (Turn {turn + 1}): {e}", title="[bold red]LiteLLM API Error[/bold red]", expand=False))
            break
        except Exception as e:
            console.print(Panel(f"Unexpected LLM interaction error (Turn {turn + 1}): {e}", title="[bold red]LLM Interaction Error[/bold red]", expand=False))
            break 

    if not final_xsv_command:
        console.print(Panel("LLM did not provide a final xsv command after all turns or due to an error.", title="[bold orange]Agent Halted[/bold orange]", expand=False))
        return

    console.rule("[bold blue]Executing Final XSV Command[/bold blue]")
    success, stdout, stderr = execute_xsv_command(final_xsv_command)

    if success:
        console.print(Panel(stdout if stdout else "[No output]", title="[bold green]XSV Output[/bold green]", expand=True, border_style="green"))
        if output_file_path:
            try:
                with open(output_file_path, 'w', encoding='utf-8') as f: f.write(stdout)
                console.print(f"\n[green]Output saved to: {output_file_path}[/green]")
            except Exception as e:
                console.print(f"\n[bold red]Error saving to '{output_file_path}': {e}[/bold red]")
    else:
        console.print(Panel(stderr if stderr else "[No error message]", title="[bold red]XSV Error[/bold red]", expand=True, border_style="red"))
        if stdout: console.print(Panel(stdout, title="[bold yellow]XSV Output (despite error)[/bold yellow]", expand=True, border_style="yellow"))

    display_token_usage()
    console.rule("[bold blue]XSV Analyzer Agent v2 Finished[/bold blue]")

def display_token_usage():
    """Displays the total token usage for the session."""
    if TOTAL_INPUT_TOKENS > 0 or TOTAL_OUTPUT_TOKENS > 0:
        console.print("\n--- Token Usage ---")
        console.print(f"Total Input Tokens: {TOTAL_INPUT_TOKENS}")
        console.print(f"Total Output Tokens: {TOTAL_OUTPUT_TOKENS}")
        console.print(f"Estimated Cost: Not calculated in this version.") # Placeholder
        console.print("-------------------")

def main():
    """Main function to parse arguments and run the agent."""
    parser = argparse.ArgumentParser(
        description="XSV Analyzer Agent v2: Uses an LLM to translate natural language queries to xsv commands.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "user_query",
        type=str,
        help="The natural language query for xsv (e.g., \"show first 10 rows\", \"count unique values in 'city' column\")."
    )
    parser.add_argument(
        "-f", "--file",
        required=True,
        type=str,
        dest="csv_file_path",
        help="Path to the CSV/TSV file to analyze."
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default=DEFAULT_MODEL_LITELLM,
        dest="model_name",
        help=f"The litellm-compatible model name to use (e.g., gpt-4o-mini, claude-3-haiku-20240307). Default: {DEFAULT_MODEL_LITELLM}"
    )
    parser.add_argument(
        "-o", "--output-file",
        type=str,
        dest="output_file_path",
        help="Optional: Path to save the stdout of the successful xsv command."
    )
    parser.add_argument(
        "-d", "--delimiter",
        type=str,
        dest="user_specified_delimiter",
        help="Optional: Specify the delimiter character (e.g., '\\t' for tab, ';' for semicolon). Overrides auto-detection."
    )
    parser.add_argument(
        "--debug-litellm",
        action="store_true",
        help="Enable litellm debug mode for verbose output."
    )

    args = parser.parse_args()

    if args.debug_litellm:
        litellm.set_verbose = True
        console.log("LiteLLM verbose mode enabled.")

    # Check for API keys (litellm typically handles this, but good to remind user)
    # For gpt-4o-mini, OPENAI_API_KEY is primary.
    if "gpt" in args.model_name.lower() and not os.getenv("OPENAI_API_KEY"):
        console.print("[bold yellow]Warning: OPENAI_API_KEY environment variable is not set. OpenAI models may fail.[/bold yellow]")
    # Add checks for other providers if their models are commonly used.

    run_xsv_analyzer_agent_v2(
        user_query=args.user_query,
        csv_file_path=args.csv_file_path,
        model_name=args.model_name,
        output_file_path=args.output_file_path,
        user_specified_delimiter=args.user_specified_delimiter
    )

if __name__ == '__main__':
    main()
    # Basic test of run_xsv_analyzer_agent_v2 (requires OPENAI_API_KEY and a test CSV)
    # Create a dummy CSV for testing if it doesn't exist for quick manual tests
    # dummy_csv_path = "dummy_test.csv"
    # if not os.path.exists(dummy_csv_path):
    #     with open(dummy_csv_path, "w", newline="") as f:
    #         writer = csv.writer(f)
    #         writer.writerow(["id", "name", "value"])
    #         writer.writerow([1, "alpha", 100])
    #         writer.writerow([2, "beta", 200])
    #         writer.writerow([3, "gamma", 150])
    #     console.print(f"Created '{dummy_csv_path}' for testing.")

    # Example of how to run it programmatically (commented out by default)
    # if os.getenv("OPENAI_API_KEY") and os.path.exists(dummy_csv_path):
    #      console.print(f"\n[bold magenta]Attempting a programmatic test run with '{dummy_csv_path}'...[/bold magenta]")
    #      run_xsv_analyzer_agent_v2(
    #          user_query="show the first 2 rows",
    #          csv_file_path=dummy_csv_path,
    #          model_name=DEFAULT_MODEL_LITELLM
    #      )
    #      run_xsv_analyzer_agent_v2(
    #          user_query="what are the headers?",
    #          csv_file_path=dummy_csv_path,
    #          model_name=DEFAULT_MODEL_LITELLM
    #      )
    # else:
    #      console.print("\n[yellow]Skipping programmatic test run: OPENAI_API_KEY not set or dummy_test.csv missing.[/yellow]")