---
name: testing:kubectl-debugging
description: Common kubectl commands for debugging Rossoctl components
---

# Kubectl Debugging Patterns

Common kubectl commands for debugging Rossoctl components.

## Context-Safe Execution (MANDATORY)

**All kubectl/oc commands MUST redirect output to files.** Commands below are shown in bare
form for readability. When executing, always redirect:

```bash
export LOG_DIR=/tmp/rossoctl/k8s/${CLUSTER:-local}
mkdir -p $LOG_DIR

# Pattern: kubectl <command> > $LOG_DIR/<name>.log 2>&1 && echo "OK" || echo "FAIL"
# Analyze in subagent: Task(subagent_type='Explore') with Grep
```

## Table of Contents

- [Setting Up Environment](#setting-up-environment)
- [Helm Debugging](#helm-debugging)
- [ConfigMap and Secret Inspection](#configmap-and-secret-inspection)
- [Pod Debugging](#pod-debugging)
- [Service Debugging](#service-debugging)
- [Keycloak Client Verification](#keycloak-client-verification)
- [Job Debugging](#job-debugging)
- [Istio Debugging](#istio-debugging)
- [Events](#events)
- [Quick Reference](#quick-reference)

## Setting Up Environment

### Using Correct Kubeconfig

```bash
# HyperShift cluster
export KUBECONFIG=~/clusters/hcp/rossoctl-hypershift-custom-mlflow/auth/kubeconfig

# Kind cluster
export KUBECONFIG=~/.kube/config
kubectl config use-context kind-rossoctl
```

### Verify Connection

```bash
kubectl cluster-info
kubectl get nodes
```

## Helm Debugging

### Check Rendered Values

```bash
helm get values rossoctl-deps -n rossoctl-system
```

### Check All Values (Including Defaults)

```bash
helm get values rossoctl-deps -n rossoctl-system -a
```

### Template Without Installing

```bash
helm template rossoctl-deps charts/rossoctl-deps -n rossoctl-system \
  -f /tmp/values.yaml > /tmp/rendered.yaml
```

### Check Release Status

```bash
helm list -n rossoctl-system
helm history rossoctl-deps -n rossoctl-system
```

## ConfigMap and Secret Inspection

### Extract ConfigMap Content

```bash
kubectl get configmap otel-collector-config -n rossoctl-system -o yaml
```

### Extract Specific Key

```bash
kubectl get configmap otel-collector-config -n rossoctl-system \
  -o jsonpath='{.data.otel-collector-config\.yaml}'
```

### Decode Secret

```bash
kubectl get secret mlflow-oauth-secret -n rossoctl-system \
  -o jsonpath='{.data.MLFLOW_CLIENT_ID}' | base64 -d
```

### List All Secret Keys

```bash
kubectl get secret mlflow-oauth-secret -n rossoctl-system \
  -o jsonpath='{.data}' | jq 'keys'
```

## Pod Debugging

### Check Pod Environment Variables

```bash
kubectl get pod otel-collector-xxx -n rossoctl-system \
  -o jsonpath='{.spec.containers[0].env}' | jq
```

### Check Pod Status

```bash
kubectl describe pod otel-collector-xxx -n rossoctl-system
```

### Get Pod Logs

```bash
kubectl logs -n rossoctl-system otel-collector-xxx
kubectl logs -n rossoctl-system otel-collector-xxx --previous  # After crash
kubectl logs -n rossoctl-system otel-collector-xxx -f          # Follow
```

### Exec Into Pod

```bash
kubectl exec -it otel-collector-xxx -n rossoctl-system -- /bin/sh
```

### Check Mounted Files

```bash
kubectl exec -it otel-collector-xxx -n rossoctl-system -- \
  ls -la /etc/pki/ca-trust/extracted/pem/
```

## Service Debugging

### Check Service Endpoints

```bash
kubectl get endpoints mlflow -n rossoctl-system
```

### Check Service Labels

```bash
kubectl get svc mlflow -n rossoctl-system --show-labels
```

### Port Forward

```bash
kubectl port-forward svc/mlflow 5000:5000 -n rossoctl-system
```

## Keycloak Client Verification

### Get Token

```bash
# Set variables
KEYCLOAK_URL="http://keycloak-service.keycloak.svc.cluster.local:8080"
CLIENT_ID="mlflow-client"
CLIENT_SECRET=$(kubectl get secret mlflow-oauth-secret -n rossoctl-system \
  -o jsonpath='{.data.MLFLOW_CLIENT_SECRET}' | base64 -d)

# Get token
curl -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET"
```

### Test From Inside Cluster

```bash
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -X POST "http://keycloak-service.keycloak.svc.cluster.local:8080/realms/master/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=mlflow-client" \
  -d "client_secret=<secret>"
```

## Job Debugging

### Check Job Status

```bash
kubectl get jobs -n keycloak
kubectl describe job mlflow-oauth-secret -n keycloak
```

### Get Job Pod Logs

```bash
kubectl logs -n keycloak -l job-name=mlflow-oauth-secret
```

### Rerun Failed Job

```bash
kubectl delete job mlflow-oauth-secret -n keycloak
# Job will be recreated by Helm if still in chart
```

## Istio Debugging

### Check Waypoint Status

```bash
kubectl get gateway -n rossoctl-system
kubectl describe gateway mlflow-waypoint -n rossoctl-system
```

### Check AuthorizationPolicy

```bash
kubectl get authorizationpolicy -n rossoctl-system
kubectl describe authorizationpolicy mlflow-traces-from-otel -n rossoctl-system
```

### Check Pod Identity

```bash
istioctl proxy-config secret otel-collector-xxx -n rossoctl-system
```

### Check ztunnel Logs

```bash
kubectl logs -n istio-system -l app=ztunnel --tail=100
```

## Events

### Namespace Events

```bash
kubectl get events -n rossoctl-system --sort-by='.lastTimestamp'
```

### Pod Events

```bash
kubectl get events -n rossoctl-system --field-selector involvedObject.name=otel-collector-xxx
```

## Resource Usage

### Pod Resources

```bash
kubectl top pods -n rossoctl-system
```

### Describe Resource Limits

```bash
kubectl get pod otel-collector-xxx -n rossoctl-system \
  -o jsonpath='{.spec.containers[0].resources}'
```

## Quick Reference

| Task | Command |
|------|---------|
| Get all pods | `kubectl get pods -n rossoctl-system` |
| Get logs | `kubectl logs -n rossoctl-system <pod>` |
| Describe pod | `kubectl describe pod -n rossoctl-system <pod>` |
| Exec shell | `kubectl exec -it <pod> -n rossoctl-system -- /bin/sh` |
| Port forward | `kubectl port-forward svc/<svc> <port>:<port> -n rossoctl-system` |
| Get events | `kubectl get events -n rossoctl-system --sort-by='.lastTimestamp'` |
| Helm values | `helm get values rossoctl-deps -n rossoctl-system` |

## Related Skills

- `tdd:hypershift`
- `k8s:live-debugging`
- `istio:ambient-waypoint`
