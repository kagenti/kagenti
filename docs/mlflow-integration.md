# MLflow Integration for LLM Observability

This document describes deploying MLflow alongside Phoenix for LLM trace
collection in Kagenti E2E tests.

## Overview

MLflow Tracing provides LLM observability similar to Phoenix. This integration
allows comparing both tools and validating that weather agent traces are
captured correctly.

## Architecture

```
Weather Agent (with dual instrumentation)
    │
    ├─ OpenInference spans (openinference-instrumentation-langchain)
    ├─ GenAI spans (opentelemetry-instrumentation-openai)
    │
    │ OTLP (port 8335)
    ▼
OTEL Collector
    │
    ├──► [filter/phoenix] ──► Phoenix (OpenInference spans only)
    │
    └──► [transform/genai_to_openinference] ──► MLflow (transformed spans)
```

## Current State

- Phoenix receives traces via OTEL Collector filter for `openinference.*` scopes
- Weather agent uses dual instrumentation:
  - OpenInference (`openinference-instrumentation-langchain`) for Phoenix
  - GenAI semantic conventions (`opentelemetry-instrumentation-openai`) for MLflow
- OTEL Collector transforms GenAI spans to OpenInference format for MLflow

## MLflow Integration Approach

### Option 1: Dual Export (Recommended)

Add MLflow as a second exporter in OTEL Collector:
- Export the same OpenInference spans to both Phoenix and MLflow
- MLflow can ingest OTLP traces directly (since MLflow 2.14+)

### Option 2: GenAI Auto-Instrumentation + Transform (Implemented)

1. Add OpenTelemetry GenAI auto-instrumentation to weather agent
2. Use OTEL Collector transform processor to convert GenAI spans to OpenInference
3. Export to both Phoenix and MLflow

**Status**: Implemented in PR. Weather agent now has dual instrumentation.

## Components Added

### 1. MLflow Helm Template (`charts/kagenti-deps/templates/mlflow.yaml`)

Deploys MLflow tracking server with:
- PostgreSQL backend (shared with Phoenix)
- OTLP receiver endpoint
- UI access via HTTPRoute/Route
- OAuth2 authentication via mlflow-oidc-auth plugin (when enabled)

### 2. OTEL Collector Pipeline Update

Added MLflow exporter pipeline with GenAI to OpenInference transform:
```yaml
processors:
  transform/genai_to_openinference:
    trace_statements:
      - context: span
        statements:
          # Convert GenAI model name to OpenInference format
          - set(attributes["llm.model_name"], attributes["gen_ai.request.model"])
          # Convert GenAI token counts to OpenInference format
          - set(attributes["llm.token_count.prompt"], attributes["gen_ai.usage.input_tokens"])
          - set(attributes["llm.token_count.completion"], attributes["gen_ai.usage.output_tokens"])

exporters:
  otlphttp/mlflow:
    endpoint: http://mlflow:5000
    tls:
      insecure: true

pipelines:
  traces/mlflow:
    receivers: [otlp]
    processors: [memory_limiter, transform/genai_to_openinference, batch]
    exporters: [otlphttp/mlflow]
```

### 3. MLflow OAuth Secret Generator (`kagenti/auth/mlflow-oauth-secret/`)

- `mlflow_oauth_secret.py` - Keycloak client registration
- `requirements.txt` - python-keycloak, kubernetes dependencies
- `Dockerfile` - container image for job

### 4. E2E Test for MLflow (`kagenti/tests/e2e/common/test_mlflow_auth.py`)

Verify weather agent traces appear in MLflow after E2E tests run.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MLFLOW_URL` | MLflow server URL | Auto-detect from cluster |
| `MLFLOW_TRACKING_URI` | MLflow tracking server URL | Auto-detect from cluster |

## Success Criteria

1. MLflow pod running and accessible
2. Weather agent traces visible in MLflow UI
3. E2E test validates traces exist in MLflow
4. OAuth authentication works when enabled

## Implementation Status

### Phase 1: Fix Basic Deployment ✅ COMPLETE

- [x] Fix startup probe (use TCP socket for startup, `/version` for readiness/liveness)
- [x] Configure proper `--allowed-hosts` based on domain:
  - OpenShift: Use route hostname from `{{ .Values.domain }}`
  - Kind: Use `mlflow.localtest.me`
- [x] Add mlflow database creation to postgres init script (`phoenix-postgres.yaml`)
- [x] Fix pip install permissions with `HOME=/tmp`
- [x] Use `psycopg[binary]` for MLflow 3.x PostgreSQL driver
- [x] Increase memory limits (512Mi request, 2Gi limit) - MLflow 3.x needs more RAM

### Phase 2: OAuth2 Integration ✅ COMPLETE

- [x] Create `kagenti/auth/mlflow-oauth-secret/` directory with:
  - `mlflow_oauth_secret.py` - Keycloak client registration
  - `requirements.txt` - python-keycloak, kubernetes dependencies
  - `Dockerfile` - container image for job

- [x] Create `charts/kagenti/templates/mlflow-oauth-secret-job.yaml`:
  - Register Keycloak client for MLflow (confidential client)
  - Create Kubernetes secret with OAuth credentials
  - RBAC for cross-namespace secret access

- [x] Update `charts/kagenti-deps/templates/mlflow.yaml`:
  - Add init container to wait for OAuth secret
  - Inject OAuth environment variables from secret
  - Configure MLflow with mlflow-oidc-auth plugin

- [x] Add values configuration to:
  - `charts/kagenti/values.yaml` - MLflow OAuth secret creator config
  - `charts/kagenti-deps/values.yaml` - MLflow auth settings

### Phase 3: E2E Tests ✅ COMPLETE

- [x] Create `kagenti/tests/e2e/common/test_mlflow_auth.py`:
  - Test MLflow accessible (200/401/302)
  - Test OAuth secret exists with required keys
  - Test authenticated access with Keycloak token
  - Test MLflow traces exist after weather agent runs

- [x] Update test fixtures to support MLflow authentication:
  - Reuse Keycloak token fixture from Phoenix tests
  - Add MLflow-specific URL and endpoint helpers

### Option 2: GenAI Auto-Instrumentation ✅ COMPLETE

- [x] Add OpenTelemetry GenAI auto-instrumentation to weather agent
  - Added `opentelemetry-instrumentation-openai` to pyproject.toml
  - Added `OpenAIInstrumentor().instrument()` in agent.py
  - PR: https://github.com/ladas/agent-examples branch: genai-autoinstrumentation

- [x] Add OTEL Collector transform processor to convert GenAI spans to OpenInference
  - Added `transform/genai_to_openinference` processor
  - Converts `gen_ai.*` attributes to `llm.*` OpenInference format

- [x] Update weather agent Shipwright builds to use fork until PR merged
  - `weather_agent_shipwright_build.yaml`
  - `weather_agent_shipwright_build_ocp.yaml`

## Pending: After Agent-Examples PR Merged

- [ ] Revert Shipwright builds back to `kagenti/agent-examples` + `main`
- [ ] Build and push `mlflow-oauth-secret` container image to GHCR

## Authentication Options

| Option | Pros | Cons |
|--------|------|------|
| [mlflow-oidc-auth](https://pypi.org/project/mlflow-oidc-auth/) | Native MLflow integration, single container | Requires pip install at runtime |
| oauth2-proxy sidecar | Standard pattern, no MLflow changes | Additional container, more resources |
| Ingress-level auth | Centralized, works with any backend | Requires ingress controller support |

**Chosen**: Use `mlflow-oidc-auth` plugin for consistency with Phoenix's native
OAuth approach. Install via pip in container command along with `psycopg[binary]`.

## Security Considerations

1. **Never use `--allowed-hosts all`** in production - configure specific domains
2. **Use confidential OAuth client** (like Phoenix) - secrets stored server-side
3. **TLS termination** at Route/Ingress level, not in MLflow container
4. **Minimal RBAC** - MLflow only reads its own OAuth secret

## References

- [MLflow Tracing](https://mlflow.org/docs/latest/llms/tracing/index.html)
- [MLflow OTLP Integration](https://mlflow.org/docs/latest/llms/tracing/tracing-schema.html)
- [OpenInference Spec](https://github.com/Arize-ai/openinference)
- [MLflow Security Middleware](https://mlflow.org/docs/latest/self-hosting/security/network/)
- [MLflow SSO Documentation](https://mlflow.org/docs/latest/self-hosting/security/sso/)
- [mlflow-oidc-auth Plugin](https://pypi.org/project/mlflow-oidc-auth/)
- [Phoenix OAuth PR #564](https://github.com/kagenti/kagenti/pull/564)
- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
