# SPIFFE-Based Keycloak Authentication

**Tracks:** [#2174](https://github.com/kagenti/kagenti/issues/2174) — Remove all provisioned credentials in favor of SPIFFE-based Keycloak authentication

---

## Overview

Kagenti is evolving from provisioned, long-lived credentials (admin secrets, per-agent
OAuth2 client secrets) toward cryptographic workload identity via SPIFFE. When fully
enabled, no credential material needs to be provisioned, rotated, or synchronized —
every component authenticates to Keycloak using its SPIRE-issued JWT-SVID.

There are **two distinct authentication paths** that both need to move to SPIFFE:

| Component | What it does | Current default | SPIFFE path |
|---|---|---|---|
| **Operator** | Registers agent/tool OAuth clients in Keycloak | Admin credentials (`keycloak-admin-secret`) | JWT-SVID via `federated-jwt` client |
| **Agents/Tools** (AuthBridge) | Exchanges tokens with Keycloak on behalf of workloads | Per-agent OAuth2 client secret | JWT-SVID via `federated-jwt` client auth type |

---

## Merged PRs

### [kagenti/kagenti#1422](https://github.com/kagenti/kagenti/pull/1422) — Move Keycloak admin secret to `kagenti-system`
**Merged:** 2026-05-12 | **Status:** ✅ In production

**What it does:**
- Moved `keycloak-admin-secret` from agent namespaces (`team1`, `team2`, …) to
  `kagenti-system` (the operator's own namespace)
- Removed references to the now-sunset AuthBridge client-registration sidecar

**Why it matters:** Before this, a compromised agent namespace had access to
full Keycloak realm admin credentials. Moving them to the operator namespace
confines blast radius — agent namespace compromise no longer grants realm admin.

**Closes:** [kagenti-operator#320](https://github.com/kagenti/kagenti-operator/issues/320)

---

### [kagenti/kagenti-operator#473](https://github.com/kagenti/kagenti-operator/pull/473) — Operator SPIFFE JWT-SVID authentication
**Merged:** 2026-07-07 | **Status:** ✅ In production

**What it does:**
- Adds `JWTSVIDGrantToken()` to the Keycloak admin client — authenticates the
  operator using its SPIFFE identity via `client_assertion_type: jwt-spiffe`
- Dual auth path in `ClientRegistrationReconciler`: `UseSpiffeAuth=true` reads
  a JWT-SVID from file (written by the spiffe-helper sidecar); `UseSpiffeAuth=false`
  falls back to admin credentials
- New Helm values: `spiffe.enabled`, `spiffe.operatorAuth.enabled`,
  `spiffe.operatorAuth.jwtAudience`, `spiffe.operatorAuth.spiffeHelper.image.*`
- spiffe-helper sidecar writes the operator's JWT-SVID to `/opt/jwt_svid.token`
  (runs as UID 65532, matching the manager)
- All failures surface as Kubernetes Events; JWT-SVID is never logged

**Feature gate:** `spiffe.operatorAuth.enabled: false` (opt-in, backward compatible)

**Implements:** [kagenti-operator#410](https://github.com/kagenti/kagenti-operator/issues/410)

---

### [kagenti/kagenti#2141](https://github.com/kagenti/kagenti/pull/2141) — Operator SPIFFE bootstrap job
**Merged:** 2026-07-07 | **Status:** ✅ In production

**What it does:**
- Python bootstrap script (`kagenti/auth/operator-spiffe-bootstrap/`) that runs as
  a Helm post-install/upgrade Job and configures Keycloak for operator SPIFFE auth:
  1. Creates/verifies the SPIFFE Identity Provider (`spire-spiffe` alias)
  2. Creates the operator's Keycloak client with `clientAuthenticatorType: federated-jwt`
  3. Assigns `manage-clients` role (scoped — not full admin)
- RBAC scoped to a single named secret (`keycloak-initial-admin`) in the Keycloak
  namespace only; no cluster-wide permissions
- Also fixes: duplicate resources in `agent-namespaces.yaml` (was causing helm
  `STATUS: failed`), `authbridge-config` ConfigMap missing in `kagenti-system`

**Feature gate:** `kagenti-operator-chart.spiffe.operatorAuth.enabled: false`

**Replaces:** [kagenti/kagenti#2135](https://github.com/kagenti/kagenti/pull/2135) (clean rewrite)

---

### [kagenti/kagenti#2155](https://github.com/kagenti/kagenti/pull/2155) — Remove stale credential docs and orphaned Helm flags *(open)*
**Status:** 🔄 Open — prerequisite cleanup

**What it does:**
- Removes the stale "Keycloak Admin Credentials for Agent Namespaces" section from
  `docs/install.md` (describes a mechanism that no longer exists)
- Removes orphaned `--set keycloak.adminUsername` / `--set keycloak.adminPassword`
  flags from `scripts/ocp/setup-kagenti.sh` (these values don't exist in any chart
  template and were silently ignored on every upgrade)

**Closes:** [#1337](https://github.com/kagenti/kagenti/issues/1337)

---

## What Remains (Issue #2174)

The PRs above gate the operator side behind a feature flag. The following work
is still needed to reach the goal of zero provisioned credentials:

1. **Agent/tool SPIFFE auth** — `authBridge.clientAuthType: "federated-jwt"` already
   exists in the chart but defaults to `"client-secret"`. Making `federated-jwt` the
   default removes the need for per-agent OAuth2 client secrets entirely.

2. **Make SPIFFE auth the default** — flip `spiffe.operatorAuth.enabled: true` and
   `authBridge.clientAuthType: "federated-jwt"` in the default chart values once
   E2E validation is complete.

3. **Remove credential-provisioning Jobs** — `kagenti-agent-oauth-secret-job`,
   `keycloak-admin-secret`, and related Jobs become unnecessary once both auth paths
   are on SPIFFE.

4. **Update documentation** — `docs/install.md`, identity guide, AuthBridge docs.

---

## Enabling SPIFFE-Based Authentication

### Prerequisites

All of the following must be in place before enabling SPIFFE auth:

- SPIRE deployed with SPIFFE OIDC Discovery Provider (`--with-spire`)
- Keycloak running (`--with-backend` or full install)
- Kagenti operator deployed (`components.agentOperator.enabled: true`)

### Step 1: Enable the SPIFFE Identity Provider in Keycloak

The `spiffeIdp` Helm Job runs automatically during `helm install`/`helm upgrade`
when SPIRE is enabled. Verify it completed:

```bash
kubectl get job -n kagenti-system -l app.kubernetes.io/name=spiffe-idp-setup
kubectl logs -n kagenti-system job/spiffe-idp-setup-job
```

Expected: job completed, IdP created with alias `spire-spiffe`.

### Step 2: Bootstrap the Operator's Keycloak Client

Run the bootstrap Job by enabling it in Helm values:

```yaml
# values-spiffe.yaml
kagenti-operator-chart:
  spiffe:
    enabled: true
    operatorAuth:
      enabled: true
      jwtAudience: "http://keycloak.your-domain.com/realms/kagenti"
      spiffeHelper:
        image:
          repository: ghcr.io/kagenti/kagenti-extensions/spiffe-helper
          tag: v0.6.0-alpha.4
      bootstrapImage: "ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest"
```

```bash
helm upgrade kagenti charts/kagenti/ \
  --values deployments/envs/dev_values.yaml \
  --values values-spiffe.yaml \
  --reuse-values
```

Verify the bootstrap Job succeeded:

```bash
kubectl get job -n keycloak kagenti-operator-client-bootstrap
kubectl logs -n keycloak job/kagenti-operator-client-bootstrap
```

Expected: operator client created in Keycloak with `federated-jwt` auth type and
`manage-clients` role.

### Step 3: Verify Operator SPIFFE Auth is Active

```bash
POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager \
  -o jsonpath='{.items[0].metadata.name}')

# Operator must have 2/2 containers (manager + spiffe-helper)
kubectl get pod -n kagenti-system -l control-plane=controller-manager

# Confirm SPIFFE auth is active
kubectl logs -n kagenti-system $POD -c manager | grep "SPIFFE ID authentication enabled"
```

Expected:
```
{"msg":"SPIFFE ID authentication enabled: using JWT-SVID for client registration",
 "operatorSPIFFEID":"spiffe://localtest.me/ns/kagenti-system/sa/controller-manager"}
```

### Step 4: Enable SPIFFE Auth for Agent/Tool Workloads

Switch AuthBridge from `client-secret` to `federated-jwt` mode:

```yaml
# Add to values-spiffe.yaml
authBridge:
  clientAuthType: "federated-jwt"
  spiffeIdpAlias: "spire-spiffe"
```

```bash
helm upgrade kagenti charts/kagenti/ \
  --values deployments/envs/dev_values.yaml \
  --values values-spiffe.yaml \
  --reuse-values
```

This propagates to all agent namespaces via `authbridge-config` ConfigMaps.
New agent/tool deployments will authenticate using their SPIFFE identity.
Existing pods need to be restarted to pick up the new config.

---

## Test Plan

### Test 1: Operator SPIFFE Auth — Operator Registers an Agent

**Goal:** Verify the operator can register an agent in Keycloak using JWT-SVID
(no admin credentials).

```bash
# 1. Deploy a test agent
kubectl apply -f - <<'EOF'
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

# 2. Wait for the operator to register the agent
kubectl logs -n kagenti-system -l control-plane=controller-manager -c manager \
  --follow --since=30s | grep -E "test-agent|registration applied"

# 3. Confirm the credentials secret was created with a SPIFFE ID
SECRET=$(kubectl get secret -n team1 -o name | grep kagenti-keycloak-client-credentials)
kubectl get $SECRET -n team1 -o jsonpath='{.data.client-id\.txt}' | base64 -d
# Expected: spiffe://localtest.me/ns/team1/sa/test-agent
```

**Pass criteria:**
- Operator logs show `"operator client registration applied"` with no errors
- Credentials secret exists in `team1`
- `client-id.txt` is a SPIFFE ID (not a plain name like `team1/test-agent`)
- No `keycloak-admin-secret` needed

---

### Test 2: Agent Token Acquisition

**Goal:** Verify the agent can obtain an access token using its client credentials.

```bash
SECRET=<secret-name-from-test-1>
CLIENT_ID=$(kubectl get secret $SECRET -n team1 -o jsonpath='{.data.client-id\.txt}' | base64 -d)
CLIENT_SECRET=$(kubectl get secret $SECRET -n team1 -o jsonpath='{.data.client-secret\.txt}' | base64 -d)

kubectl run --rm -i --restart=Never token-test --image=curlimages/curl \
  --namespace=kagenti-system -- \
  curl -s -w "\nHTTP:%{http_code}" -X POST \
  "http://keycloak-service.keycloak.svc:8080/realms/kagenti/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}"
```

**Pass criteria:**
- HTTP 200
- Response contains `access_token`
- `azp` claim in decoded JWT equals `spiffe://localtest.me/ns/team1/sa/test-agent`

---

### Test 3: Agent/Tool SPIFFE Auth (federated-jwt mode)

**Goal:** Verify agents authenticate with Keycloak using their SPIFFE identity
rather than a pre-provisioned client secret, once `clientAuthType: federated-jwt`
is set.

```bash
# 1. Confirm authbridge-config has SPIRE_ENABLED=true and CLIENT_AUTH_TYPE=federated-jwt
kubectl get configmap authbridge-config -n team1 -o yaml | grep -E "SPIRE_ENABLED|CLIENT_AUTH_TYPE"

# 2. Deploy a tool (e.g. weather-tool) and watch AuthBridge logs
TOOL_POD=$(kubectl get pod -n team1 -l app.kubernetes.io/name=weather-tool \
  -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n team1 $TOOL_POD -c authbridge-proxy --follow | grep -i "spiffe\|token\|auth"

# 3. Send a request through AuthBridge and confirm token exchange succeeds
kubectl exec -n team1 $TOOL_POD -c agent -- \
  curl -s http://localhost:8000/health
```

**Pass criteria:**
- AuthBridge logs show successful SPIFFE JWT-SVID token exchange (not client-secret)
- No `keycloak-admin-secret` reference in AuthBridge logs
- Request succeeds end-to-end

---

### Test 4: No Provisioned Credentials Needed

**Goal:** Confirm the full stack works after removing the legacy credential secrets.

```bash
# Verify keycloak-admin-secret is only in kagenti-system (not agent namespaces)
kubectl get secret keycloak-admin-secret --all-namespaces

# Confirm no agent namespace has admin credentials
kubectl get secret -n team1 | grep admin
# Expected: nothing

# Confirm operator still registers new agents correctly (repeat Test 1)
```

**Pass criteria:**
- `keycloak-admin-secret` exists only in `kagenti-system`
- Agent namespaces contain only `kagenti-keycloak-client-credentials-*` secrets
  (created by the operator, not pre-provisioned)
- New agent deployments are registered without any manual credential intervention

---

### Test 5: Upgrade / Rotation Resilience

**Goal:** Verify SPIFFE-based auth survives a Keycloak restart and JWT-SVID rotation.

```bash
# 1. Restart Keycloak
kubectl rollout restart statefulset/keycloak -n keycloak
kubectl rollout status statefulset/keycloak -n keycloak

# 2. Restart the operator (forces JWT-SVID re-read)
kubectl rollout restart deployment/kagenti-controller-manager -n kagenti-system

# 3. Deploy a new test agent and verify registration still works
# (repeat Test 1)
```

**Pass criteria:**
- Operator re-authenticates after restart with no manual intervention
- New agent registrations succeed post-restart
- spiffe-helper rotates the JWT-SVID automatically (check operator logs for
  `"authenticated with JWT-SVID"` after the restart)
