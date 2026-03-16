# vLLM `tool_choice=auto` Does Not Produce Structured `tool_calls` for Certain Models

**Date**: 2026-03-13
**Authors**: Kagenti Team
**Audience**: vLLM maintainers / Red Hat AI Inference Server team
**Severity**: High — blocks agentic tool-calling workflows for affected models

---

## Executive Summary

When serving models through vLLM with `tool_choice=auto`, certain models
(notably **Mistral Small 3.1 24B** via Red Hat AI / MAAS endpoints) generate
correct tool call JSON but place it in the response `content` field instead of
the `tool_calls` array. The `finish_reason` is `stop` instead of `tool_calls`.
This makes the response incompatible with the OpenAI Chat Completions API
contract and breaks all downstream agent frameworks (LangGraph, CrewAI, etc.)
that rely on structured `tool_calls` to route execution.

Switching to `tool_choice=required` fixes the issue for the same model on the
same endpoint, confirming the model *can* produce structured tool calls — the
problem is in vLLM's `auto` mode parsing pipeline.

We ran **300 API calls** (3 models × 5 queries × 2 modes × 10 iterations) at
`temperature=0` with 5 tools provided. The results expose three distinct bugs:

1. **Non-deterministic parsing at temperature=0** (Mistral) — same request
   produces structured `tool_calls` on some runs and JSON-in-content on others
2. **Explicit vs implicit `tool_choice` produce different behavior** (Mistral)
   — omitting `tool_choice` and setting `"tool_choice": "auto"` trigger
   different code paths with opposite results
3. **No content-based fallback** (all models) — when the parser's token
   detection fails, valid tool call JSON in `content` is silently ignored

---

## Problem Description

### Observed Behavior

When sending a request with `tool_choice=auto` and valid `tools`:

```json
{
  "model": "mistral-small-3.1-24b-instruct",
  "messages": [{"role": "user", "content": "What's the weather in NYC?"}],
  "tools": [{"type": "function", "function": {"name": "get_weather", ...}}],
  "tool_choice": "auto"
}
```

**Expected response** (OpenAI-compatible):
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [{"id": "call_123", "type": "function", "function": {"name": "get_weather", "arguments": "{\"city\": \"NYC\"}"}}]
    },
    "finish_reason": "tool_calls"
  }]
}
```

**Actual response from vLLM**:
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "[{\"name\": \"get_weather\", \"arguments\": {\"city\": \"NYC\"}}]",
      "tool_calls": []
    },
    "finish_reason": "stop"
  }]
}
```

The model correctly generates the tool call JSON, but it ends up in `content`
as plain text. The `tool_calls` array is empty. `finish_reason` is `stop`.

### Comprehensive Test Results (2026-03-13, MAAS vLLM endpoints, 300 API calls)

**Setup**: 5 tools provided (`get_weather`, `search_web`, `run_code`,
`read_file`, `write_file`), `temperature=0`, 10 iterations per combination,
tested both explicit `"tool_choice": "auto"` and implicit (field omitted).

#### Mistral Small 24B — Non-deterministic, explicit ≠ implicit

| Query | Explicit `auto` | Implicit (omitted) |
|-------|:-:|:-:|
| weather: "weather in Tokyo?" | **5/10** structured, 5/10 in content | **0/10** structured, 10/10 in content |
| search: "kubernetes news" | **3/10** structured, 7/10 in content | **10/10** structured |
| code: "fibonacci of 10" | **7/10** structured, 3/10 in content | **8/10** structured, 2/10 in content |
| file: "read /etc/hosts" | **0/10** structured, 10/10 in content | **0/10** structured, 10/10 in content |
| notool: "capital of France?" | 10/10 text-only (correct) | 10/10 text-only (correct) |

**Critical findings**:
- **Non-deterministic at temperature=0**: weather-explicit is a 50/50 coin flip
  between structured tool_calls and JSON-in-content across 10 identical runs
- **Explicit ≠ implicit**: search-explicit gives 3/10 structured while
  search-implicit gives 10/10 — behavior inverts depending on whether the
  `tool_choice` field is present
- **`read_file` never works**: 0/20 across all modes
- The model always generates **correct tool call JSON** — the data is right,
  the parser just fails to extract it

#### Llama 4 Scout 17B-16E — 100% structured, but cannot decline tools

| Query | Explicit `auto` | Implicit (omitted) |
|-------|:-:|:-:|
| weather | **10/10** structured ✅ | **10/10** structured ✅ |
| search | **10/10** structured ✅ | **10/10** structured ✅ |
| code | **10/10** structured ✅ | **10/10** structured ✅ |
| file | **10/10** structured ✅ | **10/10** structured ✅ |
| notool: "capital of France?" | 10/10 calls `search_web` ⚠️ | 10/10 calls `search_web` ⚠️ |

100/100 structured. But the model calls `search_web("capital of France")` for
a question it should answer from training data. `auto` behaves like `required`.

#### Llama 3.2 3B — 100% structured, but hallucinates wrong tools

| Query | Explicit `auto` | Implicit (omitted) |
|-------|:-:|:-:|
| weather | **10/10** structured ✅ | **10/10** structured ✅ |
| search | **10/10** structured ✅ | **10/10** structured ✅ |
| code | **10/10** structured ✅ | **10/10** structured ✅ |
| file | **10/10** structured ✅ | **10/10** structured ✅ |
| notool: "capital of France?" | 10/10 calls `get_weather(city="Paris")` ❌ | 10/10 calls `get_weather(city="Paris")` ❌ |

100/100 structured. But the model hallucinates `get_weather(city="Paris")` for
"capital of France?" — picking the wrong tool with wrong intent. Also sends
`num_results: "10"` (string) instead of integer, violating the schema.

### Impact on Agent Frameworks

All major agent frameworks check `response.tool_calls` (not `content`) to
decide whether to execute tools:

- **LangGraph**: `tools_condition` checks `AIMessage.tool_calls` — empty means
  the agent loop terminates without tool execution
- **LangChain**: `ChatOpenAI` parses `tool_calls` from the API response
- **CrewAI / AG2**: Same pattern via OpenAI SDK

When `tool_calls` is empty, the agent treats the response as a final text
answer and stops reasoning — even though the model clearly intended to call a
tool.

---

## Root Cause Analysis (from vLLM source)

We cloned vLLM and traced the tool call parsing pipeline. The issue stems from
how vLLM's parser architecture works with `tool_choice=auto`.

### Architecture

vLLM uses **model-specific tool call parsers** that look for known
tokens/prefixes in model output:

| Parser | Trigger Token/Prefix | Models |
|--------|---------------------|--------|
| `mistral` | `[TOOL_CALLS]` token ID | Mistral family |
| `hermes` | `<tool_call>...</tool_call>` XML tags | Hermes, many fine-tuned models |
| `llama3_json` | JSON after specific template | Llama 3.x |
| Others | Various model-specific markers | 30+ parsers total |

### The Failure Path

**File**: `vllm/tool_parsers/mistral_tool_parser.py`

```python
def extract_tool_calls(self, model_output: str, request):
    # If the tool call token is not present, return a text response
    if self.bot_token not in model_output:  # bot_token = "[TOOL_CALLS]"
        return ExtractedToolCallInformation(
            tools_called=False,    # ← No tools detected
            tool_calls=[],         # ← Empty array
            content=model_output   # ← Everything stays as content
        )
```

**File**: `vllm/entrypoints/openai/engine/serving.py`

```python
# When tools_called=False, the content is returned as-is
if tool_call_info is not None and tool_call_info.tools_called:
    function_calls.extend(...)
    content = tool_call_info.content
else:
    return None, content  # ← Tool JSON returned as plain text
```

### Why `required` Works But `auto` Doesn't

When `tool_choice=required`:
- vLLM's `adjust_request()` converts the tool definitions into a **JSON schema
  constraint** via structured outputs
- The model is forced to produce JSON matching the tool call schema
- The output is deterministically parseable because the schema is enforced at
  the sampling/decoding level
- No parser token detection needed

When `tool_choice=auto`:
- The model freely generates tokens
- vLLM relies entirely on the parser detecting a **model-specific marker token**
  (e.g., `[TOOL_CALLS]` for Mistral)
- If the model generates valid tool call JSON **without** the marker token, the
  parser ignores it
- The JSON ends up in `content` as plain text

### The Missing Piece

**There is no fallback content-to-tool-call extraction.** When the parser's
marker detection fails, vLLM does not attempt to:

1. Detect JSON arrays/objects in content that match tool schemas
2. Check if content looks like a tool call based on function names from the
   `tools` parameter
3. Apply structured output validation retroactively

This is a design gap — the parser is purely token/prefix-based with no
semantic fallback.

---

## Server Configuration Issues

### MAAS / Red Hat AI Endpoints

The Red Hat AI / MAAS vLLM endpoints may not be configured with optimal flags.
The issue may be exacerbated by:

1. **Missing or wrong `--chat-template`**: vLLM provides
   `tool_chat_template_mistral_parallel.jinja` which adds a tool-use system
   prompt for much better reliability. If the default template is used instead,
   the model may not produce the `[TOOL_CALLS]` prefix consistently.

2. **Tokenizer mode**: Mistral's official recommendation is
   `--tokenizer_mode mistral --config_format mistral --load_format mistral`.
   If the Transformers tokenizer is used instead, the `[TOOL_CALLS]` token may
   not be in the vocabulary, causing `MistralToolParser.__init__` to fail.

3. **AWQ/quantized models**: Quantized variants may not include the full
   tokenizer, requiring explicit `--tokenizer` pointing to the original model.

### Required Server Flags

For Mistral models to work with `tool_choice=auto`:

```bash
vllm serve mistralai/Mistral-Small-3.1-24B-Instruct-2503 \
  --enable-auto-tool-choice \
  --tool-call-parser mistral \
  --tokenizer_mode mistral \
  --config_format mistral \
  --load_format mistral \
  --chat-template examples/tool_chat_template_mistral_parallel.jinja
```

**We cannot verify** whether the MAAS endpoints use these exact flags.

---

## Specific Bugs Found

### Bug 1: Non-deterministic parsing at temperature=0

**Severity**: Critical
**Affects**: Mistral Small 24B

Identical requests produce different output formats across runs. At
`temperature=0` (which should be fully deterministic), the Mistral parser
returns structured `tool_calls` on some runs and JSON-in-content on others:

```
# 10 identical requests, temperature=0, tool_choice=auto
# Query: "What is the weather like in Tokyo right now?"

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

The model output is correct in every case — it always wants to call
`get_weather`. The parser detects the `[TOOL_CALLS]` token only 50% of the
time. This suggests a race condition in the parser, possibly related to
request batching or KV-cache state.

### Bug 2: Explicit `tool_choice=auto` ≠ omitting `tool_choice`

**Severity**: High
**Affects**: Mistral Small 24B

Per the OpenAI spec, omitting `tool_choice` when tools are present should
default to `"auto"`. But on the MAAS Mistral endpoint, they produce
**opposite results** for the same query:

```
# search query: "Search the web for the latest news about kubernetes"

Explicit "tool_choice": "auto":   3/10 structured (30%)
Implicit (field omitted):        10/10 structured (100%)

# weather query: "What is the weather like in Tokyo?"

Explicit "tool_choice": "auto":   5/10 structured (50%)
Implicit (field omitted):         0/10 structured (0%)
```

The search query works **better** without the field. The weather query works
**better** with it. This means the two modes trigger different code paths in
vLLM's request handling, violating the OpenAI API contract.

### Bug 3: No content-based fallback when parser misses tool calls

**Severity**: High
**Affects**: All models (architectural gap)

When the Mistral parser returns `tools_called=False`, valid JSON like
`[{"name": "read_file", "arguments": {"path": "/etc/hosts"}}]` sits in the
`content` field and is never extracted. `read_file` is 0/20 across all modes —
the parser never catches it, despite the JSON being perfectly valid.

The parser has no fallback to check whether `content` contains JSON matching
the provided tool schemas.

## Proposed Solutions

### For vLLM (upstream)

1. **Add content-based tool call fallback**: When `tool_choice=auto` and the
   parser returns `tools_called=False`, scan the content for JSON matching the
   provided tool schemas. If found, extract as structured `tool_calls`. This
   would be a low-risk, high-value improvement. It would fix Bug 3 entirely
   and mitigate Bug 1 (since the JSON is always correct, just not extracted).

2. **Fix non-deterministic parsing (Bug 1)**: Investigate why the Mistral
   parser produces different results for identical requests at temperature=0.
   Likely causes: KV-cache state leak between batched requests, timing-
   dependent token detection, or parser state not being reset between requests.

3. **Unify explicit/implicit tool_choice handling (Bug 2)**: Ensure that
   omitting `tool_choice` and setting `"tool_choice": "auto"` go through
   the exact same code path. The current divergence breaks the OpenAI API
   contract.

4. **Validate parser compatibility at startup**: When
   `--enable-auto-tool-choice` is set, verify the parser's trigger token exists
   in the tokenizer vocabulary. Currently `MistralToolParser` raises a
   `RuntimeError` if `[TOOL_CALLS]` is missing, but this could be a clearer
   warning with suggested fixes.

5. **Expose parser diagnostics**: Add a `/v1/tool_call_parser/status` endpoint
   (or similar) that reports the active parser, trigger tokens, and whether
   they're present in the tokenizer. This helps operators debug configuration
   issues.

### For MAAS / Red Hat AI Inference Server

1. **Document required server flags per model**: Each model card should specify
   the exact `--tool-call-parser`, `--chat-template`, and `--tokenizer_mode`
   needed for tool calling.

2. **Pre-validate tool calling support**: Before advertising a model as
   tool-call-capable, run automated tests with `tool_choice=auto` and verify
   structured `tool_calls` are returned.

3. **Consider a proxy-level fallback**: A thin layer between the MAAS endpoint
   and clients that detects tool call JSON in `content` and promotes it to
   `tool_calls` when the parser misses it.

---

## Our Workarounds

We implemented two workarounds in our agent framework:

### 1. Text-Based Tool Call Parser (client-side)

```python
# If the model returned text-based tool calls instead of structured
# tool_calls (common with vLLM without --enable-auto-tool-choice),
# parse them so LangGraph's tools_condition routes to the ToolNode.
response = maybe_patch_tool_calls(response)
```

Our `parse_text_tool_calls()` function uses regex to detect tool call patterns
in `content` like `shell(command="ls")` or `[label, tool_name]{"key": "val"}`
and converts them into proper `AIMessage.tool_calls`. This handles:
- Legacy format: `tool_name(key="value")`
- Llama 4 format: `[label, tool_name]{"key": "value"}`

### 2. Force `tool_choice=any`

```python
# tool_choice="any" forces structured tool calls. Required for models
# that fabricate output without it.
llm_with_tools = llm.bind_tools(tools, tool_choice="any")
```

This uses `required`/`any` mode to force structured output, bypassing the
parser entirely. The downside is the model cannot choose to *not* call a tool,
which requires additional application-level logic (e.g., a "done" tool).

---

## Reproduction Steps

### Direct API Call (curl)

```bash
# Against a vLLM endpoint serving Mistral Small 24B
curl -X POST $VLLM_URL/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "model": "mistral-small-3.1-24b-instruct",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant with access to tools."},
      {"role": "user", "content": "What is the weather in San Francisco?"}
    ],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {"type": "string", "description": "City name"}
          },
          "required": ["city"]
        }
      }
    }],
    "tool_choice": "auto"
  }'

# Expected: tool_calls array populated, finish_reason="tool_calls"
# Actual:   tool_calls=[], content contains JSON, finish_reason="stop"
```

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(base_url=VLLM_URL, api_key=API_KEY)

response = client.chat.completions.create(
    model="mistral-small-3.1-24b-instruct",
    messages=[{"role": "user", "content": "What is the weather in NYC?"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }],
    tool_choice="auto",
)

msg = response.choices[0].message
print(f"tool_calls: {msg.tool_calls}")    # Expected: [...], Actual: None/[]
print(f"content: {msg.content}")           # Contains the tool call JSON
print(f"finish_reason: {response.choices[0].finish_reason}")  # "stop" not "tool_calls"
```

---

## Related vLLM Issues

- [#17161](https://github.com/vllm-project/vllm/issues/17161) — `tool_calls` list empty, value in `content`
- [#17821](https://github.com/vllm-project/vllm/issues/17821) — Tool calls not triggered with `tool_choice=auto`
- [#21840](https://github.com/vllm-project/vllm/issues/21840) — Tools not invoked with `tool_choice=auto` (v0.10.0)
- [#31871](https://github.com/vllm-project/vllm/issues/31871) — Streaming returns raw text instead of parsed tool_calls
- [#29192](https://github.com/vllm-project/vllm/issues/29192) — Parsers fail to populate tool_calls array
- [#16887](https://github.com/vllm-project/vllm/issues/16887) — `tool_choice=required` doesn't work for Mistral
- [#12749](https://github.com/vllm-project/vllm/discussions/12749) — Tool call not working with Mistral Small 24B

---

## Experimental Results (2026-03-13)

Direct API calls to Red Hat AI / MAAS vLLM endpoints using curl. Each model
was tested with 5 scenarios: plain chat, `tool_choice=auto` with tool-relevant
query, `tool_choice=required`, `tool_choice=none`, and `tool_choice=auto` with
a non-tool query ("What is 2+2?").

### Llama 4 Scout 17B-16E (109B MoE)

| Test | `finish_reason` | `tool_calls` | `content` |
|------|----------------|-------------|-----------|
| **chat** (no tools) | `stop` | — | "2 + 2 = 4." |
| **auto** + weather query | `tool_calls` | ✅ `get_weather(city="San Francisco")` | `null` |
| **required** | `stop` | ✅ `get_weather(city="San Francisco")` | `""` |
| **none** | `stop` | — | "San Francisco! Known for its foggy and cool climate..." |
| **auto** + "2+2" | `stop` | — | "I am not able to complete this task as it falls outside the scope..." |

**Verdict**: Best model for tool calling. `auto` works correctly — structured
`tool_calls` with proper `finish_reason=tool_calls`. Non-tool queries correctly
return text without tool calls. Minor issue: `required` returns
`finish_reason=stop` instead of `tool_calls`.

### Mistral Small 3.1 24B

| Test | `finish_reason` | `tool_calls` | `content` |
|------|----------------|-------------|-----------|
| **chat** (no tools) | `stop` | — | "The sum of 2 + 2 is 4." |
| **auto** + weather query | `stop` | ❌ **empty** | `[{"name": "get_weather", "arguments": {"city": "San Francisco"}}]` |
| **required** | `stop` | ✅ `get_weather(city="San Francisco")` | `""` |
| **none** | `stop` | — | "I don't have real-time access to the internet to check..." |
| **auto** + "2+2" | `stop` | — | "The answer to 2+2 is 4." |

**Verdict**: **Confirms the bug.** With `tool_choice=auto`, the model generates
correct tool call JSON but puts it in the `content` field as plain text.
`tool_calls` array is empty. `finish_reason` is `stop` instead of `tool_calls`.
Switching to `tool_choice=required` fixes the issue — structured `tool_calls`
are returned correctly. This is a vLLM parser issue, not a model limitation.

### Llama 3.2 3B Instruct

| Test | `finish_reason` | `tool_calls` | `content` |
|------|----------------|-------------|-----------|
| **chat** (no tools) | `stop` | — | "2 + 2 = 4" |
| **auto** + weather query | `tool_calls` | ✅ `get_weather(city="San Francisco")` | `null` |
| **required** | `stop` | ✅ `get_weather(city="San Francisco")` | `""` |
| **none** | `stop` | — | "I don't have real-time access to current weather..." |
| **auto** + "2+2" | `tool_calls` | ⚠️ `add(x="2", y="2")` | `null` |

**Verdict**: Surprisingly good for a 3B model. `auto` and `required` both
produce structured `tool_calls`. However, the model **hallucinates tool calls**
for non-tool queries — it called a fictional `add(x, y)` tool that doesn't
exist in the provided tools. Same `finish_reason=stop` issue with `required`.

### DeepSeek R1 Qwen 14B

| Test | `finish_reason` | `tool_calls` | `content` |
|------|----------------|-------------|-----------|
| All tests | — | — | **Connection timeout (HTTP 000)** |

**Verdict**: Endpoint unreachable during testing. This model is a reasoning-only
model and is not expected to support tool calling.

### Summary Matrix

| Model | `auto` | `required` | `none` | Hallucinated tools | Recommended |
|-------|--------|-----------|--------|-------------------|-------------|
| **Llama 4 Scout** | ✅ Structured | ✅ Structured | ✅ Text only | No | ✅ Agents |
| **Mistral Small 24B** | ❌ JSON in content | ✅ Structured | ✅ Text only | No | Chat only |
| **Llama 3.2 3B** | ✅ Structured | ✅ Structured | ✅ Text only | **Yes** (add) | ⚠️ Simple tasks |
| **DeepSeek R1 14B** | N/A (timeout) | N/A | N/A | N/A | Reasoning only |

### Key Findings

1. **Mistral `auto` is broken**: The model generates correct tool call JSON but
   vLLM's Mistral parser fails to extract it. The `[TOOL_CALLS]` marker token
   is likely not produced by the model, causing the parser to skip extraction.

2. **`required` works universally**: All reachable models correctly produce
   structured `tool_calls` with `required` mode (via structured outputs).

3. **`finish_reason` inconsistency**: With `tool_choice=required`, all models
   return `finish_reason=stop` even though they produce tool calls. Only
   `tool_choice=auto` correctly sets `finish_reason=tool_calls` (when it works).

4. **Llama 3.2 3B hallucinates tools**: The small model invents tool calls for
   queries that don't need tools, calling functions not in the provided schema.

---

## Appendix: vLLM Tool Call Architecture

```
Request arrives with tool_choice="auto" + tools
    │
    ▼
[protocol.py] Validate request, default to "auto" if tools present
    │
    ▼
[cli_args.py] Check --enable-auto-tool-choice flag
    │ Missing? → 400 error
    ▼
[serving.py] render_chat_request()
    │
    ▼
[serving.py] tool_parser.adjust_request()
    │ For "required": adds JSON schema constraint (structured output)
    │ For "auto": NO structured output constraint
    ▼
Model generates tokens freely
    │
    ▼
[tool_parser] extract_tool_calls(model_output)
    │
    ├── Parser checks for model-specific marker:
    │   Mistral: [TOOL_CALLS] token
    │   Hermes:  <tool_call>...</tool_call> tags
    │   Llama:   model-specific JSON format
    │
    ├── Marker FOUND → parse JSON → return tool_calls ✅
    │
    └── Marker NOT FOUND → return tools_called=False ❌
        │
        ▼
    Content stays as plain text, tool_calls=[], finish_reason="stop"
    ┌──────────────────────────────────────────────────┐
    │  NO FALLBACK — tool JSON in content is ignored   │
    └──────────────────────────────────────────────────┘
```

**Key file paths in vLLM source**:
- `vllm/tool_parsers/abstract_tool_parser.py` — Base class and registry
- `vllm/tool_parsers/mistral_tool_parser.py` — Mistral parser (checks `[TOOL_CALLS]`)
- `vllm/tool_parsers/hermes_tool_parser.py` — Hermes parser (checks `<tool_call>`)
- `vllm/entrypoints/openai/chat_completion/serving.py` — Request handling and tool routing
- `vllm/entrypoints/openai/engine/serving.py` — Tool call extraction from content
- `vllm/entrypoints/openai/cli_args.py` — CLI flags for tool choice
