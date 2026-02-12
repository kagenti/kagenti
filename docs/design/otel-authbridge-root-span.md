# Approach A: AuthBridge ext_proc Root Span (Zero Agent Changes)

**Issue:** #667
**Goal:** Infrastructure-created root spans for OTEL GenAI observability with zero agent code changes.

## Overview

Extend the existing AuthBridge ext_proc gRPC server (Go) to create OTEL root spans for agent requests. The AuthBridge already intercepts all agent traffic via Envoy sidecar with iptables redirection. By adding OTEL span creation to the ext_proc processing pipeline, we can create properly attributed root spans without any agent code changes.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│ Agent Pod                                                │
│                                                          │
│  ┌─────────┐    ┌──────────────┐    ┌─────────────────┐ │
│  │ Envoy   │───▶│ ext_proc     │───▶│ Agent Code      │ │
│  │ Sidecar │    │ (Go gRPC)    │    │ (no changes)    │ │
│  │         │◀───│              │◀───│                 │ │
│  │ port    │    │ + OTEL SDK   │    │ + auto-instr    │ │
│  │ 15123/  │    │ + A2A parser │    │   (LangChain,   │ │
│  │ 15124   │    │ + root span  │    │    OpenAI)      │ │
│  └─────────┘    └──────┬───────┘    └────────┬────────┘ │
│                        │                      │          │
└────────────────────────┼──────────────────────┼──────────┘
                         │                      │
                         ▼                      ▼
              ┌──────────────────────────────────────┐
              │ OTEL Collector                       │
              │ (kagenti-system)                     │
              │                                      │
              │ Root span (from ext_proc)             │
              │   └── LangChain spans (from agent)   │
              │       └── LLM spans (auto-instr)     │
              │       └── Tool spans (auto-instr)    │
              │                                      │
              │ Pipeline: traces/phoenix             │
              │ Pipeline: traces/mlflow              │
              └──────────────────────────────────────┘
```

## What Changes

### 1. ext_proc Go code (`AuthProxy/go-processor/main.go`)

**Current state:** Handles only request/response headers for JWT validation and token exchange. No OTEL.

**Changes needed:**
- Add OpenTelemetry Go SDK dependency
- Change Envoy processing_mode to include body buffering:
  - `request_body_mode: BUFFERED` (for A2A JSON-RPC input parsing)
  - `response_body_mode: BUFFERED` (for response output capture)
- On inbound A2A requests:
  1. Parse JSON-RPC body to extract `params.message.parts[0].text` (user input)
  2. Extract `params.contextId` (conversation ID)
  3. Create root span: `invoke_agent {agent_name}`
  4. Set all required attributes (MLflow, OpenInference, GenAI)
  5. Inject `traceparent` header into request forwarded to agent
- On response:
  1. Parse response body for `result.artifacts[0].parts[0].text` (output)
  2. Set `mlflow.spanOutputs`, `output.value`, `gen_ai.completion` on root span
  3. End the root span

### 2. Envoy config (`envoy-config` ConfigMap)

**Current state:** `request_body_mode: NONE`, `response_body_mode: NONE`

**Changes needed:**
```yaml
processing_mode:
  request_header_mode: SEND
  response_header_mode: SEND
  request_body_mode: BUFFERED    # NEW: buffer full request body
  response_body_mode: BUFFERED   # NEW: buffer full response body
```

### 3. Agent deployment

**No changes to agent code.** Agent needs only:
- Standard OTEL SDK setup (TracerProvider + OTLP exporter) - this is typically set via environment variables
- Auto-instrumentation libraries already in use (LangChain, OpenAI)
- `OTEL_EXPORTER_OTLP_ENDPOINT` env var (already set in deployment)

The agent's auto-instrumented spans will automatically become children of the root span because:
1. ext_proc injects `traceparent` header with the root span's trace context
2. Agent's OTEL SDK extracts trace context from incoming headers (W3C propagation)
3. All spans created by auto-instrumentation inherit this context

## Root Span Attributes

The ext_proc sets these attributes on the root span:

### GenAI Semantic Conventions (Required)
| Attribute | Value | Source |
|-----------|-------|--------|
| `gen_ai.operation.name` | `invoke_agent` | Static |
| `gen_ai.provider.name` | From deployment config | ConfigMap |
| `gen_ai.agent.name` | From deployment config | ConfigMap |
| `gen_ai.agent.version` | From deployment config | ConfigMap |
| `gen_ai.conversation.id` | `params.contextId` | A2A JSON-RPC body |
| `gen_ai.prompt` | `params.message.parts[0].text` | A2A JSON-RPC body |
| `gen_ai.completion` | `result.artifacts[0].parts[0].text` | A2A response body |

### MLflow Attributes
| Attribute | Value | Source |
|-----------|-------|--------|
| `mlflow.spanInputs` | User input text | A2A JSON-RPC body |
| `mlflow.spanOutputs` | Agent response text | A2A response body |
| `mlflow.spanType` | `AGENT` | Static |
| `mlflow.traceName` | Agent name | ConfigMap |
| `mlflow.version` | Agent version | ConfigMap |
| `mlflow.runName` | `{agent_name}-invoke` | Derived |
| `mlflow.source` | Service name | ConfigMap |
| `mlflow.user` | From JWT claims | Auth header |
| `mlflow.trace.session` | Context ID | A2A JSON-RPC body |

### OpenInference Attributes
| Attribute | Value | Source |
|-----------|-------|--------|
| `openinference.span.kind` | `AGENT` | Static |
| `input.value` | User input text | A2A JSON-RPC body |
| `output.value` | Agent response text | A2A response body |

## Agent Configuration

Agent metadata (name, version, provider) is provided via a new ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agent-otel-config
  namespace: team1
data:
  AGENT_NAME: "weather-assistant"
  AGENT_VERSION: "1.0.0"
  AGENT_PROVIDER: "langchain"
  OTEL_SERVICE_NAME: "weather-service"
```

This ConfigMap is mounted into the ext_proc container, keeping agent metadata out of agent code.

## Streaming Response Handling

A2A supports streaming via SSE. For streaming responses:
- ext_proc uses `response_body_mode: BUFFERED` which may not work well with SSE
- Alternative: Use `STREAMED` mode and accumulate the final response
- Or: Set `mlflow.spanOutputs` from the last SSE event containing the final answer
- This is the same challenge PR 114 faces with `StreamingResponse`

## Trade-offs

**Pros:**
- Zero agent code changes - agents only need standard OTEL SDK + auto-instrumentation
- Centralized observability logic - update once, all agents benefit
- AuthBridge already deployed via webhook injection
- Can extract user identity from JWT (already validated by ext_proc)
- Consistent attribute naming across all agents

**Cons:**
- Body buffering adds latency (full request/response must be received before processing)
- Streaming response capture is complex
- ext_proc becomes a critical path for observability
- Agent metadata must be provided via ConfigMap (not self-described)
- Local tool calls within the agent (not via MCP) won't have tool spans from infrastructure

## E2E Test Impact

Expected test results with this approach:

| Test | Expected Result |
|------|----------------|
| TestWeatherAgentTracesInMLflow | PASS - root span has service.name |
| TestGenAITracesInMLflow | PASS - LangChain auto-instrumentation creates nested spans |
| TestMLflowTraceMetadata | PASS - root span has all metadata |
| TestSessionTracking | PASS - conversation.id from A2A body |
| TestRootSpanAttributes (MLflow) | PASS - all attributes set by ext_proc |
| TestRootSpanAttributes (OpenInference) | PASS - input/output.value set |
| TestRootSpanAttributes (GenAI) | PASS - conversation.id, agent.name set |
| TestTokenUsageVerification | PASS - LLM auto-instrumentation handles this |
| TestToolCallSpanAttributes | DEPENDS - MCP tool calls auto-instrumented, local tools not captured |
| TestErrorSpanValidation | PASS - ext_proc sets error status on failures |

## Implementation Steps

1. Add OTEL Go SDK to ext_proc `go.mod`
2. Create A2A JSON-RPC body parser
3. Implement root span creation in `handleInbound()`
4. Implement response capture in response body handler
5. Update Envoy config for body buffering
6. Add `agent-otel-config` ConfigMap to agent-namespaces template
7. Test with existing weather agent (remove observability.py)
8. Run MLflow E2E tests
