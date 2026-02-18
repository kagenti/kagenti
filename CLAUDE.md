# CLAUDE.md - Kagenti Repository

## Project Overview

**Kagenti** is a cloud-native middleware platform for deploying and orchestrating AI agents. It provides framework-neutral infrastructure for running agents (LangGraph, CrewAI, AG2, etc.) with authentication, authorization, trusted identity, and scaling.

## Quick Start

```bash
# Deploy to Kind cluster
./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy

# Show service URLs
./.github/scripts/local-setup/show-services.sh

# Access UI at http://kagenti-ui.localtest.me:8080 (admin/admin)
```

## Repository Structure

```
kagenti/
├── kagenti/
│   ├── ui-v2/              # React frontend
│   ├── backend/            # FastAPI backend
│   ├── tests/e2e/          # E2E tests
│   └── examples/           # Example agents/tools
├── charts/                 # Helm charts
│   ├── kagenti/            # Main platform chart
│   └── kagenti-deps/       # Dependencies
├── deployments/
│   ├── ansible/            # Ansible installer (recommended)
│   └── envs/               # Environment values
├── .claude/skills/         # Claude Code skills
└── docs/                   # Documentation
```

## Key Commands

| Task | Command |
|------|---------|
| Deploy to Kind | `./.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy` |
| Deploy to OpenShift | `./deployments/ansible/run-install.sh --env ocp` |
| Run E2E tests | `uv run pytest kagenti/tests/e2e/ -v` |
| Run linter | `make lint` |
| Pre-commit | `pre-commit run --all-files` |

## Claude Code Skills

Skills in `.claude/skills/` provide guided workflows:

| Category | Skills (invoke with `Skill` tool) |
|----------|--------|
| Kubernetes | `k8s:health`, `k8s:pods`, `k8s:logs` |
| Clusters | `kind:cluster`, `hypershift:cluster` |
| Auth | `auth:keycloak-confidential-client`, `auth:otel-oauth2-exporter` |
| Istio | `istio:ambient-waypoint` |
| OpenShift | `openshift:debug`, `openshift:routes`, `openshift:trusted-ca-bundle` |
| Testing | `tdd:hypershift`, `testing:kubectl-debugging`, `k8s:live-debugging` |
| Git | `git:worktree` |

See [docs/skills/](docs/skills/README.md) for skill index and [docs/ai-ops/](docs/ai-ops/README.md) for workflows.

## HyperShift Cluster Access

HyperShift hosted cluster kubeconfigs are stored at:

```
~/clusters/hcp/<MANAGED_BY_TAG>-<cluster-suffix>/auth/kubeconfig
```

Examples:
- `~/clusters/hcp/kagenti-hypershift-custom-uitst/auth/kubeconfig`
- `~/clusters/hcp/kagenti-hypershift-custom-mlflow/auth/kubeconfig`

Use with kubectl/oc commands (auto-approved in settings.json):

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-uitst/auth/kubeconfig
kubectl get pods -n kagenti-system
```

The management cluster kubeconfig is separate (in `~/.kube/`).

## Worktree Workflow

Run worktree code from main repo (keeps credentials in one place):

```bash
# Stay in main repo
# For HyperShift: source .env.<MANAGED_BY_TAG> (see .github/scripts/local-setup/README.md)
source .env.kagenti-hypershift-custom

# Run worktree's test script
.worktrees/my-feature/.github/scripts/local-setup/kind-full-test.sh --skip-cluster-destroy
```

## Key Technologies

| Component | Purpose |
|-----------|---------|
| Istio Ambient | Service mesh (mTLS) |
| Keycloak | OAuth/OIDC |
| SPIRE | Workload identity (SPIFFE) |
| Shipwright | Container builds |
| Phoenix | LLM observability |

## Namespaces

- `kagenti-system` - Platform components
- `keycloak` - Identity provider
- `team1`, `team2` - Agent namespaces

## Protocols

- **A2A**: Agent-to-Agent (Google) - `/.well-known/agent-card.json`
- **MCP**: Model Context Protocol (Anthropic) - Tool integration

## Context Budget (MANDATORY)

**Context window pollution is the #1 cost driver.** Build output, kubectl responses, and
test results dumped into conversation history get re-read on every subsequent turn,
causing exponential cost growth in long sessions. Follow these rules to minimize context usage.

### Rule 1: Redirect command output to files

Any command that produces more than ~5 lines MUST redirect to a session-scoped log file:

```bash
# Set a session-scoped log directory (use worktree/cluster name to avoid collisions)
export LOG_DIR=/tmp/kagenti/tdd/$WORKTREE   # TDD sessions
export LOG_DIR=/tmp/kagenti/rca/$WORKTREE   # RCA sessions
export LOG_DIR=/tmp/kagenti/k8s/$CLUSTER    # K8s debugging
mkdir -p $LOG_DIR

# Pattern: redirect output, return only exit code
command > $LOG_DIR/descriptive-name.log 2>&1; echo "EXIT:$?"
# or
command > $LOG_DIR/name.log 2>&1 && echo "OK" || echo "FAIL (see $LOG_DIR/name.log)"
```

### Rule 2: Analyze logs in subagents

**NEVER read large log files in the main context.** Use subagents:

```
Task(subagent_type='Explore'):
  "Use Grep with context (-C 3) on $LOG_DIR/test-run.log to find FAILED|ERROR.
   Do NOT read the whole file. Return: first error, test name, and 2-3 lines of context."
```

Use subagents for BOTH failure analysis AND success verification (e.g., "verify traces appear in the log").

### Rule 3: Small output is OK inline

These are fine without redirection (produce <5 lines):
- `git status`, `git branch`, `git log --oneline -5`
- `kubectl get nodes` (cluster health check)
- `gh pr checks <number>` (CI status table)
- `curl -s url | jq '.field'` (single JSON field)
- `echo "EXIT:$?"` (exit codes)

### What this prevents

| Pattern | Context cost | Fix |
|---------|-------------|-----|
| `kubectl get pods -A` | 50-200 lines per call | Redirect to file |
| `kubectl logs ... --tail=100` | 100 lines per call | Redirect to file |
| `gh run view --log-failed` | 1000+ lines | Redirect + subagent |
| `pytest -v` | 200+ lines | Redirect + subagent |
| `helm template` | 500+ lines | Redirect + subagent |
| `oc start-build --follow` | 100+ lines | Redirect + subagent |

## Code Style

- Python 3.11+, `uv` package manager
- Sign-off required: `git commit -s`
- Pre-commit hooks: `pre-commit install`

## Claude Code Task Lists

Task lists can be shared or session-specific:

### Shared task list (collaboration/handoff)

```bash
CLAUDE_CODE_TASK_LIST_ID=kagenti-shared claude
```

All sessions using the same ID see the same tasks.

### Separate task lists (parallel work)

```bash
# Each session gets its own isolated task list
CLAUDE_CODE_TASK_LIST_ID=hcp-cleanup claude    # Terminal 1
CLAUDE_CODE_TASK_LIST_ID=phoenix-oauth claude  # Terminal 2
```

### Default behavior

Without the env var, each session uses an ephemeral task list that doesn't
persist.

## Documentation

- [Installation Guide](docs/install.md)
- [Components](docs/components.md)
- [AI Ops / Claude Code](docs/ai-ops/README.md)
- [Demos](docs/demos/README.md)
- [Skills and Patterns](docs/skills/README.md)
- [Keycloak Patterns](docs/auth/keycloak-patterns.md)
