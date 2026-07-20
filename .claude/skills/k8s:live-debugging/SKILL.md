---
name: k8s:live-debugging
description: Iterative debugging workflow for fixing issues on a running cluster
---

# Live Cluster Debugging Workflow

Iterative debugging workflow for fixing issues on a running HyperShift cluster.

## Context-Safe Execution (MANDATORY)

**All kubectl/oc commands MUST redirect output to files.** Live debugging generates
the most context pollution because of iterative check-fix-recheck loops.

```bash
export LOG_DIR=/tmp/rossoctl/k8s/${CLUSTER:-local}
mkdir -p $LOG_DIR

# Every kubectl command → redirect to file
kubectl <command> > $LOG_DIR/<name>.log 2>&1 && echo "OK" || echo "FAIL"

# Analyze in subagent: Task(subagent_type='Explore') to read log files
# Use subagents for BOTH failure analysis AND verifying expected behavior
```

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Workflow](#workflow)
- [Common Debugging Scenarios](#common-debugging-scenarios)
- [Environment Variable Quick Reference](#environment-variable-quick-reference)
- [Useful One-Liners](#useful-one-liners)
- [After Debugging](#after-debugging)

## Overview

When tests fail on a deployed cluster, use this workflow to:
1. Diagnose the root cause
2. Make targeted fixes
3. Verify the fix without full redeployment

## Prerequisites

```bash
# Set the kubeconfig for your cluster
export KUBECONFIG=~/clusters/hcp/rossoctl-hypershift-custom-<suffix>/auth/kubeconfig

# Verify connection
kubectl get nodes
```

## Workflow

### 1. Check Test Results

```bash
# View test results XML
cat test-results/e2e-results.xml

# Or re-run failing test with verbose output
pytest rossoctl/tests/e2e/common/test_mlflow_traces.py -v -s
```

### 2. Check Pod Status

```bash
# Get all pods in relevant namespace
kubectl get pods -n rossoctl-system

# Check specific component
kubectl get pods -n rossoctl-system -l app=otel-collector

# Describe problematic pod
kubectl describe pod -n rossoctl-system <pod-name>
```

### 3. Check Logs

```bash
# Get recent logs
kubectl logs -n rossoctl-system deployment/otel-collector --tail=100

# Stream logs in real-time
kubectl logs -n rossoctl-system deployment/otel-collector -f

# Filter for errors
kubectl logs -n rossoctl-system deployment/otel-collector --tail=200 | grep -iE "(error|fail|403|401)"
```

### 4. Check Configuration

```bash
# View ConfigMap contents
kubectl get configmap otel-collector-config -n rossoctl-system -o yaml

# Check Secret contents (decoded)
kubectl get secret mlflow-oauth-secret -n rossoctl-system -o jsonpath='{.data.OIDC_CLIENT_ID}' | base64 -d

# View rendered Helm values
helm get values rossoctl-deps -n rossoctl-system > /tmp/rossoctl-deps-values.yaml
cat /tmp/rossoctl-deps-values.yaml
```

### 5. Check Authorization

```bash
# View AuthorizationPolicy
kubectl get authorizationpolicy -n rossoctl-system -o yaml

# Check waypoint proxy
kubectl get gateway -n rossoctl-system

# Check service labels
kubectl get svc mlflow -n rossoctl-system -o yaml | grep -A5 labels
```

### 6. Make Chart Changes

```bash
# Edit the chart template
vim charts/rossoctl-deps/templates/otel-collector.yaml

# Apply the change
helm upgrade rossoctl-deps charts/rossoctl-deps -n rossoctl-system \
  -f /tmp/rossoctl-deps-values.yaml
```

### 7. Restart Affected Pods

```bash
# Rollout restart to pick up ConfigMap changes
kubectl rollout restart deployment/otel-collector -n rossoctl-system

# Wait for rollout to complete
kubectl rollout status deployment/otel-collector -n rossoctl-system --timeout=60s
```

### 8. Generate Test Data

```bash
# Get route to weather service
ROUTE_HOST=$(kubectl get route weather-service -n team1 -o jsonpath='{.spec.host}')

# Send test request
curl -sk -X POST "https://$ROUTE_HOST/" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"messageId":"test-123","parts":[{"kind":"text","text":"What is the weather?"}],"role":"user"}}}'
```

### 9. Verify Fix

```bash
# Check logs after test request
kubectl logs -n rossoctl-system deployment/otel-collector --tail=50

# Run the specific failing test
pytest rossoctl/tests/e2e/common/test_mlflow_traces.py::test_mlflow_has_traces -v
```

## Common Debugging Scenarios

### OAuth/Authentication Issues

```bash
# Check if OAuth extension started
kubectl logs -n rossoctl-system deployment/otel-collector | grep oauth2client

# Test token acquisition
KEYCLOAK_HOST=$(kubectl get route keycloak -n keycloak -o jsonpath='{.spec.host}')
CLIENT_ID=$(kubectl get secret mlflow-oauth-secret -n rossoctl-system -o jsonpath='{.data.OIDC_CLIENT_ID}' | base64 -d)
CLIENT_SECRET=$(kubectl get secret mlflow-oauth-secret -n rossoctl-system -o jsonpath='{.data.OIDC_CLIENT_SECRET}' | base64 -d)

curl -sk -X POST "https://$KEYCLOAK_HOST/realms/master/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET"
```

### Mesh/Istio Issues

```bash
# Check Istiod logs for authorization warnings
kubectl logs -n istio-system deployment/istiod --tail=100 | grep -i authorization

# Check if pods are in ambient mode
kubectl get pod -n rossoctl-system -l app=otel-collector -o jsonpath='{.items[0].metadata.annotations}'

# Verify trust domain
kubectl get configmap istio -n istio-system -o jsonpath='{.data.mesh}' | grep trustDomain
```

### Trace Export Issues

```bash
# Add debug exporter to pipeline (in otel-collector.yaml)
# exporters: [ debug, otlphttp/mlflow ]

# Check debug output for traces
kubectl logs -n rossoctl-system deployment/otel-collector | grep "Span #"

# Check for export errors
kubectl logs -n rossoctl-system deployment/otel-collector | grep -i "drop\|error\|fail"
```

## Environment Variable Quick Reference

```bash
# Weather service check
kubectl get pod -n team1 -l app=weather-service -o jsonpath='{.items[0].spec.containers[0].env}' | jq

# OTEL collector environment
kubectl get pod -n rossoctl-system -l app=otel-collector -o jsonpath='{.items[0].spec.containers[0].env}' | jq
```

## Useful One-Liners

```bash
# Get all routes
kubectl get routes -A

# Check all deployments ready
kubectl get deployments -n rossoctl-system

# Watch pod status
watch kubectl get pods -n rossoctl-system

# Quick port-forward for testing
kubectl port-forward -n rossoctl-system svc/mlflow 5000:5000
```

## After Debugging

Once the fix is verified:

1. **Run full test suite**: `pytest rossoctl/tests/e2e/ -v`
2. **Commit changes**: `git add -A && git commit -m "fix: <description>"`
3. **Document findings**: Update relevant skills or CLAUDE.md

## Related Skills

- `tdd:hypershift`
- `testing:kubectl-debugging`
