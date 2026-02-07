# Kagenti RBAC Guide

This guide explains how to set up users, groups, and roles across all Kagenti services. It covers how Keycloak acts as the central identity provider, how each service consumes identity, and what configuration is needed for different personas.

## Architecture Overview

```
                    ┌─────────────┐
                    │  Keycloak   │
                    │  (master    │
                    │   realm)    │
                    └──────┬──────┘
                           │
            ┌──────────────┼──────────────────┐
            │              │                  │
     ┌──────▼──────┐ ┌─────▼──────┐   ┌──────▼──────┐
     │ Kagenti UI  │ │   MLflow   │   │  Kagenti    │
     │ (public     │ │ (confid.   │   │  Backend    │
     │  client,    │ │  client,   │   │  (JWT       │
     │  PKCE)      │ │  groups)   │   │  validation)│
     └─────────────┘ └────────────┘   └─────────────┘
```

All user authentication flows through Keycloak. Each downstream service has its own authorization model:

| Service | Auth Method | Authorization Model |
|---------|-------------|---------------------|
| Kagenti UI | OIDC (public client, PKCE) | Keycloak realm roles |
| Kagenti Backend | JWT validation | `realm_access.roles` + `resource_access` |
| MLflow | OIDC (confidential client) | Keycloak groups (`mlflow`, `mlflow-admin`) |
| OTEL Collector | Client credentials | Service account (no user context) |
| MCP Gateway | SPIFFE JWT / token exchange | SPIFFE workload identity |
| Istio | mTLS + AuthorizationPolicy | Service identity (principal-based) |

## Keycloak Setup

### Realm

Kagenti uses the `master` realm by default. All users, groups, and clients are configured here.

- **Kind**: `http://keycloak.localtest.me:8080`
- **OpenShift**: `https://keycloak-keycloak.apps.<cluster-domain>`
- **Admin Console**: `/admin/master/console`
- **Default credentials**: `admin` / `admin` (from `keycloak-initial-admin` secret in `keycloak` namespace)

### Users

Users are created in Keycloak and shared across all services. The platform creates one default user during installation:

| User | Password | Created By | Purpose |
|------|----------|------------|---------|
| `admin` | `admin` | Helm install | Platform administrator |

To create additional users:

1. **Keycloak Admin Console** > Users > Add User
2. Set username, email, first name, last name
3. Go to Credentials tab > Set Password
4. Go to Groups tab > Join groups (see [Groups](#groups) below)
5. Go to Role Mappings tab > Assign roles (see [Roles](#roles) below)

**Required profile fields**: MLflow OIDC auth requires `firstName`, `lastName`, and `email` to be set. Without these, users get a "No display name provided in OIDC userinfo" error. The `mlflow-oauth-secret` job auto-populates these for existing users, but new users should have them set at creation time.

### Groups

Groups control access to services that use group-based authorization:

| Group | Purpose | Services | Created By |
|-------|---------|----------|------------|
| `mlflow` | MLflow read/write access | MLflow (via `mlflow-oidc-auth`) | `mlflow-oauth-secret` job |
| `mlflow-admin` | MLflow admin access | MLflow (via `mlflow-oidc-auth`) | Manual (optional) |
| `team1` | Namespace scoped access | MLflow experiment permissions | `mlflow-experiment-init` job |
| `team2` | Namespace scoped access | MLflow experiment permissions | `mlflow-experiment-init` job |

**How groups propagate to tokens**: The `mlflow-oauth-secret` job creates a `groups` protocol mapper on the MLflow client. This adds a `groups` claim to the JWT token containing the user's group memberships. The `mlflow-oidc-auth` plugin reads this claim to authorize access.

### Roles

Keycloak realm roles control access to the Kagenti backend API:

| Role | Purpose | Backend Enforcement |
|------|---------|---------------------|
| `admin` | Full platform access | `require_roles("admin")` dependency |
| `slack-full-access` | Full Slack tool access | Token exchange scoping |
| `slack-partial-access` | Read-only Slack access | Token exchange scoping |
| `github-full-access` | Full GitHub tool access | Token exchange scoping |
| `github-partial-access` | Read-only GitHub access | Token exchange scoping |

The backend validates roles from the JWT token's `realm_access.roles` and `resource_access.*.roles` claims. See `kagenti/backend/app/core/auth.py`.

### Clients

Each service registers as an OAuth2 client in Keycloak:

| Client ID | Type | Flow | Created By |
|-----------|------|------|------------|
| `kagenti-ui` | Public | Authorization Code + PKCE | `ui-oauth-secret` job |
| `mlflow` | Confidential | Auth Code + Client Credentials | `mlflow-oauth-secret` job |
| `otel-collector` | Confidential | Client Credentials | `otel-oauth-secret` job |
| `admin-cli` | Built-in | Password Grant | Keycloak default |
| `spiffe://.../sa/<name>` | Confidential | JWT-based (SPIFFE) | `agent-oauth-secret` job |

## Service-Specific RBAC

### Kagenti Backend

The FastAPI backend validates JWT tokens from Keycloak and extracts roles:

```python
# Any authenticated user
@router.get("/agents")
async def list_agents(user: TokenData = Depends(get_current_user)):
    ...

# Admin-only endpoint
@router.get("/admin/config", dependencies=[Depends(require_roles("admin"))])
async def get_config():
    ...
```

**Current state**: Auth can be disabled via `ENABLE_AUTH=false`, which returns a mock `admin` user. When enabled, all endpoints validate JWT tokens against Keycloak's JWKS endpoint.

**Role extraction** (from `kagenti/backend/app/core/auth.py:155-161`):
- `realm_access.roles` - Realm-level roles
- `resource_access.<client>.roles` - Client-specific roles

### MLflow (mlflow-oidc-auth)

MLflow uses the [mlflow-oidc-auth](https://pypi.org/project/mlflow-oidc-auth/) plugin for group-based authorization.

#### Access Levels

| Access Level | Keycloak Group | Permissions |
|-------------|----------------|-------------|
| Standard user | `mlflow` | Login, view experiments/runs, create runs |
| Admin user | `mlflow-admin` | Manage experiments, users, permissions |
| No access | (no group) | Rejected with "User is not allowed to login" |

#### Experiment Permissions

Experiments are mapped to Kubernetes namespaces. Each namespace gets an experiment, and a Keycloak group with the same name gets `MANAGE` permission:

```
Namespace: team1
  └─ MLflow Experiment: "team1" (id: auto-assigned)
       └─ Permission: @team1 → MANAGE
```

The `@` prefix indicates a group (not a user) in mlflow-oidc-auth. This is set up by the `mlflow-experiment-init` job.

#### Experiment 0 (Default)

The default experiment (id=0) is created during MLflow container startup. All users in the `mlflow` group can access it. It stores traces from agents that don't specify a namespace-specific experiment.

#### OTEL Trace Ingestion

The `/v1/traces` endpoint is excluded from OIDC auth and instead secured by Istio:

```yaml
# Istio AuthorizationPolicy (L7 via waypoint proxy)
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: mlflow-traces-from-otel
spec:
  targetRefs:
    - kind: Service
      name: mlflow
  action: ALLOW
  rules:
    - from:
        - source:
            principals:
              - "cluster.local/ns/kagenti-system/sa/otel-collector"
      to:
        - operation:
            methods: ["POST"]
            paths: ["/v1/traces", "/v1/traces/*"]
    - to:
        - operation:
            notPaths: ["/v1/traces", "/v1/traces/*"]
```

This means only the OTEL collector service account can POST traces, while all other endpoints use OIDC auth.

#### Programmatic MLflow Access

To access MLflow programmatically (e.g., from scripts):

```bash
# Get token via client credentials flow
TOKEN=$(curl -s -X POST \
  "http://keycloak-service.keycloak.svc.cluster.local:8080/realms/master/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=mlflow" \
  -d "client_secret=$MLFLOW_CLIENT_SECRET" | jq -r .access_token)

# Use with MLflow API
export MLFLOW_TRACKING_TOKEN=$TOKEN
mlflow experiments search
```

### Kagenti UI

The UI uses a public OAuth2 client with PKCE (no client secret stored in browser):

1. User clicks Login
2. Browser redirects to Keycloak login page
3. User authenticates
4. Keycloak redirects back with authorization code
5. UI exchanges code for tokens (with PKCE verifier)
6. JWT stored in browser, sent as `Authorization: Bearer <token>`

The UI currently shows all features to all authenticated users. Role-based UI visibility is planned but not yet implemented.

### Agent Namespaces (team1, team2)

Agent namespaces are configured with labels that enable platform features:

```yaml
metadata:
  labels:
    kagenti-enabled: "true"           # Platform recognition
    istio-discovery: enabled          # Istio ambient mode
    istio.io/dataplane-mode: ambient  # Service mesh enrollment
    istio.io/use-waypoint: waypoint   # L7 policy evaluation
    shared-gateway-access: "true"     # Ingress gateway access
```

Each namespace gets:
- An `agent-oauth-secret` - Keycloak client credentials for agents in this namespace
- SPIFFE identity entries - `spiffe://<trust-domain>/ns/<namespace>/sa/<service-account>`
- MLflow experiment - Named after the namespace, with group-based MANAGE permission

### SPIFFE/SPIRE Workload Identity

Agents and tools use SPIFFE SVIDs (identity documents) for machine-to-machine auth:

```
spiffe://<trust-domain>/ns/<namespace>/sa/<service-account>

# Examples:
spiffe://localtest.me/ns/team1/sa/slack-researcher
spiffe://localtest.me/ns/gateway-system/sa/mcp-gateway
```

These SPIFFE IDs are registered as Keycloak client IDs, enabling OAuth2 token exchange:

```
User Token → Token Exchange (RFC 8693) → Agent-scoped Token → Tool Access
```

## Persona Setup Guide

### End User

An end user interacts with agents through the UI.

**Keycloak setup**:
1. Create user with username, email, first name, last name
2. Set password
3. Add to `mlflow` group (for trace viewing)
4. No realm roles needed (UI access is role-free currently)

**What they can do**:
- Login to Kagenti UI
- Chat with deployed agents
- View agent catalog and tool catalog
- View MLflow traces (read-only, via `mlflow` group)

### Agent Developer

An agent developer deploys and tests agents in team namespaces.

**Keycloak setup**:
1. Create user with username, email, first name, last name
2. Set password
3. Add to `mlflow` group (for trace access)
4. Add to `team1` group (for namespace-specific experiment access)
5. (Optional) Assign tool-access roles like `slack-partial-access`

**Kubernetes access needed**:
- `kubectl` access to their team namespace(s) for deploying agents
- Or use the Kagenti UI "Import Agent" feature

**What they can do**:
- Deploy agents to `team1`/`team2` namespaces
- View traces for their agents in MLflow
- Access agents via A2A protocol

### Platform Administrator

A platform admin manages all Kagenti infrastructure.

**Keycloak setup**:
1. Create user (or use default `admin`)
2. Add `admin` realm role
3. Add to `mlflow` group and `mlflow-admin` group
4. Add to all namespace groups (`team1`, `team2`, etc.)

**Kubernetes access needed**:
- Cluster-admin or equivalent

**What they can do**:
- Full access to Kagenti UI admin page
- Manage MLflow experiments and permissions
- Deploy to any namespace
- Configure Keycloak clients, users, groups

### Service Account (Machine-to-Machine)

For CI/CD pipelines or automated tools.

**Keycloak setup**:
1. Create a confidential client (not a user)
2. Enable `serviceAccountsEnabled: true`
3. Disable `standardFlowEnabled` (no browser login)
4. Add client scopes as needed

**Example** (registering via Keycloak Admin API):
```python
{
    "clientId": "ci-pipeline",
    "publicClient": False,
    "serviceAccountsEnabled": True,
    "standardFlowEnabled": False,
    "directAccessGrantsEnabled": False,
}
```

**Authentication**:
```bash
curl -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=ci-pipeline" \
  -d "client_secret=$CLIENT_SECRET"
```

## How Services Sign In via Keycloak

### Flow 1: Browser Login (UI, MLflow)

```
Browser → Keycloak Login Page → Authorization Code → Token Exchange → JWT
```

Both the Kagenti UI and MLflow use this flow. The UI uses a public client (PKCE), MLflow uses a confidential client.

### Flow 2: Client Credentials (Service-to-Service)

```
Service → POST /token (client_id + client_secret) → JWT
```

Used by OTEL Collector, CI pipelines, and automated tools. No user context - the service authenticates as itself.

### Flow 3: Token Exchange (Agent Delegation)

```
User JWT → Token Exchange (RFC 8693) → Agent-scoped JWT → Tool Access
```

Used when an agent needs to call a tool on behalf of a user. The agent's SPIFFE identity is the `client_id`, and the user's token is the `subject_token`.

### Flow 4: SPIFFE JWT (Workload Identity)

```
SPIRE Agent → JWT SVID → Keycloak validates via JWKS → Access Granted
```

Used for machine identity. The SPIFFE ID is registered as a Keycloak client, and the JWT SVID contains the workload's identity.

## Configuration Reference

### Secrets Created by Installation

| Secret | Namespace | Keys | Created By |
|--------|-----------|------|------------|
| `keycloak-initial-admin` | `keycloak` | `username`, `password` | Helm chart |
| `kagenti-ui-oauth-secret` | `kagenti-system` | `CLIENT_ID`, `CLIENT_SECRET`, `AUTH_ENDPOINT`, `TOKEN_ENDPOINT` | `ui-oauth-secret` job |
| `mlflow-oauth-secret` | `kagenti-system` | `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_DISCOVERY_URL`, `OIDC_TOKEN_URL`, `OIDC_REDIRECT_URI` | `mlflow-oauth-secret` job |
| `kagenti-keycloak-client-secret` | `team1`, `team2` | `client-secret` | `agent-oauth-secret` job |

### Environment Variables

| Variable | Service | Purpose |
|----------|---------|---------|
| `ENABLE_AUTH` | Backend | Enable/disable JWT validation |
| `KEYCLOAK_URL` | Backend, Tests | Keycloak server URL |
| `KEYCLOAK_REALM` | Backend | Realm name (default: `master`) |
| `OIDC_GROUP_NAME` | MLflow | Required group for access (default: `mlflow`) |
| `OIDC_ADMIN_GROUP_NAME` | MLflow | Admin group (default: `mlflow-admin`) |
| `MLFLOW_TRACKING_TOKEN` | Scripts, Tests | Bearer token for MLflow API |

## Troubleshooting

### "User is not allowed to login" (MLflow)

The user is not in the `mlflow` Keycloak group. Add them:
1. Keycloak Admin Console > Users > Select user > Groups > Join Group > `mlflow`

### "No display name provided in OIDC userinfo" (MLflow)

The user is missing `firstName`, `lastName`, or `email` in Keycloak. Update their profile:
1. Keycloak Admin Console > Users > Select user > Details > Fill in missing fields

### "Required role(s): admin" (Backend API)

The user doesn't have the `admin` realm role. Assign it:
1. Keycloak Admin Console > Users > Select user > Role Mappings > Assign `admin`

### Token missing `groups` claim

The MLflow client is missing the groups protocol mapper. The `mlflow-oauth-secret` job should have created it. Verify:
1. Keycloak Admin Console > Clients > `mlflow` > Client Scopes > Dedicated > Check for `groups` mapper

### Agent can't exchange tokens

Check that:
1. The agent's SPIFFE ID is registered as a Keycloak client
2. The client has `standardFlowEnabled: true` and `directAccessGrantsEnabled: true`
3. The target audience (tool) client exists in Keycloak
4. Token exchange permissions are configured
