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

### [kagenti/kagenti#2155](https://github.com/kagenti/kagenti/pull/2155) — Remove stale credential docs *(open)*

Removes docs describing a credential provisioning mechanism that no longer exists, and removes orphaned Helm flags from the OCP setup script. **Closes:** [#1337](https://github.com/kagenti/kagenti/issues/1337)

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

### Known issue: unused credential Secrets in `federated-jwt` mode

**Source:** `clientregistration_controller.go` — `ensureClientCredentialsSecret()` is called unconditionally regardless of `CLIENT_AUTH_TYPE`.

Keycloak generates an internal client secret for all clients regardless of auth type. In `federated-jwt` mode, the operator still fetches this secret and writes it to a Kubernetes Secret in the agent namespace, even though AuthBridge never reads it.

**Security assessment:**
- Not an immediate vulnerability — Keycloak enforces `clientAuthenticatorType: federated-jwt` and will reject `client_secret` grant attempts for that client
- Defense-in-depth gap — a Keycloak admin changing the client's auth type back to `client-secret` would make the stored secret exploitable
- Hygiene issue — unnecessary secrets accumulate in agent namespaces

**Fix required:** Skip `ensureClientCredentialsSecret()` when `CLIENT_AUTH_TYPE=federated-jwt`. Tracked in [#2174](https://github.com/kagenti/kagenti/issues/2174).

---

## Remaining Work (Issue #2174)

- [x] E2E test with both operator and agent SPIFFE auth enabled simultaneously — see Issues Found During Testing below
- [x] Verify agent SPIFFE JWT-SVID → Keycloak token exchange works (Test 6) ✅
- [ ] Skip creating credential Secrets for `federated-jwt` clients — `fix/skip-credential-secret-federated-jwt` branch in kagenti-operator (see Issue 3)
- [ ] Publish OCI chart version with spiffe-helper sidecar so `setup-kagenti.sh --enable-spiffe-auth` works end-to-end (see Issue 4)
- [ ] Merge PR #2155 (stale docs cleanup)
- [ ] Confirm spiffe-helper versioned tag publication process in kagenti-extensions (see Issue 1)

> **Deferred (requires team discussion):**
> - Making SPIFFE auth the default (`spiffe.operatorAuth.enabled: true`, `authBridge.clientAuthType: federated-jwt`)
> - Removing `kagenti-agent-oauth-secret-job` and `keycloak-admin-secret`
> - Updating install.md defaults

---

## Issues Found During Testing

Issues discovered during E2E testing on 2026-07-10 with branch `feat/spiffe-auth-e2e-test`.

### Issue 1: `spiffe-helper` image tag `v0.6.0-alpha.4` does not exist

**Status:** ✅ Fixed — updated to `v0.5.0-rc.3` on `feat/spiffe-auth` branch

**Symptom:** Operator pod stuck in `ImagePullBackOff` for the spiffe-helper container.

```
Failed to pull image "ghcr.io/kagenti/kagenti-extensions/spiffe-helper:v0.6.0-alpha.4": manifest unknown
```

**Root cause:** The tag `v0.6.0-alpha.4` exists as a GitHub release in kagenti-extensions but the corresponding container image was **never published** to ghcr.io. Not all kagenti-extensions GitHub release tags produce container images. `v0.5.0-rc.3` is the latest versioned tag confirmed to exist in the registry (same digest as `:latest`).

**Fix:** Updated `feat/spiffe-auth` operator chart to use `v0.5.0-rc.3`. Added comment warning that release tag existence does not guarantee image publication.

> **Note for future bumps:** Before updating this tag, verify the image exists: `docker pull ghcr.io/kagenti/kagenti-extensions/spiffe-helper:<tag>`

---

### Issue 2: `agent-label-protection` admission policy blocks direct `kagenti.io/type` label

**Status:** ✅ Resolved — use `AgentRuntime` CR instead

**Symptom:** Directly setting `kagenti.io/type: agent` on a Deployment is rejected:

```
ValidatingAdmissionPolicy 'agent-label-protection' with binding 'agent-label-protection' denied request:
The kagenti.io/type label on team1/test-agent can only be applied by the kagenti-operator
via an AgentRuntime CR. Create an AgentRuntime targeting this workload instead of manually setting the label.
```

**Root cause:** A new `agent-label-protection` admission policy was added to main after previous testing. It prevents external actors from spoofing the `kagenti.io/type` label to hijack the operator's client registration mechanism.

**Resolution:** Create a Deployment without the label, then create an `AgentRuntime` CR targeting it. The operator then applies the label via its reconciliation loop.

**Where `AgentRuntime` is used:** In normal Kagenti usage, the Kagenti UI creates `AgentRuntime` objects when a user deploys an agent — end users don't write this YAML manually. The `AgentRuntime` pattern appears in this test document only because manual `kubectl` testing requires it as a workaround for the admission policy. In production, the UI handles this transparently.

**Impact on test plan:** Test 1 in this document uses the `AgentRuntime` pattern instead of direct label setting. Updated in the test plan below.

---

### Issue 3: Unused credential Secret — Keycloak DOES reject client_secret grant

**Status:** ✅ Better than expected — not a security vulnerability in practice

**Finding:** When `clientAuthType=federated-jwt`, we confirmed (via testing) that Keycloak returns `HTTP 401 invalid_client` when the `client_secret` grant is attempted. Keycloak fully enforces `clientAuthenticatorType: federated-jwt` and refuses secret-based auth for that client.

**Updated security assessment:** The defense-in-depth gap concern is lower severity than documented — the secret cannot be used even if stolen, because Keycloak itself rejects it. The hygiene concern (unnecessary secrets) remains.

---

### Issue 5: `default_policy: passthrough` prevents outbound token injection via forward proxy

**Status:** ✅ By design — passthrough is correct for MCP tool calls; SPIFFE exchange tested directly

**Finding:** AuthBridge's outbound `default_policy: passthrough` means it does not inject Keycloak tokens into outbound HTTP requests by default. This is intentional — it prevents tokens from being attached to all outbound calls (e.g., MCP connections to tools that don't require authentication). Token injection is configured per-route.

The `default_policy` is managed by the operator and resets on every reconcile, so it cannot be patched manually.

**How SPIFFE outbound auth actually works:** The SPIFFE token exchange is verified by directly calling Keycloak using the agent's JWT-SVID (`/opt/jwt_svid.token` written by spiffe-helper). See Test 6 for the verified flow.

---

### Issue 4: `setup-kagenti.sh` uses OCI operator chart (missing spiffe-helper template)

**Status:** ❌ Open — blocked on OCI chart publication

**Symptom:** Running `setup-kagenti.sh --enable-spiffe-auth` installs the operator from the OCI-published chart (version 0.3.0-alpha.6) which does not contain the spiffe-helper sidecar template. The operator pod starts with only 1 container instead of 2.

**Root cause:** `setup-kagenti.sh` runs `helm install kagenti charts/kagenti/` which downloads the operator subchart from OCI. PR #473 merged the spiffe-helper chart changes to kagenti-operator, but a new chart version has not been published to the OCI registry.

**Why overriding the image is not sufficient:** The problem is not the image — it is the Helm template. The OCI chart (v0.3.0-alpha.6) has no `{{- if .Values.spiffe.operatorAuth.enabled }}` block at all. Helm values can only configure what the template exposes. Adding `--set spiffe.operatorAuth.spiffeHelper.image.tag=...` has no effect when the template code does not exist in the chart.

**Workaround used for testing:** Manually package the chart from the local kagenti-operator `feat/spiffe-auth` source and place it in `charts/kagenti/charts/` before running helm install.

**Fix required:** Publish a new tagged version of `kagenti-operator-chart` to OCI that includes the spiffe-helper sidecar, then update `charts/kagenti/Chart.yaml` to reference it.

**This blocks `setup-kagenti.sh --enable-spiffe-auth` from working end-to-end until resolved.**

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
  publicUrl: "http://keycloak.your-domain.com"   # required for audience derivation

kagenti-operator-chart:
  spiffe:
    enabled: true
    operatorAuth:
      enabled: true
      spiffeHelper:
        image:
          repository: ghcr.io/kagenti/kagenti-extensions/spiffe-helper
          tag: v0.6.0-alpha.4
      bootstrapImage: "ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest"

authBridge:
  clientAuthType: "federated-jwt"
  spiffeIdpAlias: "spire-spiffe"
```

---

## Test Plan

### Test 1: Operator registers an agent using SPIFFE auth

**Goal:** Confirm the operator authenticates to Keycloak using JWT-SVID (no admin credentials).

> **Note:** Direct `kagenti.io/type` label setting is blocked by the `agent-label-protection`
> admission policy. Use an `AgentRuntime` CR instead (see Issue 2 above).

```bash
# 1. Deploy a test agent via AgentRuntime CR
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
  # Do NOT set kagenti.io/type here — use AgentRuntime below
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

Run Tests 1–3 with `--enable-spiffe-auth`. Confirms operator registration and AuthBridge configuration both work via SPIFFE without interfering.

**Also verify the known issue (credential Secrets unused):**
```bash
# Credential Secrets still exist even in federated-jwt mode (known issue)
kubectl get secret -n team1 | grep kagenti-keycloak-client-credentials
# Confirm Keycloak rejects client_secret grant (federated-jwt enforced)
SECRET=$(kubectl get secret -n team1 -o name | grep kagenti-keycloak-client-credentials | head -1)
CLIENT_ID=$(kubectl get $SECRET -n team1 -o jsonpath='{.data.client-id\.txt}' | base64 -d)
CLIENT_SECRET=$(kubectl get $SECRET -n team1 -o jsonpath='{.data.client-secret\.txt}' | base64 -d)
kubectl run --rm -i --restart=Never check --image=curlimages/curl --namespace=kagenti-system -- \
  curl -s -w "\nHTTP:%{http_code}" -X POST \
  "http://keycloak-service.keycloak.svc:8080/realms/kagenti/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}" \
  | grep -E "HTTP:|error"
# Expected: HTTP:401 (Keycloak enforces federated-jwt, rejects client_secret)
```

---

### Test 6: Direct agent SPIFFE JWT-SVID → Keycloak token exchange

**Goal:** Prove the full SPIFFE auth chain for agent/tool workloads end-to-end.

Note: AuthBridge's outbound `default_policy: passthrough` means token injection via the forward proxy doesn't happen by default (by design — MCP tool calls don't require tokens). The SPIFFE exchange is tested directly.

```bash
# 1. Get the agent's JWT-SVID from spiffe-helper
AGENT_POD=$(kubectl get pod -n team1 -l app.kubernetes.io/name=weather-service \
  -o jsonpath='{.items[0].metadata.name}')
JWT_SVID=$(kubectl exec -n team1 $AGENT_POD -c authbridge-proxy -- cat /opt/jwt_svid.token)
CLIENT_ID=$(kubectl exec -n team1 $AGENT_POD -c authbridge-proxy -- cat /shared/client-id.txt)

echo "Client ID: $CLIENT_ID"
# Expected: spiffe://localtest.me/ns/team1/sa/weather-service

# 2. Exchange JWT-SVID for Keycloak access token using jwt-spiffe assertion type
kubectl run --rm -i --restart=Never spiffe-test --image=curlimages/curl \
  --namespace=kagenti-system \
  --env="JWT_SVID=$JWT_SVID" \
  --env="CLIENT_ID=$CLIENT_ID" -- \
  sh -c 'curl -s -w "\nHTTP:%{http_code}" -X POST \
    "http://keycloak-service.keycloak.svc:8080/realms/kagenti/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials" \
    -d "client_id=${CLIENT_ID}" \
    -d "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-spiffe" \
    -d "client_assertion=${JWT_SVID}"' | grep -E "HTTP:|access_token|error"
```

**Pass criteria:**
- `HTTP:200` with `access_token` in response
- `azp` in decoded JWT equals the agent's SPIFFE ID
- No `client_secret` used anywhere in the exchange

---

### Test 5: Restart resilience

```bash
kubectl rollout restart deployment/kagenti-controller-manager -n kagenti-system
kubectl rollout status deployment/kagenti-controller-manager -n kagenti-system
# Then repeat Test 1 — new registrations must succeed after restart
```

**Pass criteria:** New agent registrations succeed after operator restart with no manual intervention.
