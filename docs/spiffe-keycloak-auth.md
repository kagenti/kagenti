# SPIFFE-Based Keycloak Authentication

**Tracks:** [#2174](https://github.com/kagenti/kagenti/issues/2174) — Remove all provisioned credentials in favor of SPIFFE-based Keycloak authentication

---

## Overview

Kagenti is moving from provisioned, long-lived credentials (admin secrets, per-agent
OAuth2 client secrets) toward cryptographic workload identity via SPIFFE. When fully
enabled, no credential material needs to be provisioned, rotated, or synchronized —
every component authenticates to Keycloak using its SPIRE-issued JWT-SVID.

There are **two independent authentication paths** that both need to move to SPIFFE:

| Component | What it does | Current default | SPIFFE path |
|---|---|---|---|
| **Operator** | Registers agent/tool OAuth clients in Keycloak via Admin API | Admin credentials (`keycloak-admin-secret`) | JWT-SVID via `federated-jwt` client |
| **Agents/Tools** (AuthBridge) | Exchanges tokens with Keycloak on behalf of workloads | Per-agent OAuth2 `client_secret` | JWT-SVID via SPIFFE workload API |

These two paths are independent: you can enable one without the other.

---

## Background: How JWT-SVID Authentication Works with Keycloak

Understanding the audience claim is essential to configuring this correctly.

### The Keycloak realm model

"Realm" is a Keycloak concept, not an OIDC concept. A single Keycloak instance can host multiple completely isolated identity domains called realms — each with its own users, clients, keys, and configuration. In OIDC terms, each Keycloak realm IS a separate authorization server.

Every OIDC authorization server has an **issuer URL** — a stable string that uniquely identifies it. The `kagenti` realm's issuer URL is:
```
http://<keycloak-public-host>/realms/kagenti
```

This value is what Keycloak advertises in its OIDC discovery document:
```bash
curl http://keycloak.localtest.me:8080/realms/kagenti/.well-known/openid-configuration | jq .issuer
# "http://keycloak.localtest.me:8080/realms/kagenti"
```

### The JWT audience claim

A JWT has an `aud` (audience) claim that identifies the intended recipient. It is a security mechanism — the recipient checks that it is named in `aud` and rejects tokens where it isn't, preventing a token minted for one service from being replayed against another.

In the `federated-jwt` flow, the operator (or an agent) presents a JWT-SVID to Keycloak's token endpoint as a **client assertion** (RFC 7523). The JWT-SVID's `aud` claim must equal Keycloak's realm issuer URL. This tells Keycloak: "this token was minted for you specifically."

Note that SPIRE, not Keycloak, issues the JWT-SVID. Keycloak is the *recipient* (audience), not the issuer. The `iss` (issuer) claim in the JWT-SVID identifies SPIRE.

**Why the realm URL and not just the Keycloak base URL?** A token minted for `realms/kagenti` must not be accepted by `realms/master`. Using the realm-specific URL prevents cross-realm token reuse.

**Why the PUBLIC/EXTERNAL Keycloak URL?** The `aud` check is a **string equality** comparison — not a network connection. Keycloak compares the `aud` claim against its own issuer string, which it derives from its external configuration (`keycloak.publicUrl`). Even from inside the cluster, the audience must use the public URL:

```
Correct:   http://keycloak.localtest.me:8080/realms/kagenti   (matches .well-known issuer)
Wrong:     http://keycloak-service.keycloak.svc:8080/realms/kagenti  (string mismatch → rejected)
```

The audience is always `keycloak.publicUrl/realms/<realm>` and is derived automatically from those Helm values. No separate audience configuration is needed.

---

## Merged PRs

### [kagenti/kagenti#1422](https://github.com/kagenti/kagenti/pull/1422) — Move Keycloak admin secret to `kagenti-system`
**Merged:** 2026-05-12

Moved `keycloak-admin-secret` from agent namespaces to the operator's own namespace (`kagenti-system`). Before this, a compromised agent namespace had full Keycloak realm admin access. **Closes:** [kagenti-operator#320](https://github.com/kagenti/kagenti-operator/issues/320)

---

### [kagenti/kagenti-operator#473](https://github.com/kagenti/kagenti-operator/pull/473) — Operator SPIFFE JWT-SVID authentication
**Merged:** 2026-07-07

Adds SPIFFE-based authentication for the **operator → Keycloak Admin API** path:
- spiffe-helper sidecar runs in the operator pod and writes the operator's JWT-SVID to `/opt/jwt_svid.token`
- Operator reads the file and uses it as a RFC 7523 client assertion to obtain an access token from Keycloak
- Keycloak client is registered with `clientAuthenticatorType: federated-jwt` and `manage-clients` role only (not full admin)

Helm values: `spiffe.enabled` (SPIRE is present) + `spiffe.operatorAuth.enabled` (use SPIFFE for Keycloak registration). Both default to `false`.

---

### [kagenti/kagenti#2141](https://github.com/kagenti/kagenti/pull/2141) — Operator SPIFFE bootstrap job
**Merged:** 2026-07-07

Helm post-install/upgrade Job that configures Keycloak for operator SPIFFE auth:
1. Creates the SPIFFE Identity Provider (`spire-spiffe` alias)
2. Creates the operator's Keycloak client with `clientAuthenticatorType: federated-jwt`
3. Assigns `manage-clients` role

Gated by: `kagenti-operator-chart.spiffe.operatorAuth.enabled: false`

---

### [kagenti-operator#476](https://github.com/kagenti/kagenti-operator/pull/476) — SPIFFE auth follow-up fixes
**Merged:** 2026-07-13 | **Included in:** `kagenti-operator-chart:0.3.0-alpha.7`

- Remove `jwtAudience` Helm value — audience is always derived from `keycloak.publicUrl/realms/<realm>`, no separate field needed
- Skip credential Secret creation in `federated-jwt` mode — AuthBridge uses JWT-SVIDs directly, the Secret was unnecessary
- Skip pod template annotation in `federated-jwt` mode — the annotation caused pods to wait for a Secret that no longer exists
- Fix webhook to skip credential annotation pre-population in `federated-jwt` mode

### [kagenti-operator#479](https://github.com/kagenti/kagenti-operator/pull/479) — Remove legacy client-registration sidecar label
**Merged:** 2026-07-14 | **Included in:** `kagenti-operator-chart:0.3.0-alpha.7`

Removes `kagenti.io/client-registration-inject=true` opt-in label. The in-pod sidecar was removed in #1422; this cleans up the last references. **Closes:** [#1913](https://github.com/kagenti/kagenti/issues/1913)

### [kagenti/kagenti#2155](https://github.com/kagenti/kagenti/pull/2155) — Remove stale credential docs *(open)*

Removes docs describing a credential provisioning mechanism that no longer exists. **Closes:** [#1337](https://github.com/kagenti/kagenti/issues/1337)

---

## How Agent/Tool Authentication Works (Source Code Findings)

### What the operator does per agent at registration time

When the operator's `ClientRegistrationReconciler` detects a new agent/tool Deployment, it:

1. Reads `CLIENT_AUTH_TYPE` from the `authbridge-config` ConfigMap in the agent namespace
2. Calls Keycloak Admin API to register an OAuth client for the workload
3. Sets `clientAuthenticatorType` to either `client-secret` or `federated-jwt` based on `CLIENT_AUTH_TYPE`
4. For `federated-jwt`: also sets `jwt.credential.issuer` (SPIFFE IdP alias) and `jwt.credential.sub` (workload SPIFFE ID) attributes on the Keycloak client
5. Fetches the Keycloak-generated client secret and writes a Kubernetes Secret to the agent namespace

### What AuthBridge does per agent

In `client-secret` mode: AuthBridge reads `client-id.txt` and `client-secret.txt` from the credential Secret mounted in the pod.

In `federated-jwt` mode: AuthBridge uses `identity.type: spiffe` — it reads a JWT-SVID from the SPIFFE workload API socket directly and uses it for token exchange with Keycloak. **The credential Secret is not read.**

### Credential Secrets in `federated-jwt` mode

**Fixed in:** kagenti-operator#476 (included in `0.3.0-alpha.7`)

In `federated-jwt` mode the operator now:
- Does **not** create a credential Secret (no `ensureClientCredentialsSecret()`)
- Does **not** annotate the pod template with the Secret name (no `patchTemplate()`)
- The webhook also skips pre-populating the credential annotation

AuthBridge reads JWT-SVIDs directly from the SPIFFE workload API socket — no credential Secret is needed or created.

---

## Remaining Work (Issue #2174)

- [x] Skip credential Secrets for `federated-jwt` clients — fixed in kagenti-operator#476, included in `0.3.0-alpha.7`
- [x] E2E test with both paths enabled simultaneously — completed, all tests pass
- [ ] Merge PR #2188 (kagenti) — `--enable-spiffe-auth` flag + chart bump to `0.3.0-alpha.7`
- [ ] Merge PR #2155 (stale docs cleanup)
- [ ] Open follow-up issue / PR for kagenti-operator#478 — replace spiffe-helper sidecar with direct go-spiffe SDK call (removes dependency on unmaintained standalone image)

> **Deferred (requires team discussion):**
> - Making SPIFFE auth the default
> - Removing `kagenti-agent-oauth-secret-job` and `keycloak-admin-secret`

---

## Enabling SPIFFE Authentication

### Prerequisites

- SPIRE deployed (`--with-spire`)
- Keycloak running
- `keycloak.publicUrl` set to the external Keycloak URL (e.g. `http://keycloak.localtest.me:8080`)
- Kagenti operator deployed (`components.agentOperator.enabled: true`)

### Using setup-kagenti.sh

```bash
# Operator SPIFFE auth only
# (operator → Keycloak uses JWT-SVID; agents still use client secrets)
scripts/kind/setup-kagenti.sh --with-spire --enable-operator-spiffe-auth

# Agent/tool SPIFFE auth only
# (AuthBridge uses JWT-SVID; operator still uses admin credentials)
scripts/kind/setup-kagenti.sh --with-spire --enable-agent-spiffe-auth

# Both — eliminates all provisioned credentials
scripts/kind/setup-kagenti.sh --with-spire --enable-spiffe-auth
```

Both `--enable-operator-spiffe-auth` and `--enable-agent-spiffe-auth` require `--with-spire` and will fail immediately with a clear error if SPIRE is not enabled.

### Manual Helm values

```yaml
keycloak:
  publicUrl: "http://keycloak.your-domain.com"   # required — used for JWT audience derivation

kagenti-operator-chart:
  spiffe:
    enabled: true
    operatorAuth:
      enabled: true
      # spiffeHelper.image and jwtAudience are not needed — defaults are correct in 0.3.0-alpha.7
      bootstrapImage: "ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest"

authBridge:
  clientAuthType: "federated-jwt"
  spiffeIdpAlias: "spire-spiffe"
```

> **Note:** `kagenti-operator-chart:0.3.0-alpha.7` (released 2026-07-14) is required. Earlier versions do not have the spiffe-helper sidecar template or the `federated-jwt` credential fixes.

---

## Test Plan

### Test 1: Operator registers an agent using SPIFFE auth

**Goal:** Confirm the operator authenticates to Keycloak using JWT-SVID (no admin credentials).

```bash
# 1. Deploy a test agent
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
  labels:
    kagenti.io/type: agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: test-agent
  template:
    metadata:
      labels:
        app: test-agent
        kagenti.io/type: agent
    spec:
      serviceAccountName: test-agent
      containers:
      - name: agent
        image: busybox
        command: ["sleep", "3600"]
EOF

# 2. Confirm SPIFFE auth is active
POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager \
  -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n kagenti-system $POD -c manager | grep "SPIFFE ID authentication enabled"
# Expected: {"msg":"SPIFFE ID authentication enabled: using JWT-SVID for client registration",...}

# 3. Confirm registration succeeded
kubectl get secret -n team1 | grep kagenti-keycloak-client-credentials
kubectl get secret kagenti-keycloak-client-credentials-* -n team1 \
  -o jsonpath='{.data.client-id\.txt}' | base64 -d
# Expected: spiffe://localtest.me/ns/team1/sa/test-agent
```

**Pass criteria:** SPIFFE auth log message present; client ID is a SPIFFE ID; no `keycloak-admin-secret` referenced in operator logs.

---

### Test 2: Agent obtains a token using client credentials

```bash
SECRET=$(kubectl get secret -n team1 -o name | grep kagenti-keycloak-client-credentials | head -1)
CLIENT_ID=$(kubectl get $SECRET -n team1 -o jsonpath='{.data.client-id\.txt}' | base64 -d)
CLIENT_SECRET=$(kubectl get $SECRET -n team1 -o jsonpath='{.data.client-secret\.txt}' | base64 -d)

kubectl run --rm -i --restart=Never token-test --image=curlimages/curl \
  --namespace=kagenti-system -- \
  curl -s -w "\nHTTP:%{http_code}" -X POST \
  "http://keycloak-service.keycloak.svc:8080/realms/kagenti/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}"
```

**Pass criteria:** HTTP 200; `access_token` present; `azp` in decoded JWT equals the SPIFFE ID.

---

### Test 3: Agent/tool uses SPIFFE identity through AuthBridge (`federated-jwt` mode)

**Goal:** Confirm AuthBridge uses JWT-SVID, not the credential Secret.

```bash
# 1. Confirm authbridge-config has the right auth type
kubectl get configmap authbridge-config -n team1 \
  -o jsonpath='{.data.CLIENT_AUTH_TYPE}'
# Expected: federated-jwt

# 2. Confirm authbridge-runtime-config uses spiffe identity type
kubectl get configmap authbridge-runtime-config -n kagenti-system -o yaml \
  | grep -A 2 "identity:"
# Expected: type: spiffe

# 3. Confirm a request through AuthBridge succeeds
TOOL_POD=$(kubectl get pod -n team1 -l app.kubernetes.io/name=weather-tool \
  -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n team1 $TOOL_POD -c agent -- curl -s http://localhost:8000/health
```

**Pass criteria:** Auth type is `federated-jwt`; identity type is `spiffe`; requests succeed.

---

### Test 4: Combined — both paths use SPIFFE simultaneously

Run Tests 1–3 with `--enable-spiffe-auth`. Confirms operator registration and AuthBridge token exchange both work via SPIFFE without interfering.

**Also check the known issue:**
```bash
# Credential Secrets still exist even in federated-jwt mode (known issue)
kubectl get secret -n team1 | grep kagenti-keycloak-client-credentials
# These exist but AuthBridge does not use them in federated-jwt mode
```

---

### Test 5: Restart resilience

```bash
kubectl rollout restart deployment/kagenti-controller-manager -n kagenti-system
kubectl rollout status deployment/kagenti-controller-manager -n kagenti-system
# Then repeat Test 1 — new registrations must succeed after restart
```

**Pass criteria:** New agent registrations succeed after operator restart with no manual intervention.
