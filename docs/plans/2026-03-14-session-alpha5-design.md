# Session Alpha-5 Design — Reflector + Reporter + Prompt + UI Fixes

## Workstream 1: Agent Reasoning (agent-examples repo)

### 1a. Reflector Full Step History
- `context_builders.py`: Increase `_MAX_REFLECTOR_PAIRS` from 3 → 10
- Add structured step summary to reflector system prompt: total tool calls, tools used, error count (derived from messages since STEP_BOUNDARY)

### 1b. Reporter Thinking+Tool Loop
- `graph.py`: Give reporter read-only tools (file_read, grep, glob) + respond_to_user
- `reasoning.py`: Change reporter_node to use `invoke_with_tool_loop()` with thinking_budget=2
- `prompts.py`: Update REPORTER_SYSTEM to instruct scanning workspace for files, verify existence, produce structured report with file list
- Reporter output includes `files_touched: list[str]`
- Reporter uses step_results + plan status AND tools to verify files

### 1c. Thinking Budget Tuning
- `reasoning.py`: Change default THINKING_ITERATION_BUDGET from 5 → 2
- `sandbox_deploy.py`: Change wizard default from 5 → 2

### 1d. Prompt Visibility Everywhere
- Executor edge cases: create synthetic LLMCallCapture for cycle limit, budget exceeded, done signal paths
- Step selector: emit `_prompt_messages` from the brief prompt

## Workstream 2: UI (sandbox-agent repo)

### 2a. Budget Stats Auto-Reload
- `SessionStatsPanel.tsx`: Add setInterval(3000) polling when streaming + stats tab active

### 2b. File Browser Auto-Refresh
- `FileBrowser.tsx`: Add refetchInterval: 3000 on directory query when session active

### 2c. Reporter Files-Touched Display
- `loopBuilder.ts`: Extract files_touched from reporter events
- `LoopDetail.tsx`: Render first 15 file paths as expandable badges
