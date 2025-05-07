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
import csv # Added for delimiter detection
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

# --- UTF-8 Conversion Function ---
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
    ENCODING_DETECT_CHUNK_SIZE = 4096  # Max chunk size for encoding detection

    try:
        # 1. Try to detect encoding by reading a small chunk
        encodings_to_try = ['utf-8', 'utf-8-sig', 'latin-1', 'windows-1252']
        
        for enc in encodings_to_try:
            try:
                with open(original_file_path, 'rb') as f_test: # Read as binary for chunk test
                    chunk = f_test.read(ENCODING_DETECT_CHUNK_SIZE)
                chunk.decode(enc) # Try decoding the chunk
                detected_encoding = enc
                console.log(f"Detected encoding for '{original_file_path}' as: {detected_encoding}")
                break # Found a working encoding
            except UnicodeDecodeError:
                # console.log(f"Encoding test failed for {enc} on '{original_file_path}'") # Optional: too verbose
                continue
            # FileNotFoundError should be caught by main, but good to have a check here
            except FileNotFoundError:
                 console.print(Panel(f"Error: Input file not found at '{original_file_path}' during encoding check.", title="[bold red]File Not Found[/bold red]", expand=False))
                 return original_file_path, None, False # Indicate error
        
        if detected_encoding is None:
            console.log(f"Could not determine encoding for '{original_file_path}' from common types. Assuming UTF-8 or binary.", style="yellow")
            return original_file_path, None, False # Proceed with original, might fail later

        # 2. Convert if not UTF-8 or UTF-8-SIG (UTF-8 with BOM)
        if detected_encoding.lower() not in ['utf-8', 'utf-8-sig']:
            base, ext = os.path.splitext(original_file_path)
            new_utf8_file_path = f"{base}.utf8{ext}" # Simple suffixing, e.g. data.csv -> data.utf8.csv

            console.log(f"Converting '{original_file_path}' (from {detected_encoding}) to UTF-8 at '{new_utf8_file_path}'")
            
            with open(original_file_path, 'r', encoding=detected_encoding, errors='replace') as f_in, \
                 open(new_utf8_file_path, 'w', encoding='utf-8') as f_out:
                # Read and write line by line to handle potentially large files
                for line in f_in:
                    f_out.write(line)
            
            path_to_process = new_utf8_file_path
            was_converted = True
            console.log(f"Conversion successful. Processing will use: '{path_to_process}'")
        else:
            console.log(f"File '{original_file_path}' is already {detected_encoding}. No conversion needed.")
            # path_to_process is already original_file_path

    except FileNotFoundError: # Catch if original_file_path itself is not found at the start
        console.print(Panel(f"Error: Input file not found at '{original_file_path}'", title="[bold red]File Not Found[/bold red]", expand=False))
        return original_file_path, None, False # Indicate error
    except Exception as e:
        console.log(f"An unexpected error occurred during encoding check/conversion for '{original_file_path}': {e}", style="bold red")
        return original_file_path, detected_encoding, False # Return original path, but flag that something went wrong

    return path_to_process, detected_encoding, was_converted

# --- Delimiter Detection Function (Simplified) ---
def detect_delimiter(file_path: str, num_lines_to_sample: int = 5, default_delimiter: str = ',') -> str:
    """
    Detects the delimiter of a UTF-8 encoded CSV/TSV file by sniffing a sample of its content.
    Assumes file_path is already UTF-8 encoded.
    """
    console.log(f"Attempting to detect delimiter for UTF-8 file: {file_path}")
    sample_lines = None
    try:
        # File is expected to be UTF-8 now
        with open(file_path, 'r', newline='', encoding='utf-8') as f: # Always use utf-8
            sample_lines = "".join([f.readline() for _ in range(num_lines_to_sample)])
        
        if not sample_lines:
            console.log(f"File '{file_path}' is empty or too short to sample. Using default delimiter '{default_delimiter}'.", style="yellow")
            return default_delimiter

        console.log(f"Sample for sniffing ({num_lines_to_sample} lines) from '{file_path}':\n---\n{sample_lines}\n---", style="blue")

        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample_lines, delimiters=',;\t|') # Common delimiters
        detected_delimiter_char = dialect.delimiter
        console.log(f"Detected delimiter: '{detected_delimiter_char}' (repr: {repr(detected_delimiter_char)}) for '{file_path}'", style="green")
        return detected_delimiter_char
        
    except FileNotFoundError: # Should be less likely now, but good to keep
        console.log(f"File not found during delimiter detection: '{file_path}'. Using default: '{default_delimiter}'.", style="bold red")
        return default_delimiter
    except csv.Error:
        console.log(f"csv.Sniffer could not automatically detect delimiter for '{file_path}' from the sample. Using default: '{default_delimiter}'.", style="yellow")
        return default_delimiter
    except Exception as e:
        console.log(f"An unexpected error occurred during delimiter detection for '{file_path}': {e}. Using default: '{default_delimiter}'.", style="bold red")
        return default_delimiter

# --- LLM Prompt Template ---
XSV_COMMAND_GENERATION_PROMPT_TEMPLATE = """
<purpose>
You are an expert in using the 'xsv' command-line tool for analyzing CSV and other
delimiter-separated value files. Your task is to translate a user's natural language
query about a CSV file into a single, correct, and efficient 'xsv' command.
</purpose>

<instructions>
1.  Analyze the user's query, the provided CSV file path, and the pre-detected delimiter.
2.  Determine the most appropriate 'xsv' subcommand and options to fulfill the query.
3.  Construct the complete 'xsv' command string.
4.  Ensure the command is syntactically correct and includes the file path.
5.  Do NOT include any introductory or explanatory text, only the raw 'xsv' command.
6.  Do NOT include the 'uv run sfa_xsv_analyzer_v1.py' part, only the 'xsv ...' part.
7.  If the user query is ambiguous or cannot be translated into a single 'xsv' command,
    return an empty string or a brief message indicating the limitation.
8.  Assume the 'xsv' command is available in the environment.
9.  The script has pre-detected the delimiter for the input file as: '{detected_delimiter}'.
    You MUST use this delimiter in your 'xsv' command by including the `-d "{detected_delimiter}"` option
    if the detected delimiter is NOT a comma (e.g., for tab, semicolon, pipe).
    For example, if detected_delimiter is a tab character, use `xsv ... -d "\t" ...`.
    If the user's query *explicitly* specifies a different delimiter, prioritize the user's specification
    and use that delimiter with the -d flag. Otherwise, rely on the pre-detected one.
10. If the user asks for output formatting (e.g., JSON, pretty table), use appropriate
    xsv subcommands or combinations (e.g., `xsv search ... | xsv json`).
</instructions>

<user_query>{user_query}</user_query>

<csv_file_path>{csv_file_path}</csv_file_path>

<detected_delimiter_info>
The file's delimiter has been pre-detected as: '{detected_delimiter}'.
If this is not a comma, ensure you use the -d option (e.g., -d "\t" for tab, -d ";" for semicolon).
</detected_delimiter_info>

<examples>
User Query: show first 10 rows
CSV File Path: data.csv
Detected Delimiter: ','
xsv command: xsv slice -n 1 -u 10 data.csv

User Query: count rows in tab separated file
CSV File Path: data.tsv
Detected Delimiter: '\t'
xsv command: xsv count -d "\t" data.tsv

User Query: list columns from semicolon file
CSV File Path: stats.scsv
Detected Delimiter: ';'
xsv command: xsv headers -d ";" stats.scsv

User Query: filter rows where age > 30 and select name, email
CSV File Path: users.csv
Detected Delimiter: ','
xsv command: xsv search -s age -p '^([3-9]\d|\d{{3,}})$' users.csv | xsv select name,email

User Query: find rows with "error" in any column (file is pipe-delimited)
CSV File Path: log.psv
Detected Delimiter: '|'
xsv command: xsv search "error" log.psv -d "|"
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

def get_xsv_command_from_ai(user_query: str, csv_file_path: str, llm_provider: str, api_key: str, model_name: str, detected_delimiter: str) -> Optional[str]:
    """
    Generates an xsv command from a user query using an LLM.

    Args:
        user_query: The natural language query from the user.
        csv_file_path: The path to the CSV file.
        llm_provider: The LLM provider to use ('anthropic', 'openai', 'google').
        api_key: The API key for the chosen provider.
        model_name: The specific model name to use.
        detected_delimiter: The delimiter detected by the script.

    Returns:
        The generated xsv command string, or None if generation failed.
    """
    global TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS

    console.log(
        f"Attempting to generate xsv command using {llm_provider}/{model_name} "
        f"for query: '{user_query}' on file: '{csv_file_path}' with detected delimiter: '{repr(detected_delimiter)}'"
    )

    prompt = XSV_COMMAND_GENERATION_PROMPT_TEMPLATE.format(
        user_query=user_query,
        csv_file_path=csv_file_path,
        detected_delimiter=detected_delimiter
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
    output_file_path: Optional[str] = None,
    detected_delimiter: str = ',' # Added detected_delimiter
) -> Tuple[Optional[str], int, int]:
    """
    Main logic function for the XSV Analyzer Agent.

    Orchestrates the process of:
    1. Getting an xsv command from an LLM based on user query and detected delimiter.
    2. Optionally appending output redirection if an output file is specified.
    3. Executing the xsv command.
    4. Returning the result or error, along with token counts.
    """
    global TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS

    console.log(
        f"Starting XSV Analyzer Agent for query: '{user_query}' "
        f"on file: '{csv_file_path}' (Delimiter for LLM: '{repr(detected_delimiter)}')"
    )

    generated_xsv_command = get_xsv_command_from_ai(
        user_query, csv_file_path, llm_provider, api_key, model_name, detected_delimiter
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

    # Ensure file is UTF-8 and get the path to process
    path_to_process, original_encoding, was_converted = ensure_utf8_file(args.csv_file)

    if original_encoding is None and not os.path.exists(path_to_process): # Check if ensure_utf8_file indicated a critical error
        console.print(Panel(f"Critical error: Could not read or process input file '{args.csv_file}'. Exiting.", title="[bold red]File Processing Error[/bold red]", expand=False))
        sys.exit(1)
    
    if was_converted:
        console.log(f"Original file '{args.csv_file}' (encoding: {original_encoding}) was converted to UTF-8: '{path_to_process}'")
    else:
        console.log(f"Processing file '{path_to_process}' (original encoding: {original_encoding or 'assumed utf-8/binary'})")

    # Detect delimiter from the (now guaranteed UTF-8) file
    detected_delimiter = detect_delimiter(path_to_process)
    console.log(f"Delimiter for xsv command generation on '{path_to_process}': '{repr(detected_delimiter)}'")

    # Reset global token counters for this run
    global TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS
    TOTAL_INPUT_TOKENS = 0
    TOTAL_OUTPUT_TOKENS = 0
    
    # Call run_xsv_analyzer_agent with the path_to_process
    _result_output, current_run_input_tokens, current_run_output_tokens = run_xsv_analyzer_agent(
        user_query=args.query,
        csv_file_path=path_to_process, # Use the UTF-8 version
        llm_provider=args.llm_provider,
        api_key=api_key,
        model_name=model_name_to_use,
        output_file_path=args.output_file,
        detected_delimiter=detected_delimiter
    )

    # Optional: Cleanup the .utf8.csv file if it was created
    # if was_converted and path_to_process != args.csv_file:
    #     try:
    #         os.remove(path_to_process)
    #         console.log(f"Cleaned up temporary UTF-8 file: {path_to_process}", style="dim")
    #     except OSError as e:
    #         console.log(f"Warning: Could not remove temporary UTF-8 file '{path_to_process}': {e}", style="yellow")

    # run_xsv_analyzer_agent handles printing of its own results/errors.
    # main's responsibility is to call display_token_usage, which uses the final global counts.
    display_token_usage()

# --- Entry Point ---
if __name__ == "__main__":
    main()