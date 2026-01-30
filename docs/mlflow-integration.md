# MLflow Integration for LLM Observability

This document describes deploying MLflow alongside Phoenix for LLM trace
collection in Kagenti E2E tests.

## Overview

MLflow Tracing provides LLM observability similar to Phoenix. This integration
allows comparing both tools and validating that weather agent traces are
captured correctly.

## Architecture

```
Weather Agent
    │
    │ OTLP (port 8335)
    ▼
OTEL Collector
    │
    ├──► [filter/phoenix] ──► Phoenix (OpenInference spans only)
    │
    └──► [filter/mlflow] ──► MLflow (GenAI semantic convention spans)
```

## Current State

- Phoenix receives traces via OTEL Collector filter for `openinference.*` scopes
- Weather agent uses OpenInference instrumentation (`openinference-instrumentation-langchain`)
- OTEL Collector filters out non-OpenInference spans before sending to Phoenix

## MLflow Integration Approach

### Option 1: Dual Export (Recommended)

Add MLflow as a second exporter in OTEL Collector:
- Export the same OpenInference spans to both Phoenix and MLflow
- MLflow can ingest OTLP traces directly (since MLflow 2.14+)

### Option 2: GenAI Auto-Instrumentation + Transform

1. Add OpenTelemetry GenAI auto-instrumentation to weather agent
2. Use OTEL Collector transform processor to convert GenAI spans to OpenInference
3. Export to both Phoenix and MLflow

## Components to Add

### 1. MLflow Helm Template (`charts/kagenti-deps/templates/mlflow.yaml`)

Deploys MLflow tracking server with:
- PostgreSQL backend (shared with Phoenix or dedicated)
- OTLP receiver endpoint
- UI access via HTTPRoute/Route

### 2. OTEL Collector Pipeline Update

Add MLflow exporter pipeline:
```yaml
exporters:
  otlp/mlflow:
    endpoint: mlflow:4317
    tls:
      insecure: true

pipelines:
  traces/mlflow:
    receivers: [otlp]
    processors: [memory_limiter, batch]
    exporters: [otlp/mlflow]
```

### 3. E2E Test for MLflow Traces

Verify weather agent traces appear in MLflow after E2E tests run.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MLFLOW_TRACKING_URI` | MLflow server URL | Auto-detect from cluster |

## Success Criteria

1. MLflow pod running and accessible
2. Weather agent traces visible in MLflow UI
3. E2E test validates traces exist in MLflow

## TODO: Security and Authentication

### Resolved Issues

- [x] **Startup probe failing**: Fixed by using TCP socket for startup probe and
      `/version` endpoint for readiness/liveness probes. The `/health` endpoint is
      unreliable during MLflow startup.

- [x] **`--allowed-hosts all` is insecure**: Fixed by configuring specific allowed hosts
      based on domain (`mlflow.{{ .Values.domain }}`) plus internal Kubernetes DNS names.

### Security Implementation (Follow Phoenix Pattern from PR #564)

MLflow 3.x has [security middleware](https://mlflow.org/docs/latest/self-hosting/security/network/)
that protects against DNS rebinding, CORS, and clickjacking. For OAuth authentication,
use the [oauth2-proxy pattern](https://mlflow.org/docs/latest/self-hosting/security/sso/)
recommended by MLflow documentation.

#### Phase 1: Fix Basic Deployment

- [x] Fix startup probe (use TCP socket for startup, `/version` for readiness/liveness)
- [x] Configure proper `--allowed-hosts` based on domain:
  - OpenShift: Use route hostname from `{{ .Values.domain }}`
  - Kind: Use `mlflow.localtest.me`
- [x] Add mlflow database creation to postgres init script (`phoenix-postgres.yaml`)
- [x] Fix pip install permissions with `HOME=/tmp`
- [x] Use `psycopg[binary]` for MLflow 3.x PostgreSQL driver
- [x] Increase memory limits (512Mi request, 2Gi limit) - MLflow 3.x needs more RAM

#### Phase 2: OAuth2 Integration (Similar to Phoenix PR #564)

- [ ] Create `kagenti/auth/mlflow-oauth-secret/` directory with:
  - `mlflow_oauth_secret.py` - Keycloak client registration
  - `requirements.txt` - python-keycloak, kubernetes dependencies
  - `Dockerfile` - container image for job

- [ ] Create `charts/kagenti/templates/mlflow-oauth-secret-job.yaml`:
  - Register Keycloak client for MLflow (confidential client)
  - Create Kubernetes secret with OAuth credentials
  - RBAC for cross-namespace secret access

- [ ] Update `charts/kagenti-deps/templates/mlflow.yaml`:
  - Add init container to wait for OAuth secret
  - Inject OAuth environment variables from secret
  - Configure MLflow with [mlflow-oidc-auth plugin](https://pypi.org/project/mlflow-oidc-auth/)
    or oauth2-proxy sidecar

- [ ] Add values configuration:
  ```yaml
  mlflow:
    auth:
      enabled: false  # Enable in ocp_values.yaml
      secretName: mlflow-oauth-secret
  mlflowOAuthSecret:
    image: ghcr.io/kagenti/kagenti/mlflow-oauth-secret
    tag: latest
    clientId: mlflow
  ```

#### Phase 3: E2E Tests

- [ ] Create `kagenti/tests/e2e/common/test_mlflow_auth.py`:
  - Test MLflow accessible (200/401/302)
  - Test OAuth secret exists with required keys
  - Test authenticated access with Keycloak token
  - Test MLflow traces exist after weather agent runs

- [ ] Update test fixtures to support MLflow authentication:
  - Reuse Keycloak token fixture from Phoenix tests
  - Add MLflow-specific URL and endpoint helpers

### Authentication Options

| Option | Pros | Cons |
|--------|------|------|
| [mlflow-oidc-auth](https://pypi.org/project/mlflow-oidc-auth/) | Native MLflow integration, single container | Requires pip install at runtime |
| oauth2-proxy sidecar | Standard pattern, no MLflow changes | Additional container, more resources |
| Ingress-level auth | Centralized, works with any backend | Requires ingress controller support |

**Recommendation**: Use `mlflow-oidc-auth` plugin for consistency with Phoenix's native
OAuth approach. Install via pip in container command along with `psycopg[binary]`.

### Security Considerations

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
