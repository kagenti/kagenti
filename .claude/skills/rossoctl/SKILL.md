---
name: rossoctl
description: Deploy and manage Rossoctl platform, operator, agents, and tools on Kubernetes.
---

```mermaid
flowchart TD
    DEPLOY([Deploy]) --> TYPE{Platform?}
    TYPE -->|Kind| KDEPLOY["rossoctl:deploy"]:::deploy
    TYPE -->|OpenShift| ODEPLOY["rossoctl:deploy"]:::deploy
    TYPE -->|HyperShift| HSDEPLOY["rossoctl:operator"]:::deploy

    KDEPLOY --> HEALTH["k8s:health"]:::k8s
    ODEPLOY --> HEALTH
    HSDEPLOY --> HEALTH
    HEALTH -->|Healthy| DONE([Ready])
    HEALTH -->|Issues| DEBUG{Debug}
    DEBUG -->|Pods| PODS["k8s:pods"]:::k8s
    DEBUG -->|Logs| LOGS["k8s:logs"]:::k8s
    DEBUG -->|UI| UI["rossoctl:ui-debug"]:::deploy

    classDef deploy fill:#795548,stroke:#333,color:white
    classDef k8s fill:#00BCD4,stroke:#333,color:white
```

> Follow this diagram as the workflow.

# Rossoctl Skills

Skills for deploying and managing the Rossoctl platform.

## Available Sub-Skills

| Skill | Description |
|-------|-------------|
| `rossoctl:operator` | Deploy Rossoctl operator, agents, tools, run E2E tests |
| `rossoctl:deploy` | Deploy Rossoctl Kind cluster using Python installer |
| `rossoctl:ui-debug` | Debug UI issues including 502 errors, API connectivity, nginx proxy |

## Quick Deploy (Kind)

```bash
# Deploy platform
./.github/scripts/operator/30-run-installer.sh

# Wait for CRDs
./.github/scripts/operator/41-wait-crds.sh

# Deploy demo agents
./.github/scripts/operator/71-build-weather-tool.sh
./.github/scripts/operator/72-deploy-weather-tool.sh
./.github/scripts/operator/74-deploy-weather-agent.sh
```

## Quick Deploy (OpenShift)

```bash
export KUBECONFIG=~/clusters/hcp/<cluster-name>/auth/kubeconfig
./.github/scripts/operator/30-run-installer.sh --env ocp
```

## Run E2E Tests

```bash
export AGENT_URL="http://localhost:8000"
export ROSSOCTL_CONFIG_FILE=deployments/envs/dev_values.yaml
./.github/scripts/operator/90-run-e2e-tests.sh
```

## Related Documentation

- `docs/install.md`
