# Scoped Tokens Guide: AuthBridge Token Exchange for Kagenti Services

> **Date:** 2026-02-25 | **Applies to:** Kagenti platform with SPIRE, Keycloak, AuthBridge, and agent sandboxes

## Overview

Kagenti uses **scoped tokens** to enforce least-privilege access across all services. No workload ever receives a long-lived credential or a token with more permissions than it needs. This guide covers how to create, configure, and use scoped tokens for every service in the platform.

**Core flow:**
```
SPIRE Agent → SPIFFE SVID → Keycloak Token Exchange (RFC 8693) → Scoped OAuth2 Token → Service
```

**Key principle:** The agent never handles raw credentials. AuthBridge (Envoy ext_proc) intercepts all outbound requests and transparently injects scoped tokens.

---

## Table of Contents

1. [Architecture: How Scoped Tokens Work](#1-architecture)
2. [Prerequisites](#2-prerequisites)
3. [SPIFFE/SPIRE: Workload Identity](#3-spire)
4. [Keycloak: Client Registration](#4-keycloak-registration)
5. [Keycloak: Token Exchange Configuration](#5-token-exchange)
6. [Service-Specific Token Scoping](#6-services)
   - [6.1 GitHub API](#61-github)
   - [6.2 LLM APIs (OpenAI, Anthropic, etc.)](#62-llm)
   - [6.3 MLflow](#63-mlflow)
   - [6.4 Package Registries (PyPI, npm)](#64-registries)
   - [6.5 Slack API](#65-slack)
   - [6.6 Agent-to-Agent (A2A)](#66-a2a)
   - [6.7 MCP Gateway](#67-mcp)
7. [AuthBridge: Transparent Token Injection](#7-authbridge)
8. [Sandbox Agent Token Flow](#8-sandbox)
9. [Verification and Debugging](#9-verification)
10. [Security Best Practices](#10-security)

---

## 1. Architecture: How Scoped Tokens Work {#1-architecture}

```
┌─────────────────────────────────────────────────────────────────────┐
│  Sandbox Agent Pod                                                   │
│                                                                      │
│  ┌── Agent Container ──────────────────────────────────────────────┐│
│  │  Makes HTTP requests to external services                       ││
│  │  (agent has NO credentials — just calls URLs normally)          ││
│  └────────────────────────┬────────────────────────────────────────┘│
│                           │ outbound request                        │
│  ┌────────────────────────▼────────────────────────────────────────┐│
│  │  Envoy Sidecar (Istio Ambient) + AuthBridge ext_proc           ││
│  │                                                                 ││
│  │  1. Read pod's SPIFFE SVID (from SPIRE CSI driver)             ││
│  │  2. Present SVID to Keycloak as client credentials             ││
│  │  3. Exchange for scoped token (audience = target service)      ││
│  │  4. Inject token as Authorization header                       ││
│  │  5. Forward request to target                                  ││
│  └────────────────────────┬────────────────────────────────────────┘│
│                           │ request + scoped token                  │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
              ┌─────────────▼────────────────┐
              │  Keycloak (Token Exchange)    │
              │                               │
              │  Validates SVID (JWKS)        │
              │  Checks exchange permissions  │
              │  Issues scoped token:         │
              │  - audience: target service   │
              │  - scope: least privilege     │
              │  - exp: short-lived (5 min)   │
              └──────────────────────────────┘
```

**Three stages of token exchange:**

| Stage | From | To | Token Audience | Purpose |
|-------|------|----|---------------|---------|
| 1. User auth | User (browser) | Keycloak | `kagenti-ui` | User logs in, gets initial token |
| 2. Agent exchange | AuthBridge (SVID) | Keycloak | Agent SPIFFE ID | Agent receives user-delegated token |
| 3. Service exchange | AuthBridge (SVID) | Keycloak | Target service | Agent accesses external service with scoped token |

---

## 2. Prerequisites {#2-prerequisites}

Before creating scoped tokens, ensure:

```bash
# 1. SPIRE is running
kubectl get pods -n spire -l app=spire-server

# 2. Keycloak is accessible
curl -s http://keycloak.keycloak.svc.cluster.local:8080/realms/master/.well-known/openid-configuration | jq .issuer

# 3. SPIRE OIDC discovery is available
curl -s http://spire-oidc.localtest.me:8080/.well-known/openid-configuration | jq .jwks_uri

# 4. Agent namespace has SPIFFE helper configured
kubectl get cm spiffe-helper-config -n team1
```

**Required tools:**
- `kcadm.sh` (Keycloak admin CLI) or `python-keycloak` library
- `kubectl` or `oc` with cluster admin access
- `curl` and `jq` for verification

---

## 3. SPIFFE/SPIRE: Workload Identity {#3-spire}

Every pod in Kagenti gets a cryptographic identity from SPIRE.

### Identity Format

```
spiffe://{trust-domain}/ns/{namespace}/sa/{service-account}
```

**Examples:**
```
spiffe://localtest.me/ns/team1/sa/sandbox-agent          # Sandbox agent in team1
spiffe://localtest.me/ns/team1/sa/slack-researcher        # Slack research agent
spiffe://localtest.me/ns/kagenti-system/sa/kagenti-api    # Platform API
spiffe://apps.ocp.example.com/ns/team2/sa/github-agent    # OpenShift cluster
```

### SVID Delivery to Pods

SPIRE delivers SVIDs via the **SPIFFE CSI Driver** (or SPIFFE Helper sidecar):

```yaml
# Pod spec (automatically injected by SPIFFE Helper config)
volumes:
- name: spiffe-workload-api
  csi:
    driver: csi.spiffe.io
    readOnly: true

containers:
- name: agent
  volumeMounts:
  - name: spiffe-workload-api
    mountPath: /spiffe-workload-api
    readOnly: true
```

**Files written to the pod:**

| File | Content | Used For |
|------|---------|----------|
| `/opt/svid.pem` | X.509 certificate | mTLS |
| `/opt/svid_key.pem` | Private key | mTLS |
| `/opt/svid_bundle.pem` | Trust bundle | CA verification |
| `/opt/jwt_svid.token` | JWT SVID | Token exchange (audience: "kagenti") |

### Verify SVID in a Pod

```bash
# Check JWT SVID is present
kubectl exec -n team1 deploy/sandbox-agent -- cat /opt/jwt_svid.token | jwt decode -

# Expected claims:
# sub: spiffe://localtest.me/ns/team1/sa/sandbox-agent
# aud: kagenti
# iss: https://spire-server.spire.svc.cluster.local:8443
```

---

## 4. Keycloak: Client Registration {#4-keycloak-registration}

Each workload that needs scoped tokens must be registered as a Keycloak client. Kagenti automates this via init containers.

### Automatic Registration (Recommended)

The `agent-oauth-secret-job` runs at install time and registers clients for each agent namespace:

```yaml
# charts/kagenti/templates/agent-oauth-secret-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: agent-oauth-secret
spec:
  template:
    spec:
      containers:
      - name: agent-oauth-secret
        image: ghcr.io/kagenti/agent-oauth-secret:latest
        env:
        - name: KEYCLOAK_BASE_URL
          value: "http://keycloak.keycloak.svc.cluster.local:8080"
        - name: KEYCLOAK_DEMO_REALM
          value: "demo"
        - name: AGENT_NAMESPACES
          value: "team1,team2"
        - name: SPIFFE_PREFIX
          value: "spiffe://localtest.me/sa"
```

**What it creates:**
1. A Keycloak confidential client per agent, with `clientId` = SPIFFE ID
2. A Kubernetes Secret `kagenti-keycloak-client-secret` in each agent namespace
3. A ConfigMap `environments` with Keycloak connection details

### Manual Registration

For custom agents or sandbox agents not covered by the install job:

```python
from keycloak import KeycloakAdmin

# Connect to Keycloak
keycloak_admin = KeycloakAdmin(
    server_url="http://keycloak.keycloak.svc.cluster.local:8080",
    username="admin",
    password="admin",
    realm_name="master",
)

# Register sandbox agent as a confidential client
client_payload = {
    "clientId": "spiffe://localtest.me/ns/team1/sa/sandbox-agent",
    "name": "Sandbox Coding Agent",
    "enabled": True,
    "standardFlowEnabled": False,        # No browser login
    "directAccessGrantsEnabled": False,   # No password grant
    "serviceAccountsEnabled": True,       # Machine-to-machine
    "publicClient": False,                # Confidential
    "protocol": "openid-connect",
    "attributes": {
        "oauth2.device.authorization.grant.enabled": "false",
        "oidc.ciba.grant.enabled": "false",
    },
}

# Create client
client_id_internal = keycloak_admin.create_client(client_payload)
print(f"Created client: {client_id_internal}")

# Get client secret
client_secret = keycloak_admin.get_client_secrets(client_id_internal)
print(f"Client secret: {client_secret['value']}")
```

### Using kcadm.sh (CLI)

```bash
# Login to Keycloak admin
kcadm.sh config credentials \
  --server http://keycloak.keycloak.svc.cluster.local:8080 \
  --realm master \
  --user admin \
  --password admin

# Create a confidential client for the sandbox agent
kcadm.sh create clients -r master \
  -s clientId="spiffe://localtest.me/ns/team1/sa/sandbox-agent" \
  -s name="Sandbox Agent" \
  -s enabled=true \
  -s publicClient=false \
  -s serviceAccountsEnabled=true \
  -s standardFlowEnabled=false \
  -s directAccessGrantsEnabled=false

# Get the client secret
CLIENT_UUID=$(kcadm.sh get clients -r master \
  -q clientId="spiffe://localtest.me/ns/team1/sa/sandbox-agent" \
  --fields id --format csv --noquotes)
kcadm.sh get clients/$CLIENT_UUID/client-secret -r master
```

---

## 5. Keycloak: Token Exchange Configuration {#5-token-exchange}

Token exchange (RFC 8693) allows one client to exchange a token for another client's audience. This must be explicitly enabled per client pair.

### Step 1: Enable Token Exchange on the Target Client

The target service (e.g., `github-tool`, `mlflow`) must allow token exchange:

```bash
# Get the target client UUID
TARGET_UUID=$(kcadm.sh get clients -r master \
  -q clientId="github-tool" \
  --fields id --format csv --noquotes)

# Enable token exchange permission
kcadm.sh update clients/$TARGET_UUID -r master \
  -s 'attributes."token.exchange.standard.flow.enabled"=true'
```

### Step 2: Create a Token Exchange Policy

```bash
# Create a client policy allowing the sandbox agent to exchange tokens
kcadm.sh create clients/$TARGET_UUID/authz/resource-server/policy -r master \
  -s name="allow-sandbox-agent-exchange" \
  -s type="client" \
  -s logic="POSITIVE" \
  -s 'clients=["spiffe://localtest.me/ns/team1/sa/sandbox-agent"]'
```

### Step 3: Create a Token Exchange Permission

```bash
# Create permission linking the policy to the token exchange scope
kcadm.sh create clients/$TARGET_UUID/authz/resource-server/permission -r master \
  -s name="sandbox-agent-exchange-permission" \
  -s type="scope" \
  -s 'scopes=["token-exchange"]' \
  -s 'policies=["allow-sandbox-agent-exchange"]'
```

### Step 4: Test Token Exchange

```bash
# Get agent's JWT SVID
JWT_SVID=$(cat /opt/jwt_svid.token)

# Get user's access token (or use service account token)
USER_TOKEN=$(curl -s -X POST \
  http://keycloak.keycloak.svc.cluster.local:8080/realms/master/protocol/openid-connect/token \
  -d "grant_type=client_credentials" \
  -d "client_id=spiffe://localtest.me/ns/team1/sa/sandbox-agent" \
  -d "client_secret=$CLIENT_SECRET" \
  | jq -r .access_token)

# Exchange for a scoped token targeting github-tool
SCOPED_TOKEN=$(curl -s -X POST \
  http://keycloak.keycloak.svc.cluster.local:8080/realms/master/protocol/openid-connect/token \
  -H "Authorization: Bearer $JWT_SVID" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=$USER_TOKEN" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "audience=github-tool" \
  -d "client_id=spiffe://localtest.me/ns/team1/sa/sandbox-agent" \
  | jq -r .access_token)

echo "$SCOPED_TOKEN" | jwt decode -
# Expected: aud=github-tool, act.sub=spiffe://..., scope=github-read
```

---

## 6. Service-Specific Token Scoping {#6-services}

### 6.1 GitHub API {#61-github}

**Scopes needed by sandbox agents:**

| Operation | Scope | Risk Level |
|-----------|-------|-----------|
| Read code | `repos:read` | Low |
| Create draft PR | `create-draft` | Medium |
| Comment on PR/Issue | `issues:write` | Medium |
| Push to branch | `repos:write` | High (requires HITL) |
| Merge PR | Never granted | Blocked |
| Delete branch | Never granted | Blocked |
| Admin operations | Never granted | Blocked |

**Keycloak client setup:**

```bash
# Create GitHub tool client
kcadm.sh create clients -r master \
  -s clientId="github-tool" \
  -s name="GitHub API Access" \
  -s publicClient=false \
  -s serviceAccountsEnabled=true

# Create client scopes for GitHub permissions
kcadm.sh create client-scopes -r master \
  -s name="github-read" \
  -s protocol="openid-connect"

kcadm.sh create client-scopes -r master \
  -s name="github-draft-pr" \
  -s protocol="openid-connect"

kcadm.sh create client-scopes -r master \
  -s name="github-write" \
  -s protocol="openid-connect"

# Assign scopes to the github-tool client
GITHUB_UUID=$(kcadm.sh get clients -r master \
  -q clientId="github-tool" \
  --fields id --format csv --noquotes)

kcadm.sh update clients/$GITHUB_UUID/default-client-scopes/$(kcadm.sh get client-scopes -r master -q name=github-read --fields id --format csv --noquotes) -r master
```

**AuthBridge configuration:**

```yaml
# ConfigMap for AuthBridge in sandbox pod
apiVersion: v1
kind: ConfigMap
metadata:
  name: authbridge-config
data:
  TARGET_AUDIENCE: "github-tool"
  TOKEN_URL: "http://keycloak.keycloak.svc.cluster.local:8080/realms/master/protocol/openid-connect/token"
  # AuthBridge will exchange SVID for a github-tool scoped token
  # before forwarding requests to api.github.com
```

### 6.2 LLM APIs (OpenAI, Anthropic, etc.) {#62-llm}

LLM API keys are not directly managed by Keycloak — they are external credentials. AuthBridge handles this via a **credential vault** pattern:

```yaml
# Secret containing LLM API key (created by operator)
apiVersion: v1
kind: Secret
metadata:
  name: llm-credentials
  namespace: team1
type: Opaque
data:
  OPENAI_API_KEY: <base64-encoded-key>
  ANTHROPIC_API_KEY: <base64-encoded-key>
```

**AuthBridge injects the appropriate API key based on the outbound request destination:**

| Destination | Header Injected | Source |
|-------------|----------------|--------|
| `api.openai.com` | `Authorization: Bearer $OPENAI_API_KEY` | Secret `llm-credentials` |
| `api.anthropic.com` | `x-api-key: $ANTHROPIC_API_KEY` | Secret `llm-credentials` |
| `ollama.kagenti-system.svc` | None (internal, mTLS only) | SPIFFE SVID |

**The agent code uses litellm and never handles API keys:**

```python
import litellm
# LLM_MODEL and LLM_API_BASE set via environment
# AuthBridge injects the API key transparently
response = litellm.completion(
    model=os.environ["LLM_MODEL"],
    messages=[{"role": "user", "content": "Hello"}],
)
```

### 6.3 MLflow {#63-mlflow}

MLflow uses OAuth2 via the `mlflow-oidc-auth` plugin. A dedicated Keycloak client is created:

```bash
# Created by mlflow-oauth-secret-job (automatic)
# Client: kagenti-mlflow
# Realm: demo (or master)
# Scopes: mlflow-read, mlflow-write

# Manual creation if needed:
kcadm.sh create clients -r demo \
  -s clientId="kagenti-mlflow" \
  -s name="MLflow Observability" \
  -s publicClient=false \
  -s serviceAccountsEnabled=true
```

**MLflow token flow:**
```
Agent → AuthBridge → Keycloak (exchange SVID for mlflow audience) → MLflow API
```

**Environment setup for MLflow:**

```yaml
env:
- name: MLFLOW_TRACKING_URI
  value: "http://mlflow.kagenti-system.svc.cluster.local:5000"
- name: MLFLOW_TRACKING_TOKEN
  # AuthBridge injects this transparently via ext_proc
  # Agent code does NOT need this env var
```

### 6.4 Package Registries (PyPI, npm) {#64-registries}

Package registries are accessed through the **Squid proxy sidecar** (C5), not through token exchange. The proxy enforces domain allowlists:

```
# squid.conf — allowed package registries
acl allowed_domains dstdomain .pypi.org
acl allowed_domains dstdomain .pythonhosted.org
acl allowed_domains dstdomain .npmjs.org
acl allowed_domains dstdomain .registry.npmjs.org
```

**For private registries** (e.g., Artifactory, Nexus), AuthBridge can inject registry credentials:

```yaml
# Secret for private registry auth
apiVersion: v1
kind: Secret
metadata:
  name: registry-credentials
data:
  ARTIFACTORY_TOKEN: <base64-encoded>
```

### 6.5 Slack API {#65-slack}

Slack integration uses a dedicated Keycloak client with scoped permissions:

```bash
# Keycloak client for Slack access
kcadm.sh create clients -r master \
  -s clientId="slack-tool" \
  -s name="Slack API Access" \
  -s publicClient=false \
  -s serviceAccountsEnabled=true

# Create scopes
kcadm.sh create client-scopes -r master \
  -s name="slack-full-access" \
  -s protocol="openid-connect"
# Maps to: channels:read, channels:history, messages:write

kcadm.sh create client-scopes -r master \
  -s name="slack-partial-access" \
  -s protocol="openid-connect"
# Maps to: channels:read only
```

**Token exchange:**
```
Agent SVID → Keycloak → scoped token (aud: slack-tool, scope: slack-partial-access) → Slack API
```

### 6.6 Agent-to-Agent (A2A) {#66-a2a}

A2A communication between agents uses mutual SPIFFE identity (mTLS via Istio Ambient):

```
Agent A (SVID: spiffe://localtest.me/ns/team1/sa/planning-agent)
    │
    │ A2A message/send with contextId
    │ (mTLS: Istio validates both SVIDs)
    │
    ▼
Agent B (SVID: spiffe://localtest.me/ns/team1/sa/sandbox-agent)
    │
    │ AuthBridge ext_proc:
    │   - Validates caller's JWT
    │   - Creates OTEL root span
    │   - Injects traceparent
    │
    ▼
Agent B processes request
```

**No explicit token exchange needed** for intra-mesh A2A — Istio Ambient provides mTLS. For cross-namespace A2A, AuthorizationPolicy controls access:

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: allow-a2a-from-team1
  namespace: team2
spec:
  rules:
  - from:
    - source:
        principals: ["spiffe://localtest.me/ns/team1/sa/planning-agent"]
    to:
    - operation:
        methods: ["POST"]
        paths: ["/.well-known/agent-card.json", "/a2a/*"]
```

### 6.7 MCP Gateway {#67-mcp}

MCP tools are accessed through the Kagenti MCP Gateway, which authenticates via AuthBridge:

```
Agent → MCP Gateway (Envoy) → AuthBridge validates JWT → Tool Server
```

**Gateway configuration:**

```yaml
# MCP Gateway expects a valid JWT with audience "mcp-gateway"
env:
- name: EXPECTED_AUDIENCE
  value: "mcp-gateway"
- name: ISSUER
  value: "http://keycloak.keycloak.svc.cluster.local:8080/realms/master"
```

---

## 7. AuthBridge: Transparent Token Injection {#7-authbridge}

AuthBridge is the component that makes scoped tokens transparent to agents. It runs as an Envoy ext_proc in the Istio Ambient mesh.

### How AuthBridge ext_proc Works

```
Inbound request → Envoy → ext_proc:
  1. Extract JWT from Authorization header
  2. Validate signature via Keycloak JWKS
  3. Check expiration, issuer, audience
  4. If invalid: return HTTP 401
  5. If valid: create OTEL root span, inject traceparent
  6. Forward to agent container

Outbound request → Envoy → ext_proc:
  1. Read pod's SPIFFE SVID
  2. Determine target audience from request URL
  3. Exchange SVID for scoped token via Keycloak
  4. Inject scoped token as Authorization header
  5. Forward to external service
```

### Configuration

AuthBridge is configured via environment variables on the Envoy sidecar:

```yaml
env:
# Inbound validation
- name: ISSUER
  value: "http://keycloak.keycloak.svc.cluster.local:8080/realms/master"
- name: EXPECTED_AUDIENCE
  value: "sandbox-agent"  # This agent's audience

# Outbound exchange
- name: TOKEN_URL
  value: "http://keycloak.keycloak.svc.cluster.local:8080/realms/master/protocol/openid-connect/token"
- name: CLIENT_ID
  valueFrom:
    secretKeyRef:
      name: kagenti-keycloak-client-secret
      key: CLIENT_ID
- name: CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: kagenti-keycloak-client-secret
      key: CLIENT_SECRET
- name: TARGET_AUDIENCE
  value: "github-tool"  # Default outbound audience
```

### OTEL Root Span Creation

On inbound A2A requests, AuthBridge creates a root span with GenAI semantic conventions:

```
Root span: "invoke_agent sandbox-agent"
  Attributes:
    gen_ai.system: "kagenti"
    gen_ai.request.model: <from request body>
    mlflow.spanType: "AGENT"
    a2a.context_id: <from A2A message>
    a2a.task_id: <from A2A message>
  Injected header:
    traceparent: 00-<trace_id>-<span_id>-01
```

---

## 8. Sandbox Agent Token Flow {#8-sandbox}

End-to-end flow for a sandbox agent accessing external services:

```
┌─── Step 1: Pod Startup ───────────────────────────────────────────┐
│                                                                    │
│  SPIRE Agent → issues SVID to pod via CSI driver                  │
│  Init container:                                                   │
│    1. git clone primary repo → /workspace                         │
│    2. Client registration → register with Keycloak using SVID     │
│       Creates client: spiffe://localtest.me/ns/team1/sa/sandbox   │
│       Stores secret in: kagenti-keycloak-client-secret             │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘

┌─── Step 2: Inbound A2A Request ───────────────────────────────────┐
│                                                                    │
│  Caller → sends A2A message with JWT (aud: sandbox-agent)         │
│  AuthBridge ext_proc:                                              │
│    1. Validates JWT via Keycloak JWKS                              │
│    2. Creates OTEL root span                                       │
│    3. Injects traceparent header                                   │
│    4. Forwards to agent container                                  │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘

┌─── Step 3: Agent Makes Outbound Request ──────────────────────────┐
│                                                                    │
│  Agent calls: requests.get("https://api.github.com/repos/...")    │
│                                                                    │
│  AuthBridge ext_proc:                                              │
│    1. Reads SVID: spiffe://localtest.me/ns/team1/sa/sandbox       │
│    2. Exchanges SVID → Keycloak → scoped token (aud: github-tool) │
│    3. Injects: Authorization: Bearer <scoped-github-token>        │
│    4. Request goes through Squid proxy (domain allowlist check)    │
│    5. Reaches api.github.com with scoped token                    │
│                                                                    │
│  Scoped token payload:                                             │
│  {                                                                 │
│    "sub": "user-123",               # Original user identity      │
│    "act": {                                                        │
│      "sub": "spiffe://localtest.me/ns/team1/sa/sandbox"           │
│    },                                # Agent acting on behalf      │
│    "aud": "github-tool",            # Target audience              │
│    "scope": "repos:read create-draft", # Scoped permissions       │
│    "exp": 1735686900                # Short-lived (5 min)          │
│  }                                                                 │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### What the Agent Code Looks Like

The agent has **zero awareness of tokens or credentials:**

```python
import httpx
import litellm

# Agent makes normal HTTP requests — AuthBridge handles auth
async def fetch_repo_info(repo: str) -> dict:
    async with httpx.AsyncClient() as client:
        # AuthBridge intercepts this and injects scoped GitHub token
        resp = await client.get(f"https://api.github.com/repos/{repo}")
        return resp.json()

# Agent calls LLM — AuthBridge injects API key
response = litellm.completion(
    model="claude-sonnet-4-20250514",
    messages=[{"role": "user", "content": "Analyze this code"}],
    # No api_key parameter needed — AuthBridge handles it
)

# Agent sends OTEL traces — AuthBridge created the root span
# Agent's auto-instrumented spans become children automatically
```

---

## 9. Verification and Debugging {#9-verification}

### Verify SPIRE is Issuing SVIDs

```bash
# Check SPIRE server entries
kubectl exec -n spire deploy/spire-server -- \
  /opt/spire/bin/spire-server entry show

# Check a specific agent pod has its SVID
kubectl exec -n team1 deploy/sandbox-agent -- ls -la /opt/
# Should show: svid.pem, svid_key.pem, svid_bundle.pem, jwt_svid.token
```

### Verify Keycloak Client Registration

```bash
# List all clients in the realm
kcadm.sh get clients -r master --fields clientId | jq '.[].clientId'

# Check a specific client exists
kcadm.sh get clients -r master \
  -q clientId="spiffe://localtest.me/ns/team1/sa/sandbox-agent" \
  --fields clientId,enabled,serviceAccountsEnabled
```

### Test Token Exchange Manually

```bash
# Get a service account token for the agent
AGENT_TOKEN=$(curl -s -X POST \
  http://keycloak.keycloak.svc.cluster.local:8080/realms/master/protocol/openid-connect/token \
  -d "grant_type=client_credentials" \
  -d "client_id=spiffe://localtest.me/ns/team1/sa/sandbox-agent" \
  -d "client_secret=$CLIENT_SECRET" \
  | jq -r .access_token)

# Exchange for a scoped token
SCOPED=$(curl -s -X POST \
  http://keycloak.keycloak.svc.cluster.local:8080/realms/master/protocol/openid-connect/token \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=$AGENT_TOKEN" \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:access_token" \
  -d "audience=github-tool" \
  -d "client_id=spiffe://localtest.me/ns/team1/sa/sandbox-agent" \
  -d "client_secret=$CLIENT_SECRET" \
  | jq .)

echo "$SCOPED" | jq .access_token | jwt decode -
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `invalid_client` | Client not registered | Run `agent-oauth-secret` job |
| `unauthorized_client` for exchange | Token exchange not enabled | Add exchange permission on target client |
| `invalid_grant` | SVID expired | Check SPIRE agent connectivity |
| 401 on inbound A2A | JWT signature validation failed | Verify Keycloak JWKS endpoint accessible |
| No token injected outbound | AuthBridge not configured | Check ext_proc env vars and Envoy config |

### Debug AuthBridge Logs

```bash
# AuthBridge logs in the Envoy sidecar
kubectl logs -n team1 deploy/sandbox-agent -c istio-proxy | grep -i "ext_proc\|authbridge\|token"

# Keycloak token exchange logs
kubectl logs -n keycloak deploy/keycloak | grep -i "token-exchange\|exchange"
```

---

## 10. Security Best Practices {#10-security}

### Token Scoping Rules

| Rule | Rationale |
|------|-----------|
| Tokens expire in 5 minutes max | Limits blast radius if token is leaked |
| Audience is always set | Prevents token reuse across services |
| `act` claim tracks delegation chain | Audit trail: who requested, who is acting |
| Merge/delete/admin scopes never granted | Prevents destructive operations |
| Read-only is the default scope | Principle of least privilege |
| Write scopes require HITL approval | Human must approve writes |

### Defense-in-Depth: 4 Layers of Credential Protection

```
Layer 1: Agent never receives raw credentials (AuthBridge injects them)
Layer 2: Tokens are short-lived (5 min) and audience-scoped
Layer 3: Keycloak enforces exchange permissions (policy-based)
Layer 4: nono Landlock blocks filesystem access to credential files
         (~/.ssh, ~/.aws, ~/.kube always denied)
```

### Audit Trail

Every token exchange is logged:
- **Keycloak:** Logs every exchange with timestamp, client ID, audience, scope
- **AuthBridge OTEL:** Root span includes agent identity, user identity, and trace context
- **MLflow:** Traces link agent actions to user requests

---

## Related Documentation

- [Identity Guide](../identity-guide.md) — Complete SPIFFE/SPIRE/Keycloak architecture
- [Token Exchange Deep Dive](../../kagenti/examples/identity/token_exchange.md) — Detailed flow walkthrough
- [Client Registration Examples](../../kagenti/examples/identity/keycloak_token_exchange/README.md) — Working demo
- [API Authentication](../api-authentication.md) — Client credentials for programmatic access
- [Components](../components.md) — AuthBridge architecture overview
- [Sandbox Agent Research](../plans/2026-02-23-sandbox-agent-research.md) — Full sandbox architecture with C1-C20 capabilities
