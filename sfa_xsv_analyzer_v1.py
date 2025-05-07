#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "anthropic>=0.47.1",
#   "openai>=1.0.0",
#   "google-generativeai>=0.7.0",
#   "rich>=13.7.0",
# ]
# ///
"""
Single-File Agent: XSV Analyzer (sfa_xsv_analyzer_v1.py)

Purpose:
This agent leverages the power of Large Language Models (LLMs) to analyze
CSV (and other delimiter-separated value) files using the 'xsv' command-line tool.
It takes a natural language query, translates it into an appropriate 'xsv' command,
executes the command, and returns the result.

Example CLI Usage:
  uv run sfa_xsv_analyzer_v1.py "show first 5 rows" -f data.csv -p openai
  uv run sfa_xsv_analyzer_v1.py "count unique values in 'city' column" --file data.csv --provider anthropic
  uv run sfa_xsv_analyzer_v1.py "filter rows where 'age' > 30 and select 'name', 'email'" -f users.tsv -d "\t" -p google

API Key Prerequisites:
To use this agent, you MUST set the following API keys as environment variables:
- ANTHROPIC_API_KEY: For using Anthropic's Claude models.
- OPENAI_API_KEY: For using OpenAI's GPT models.
- GOOGLE_API_KEY: For using Google's Gemini models.

Other Prerequisites:
- 'xsv' command-line tool: Must be installed and available in your system's PATH.
  Installation: https://github.com/BurntSushi/xsv#installation
"""

import os
import sys
import argparse
import subprocess
import json
import textwrap
from typing import Tuple, Optional

import time

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from anthropic import Anthropic
from openai import OpenAI
import google.generativeai as genai # Using alias for convenience

# Initialize Rich Console
console = Console()

# --- Constants ---
# Default LLM models
DEFAULT_MODEL_ANTHROPIC = "claude-3-haiku-20240307"
DEFAULT_MODEL_OPENAI = "gpt-4o-mini"
DEFAULT_MODEL_GOOGLE = "gemini-1.5-flash-latest"

# API call settings
API_MAX_RETRIES = 3
API_RETRY_WAIT = 5  # seconds

# Token tracking (global for simplicity in this SFA)
TOTAL_INPUT_TOKENS = 0
TOTAL_OUTPUT_TOKENS = 0


# --- LLM Prompt Template ---
XSV_COMMAND_GENERATION_PROMPT_TEMPLATE = """
<purpose>
You are an expert in using the 'xsv' command-line tool for analyzing CSV and other
delimiter-separated value files. Your task is to translate a user's natural language
query about a CSV file into a single, correct, and efficient 'xsv' command.
</purpose>

<instructions>
1.  Analyze the user's query and the provided CSV file path.
2.  Determine the most appropriate 'xsv' subcommand and options to fulfill the query.
3.  Construct the complete 'xsv' command string.
4.  Ensure the command is syntactically correct and includes the file path.
5.  Do NOT include any introductory or explanatory text, only the raw 'xsv' command.
6.  Do NOT include the 'uv run sfa_xsv_analyzer_v1.py' part, only the 'xsv ...' part.
7.  If the user query is ambiguous or cannot be translated into a single 'xsv' command,
    return an empty string or a brief message indicating the limitation.
8.  Assume the 'xsv' command is available in the environment.
9.  If the user specifies a delimiter other than comma, use the `-d` flag.
10. If the user asks for output formatting (e.g., JSON, pretty table), use appropriate
    xsv subcommands or combinations (e.g., `xsv search ... | xsv json`).
</instructions>

<user_query>{user_query}</user_query>

<csv_file_path>{csv_file_path}</csv_file_path>

<examples>
User Query: show first 10 rows
CSV File Path: data.csv
xsv command: xsv slice -n 1 -u 10 data.csv

User Query: count rows
CSV File Path: data.csv
xsv command: xsv count data.csv

User Query: list columns
CSV File Path: data.csv
xsv command: xsv headers data.csv

User Query: filter rows where age > 30 and select name, email
CSV File Path: users.csv
xsv command: xsv search -s age -p '^([3-9]\d|\d{{3,}})$' users.csv | xsv select name,email

User Query: find rows with "error" in any column
CSV File Path: log.tsv
xsv command: xsv search "error" log.tsv -d "\t"
</examples>

Your xsv command:
"""

# --- XSV Command Execution ---
def execute_xsv_command(xsv_command_str: str) -> Tuple[bool, str, str]:
    """
    Executes a given xsv command string using subprocess.

    Args:
        xsv_command_str: The complete xsv command to execute.

    Returns:
        A tuple containing:
            - success_status (bool): True if the command executed successfully (return code 0), False otherwise.
            - stdout (str): The standard output of the command.
            - stderr (str): The standard error of the command.
    """
    console.log(f"Executing xsv command: '{xsv_command_str}'")
    success_status = True
    stdout_str = ""
    stderr_str = ""

    try:
        # Ensure the command is passed as a string when shell=True
        process = subprocess.run(
            xsv_command_str,
            shell=True,
            capture_output=True,
            text=True,
            check=False  # We handle the return code manually
        )
        stdout_str = process.stdout.strip() if process.stdout else ""
        stderr_str = process.stderr.strip() if process.stderr else ""

        if process.returncode != 0:
            success_status = False
            console.log(f"xsv command failed with return code {process.returncode}.")
            if stderr_str:
                console.log(f"Stderr: {stderr_str}")
            else:
                console.log("Stderr: (empty)") # Explicitly state if stderr is empty
        else:
            console.log("xsv command executed successfully.")
            # Log stdout only if it's not empty, as per checklist refinement
            # if stdout_str:
            #     console.log(f"Stdout: {stdout_str}")


    except FileNotFoundError:
        success_status = False
        stderr_str = "Error: 'xsv' command not found. Please ensure it is installed and in your PATH."
        console.log(stderr_str, style="bold red")
    except Exception as e:
        success_status = False
        # It's good practice to include the type of exception and the original command
        error_type = type(e).__name__
        error_msg = str(e)
        stderr_str = (
            f"An unexpected error occurred ({error_type}) while executing "
            f"xsv command '{xsv_command_str}': {error_msg}"
        )
        console.log(stderr_str, style="bold red")

    return success_status, stdout_str, stderr_str

# --- LLM Calling Functions ---

def call_anthropic_llm(prompt: str, api_key: str, model_name: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Calls the Anthropic LLM API."""
    client = Anthropic(api_key=api_key)
    response_text = None
    input_tokens = None
    output_tokens = None

    for attempt in range(API_MAX_RETRIES):
        try:
            console.log(f"Attempt {attempt + 1}/{API_MAX_RETRIES} calling Anthropic model: {model_name}")
            message = client.messages.create(
                model=model_name,
                max_tokens=200, # Reasonable limit for an xsv command
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            response_text = message.content[0].text
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            console.log("Anthropic API call successful.")
            # console.log(f"Raw Anthropic response: {message}") # Optional: log raw response
            break # Success
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError) as e:
            console.log(f"Anthropic API error on attempt {attempt + 1}: {e}", style="bold yellow")
            if attempt < API_MAX_RETRIES - 1:
                console.log(f"Retrying in {API_RETRY_WAIT} seconds...", style="yellow")
                time.sleep(API_RETRY_WAIT)
            else:
                console.log("Max retries reached for Anthropic API.", style="bold red")
        except Exception as e:
            console.log(f"An unexpected error occurred during Anthropic API call: {e}", style="bold red")
            break # Do not retry on unexpected errors

    return response_text, input_tokens, output_tokens

def call_openai_llm(prompt: str, api_key: str, model_name: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Calls the OpenAI LLM API."""
    client = OpenAI(api_key=api_key)
    response_text = None
    input_tokens = None
    output_tokens = None

    for attempt in range(API_MAX_RETRIES):
        try:
            console.log(f"Attempt {attempt + 1}/{API_MAX_RETRIES} calling OpenAI model: {model_name}")
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200, # Reasonable limit for an xsv command
            )
            response_text = response.choices[0].message.content
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            console.log("OpenAI API call successful.")
            # console.log(f"Raw OpenAI response: {response}") # Optional: log raw response
            break # Success
        except (openai.APIConnectionError, openai.RateLimitError, openai.APIStatusError) as e:
            console.log(f"OpenAI API error on attempt {attempt + 1}: {e}", style="bold yellow")
            if attempt < API_MAX_RETRIES - 1:
                console.log(f"Retrying in {API_RETRY_WAIT} seconds...", style="yellow")
                time.sleep(API_RETRY_WAIT)
            else:
                console.log("Max retries reached for OpenAI API.", style="bold red")
        except Exception as e:
            console.log(f"An unexpected error occurred during OpenAI API call: {e}", style="bold red")
            break # Do not retry on unexpected errors

    return response_text, input_tokens, output_tokens

def call_google_llm(prompt: str, api_key: str, model_name: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Calls the Google GenAI LLM API."""
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        console.log(f"Error configuring Google GenAI: {e}", style="bold red")
        return None, None, None

    model = genai.GenerativeModel(model_name)
    response_text = None
    input_tokens = None
    output_tokens = None

    for attempt in range(API_MAX_RETRIES):
        try:
            console.log(f"Attempt {attempt + 1}/{API_MAX_RETRIES} calling Google model: {model_name}")
            # Count input tokens before the call
            try:
                input_tokens_response = model.count_tokens(prompt)
                input_tokens = input_tokens_response.total_tokens
            except Exception as e:
                console.log(f"Warning: Could not count input tokens for Google model: {e}", style="yellow")
                input_tokens = None # Indicate failure to count

            response = model.generate_content(prompt)
            response_text = response.text

            # Count output tokens after the call
            try:
                output_tokens_response = model.count_tokens(response_text)
                output_tokens = output_tokens_response.total_tokens
            except Exception as e:
                console.log(f"Warning: Could not count output tokens for Google model: {e}", style="yellow")
                output_tokens = None # Indicate failure to count

            console.log("Google GenAI API call successful.")
            # console.log(f"Raw Google response: {response}") # Optional: log raw response
            break # Success
        except Exception as e: # Catching generic Exception for broader Google API errors
            console.log(f"Google GenAI API error on attempt {attempt + 1}: {e}", style="bold yellow")
            if attempt < API_MAX_RETRIES - 1:
                console.log(f"Retrying in {API_RETRY_WAIT} seconds...", style="yellow")
                time.sleep(API_RETRY_WAIT)
            else:
                console.log("Max retries reached for Google GenAI API.", style="bold red")

    return response_text, input_tokens, output_tokens

# --- XSV Command Generation ---

def get_xsv_command_from_ai(user_query: str, csv_file_path: str, llm_provider: str, api_key: str, model_name: str) -> Optional[str]:
    """
    Generates an xsv command from a user query using an LLM.

    Args:
        user_query: The natural language query from the user.
        csv_file_path: The path to the CSV file.
        llm_provider: The LLM provider to use ('anthropic', 'openai', 'google').
        api_key: The API key for the chosen provider.
        model_name: The specific model name to use.

    Returns:
        The generated xsv command string, or None if generation failed.
    """
    global TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS

    console.log(
        f"Attempting to generate xsv command using {llm_provider}/{model_name} "
        f"for query: '{user_query}' on file: '{csv_file_path}'"
    )

    prompt = XSV_COMMAND_GENERATION_PROMPT_TEMPLATE.format(
        user_query=user_query,
        csv_file_path=csv_file_path
    )

    response_text = None
    input_tokens = None
    output_tokens = None

    if llm_provider == "anthropic":
        response_text, input_tokens, output_tokens = call_anthropic_llm(prompt, api_key, model_name)
    elif llm_provider == "openai":
        response_text, input_tokens, output_tokens = call_openai_llm(prompt, api_key, model_name)
    elif llm_provider == "google":
        response_text, input_tokens, output_tokens = call_google_llm(prompt, api_key, model_name)
    else:
        console.log(f"Unknown LLM provider: {llm_provider}", style="bold red")
        return None

    if response_text:
        # Update token counts
        if input_tokens is not None:
            TOTAL_INPUT_TOKENS += input_tokens
        if output_tokens is not None:
            TOTAL_OUTPUT_TOKENS += output_tokens

        console.log(f"Raw LLM response:\n---\n{response_text}\n---")

        # Extract and sanitize the command
        command = response_text.strip()
        # Remove markdown code block if present
        if command.startswith("```") and command.endswith("```"):
            command = command[3:-3].strip()
            # Remove language specifier if present (e.g., ```bash)
            if command.startswith("bash"):
                command = command[4:].strip()
            elif command.startswith("sh"):
                command = command[2:].strip()

        console.log(f"Extracted and sanitized command: '{command}'")
        return command
    else:
        console.log("LLM call failed or returned no text.", style="bold red")
        return None

# --- Main Agent Logic ---

def run_xsv_analyzer_agent(
    user_query: str,
    csv_file_path: str,
    llm_provider: str,
    api_key: str,
    model_name: str,
    output_file_path: Optional[str] = None
) -> Tuple[Optional[str], int, int]:
    """
    Main logic function for the XSV Analyzer Agent.

    Orchestrates the process of:
    1. Getting an xsv command from an LLM based on user query.
    2. Optionally appending output redirection if an output file is specified.
    3. Executing the xsv command.
    4. Returning the result or error, along with token counts.
    """
    global TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS

    console.log(
        f"Starting XSV Analyzer Agent for query: '{user_query}' "
        f"on file: '{csv_file_path}'"
    )

    generated_xsv_command = get_xsv_command_from_ai(
        user_query, csv_file_path, llm_provider, api_key, model_name
    )

    if not generated_xsv_command:
        console.log("Failed to generate xsv command.", style="bold red")
        return None, TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS

    console.log(f"LLM generated xsv command: '{generated_xsv_command}'")
    
    final_xsv_command = generated_xsv_command
    output_redirected_by_agent = False

    if output_file_path:
        # Check if the command already contains redirection operators
        if not (">" in generated_xsv_command or ">>" in generated_xsv_command):
            # Ensure output_file_path is quoted if it contains spaces and is not already quoted.
            if " " in output_file_path and not (
                output_file_path.startswith('"') and output_file_path.endswith('"')
            ):
                quoted_output_file_path = f'"{output_file_path}"'
            else:
                quoted_output_file_path = output_file_path
            
            final_xsv_command = f'{generated_xsv_command} > {quoted_output_file_path}'
            output_redirected_by_agent = True
            console.log(f"Appended output redirection to: {quoted_output_file_path}")
        else:
            console.log(f"Output redirection detected in LLM command. Agent will not append redirection.")


    success, stdout, stderr = execute_xsv_command(final_xsv_command)

    if not success:
        error_message = f"Error executing xsv command: {stderr}"
        console.log(error_message, style="bold red")
        console.print(Panel(stderr if stderr else "Unknown execution error", title="[bold red]xsv Execution Error[/bold red]", expand=False))
        return f"xsv execution failed: {stderr}", TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS

    console.log("xsv command executed successfully.")

    if output_file_path:
        # This condition checks if an output path was intended.
        success_message = f"Output successfully processed. Target output file: {output_file_path}"
        # Refine message if redirection was active (either by LLM or agent)
        if output_redirected_by_agent or (">" in final_xsv_command or ">>" in final_xsv_command):
             success_message = f"Output successfully written to {output_file_path}"

        console.print(Panel(success_message, title="[bold green]xsv Execution Success[/bold green]", expand=False))
        return success_message, TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS
    else:
        # Output was to stdout
        if stdout:
            # Attempt to display as CSV, fallback to plain panel
            if ("," in stdout or "\t" in stdout) and "\n" in stdout: # Simple heuristic
                 console.print(Syntax(stdout, "csv", theme="material", line_numbers=True, word_wrap=True))
            else:
                 console.print(Panel(stdout, title="[bold green]xsv Output[/bold green]", expand=True))
        else:
            no_stdout_message = "xsv command executed successfully, but produced no standard output."
            console.print(Panel(no_stdout_message, title="[bold green]xsv Execution Success[/bold green]", expand=False))
            return no_stdout_message, TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS
            
        return stdout, TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS
# --- Token Usage Display ---
def display_token_usage():
    """
    Displays the token usage for the LLM calls using a rich.Table.
    Token counts are based on global variables updated during API calls.
    Acknowledges the best-effort nature of token counts.
    """
    if TOTAL_INPUT_TOKENS > 0 or TOTAL_OUTPUT_TOKENS > 0:
        token_table = Table(
            title="LLM Token Usage",
            show_header=True,
            header_style="bold magenta",
            caption="Token counts are estimates based on API responses. Some LLMs/calls may not provide exact figures."
        )
        token_table.add_column("Metric", style="dim", width=15)
        token_table.add_column("Tokens", justify="right")
        token_table.add_row("Input Tokens", str(TOTAL_INPUT_TOKENS))
        token_table.add_row("Output Tokens", str(TOTAL_OUTPUT_TOKENS))
        token_table.add_row("Total Tokens", str(TOTAL_INPUT_TOKENS + TOTAL_OUTPUT_TOKENS))
        console.print(token_table)
    else:
        # This case might occur if token counting failed, was not supported, or no LLM calls were made.
        console.print(Panel(
            "No token usage recorded. This may occur if LLM calls were not made, "
            "token counting failed, or is not supported for all API calls.\n\n"
            "Note: Token counts are generally estimates based on API responses.",
            title="Token Usage Information",
            expand=False,
            border_style="yellow"
        ))

# --- Main Application Logic ---
def main():
    """
    Main function to orchestrate the CSV analysis process using xsv via LLM.
    Parses command-line arguments, validates inputs, retrieves API keys,
    calls the xsv analyzer agent, and displays results.
    """
    script_description = """
This agent leverages the power of Large Language Models (LLMs) to analyze
CSV (and other delimiter-separated value) files using the 'xsv' command-line tool.
It takes a natural language query, translates it into an appropriate 'xsv' command,
executes the command, and returns the result.

API Key Prerequisites:
- ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY must be set as environment variables.

Other Prerequisites:
- 'xsv' command-line tool: Must be installed and available in your system's PATH.
"""

    parser = argparse.ArgumentParser(
        description=textwrap.dedent(script_description),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "query",
        help="The natural language query for xsv to process."
    )
    parser.add_argument(
        "--csv-file", "-f",
        required=True,
        help="Path to the input CSV file."
    )
    parser.add_argument(
        "--llm-provider", "-p",
        required=True,
        choices=["anthropic", "openai", "google"],
        help="The LLM provider to use."
    )
    parser.add_argument(
        "--output-file", "-o",
        help="Optional path to save the xsv command output to a file."
    )
    parser.add_argument(
        "--model-name", "-m",
        help="Override default model for the selected provider. API keys are sourced from environment variables (e.g., ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY)."
    )

    args = parser.parse_args()

    # Validate csv_file_path
    if not os.path.exists(args.csv_file):
        console.print(Panel(f"Error: Input CSV file not found at '{args.csv_file}'", title="[bold red]File Not Found[/bold red]", expand=False))
        sys.exit(1)

    # Retrieve API key
    api_key_env_var_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY"
    }
    api_key_env_var = api_key_env_var_map[args.llm_provider]
    api_key = os.getenv(api_key_env_var)

    if not api_key:
        console.print(Panel(f"Error: {api_key_env_var} environment variable not set.", title="[bold red]API Key Error[/bold red]", expand=False))
        sys.exit(1)

    # Determine model name
    model_name_to_use = args.model_name
    if not model_name_to_use:
        if args.llm_provider == "anthropic":
            model_name_to_use = DEFAULT_MODEL_ANTHROPIC
        elif args.llm_provider == "openai":
            model_name_to_use = DEFAULT_MODEL_OPENAI
        elif args.llm_provider == "google":
            model_name_to_use = DEFAULT_MODEL_GOOGLE
    
    console.log(f"Using LLM Provider: {args.llm_provider}, Model: {model_name_to_use}")

    # Reset global token counters for this run, as main() is the entry point for a single execution.
    # This ensures that if the script is imported and functions called multiple times,
    # the main CLI execution path has its own clean token count.
    global TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS
    TOTAL_INPUT_TOKENS = 0
    TOTAL_OUTPUT_TOKENS = 0
    
    # Call run_xsv_analyzer_agent
    # The run_xsv_analyzer_agent function returns token counts, but these are already accumulated globally.
    # We pass them to display_token_usage for clarity, though display_token_usage will use the globals.
    _result_output, current_run_input_tokens, current_run_output_tokens = run_xsv_analyzer_agent(
        user_query=args.query,
        csv_file_path=args.csv_file,
        llm_provider=args.llm_provider,
        api_key=api_key,
        model_name=model_name_to_use,
        output_file_path=args.output_file
    )

    # run_xsv_analyzer_agent handles printing of its own results/errors.
    # main's responsibility is to call display_token_usage, which uses the final global counts.
    display_token_usage()

# --- Entry Point ---
if __name__ == "__main__":
    main()