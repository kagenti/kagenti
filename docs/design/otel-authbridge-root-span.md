# Zero-Agent OTEL: AuthBridge ext_proc Observability

**Issue:** #667
**PR kagenti:** #668
**PR agent-examples:** #122

## Overview

Full GenAI observability with **zero OTEL code in the agent**. The AuthBridge
`otel-ext-proc` sidecar intercepts A2A SSE streams through Envoy, creates root
spans and nested child spans by parsing LangGraph events from the stream. The
OTEL Collector transforms `gen_ai.*` attributes to MLflow and Phoenix formats.

## Architecture

```
Client → Route → Envoy(15124) → ext_proc(9090) → Agent(8000)
                                     |
                                     v
                              OTEL Collector
                              /           \
                        Phoenix          MLflow
                  (OpenInference)    (mlflow.*)
```

### Pod Structure (4 containers)

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `agent` | weather-service:v0.0.1 | 8000 | A2A agent (zero OTEL deps) |
| `envoy-proxy` | envoyproxy/envoy:v1.33 | 15124 | Inbound proxy with ext_proc filter |
| `otel-ext-proc` | authbridge-otel-processor:latest | 9090 | GenAI span creation from SSE |
| `kagenti-client-registration` | client-registration:latest | — | Keycloak client sidecar |

## How It Works

### 1. Request Phase (Headers + Body)

The ext_proc intercepts the inbound request:
- Creates root span `invoke_agent {agent_name}` with `gen_ai.*` attributes
- Injects `traceparent` W3C header into the request
- Parses A2A JSON-RPC body for user input → `gen_ai.prompt`
- Skips non-API paths (agent-card, health)

### 2. Response Phase (SSE Stream)

The agent emits LangGraph events as valid JSON in SSE `status-update` messages.
The ext_proc parses each chunk in real-time:

| SSE Event | Span Created | Key Attributes |
|-----------|-------------|----------------|
| `🚶‍♂️assistant:` with tool_calls | `chat {model}` | `gen_ai.usage.input_tokens`, `gen_ai.response.model`, `gen_ai.tool.calls` |
| `🚶‍♂️tools:` | `execute_tool {name}` | `gen_ai.tool.name`, `gen_ai.tool.call.id` |
| `🚶‍♂️assistant:` with content | `chat {model}` | `gen_ai.usage.input_tokens`, `gen_ai.response.finish_reasons` |
| `artifact-update` | (root span) | `gen_ai.completion` set on root |
| `status-update` final=true | — | Root span ended |

### 3. Client Disconnect Handling

When the SSE client disconnects mid-stream:
1. ext_proc starts a background `tasks/resubscribe` connection immediately on task ID capture
2. If resubscribe returns no events (EventQueue closed), falls back to `tasks/get`
3. The agent saves the completed task to the InMemoryTaskStore (always, not just on failure)
4. `tasks/get` retrieves the artifact and sets `gen_ai.completion` on the root span

### 4. OTEL Collector Transforms

The ext_proc sets **only `gen_ai.*` attributes** (standard OTel GenAI semantic conventions).
The OTEL Collector derives backend-specific attributes:

**Phoenix pipeline** (`transform/genai_to_openinference`):

| GenAI Attribute | OpenInference Attribute |
|-----------------|------------------------|
| `gen_ai.request.model` | `llm.model_name` |
| `gen_ai.usage.input_tokens` | `llm.token_count.prompt` |
| `gen_ai.usage.output_tokens` | `llm.token_count.completion` |
| `gen_ai.system` | `llm.provider` |
| `gen_ai.prompt` | `input.value` |
| `gen_ai.completion` | `output.value` |
| Span name `invoke_agent*` | `openinference.span.kind = AGENT` |
| Span name `chat*` | `openinference.span.kind = LLM` |
| Span name `execute_tool*` | `openinference.span.kind = TOOL` |

**MLflow pipeline** (`transform/genai_to_mlflow`):

| GenAI Attribute | MLflow Attribute |
|-----------------|-----------------|
| `gen_ai.prompt` | `mlflow.spanInputs` |
| `gen_ai.completion` | `mlflow.spanOutputs` |
| `gen_ai.agent.name` | `mlflow.traceName` |
| `gen_ai.conversation.id` | `mlflow.trace.session` |
| `gen_ai.agent.version` | `mlflow.version` |
| `gen_ai.usage.input_tokens` | `mlflow.span.chat_usage.input_tokens` |
| `gen_ai.usage.output_tokens` | `mlflow.span.chat_usage.output_tokens` |
| Span name `invoke_agent*` | `mlflow.spanType = AGENT` |
| Span name `chat*` | `mlflow.spanType = LLM` |
| Span name `execute_tool*` | `mlflow.spanType = TOOL` |

## Trace Tree (MLflow/Phoenix)

```
invoke_agent weather-assistant          ← root span
├── gen_ai.prompt = "What is the weather?"
├── gen_ai.completion = "The weather in..."
├── gen_ai.conversation.id = <context_id>
│
├── chat gpt-4o-mini-2024-07-18        ← LLM decides to call tool
│   ├── gen_ai.usage.input_tokens = 73
│   ├── gen_ai.usage.output_tokens = 14
│   ├── gen_ai.response.model = gpt-4o-mini-2024-07-18
│   └── gen_ai.response.finish_reasons = tool_calls
│
├── execute_tool get_weather            ← tool execution
│   ├── gen_ai.tool.name = get_weather
│   └── gen_ai.tool.call.id = call_xxx
│
└── chat gpt-4o-mini-2024-07-18        ← LLM generates answer
    ├── gen_ai.usage.input_tokens = 154
    ├── gen_ai.usage.output_tokens = 62
    └── gen_ai.response.finish_reasons = stop
```

## Span Naming (per OTel GenAI Spec)

Per https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/:

| Operation | Span Name | `gen_ai.operation.name` |
|-----------|-----------|------------------------|
| Agent invocation | `invoke_agent {gen_ai.agent.name}` | `invoke_agent` |
| LLM chat | `chat {gen_ai.request.model}` | `chat` |
| Tool execution | `execute_tool {gen_ai.tool.name}` | `execute_tool` |

## Agent Requirements

The agent has **zero OTEL dependencies**. It only needs to:

1. Serialize LangGraph events as valid JSON (via `model_dump()` + `json.dumps()`)
2. Save completed tasks to the InMemoryTaskStore for disconnect recovery

The `asyncio.shield()` in `execute()` prevents SSE disconnect from cancelling
the LangGraph execution. The agent completes even if nobody is listening.

## Key Files

| File | Purpose |
|------|---------|
| `kagenti/examples/agents/authbridge-otel/main.go` | ext_proc implementation |
| `kagenti/examples/agents/authbridge-otel/Dockerfile` | Builds ext_proc |
| `kagenti/examples/agents/weather_service_deployment_ocp.yaml` | 4-container pod |
| `charts/kagenti-deps/templates/otel-collector.yaml` | Collector transforms |
| `charts/kagenti/templates/agent-namespaces.yaml` | Envoy config |
