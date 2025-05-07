# Plan: Address LLM JSON Formatting Issue in sfa_xsv_analyzer_v2.py

Date: 2025-07-05

## 1. Problem Analysis

The `sfa_xsv_analyzer_v2.py` script experiences issues where the Language Model (LLM) consistently wraps its JSON responses in markdown code fences (e.g., ` ```json ... ``` `). This occurs despite system prompts instructing it to return raw JSON and corrective re-prompts when a `json.JSONDecodeError` is encountered.

The script's error detection and re-prompting logic for JSON format errors are in place, but the LLM fails to comply with the formatting instructions.

## 2. Proposed Solution

A multi-layered approach is proposed to make the system more robust and to better guide the LLM:

### Phase 1: Immediate Mitigation - Output Post-processing

*   **Action:** Modify the script to attempt to strip common markdown code fences (like ` ```json ` and ` ``` `) from the `llm_content_str` *before* passing it to `json.loads()`.
*   **Rationale:** This is a pragmatic fix that can immediately handle the observed error pattern, making the agent more resilient even if the LLM continues this behavior occasionally.

### Phase 2: Enhanced Prompting & Re-prompting

*   **Action (System Prompt):** Strengthen the initial system prompt (around line 478 in `sfa_xsv_analyzer_v2.py`) to be even more explicit.
    *   Example addition: "Your JSON response must be raw text, starting directly with `{` and ending with `}`. Do NOT wrap it in markdown code fences (e.g., \`\`\`json ... \`\`\`)."
*   **Action (Re-prompt Message):** When a `JSONDecodeError` occurs, make the corrective user message (around line 637 in `sfa_xsv_analyzer_v2.py`) more specific.
    *   Example change: Instead of "Your response was not in the expected JSON format," use "Your response appeared to be wrapped in markdown (e.g., \`\`\`json ... \`\`\`). Please provide only the raw JSON object itself, starting with { and ending with }."
*   **Rationale:** These changes aim to provide clearer, more targeted instructions to the LLM, both initially and during correction, to help it avoid the formatting mistake.

### Phase 3: (If Necessary) Few-Shot Example in Prompt

*   **Action:** If the above changes don't fully resolve the issue, consider adding a concise example of a *correct* and *incorrect* JSON response format within the system prompt.
*   **Rationale:** Explicit examples (few-shot learning) can be very effective in guiding LLM output format.

## 3. Visual Plan (Mermaid Diagram)

```mermaid
graph TD
    A[Start: LLM Interaction] --> B{LLM provides response};
    B --> C{Response has tool_calls?};
    C -- Yes --> D[Process Tool Calls];
    D --> A;
    C -- No --> E[Get llm_content_str];
    E --> F[Proposed: Strip Markdown Fences from llm_content_str];
    F --> G{Attempt json.loads()};
    G -- Success --> H{Valid command/error?};
    H -- Yes, Command --> I[Execute XSV Command];
    H -- Yes, Error --> J[Report LLM Error];
    H -- No (Invalid Structure) --> K[Handle Invalid JSON Structure];
    K --> L[Append Enhanced Re-prompt to Messages];
    L --> A;
    G -- Fail (JSONDecodeError) --> M[Log Format Error];
    M --> L;

    subgraph Enhancements
        P1[Strengthen Initial System Prompt: No Markdown!]
    end

    style F fill:#f9f,stroke:#333,stroke-width:2px
    style L fill:#f9f,stroke:#333,stroke-width:2px
    style P1 fill:#ccf,stroke:#333,stroke-width:2px
```

## 4. Next Steps

Proceed with implementing Phase 1 and Phase 2 as agreed.