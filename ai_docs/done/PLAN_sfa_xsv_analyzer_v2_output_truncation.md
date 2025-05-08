# Plan: XSV Analyzer v2 Output Truncation

**Objective:** Modify the script [`sfa_xsv_analyzer_v2.py`](../../sfa_xsv_analyzer_v2.py) to limit the size of `xsv` command output returned to the LLM and inform the LLM about this limitation.

**Key Changes:**

1.  **Introduce Constants (around [`sfa_xsv_analyzer_v2.py:46`](../../sfa_xsv_analyzer_v2.py:46)):**
    *   `XSV_OUTPUT_MAX_CHARS = 4000`
    *   `XSV_TRUNCATION_MESSAGE = "... [Output truncated]"`

2.  **Modify `execute_xsv_command` Function (around [`sfa_xsv_analyzer_v2.py:261`](../../sfa_xsv_analyzer_v2.py:261)):**
    *   After obtaining `stdout_str` (around [`sfa_xsv_analyzer_v2.py:268`](../../sfa_xsv_analyzer_v2.py:268)), if `len(stdout_str) > XSV_OUTPUT_MAX_CHARS`, truncate it and append `XSV_TRUNCATION_MESSAGE`.
        *   Truncation logic:
            ```python
            if len(stdout_str) > XSV_OUTPUT_MAX_CHARS:
                cutoff_point = XSV_OUTPUT_MAX_CHARS - len(XSV_TRUNCATION_MESSAGE)
                stdout_str = stdout_str[:cutoff_point] + XSV_TRUNCATION_MESSAGE
            ```

3.  **Update System Prompt (within `run_xsv_analyzer_agent_v2` function, around [`sfa_xsv_analyzer_v2.py:322`](../../sfa_xsv_analyzer_v2.py:322)):**
    *   Add a new point to the "Key Information" or "Instructions" section stating:
        *   Output from `xsv` commands will be truncated if it exceeds 4000 characters.
        *   Truncated output will end with `"... [Output truncated]"`.
        *   The LLM should be mindful of this for commands producing large outputs.
        *   Remind the LLM to use the `get_xsv_subcommand_help` tool for alternatives.

**Mermaid Diagram of Changes:**

```mermaid
graph TD
    A[Start: User Task] --> B{Modify sfa_xsv_analyzer_v2.py};
    B --> C[Define Constants];
    C --> C1[Add XSV_OUTPUT_MAX_CHARS = 4000];
    C --> C2[Add XSV_TRUNCATION_MESSAGE = "... [Output truncated]"];
    B --> D[Modify execute_xsv_command function];
    D --> D1[Get stdout_str from xsv process];
    D1 --> D2{len(stdout_str) > XSV_OUTPUT_MAX_CHARS?};
    D2 -- Yes --> D3[Truncate stdout_str];
    D3 --> D4[Append XSV_TRUNCATION_MESSAGE];
    D4 --> D5[Return modified stdout_str];
    D2 -- No --> D5;
    B --> E[Update system_prompt in run_xsv_analyzer_agent_v2];
    E --> E1[Add info about output truncation (4000 chars)];
    E1 --> E2[Mention XSV_TRUNCATION_MESSAGE];
    E2 --> E3[Advise LLM to consider this for large outputs];
    E3 --> E4[Remind LLM about get_xsv_subcommand_help tool for alternatives];
    C1 & C2 & D5 & E4 --> F[End: Script Modified];