# Sandbox Agent Tool Calling — What Works and What Doesn't

**Date**: 2026-03-13
**For**: Sandbox agent development sessions
**Based on**: 300 API calls across 3 MAAS models, 10 iterations each, temperature=0

---

## TL;DR

1. **Use `tool_choice="any"` (or `"required"`)** — this is the only mode that
   works 100% reliably across all models. We already do this.
2. **Keep the text-based tool call parser** (`maybe_patch_tool_calls`) — Mistral
   puts tool calls in `content` 59% of the time with `auto`.
3. **Add a `respond_to_user` escape tool** — Llama 4 and Llama 3.2 cannot
   produce text-only responses when tools are present. They need a tool-shaped
   way to return final answers.
4. **Do NOT rely on `tool_choice="auto"`** — it's broken on Mistral (non-deterministic)
   and semantically wrong on Llama models (always calls a tool).

---

## The Problem By Model

### Mistral Small 24B — Parsing is broken

The model has the **best judgment** about when to use tools. It correctly
declines to call tools for non-tool queries ("What is the capital of France?"
→ text response 20/20 times). But vLLM's Mistral parser fails to extract
structured `tool_calls` consistently:

```
tool_choice=auto, "What is the weather in Tokyo?", temperature=0, 10 runs:

Run 1:  finish_reason=tool_calls  tool_calls=[get_weather(city="Tokyo")]  ✅
Run 2:  finish_reason=stop        tool_calls=[]  content='[{"name":"get_weather"...}]'  ❌
Run 3:  finish_reason=stop        tool_calls=[]  content='[{"name":"get_weather"...}]'  ❌
Run 4:  finish_reason=stop        tool_calls=[]  content='[{"name":"get_weather"...}]'  ❌
Run 5:  finish_reason=stop        tool_calls=[]  content='[{"name":"get_weather"...}]'  ❌
Run 6:  finish_reason=stop        tool_calls=[]  content='[{"name":"get_weather"...}]'  ❌
Run 7:  finish_reason=tool_calls  tool_calls=[get_weather(city="Tokyo")]  ✅
Run 8:  finish_reason=tool_calls  tool_calls=[get_weather(city="Tokyo")]  ✅
Run 9:  finish_reason=tool_calls  tool_calls=[get_weather(city="Tokyo")]  ✅
Run 10: finish_reason=tool_calls  tool_calls=[get_weather(city="Tokyo")]  ✅
```

**50/50 coin flip at temperature=0.** The JSON is correct in both cases — the
model always wants to call the tool. But vLLM's `[TOOL_CALLS]` token parser
only catches it half the time.

Worse: `read_file` was **0/20** structured across all modes. The parser never
catches it.

### Llama 4 Scout — Can't say "no" to tools

100% reliable structured `tool_calls` — never a parsing failure. But:

```
tool_choice=auto, "What is the capital of France?", 5 tools provided:

Run 1-10:  tool_calls=[search_web(query="capital of France")]  ← WRONG
```

The model should answer "Paris" from training data. Instead it calls
`search_web` every time. It **never produces text-only responses** when tools
are present. `auto` mode acts like `required` mode.

### Llama 3.2 3B — Hallucinates wrong tools

100% reliable parsing, but:

```
tool_choice=auto, "What is the capital of France?", 5 tools provided:

Run 1-10:  tool_calls=[get_weather(city="Paris", units="celsius")]  ← WRONG TOOL
```

It free-associates France → Paris → weather. Also sends `num_results: "10"`
(string) instead of `10` (integer), violating the schema.

---

## How to Handle This in the Sandbox Agent

### Strategy 1: Force tool calls + escape tool (RECOMMENDED)

This is what we currently do and it's correct:

```python
# graph.py — force structured tool calls
llm_with_tools = llm.bind_tools(tools, tool_choice="any")
```

Add a `respond_to_user` tool that the model can call when it wants to return
a final answer:

```python
# Already exists as the "done" detection in the reflector node
# The model calls a tool, the reflector checks if the task is complete
```

**Why this works**: `tool_choice="any"` (maps to `"required"` in OpenAI API)
uses structured outputs/JSON schema at the decoding level. The parser is
bypassed entirely — the model is constrained to produce valid tool call JSON.
This works 100% on all models.

**Trade-off**: The model cannot freely choose to return text. It must always
call a tool. This is fine for agentic loops where you want tool execution at
every step and use a reflector node to decide when to stop.

### Strategy 2: Keep text-based parser as fallback (KEEP)

```python
# reasoning.py line 904-910
# If the model returned text-based tool calls instead of structured
# tool_calls (common with vLLM without --enable-auto-tool-choice),
# parse them so tools_condition routes to the ToolNode.
pre_patch_content = response.content
had_structured_tools = bool(response.tool_calls)
response = maybe_patch_tool_calls(response)
```

**Keep this code.** Even with `tool_choice="any"`, there are edge cases where
the model might switch to text-based tool calls (e.g., if LiteLLM strips the
tool_choice parameter, if the model falls back to chat mode during long
conversations, etc.). The text parser is a safety net.

### Strategy 3: Model-specific configuration

If we ever switch to `tool_choice="auto"` (e.g., to let the model decide when
to stop), use model-specific settings:

```python
MODEL_TOOL_CONFIG = {
    "llama-4-scout": {
        "tool_choice": "auto",      # Works 100%
        "needs_done_tool": True,     # Can't produce text-only responses
        "text_parser": False,        # Not needed
    },
    "mistral-small": {
        "tool_choice": "required",   # auto is broken (50/50)
        "needs_done_tool": True,     # Required since using "required"
        "text_parser": True,         # Needed as fallback
    },
    "llama-3.2-3b": {
        "tool_choice": "auto",       # Works but hallucinates
        "needs_done_tool": True,     # Can't produce text-only responses
        "text_parser": False,        # Not needed
        "validate_tool_name": True,  # Check tool exists in schema!
    },
}
```

### Strategy 4: Explicit vs implicit matters for Mistral

**Always pass `tool_choice` explicitly.** Do not omit it. Our tests show
Mistral behaves differently:

- `"tool_choice": "auto"` → weather 5/10 structured
- no tool_choice field → weather 0/10 structured

And confusingly, search was the opposite:
- `"tool_choice": "auto"` → search 3/10 structured
- no tool_choice field → search 10/10 structured

This inconsistency means the code path differs. Always be explicit.

---

## What We Need From vLLM

1. **Content-based tool call fallback** — when the parser returns
   `tools_called=False` but the content contains valid JSON matching the tool
   schema, extract it as `tool_calls`. This would fix Mistral immediately.

2. **Deterministic parsing at temperature=0** — same input should produce same
   output format every time. The 50/50 flip is a bug.

3. **Explicit = implicit behavior** — `"tool_choice": "auto"` and omitting
   `tool_choice` should behave identically per OpenAI spec.

---

## Quick Reference

| Scenario | What to use | Why |
|----------|-------------|-----|
| Agentic loop (sandbox agent) | `tool_choice="any"` + text parser fallback | 100% reliable, works on all models |
| Simple single-tool agent | `tool_choice="required"` | Forces structured output |
| Chat with optional tools | `tool_choice="auto"` on Llama 4 only | Only model where auto works |
| Mistral anything | `tool_choice="required"` | auto is broken |
| Need text-only responses | Strip tools from request OR add "respond" tool | No model handles auto correctly |

---

## Raw Data Location

- CSV results: `/tmp/kagenti/vllm-tests/consistency/{mistral,llama4,llama32}.csv`
- Full vLLM analysis: `docs/plans/2026-03-13-vllm-tool-choice-auto-issue.md`
- Test script: `/tmp/kagenti/vllm-tests/test_auto_consistency.py`
