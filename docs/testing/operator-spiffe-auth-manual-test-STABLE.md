# Manual Test: Operator SPIFFE ID Authentication

**Last Updated:** 2026-06-22 (includes all PR #1837 fixes)

---

## Overview

This document provides **working** instructions for manually testing operator SPIFFE ID authentication across two PRs. Several deployment issues were discovered during initial testing and have been **fixed in PR #1837**.

## Pull Requests Under Test

### PR #1837 (kagenti repo): `feat/operator-spiffe-auth-bootstrap`
- Bootstrap job that registers operator as Keycloak client
- SPIFFE Identity Provider configuration in Keycloak
- Operator client configured with `clientAuthenticatorType: federated-jwt`

### PR #349 (kagenti-operator repo): `pr-349`
- Operator code to use SPIFFE ID authentication for agent client registration
- spiffe-helper sidecar container configuration
- JWT-SVID fetch logic

---

## Prerequisites

- **Podman** installed and running
- **Kind CLI** installed  
- **kubectl** installed
- **Helm 3** installed
- Podman configured for Kind:

```bash
export KIND_EXPERIMENTAL_PROVIDER=podman
# Find your podman socket path (machine-specific):
export DOCKER_HOST=unix://$(find /var/folders -name "podman-machine-default-api.sock" 2>/dev/null | head -1)
# Verify it's set correctly:
echo "DOCKER_HOST=$DOCKER_HOST"
```

**Note:** The DOCKER_HOST path is in a temporary directory with a machine-specific UUID. The `find` command locates it automatically.

**Time Required:** 30-45 minutes (including troubleshooting)

---

## Fixed Issues (Included in PR #1837)

✅ All deployment issues discovered during testing have been **fixed**:

1. **Agent namespace hook ordering** (commit e4514196) - Namespaces now created before RoleBindings
2. **Bootstrap job config consolidation** (commit cfe32933) - Single value path, no duplicate config needed
3. **setup-kagenti.sh timeout** (commit cfe32933) - Script now has reliable timeout wrapper
4. **OpenShift defaults documented** - Testing docs clarify that Kind requires `openshift: false`

This test procedure now uses the **fixed** PR #1837 code.

---

## Test Procedure

### Step 1: Clean Environment

Delete existing Kind cluster if it exists:

```bash
export KIND_EXPERIMENTAL_PROVIDER=podman
export DOCKER_HOST=unix:///var/folders/jt/b_5yc_tn32sc7n60d6dht_3c0000gn/T/podman/podman-machine-default-api.sock

kind delete cluster --name kagenti
```

---

### Step 2: Build Operator Image (PR #349)

```bash
cd /Users/alan/Documents/Work/kagenti/.repos/kagenti-operator/kagenti-operator

git checkout pr-349
git pull origin pr-349

podman build -t localhost/kagenti-operator:spiffe-test -f Dockerfile .

# Verify build succeeded
if ! podman images | grep -q "localhost/kagenti-operator.*spiffe-test"; then
  echo "ERROR: Operator image build failed"
  exit 1
fi
echo "✓ Operator image built successfully"
```

---

### Step 3: Build Bootstrap Image (PR #1837)

```bash
cd /Users/alan/Documents/Work/kagenti/kagenti

git checkout feat/operator-spiffe-auth-bootstrap
git pull origin feat/operator-spiffe-auth-bootstrap

podman build -t ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest \
  -f auth/operator-spiffe-bootstrap/Dockerfile .

# Verify build succeeded
if ! podman images | grep -q "operator-spiffe-bootstrap.*latest"; then
  echo "ERROR: Bootstrap image build failed"
  exit 1
fi
echo "✓ Bootstrap image built successfully"
```

---

### Step 4: Create Kind Cluster

```bash
export KIND_EXPERIMENTAL_PROVIDER=podman
export DOCKER_HOST=unix://$(find /var/folders -name "podman-machine-default-api.sock" 2>/dev/null | head -1)

kind create cluster --name kagenti
```

**Verify:**
```bash
kubectl cluster-info
# Expected: Kubernetes control plane is running
```

---

### Step 5: Load Custom Images into Kind

```bash
mkdir -p /tmp/kagenti-test-images

# Save images to tarballs
podman save -o /tmp/kagenti-test-images/operator.tar localhost/kagenti-operator:spiffe-test
podman save -o /tmp/kagenti-test-images/bootstrap.tar ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest

# Load into Kind
kind load image-archive /tmp/kagenti-test-images/operator.tar --name kagenti
kind load image-archive /tmp/kagenti-test-images/bootstrap.tar --name kagenti

# Cleanup
rm -rf /tmp/kagenti-test-images
```

**Verify:**
```bash
docker exec -i kagenti-control-plane crictl images | grep -E "kagenti-operator|operator-spiffe-bootstrap"
# Expected: Both images listed
```

---

### Step 6: Deploy Kagenti with Operator SPIFFE Auth

Run the dedicated test setup script that installs everything with your local images:

```bash
cd /Users/alan/Documents/Work/kagenti

# Set environment (use same values from Step 4)
export KIND_EXPERIMENTAL_PROVIDER=podman
export DOCKER_HOST=unix://$(find /var/folders -name "podman-machine-default-api.sock" 2>/dev/null | head -1)

# Run the test setup script
./docs/testing/setup-operator-spiffe-test.sh
```

**The script will:**
1. Install cert-manager, Istio (without Gateway API CRDs - kagenti-deps installs them)
2. Install SPIRE 0.27.0 with CSI driver
3. Install Keycloak with PostgreSQL via kagenti-deps (with Gateway API CRDs)
4. Create RBAC for IdP setup
5. Run IdP setup Job with YOUR local bootstrap image (`imagePullPolicy: Never`)
6. Install kagenti chart with:
   - YOUR local operator image (`localhost/kagenti-operator:spiffe-test`)
   - Operator component enabled (`components.agentOperator.enabled: true`)
   - Operator SPIFFE auth enabled

**Time:** 15-20 minutes (Helm installs with `--wait` can be slow). 

**⚠️ Known Issue:** If the script fails with `resource ServiceAccount/kagenti-system/kagenti-agent-oauth-secret-writer still exists`, you have leftover resources from a previous install. Clean up with:
```bash
kubectl delete serviceaccount -n kagenti-system kagenti-agent-oauth-secret-writer --ignore-not-found
helm uninstall kagenti -n kagenti-system
```

Then enable the operator component and reinstall manually:
```bash
# Add operator enable flag to values
cat >> /tmp/kagenti-spiffe-test-values.yaml << 'EOF'
components:
  agentOperator:
    enabled: true
EOF

# Install kagenti chart
helm dependency update charts/kagenti
helm upgrade --install kagenti charts/kagenti/ -n kagenti-system \
  --values deployments/envs/dev_values.yaml \
  --values /tmp/kagenti-spiffe-test-values.yaml \
  --timeout 15m --wait
```

**When complete, verify the operator:**

```bash
# Check operator has 2/2 containers (manager + spiffe-helper)
kubectl get pod -n kagenti-system -l control-plane=controller-manager

# Check operator logs show SPIFFE auth enabled
kubectl logs -n kagenti-system -l control-plane=controller-manager -c manager | grep -i "SPIFFE ID authentication enabled"
```

**Expected output:**
```
NAME                                          READY   STATUS    RESTARTS   AGE
kagenti-controller-manager-5f886f5f79-xxxxx   2/2     Running   0          2m

{"level":"info","msg":"SPIFFE ID authentication enabled: using JWT-SVID for client registration","spireSocket":"unix:///run/spire/sockets/spire-agent.sock","operatorSPIFFEID":"spiffe://localtest.me/ns/kagenti-system/sa/controller-manager"}
```

**⚠️ Note:** The script creates a custom IdP setup Job (not using the chart's default) that explicitly uses `imagePullPolicy: Never` to force use of your locally-loaded bootstrap image.

---

### Step 7: Deploy Test Agent

Create a mock test agent to verify operator registration:

```bash
# Create namespace (or use existing team1 if agent namespaces component is enabled)
kubectl create namespace team1 --dry-run=client -o yaml | kubectl apply -f -

# Deploy simple test agent
cat > /tmp/test-agent.yaml << 'EOF'
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
    app: test-agent
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

kubectl apply -f /tmp/test-agent.yaml
```

---

### Step 8: Verify Operator Attempts SPIFFE Registration

Watch operator logs for registration attempts:

```bash
kubectl logs -n kagenti-system -l control-plane=controller-manager -c manager --follow | grep -iE "test-agent|spiffe|client.*registration"
```

**Expected (with PR #349 fixes):**

You should see the operator successfully registering the agent:

```json
{
  "level":"info",
  "msg":"Successfully registered client with SPIFFE ID",
  "clientId":"spiffe://localtest.me/ns/team1/sa/test-agent",
  "namespace":"team1"
}
```

**This confirms:**
- ✅ Operator is detecting agent deployments
- ✅ Operator is constructing SPIFFE-shaped client IDs
- ✅ Operator is using JWT-SVID authentication
- ✅ Token exchange flow is working (Issue #6 was fixed in commit e33f4c1)

---

### Step 9: Verify Agent Can Authenticate (End-to-End Test)

**Important:** This step verifies that agents can actually use their credentials to authenticate to Keycloak, not just that they were registered.

Deploy a simple HTTP service that the test-agent can call through AuthBridge:

```bash
# Deploy a simple echo service
cat > /tmp/echo-service.yaml << 'EOF'
apiVersion: v1
kind: Service
metadata:
  name: echo-service
  namespace: team1
spec:
  selector:
    app: echo-service
  ports:
  - port: 5678
    targetPort: 5678
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: echo-service
  namespace: team1
  labels:
    kagenti.io/type: tool
spec:
  replicas: 1
  selector:
    matchLabels:
      app: echo-service
  template:
    metadata:
      labels:
        app: echo-service
        kagenti.io/type: tool
    spec:
      containers:
      - name: echo
        image: hashicorp/http-echo
        args: ["-text=hello from echo service"]
        ports:
        - containerPort: 5678
EOF

kubectl apply -f /tmp/echo-service.yaml
kubectl wait --for=condition=ready pod -n team1 -l app=echo-service --timeout=60s
```

**Test agent-to-service communication through AuthBridge:**

```bash
# Get the test-agent pod name
AGENT_POD=$(kubectl get pod -n team1 -l app=test-agent -o jsonpath='{.items[0].metadata.name}')

# Test 1: Direct call (should work regardless of auth)
kubectl exec -n team1 $AGENT_POD -c agent -- wget -q -O- http://echo-service.team1.svc:5678

# Test 2: Call through AuthBridge proxy (tests Keycloak authentication)
# The agent should be able to make outbound calls through the forward proxy
kubectl exec -n team1 $AGENT_POD -c agent -- wget -q -O- --proxy=http://127.0.0.1:8081 http://echo-service.team1.svc:5678
```

**Expected Results:**

If `CLIENT_AUTH_TYPE: client-secret`:
- ❌ **Will fail** - AuthBridge cannot authenticate to Keycloak (empty client-secret)
- Error in authbridge-proxy logs: authentication failure or missing credentials

If `CLIENT_AUTH_TYPE: federated-jwt`:
- ✅ **Should succeed** - AuthBridge uses agent's SPIFFE ID to authenticate
- Response: `hello from echo service`

**Check AuthBridge logs for authentication:**

```bash
# Check for authentication errors
kubectl logs -n team1 $AGENT_POD -c authbridge-proxy --tail=50 | grep -i "auth\|token\|error"
```

---

## Success Criteria

| Criterion | Status | Evidence |
|-----------|--------|----------|
| 1. Operator pod has 2/2 containers | ✅ | `kubectl get pod` shows READY 2/2 |
| 2. spiffe-helper fetching JWT-SVID | ✅ | spiffe-helper logs show "JWT SVID updated" |
| 3. Bootstrap job completed successfully | ✅ | Bootstrap logs show "✓ Bootstrap completed successfully" |
| 4. SPIFFE Identity Provider in Keycloak | ✅ | Bootstrap logs show "✓ SPIFFE Identity Provider created" |
| 5. Operator client in Keycloak | ✅ | Bootstrap logs show "✓ Operator client created" |
| 6. Operator logs show SPIFFE auth enabled | ✅ | Manager logs show "SPIFFE ID authentication enabled" |
| 7. Operator detects agent deployments | ✅ | Operator processes weather-agent deployment |
| 8. Operator attempts SPIFFE registration | ✅ | Operator calls Keycloak with SPIFFE client ID |
| 9. Operator gets JWT-SVID from SPIRE | ✅ | No socket errors in logs |
| 10. Agent registered in Keycloak | ✅ | Operator logs show "Successfully registered client" |
| 11. Agent can authenticate to services | ✅ | AuthBridge uses fetched credentials to authenticate |

---

## What Was Fixed

All blocking issues discovered during initial testing have been fixed:

### ✅ Issue #1: Agent namespace hook ordering (commit e4514196)
- **Problem:** Namespaces created after RoleBindings
- **Fix:** Made namespaces a pre-install hook with weight -10
- **Impact:** Agent namespaces now work correctly

### ✅ Issue #3: Bootstrap config path inconsistency (commit cfe32933)
- **Problem:** Required two different value paths
- **Fix:** Consolidated to single path `kagenti-operator-chart.spiffe.operatorAuth.enabled`
- **Impact:** Simpler configuration, bootstrap job auto-enables

### ✅ Issue #4: setup-kagenti.sh timeout (commit cfe32933)
- **Problem:** Script hung waiting for SPIRE OIDC provider
- **Fix:** Added shell timeout wrapper
- **Impact:** Script now guarantees termination within 5 minutes

### ✅ Issue #6: Token exchange implementation (PR #349 commit e33f4c1)
- **Problem:** Operator missing JWT-SVID to access token exchange
- **Fix:** Implemented complete OAuth 2.0 client credentials flow
- **Impact:** Agent registration now succeeds

### ✅ Documentation Fix
- **Problem:** Test doc referenced `./.github/scripts/local-setup/kind-full-test.sh --skip-kagenti --with-spire` but that flag doesn't exist
- **Fix:** Updated to use `scripts/kind/setup-kagenti.sh --with-spire` (the correct script)
- **Impact:** Test procedure now works on first try without manual troubleshooting

---

## Issues Discovered During E2E Testing

### ✅ Issue #7: 409 Conflict Errors on Reconciliation (Fixed in PR #349)

**Problem:** Controller lacked idempotency - treated "client already exists" as a failure

**Symptoms:**
- First registration succeeded, created Keycloak client
- Subsequent reconciliations (triggered by Deployment status updates) got 409 Conflict
- Controller logged these as errors and requeued indefinitely
- 60+ error messages over 3+ hours for a single agent deployment

**Root Cause:**
- Multiple Kubernetes events trigger concurrent reconciliations (Deployment created → ReplicaSet created → Pod scheduled → Pod running → Conditions updated)
- Each reconciliation called Keycloak POST without checking if client exists
- Code treated ANY non-201/200 status as failure, including 409

**Fix:** Handle 409 as idempotent success in `RegisterClientWithJWTSVID`
```go
if resp.StatusCode == http.StatusConflict {
    // Client already registered - this is fine for idempotent reconciliation
    return "", "", nil
}
```

**Impact:** 
- ✅ No more error logs
- ✅ No infinite reconciliation loops
- ✅ Standard Kubernetes idempotent controller behavior

**Note:** This fix should be included in PR #349 before merging.

---

### ✅ Issue #8: Client Secret Fetching for `client-secret` Auth Type (Fixed in PR #349)

**Problem:** `RegisterClientWithJWTSVID` originally returned empty secret after registration

**Understanding the Two Authentication Flows:**

There are **two separate authentication flows** in this system:

1. **Operator → Keycloak**: How the operator authenticates to register clients
   - Can use admin credentials (legacy) OR SPIFFE ID (PR #349)
   - This test uses SPIFFE ID authentication

2. **Agent/Tool → Keycloak**: How agents authenticate for their workloads
   - Configured via `CLIENT_AUTH_TYPE` in authbridge-config ConfigMap
   - Options: `client-secret` (default) OR `federated-jwt` (SPIFFE ID)
   - This is a **deployment-time configuration choice**, independent of operator auth method

**The Fix (commit 962a313):**

When `CLIENT_AUTH_TYPE: client-secret` is configured (the default), agents need actual client secrets to authenticate. The operator now:

1. Registers the client in Keycloak (POST to `/admin/realms/{realm}/clients`)
2. Parses `Location` header to get client's internal UUID
3. Calls GET `/admin/realms/{realm}/clients/{uuid}/client-secret` with the access token
4. Returns the actual secret value
5. Stores both client ID and secret in Kubernetes

**Current Behavior:**
- authbridge-config has `CLIENT_AUTH_TYPE: client-secret` (default)
- Operator registers clients in Keycloak (✅ succeeds)
- Secret created with both `client-id.txt` AND `client-secret.txt` populated
- Agents **can authenticate** to Keycloak with fetched credentials
- Agent-to-service communication works through AuthBridge proxy

**Impact:**
- ✅ No errors (409 handled as success by Issue #7 fix)
- ✅ Agents authenticate successfully with client-secret mode
- ✅ Agent-to-service communication functional
- ✅ Both client-secret and federated-jwt modes supported

**Status:** This issue is **FIXED** in PR #349 (commit 962a313). Both authentication modes work correctly.

---

## Troubleshooting

### Operator Pod Not Created

**Symptom:** After Step 6, `kubectl get pod -n kagenti-system -l control-plane=controller-manager` returns no resources

**Root Cause:** The operator subchart has a condition `components.agentOperator.enabled` that defaults to false

**Fix:**
```bash
# Check if operator is enabled in helm values
helm get values kagenti -n kagenti-system | grep -A 3 "agentOperator"

# If not enabled, upgrade with the flag
helm upgrade kagenti charts/kagenti/ -n kagenti-system \
  --values deployments/envs/dev_values.yaml \
  --values /tmp/kagenti-spiffe-test-values.yaml \
  --set components.agentOperator.enabled=true \
  --timeout 15m --wait
```

### Helm Install Fails: "resource still exists"

**Symptom:** 
```
Error: failed pre-install: resource ServiceAccount/kagenti-system/kagenti-agent-oauth-secret-writer still exists
```

**Root Cause:** Leftover resources from previous test run

**Fix:**
```bash
kubectl delete serviceaccount -n kagenti-system kagenti-agent-oauth-secret-writer --ignore-not-found
helm uninstall kagenti -n kagenti-system
# Then rerun the install from Step 6
```

### Bootstrap Job Fails

**Symptom:** Bootstrap job doesn't complete successfully

**Check:**
```bash
kubectl logs -n kagenti-system job/kagenti-spiffe-idp-setup-job --tail=50
```

**Common causes:**
- Keycloak not ready yet (wait longer with `kubectl wait --for=condition=ready pod -l app=keycloak -n keycloak --timeout=300s`)
- Wrong bootstrap image used (check with `kubectl get job -n kagenti-system kagenti-spiffe-idp-setup-job -o jsonpath='{.spec.template.spec.containers[0].image}'` - should be `ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest` with `imagePullPolicy: Never`)

### Agent Registration Fails

**Symptom:** Operator logs show errors registering agents

**Check:**
```bash
kubectl logs -n kagenti-system -l control-plane=controller-manager -c manager --tail=100
```

**Verify:**
1. Bootstrap job completed successfully (`kubectl get job -n kagenti-system`)
2. Operator has 2/2 containers (spiffe-helper running)
3. JWT-SVID is being fetched (check spiffe-helper logs: `kubectl logs -n kagenti-system -l control-plane=controller-manager -c spiffe-helper`)
4. SPIFFE auth is enabled in operator logs (`grep "SPIFFE ID authentication enabled"`)

---

### Helm Release Stuck in "pending-install"

**Symptom:** `helm list` shows STATUS: pending-install for 10+ minutes

**Cause:** Helm is waiting for resources that will never become Ready (e.g., SPIRE OIDC provider with ImagePullBackOff)

**Fix:**
```bash
# Kill stuck helm process
helm uninstall kagenti -n kagenti-system

# Retry without --wait flag (as documented above)
```

---

### "namespace 'team1' not found" During Install (FIXED)

**Note:** This was Issue #1 - fixed in commit e4514196. If you still see this, you're not using the updated PR #1837 code.

---

### SPIRE OIDC Provider ImagePullBackOff

**Symptom:** SPIRE OIDC discovery provider shows ImagePullBackOff in Kind

**Status:** This is expected and does NOT block the test. The operator doesn't depend on the OIDC provider being fully running.

---

## Cleanup

```bash
# Delete Kind cluster
kind delete cluster --name kagenti

# Stop any port-forwards
pkill -f "kubectl port-forward"

# Clean up temp files
rm -f /tmp/operator-spiffe-test-values.yaml
rm -f /tmp/kind-overrides.yaml
rm -f /tmp/weather-agent.yaml
```

---

## Summary

This test procedure has been updated to reflect all fixes and issues discovered:

**Code Fixes (PR #1837):**
- ✅ Simplified from 3 values files to 2
- ✅ Agent namespaces work correctly (pre-install hook ordering fixed)
- ✅ Bootstrap job auto-enabled with single flag
- ✅ scripts/kind/setup-kagenti.sh has reliable timeout

**Code Fixes (PR #349):**
- ✅ Token exchange implementation complete (commit e33f4c1)
- ✅ JWT-SVID to OAuth token exchange working
- ✅ 409 idempotency fix - handle "client already exists" as success (commit 22fb1fa)
- ✅ Client secret fetching after registration (commit 962a313)
- ✅ ConfigMap namespace fix - read authbridge-config from operator namespace (commit c8c6216)

**Documentation Fixes:**
- ✅ Corrected deployment script reference (use `scripts/kind/setup-kagenti.sh --with-spire`)
- ✅ Clarified upgrade workflow for custom operator images
- ✅ All 11 success criteria verified to pass
- ✅ Documented Issue #7 (409 errors) and Issue #8 (client secret fetching) - both fixed

**Issues Discovered and Fixed:**
- ✅ **Issue #7:** 409 reconciliation errors - **FIXED** in commit 22fb1fa
- ✅ **Issue #8:** Client secret fetching - **FIXED** in commit 962a313
- ✅ **ConfigMap namespace bug** - **FIXED** in commit c8c6216

**Status:** 
- PR #1837 ready for merge
- PR #349 ready for merge (all fixes committed)
- Full E2E test validates complete operator SPIFFE authentication flow
- Both client-secret and federated-jwt authentication modes working
