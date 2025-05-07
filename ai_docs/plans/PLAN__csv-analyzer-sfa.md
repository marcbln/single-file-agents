Okay, here's an implementation plan for an AI Coding Agent to create a Single File AI Agent (SFA) that uses the `xsv` CLI tool to analyze CSV files.

The target SFA will be named `sfa_xsv_analyzer_v1.py`.

---

**Project Goal:** Create `sfa_xsv_analyzer_v1.py`, a Python script that takes a user query and a CSV file path as input. It will use an LLM to determine the appropriate `xsv` command to execute based on the user's query, run that command, and present the results.

**Target AI Coder:** This plan is for an AI agent with Python coding capabilities and access to an LLM (e.g., Claude, GPT, Gemini) for generating parts of the SFA, especially the LLM interaction logic and prompts.

---

**Implementation Plan: `sfa_xsv_analyzer_v1.py`**

**Phase 1: Setup and Boilerplate**

1.  **Create File:**
    *   Action: Create a new Python file named `sfa_xsv_analyzer_v1.py`.

2.  **Add UV Shebang and Dependency Block:**
    *   Action: Add the `uv run --script` shebang at the very top.
    *   Action: Add the `/// script ... ///` block for dependencies.
        *   Required dependencies: `rich` (for console output), and an LLM SDK (e.g., `anthropic`, `openai`, `google-generativeai` - choose one, let's assume `anthropic` for this plan).
        ```python
        #!/usr/bin/env -S uv run --script
        # /// script
        # dependencies = [
        #   "anthropic>=0.47.1",  # Or openai / google-generativeai
        #   "rich>=13.7.0",
        # ]
        # ///
        ```

3.  **Add Main Docstring:**
    *   Action: Create a comprehensive docstring for the SFA.
    *   Content:
        *   Purpose of the SFA (analyzes CSVs using `xsv` driven by an LLM).
        *   How to run it (example CLI usage).
        *   Required environment variables (e.g., `ANTHROPIC_API_KEY`).
        *   Prerequisites (e.g., `xsv` must be installed and in PATH).

4.  **Import Necessary Modules:**
    *   Action: Import standard Python libraries: `os`, `sys`, `argparse`, `subprocess`, `json`.
    *   Action: Import `Console`, `Panel`, `Syntax`, `Table` from `rich`.
    *   Action: Import the chosen LLM SDK (e.g., `from anthropic import Anthropic`).

5.  **Initialize Rich Console:**
    *   Action: `console = Console()`

6.  **Define Constants:**
    *   Action: Define `MODEL_NAME` (e.g., `"claude-3-7-sonnet-20250219"`).
    *   Action: Define `API_MAX_RETRIES`, `API_RETRY_WAIT`.
    *   Action: Define global variables for token tracking (e.g., `TOTAL_INPUT_TOKENS = 0`, `TOTAL_OUTPUT_TOKENS = 0`).

7.  **Implement `main()` Guard:**
    *   Action: Add `if __name__ == "__main__":` calling a `main()` function.

**Phase 2: `xsv` Command Execution Function**

1.  **Define `execute_xsv_command` function:**
    *   Signature: `execute_xsv_command(xsv_command_str: str) -> Tuple[bool, str, str]`
        *   Returns: `(success_status, stdout, stderr)`
    *   Action:
        *   Log the command being executed.
        *   Use `subprocess.run()` to execute the `xsv_command_str`.
            *   `shell=True` (be mindful of security if commands are not fully AI-generated and sanitized, but for `xsv` from a trusted LLM, it's often simpler).
            *   Capture `stdout` and `stderr`.
            *   Set `text=True`.
        *   Check `returncode`. If non-zero, set `success_status` to `False`.
        *   Handle `FileNotFoundError` if `xsv` is not installed, return an informative error in `stderr`.
        *   Log the outcome (success/failure) and the `stdout`/`stderr`.
        *   Return the tuple.

**Phase 3: LLM Integration for `xsv` Command Generation**

1.  **Define `XSV_COMMAND_GENERATION_PROMPT_TEMPLATE`:**
    *   Action: Create a detailed XML-style prompt template.
    *   Content:
        *   `<purpose>`: You are an expert in `xsv` CLI and CSV data analysis. Your task is to generate the correct `xsv` command based on a user's query and the path to a CSV file.
        *   `<instructions>`:
            *   Analyze the user query and CSV file path.
            *   Determine the most appropriate `xsv` subcommand and options.
            *   Construct a single, runnable `xsv` command string.
            *   Return *ONLY* the `xsv` command string. No explanations, no markdown, just the command.
            *   Assume the CSV file has a header row.
            *   If the user asks to save output, pipe `>` to a filename (e.g., `output.csv` or `output.txt`). Infer a sensible filename if not provided.
            *   Use `xsv input <csv_file_path> <subcommand_and_options>` for commands that read from stdin or when chaining multiple `xsv` commands is cleaner.
            *   Alternatively, many `xsv` commands accept the file path directly as the last argument.
            *   Refer to this summary of `xsv` commands:
                *   `xsv cat rows/columns ...`: Concatenate CSV files.
                *   `xsv count ...`: Count rows.
                *   `xsv fixlengths ...`: Make all rows have the same number of columns.
                *   `xsv flatten ...`: Flatten records (one field per line).
                *   `xsv fmt ...`: Format CSV output (e.g., change delimiter).
                *   `xsv frequency ...`: Show frequency of values in columns.
                *   `xsv headers ...`: Show header names.
                *   `xsv index ...`: Create an index for faster access.
                *   `xsv input <path> ...`: Read CSV from path (useful for chaining).
                *   `xsv join ...`: Join CSV files.
                *   `xsv sample <N> ...`: Sample N rows.
                *   `xsv search <pattern> ...`: Search for regex pattern.
                *   `xsv select <fields> ...`: Select columns.
                *   `xsv slice ...`: Slice rows.
                *   `xsv sort -s <col> ...`: Sort by column.
                *   `xsv stats ...`: Calculate basic statistics.
                *   `xsv table ...`: Output as a neatly formatted table.
        *   `<user_query>`: `{user_query}` (placeholder)
        *   `<csv_file_path>`: `{csv_file_path}` (placeholder)
        *   `<examples>`:
            *   Example 1: User query "Show first 5 rows of data.csv", CSV "data.csv" -> `xsv slice -l 5 data.csv`
            *   Example 2: User query "Count rows in input.csv", CSV "input.csv" -> `xsv count input.csv`
            *   Example 3: User query "Select 'name' and 'age' columns from people.csv", CSV "people.csv" -> `xsv select name,age people.csv`
            *   Example 4: User query "Find rows where 'city' is 'London' in customers.csv and save to london_customers.csv", CSV "customers.csv" -> `xsv search -s city London customers.csv > london_customers.csv`
        *   `Your xsv command:` (LLM should fill this)

2.  **Define `get_xsv_command_from_ai` function:**
    *   Signature: `get_xsv_command_from_ai(user_query: str, csv_file_path: str, client: LLMClient) -> Optional[str]`
    *   Action:
        *   Log the attempt to generate an `xsv` command.
        *   Format `XSV_COMMAND_GENERATION_PROMPT_TEMPLATE` with `user_query` and `csv_file_path`.
        *   Make an API call to the LLM (e.g., `client.messages.create`).
            *   Use `MODEL_NAME`.
            *   Include retry logic (loop `API_MAX_RETRIES` times with `API_RETRY_WAIT` delay).
        *   Increment `TOTAL_INPUT_TOKENS` and `TOTAL_OUTPUT_TOKENS` based on `response.usage`.
        *   Extract the `xsv` command string from the LLM's response.
            *   Ensure it's *only* the command (strip whitespace, remove backticks if present).
        *   Log the raw response and the extracted command.
        *   Return the command string or `None` if generation fails.

**Phase 4: Main Agent Logic Function**

1.  **Define `run_xsv_analyzer_agent` function:**
    *   Signature: `run_xsv_analyzer_agent(user_query: str, csv_file_path: str, client: LLMClient, output_file_path: Optional[str] = None) -> Tuple[Optional[str], int, int]`
        *   Returns: `(final_result_str_or_None, total_input_tokens, total_output_tokens)`
    *   Action:
        *   Log agent start.
        *   Call `get_xsv_command_from_ai` to get the `xsv` command.
        *   If no command is generated:
            *   Log failure.
            *   Return `None` and current token counts.
        *   If a command is generated:
            *   If `output_file_path` is provided and not already in the command, append ` > {output_file_path}` to the `xsv` command.
            *   Call `execute_xsv_command` with the generated command.
            *   If `execute_xsv_command` fails:
                *   Log failure.
                *   Return the error message from `xsv` and token counts.
            *   If `execute_xsv_command` succeeds:
                *   Log success.
                *   Display `stdout` using `rich.Syntax` or `rich.Panel`.
                *   If an `output_file_path` was used, confirm file creation.
                *   Return `stdout` (or a success message if output was to file) and token counts.
        *   (Optional for v1, consider for v2: If `xsv` output is complex, make another LLM call to summarize or interpret the `xsv` output for the user.)

**Phase 5: Command-Line Interface and Execution**

1.  **Implement `main()` function:**
    *   Action:
        *   Initialize `argparse.ArgumentParser`.
        *   Add arguments:
            *   `query`: Positional argument for the user's query.
            *   `--csv-file` (`-f`): Required, path to the input CSV file.
            *   `--output-file` (`-o`): Optional, path to save the `xsv` command output.
            *   `--api-key`: Optional, to override environment variable.
        *   Parse arguments.
        *   Validate `csv_file_path` exists.
        *   Retrieve API key (from args or `os.getenv`). Handle missing key.
        *   Initialize the LLM client (e.g., `Anthropic(api_key=...)`).
        *   Call `run_xsv_analyzer_agent` with parsed arguments.
        *   Print the final result or error message from `run_xsv_analyzer_agent`.
        *   Call a function `display_token_usage(TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS)` (to be implemented in Phase 1 or 6).

**Phase 6: Refinement and Helper Functions**

    *   Signature: `display_token_usage(input_tokens: int, output_tokens: int)`
    *   Action: Use `rich.Table` to display input, output, and total tokens, and potentially estimated cost.

2.  **Error Handling:**
    *   Action: Review all functions and add robust `try-except` blocks.
    *   Action: Ensure user-friendly error messages are logged and returned.

3.  **Logging:**
    *   Action: Use `console.log()` for debug/info messages throughout the script.
    *   Action: Use `console.print()` with `rich.Panel` or `Syntax` for user-facing output.

4.  **Code Comments and Readability:**
    *   Action: Add comments explaining complex logic.
    *   Action: Ensure code follows PEP 8 guidelines.

5.  **Testing:**
    *   Action: Manually test with various user queries and CSV files.
        *   Simple queries (e.g., "show headers").
        *   Filtering queries.
        *   Queries requiring output to a file.
        *   Invalid queries or non-existent CSV files.
    *   Action: Test `xsv` not found scenario.

---
This plan provides a structured approach for the AI coding agent. It breaks down the SFA creation into manageable phases and specific actions, making it easier for the AI to implement. Remember to instruct the AI to ask for clarification if any part of the plan is unclear.