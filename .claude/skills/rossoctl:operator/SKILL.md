---
name: rossoctl:operator
description: Deploy and manage Rossoctl operator, agents, and tools on Kubernetes. Handles installer, CRDs, pipelines, and demo deployments.
---

# Rossoctl Operator Skill

Deploy and manage Rossoctl operator, agents, and tools on Kubernetes clusters.

## Context-Safe Execution (MANDATORY)

**Deploy/build commands produce large output.** Always redirect to files:

```bash
export LOG_DIR="${LOG_DIR:-${WORKSPACE_DIR:-/tmp}/rossoctl-deploy}"
mkdir -p "$LOG_DIR"

# Pattern: redirect build/deploy output
command > $LOG_DIR/<name>.log 2>&1; echo "EXIT:$?"
# On failure: Task(subagent_type='Explore') with Grep to find errors
```

## When to Use

- Deploying Rossoctl platform to a cluster
- Building and deploying agents/tools
- Running E2E tests
- User asks "deploy rossoctl", "build agent", or "run e2e tests"

## Quick Deploy (Kind)

```bash
# Deploy everything to Kind cluster
./.github/scripts/operator/30-run-installer.sh

# Wait for CRDs and apply pipeline template
./.github/scripts/operator/41-wait-crds.sh
```

## Quick Deploy (OpenShift/HyperShift)

```bash
# Set kubeconfig for target cluster
export KUBECONFIG=~/clusters/hcp/<cluster-name>/auth/kubeconfig

# Deploy with OCP values
./.github/scripts/operator/30-run-installer.sh --env ocp

# Wait for CRDs and apply pipeline template
./.github/scripts/operator/41-wait-crds.sh
```

## Deploy Demo Agents

Full demo deployment workflow:

```bash
# 1. Setup team1 namespace (if not exists)
./.github/scripts/operator/70-setup-team1-namespace.sh

# 2. Build weather tool (Tekton pipeline)
./.github/scripts/operator/71-build-weather-tool.sh

# 3. Deploy weather tool
./.github/scripts/operator/72-deploy-weather-tool.sh

# 5. Deploy weather agent
./.github/scripts/operator/74-deploy-weather-agent.sh
```

## Run E2E Tests

```bash
# Set agent URL (Kind)
export AGENT_URL="http://localhost:8000"
kubectl port-forward -n team1 svc/weather-service 8000:8000 &

# Set agent URL (OpenShift)
export AGENT_URL="https://$(oc get route -n team1 weather-service -o jsonpath='{.spec.host}')"

# Set config file
export ROSSOCTL_CONFIG_FILE=deployments/envs/dev_values.yaml  # Kind
export ROSSOCTL_CONFIG_FILE=deployments/envs/ocp_values.yaml  # OpenShift

# Run tests
./.github/scripts/operator/90-run-e2e-tests.sh
```

## Script Reference

### Core Deployment

| Script | Description |
|--------|-------------|
| `30-run-installer.sh` | Run platform installer |
| `41-wait-crds.sh` | Wait for Rossoctl CRDs to be available |

### Namespace Setup

| Script | Description |
|--------|-------------|
| `70-setup-team1-namespace.sh` | Setup team1 namespace with required resources |

### Agent/Tool Deployment

| Script | Description |
|--------|-------------|
| `71-build-weather-tool.sh` | Build weather tool via Tekton pipeline |
| `72-deploy-weather-tool.sh` | Deploy weather tool Component CR |
| `74-deploy-weather-agent.sh` | Deploy weather agent Component CR |
| `75-deploy-weather-tool-shipwright.sh` | Alternative: deploy with Shipwright |

### Testing

| Script | Description |
|--------|-------------|
| `90-run-e2e-tests.sh` | Run E2E test suite |

## Environment Variables

### Installer

| Variable | Default | Description |
|----------|---------|-------------|
| `--env` | dev | Environment (dev, ocp, test) |
| `KUBECONFIG` | ~/.kube/config | Kubernetes config |

### E2E Tests

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_URL` | required | Agent endpoint URL |
| `ROSSOCTL_CONFIG_FILE` | required | Values file for config |
| `PHOENIX_URL` | (optional) | Phoenix observability URL |

## Installer Options

```bash
# View all options
./.github/scripts/operator/30-run-installer.sh --help

# Common options:
./.github/scripts/operator/30-run-installer.sh --env dev     # Kind/local
./.github/scripts/operator/30-run-installer.sh --env ocp     # OpenShift
./.github/scripts/operator/30-run-installer.sh --env test    # CI testing
```

## Debugging

### Check Operator Status

```bash
# Operator pods
kubectl get pods -n rossoctl-system -l app=rossoctl-operator

# Operator logs
kubectl logs -n rossoctl-system -l app=rossoctl-operator --tail=100

# CRDs
kubectl get crd | grep rossoctl
```

### Check Agent/Tool Status

```bash
# All components
kubectl get components -A

# Shipwright builds
kubectl get builds -A
kubectl get buildruns -A

# Deployments
kubectl get deployments -n team1
```

### Check Shipwright/Tekton Pipelines

```bash
# Pipeline runs
kubectl get pipelineruns -n team1

# Task runs
kubectl get taskruns -n team1

# Pipeline logs
tkn pipelinerun logs -n team1 <pipeline-run-name>
```

### Check Routes/Ingress

```bash
# Kind (HTTPRoutes)
kubectl get httproutes -A

# OpenShift (Routes)
oc get routes -A
```

## Troubleshooting

### Installer Fails

```bash
# Check installer logs
# (Logs are output during run)

# Check namespace
kubectl get ns rossoctl-system

# Check pods
kubectl get pods -n rossoctl-system
```

### CRDs Not Available

```bash
# Check CRD installation
kubectl get crd | grep rossoctl

# Re-run wait script
./.github/scripts/operator/41-wait-crds.sh
```

### Build Fails

```bash
# Check Tekton pipeline run
kubectl get pipelineruns -n team1

# View pipeline logs
kubectl logs -n team1 -l tekton.dev/pipelineRun=<run-name>

# Check Tekton controller
kubectl logs -n tekton-pipelines deployment/tekton-pipelines-controller --tail=100
```

### Agent Not Responding

```bash
# Check pod status
kubectl get pods -n team1 -l app=weather-service

# View agent logs
kubectl logs -n team1 deployment/weather-service --tail=100

# Check service
kubectl get svc -n team1 weather-service

# Test connectivity
kubectl port-forward -n team1 svc/weather-service 8000:8000
curl http://localhost:8000/.well-known/agent.json
```

## Related Skills

- **kind:cluster**: Manage Kind clusters
- **hypershift:cluster**: Manage HyperShift clusters
- **k8s:pods**: Debug pod issues
- **k8s:logs**: Query logs

## Related Documentation

- `deployments/README.md` - Deployment guide
- `docs/install.md` - Installation guide
- `docs/components.md` - Component details
