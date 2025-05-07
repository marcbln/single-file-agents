# Plan: Automatic Delimiter Detection for sfa_xsv_analyzer_v1.py

This document outlines the plan to enhance `sfa_xsv_analyzer_v1.py` by adding automatic CSV/TSV delimiter detection. This will improve user experience by removing the need for a manual delimiter flag in most cases.

## 1. Goal

Modify `sfa_xsv_analyzer_v1.py` to:
1.  Automatically detect the delimiter used in the input CSV/TSV file.
2.  Inform the LLM about the detected delimiter so it can construct the correct `xsv` command.

## 2. Key Changes

### 2.1. New Function: `detect_delimiter`

A new function will be added to handle delimiter detection.

```python
import csv # Add this import at the top of the file

# ... other imports ...

# Potentially place this function near other utility functions or before main logic
def detect_delimiter(file_path: str, num_lines_to_sample: int = 5, default_delimiter: str = ',') -> str:
    """
    Detects the delimiter of a CSV/TSV file by sniffing a sample of its content.

    Args:
        file_path: Path to the CSV/TSV file.
        num_lines_to_sample: Number of lines to read for sniffing.
        default_delimiter: Delimiter to return if detection fails.

    Returns:
        The detected delimiter character (e.g., ',', '\t', ';') or the default.
    """
    console.log(f"Attempting to detect delimiter for file: {file_path}")
    try:
        with open(file_path, 'r', newline='', encoding='utf-8') as f:
            sample_lines = "".join([f.readline() for _ in range(num_lines_to_sample)])
            if not sample_lines:
                console.log(f"File '{file_path}' is empty or too short to sample. Using default delimiter '{default_delimiter}'.", style="yellow")
                return default_delimiter

            sniffer = csv.Sniffer()
            # Provide a list of common delimiters to aid the sniffer
            dialect = sniffer.sniff(sample_lines, delimiters=',;\t|')
            detected_delimiter = dialect.delimiter
            console.log(f"Detected delimiter: '{detected_delimiter}' (repr: {repr(detected_delimiter)})", style="green")
            return detected_delimiter
    except csv.Error:
        console.log(f"Could not automatically detect delimiter for '{file_path}'. Using default: '{default_delimiter}'.", style="yellow")
        return default_delimiter
    except FileNotFoundError:
        console.log(f"File not found during delimiter detection: '{file_path}'. Using default: '{default_delimiter}'.", style="bold red")
        return default_delimiter # Or raise the error if main validation hasn't happened yet
    except Exception as e:
        console.log(f"An unexpected error occurred during delimiter detection for '{file_path}': {e}. Using default: '{default_delimiter}'.", style="bold red")
        return default_delimiter
```

**Placement**: This function can be placed after the import statements and before the `XSV_COMMAND_GENERATION_PROMPT_TEMPLATE` or other helper functions.

### 2.2. Modify `main()` function

The `main()` function will be updated to call `detect_delimiter` and pass the result.

**Current `main()` snippet (around line 585):**
```python
    _result_output, current_run_input_tokens, current_run_output_tokens = run_xsv_analyzer_agent(
        user_query=args.query,
        csv_file_path=args.csv_file,
        llm_provider=args.llm_provider,
        api_key=api_key,
        model_name=model_name_to_use,
        output_file_path=args.output_file
    )
```

**Proposed changes to `main()`:**
```python
    # ... (after API key retrieval and model name determination) ...

    # Validate csv_file_path (already exists around line 546)
    if not os.path.exists(args.csv_file):
        console.print(Panel(f"Error: Input CSV file not found at '{args.csv_file}'", title="[bold red]File Not Found[/bold red]", expand=False))
        sys.exit(1)

    # NEW: Detect delimiter
    detected_delimiter = detect_delimiter(args.csv_file)
    console.log(f"Using delimiter: '{detected_delimiter}' (repr: {repr(detected_delimiter)}) for LLM prompt and xsv command generation.")

    # ... (reset token counters) ...
    
    # Call run_xsv_analyzer_agent, passing the detected_delimiter
    _result_output, current_run_input_tokens, current_run_output_tokens = run_xsv_analyzer_agent(
        user_query=args.query,
        csv_file_path=args.csv_file,
        llm_provider=args.llm_provider,
        api_key=api_key,
        model_name=model_name_to_use,
        output_file_path=args.output_file,
        detected_delimiter=detected_delimiter # NEW argument
    )
    # ... (rest of main) ...
```

### 2.3. Modify `run_xsv_analyzer_agent()` function

This function needs to accept `detected_delimiter` and pass it to `get_xsv_command_from_ai`.

**Current signature (around line 376):**
```python
def run_xsv_analyzer_agent(
    user_query: str,
    csv_file_path: str,
    llm_provider: str,
    api_key: str,
    model_name: str,
    output_file_path: Optional[str] = None
) -> Tuple[Optional[str], int, int]:
```

**Proposed changes:**
*   Add `detected_delimiter: str` to the signature.
*   Pass `detected_delimiter` to `get_xsv_command_from_ai`.

```python
def run_xsv_analyzer_agent(
    user_query: str,
    csv_file_path: str,
    llm_provider: str,
    api_key: str,
    model_name: str,
    output_file_path: Optional[str] = None,
    detected_delimiter: str = ',' # NEW parameter with default
) -> Tuple[Optional[str], int, int]:
    # ...
    generated_xsv_command = get_xsv_command_from_ai(
        user_query, csv_file_path, llm_provider, api_key, model_name, detected_delimiter # Pass new arg
    )
    # ...
```

### 2.4. Modify `get_xsv_command_from_ai()` function

This function needs to accept `detected_delimiter` and use it in the prompt.

**Current signature (around line 308):**
```python
def get_xsv_command_from_ai(user_query: str, csv_file_path: str, llm_provider: str, api_key: str, model_name: str) -> Optional[str]:
```

**Proposed changes:**
*   Add `detected_delimiter: str` to the signature.
*   Update the `prompt.format()` call.

```python
def get_xsv_command_from_ai(user_query: str, csv_file_path: str, llm_provider: str, api_key: str, model_name: str, detected_delimiter: str) -> Optional[str]: # NEW parameter
    # ...
    console.log(
        f"Attempting to generate xsv command using {llm_provider}/{model_name} "
        f"for query: '{user_query}' on file: '{csv_file_path}' with detected delimiter: '{repr(detected_delimiter)}'" # Log delimiter
    )

    prompt = XSV_COMMAND_GENERATION_PROMPT_TEMPLATE.format(
        user_query=user_query,
        csv_file_path=csv_file_path,
        detected_delimiter=detected_delimiter # NEW format argument
    )
    # ...
```

### 2.5. Update `XSV_COMMAND_GENERATION_PROMPT_TEMPLATE`

The prompt template needs to be updated to inform the LLM about the detected delimiter.

**Current template (around line 73):**
```python
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
...
</examples>

Your xsv command:
"""
```

**Proposed changes to the template:**
*   Add a placeholder for the detected delimiter information.
*   Modify instruction 9 to reflect that the delimiter is pre-detected.

```python
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
    For example, if detected_delimiter is '\t', use `xsv ... -d "\t" ...`.
    If the user's query *explicitly* specifies a different delimiter, prioritize the user's specification
    and use that delimiter with the -d flag. Otherwise, rely on the pre-detected one.
10. If the user asks for output formatting (e.g., JSON, pretty table), use appropriate
    xsv subcommands or combinations (e.g., `xsv search ... | xsv json`).
</instructions>

<user_query>{user_query}</user_query>

<csv_file_path>{csv_file_path}</csv_file_path>

<detected_delimiter_info>
The file's delimiter has been pre-detected as: '{detected_delimiter}' (represented as a Python string).
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
```
*(Note: The `repr()` of the delimiter might be useful for the LLM to correctly interpret escape characters like `\t`.)*
*Self-correction: The prompt should directly use the delimiter string, not its `repr()`, to avoid confusion for the LLM. The examples should show how to handle special characters like tab (`\t`). The `detect_delimiter` function itself will return the character, e.g. `\t`.*
*Corrected prompt section for `detected_delimiter_info` and instruction 9:*
```python
# ... (within XSV_COMMAND_GENERATION_PROMPT_TEMPLATE)
# Instruction 9:
# 9. The script has pre-detected the delimiter for the input file as: '{detected_delimiter}'.
#    You MUST use this delimiter in your 'xsv' command by including the `-d "{detected_delimiter}"` option
#    if the detected delimiter is NOT a comma (e.g., for tab, semicolon, pipe).
#    For example, if detected_delimiter is a tab character, use `xsv ... -d "\t" ...`.
#    If the user's query *explicitly* specifies a different delimiter, prioritize the user's specification
#    and use that delimiter with the -d flag. Otherwise, rely on the pre-detected one.
#
# <detected_delimiter_info>
# The file's delimiter has been pre-detected as: '{detected_delimiter}'.
# If this is not a comma, ensure you use the -d option (e.g., -d "\t" for tab, -d ";" for semicolon).
# </detected_delimiter_info>
```

## 3. Testing Considerations
*   Test with standard CSV files (comma-delimited).
*   Test with TSV files (tab-delimited).
*   Test with semicolon-delimited files.
*   Test with pipe-delimited files.
*   Test with files having few lines (less than `num_lines_to_sample`).
*   Test with empty files.
*   Test with files where the user query *also* specifies a delimiter, to ensure the LLM prioritizes correctly if instructed.

## 4. Summary
This plan introduces a robust automatic delimiter detection mechanism, making the `sfa_xsv_analyzer_v1.py` script more versatile and easier to use with various XSV file formats without manual intervention for common delimiters.