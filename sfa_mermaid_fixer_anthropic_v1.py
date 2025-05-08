#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "anthropic>=0.47.1",
#   "rich>=13.7.0",
# ]
# ///
"""
Mermaid Fixer Single File Agent (sfa_mermaid_fixer_anthropic_v1.py)

This script takes potentially broken MermaidJS code, validates it using the
Mermaid CLI ('mmdc'), and uses the Anthropic Claude 3.5 Sonnet API to suggest
fixes based on validation errors. It iterates this process until the code is
valid or a maximum number of iterations is reached.

Requires:
- Python 3.8+
- 'uv' package manager (for running with shebang)
- Mermaid CLI ('mmdc') installed globally (`npm install -g @mermaid-js/mermaid-cli`)
- ANTHROPIC_API_KEY environment variable set.

Example Usage:

1. Fix code from a string:
   python sfa_mermaid_fixer_anthropic_v1.py -c "graph TD; A-- B;" --max-iterations 3

2. Fix code from a file and save to another file:
   python sfa_mermaid_fixer_anthropic_v1.py -i broken.mmd -o fixed.mmd

3. Pipe code in:
   cat broken.mmd | python sfa_mermaid_fixer_anthropic_v1.py
"""

import os
import sys
import argparse
import subprocess
import tempfile
import time
import re
import typing
from typing import Tuple, Optional

# Rich imports
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.table import Table

# Anthropic import
try:
    from anthropic import Anthropic
except ImportError:
    print("Error: 'anthropic' library not found. Please ensure dependencies are installed.", file=sys.stderr)
    print("If using the shebang, 'uv' should handle this automatically.", file=sys.stderr)
    sys.exit(1)

# --- Constants ---
MODEL_NAME = "claude-3-5-sonnet-20240620"
MAX_RETRIES_API = 3
RETRY_WAIT_API = 5  # seconds
FIXER_PROMPT_TEMPLATE = """
<prompt>
You are an expert in MermaidJS syntax. Your task is to fix the provided Mermaid code based on the validation error message from the Mermaid CLI (`mmdc`).

**Current Mermaid Code:**
<current_code>
{current_code}
</current_code>

**Validation Error:**
<error_message>
{error_message}
</error_message>

**Instructions:**
1. Analyze the error message and the code carefully.
2. Identify the specific syntax error(s).
3. Determine the necessary corrections.
4. Provide *only* the complete, corrected Mermaid code block below. Do not include any explanations, apologies, or introductory text outside the code block. The code block should start with ```mermaid and end with ```. Ensure the entire valid Mermaid diagram definition is included.

**Corrected Mermaid Code:**
<corrected_code>
```mermaid
{{Insert corrected code here}}
```
</corrected_code>
</prompt>
"""

# --- Initialization ---
console = Console()

# --- Helper Functions ---

def extract_mermaid_code(text: str) -> Optional[str]:
    """
    Extracts Mermaid code from a string, looking for ```mermaid blocks
    or attempting fallback if only code seems present.
    """
    # Primary extraction using ```mermaid block
    match = re.search(r"```mermaid\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Fallback: Check if the response looks like only Mermaid code
    # Basic check for common diagram types and lack of conversational markers
    trimmed_text = text.strip()
    common_starts = ["graph", "sequenceDiagram", "classDiagram", "stateDiagram", "gantt", "pie", "flowchart", "erDiagram", "journey", "requirementDiagram", "gitGraph"]
    likely_code = False
    for start in common_starts:
        if trimmed_text.lower().startswith(start):
            likely_code = True
            break

    # Avoid common conversational phrases if checking fallback
    if likely_code and not re.search(r"(here is|sure,|apologies|sorry|fixed code|hope this helps)", trimmed_text, re.IGNORECASE):
         # Check if it contains typical non-code structures like XML tags used in the prompt
        if not ("<corrected_code>" in trimmed_text or "<prompt>" in trimmed_text):
            console.log("[yellow]Warning:[/yellow] No ```mermaid block found, attempting fallback extraction based on content.")
            return trimmed_text

    return None

def display_token_usage(input_tokens: int, output_tokens: int):
    """Displays token usage in a table."""
    table = Table(title="Anthropic API Token Usage", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="dim", width=15)
    table.add_column("Value", justify="right")

    table.add_row("Input Tokens", str(input_tokens))
    table.add_row("Output Tokens", str(output_tokens))
    table.add_row("Total Tokens", str(input_tokens + output_tokens))

    console.print(table)

# --- Core Functions ---

def validate_mermaid_code(code: str) -> Tuple[bool, str]:
    """
    Validates Mermaid code using the mmdc CLI.

    Args:
        code: The Mermaid code string to validate.

    Returns:
        A tuple containing:
        - bool: True if the code is valid, False otherwise.
        - str: A message indicating success or the stderr output on failure.
    """
    console.log("Validating Mermaid code...")
    temp_file_path = None
    try:
        # Create a temporary file with .mmd suffix
        with tempfile.NamedTemporaryFile(mode='w', suffix=".mmd", delete=False, encoding='utf-8') as temp_file:
            temp_file.write(code)
            temp_file_path = temp_file.name

        # Create a temporary output file with valid extension
        with tempfile.NamedTemporaryFile(mode='w', suffix=".svg", delete=False, encoding='utf-8') as temp_output:
            output_target = temp_output.name

        # Construct the mmdc command with valid output file
        command = ["mmdc", "-i", temp_file_path, "-o", output_target, "--quiet"]

        # Execute the command
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8')

        # Check the result
        if result.returncode == 0:
            console.log("[green]Validation successful.[/green]")
            return True, "Mermaid code is valid."
        else:
            error_message = result.stderr.strip() if result.stderr else "Unknown validation error (no stderr)."
            # Sometimes mmdc puts errors on stdout too
            if not error_message and result.stdout:
                 error_message = result.stdout.strip()
            console.log(f"[red]Validation failed.[/red] Error: {error_message[:200]}...") # Log truncated error
            return False, error_message

    except FileNotFoundError:
        error_msg = "Error: 'mmdc' command not found. Please install Mermaid CLI: npm install -g @mermaid-js/mermaid-cli"
        console.log(f"[bold red]{error_msg}[/bold red]")
        return False, error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred during validation: {e}"
        console.log(f"[bold red]{error_msg}[/bold red]")
        return False, error_msg
    finally:
        # Ensure the temporary file is removed
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError as e:
                 console.log(f"[yellow]Warning:[/yellow] Could not remove temporary file {temp_file_path}: {e}")


def get_ai_fix(code: str, error: str, client: Anthropic) -> Tuple[Optional[str], int, int]:
    """
    Calls the Anthropic API to get a suggested fix for the Mermaid code.

    Args:
        code: The current (broken) Mermaid code.
        error: The validation error message from mmdc.
        client: An initialized Anthropic client instance.

    Returns:
        A tuple containing:
        - Optional[str]: The suggested fixed code, or None if failed.
        - int: Total input tokens used in this function call.
        - int: Total output tokens used in this function call.
    """
    total_input_tokens = 0
    total_output_tokens = 0
    formatted_prompt = FIXER_PROMPT_TEMPLATE.format(current_code=code, error_message=error)

    for attempt in range(MAX_RETRIES_API):
        console.log(f"Attempting to get AI fix (Attempt {attempt + 1}/{MAX_RETRIES_API})...")
        try:
            response = client.messages.create(
                model=MODEL_NAME,
                max_tokens=2048, # Generous limit for code
                messages=[
                    {"role": "user", "content": formatted_prompt}
                ]
            )

            # Track token usage
            if response.usage:
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                console.log(f"API call successful. Tokens used: Input={input_tokens}, Output={output_tokens}")
            else:
                 console.log("[yellow]Warning:[/yellow] Token usage information not available in API response.")


            # Extract response text
            response_text = ""
            if response.content and response.content[0].type == "text":
                response_text = response.content[0].text
            else:
                 console.log("[yellow]Warning:[/yellow] No text content found in AI response.")
                 # Fall through to extraction attempt anyway, maybe it's just code

            # Extract Mermaid code from the response
            suggested_fix = extract_mermaid_code(response_text)

            if suggested_fix:
                console.log("[green]AI suggested a fix.[/green]")
                return suggested_fix, total_input_tokens, total_output_tokens
            else:
                console.log(f"[yellow]Warning:[/yellow] Could not extract Mermaid code from AI response (Attempt {attempt + 1}/{MAX_RETRIES_API}). Response snippet:\n{response_text[:500]}...")
                if attempt < MAX_RETRIES_API - 1:
                    console.log(f"Waiting {RETRY_WAIT_API} seconds before retrying...")
                    time.sleep(RETRY_WAIT_API)
                # Continue to next attempt or final failure

        except Exception as e:
            console.log(f"[bold red]API Error (Attempt {attempt + 1}/{MAX_RETRIES_API}): {e}[/bold red]")
            if attempt < MAX_RETRIES_API - 1:
                console.log(f"Waiting {RETRY_WAIT_API} seconds before retrying...")
                time.sleep(RETRY_WAIT_API)
            # Continue to next attempt or final failure

    # If loop finishes without returning a fix
    console.log("[bold red]Failed to get a valid fix from AI after multiple retries.[/bold red]")
    return None, total_input_tokens, total_output_tokens


def run_fixer_agent(initial_code: str, max_iterations: int, client: Anthropic) -> Tuple[Optional[str], int, int]:
    """
    Runs the main loop for validating and fixing Mermaid code.

    Args:
        initial_code: The starting Mermaid code.
        max_iterations: Maximum number of fixing attempts.
        client: An initialized Anthropic client instance.

    Returns:
        A tuple containing:
        - Optional[str]: The final fixed code if successful, else None.
        - int: Total input tokens used across all API calls.
        - int: Total output tokens used across all API calls.
    """
    current_code = initial_code.strip()
    total_input_tokens = 0
    total_output_tokens = 0

    for i in range(max_iterations):
        console.print(Panel(f"Iteration {i + 1}/{max_iterations}", style="bold blue", title="Iteration Progress"))
        console.print(Panel(Syntax(current_code, "mermaid", theme="monokai", line_numbers=True), title="Current Code", border_style="cyan"))

        # Validate the current code
        is_valid, validation_output = validate_mermaid_code(current_code)

        if is_valid:
            console.print(Panel("✅ Mermaid code is valid!", style="bold green", title="Success"))
            return current_code, total_input_tokens, total_output_tokens

        # Handle validation errors
        console.print(Panel(validation_output, title="Validation Error", border_style="red"))

        # Check if the error is due to mmdc not being installed
        if "mmdc' command not found" in validation_output:
            console.print(Panel("❌ Cannot proceed without 'mmdc'. Please install it.", style="bold red", title="Prerequisite Missing"))
            return None, total_input_tokens, total_output_tokens # Cannot fix if validator is missing

        # If not valid, attempt to get an AI fix
        suggested_fix, input_tokens, output_tokens = get_ai_fix(current_code, validation_output, client)
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens

        if suggested_fix is None:
            console.print(Panel("❌ Failed to get a fix suggestion from the AI.", style="bold red", title="AI Failure"))
            return None, total_input_tokens, total_output_tokens

        # Check if the AI returned the exact same code
        if suggested_fix.strip() == current_code:
            console.print(Panel("⚠️ AI returned the same code. Stopping iteration to prevent potential loop.", style="bold yellow", title="Warning"))
            # Return the current code as the best effort, even though it's not validated
            return current_code, total_input_tokens, total_output_tokens

        # Update code for the next iteration
        current_code = suggested_fix.strip()
        console.log("Updated code based on AI suggestion. Proceeding to next validation.")
        time.sleep(1) # Small delay before next iteration

    # If loop finishes without valid code
    console.print(Panel(f"❌ Failed to fix Mermaid code within {max_iterations} iterations.", style="bold red", title="Failure"))
    return None, total_input_tokens, total_output_tokens

# --- Main Execution ---

def main():
    """Main function to parse arguments and run the fixer."""
    parser = argparse.ArgumentParser(
        description="Fixes broken MermaidJS code using mmdc validation and Anthropic AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Example Usage:
  python sfa_mermaid_fixer_anthropic_v1.py -c "graph TD; A-- B;" --max-iterations 3
  python sfa_mermaid_fixer_anthropic_v1.py -i broken.mmd -o fixed.mmd
  cat broken.mmd | python sfa_mermaid_fixer_anthropic_v1.py -o fixed.mmd
"""
    )

    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("-i", "--input", help="Path to the input Mermaid file (.mmd)")
    group.add_argument("-c", "--code", help="Mermaid code string")

    parser.add_argument("-o", "--output", help="Path to save the fixed Mermaid file")
    parser.add_argument("--max-iterations", type=int, default=5, help="Maximum fixing iterations (default: 5)")

    args = parser.parse_args()

    # --- Load Initial Code ---
    initial_code = None
    if args.code:
        initial_code = args.code
        console.log("Using Mermaid code provided via --code argument.")
    elif args.input:
        try:
            with open(args.input, 'r', encoding='utf-8') as f:
                initial_code = f.read()
            console.log(f"Loaded Mermaid code from input file: {args.input}")
        except FileNotFoundError:
            console.print(f"[bold red]Error:[/bold red] Input file not found: {args.input}")
            sys.exit(1)
        except IOError as e:
            console.print(f"[bold red]Error:[/bold red] Could not read input file {args.input}: {e}")
            sys.exit(1)
    elif not sys.stdin.isatty(): # Check if stdin has data (piped input)
        console.log("Reading Mermaid code from stdin...")
        initial_code = sys.stdin.read()
    else:
        # No input provided via args or stdin
        parser.print_help()
        console.print("\n[bold red]Error:[/bold red] No input code provided. Use --code, --input, or pipe data via stdin.")
        sys.exit(1)

    if not initial_code or not initial_code.strip():
        console.print("[bold red]Error:[/bold red] Input code is empty.")
        sys.exit(1)

    # --- API Key and Client Initialization ---
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[bold red]Error:[/bold red] ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    try:
        client = Anthropic(api_key=api_key)
        console.log("Anthropic client initialized successfully.")
    except Exception as e:
        console.print(f"[bold red]Error initializing Anthropic client: {e}[/bold red]")
        sys.exit(1)

    # --- Run the Fixer Agent ---
    console.print(Panel("Starting Mermaid Fixer Agent", style="bold magenta"))
    fixed_code, total_input_tokens, total_output_tokens = run_fixer_agent(
        initial_code, args.max_iterations, client
    )

    # --- Display Token Usage ---
    display_token_usage(total_input_tokens, total_output_tokens)

    # --- Output Results ---
    if fixed_code:
        console.print(Panel("✅ Final Fixed Code:", style="bold green", title_align="left"))
        console.print(Syntax(fixed_code, "mermaid", theme="monokai", line_numbers=False))

        if args.output:
            try:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(fixed_code)
                console.print(f"\n[green]Successfully saved fixed code to:[/green] {args.output}")
            except IOError as e:
                console.print(f"\n[bold red]Error:[/bold red] Could not write to output file {args.output}: {e}")
                # Don't exit with error code here, as the primary goal (fixing) might have succeeded
    else:
        console.print(Panel("❌ Failed to produce valid Mermaid code after all iterations.", style="bold red", title="Overall Result"))
        sys.exit(1) # Exit with error code if the process failed

if __name__ == "__main__":
    main()