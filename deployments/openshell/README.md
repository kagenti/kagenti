# OpenShell PoC — Quick Start

Deploy OpenShell + Kagenti Operator with 3 test agents on Kind or HyperShift.

## Prerequisites

- Docker or Rancher Desktop running
- Helm v3 (`brew install helm@3` if you have Helm v4)
- `kubectl` configured
- For LLM tests: `.env.maas` file with LiteMaaS credentials

## Kind (Local)

### Full deploy + test (one command)

```bash
# From the main repo root (not worktree)
PATH="/opt/homebrew/opt/helm@3/bin:$PATH" \
  .worktrees/stream1-sandbox-agent/.github/scripts/local-setup/openshell-full-test.sh \
  --skip-cluster-destroy
```

This creates a Kind cluster, installs Kagenti platform (headless), deploys
OpenShell Gateway, builds and deploys 4 agents, and runs 52 E2E tests.

### Iterate on existing cluster

```bash
# Skip cluster creation (reuse existing)
PATH="/opt/homebrew/opt/helm@3/bin:$PATH" \
  .worktrees/stream1-sandbox-agent/.github/scripts/local-setup/openshell-full-test.sh \
  --skip-cluster-create --skip-cluster-destroy

# Tests only (fastest iteration)
PATH="/opt/homebrew/opt/helm@3/bin:$PATH" \
  .worktrees/stream1-sandbox-agent/.github/scripts/local-setup/openshell-full-test.sh \
  --skip-cluster-create --skip-cluster-destroy --skip-install --skip-agents

# Skip tests (deploy only)
PATH="/opt/homebrew/opt/helm@3/bin:$PATH" \
  .worktrees/stream1-sandbox-agent/.github/scripts/local-setup/openshell-full-test.sh \
  --skip-cluster-create --skip-cluster-destroy --skip-test
```

### Manual testing

```bash
# Port-forward to weather agent and send A2A request
kubectl port-forward -n team1 svc/weather-agent 8080:8080 &
curl -s -X POST http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","messageId":"m1","parts":[{"type":"text","text":"What is the weather in London?"}]}}}' | python3 -m json.tool

# Check OpenShell gateway logs
kubectl logs -n openshell-system openshell-gateway-0 --tail=20

# Check supervised weather agent (PID 1 = openshell-sandbox)
kubectl exec -n team1 deploy/weather-agent-supervised -- cat /proc/1/cmdline | tr '\0' ' '
```

## HyperShift (OpenShift)

### Full deploy + test

```bash
# Source HyperShift credentials
source .env.kagenti-hypershift-custom

# Deploy (creates cluster + installs everything)
PATH="/opt/homebrew/opt/helm@3/bin:$PATH" \
  .worktrees/stream1-sandbox-agent/.github/scripts/local-setup/openshell-full-test.sh \
  --platform ocp --skip-cluster-destroy ospoc

# Or on existing cluster
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-ospoc/auth/kubeconfig
PATH="/opt/homebrew/opt/helm@3/bin:$PATH" \
  .worktrees/stream1-sandbox-agent/.github/scripts/local-setup/openshell-full-test.sh \
  --platform ocp --skip-cluster-create --skip-cluster-destroy
```

### Notes for HyperShift

- Custom agents (ADK, Claude SDK) need Shipwright builds on OCP:
  ```bash
  kubectl apply -f deployments/openshell/agents/adk-agent/shipwright-build.yaml
  kubectl apply -f deployments/openshell/agents/claude-sdk-agent/shipwright-build.yaml
  ```
- The weather agent uses a public ghcr.io image and works without builds
- The gateway needs `anyuid` SCC (handled by the fulltest script)

## What's Deployed

| Component | Namespace | Image |
|-----------|-----------|-------|
| OpenShell Gateway | `openshell-system` | `ghcr.io/nvidia/openshell/gateway:latest` |
| Sandbox CRD Controller | `agent-sandbox-system` | upstream |
| Weather Agent | `team1` | `ghcr.io/kagenti/agent-examples/weather_service:latest` |
| Weather Agent (supervised) | `team1` | Local build (supervisor + weather) |
| ADK Agent | `team1` | Local build (Kind) or Shipwright (OCP) |
| Claude SDK Agent | `team1` | Local build (Kind) or Shipwright (OCP) |

## E2E Tests

```bash
# Run all tests (from main repo root)
OPENSHELL_LLM_AVAILABLE=true uv run pytest \
  .worktrees/stream1-sandbox-agent/kagenti/tests/e2e/openshell/ -v --timeout=120

# Run specific test file
uv run pytest .worktrees/stream1-sandbox-agent/kagenti/tests/e2e/openshell/test_weather_agent.py -v

# Run with Kind cluster kubeconfig
KUBECONFIG=~/.kube/config uv run pytest \
  .worktrees/stream1-sandbox-agent/kagenti/tests/e2e/openshell/ -v
```

### Test Categories

| Category | Tests | LLM Needed? |
|----------|-------|-------------|
| Platform health | 8 | No |
| Weather agent A2A | 4 | No |
| ADK agent (hello + PR review) | 3 | PR review: Yes |
| Claude SDK agent (hello + code review + code gen) | 4 | Code review/gen: Yes |
| Credential isolation | 12 | No |
| Sandbox lifecycle (CRD CRUD) | 4 | No |
| Built-in sandboxes | 5 | Partial |
| Skill discovery | 5 | No |
| Agent skills (PR review, code review) | 3 | Yes |

## Flags

| Flag | Description |
|------|-------------|
| `--platform kind\|ocp` | Auto-detected, or force platform |
| `--skip-cluster-create` | Reuse existing cluster |
| `--skip-cluster-destroy` | Keep cluster for debugging |
| `--skip-install` | Skip Kagenti platform install |
| `--skip-agents` | Skip agent deployment |
| `--skip-test` | Skip E2E tests |
| `--cluster-name NAME` | Kind cluster name (default: kagenti) |
| `[suffix]` | HyperShift cluster suffix (positional) |

## Architecture

See [docs/agentic-runtime/openshell-integration.md](../../docs/agentic-runtime/openshell-integration.md)

