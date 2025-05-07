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
an appropriate 'xsv' command, executes it, and provides a synthesized answer.

Based on the plans:
- ai_docs/plans/PLAN_sfa_xsv_analyzer_v2.md
- ai_docs/plans/PLAN_sfa_xsv_analyzer_v2_answer_synthesis.md

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
from rich import print as rprint # For pretty-printing complex objects

# --- Initialize Rich Console ---
console = Console()

# --- Constants ---
DEFAULT_MODEL_LITELLM = "gpt-4o-mini" # Target for initial development
DEFAULT_XSV_OUTPUT_TRUNCATION_CHARS = 4000 # Default if AI doesn't specify
MAX_XSV_OUTPUT_CHARS_LIMIT = 10000     # Absolute maximum truncation limit
XSV_TRUNCATION_MESSAGE = "... [Output truncated]"
 
# API call settings (can be refined or use litellm's defaults)
API_MAX_RETRIES = 3 # For litellm calls, litellm has its own retry logic too.
API_RETRY_WAIT = 5  # seconds
DEFAULT_MAX_INTERACTION_TURNS = 15 # Default max LLM interactions (tool calls) to prevent loops

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
def execute_xsv_command(xsv_command_str: str, requested_truncation_length: Optional[int] = None) -> Tuple[bool, str, str, Optional[int]]:
    """
    Executes a given xsv command string using subprocess.
    Truncates output if it exceeds the determined truncation length.

    Args:
        xsv_command_str: The xsv command to execute.
        requested_truncation_length: The desired truncation length suggested by the AI.

    Returns:
        A tuple: (success_flag, stdout_str, stderr_str, actual_truncation_limit_applied_if_any).
        actual_truncation_limit_applied_if_any is the character limit used for truncation if truncation occurred, else None.
    """
    console.log(f"Executing xsv command: '{xsv_command_str}'")

    # Determine actual truncation character limit
    if requested_truncation_length is not None:
        # Use AI's requested length, but cap it at the absolute max and ensure it's positive
        effective_truncation_chars = min(max(requested_truncation_length, 100), MAX_XSV_OUTPUT_CHARS_LIMIT) # Ensure at least 100 chars if specified
        console.log(f"AI requested truncation at {requested_truncation_length} chars. Effective limit: {effective_truncation_chars} (Max: {MAX_XSV_OUTPUT_CHARS_LIMIT})")
    else:
        effective_truncation_chars = DEFAULT_XSV_OUTPUT_TRUNCATION_CHARS
        console.log(f"No specific truncation length requested by AI. Using default: {effective_truncation_chars} chars.")

    actual_truncation_applied_at: Optional[int] = None

    try:
        process = subprocess.run(
            xsv_command_str, shell=True, capture_output=True, text=True, check=False
        )
        stdout_str = process.stdout.strip() if process.stdout else ""
        stderr_str = process.stderr.strip() if process.stderr else ""

        if process.returncode == 0 and stdout_str and len(stdout_str) > effective_truncation_chars:
            cutoff_point = effective_truncation_chars - len(XSV_TRUNCATION_MESSAGE)
            if cutoff_point < 0: # Should not happen with reasonable limits
                cutoff_point = 0
            stdout_str = stdout_str[:cutoff_point] + XSV_TRUNCATION_MESSAGE
            actual_truncation_applied_at = effective_truncation_chars
            console.log(f"xsv command output truncated to {effective_truncation_chars} chars.")

        if process.returncode != 0:
            console.log(f"xsv command failed (code {process.returncode}). Stderr: {stderr_str or '(empty)'}")
            return False, stdout_str, stderr_str, actual_truncation_applied_at # Still return stdout in case it has partial info
        
        console.log("xsv command executed successfully.")
        return True, stdout_str, stderr_str, actual_truncation_applied_at
    except FileNotFoundError:
        stderr_str = "Error: 'xsv' command not found. Ensure it's installed and in PATH."
        console.log(stderr_str, style="bold red")
        return False, "", stderr_str, None
    except Exception as e:
        stderr_str = f"Unexpected error executing xsv command '{xsv_command_str}': {type(e).__name__}: {e}"
        console.log(stderr_str, style="bold red")
        return False, "", stderr_str, None

# --- Answer Synthesis Function ---
def synthesize_answer_from_xsv_output(
    user_query: str,
    xsv_output_data: str,
    model_name: str,
    original_file_name: str,
    actual_truncation_limit: Optional[int] # New parameter
) -> Tuple[Optional[str], int, int]:
    """
    Uses an LLM to synthesize a direct, human-readable answer to the user's query
    based on the raw output from the xsv command.
    
    Args:
        user_query: The original natural language question from the user.
        xsv_output_data: The raw string output from the executed xsv command.
        model_name: The LiteLLM model identifier (e.g., "gpt-4o-mini").
        original_file_name: The base name of the CSV file being queried (for context).
        actual_truncation_limit: The character limit at which truncation occurred, if any.
        
    Returns:
        A tuple containing:
        - The synthesized answer as a string, or None if synthesis failed.
        - The number of input tokens used for this LLM call.
        - The number of output tokens used for this LLM call.
    """
    console.log(f"Synthesizing answer from xsv output using model: {model_name}")
    
    if not xsv_output_data or xsv_output_data.strip() == "":
        console.log("XSV output is empty, returning a simple 'no data' response.")
        return "No data was returned by the xsv command. This likely means no matching data was found.", 0, 0
    
    truncation_note = ""
    if actual_truncation_limit is not None and XSV_TRUNCATION_MESSAGE in xsv_output_data:
        truncation_note = f"\nNote that the xsv output was truncated at {actual_truncation_limit} characters."
    
    system_prompt = textwrap.dedent(f"""
    You are an analytical assistant that provides direct, concise answers to questions about CSV data.
    
    Your task is to analyze the output from an 'xsv' command and provide a clear, direct answer to the user's original query.
    
    Guidelines:
    1. Focus ONLY on the data provided in the xsv output - do not make assumptions beyond what's shown.
    2. Provide a direct answer to the user's query based solely on the xsv output.
    3. If the query was "is X in the list?" and rows containing X are present in the output, confirm this clearly.
    4. If the query was "is X in the list?" and no rows containing X are in the output, state this clearly.
    5. If the xsv output appears to be truncated (as indicated by "{XSV_TRUNCATION_MESSAGE}"), acknowledge this limitation in your answer, mentioning the character limit if provided.
    6. Keep your answer concise but complete - typically 1-3 sentences is sufficient.
    7. Do not include the raw xsv output in your answer.
    8. Do not explain the xsv command that was used.
    
    Original user query: "{user_query}"
    CSV file being analyzed: "{original_file_name}"
    {truncation_note}
    """).strip()
    
    try:
        # Make a single LLM call for answer synthesis (no tools needed)
        response = litellm.completion(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"XSV command output:\n\n{xsv_output_data}"}
            ],
            max_tokens=300,
            temperature=0.1
        )
        
        # Extract answer and token usage
        synthesized_answer = response.choices[0].message.content.strip()
        input_tokens = response.usage.prompt_tokens or 0
        output_tokens = response.usage.completion_tokens or 0
        
        console.log(f"Answer synthesis successful. Input tokens: {input_tokens}, Output tokens: {output_tokens}")
        return synthesized_answer, input_tokens, output_tokens
        
    except litellm.exceptions.APIError as e:
        console.print(Panel(f"LiteLLM API Error during answer synthesis: {e}",
                           title="[bold red]Answer Synthesis Error[/bold red]",
                           expand=False))
        return None, 0, 0
    except Exception as e:
        console.print(Panel(f"Unexpected error during answer synthesis: {e}",
                           title="[bold red]Answer Synthesis Error[/bold red]",
                           expand=False))
        return None, 0, 0

# --- Main Agent Logic ---
def run_xsv_analyzer_agent_v2(
    user_query: str,
    csv_file_path: str,
    model_name: str,
    output_file_path: Optional[str] = None,
    user_specified_delimiter: Optional[str] = None,
    max_interaction_turns: int = DEFAULT_MAX_INTERACTION_TURNS
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

    Output Truncation:
    - The output from any executed 'xsv' command might be truncated.
    - The absolute maximum output length is {MAX_XSV_OUTPUT_CHARS_LIMIT} characters.
    - The default truncation length is {DEFAULT_XSV_OUTPUT_TRUNCATION_CHARS} characters.
    - When truncated, the output will end with "{XSV_TRUNCATION_MESSAGE}".
    - You can suggest a 'preferred_output_truncation_length' (integer) in your JSON response if you believe a specific
      length (between 100 and {MAX_XSV_OUTPUT_CHARS_LIMIT}) is more appropriate for the command you are generating.
      This is useful if you anticipate very long output and want to control it, or if you need slightly more than the default.

    Instructions:
    1. Analyze the user's query, the file context, and the delimiter.
    2. If the main `xsv -h` (provided below) is not enough, use the `get_xsv_subcommand_help` tool to get more details.
    3. Once you have sufficient information, construct your response.
    4. Your final response (when not using a tool) MUST be a JSON object containing:
       - "xsv_command": (string) The complete 'xsv' command string. This command MUST include the actual file path: '{processed_file_path}'.
       - "preferred_output_truncation_length": (integer, optional) Your suggested character limit for the output of this command.
         If omitted, {DEFAULT_XSV_OUTPUT_TRUNCATION_CHARS} will be used. Must be between 100 and {MAX_XSV_OUTPUT_CHARS_LIMIT}.
    5. If the query is ambiguous or cannot be translated into a single 'xsv' command even after using tools,
       respond with a JSON object: {{"error": "Your explanation here"}}.
    
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

    final_xsv_command_str = None
    preferred_truncation: Optional[int] = None # Variable to store AI's preference

    # 5. Main Interaction Loop with litellm
    for turn in range(max_interaction_turns):
        console.rule(f"[bold cyan]LLM Interaction Turn {turn + 1}/{max_interaction_turns}[/bold cyan]")
        # console.print(f"Sending messages to LLM ({model_name}):") # Can be verbose
        # for i, msg in enumerate(messages):
        #     # (Display logic omitted for brevity, was present in previous step)

        try:
            # --- LOG 1: MESSAGES TO LLM ---
            console.log("[bold yellow] --- MESSAGES TO LLM --- [/bold yellow]")
            try:
                console.log(json.dumps(messages, indent=2, ensure_ascii=False))
            except TypeError:
                rprint(messages)
            console.log("[bold yellow] ----------------------- [/bold yellow]")
            # --- END LOG 1 ---

            response = litellm.completion(
                model=model_name,
                messages=messages,
                tools=[TOOL_GET_XSV_SUBCOMMAND_HELP],
                tool_choice="auto", 
                max_tokens=400, # Increased slightly for JSON
                temperature=0.1
            )
            
            current_input_tokens = response.usage.prompt_tokens or 0
            current_output_tokens = response.usage.completion_tokens or 0
            TOTAL_INPUT_TOKENS += current_input_tokens
            TOTAL_OUTPUT_TOKENS += current_output_tokens
            console.log(f"LLM call successful. Input tokens: {current_input_tokens}, Output tokens: {current_output_tokens}")

            response_message = response.choices[0].message

            # --- LOG 2: RESPONSE FROM LLM ---
            console.log("[bold yellow] --- RESPONSE FROM LLM --- [/bold yellow]")
            # Log the raw content string for easier debugging of JSON issues
            raw_content_for_log = response_message.content if response_message.content else ""
            # Use model_dump for the entire message object if it's a Pydantic model, otherwise handle dict
            loggable_response_message = response_message.model_dump(exclude_none=True) if hasattr(response_message, 'model_dump') else response_message
            
            # Ensure content is part of the loggable structure if it was a simple string before
            if isinstance(loggable_response_message, dict) and 'content' not in loggable_response_message and raw_content_for_log:
                 loggable_response_message['content'] = raw_content_for_log

            try:
                console.log(json.dumps(loggable_response_message, indent=2, ensure_ascii=False))
            except TypeError:
                rprint(loggable_response_message)
            console.log("[bold yellow] ------------------------- [/bold yellow]")
            # --- END LOG 2 ---

            messages.append(loggable_response_message)

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
                        except Exception as e: # Catch more general errors during tool execution
                            tool_response_content = f"Error executing tool '{function_name}': {e}"
                        
                        messages.append({
                            "tool_call_id": tool_call.id, "role": "tool",
                            "name": function_name, "content": tool_response_content,
                        })
                        # --- LOG 3: TOOL RESPONSE ---
                        console.log("[bold green] --- TOOL RESPONSE CONTENT --- [/bold green]")
                        console.log(messages[-1]) # Log the appended tool message
                        console.log("[bold green] --------------------------- [/bold green]")
                        # --- END LOG 3 ---
                    else:
                        messages.append({
                            "tool_call_id": tool_call.id, "role": "tool", "name": function_name,
                            "content": f"Error: Tool '{function_name}' is not available.",
                        })
                continue
            
            # No tool calls, expect JSON response with xsv_command or error
            llm_content_str = response_message.content
            if not llm_content_str or not isinstance(llm_content_str, str):
                console.print(Panel("LLM provided non-string or empty content when command was expected.", title="[bold red]LLM Response Error[/bold red]", expand=False))
                messages.append({"role": "user", "content": "Your response content was not a string or was empty. Please provide the xsv command as a JSON object or use a tool."})
                continue

            try:
                parsed_llm_response = json.loads(llm_content_str)
                
                if "error" in parsed_llm_response:
                    error_message = parsed_llm_response["error"]
                    console.print(Panel(f"LLM indicated an error: {error_message}", title="[bold yellow]LLM Reported Issue[/bold yellow]", expand=False))
                    console.rule("[bold red]Final Agent Output[/bold red]")
                    console.print(f"Could not generate xsv command. Reason: {error_message}")
                    return

                if "xsv_command" in parsed_llm_response:
                    final_xsv_command_str = parsed_llm_response["xsv_command"]
                    if not isinstance(final_xsv_command_str, str) or not final_xsv_command_str.strip().startswith("xsv"):
                        raise ValueError("LLM provided an invalid 'xsv_command' format or content (must be string starting with 'xsv').")
                    
                    final_xsv_command_str = final_xsv_command_str.strip() # Ensure it's stripped
                    
                    preferred_truncation = parsed_llm_response.get("preferred_output_truncation_length")
                    if preferred_truncation is not None:
                        if not isinstance(preferred_truncation, int):
                            console.log(f"LLM provided non-integer preferred_output_truncation_length: {preferred_truncation}. Ignoring.", style="yellow")
                            preferred_truncation = None
                        elif not (100 <= preferred_truncation <= MAX_XSV_OUTPUT_CHARS_LIMIT):
                             console.log(f"LLM provided out-of-bounds preferred_output_truncation_length: {preferred_truncation}. Will be clamped by execute_xsv_command.", style="yellow")
                        else:
                            console.log(f"LLM suggested preferred_output_truncation_length: {preferred_truncation}")
                    
                    console.log(f"LLM provided final xsv command: '{final_xsv_command_str}'")
                    break # Exit loop, command received
                else:
                    raise ValueError("LLM JSON response missing 'xsv_command' or 'error' key.")

            except json.JSONDecodeError:
                console.print(Panel(
                    f"LLM response was not valid JSON. Content:\n{llm_content_str}",
                    title="[bold red]LLM Response Format Error[/bold red]", expand=False
                ))
                messages.append({"role": "user", "content": "Your response was not in the expected JSON format. Please provide the xsv command as a JSON object with 'xsv_command' and optionally 'preferred_output_truncation_length', or an 'error' field."})
                continue

            except ValueError as ve:
                console.print(Panel(f"Error processing LLM JSON response: {ve}\nContent: {llm_content_str}", title="[bold red]LLM Response Error[/bold red]", expand=False))
                messages.append({"role": "user", "content": f"There was an issue with your JSON response: {ve}. Please correct it."})
                continue
        
        except litellm.exceptions.APIError as e:
            console.print(Panel(f"LiteLLM API Error (Turn {turn + 1}): {e}", title="[bold red]API Error[/bold red]", expand=False))
            if turn < API_MAX_RETRIES -1 :
                 console.log(f"Retrying LLM call in {API_RETRY_WAIT}s... (Attempt {turn + 2}/{API_MAX_RETRIES})")
                 time.sleep(API_RETRY_WAIT)
                 if messages and messages[-1].get("role") == "assistant": messages.pop()
                 continue
            console.print("API retries exhausted.")
            return
        except Exception as e:
            console.print(Panel(f"An unexpected error occurred during LLM interaction (Turn {turn + 1}): {e}", title="[bold red]Unexpected Error[/bold red]", expand=False))
            return # Exit on other unexpected errors

    if not final_xsv_command_str:
        console.print(Panel("Max interaction turns reached or loop exited, but no xsv command was generated.", title="[bold red]Interaction Limit Reached or Error[/bold red]", expand=False))
        if messages: # Log last few messages if any exist
            console.log("Last few messages in conversation:")
            for msg in messages[-5:]: rprint(msg)
        return

    # 6. Execute the final xsv command
    console.rule("[bold green]Executing Final XSV Command[/bold green]")
    console.print(f"Command: [cyan]{final_xsv_command_str}[/cyan]")
    if preferred_truncation is not None:
            clamped_truncation = min(max(preferred_truncation, 100), MAX_XSV_OUTPUT_CHARS_LIMIT)
            console.print(f"Attempting to use AI-suggested truncation (clamped if necessary): {clamped_truncation} chars.")

    success, stdout_data, stderr_data, actual_truncation_applied = execute_xsv_command(final_xsv_command_str, preferred_truncation)
    
    if stdout_data: # Always show stdout if present
        console.print(Panel(Syntax(stdout_data, "bash", theme="monokai", line_numbers=True, word_wrap=True), title="[bold green]xsv stdout[/bold green]", expand=False, border_style="green"))
    
    if stderr_data: # Show stderr if present and either command failed or stderr has content
        if not success or stderr_data.strip():
             console.print(Panel(stderr_data, title="[bold red]xsv stderr[/bold red]", expand=False, border_style="red"))
    
    if not success and not stdout_data and not (stderr_data and stderr_data.strip()): # If failed, no stdout, no meaningful stderr
         console.print(Panel("xsv command failed with no output to stdout or stderr.", title="[bold red]xsv Execution Failed[/bold red]", expand=False, border_style="red"))

    # 7. Synthesize Answer
    if success:
        console.rule("[bold magenta]Synthesizing Answer[/bold magenta]")
        synthesized_answer, synth_in_tokens, synth_out_tokens = synthesize_answer_from_xsv_output(
            user_query,
            stdout_data,
            model_name,
            os.path.basename(csv_file_path), # Use processed_file_path for consistency if needed, but basename is for display
            actual_truncation_applied
        )
        TOTAL_INPUT_TOKENS += synth_in_tokens
        TOTAL_OUTPUT_TOKENS += synth_out_tokens

        if synthesized_answer:
            console.rule("[bold blue]Final Synthesized Answer[/bold blue]")
            console.print(Panel(synthesized_answer, title="Answer", expand=False))
            if output_file_path:
                try:
                    with open(output_file_path, 'w', encoding='utf-8') as f:
                        f.write(f"User Query: {user_query}\n")
                        f.write(f"XSV Command: {final_xsv_command_str}\n")
                        if preferred_truncation is not None or actual_truncation_applied is not None:
                             f.write(f"AI Suggested Truncation: {preferred_truncation if preferred_truncation is not None else 'N/A'}\n")
                             f.write(f"Actual Truncation Applied At: {actual_truncation_applied if actual_truncation_applied is not None else 'Not Truncated or Default'}\n")
                        f.write(f"\nXSV Output:\n{stdout_data}\n\n") # stdout_data already contains truncation message if applied
                        if stderr_data and stderr_data.strip(): # Only write stderr if it has content
                            f.write(f"XSV Stderr:\n{stderr_data}\n\n")
                        f.write(f"Synthesized Answer:\n{synthesized_answer}\n")
                    console.log(f"Full interaction details saved to: {output_file_path}")
                except Exception as e:
                    console.log(f"Error writing to output file '{output_file_path}': {e}", style="red")
        else: # Synthesize answer returned None or empty
            console.print("[bold yellow]Could not synthesize an answer from the xsv output.[/bold yellow]")
            if not stdout_data and not success:
                pass # Error already handled by xsv execution block
            elif not stdout_data:
                console.print("[italic]The xsv command produced no output to synthesize from.[/italic]")
                if output_file_path: # Still save what we have
                    try:
                        with open(output_file_path, 'w', encoding='utf-8') as f:
                            f.write(f"User Query: {user_query}\n")
                            f.write(f"XSV Command: {final_xsv_command_str}\n")
                            f.write("XSV Output: No output produced.\n")
                            if stderr_data and stderr_data.strip(): f.write(f"XSV Stderr:\n{stderr_data}\n")
                            f.write("Synthesized Answer: Could not be generated (no xsv output).\n")
                        console.log(f"Interaction details (no synthesis) saved to: {output_file_path}")
                    except Exception as e:
                        console.log(f"Error writing to output file '{output_file_path}': {e}", style="red")

    else: # xsv command failed
        console.print("[bold red]Skipping answer synthesis because the xsv command failed.[/bold red]")
        if output_file_path: # Save error details
            try:
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    f.write(f"User Query: {user_query}\n")
                    f.write(f"XSV Command Attempted: {final_xsv_command_str}\n")
                    f.write("XSV Command Execution Failed.\n")
                    if stdout_data: f.write(f"XSV stdout (partial/error):\n{stdout_data}\n")
                    if stderr_data: f.write(f"XSV stderr:\n{stderr_data}\n")
                console.log(f"Error details saved to: {output_file_path}")
            except Exception as e:
                console.log(f"Error writing error details to output file '{output_file_path}': {e}", style="red")

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
        "-t", "--max-turns",
        type=int,
        default=DEFAULT_MAX_INTERACTION_TURNS,
        dest="max_interaction_turns",
        help=f"Maximum number of LLM interaction turns (default: {DEFAULT_MAX_INTERACTION_TURNS})"
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
        help="Optional: Path to save the synthesized answer and/or raw output of the successful xsv command."
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
        max_interaction_turns=args.max_interaction_turns,
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