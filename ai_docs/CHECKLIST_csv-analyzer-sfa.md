# Checklist for sfa_xsv_analyzer_v1.py Implementation

## Phase 1: Setup and Boilerplate
- [x] Create file: `sfa_xsv_analyzer_v1.py`
- [x] Add UV Shebang
- [x] Add `/// script ... ///` block with dependencies: `rich`, `anthropic`, `openai`, `google-generativeai`
- [x] Add comprehensive main docstring:
    - [x] Describe purpose of the SFA
    - [x] Provide example CLI usage (e.g., `uv run sfa_xsv_analyzer_v1.py "show first 5 rows" -f data.csv -p openai`)
    - [x] **Clearly state that API keys MUST be set as environment variables (e.g., `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`) and list them.**
    - [x] State prerequisites (e.g., `xsv` must be installed and in PATH)
- [x] Import standard modules: `os`, `sys`, `argparse`, `subprocess`, `json`, `textwrap`
- [x] Import `rich` components: `Console`, `Panel`, `Syntax`, `Table`
- [x] Import LLM SDKs: `Anthropic` from `anthropic`, `OpenAI` from `openai`, `GenerativeModel` from `google.generativeai` (or `import google.generativeai as genai`).
- [x] Initialize `console = Console()`
- [x] Define constants:
    - [x] `DEFAULT_MODEL_ANTHROPIC = "claude-3-haiku-20240307"`
    - [x] `DEFAULT_MODEL_OPENAI = "gpt-4o-mini"`
    - [x] `DEFAULT_MODEL_GOOGLE = "gemini-1.5-flash-latest"`
    - [x] `API_MAX_RETRIES = 3`, `API_RETRY_WAIT = 5` (seconds).
    - [x] `TOTAL_INPUT_TOKENS = 0`, `TOTAL_OUTPUT_TOKENS = 0`.
- [x] Implement `if __name__ == "__main__": main()` guard

## Phase 2: `xsv` Command Execution Function
- [x] Define `execute_xsv_command(xsv_command_str: str) -> Tuple[bool, str, str]`
- [x]     Log command execution
- [x]     Use `subprocess.run()` (shell=True, capture output, text=True)
- [x]     Check `returncode` for success/failure
- [x]     Handle `FileNotFoundError` for `xsv`
- [x]     Log outcome
- [x]     Return `(success_status, stdout, stderr)`

## Phase 3: LLM Integration for `xsv` Command Generation
- [x] Define `XSV_COMMAND_GENERATION_PROMPT_TEMPLATE` (XML-style, generic)
- [x] Define `call_anthropic_llm(prompt: str, api_key: str, model_name: str) -> Tuple[Optional[str], Optional[int], Optional[int]]`
    - [x] Initialize Anthropic client
    - [x] API call with retries and error handling
    - [x] Extract response text
    - [x] Report/estimate input/output tokens
    - [x] Return `(response_text, input_tokens, output_tokens)`
- [x] Define `call_openai_llm(prompt: str, api_key: str, model_name: str) -> Tuple[Optional[str], Optional[int], Optional[int]]`
    - [x] Initialize OpenAI client
    - [x] API call with retries and error handling
    - [x] Extract response text
    - [x] Report/estimate input/output tokens
    - [x] Return `(response_text, input_tokens, output_tokens)`
- [x] Define `call_google_llm(prompt: str, api_key: str, model_name: str) -> Tuple[Optional[str], Optional[int], Optional[int]]`
    - [x] Initialize Google GenAI client
    - [x] API call with retries and error handling
    - [x] Extract response text
    - [x] Report/estimate input/output tokens
    - [x] Return `(response_text, input_tokens, output_tokens)`
- [x] Define `get_xsv_command_from_ai(user_query: str, csv_file_path: str, llm_provider: str, api_key: str, model_name: str) -> Optional[str]`
    - [x] Format `XSV_COMMAND_GENERATION_PROMPT_TEMPLATE`
    - [x] Dispatch to `call_anthropic_llm`, `call_openai_llm`, or `call_google_llm` based on `llm_provider`
    - [x] Update global token counters (best effort)
    - [x] Extract and sanitize `xsv` command from LLM response
    - [x] Log raw response and extracted command
    - [x] Return command string or `None`

## Phase 4: Main Agent Logic Function
- [x] Define `run_xsv_analyzer_agent(user_query: str, csv_file_path: str, llm_provider: str, api_key: str, model_name: str, output_file_path: Optional[str] = None) -> Tuple[Optional[str], int, int]`
    - [x] Log agent start
    - [x] Call `get_xsv_command_from_ai`
    - [x] Handle no command generated scenario
    - [x] If command generated:
        - [x] Append ` > {output_file_path}` if applicable and not already in command
        - [x] Call `execute_xsv_command`
        - [x] Handle `execute_xsv_command` success (display output)
        - [x] Handle `execute_xsv_command` failure (display error)
    - [x] Return `(result_string_or_None, TOTAL_INPUT_TOKENS, TOTAL_OUTPUT_TOKENS)`

## Phase 5: Command-Line Interface and Execution
- [x] Implement `main()` function:
    - [x] Initialize `argparse.ArgumentParser`
        - [x] Ensure a descriptive `description` for the parser.
        - [x] Add `query` argument (positional) with clear `help` text.
        - [x] Add `--csv-file` / `-f` argument (required) with clear `help` text.
        - [x] Add `--llm-provider` / `-p` argument (required, choices: `anthropic`, `openai`, `google`) with clear `help` text.
        - [x] Add `--output-file` / `-o` argument (optional) with clear `help` text.
        - [x] Add `--model-name` / `-m` argument (optional) with clear `help` text (e.g., "Override default model for the selected provider. API keys are sourced from environment variables like OPENAI_API_KEY.").
        - [x] **Ensure overall CLI help message (`-h`) is comprehensive, user-friendly, and clearly states API keys are sourced from environment variables.**
    - [x] Parse arguments
    - [x] Validate `csv_file_path` existence
    - [x] **Retrieve API key from the appropriate environment variable (e.g., `os.getenv("OPENAI_API_KEY")`) based on `llm_provider`. If not set, print an error and exit.**
    - [x] Determine model name (CLI arg > default) for selected provider.
    - [x] Call `run_xsv_analyzer_agent` (the `api_key` parameter will be passed from the retrieved env var).
    - [x] Print final result or error.
    - [x] Call `display_token_usage`.

## Phase 6: Refinement and Helper Functions
- [x] Implement `display_token_usage(input_tokens: int, output_tokens: int)`
    - [x] Use `rich.Table` for formatted output
    - [x] Acknowledge best-effort nature of token counts
- [x] Review and add robust `try-except` blocks throughout
- [x] Ensure user-friendly error messages (logged and returned)
- [x] Use `console.log()` for debug/info, `console.print()` for user output
- [x] Add code comments for complex logic
- [x] Ensure PEP 8 compliance
- [ ] Perform manual testing:
    - [ ] Test with Anthropic provider
    - [ ] Test with OpenAI provider
    - [ ] Test with Google provider
    - [ ] Test various query types (simple, filter, output to file)
    - [ ] Test with non-existent CSV
    - [ ] Test API key handling (env var, missing key for selected provider)
    - [ ] Test `xsv` not found scenario
    - [ ] Test default model usage vs. CLI model override