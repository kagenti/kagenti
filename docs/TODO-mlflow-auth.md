# MLflow Authentication Architecture - TODO and Analysis

## Current State

MLflow is deployed with `mlflow-oidc-auth` plugin providing Keycloak OIDC authentication.
The OTEL collector sends traces to MLflow's `/v1/traces` endpoint using OAuth2 client credentials.

### What Works

1. **UI Authentication**: Users authenticate via Keycloak → OIDC → session cookie
2. **OTEL Trace Ingestion**: OTEL collector → `/v1/traces` endpoint (mTLS via Istio)
3. **Authorization Policy**: Istio AuthorizationPolicy restricts `/v1/traces` to otel-collector SA

### Current Workarounds

We apply runtime patches to mlflow-oidc-auth because:

1. **Missing otel_router**: mlflow-oidc-auth doesn't include MLflow's `otel_router`
   for the `/v1/traces` OTLP endpoint
   - **Fix**: Patch `get_all_routers()` before app creation to include `otel_router`
   - **Upstream issue**: Should be reported to https://github.com/mlflow-oidc/mlflow-oidc-auth

2. **No path exclusions**: mlflow-oidc-auth hardcodes unprotected paths in middleware
   - **Fix**: Monkey-patch `AuthMiddleware._is_unprotected_route()` to exclude `/v1/traces`
   - **Security**: Istio AuthorizationPolicy handles auth for this path via mTLS
   - **Upstream request**: Add `OIDC_EXCLUDE_PATHS` environment variable

3. **MLflow tracking store**: Need both `MLFLOW_BACKEND_STORE_URI` and `MLFLOW_TRACKING_URI`
   for the otel_router to use PostgreSQL instead of SQLite

## Open Issues

### 1. E2E Test Authentication

**Problem**: E2E tests can't read traces from MLflow API because it requires OIDC auth.

**Options**:
- [ ] Create a service account user in mlflow-oidc-auth with basic auth
- [ ] Use Keycloak service account for test client
- [ ] Add read-only paths to unprotected list (security concern)

### 2. Programmatic API Access

**Problem**: CI/CD pipelines and internal services need to access MLflow API.

**Options**:
- [ ] Basic auth users (mlflow-oidc-auth supports this)
- [ ] Service account tokens from Keycloak
- [ ] Robot accounts (mlflow-oidc-proxy pattern)

## Alternative Architectures

### Option A: Current Approach (mlflow-oidc-auth + Runtime Patches)

```
Browser → Keycloak OIDC → mlflow-oidc-auth → MLflow
OTEL    → mTLS (Istio) → /v1/traces (patched) → MLflow
```

**Pros**:
- Single MLflow instance
- Direct OIDC integration
- Role/group mapping via Keycloak claims

**Cons**:
- Runtime patches required (fragile)
- No native path exclusions
- Maintenance burden on upgrades

### Option B: OAuth2-Proxy Sidecar

```
Browser → oauth2-proxy → MLflow (no auth)
OTEL    → mTLS (Istio) → MLflow /v1/traces
```

**Pros**:
- MLflow stays stateless
- Stronger separation of concerns
- Well-supported oauth2-proxy project

**Cons**:
- Additional network hop
- Extra service to manage
- Less tight coupling with MLflow RBAC

### Option C: Istio-Level Authentication

```
Browser → Istio RequestAuth (JWT) → MLflow (no auth)
OTEL    → Istio AuthPolicy (mTLS) → MLflow /v1/traces
```

**Pros**:
- No application-level auth needed
- Unified auth at mesh level
- Simpler MLflow configuration

**Cons**:
- No experiment-level RBAC
- Less flexible for complex policies
- Requires JWT in every request

### Option D: mlflow-oidc-proxy (Multi-Tenant)

```
Browser → mlflow-oidc-proxy → MLflow-A (team-a)
                           → MLflow-B (team-b)
OTEL    → mlflow-oidc-proxy → MLflow-{team}
```

**Pros**:
- True multi-tenancy
- Policy-based authorization
- Namespace → MLflow isolation

**Cons**:
- Multiple MLflow instances
- Higher resource usage
- More complex deployment

## Recommendations

### Short-term (Current Sprint)

1. **Keep current approach** with documented runtime patches
2. **Create upstream issue** for mlflow-oidc-auth:
   - Request: Include `otel_router` in `get_all_routers()`
   - Request: Add `OIDC_EXCLUDE_PATHS` environment variable
3. **Fix E2E tests**: Use Keycloak service account token or basic auth

### Medium-term (Next Quarter)

1. **Evaluate Istio-level auth** for simpler setup:
   - Add RequestAuthentication for Keycloak JWT
   - Add AuthorizationPolicy for path-based access
   - Remove mlflow-oidc-auth if mesh auth sufficient

2. **Consider mlflow-oidc-proxy** if multi-tenancy needed:
   - Namespace → separate MLflow mapping
   - Policy-based tenant isolation

### Long-term (Future)

1. **Contribute upstream** to mlflow-oidc-auth:
   - PR for otel_router inclusion
   - PR for configurable path exclusions

2. **Standardize ML observability** across platforms:
   - Unified auth for Phoenix + MLflow + Kiali
   - Consistent trace ingestion patterns

## Security Model

### Current Security Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                      Security Architecture                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Layer 1: Network (Istio mTLS)                                  │
│  ├── All pod-to-pod traffic encrypted                          │
│  ├── SPIFFE identity for each workload                         │
│  └── Zero-trust by default                                      │
│                                                                  │
│  Layer 2: Authorization (Istio AuthorizationPolicy)             │
│  ├── /v1/traces: Only otel-collector SA allowed (POST)         │
│  └── Other paths: Any authenticated principal                   │
│                                                                  │
│  Layer 3: Authentication (mlflow-oidc-auth)                     │
│  ├── UI: Keycloak OIDC session                                  │
│  ├── API: Bearer token or basic auth                            │
│  └── /v1/traces: Excluded (mTLS handles auth)                   │
│                                                                  │
│  Layer 4: Application (MLflow RBAC)                             │
│  ├── Experiment permissions (READ/EDIT/MANAGE)                  │
│  └── Group-based access control                                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Trace Ingestion Security

The `/v1/traces` endpoint is secured via:

1. **Istio mTLS**: Mutual TLS authentication
2. **AuthorizationPolicy**: Only `otel-collector` service account can POST
3. **Network isolation**: Internal cluster traffic only (no ingress)

This is the **recommended pattern** for machine-to-machine authentication.

## References

- [mlflow-oidc-auth GitHub](https://github.com/mlflow-oidc/mlflow-oidc-auth)
- [mlflow-oidc-proxy GitHub](https://github.com/meln5674/mlflow-oidc-proxy)
- [MLflow Authentication Docs](https://mlflow.org/docs/latest/auth/index.html)
- [Istio Authorization](https://istio.io/latest/docs/tasks/security/authorization/)
- [OTLP Receiver Security](https://www.dash0.com/guides/opentelemetry-otlp-receiver)
- [oauth2-proxy with Keycloak](https://oauth2-proxy.github.io/oauth2-proxy/configuration/providers/keycloak_oidc/)
