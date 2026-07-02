# Manual Test: Operator SPIFFE ID Authentication

**Last Updated:** 2026-07-01

**Branch:** `feat/operator-spiffe-auth-clean` (PR #2135)

**Status:** ✅ **COMPLETE** - All 9 steps passed successfully on a fresh cluster

---

## E2E Test Results Summary

| Test Component | Status | Details |
|---|---|---|
| Operator SPIFFE Auth | ✅ PASS | Operator authenticates to Keycloak using JWT-SVID |
| Agent Registration | ✅ PASS | Clients registered with SPIFFE-shaped IDs |
| Client Credentials | ✅ PASS | OAuth2 client credentials grant returns HTTP 200 |
| Helm Release Status | ✅ PASS | `STATUS: deployed` (no more "failed") |
| Operator Pod | ✅ PASS | 2/2 containers (manager + spiffe-helper) on first install |
| authbridge-config | ✅ PASS | Present in kagenti-system from install time |

**Conclusion:** PRs #2135 and #349 are **READY TO MERGE**.

---

## ⚠️ CRITICAL REQUIREMENTS

### 1. SPIFFE Auth is MANDATORY
**This test MUST use SPIFFE authentication. NEVER use admin credentials as a workaround.**
- The entire purpose of PR #2135 and PR #349 is to eliminate credential-based authentication
- If SPIFFE auth doesn't work, the test has FAILED — do not bypass it

### 2. Full E2E Test is MANDATORY
All steps 1–9 must complete successfully before declaring these PRs ready to merge.

---

## Overview

This document provides instructions for manually testing operator SPIFFE ID authentication across two PRs. All deployment issues discovered during testing have been fixed.

## Pull Requests Under Test

### PR #2135 (kagenti repo): `feat/operator-spiffe-auth-clean`
- Bootstrap job that registers the operator as a Keycloak client with `federated-jwt` auth
- SPIFFE Identity Provider configuration in Keycloak
- Operator helm chart with spiffe-helper sidecar (`kagenti-operator-chart` v0.3.0-alpha.4 committed to `charts/kagenti/charts/`)
- `authbridge-config` ConfigMap created in `kagenti-system` for the operator's client registration controller

### PR #349 (kagenti-operator repo): `pr-349`
- Operator code to use SPIFFE ID authentication for agent client registration
- JWT-SVID fetch and OAuth 2.0 client credentials flow via spiffe-helper

---

## Prerequisites

- **Container Runtime:** Docker (Colima or Docker Desktop) or Podman
- **Kind CLI**, **kubectl**, **Helm 3** installed

### Docker (Colima or Docker Desktop)
```bash
# Start Colima if using it
colima start --cpu 4 --memory 8

# Verify
docker ps
```

### Podman
```bash
export KIND_EXPERIMENTAL_PROVIDER=podman
export DOCKER_HOST=unix://$(find /var/folders -name "podman-machine-default-api.sock" 2>/dev/null | head -1)
```

**Time Required:** 25–35 minutes

---

## Fixed Issues (Included in PR #2135)

All deployment issues discovered during testing are fixed:

| # | Issue | Fix |
|---|---|---|
| 1 | Helm install `STATUS: failed` — 10 "already exists" errors | Removed duplicate resources from `agent-namespaces.yaml`; secrets/configmaps now only in `agent-namespace-resources.yaml` |
| 2 | `authbridge-config` missing in `kagenti-system` — operator waited indefinitely | Added `authbridge-config` ConfigMap to `kagenti-system` when `components.agentOperator.enabled: true` |
| 3 | OCI subchart override: spiffe-helper sidecar missing on install | `kagenti-operator-chart` (v0.3.0-alpha.4 with spiffe-helper) committed to repo; setup script deletes OCI tarball and `Chart.lock` so local chart is used |
| 4 | Setup script did two-step install; second upgrade failed silently | Moved tarball/lock deletion before the initial `helm upgrade --install` — single-step install now |
| 5 | Helm template syntax bug | Fixed extra `{{- end }}` in `agent-namespace-resources.yaml` |
| 6 | Bootstrap job requires correct image | Setup script runs bootstrap job with `imagePullPolicy: Never` |

## Known Issues

- **Helm release briefly shows `pending-install`** immediately after `helm upgrade --install` completes. This is a timing race between `--wait` returning and helm finalising the release state — it resolves to `deployed` within seconds automatically. Use `kubectl get pod -n kagenti-system -l control-plane=controller-manager` to verify readiness rather than `helm status`.

---

## Repository Structure

The kagenti-operator repo has a **nested directory structure**:

```
/path/to/kagenti-operator/        ← git clone creates this
└── kagenti-operator/              ← actual code (cd into this for docker build!)
    ├── Dockerfile
    └── cmd/main.go
```

After cloning, `cd` into the **inner** `kagenti-operator` directory to find the Dockerfile.

---

## Test Procedure

### Step 1: Clean Environment

```bash
kind delete cluster --name kagenti
```

---

### Step 2: Build Operator Image (PR #349)

The PR #349 branch is `feat/spiffe-dcr-client-registration`. Navigate to the
**inner** `kagenti-operator` directory to find the Dockerfile:

```bash
cd /path/to/kagenti-operator/kagenti-operator

git fetch origin
git checkout feat/spiffe-dcr-client-registration
git pull origin feat/spiffe-dcr-client-registration

docker build -t localhost/kagenti-operator:spiffe-test .

echo "Exit: $?"
# Expected: Exit: 0
```

---

### Step 3: Build Bootstrap Image (PR #2135)

```bash
cd /path/to/kagenti

git checkout feat/operator-spiffe-auth-clean
git pull origin feat/operator-spiffe-auth-clean

# Build context must be kagenti/ — the Dockerfile uses COPY auth/operator-spiffe-bootstrap/...
# relative to that directory
docker build -t ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest \
  -f kagenti/auth/operator-spiffe-bootstrap/Dockerfile \
  kagenti/

echo "Exit: $?"
# Expected: Exit: 0
```

---

### Step 4: Create Kind Cluster

```bash
# From kagenti repo root
kind create cluster --name kagenti --config scripts/kind/kind-config-registry.yaml

kubectl cluster-info
# Expected: Kubernetes control plane is running
```

---

### Step 5: Load Custom Images into Kind

```bash
# Simpler approach — load directly from Docker daemon
kind load docker-image localhost/kagenti-operator:spiffe-test --name kagenti
kind load docker-image ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest --name kagenti

# Verify both images are in the cluster
docker exec -i kagenti-control-plane crictl images 2>/dev/null | grep -E "kagenti-operator|operator-spiffe-bootstrap"
# Expected: Both images listed
```

---

### Step 6: Deploy Kagenti with Operator SPIFFE Auth

The setup script packages the operator helm chart from your local kagenti-operator
checkout (it needs the chart from PR #349 which adds the spiffe-helper sidecar —
the published OCI chart doesn't have it yet).

```bash
cd /path/to/kagenti

# Point to your kagenti-operator checkout (default: ../kagenti-operator)
export KAGENTI_OPERATOR_REPO=/path/to/kagenti-operator

./docs/testing/setup-operator-spiffe-test.sh
```

The script installs (in order): cert-manager → Istio → SPIRE → kagenti-deps (Keycloak) → SPIFFE IdP setup job → kagenti chart with operator SPIFFE auth enabled.

**Expected output — all green checkmarks:**
```
✓ cert-manager installed
✓ Istio installed
✓ SPIRE installed
✓ kagenti-deps installed
✓ SPIFFE IdP setup completed
✓ Using operator subchart from kagenti-operator source (PR #349)
✓ kagenti installed
✓ Operator is ready
✓ Setup complete!
```

**After the script finishes, verify:**

```bash
# Operator must have 2/2 containers (manager + spiffe-helper)
kubectl get pod -n kagenti-system -l control-plane=controller-manager
# Expected: READY 2/2

# Helm release must be deployed (not failed/pending)
helm list -n kagenti-system
# Expected: STATUS deployed

# SPIFFE auth enabled message (search full logs by pod name)
POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n kagenti-system $POD -c manager | grep "SPIFFE ID authentication enabled"
# Expected: {"msg":"SPIFFE ID authentication enabled: using JWT-SVID for client registration",...}
```

**Time:** ~20 minutes.

---

### Step 7: Deploy Test Agent

```bash
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

kubectl wait --for=condition=available deployment/test-agent -n team1 --timeout=90s
kubectl get pod -n team1 -l app=test-agent
# Expected: READY 2/2 (agent + authbridge sidecar injected by operator webhook)
```

---

### Step 8: Verify Operator Registration

```bash
# Watch for registration — should appear within ~30 seconds
kubectl logs -n kagenti-system -l control-plane=controller-manager -c manager \
  --follow --since=2m | grep -iE "test-agent|registration applied"
# Expected: {"msg":"operator client registration applied",...,"workload":"test-agent","namespace":"team1"}

# Verify the credentials secret was created
kubectl get secret -n team1 | grep kagenti-keycloak-client-credentials
# Expected: kagenti-keycloak-client-credentials-59cb4144e6505e3b   Opaque   2

# Verify the client ID is a SPIFFE ID (not a plain name)
SECRET=kagenti-keycloak-client-credentials-59cb4144e6505e3b
kubectl get secret $SECRET -n team1 -o jsonpath='{.data.client-id\.txt}' | base64 -d && echo ""
# Expected: spiffe://localtest.me/ns/team1/sa/test-agent
```

---

### Step 9: Verify End-to-End Authentication

```bash
SECRET=kagenti-keycloak-client-credentials-59cb4144e6505e3b
CLIENT_ID=$(kubectl get secret $SECRET -n team1 -o jsonpath='{.data.client-id\.txt}' | base64 -d)
CLIENT_SECRET=$(kubectl get secret $SECRET -n team1 -o jsonpath='{.data.client-secret\.txt}' | base64 -d)

kubectl run --rm -i --restart=Never curl-test --image=curlimages/curl --namespace=kagenti-system -- \
  curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST \
  "http://keycloak-service.keycloak.svc:8080/realms/kagenti/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" | grep -E "access_token|HTTP_STATUS|error"
```

**Expected:**
```
{"access_token":"eyJ...","token_type":"Bearer",...}
HTTP_STATUS:200
```

The `azp` claim in the decoded JWT will be `spiffe://localtest.me/ns/team1/sa/test-agent`, confirming end-to-end SPIFFE identity.

---

## Success Criteria

| # | Criterion | How to verify |
|---|---|---|
| 1 | Operator pod has 2/2 containers | `kubectl get pod -n kagenti-system -l control-plane=controller-manager` |
| 2 | Helm release is `deployed` | `helm list -n kagenti-system` |
| 3 | SPIFFE auth enabled in operator logs | `kubectl logs ... -c manager \| grep "SPIFFE ID authentication enabled"` |
| 4 | `authbridge-config` in `kagenti-system` | `kubectl get configmap authbridge-config -n kagenti-system` |
| 5 | Test agent pod 2/2 (authbridge injected) | `kubectl get pod -n team1 -l app=test-agent` |
| 6 | Client credentials secret exists | `kubectl get secret -n team1 \| grep kagenti-keycloak-client-credentials` |
| 7 | Client ID is a SPIFFE ID | Decoded `client-id.txt` = `spiffe://localtest.me/ns/team1/sa/test-agent` |
| 8 | Token endpoint returns HTTP 200 | Step 9 curl response |

---

## Troubleshooting

### `helm status kagenti` shows `pending-install` briefly
Normal — resolves to `deployed` within seconds. Check pod readiness instead.

### Operator pod not 2/2 after install
```bash
helm get values kagenti -n kagenti-system | grep -A 5 "spiffe:"
# Both spiffe.enabled and spiffe.operatorAuth.enabled must be true

kubectl describe pod -n kagenti-system -l control-plane=controller-manager
# Check Events for image pull or volume mount errors
```

### SPIFFE auth log message not found with `--tail=50`
Use the full log search instead:
```bash
POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n kagenti-system $POD -c manager | grep "SPIFFE ID authentication enabled"
```

### Agent pod stuck in `ContainerCreating`
The operator may not have registered the agent yet. Check:
```bash
kubectl describe pod -n team1 -l app=test-agent | grep -A 3 "Events:"
kubectl logs -n kagenti-system -l control-plane=controller-manager -c manager --tail=50
```

### Bootstrap job fails
```bash
kubectl logs -n kagenti-system job/kagenti-spiffe-idp-setup-job --tail=50
# Common cause: bootstrap image not loaded with imagePullPolicy: Never
# Verify: kubectl get job -n kagenti-system kagenti-spiffe-idp-setup-job \
#   -o jsonpath='{.spec.template.spec.containers[0].imagePullPolicy}'
```

---

## Cleanup

```bash
kind delete cluster --name kagenti
rm -f /tmp/kagenti-spiffe-test-values.yaml
```
