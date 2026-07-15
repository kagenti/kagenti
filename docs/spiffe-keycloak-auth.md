# SPIFFE-Based Keycloak Authentication

**Tracks:** [#2174](https://github.com/kagenti/kagenti/issues/2174) — Remove all provisioned credentials in favor of SPIFFE-based Keycloak authentication

---

## Overview

Kagenti is moving from provisioned, long-lived credentials (admin secrets, per-agent OAuth2 client secrets) toward cryptographic workload identity via SPIFFE. When fully enabled, no credential material needs to be provisioned, rotated, or synchronized — every component authenticates to Keycloak using its SPIRE-issued JWT-SVID.

There are **two independent authentication paths**:

| Component | Current default | SPIFFE path |
|---|---|---|
| **Operator** | Admin credentials (`keycloak-admin-secret`) | JWT-SVID via `federated-jwt` Keycloak client |
| **Agents/Tools** (AuthBridge) | Per-agent OAuth2 `client_secret` | JWT-SVID via SPIFFE workload API |

Both are gated off by default and can be enabled independently.

---

## Background: How JWT-SVID Authentication Works with Keycloak

### Keycloak realms

"Realm" is a Keycloak concept, not an OIDC concept. Each realm is an independent OIDC authorization server with its own issuer URL:

```
http://<keycloak-public-host>/realms/kagenti
```

### The JWT audience claim

When the operator or an agent presents a JWT-SVID to Keycloak's token endpoint as a client assertion (RFC 7523), the JWT's `aud` claim must equal the realm's issuer URL. This is a **string equality check, not a network connection** — Keycloak compares the `aud` claim against its own configured issuer string.

**Why the public/external URL:** Keycloak's issuer is always the external URL it was configured with (`keycloak.publicUrl`). Using the in-cluster service address (`keycloak-service.keycloak.svc`) causes a silent string mismatch.

The audience is always `keycloak.publicUrl/realms/<realm>` and is derived automatically — no separate configuration needed.

---

## Merged PRs

### [kagenti/kagenti#1422](https://github.com/kagenti/kagenti/pull/1422) — Move Keycloak admin secret to `kagenti-system`
**Merged:** 2026-05-12

Moved `keycloak-admin-secret` from agent namespaces to the operator namespace. Before this, a compromised agent namespace had full Keycloak realm admin access. Closes [kagenti-operator#320](https://github.com/kagenti/kagenti-operator/issues/320).

---

### [kagenti-operator#473](https://github.com/kagenti/kagenti-operator/pull/473) — Operator SPIFFE JWT-SVID authentication
**Merged:** 2026-07-07 | **In:** `kagenti-operator-chart:0.3.0-alpha.7`

Adds SPIFFE-based authentication for the operator → Keycloak Admin API path. When enabled, a spiffe-helper sidecar writes the operator's JWT-SVID to `/opt/jwt_svid.token`; the operator reads it and uses it as a RFC 7523 client assertion. Operator Keycloak client uses `manage-clients` role only (not full admin).

---

### [kagenti/kagenti#2141](https://github.com/kagenti/kagenti/pull/2141) — Operator SPIFFE bootstrap job
**Merged:** 2026-07-07

Helm post-install/upgrade Job that configures Keycloak for operator SPIFFE auth:
1. Creates the SPIFFE Identity Provider (`spire-spiffe` alias)
2. Creates the operator's Keycloak client with `clientAuthenticatorType: federated-jwt`
3. Assigns `manage-clients` role

---

### [kagenti-operator#476](https://github.com/kagenti/kagenti-operator/pull/476) — SPIFFE auth follow-up fixes
**Merged:** 2026-07-13 | **In:** `kagenti-operator-chart:0.3.0-alpha.7`

- Remove `jwtAudience` Helm value — audience always derived from `keycloak.publicUrl/realms/<realm>`
- Skip credential Secret creation in `federated-jwt` mode — AuthBridge uses JWT-SVIDs directly, no Secret needed
- Skip pod template annotation in `federated-jwt` mode — was causing pods to wait for a Secret that doesn't exist
- Fix webhook to skip credential annotation pre-population in `federated-jwt` mode

---

### [kagenti-operator#479](https://github.com/kagenti/kagenti-operator/pull/479) — Remove legacy client-registration sidecar label
**Merged:** 2026-07-14 | **In:** `kagenti-operator-chart:0.3.0-alpha.7`

Removes `kagenti.io/client-registration-inject=true` opt-in label. The in-pod sidecar was removed in #1422; this cleans up the last code references. Closes [#1913](https://github.com/kagenti/kagenti/issues/1913).

---

### [kagenti/kagenti#2188](https://github.com/kagenti/kagenti/pull/2188) — `--enable-spiffe-auth` flag *(open)*

Adds `--enable-spiffe-auth`, `--enable-operator-spiffe-auth`, and `--enable-agent-spiffe-auth` flags to `setup-kagenti.sh`. Also bumps `kagenti-operator-chart` to `0.3.0-alpha.7`.

---

### [kagenti/kagenti#2155](https://github.com/kagenti/kagenti/pull/2155) — Remove stale credential docs *(open)*

Removes docs describing a credential provisioning mechanism that no longer exists. Closes [#1337](https://github.com/kagenti/kagenti/issues/1337).

---

## How Operator SPIFFE Auth Works (End-to-End)

This flow runs **once at install time** to configure Keycloak, then **on every reconcile** when the operator needs to register agent clients.

### Step 1: Bootstrap Job (install/upgrade)

When `spiffe.operatorAuth.enabled=true`, a Helm post-install/upgrade Job runs automatically. The job (`operator-client-bootstrap`) uses admin credentials **one time** to configure Keycloak so the operator can authenticate without them afterwards:

1. Creates a SPIFFE Identity Provider in Keycloak pointing at SPIRE's OIDC Discovery Provider (so Keycloak can validate JWT-SVIDs)
2. Creates a Keycloak client for the operator with `clientAuthenticatorType: federated-jwt` and the operator's SPIFFE ID as the subject (`spiffe://localtest.me/ns/kagenti-system/sa/controller-manager`)
3. Assigns the `manage-clients` role to that client (scoped — not full admin)

After this job completes, the admin credentials are no longer needed for operator authentication.

### Step 2: Operator authenticates to Keycloak (every reconcile)

When the operator needs to register a new agent client:

1. The **spiffe-helper sidecar** in the operator pod continuously fetches the operator's JWT-SVID from the SPIRE workload API socket and writes it to `/opt/jwt_svid.token`
2. The operator reads the JWT-SVID from that file
3. The operator sends a `client_credentials` grant to Keycloak with the JWT-SVID as a `client_assertion` (assertion type: `jwt-spiffe`)
4. Keycloak validates the JWT-SVID signature against SPIRE's JWKS, confirms the `aud` claim matches the realm issuer URL, and returns an access token
5. The operator uses that access token to call the Keycloak Admin API

```
Operator pod
├─ spiffe-helper sidecar ──→ SPIRE workload API socket
│   writes JWT-SVID to /opt/jwt_svid.token (auto-rotates)
└─ manager binary
    reads JWT-SVID
    POST /realms/kagenti/protocol/openid-connect/token
      client_assertion_type: jwt-spiffe
      client_assertion: <JWT-SVID>
    ──→ Keycloak validates via SPIFFE IdP JWKS
    ←── access token (manage-clients scope)
    uses token to call Admin API
```

---

## How Agent/Tool SPIFFE Auth Works (End-to-End)

### Step 1: Operator registers each agent (per-workload)

When the operator detects a new agent/tool Deployment with `CLIENT_AUTH_TYPE=federated-jwt`:

1. Calls Keycloak Admin API (using its own JWT-SVID token from above)
2. Creates a Keycloak client for the workload with `clientAuthenticatorType: federated-jwt`
3. Sets `jwt.credential.sub` to the workload's SPIFFE ID (e.g. `spiffe://localtest.me/ns/team1/sa/weather-service`)
4. **Does not** create a Kubernetes credential Secret — AuthBridge doesn't need one

### Step 2: AuthBridge exchanges tokens for each outbound request

When an agent makes an outbound call that requires authentication:

1. The **authbridge-proxy sidecar** in the agent pod fetches the workload's JWT-SVID from the SPIRE workload API socket (using the go-spiffe SDK — no separate binary needed)
2. Sends a `client_credentials` grant to Keycloak with the JWT-SVID as a `client_assertion`
3. Keycloak validates and returns an access token scoped to that workload's SPIFFE identity
4. AuthBridge attaches the access token to the outbound request

```
Agent pod
└─ authbridge-proxy sidecar
    fetches JWT-SVID from SPIRE workload API socket (go-spiffe SDK)
    POST /realms/kagenti/protocol/openid-connect/token
      client_assertion_type: jwt-spiffe
      client_assertion: <workload JWT-SVID>
    ──→ Keycloak validates; returns access token
    attaches token to outbound requests
```

---

## How Agent/Tool Registration Works (Source Code Detail)

When the operator detects a new agent/tool Deployment:

1. Reads `CLIENT_AUTH_TYPE` from the `authbridge-config` ConfigMap in the agent namespace
2. Calls Keycloak Admin API to register an OAuth client
3. In `federated-jwt` mode: sets `clientAuthenticatorType: federated-jwt` and sets `jwt.credential.issuer` + `jwt.credential.sub` attributes on the Keycloak client
4. In `federated-jwt` mode: **does not** create a credential Secret (fixed in #476)
5. In `client-secret` mode: creates a `kagenti-keycloak-client-credentials-*` Secret with the client credentials

### What AuthBridge does per agent

In `client-secret` mode: AuthBridge reads credential files from the mounted Secret.

In `federated-jwt` mode: AuthBridge uses `identity.type: spiffe` — reads a JWT-SVID from the SPIFFE workload API socket directly. No credential Secret is mounted or read.

---

## Remaining Work (Issue #2174)

- [x] Skip credential Secrets for `federated-jwt` clients — fixed in #476, in `0.3.0-alpha.7`
- [x] E2E test with both paths enabled simultaneously — **all tests pass** (see below)
- [ ] Merge PR #2188 (kagenti) — `--enable-spiffe-auth` flag + chart bump to `0.3.0-alpha.7`
- [ ] Merge PR #2155 (stale docs cleanup)
- [ ] PR [kagenti-operator#478](https://github.com/kagenti/kagenti-operator/pull/478) — replace spiffe-helper sidecar with direct go-spiffe SDK call (removes dependency on standalone image that is no longer actively maintained)

> **Deferred (requires team discussion):**
> Making SPIFFE auth the default; removing `kagenti-agent-oauth-secret-job` and `keycloak-admin-secret`

---

## Enabling SPIFFE Authentication

### Requirements

- `kagenti-operator-chart:0.3.0-alpha.7` or later (released 2026-07-14)
- SPIRE deployed (`--with-spire`)
- `keycloak.publicUrl` set (e.g. `http://keycloak.localtest.me:8080`)

### Using setup-kagenti.sh (on PR #2188 branch)

```bash
# Operator SPIFFE auth only
scripts/kind/setup-kagenti.sh --with-spire --enable-operator-spiffe-auth

# Agent/tool SPIFFE auth only
scripts/kind/setup-kagenti.sh --with-spire --enable-agent-spiffe-auth

# Both — no provisioned credentials needed
scripts/kind/setup-kagenti.sh --with-spire --enable-spiffe-auth
```

Both SPIFFE auth flags require `--with-spire` and fail immediately with a clear error if SPIRE is not enabled.

### Manual Helm values

```yaml
keycloak:
  publicUrl: "http://keycloak.your-domain.com"   # required

kagenti-operator-chart:
  spiffe:
    enabled: true
    operatorAuth:
      enabled: true
      bootstrapImage: "ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest"
      # No jwtAudience needed — derived from keycloak.publicUrl automatically

authBridge:
  clientAuthType: "federated-jwt"
  spiffeIdpAlias: "spire-spiffe"

spire:
  enabled: true   # required when authBridge.clientAuthType=federated-jwt
```

---

## E2E Test Results (2026-07-14, `kagenti-operator-chart:0.3.0-alpha.7`)

Full test on a fresh Kind cluster using only published artifacts (no custom operator build).

| Test | Result |
|---|---|
| Operator pod 2/2 (manager + spiffe-helper sidecar) | ✅ |
| `SPIFFE ID authentication enabled` in operator logs | ✅ |
| Helm `STATUS: deployed` | ✅ |
| Agent `CLIENT_AUTH_TYPE: federated-jwt` | ✅ |
| No credential Secrets created for agents (PR #476 fix) | ✅ |
| Agent pods 2/2 with no Init issues (webhook fix) | ✅ |
| Bootstrap job registered operator with SPIFFE client | ✅ |
| Agent JWT-SVID → Keycloak token: HTTP 200 | ✅ |

**Issues found during testing:**

| Issue | Status |
|---|---|
| `values.yaml` image tag not bumped alongside `Chart.yaml` (both need updating) | Fixed in PR #2188 |
| `spiffe.enabled` missing from `--enable-operator-spiffe-auth` flag (chart requires both `spiffe.enabled` and `spiffe.operatorAuth.enabled`) | Fixed in PR #2188 |
| `keycloak.publicUrl` not passed to operator subchart (subcharts don't inherit parent values) | Fixed in PR #2188 |
| `spire.enabled` not set explicitly (relied on chart default) | Fixed in PR #2188 |

---

## Test Plan

### Test 1: Operator registers an agent using SPIFFE auth

```bash
# Deploy via AgentRuntime (agent-label-protection policy requires this)
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: ServiceAccount
metadata:
  name: test-agent
  namespace: team1
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-agent
  namespace: team1
spec:
  replicas: 1
  selector:
    matchLabels:
      app: test-agent
  template:
    metadata:
      labels:
        app: test-agent
    spec:
      serviceAccountName: test-agent
      containers:
      - name: agent
        image: busybox
        command: ["sleep", "3600"]
---
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: test-agent
  namespace: team1
spec:
  type: agent
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: test-agent
EOF

# Verify SPIFFE auth message
POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager \
  -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n kagenti-system $POD -c manager | grep "SPIFFE ID authentication enabled"

# Verify no credential Secret was created
kubectl get secret -n team1 | grep kagenti-keycloak-client-credentials
# Expected: nothing (federated-jwt mode skips Secret creation)
```

**Pass:** SPIFFE auth log message present; no credential Secrets in team1.

---

### Test 2: Agent JWT-SVID → Keycloak token exchange

```bash
AGENT_POD=$(kubectl get pod -n team1 -l app.kubernetes.io/name=weather-service \
  -o jsonpath='{.items[0].metadata.name}')
JWT_SVID=$(kubectl exec -n team1 $AGENT_POD -c authbridge-proxy -- cat /opt/jwt_svid.token)
CLIENT_ID="spiffe://localtest.me/ns/team1/sa/weather-service"

kubectl run --rm -i --restart=Never spiffe-test --image=curlimages/curl \
  --namespace=kagenti-system \
  --env="JWT=$JWT_SVID" --env="CID=$CLIENT_ID" -- \
  sh -c 'curl -s -w "\nHTTP:%{http_code}" -X POST \
    "http://keycloak-service.keycloak.svc:8080/realms/kagenti/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials&client_id=${CID}&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-spiffe&client_assertion=${JWT}"' \
  | grep -E "HTTP:|access_token|error"
```

**Pass:** HTTP 200 with `access_token`; `azp` in decoded JWT equals the agent's SPIFFE ID.

---

### Test 3: No provisioned credentials needed

```bash
# keycloak-admin-secret exists only in kagenti-system
kubectl get secret keycloak-admin-secret --all-namespaces
# Expected: only kagenti-system

# No credential Secrets in agent namespaces
kubectl get secret -n team1 | grep keycloak-client-credentials
# Expected: nothing (in federated-jwt mode)
```
