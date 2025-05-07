# Plan: sfa_xsv_analyzer_v2.py

**Objective:** Develop `sfa_xsv_analyzer_v2.py`, an advanced version of the xsv analyzer agent. This version will use `litellm` to abstract LLM interactions, incorporate the main `xsv -h` output into the system prompt, and allow the LLM to request help for specific `xsv` subcommands using tool-calling.

**Target LLM for Initial Development:** OpenAI's `gpt-4o-mini`
**Target Filename:** `sfa_xsv_analyzer_v2.py`
**`xsv -h` Integration:** Include as part of the system prompt.
**Subcommand Help Tool:** Takes `subcommand_name` as an argument.

---

## Plan Details:

**1. Project Setup & Core Dependencies:**
    *   Create a new Python script file: `sfa_xsv_analyzer_v2.py`.
    *   Define script dependencies in the `/// script` block:
        *   `litellm` (for LLM abstraction and tool calling).
        *   `openai` (as `litellm` might require the provider's SDK for certain functionalities, and we're targeting `gpt-4o-mini`).
        *   `rich` (for enhanced console output, reusing from v1).
    *   Standard library imports: `os`, `sys`, `argparse`, `subprocess`, `json`, `textwrap`, `csv`.

**2. Configuration & Constants:**
    *   **LLM Configuration:**
        *   Default model: `gpt-4o-mini`.
        *   API keys will be managed via environment variables (e.g., `OPENAI_API_KEY`), which `litellm` typically reads automatically.
    *   **Retry Logic:** Constants for API call retries and wait times (can be adapted from v1 or use `litellm`'s built-in retry mechanisms if available and suitable).
    *   **Global Variables (if necessary):**
        *   `XSV_MAIN_HELP_OUTPUT`: To store the output of `xsv -h` once fetched.

**3. Fetching and Managing `xsv` Help Content:**
    *   **`get_xsv_main_help()` function:**
        *   Purpose: Executes `xsv -h` using `subprocess.run()`.
        *   Returns: The standard output (help text) as a string.
        *   Error Handling: Catches `FileNotFoundError` if `xsv` is not installed and other potential `subprocess` errors.
        *   Memoization: This function should ideally run once and cache its result (e.g., in the `XSV_MAIN_HELP_OUTPUT` global variable) to avoid repeated `subprocess` calls.
    *   **`execute_get_xsv_subcommand_help(subcommand_name: str)` function:**
        *   Purpose: Executes `xsv <subcommand_name> -h` (e.g., `xsv stats -h`).
        *   Input: `subcommand_name` (string).
        *   Returns: The help text for the specified subcommand.
        *   Error Handling: Similar to `get_xsv_main_help()`.

**4. `litellm` Integration and Tool Definition:**
    *   **System Prompt Construction:**
        *   A function will dynamically create the system prompt for `litellm`.
        *   Content:
            *   Role definition: "You are an expert in using the 'xsv' command-line tool..."
            *   Instructions on how to use the `get_xsv_subcommand_help` tool.
            *   The full output of `xsv -h` (obtained from `get_xsv_main_help()`).
            *   Guidance on providing only the final `xsv` command string as output when ready.
    *   **Tool Definition for `litellm` (OpenAI-compatible format):**
        ```json
        {
            "type": "function",
            "function": {
                "name": "get_xsv_subcommand_help",
                "description": "Fetches the help documentation for a specific xsv subcommand (e.g., 'stats', 'slice', 'search'). Use this if you need more details about a subcommand's options or usage.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subcommand_name": {
                            "type": "string",
                            "description": "The name of the xsv subcommand to get help for (e.g., 'stats', 'count')."
                        }
                    },
                    "required": ["subcommand_name"]
                }
            }
        }
        ```
    *   **Mapping Tool Calls to Python Functions:**
        *   A dictionary or conditional logic will map the tool name `get_xsv_subcommand_help` to the Python function `execute_get_xsv_subcommand_help`.

**5. Core Agent Logic (`run_xsv_analyzer_agent_v2`):**
    *   Initialize `XSV_MAIN_HELP_OUTPUT` by calling `get_xsv_main_help()` at the beginning.
    *   **Message History Management:** Maintain a list of messages for the conversation with the LLM.
    *   **Initial User Message:**
        *   Include the user's natural language query.
        *   Include the path to the CSV file.
        *   Include the auto-detected delimiter (from v1's `detect_delimiter` function).
    *   **Main Interaction Loop with `litellm`:**
        1.  Construct the message list (system prompt, previous interactions, current user/tool message).
        2.  Call `litellm.completion(model="gpt-4o-mini", messages=messages, tools=[...], tool_choice="auto")`.
        3.  **Process LLM Response:**
            *   **If `tool_calls` are present:**
                *   For each tool call (expecting `get_xsv_subcommand_help`):
                    *   Extract `subcommand_name` from `tool_call.function.arguments`.
                    *   Execute `execute_get_xsv_subcommand_help(subcommand_name)`.
                    *   Append the assistant's message (containing the tool call) and a new "tool" role message (containing the `tool_call_id` and the help text as `content`) to the message history.
                *   Continue the loop (go back to step 1).
            *   **If no `tool_calls` (LLM provides direct answer/command):**
                *   Extract the generated `xsv` command string from the assistant's message.
                *   Proceed to execute this command.
                *   Break the loop.
            *   **Error/Empty Response:** Handle cases where the LLM doesn't call a tool and doesn't provide a command.
    *   **Final `xsv` Command Execution:**
        *   Use the existing `execute_xsv_command` function (from v1, possibly with minor adaptations) to run the LLM-generated command.
    *   **Output and Token Tracking:**
        *   Display results using `rich` components.
        *   Track token usage using information from `litellm`'s response object.

**6. Reusing and Adapting Components from v1:**
    *   **Argument Parsing (`argparse`):**
        *   Modify to accept `--model` (passed to `litellm`) and remove `--provider`.
        *   Keep `--file`, `--query`, `--delimiter` (optional, as auto-detection is primary), `--output-file`.
    *   **`ensure_utf8_file(original_file_path)`:** Retain for robust file handling.
    *   **`detect_delimiter(file_path)`:** Retain and provide its output as context to the LLM.
    *   **`execute_xsv_command(xsv_command_str)`:** Retain for executing the final command.
    *   **`rich` Console Output:** Maintain for user-friendly display of logs, commands, and results.

**7. Code to be Removed/Replaced from v1:**
    *   Direct LLM client initializations (Anthropic, OpenAI, Google).
    *   Functions: `call_anthropic_llm`, `call_openai_llm`, `call_google_llm`.
    *   The static `XSV_COMMAND_GENERATION_PROMPT_TEMPLATE` (will be replaced by dynamic system prompt and conversational interaction).
    *   The old `get_xsv_command_from_ai` function will be effectively replaced by the new `litellm` interaction loop.

**8. Error Handling and Edge Cases:**
    *   Comprehensive error handling for `litellm.completion()` calls (API errors, rate limits).
    *   Failures in `xsv` execution (main help, subcommand help, final command).
    *   LLM repeatedly failing to generate a command or getting stuck in a tool-call loop (implement a max interaction turns).
    *   `xsv` not installed (initial check when fetching main help).

**9. Workflow Diagram:**

```mermaid
graph TD
    A[Start: User runs sfa_xsv_analyzer_v2.py with query & file] --> B(Parse CLI Arguments);
    B --> C{Fetch `xsv -h` (Store Globally)};
    C --> D[Ensure File UTF-8 & Detect Delimiter];
    D --> E[Prepare Initial Messages: System Prompt (with `xsv -h`) + User Query (with file info, delimiter)];
    E --> F[Loop: Call `litellm.completion()` with `get_xsv_subcommand_help` tool];
    F --> G{LLM Response: Tool Call for `get_xsv_subcommand_help`?};
    G -- Yes --> H[Extract `subcommand_name`];
    H --> I[Call `execute_get_xsv_subcommand_help(subcommand_name)`];
    I --> J[Append Assistant's Tool Call & Tool's Help Output to Messages];
    J --> F;
    G -- No (Final `xsv` command from LLM) --> K[Extract Final `xsv` Command String];
    K --> L[Call `execute_xsv_command(final_command)`];
    L --> M{Command Successful?};
    M -- Yes --> N[Display Stdout / Save to File];
    M -- No --> O[Display Stderr];
    N --> P[End];
    O --> P;