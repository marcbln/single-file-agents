# Plan: Implement the Mermaid Fixer Single File Agent (sfa_mermaid_fixer_anthropic_v1.py)

**Goal:** Create a Python script using `uv` for dependencies that takes broken MermaidJS code (either as a string or from a file), iteratively uses the Mermaid CLI (`mmdc`) to validate it, and calls the Anthropic Claude 3.7 Sonnet API to suggest fixes based on validation errors until the code is valid or a maximum number of iterations is reached.

**Phase 1: Setup and Boilerplate**

1.  **Create File:** Create a new Python file named `sfa_mermaid_fixer_anthropic_v1.py`.
2.  **Shebang:** Add the `uv` shebang line at the very top:
    ```python
    #!/usr/bin/env -S uv run --script
    ```
3.  **Dependency Block:** Add the `uv` script dependency block:
    ```python
    # /// script
    # dependencies = [
    #   "anthropic>=0.47.1",
    #   "rich>=13.7.0",
    # ]
    # ///
    ```
4.  **Docstring:** Add the main script docstring, including the purpose and example usage provided in the requirements.
5.  **Imports:** Add necessary standard library imports: `os`, `sys`, `argparse`, `subprocess`, `tempfile`, `time`, `re`, `typing`.
6.  **Rich/Anthropic Imports:** Add imports for `rich` and `anthropic`:
    ```python
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.markdown import Markdown
    from rich.table import Table
    from anthropic import Anthropic
    ```
7.  **Console Initialization:** Initialize the `rich` console: `console = Console()`.
8.  **Constants:** Define constants near the top: `MODEL_NAME`, `MAX_RETRIES_API`, `RETRY_WAIT_API`.
9.  **Main Guard:** Add the standard `if __name__ == "__main__":` block with a call to `main()`.

**Phase 2: Mermaid CLI Validation Function**

1.  **Define Function:** Create the `validate_mermaid_code(code: str) -> Tuple[bool, str]` function.
2.  **Temp File:** Implement logic to write the input `code` to a temporary file using `tempfile.NamedTemporaryFile`. Ensure the file has a `.mmd` suffix if possible and is deleted afterwards (`delete=False` initially, then `os.remove` in a `finally` block).
3.  **MMDC Command:** Construct the `mmdc` command list (e.g., `["mmdc", "-i", temp_file_path, "-o", "/dev/null", "--quiet"]`). Handle the output target for Windows (`NUL`).
4.  **Subprocess Execution:** Use `subprocess.run` to execute the command. Capture `stdout` and `stderr`. Set `text=True` and `check=False`.
5.  **Error Handling:** Include a `try...except FileNotFoundError` block to catch cases where `mmdc` is not installed and return an informative error message. Include a general `except Exception`.
6.  **Result Check:** Check the `returncode` of the subprocess result.
    *   If 0, return `(True, "Mermaid code is valid.")`.
    *   If non-zero, return `(False, result.stderr.strip())`.
7.  **Logging:** Add `console.log` statements for starting the validation and reporting success or failure, including the error message if validation fails.
8.  **Cleanup:** Ensure the temporary file is removed in the `finally` block.

**Phase 3: AI Code Fixing Function**

1.  **Define Prompt Template:** Create the `FIXER_PROMPT_TEMPLATE` string variable containing the detailed XML prompt structure with placeholders `{current_code}` and `{error_message}`.
2.  **Define Code Extraction Function:** Create the helper function `extract_mermaid_code(text: str) -> Optional[str]` using `re.search` to find and extract code within ```mermaid ... ``` blocks. Include the fallback logic for code not in blocks.
3.  **Define AI Fix Function:** Create the `get_ai_fix(code: str, error: str, client: Anthropic) -> Tuple[Optional[str], int, int]` function.
4.  **Format Prompt:** Use `FIXER_PROMPT_TEMPLATE.format(...)` to create the specific prompt for the API call.
5.  **API Call Loop:** Implement a `for` loop for retries (`MAX_RETRIES_API`).
6.  **Anthropic API Call:** Inside the loop, use `client.messages.create` with the appropriate model, max tokens, messages list, and system prompt. Use a `try...except` block to handle API errors. Implement `time.sleep(RETRY_WAIT_API)` between retries.
7.  **Token Tracking:** After a successful API call, access `response.usage` to get `input_tokens` and `output_tokens`. Add them to running totals.
8.  **Response Processing:** Extract the text content from the `response.content` list (checking for `block.type == "text"`).
9.  **Code Extraction:** Call `extract_mermaid_code` on the response text.
10. **Result Handling:**
    *   If `extract_mermaid_code` returns code, log success and return `(fixed_code, input_tokens, output_tokens)`.
    *   If it returns `None`, log a warning. If retries remain, continue the loop. If no retries left, log failure and return `(None, input_tokens, output_tokens)`.
11. **Failure Return:** If all retries fail, return `(None, input_tokens, output_tokens)`.
12. **Logging:** Add `console.log` statements for attempting the fix, reporting API errors, and indicating success or failure.

**Phase 4: Main Agent Loop Function**

1.  **Define Function:** Create the `run_fixer_agent(initial_code: str, max_iterations: int, client: Anthropic) -> Tuple[Optional[str], int, int]` function.
2.  **Initialization:** Set `current_code = initial_code`. Initialize total token counters to zero.
3.  **Iteration Loop:** Start a `for` loop from `0` to `max_iterations - 1`.
4.  **Display & Validate:** Inside the loop, print the `current_code` (using `rich.Panel` and `Syntax`). Call `validate_mermaid_code(current_code)`.
5.  **Check Validity:** If `is_valid` is `True`, print a success message and return `(current_code, total_tokens...)`.
6.  **Handle Validation Errors:** If `is_valid` is `False`, print the error message using `rich.Panel`. Check if the error indicates `mmdc` is missing and return `(None, tokens...)` if so.
7.  **Get AI Fix:** Call `get_ai_fix(current_code, error_message, client)`. Add returned tokens to totals.
8.  **Check AI Result:** If `get_ai_fix` returns `None`, print failure and return `(None, total_tokens...)`.
9.  **Check for No Change:** Compare `suggested_fix.strip()` with `current_code.strip()`. If they are the same, print a warning about the loop and return `(current_code, total_tokens...)`.
10. **Update Code:** Set `current_code = suggested_fix`.
11. **Loop End:** If the loop finishes without returning, print a failure message (max iterations reached) and return `(None, total_tokens...)`.

**Phase 5: Command-Line Interface and Execution**

1.  **Implement `main()`:** Define the `main()` function.
2.  **Argument Parsing:** Use `argparse.ArgumentParser` to define CLI arguments: `--input`/`-i`, `--code`/`-c` (mutually exclusive), `--output`/`-o`, `--max-iterations`.
3.  **Load Initial Code:** Based on `args.input` or `args.code`, load the `initial_code`. Handle potential `FileNotFoundError` for `--input`. Check if `initial_code` is empty.
4.  **API Key Check:** Get `ANTHROPIC_API_KEY` using `os.getenv`. Print an error and exit if not set.
5.  **Initialize Client:** Create the `Anthropic` client instance. Handle potential initialization errors.
6.  **Call Agent:** Call `run_fixer_agent(initial_code, args.max_iterations, client)` to get the `fixed_code` and token counts.
7.  **Implement Token Display:** Create a `display_token_usage(input_tokens, output_tokens)` function using `rich.Table` to show the token counts (reuse from previous SFAs if available). Call this function with the returned token counts.
8.  **Output Results:**
    *   Print the final status (success or failure).
    *   If `fixed_code` is not `None`, print it using `rich.Panel` and `Syntax`.
    *   If `args.output` was provided and `fixed_code` is not `None`, write `fixed_code` to the specified file. Handle potential file writing errors.
    *   If `fixed_code` is `None`, indicate failure and optionally print the last attempted code.

**Phase 6: Refinement**

1.  **Review:** Read through the complete script.
2.  **Add Comments:** Add comments explaining complex parts.
3.  **Refine Logging:** Ensure `console.log` and `console.print` provide useful feedback during execution.
4.  **Test:** Run the script with the example usage cases provided in the docstring and potentially add more test cases (e.g., edge cases, very large code, different error types).

