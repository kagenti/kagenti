# Manual Test: Operator SPIFFE ID Authentication

## Overview

This document provides comprehensive instructions for manually testing operator SPIFFE ID authentication across two PRs. This test must be performed from a clean Kind cluster with no workarounds or manual fixes required.

## Pull Requests Under Test

### PR #1837 (kagenti repo): `feat/operator-spiffe-auth-bootstrap`
**What it adds**: 
- Bootstrap job that registers the operator as a Keycloak client using SPIFFE ID authentication
- SPIFFE Identity Provider configuration in Keycloak
- Operator client configured with `clientAuthenticatorType: federated-jwt`
- **Authentication method**: SPIFFE ID auth (NOT DCR - DCR mentions in commits were reverted)

### PR #349 (kagenti-operator repo): `pr-349`
**What it adds**:
- Operator code changes to use SPIFFE ID authentication when registering agent clients
- spiffe-helper sidecar container configuration
- JWT-SVID fetch logic for Keycloak Admin API authentication
- **Authentication method**: SPIFFE ID auth (NOT DCR - DCR mentions in commits were reverted)

## Prerequisites

- Podman installed and running
- Kind CLI installed  
- kubectl installed
- Podman configured for Kind:
```bash
export KIND_EXPERIMENTAL_PROVIDER=podman
export DOCKER_HOST=unix:///var/folders/jt/b_5yc_tn32sc7n60d6dht_3c0000gn/T/podman/podman-machine-default-api.sock
```

## Test Procedure

### Step 1: Clean Environment

Delete existing Kind cluster:

```bash
kind delete cluster --name kagenti
```

---

### Step 2: Build Operator Image (PR #349)

Build the operator from the `pr-349` branch:

```bash
cd /Users/alan/Documents/Work/kagenti/.repos/kagenti-operator/kagenti-operator

# Ensure on correct branch
git checkout pr-349
git pull origin pr-349

# Build image
podman build -t localhost/kagenti-operator:spiffe-test -f Dockerfile .
```

**Expected**: Image `localhost/kagenti-operator:spiffe-test` built successfully.

**Verify**:
```bash
podman images | grep kagenti-operator
# Should show: localhost/kagenti-operator  spiffe-test
```

---

### Step 3: Build Bootstrap Image (PR #1837)

Build the operator bootstrap image from the `feat/operator-spiffe-auth-bootstrap` branch.

**Note**: PR #1837 only adds the bootstrap image. Other Kagenti images (backend, agent-oauth-secret, etc.) are unchanged and will be pulled from ghcr.io during deployment.

```bash
cd /Users/alan/Documents/Work/kagenti/kagenti

# Ensure on correct branch
git checkout feat/operator-spiffe-auth-bootstrap
git pull origin feat/operator-spiffe-auth-bootstrap

# Build bootstrap image (this is the ONLY new image in PR #1837)
podman build -t ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest \
  -f auth/operator-spiffe-bootstrap/Dockerfile .
```

**Expected**: Bootstrap image built successfully.

**Verify**:
```bash
podman images | grep operator-spiffe-bootstrap
# Should show: ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap  latest
```

---

### Step 4: Load Images into Kind

Export the two PR images from Podman and load into Kind cluster. Other images will be pulled from ghcr.io automatically during deployment.

```bash
mkdir -p /tmp/kagenti-test-images

# Load operator image (from PR #349)
podman save -o /tmp/kagenti-test-images/operator.tar localhost/kagenti-operator:spiffe-test
kind load image-archive /tmp/kagenti-test-images/operator.tar --name kagenti

# Load bootstrap image (from PR #1837)
podman save -o /tmp/kagenti-test-images/bootstrap.tar ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest
kind load image-archive /tmp/kagenti-test-images/bootstrap.tar --name kagenti

# Cleanup
rm -rf /tmp/kagenti-test-images
```

**Expected**: Both PR images loaded into Kind. Other Kagenti images (backend, agent-oauth-secret, etc.) will be pulled from ghcr.io during deployment.

**Verify**:
```bash
docker exec -i kagenti-control-plane crictl images | grep -E "kagenti-operator|operator-spiffe-bootstrap"
# Should show both images
```

---

### Step 5: Create Helm Values Override

Create values file to use local operator image and enable SPIFFE auth:

```bash
cat > /tmp/operator-spiffe-test-values.yaml << 'EOF'
kagenti-operator-chart:
  controllerManager:
    container:
      image:
        repository: localhost/kagenti-operator
        tag: spiffe-test
  spiffe:
    enabled: true
    operatorAuth:
      enabled: true
      spiffeHelper:
        jwtAudience: "http://keycloak.localtest.me:8080/realms/kagenti"
EOF
```

**Expected**: Values file created at `/tmp/operator-spiffe-test-values.yaml`.

**Verify**:
```bash
cat /tmp/operator-spiffe-test-values.yaml
```

---

### Step 6: Deploy Kagenti with SPIFFE and Operator SPIFFE Auth

Deploy using the standard setup script:

```bash
cd /Users/alan/Documents/Work/kagenti

./scripts/kind/setup-kagenti.sh \
  --skip-cluster \
  --with-spire \
  --with-mlflow \
  --enable-operator-spiffe-auth \
  --kagenti-values /tmp/operator-spiffe-test-values.yaml
```

**Expected**: Complete Kagenti deployment with:
- SPIRE (Agent + Server + CSI Driver)
- Keycloak
- Kagenti operator with SPIFFE auth enabled
- Bootstrap job created in `keycloak` namespace

**Verify**:
```bash
# Check all namespaces created
kubectl get ns | grep -E "kagenti-system|keycloak|spire|zero-trust"

# Check SPIRE components
kubectl get pods -n spire-system  # Agent + CSI driver
kubectl get pods -n zero-trust-workload-identity-manager  # Server

# Check Keycloak
kubectl get pods -n keycloak  # Keycloak + Postgres

# Check operator
kubectl get pods -n kagenti-system -l control-plane=controller-manager

# ⚠️ IMMEDIATELY check bootstrap job (it auto-deletes after 5 minutes!)
kubectl get job -n keycloak kagenti-operator-client-bootstrap
kubectl logs -n keycloak job/kagenti-operator-client-bootstrap --tail=50
```

**All pods should be Running, bootstrap job should be Complete.**

**⚠️ CRITICAL**: If you don't check the bootstrap job within 5 minutes of deployment completing, it will be auto-deleted and you won't be able to see its logs or status. Proceed immediately to Step 9 after deployment completes!

---

### Step 7: Verify Operator Has spiffe-helper Sidecar

Check that the operator pod has both manager and spiffe-helper containers:

```bash
OPERATOR_POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager -o jsonpath='{.items[0].metadata.name}')

echo "Operator pod: $OPERATOR_POD"
kubectl get pod "$OPERATOR_POD" -n kagenti-system -o jsonpath='{.spec.containers[*].name}'
echo ""
kubectl get pod "$OPERATOR_POD" -n kagenti-system -o jsonpath='{.status.containerStatuses[*].name}'
echo ""
```

**Expected Output**:
```
Operator pod: kagenti-controller-manager-xxxxx-xxxxx
manager spiffe-helper
manager spiffe-helper
```

**Status**: Pod should be `Running` with `2/2` containers ready.

**Verify**:
```bash
kubectl get pod "$OPERATOR_POD" -n kagenti-system
# Should show: READY 2/2, STATUS Running
```

---

### Step 8: Verify Operator Has SPIRE Identity (ClusterSPIFFEID)

Check that SPIRE has assigned the operator a SPIFFE identity:

```bash
# Check if ClusterSPIFFEID exists for operator
kubectl get clusterspiffeid | grep operator

# Check SPIRE registration entry
kubectl exec -n zero-trust-workload-identity-manager spire-server-0 -c spire-server -- \
  /opt/spire/bin/spire-server entry show | grep -A 10 "ns/kagenti-system/sa"
```

**Expected**:
- ClusterSPIFFEID resource exists for operator (may be named `kagenti-operator` or similar)
- SPIRE entry shows: `spiffe://localtest.me/ns/kagenti-system/sa/controller-manager`
- Entry should have selector matching the operator pod

**Verify**: The operator has a valid SPIFFE identity registered in SPIRE.

**If ClusterSPIFFEID is missing**, this is a **BUG** - the deployment should create it automatically.

---

### Step 9: Verify Bootstrap Job Configured Keycloak

**⚠️ IMPORTANT**: The bootstrap job auto-deletes after 5 minutes (`ttlSecondsAfterFinished: 300`). You must check it immediately after deployment completes.

Check that the bootstrap job successfully configured Keycloak:

```bash
# Check bootstrap job status (do this immediately after deployment!)
kubectl get job -n keycloak kagenti-operator-client-bootstrap

# Watch job until completion (if still running)
kubectl wait --for=condition=complete job/kagenti-operator-client-bootstrap -n keycloak --timeout=180s

# Check job logs (must do within 5 minutes of completion)
kubectl logs -n keycloak job/kagenti-operator-client-bootstrap --tail=50
```

**Expected Job Status**:
```
NAME                                STATUS     COMPLETIONS   DURATION   AGE
kagenti-operator-client-bootstrap   Complete   1/1           45s        2m
```

**Expected Job Logs**:
```
✓ SPIFFE Identity Provider 'spire-spiffe' created/updated
✓ Operator client 'kagenti-operator' created
✓ Client authenticator type: federated-jwt
✓ manage-clients role assigned
✓ Bootstrap completed successfully
```

**If job is missing or shows `NotFound`**: The job either hasn't been created yet (wait), or it completed/failed and was already deleted. Check events:
```bash
kubectl get events -n keycloak --sort-by='.lastTimestamp' | grep bootstrap
```

**If job shows `Failed` status**: This is a **BUG**. Check logs before it gets deleted:
```bash
kubectl logs -n keycloak job/kagenti-operator-client-bootstrap
```

**Verify Keycloak Configuration** (do this even if job was deleted):

```bash
# Port-forward to Keycloak
kubectl port-forward -n keycloak svc/keycloak-service 8080:8080 &
sleep 3

# Get admin credentials
KEYCLOAK_ADMIN_USER=$(kubectl get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.username}' | base64 -d)
KEYCLOAK_ADMIN_PASS=$(kubectl get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.password}' | base64 -d)

# Get admin token
TOKEN=$(curl -s -X POST "http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$KEYCLOAK_ADMIN_USER" \
  -d "password=$KEYCLOAK_ADMIN_PASS" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" | jq -r '.access_token')

# Check SPIFFE Identity Provider
curl -s "http://keycloak.localtest.me:8080/admin/realms/kagenti/identity-provider/instances/spire-spiffe" \
  -H "Authorization: Bearer $TOKEN" | jq '{providerId, alias}'

# Check operator client
curl -s "http://keycloak.localtest.me:8080/admin/realms/kagenti/clients?clientId=kagenti-operator" \
  -H "Authorization: Bearer $TOKEN" | jq '.[0] | {clientId, clientAuthenticatorType, serviceAccountsEnabled}'
```

**Expected Output**:

**SPIFFE IdP**:
```json
{
  "providerId": "spiffe",
  "alias": "spire-spiffe"
}
```

**Operator Client**:
```json
{
  "clientId": "kagenti-operator",
  "clientAuthenticatorType": "federated-jwt",
  "serviceAccountsEnabled": true
}
```

**If any of these don't match, this is a BUG in the bootstrap job.**

**Common bootstrap job issues**:
- Image pull failures (check if image was loaded into Kind correctly)
- Environment variable errors (SPIRE_OIDC_URL vs SPIRE_OIDC_DISCOVERY_URL confusion)
- Keycloak not ready when job runs (timing issue)
- Wrong service URLs or connection errors

---

### Step 10: Verify Operator Uses SPIFFE Authentication

Check operator logs to confirm SPIFFE ID auth is enabled:

```bash
OPERATOR_POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager -o jsonpath='{.items[0].metadata.name}')

kubectl logs -n kagenti-system "$OPERATOR_POD" -c manager | grep -i "spiffe\|dcr\|jwt-svid"
```

**Expected Log Lines**:
```json
{"level":"info","msg":"SPIFFE ID authentication enabled: using JWT-SVID for client registration","spireSocket":"unix:///run/spire/sockets/agent.sock"}
```

**Verify**: Operator knows it should use SPIFFE authentication for client registration.

---

### Step 11: Deploy Weather Agent

Deploy the example weather agent to test operator client registration:

```bash
cd /Users/alan/Documents/Work/kagenti

# Deploy weather agent using the CLI skill
kubectl create namespace team1 --dry-run=client -o yaml | kubectl apply -f -

# Deploy weather agent and tool
# Use the kagenti:weather-demo skill or deploy manually
```

**Alternative - Manual Deployment**:

```bash
# Create test agent with proper labels
cat > /tmp/weather-agent.yaml << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-agent
  namespace: team1
  labels:
    kagenti.io/type: agent
    app: weather-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: weather-agent
  template:
    metadata:
      labels:
        app: weather-agent
        kagenti.io/type: agent
    spec:
      serviceAccountName: weather-agent
      containers:
      - name: agent
        image: busybox
        command: ["sleep", "3600"]
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: weather-agent
  namespace: team1
EOF

kubectl apply -f /tmp/weather-agent.yaml
```

**Expected**: Weather agent deployment created in team1 namespace.

**Verify**:
```bash
kubectl get deployment -n team1 weather-agent
kubectl get pod -n team1 -l app=weather-agent
```

**Pod should eventually reach Running status.**

---

### Step 12: Verify Operator Registers Weather Agent Using SPIFFE ID

Watch operator logs for client registration activity:

```bash
OPERATOR_POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager -o jsonpath='{.items[0].metadata.name}')

# Watch for registration
kubectl logs -n kagenti-system "$OPERATOR_POD" -c manager --follow | grep -i "weather-agent"
```

**Expected Log Entries**:
- Operator detects the weather-agent deployment
- Constructs SPIFFE-based client ID: `spiffe://localtest.me/ns/team1/sa/weather-agent`
- Attempts to fetch JWT-SVID from SPIRE
- Registers client in Keycloak using JWT-SVID authentication

**Look for**:
- NO errors about missing socket or connection refused
- NO "using admin credentials" messages
- SUCCESS messages about client registration

**If you see errors like**:
- `dial unix /run/spire/sockets/agent.sock: connect: no such file or directory` → **BUG**: Operator can't access SPIRE
- `failed to fetch JWT-SVID` → **BUG**: SPIRE registration issue
- Any authentication failures → **BUG**

---

### Step 13: Verify Weather Agent Client in Keycloak

Check that the weather agent client was registered in Keycloak:

```bash
# Port-forward to Keycloak (if not already running)
kubectl port-forward -n keycloak svc/keycloak-service 8080:8080 &
sleep 3

# Get admin token (if not already obtained)
KEYCLOAK_ADMIN_USER=$(kubectl get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.username}' | base64 -d)
KEYCLOAK_ADMIN_PASS=$(kubectl get secret -n keycloak keycloak-initial-admin -o jsonpath='{.data.password}' | base64 -d)

TOKEN=$(curl -s -X POST "http://keycloak.localtest.me:8080/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$KEYCLOAK_ADMIN_USER" \
  -d "password=$KEYCLOAK_ADMIN_PASS" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" | jq -r '.access_token')

# Check for weather agent client
curl -s "http://keycloak.localtest.me:8080/admin/realms/kagenti/clients?clientId=team1.weather-agent" \
  -H "Authorization: Bearer $TOKEN" | jq '.[0] | {clientId, enabled}'
```

**Expected Output**:
```json
{
  "clientId": "team1.weather-agent",
  "enabled": true
}
```

**Verify**: The client exists and was registered by the operator using SPIFFE ID authentication (not admin credentials).

**If client doesn't exist, this is a BUG.**

---

## Success Criteria

All of the following must be true for the test to pass:

1. ✅ Operator pod runs with 2/2 containers (manager + spiffe-helper)
2. ✅ Operator has a SPIFFE identity registered in SPIRE  
3. ✅ Bootstrap job completes successfully
4. ✅ SPIFFE Identity Provider configured in Keycloak with `providerId: "spiffe"`
5. ✅ Operator client configured in Keycloak with `clientAuthenticatorType: "federated-jwt"`
6. ✅ Operator logs show "SPIFFE ID authentication enabled: using JWT-SVID for client registration"
7. ✅ Weather agent deployment created successfully
8. ✅ Operator detects weather agent and attempts registration
9. ✅ NO errors fetching JWT-SVID from SPIRE
10. ✅ Weather agent client appears in Keycloak
11. ✅ Operator used SPIFFE ID authentication (not admin credentials)

## Known Issues to Fix

If any of these issues appear during testing, they are **BUGS** that must be fixed:

### Issue 1: CSI Volume Missing volumeAttributes
**Symptom**: Operator can't access SPIRE socket - `dial unix /run/spire/sockets/agent.sock: connect: no such file or directory`  
**Root Cause**: SPIRE CSI volume definition lacks `volumeAttributes` needed for the CSI driver to provide the socket  
**Fix Required**: Add `volumeAttributes` (podKind, podName, podNamespace) to the CSI volume spec in operator chart

### Issue 2: Bootstrap Job Failed or Didn't Register Operator
**Symptom**: Job exists or ServiceAccount exists but operator client not in Keycloak  
**Root Cause**: Bootstrap job crashed, wrong environment variables, or image issue  
**Fix Required**: Check bootstrap job logs immediately after deployment (job auto-deletes after 5 minutes)
**Common Causes**:
  - Environment variable name mismatch (SPIRE_OIDC_URL vs SPIRE_OIDC_DISCOVERY_URL)
  - Image not loaded into Kind properly
  - Keycloak not ready when job starts
  - Connection errors to Keycloak or SPIRE services

### Issue 3: (Duplicate of Issue 1 - removed)

### Issue 3: Webhook Timeouts
**Symptom**: Pods fail to create with "context deadline exceeded"  
**Root Cause**: Webhook performance issue or informer sync problem  
**Fix Required**: Investigate webhook implementation

## Cleanup

```bash
kind delete cluster --name kagenti
kubectl port-forward --all-namespaces | pkill -f "port-forward"
```

## Notes

- This test must work on a **fresh cluster** without any manual workarounds
- All automation should be in place - no manual Keycloak configuration, no manual ClusterSPIFFEID creation
- The test proves that both PRs work together to enable operator SPIFFE ID authentication
