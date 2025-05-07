# Plan: XSV Analyzer v2 - Answer Synthesis

**Date:** 2025-07-05

**Objective:** Modify the `sfa_xsv_analyzer_v2.py` script to interpret the output of the `xsv` command using an LLM and provide a concise, synthesized answer to the user's original query, rather than just displaying the raw `xsv` output.

## Background

The current `sfa_xsv_analyzer_v2.py` script successfully uses an LLM to generate an `xsv` command based on a user's natural language query and then executes that command. However, it directly outputs the raw results from `xsv` (e.g., matching CSV rows). Users have indicated a preference for a more direct, human-readable answer to their query (e.g., "Yes, 'soap' is in the list" instead of a dump of rows containing "soap").

## Proposed Changes

The core idea is to introduce a new phase after the `xsv` command has been executed. This phase will involve an additional, distinct LLM call dedicated to interpreting the `xsv` output in the context of the original user query.

### Phase 1: Command Generation (Iterative) - Existing

*   **No changes to the current logic.**
*   The existing loop in `run_xsv_analyzer_agent_v2()` (around lines 382-458) that uses `litellm.completion` with the `TOOL_GET_XSV_SUBCOMMAND_HELP` tool will remain.
*   This loop allows the LLM to iteratively refine the `xsv` command, potentially making multiple tool calls, up to `MAX_INTERACTION_TURNS`.

### Phase 2: Command Execution - Existing

*   **No changes to the current logic.**
*   The call to `execute_xsv_command()` (around line 465) will remain as is, executing the `xsv` command generated in Phase 1.

### Phase 3: Answer Synthesis (New)

This new phase will be added after Phase 2.

1.  **New Function: `synthesize_answer_from_xsv_output`**
    *   **Purpose:** To take the raw output from the `xsv` command and the original user query, and use an LLM to generate a direct, human-readable answer.
    *   **Inputs:**
        *   `user_query` (str): The original natural language question from the user.
        *   `xsv_output_data` (str): The raw string output from the executed `xsv` command.
        *   `model_name` (str): The LiteLLM model identifier (e.g., "gpt-4o-mini").
        *   `original_file_name` (str): The base name of the CSV file being queried (for context).
    *   **Logic:**
        1.  Construct a specific system prompt for this LLM call. The prompt will instruct the LLM to:
            *   Act as an analytical assistant.
            *   Carefully review the `user_query`.
            *   Carefully examine the provided `xsv_output_data`.
            *   Generate a direct, concise, natural-language answer to the `user_query` based *solely* on the provided `xsv_output_data`.
            *   If `xsv_output_data` is empty, clearly state that no data was returned by the command or that the query yielded no results.
            *   If `xsv_output_data` contains rows/information relevant to the query (e.g., for a search query like "is soap in the list?", if rows are present, it implies "soap" was found), the answer should reflect this finding (e.g., "Yes, 'soap' appears to be in the list based on the data found.").
            *   If `xsv_output_data` is empty or does not contain information that directly answers the query, the answer should state that the item was likely not found or the query didn't produce relevant results (e.g., "No, 'soap' does not appear to be in the list based on the data returned.").
            *   Acknowledge if the `xsv_output_data` appears to have been truncated (e.g., if it contains the `XSV_TRUNCATION_MESSAGE`).
        2.  Make a *single* `litellm.completion` call. This call will **not** use any tools; its purpose is purely text generation for the answer.
        3.  Extract the synthesized textual answer from the LLM's response.
        4.  Track and return the input and output tokens used specifically for this answer synthesis call.
    *   **Outputs:** A tuple `(synthesized_answer: Optional[str], input_tokens: int, output_tokens: int)`.

2.  **Integration into `run_xsv_analyzer_agent_v2` function:**
    *   This integration will occur after the `execute_xsv_command()` call (after line 465).
    *   A new `console.rule` (e.g., "[bold blue]Synthesizing Final Answer[/bold blue]") will delineate this phase.
    *   If the `xsv` command was successful (`success is True`) and `stdout` (the `xsv_output_data`) is available and not empty:
        1.  Call the new `synthesize_answer_from_xsv_output()` function.
        2.  Update the global `TOTAL_INPUT_TOKENS` and `TOTAL_OUTPUT_TOKENS` with the tokens used by this synthesis call.
        3.  If `synthesize_answer_from_xsv_output()` returns a valid `synthesized_answer`:
            *   Print this answer to the console, perhaps using a `Panel` titled "[bold green]Synthesized Answer[/bold green]".
            *   If `output_file_path` is specified, save this `synthesized_answer` to the file (instead of the raw `xsv` output).
        4.  If `synthesize_answer_from_xsv_output()` fails to return an answer (e.g., due to an API error during synthesis):
            *   Print a message indicating that answer synthesis failed.
            *   Fall back to printing the raw `xsv_stdout` (as the script currently does, but perhaps with a title like "[bold yellow]Raw XSV Output (Synthesis Failed)[/bold yellow]").
            *   If `output_file_path` is specified, save the raw `xsv_stdout` to the file in this fallback scenario.
    *   If the `xsv` command was successful but produced no `stdout`:
        *   Print a message like "[No output from xsv command to synthesize an answer from.]".
        *   If `output_file_path` is specified, save an appropriate message or empty string.
    *   If the `xsv` command itself failed:
        *   The existing error handling (printing `stderr` and any partial `stdout`) will remain. No synthesis attempt will be made.

### Token Usage

*   The existing `display_token_usage()` function will correctly reflect the total tokens used, as the global counters will be updated by both the command generation phase and the new answer synthesis phase.

## Workflow Diagram

```mermaid
graph TD
    A[Start Agent] --> B{Input: User Query, File Path};
    B --> C_Phase1[Phase 1: LLM Generates XSV Command (Iterative, Max Turns)];
    C_Phase1 -- Uses xsv help & tool calls --> C_Phase1;
    C_Phase1 -- Final XSV Command Determined --> D_Phase2[Phase 2: Execute XSV Command];
    D_Phase2 -- XSV Output & Success? --> E_Phase3[Phase 3: LLM Synthesizes Final Answer (Single Call)];
    D_Phase2 -- XSV Fails/No Output --> F[Show XSV Error / No Output Message];
    E_Phase3 -- Answer Synthesized --> G[Display Synthesized Answer];
    E_Phase3 -- Synthesis Fails --> H[Display Raw XSV Output (Fallback)];
    G --> I{Save Synthesized Answer to File?};
    H --> J{Save Raw XSV Output to File?};
    F --> K[End];
    I --> K;
    J --> K;
```

## Impact Summary

*   **User Experience:** Users will receive a direct, natural-language answer to their queries instead of raw data dumps.
*   **LLM Calls:** An additional LLM call will be introduced for answer synthesis. The total LLM calls will be 1 (for synthesis) + (1 to `MAX_INTERACTION_TURNS` for command generation).
*   **Output File:** If an output file is specified, it will now contain the synthesized answer by default, falling back to raw `xsv` output if synthesis fails.
*   **Code Changes:** Requires adding a new function (`synthesize_answer_from_xsv_output`) and modifying the main `run_xsv_analyzer_agent_v2` function to incorporate this new phase.