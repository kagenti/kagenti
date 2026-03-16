# Sandbox Agent - Session Passover (2026-02-18)

> **For next session:** Commit the E2E test, optionally update the agent-examples PR, and handle remaining items.

## What Was Done This Session

### 1. Fixed Multi-Turn Memory Bug (DONE)

**Root cause:** `build_graph()` was called with `checkpointer=None` and `astream()` had no `thread_id` config, so LangGraph discarded conversation state between turns.

**Fix applied** in `.worktrees/agent-examples/a2a/sandbox_agent/src/sandbox_agent/agent.py`:
- Added `from langgraph.checkpoint.memory import MemorySaver`
- Created shared `self._checkpointer = MemorySaver()` in `__init__`
- Changed `checkpointer=None` to `checkpointer=self._checkpointer`
- Added `graph_config = {"configurable": {"thread_id": context_id or "stateless"}}` and passed it to `graph.astream()`

**Committed and pushed:** `04f7cd5` on `origin/feat/sandbox-agent` in the `agent-examples` repo.

### 2. Added "Bob Beep" E2E Memory Test (DONE, NOT COMMITTED)

Added `TestSandboxAgentMemory::test_multi_turn_memory` to the kagenti repo worktree at `.worktrees/sandbox-agent/kagenti/tests/e2e/common/test_sandbox_agent.py`.

The test is **not yet committed** -- it's a staged change in `.worktrees/sandbox-agent` (branch `feat/sandbox-agent`, based on `fix/hypershift-kubeconfig-portability`).

### 3. Built and Deployed (DONE)

- Triggered Shipwright BuildRun `sandbox-agent-run-9rn9b` -- succeeded
- Rolled out new `sandbox-agent` deployment on `kagenti-hypershift-custom-lpvc`
- New pod `sandbox-agent-d5569f6fd-jwn9k` running with the MemorySaver fix

### 4. All 5 E2E Tests Passed (VERIFIED)

```
test_agent_card                    PASSED
test_shell_ls                      PASSED
test_file_write_and_read           PASSED
test_multi_turn_file_persistence   PASSED
test_multi_turn_memory             PASSED  <-- NEW (Bob Beep)
```

## What Remains

### Must Do

1. **Commit the E2E test** in `.worktrees/sandbox-agent` (kagenti repo):
   ```bash
   cd .worktrees/sandbox-agent
   git add kagenti/tests/e2e/common/test_sandbox_agent.py
   git commit -s -m "test: add multi-turn memory E2E test (Bob Beep)"
   git push origin feat/sandbox-agent
   ```

2. **Create PR** for the kagenti repo E2E test (branch `feat/sandbox-agent` -> `main`).

3. **Update agent-examples PR** https://github.com/kagenti/agent-examples/pull/126 -- the MemorySaver fix is pushed but the PR description may need updating.

### Optional / Nice-to-Have

4. **Wire `AsyncPostgresSaver`** for multi-pod memory persistence (needs PG connection string). Current `MemorySaver` is in-memory only, so memory is lost on pod restart and doesn't work across replicas.

5. **Close issue** https://github.com/kagenti/kagenti/issues/708 once both PRs merge.

## Cluster & Environment

| Item | Value |
|------|-------|
| Cluster | `kagenti-hypershift-custom-lpvc` |
| Kubeconfig | `~/clusters/hcp/kagenti-hypershift-custom-lpvc/auth/kubeconfig` |
| Agent namespace | `team1` |
| Agent deployment | `sandbox-agent` (Running, 1/1) |
| Image | `image-registry.openshift-image-registry.svc:5000/team1/sandbox-agent:v0.0.1` |
| LLM | OpenAI `gpt-4o-mini` via `openai-secret` in team1 |

## Worktrees

| Worktree | Repo | Branch | State |
|----------|------|--------|-------|
| `.worktrees/agent-examples` | `ladas/agent-examples` | `feat/sandbox-agent` | Clean (pushed `04f7cd5`) |
| `.worktrees/sandbox-agent` | `kagenti/kagenti` | `feat/sandbox-agent` | **1 uncommitted file** (E2E test) |

## Key Commands

```bash
# Source env
export MANAGED_BY_TAG=${MANAGED_BY_TAG:-kagenti-hypershift-custom}
source .env.${MANAGED_BY_TAG}
export KUBECONFIG=~/clusters/hcp/${MANAGED_BY_TAG}-lpvc/auth/kubeconfig

# Check agent
kubectl get pods -n team1 -l app.kubernetes.io/name=sandbox-agent
kubectl logs -n team1 deployment/sandbox-agent --tail=20

# Port-forward for local testing
kubectl port-forward -n team1 svc/sandbox-agent 8001:8080

# Run E2E tests from worktree
cd .worktrees/sandbox-agent
SANDBOX_AGENT_URL=http://localhost:8001 \
  KAGENTI_CONFIG_FILE=deployments/envs/ocp_values.yaml \
  uv run pytest kagenti/tests/e2e/common/test_sandbox_agent.py -v --timeout=120

# Rebuild after code changes (in agent-examples worktree)
cd .worktrees/agent-examples
git add -A && git commit -s -m "fix: ..." && git push origin feat/sandbox-agent
# Then from main repo:
kubectl create -f - <<EOF
apiVersion: shipwright.io/v1beta1
kind: BuildRun
metadata:
  generateName: sandbox-agent-run-
  namespace: team1
spec:
  build:
    name: sandbox-agent
EOF
# Wait ~90s, then:
kubectl rollout restart deployment/sandbox-agent -n team1
```

## File Map

```
.worktrees/agent-examples/a2a/sandbox_agent/
├── src/sandbox_agent/
│   ├── agent.py           # FIXED: MemorySaver + thread_id config
│   └── graph.py           # Already accepted checkpointer param
└── ...

.worktrees/sandbox-agent/  (kagenti repo)
└── kagenti/tests/e2e/common/
    └── test_sandbox_agent.py  # ADDED: TestSandboxAgentMemory (uncommitted)
```

## Startup Command for Next Session

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export MANAGED_BY_TAG=${MANAGED_BY_TAG:-kagenti-hypershift-custom}
source .env.${MANAGED_BY_TAG}
export KUBECONFIG=~/clusters/hcp/${MANAGED_BY_TAG}-lpvc/auth/kubeconfig
claude
```

Then say:

> Read docs/plans/2026-02-18-sandbox-agent-passover.md and continue. Commit the E2E test in .worktrees/sandbox-agent, create the kagenti PR, and update the agent-examples PR #126. Use /superpowers:finishing-a-development-branch.
