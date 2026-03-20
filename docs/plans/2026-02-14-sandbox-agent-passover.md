# Sandbox Agent - Session Passover

> **For next session:** Use `/tdd:hypershift` on the `lpvc` cluster to continue this work.

## Current State

### What's Built and Running

- **Sandbox agent** deployed on `kagenti-hypershift-custom-lpvc` HyperShift cluster
- **Agent code**: `agent-examples` repo, branch `feat/sandbox-agent`
- **Draft PR**: https://github.com/kagenti/agent-examples/pull/126
- **GitHub Issue**: https://github.com/kagenti/kagenti/issues/708
- **Design docs**: `docs/plans/2026-02-14-agent-context-isolation-design.md` and `*-impl.md`

### Working Features

- Shell execution (grep, sed, ls, python, pip install, git clone, bash scripts)
- File read/write with path-traversal prevention
- Per-context workspace directories on emptyDir volume
- `settings.json` three-tier permission control (allow/deny/HITL)
- `sources.json` capability declaration
- `web_fetch` tool with domain allowlist (github.com, api.github.com, pypi.org, etc.)
- A2A agent card and streaming responses
- 68 unit tests + 4 E2E tests passing

### Known Bug: No Multi-Turn Memory

**Root cause:** The graph is compiled with `checkpointer=None` in `agent.py`. Without a checkpointer, LangGraph discards conversation state between invocations, even when the same `context_id`/`thread_id` is used.

**Fix needed:** Add `MemorySaver` (single-pod) or `AsyncPostgresSaver` (multi-pod) to `SandboxAgentExecutor.__init__` and pass it to `build_graph()`.

**Quick fix (MemorySaver):**
```python
# In SandboxAgentExecutor.__init__():
from langgraph.checkpoint.memory import MemorySaver
self._checkpointer = MemorySaver()

# In execute(), pass to build_graph:
graph = build_graph(
    workspace_path=workspace_path,
    permission_checker=self._permission_checker,
    sources_config=self._sources_config,
    checkpointer=self._checkpointer,  # ADD THIS
)
```

Note: The graph must NOT be rebuilt on every request when using a checkpointer — or use a shared checkpointer instance across calls. Currently `build_graph` is called per-request in `execute()`. Either cache the graph or extract the checkpointer to be shared.

**Better fix:** Build the graph once in `__init__` with a checkpointer, reuse it across requests:
```python
class SandboxAgentExecutor(AgentExecutor):
    def __init__(self):
        ...
        self._checkpointer = MemorySaver()
        # Build graph once, reuse across requests
        self._graph = build_graph(
            workspace_path=config.workspace_root,
            permission_checker=self._permission_checker,
            sources_config=self._sources_config,
            checkpointer=self._checkpointer,
        )
```

But this means workspace_path is fixed at init time, not per-context. The workspace_path is used by the file tools, so they'd need to be context-aware. This needs a small refactor: either make the tools resolve workspace_path at call time from the state, or build the graph per-context but share the checkpointer.

**Recommended approach:** Share the checkpointer, build graph per-context (current pattern), just pass the shared checkpointer:
```python
class SandboxAgentExecutor(AgentExecutor):
    def __init__(self):
        ...
        self._checkpointer = MemorySaver()

    async def execute(self, context, event_queue):
        ...
        graph = build_graph(
            workspace_path=workspace_path,
            ...
            checkpointer=self._checkpointer,  # Shared across calls
        )
        # thread_id config already set:
        graph_config = {"configurable": {"thread_id": context_id}}
```

### E2E Test to Add

```python
@pytest.mark.asyncio
async def test_multi_turn_memory(self, test_session_id):
    """Verify agent remembers context across turns."""
    agent_url = os.getenv("SANDBOX_AGENT_URL", "...")
    client, _ = await _connect_to_agent(agent_url)
    context_id = f"memory-{test_session_id}"

    # Turn 1: Tell the agent a name
    msg1 = A2AMessage(
        role="user",
        parts=[TextPart(text="My name is Bob Beep")],
        messageId=uuid4().hex,
        contextId=context_id,
    )
    response1, _ = await _extract_response(client, msg1)
    assert response1, "Turn 1: No response"

    # Turn 2: Ask for the name back
    msg2 = A2AMessage(
        role="user",
        parts=[TextPart(text="What is my name?")],
        messageId=uuid4().hex,
        contextId=context_id,
    )
    response2, _ = await _extract_response(client, msg2)
    assert "Bob Beep" in response2, (
        f"Agent didn't remember the name.\n"
        f"Expected 'Bob Beep' in response.\n"
        f"Response: {response2}"
    )
```

## Cluster & Environment

| Item | Value |
|------|-------|
| Cluster | `kagenti-hypershift-custom-lpvc` |
| Kubeconfig | `~/clusters/hcp/kagenti-hypershift-custom-lpvc/auth/kubeconfig` |
| Agent namespace | `team1` |
| Agent deployment | `sandbox-agent` |
| Agent service | `sandbox-agent:8080` (maps to container 8000) |
| LLM | OpenAI `gpt-4o-mini` via `openai-secret` in team1 |
| Image registry | `image-registry.openshift-image-registry.svc:5000/team1/sandbox-agent:v0.0.1` |
| Worktree | `.worktrees/agent-examples` on branch `feat/sandbox-agent` |

### Key Commands

```bash
# Source env
export MANAGED_BY_TAG=${MANAGED_BY_TAG:-kagenti-hypershift-custom}
source .env.${MANAGED_BY_TAG}
export KUBECONFIG=~/clusters/hcp/${MANAGED_BY_TAG}-lpvc/auth/kubeconfig

# Check agent
kubectl get pods -n team1 -l app.kubernetes.io/name=sandbox-agent
kubectl logs -n team1 deployment/sandbox-agent --tail=20

# Rebuild after code changes
cd .worktrees/agent-examples
git add -A && git commit -s -m "fix: ..." && git push origin feat/sandbox-agent
# Back to main repo:
KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-lpvc/auth/kubeconfig \
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
KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-lpvc/auth/kubeconfig \
  kubectl rollout restart deployment/sandbox-agent -n team1

# Port-forward for local testing
KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-lpvc/auth/kubeconfig \
  kubectl port-forward -n team1 svc/sandbox-agent 8001:8080

# Run E2E tests
SANDBOX_AGENT_URL=http://localhost:8001 \
  KAGENTI_CONFIG_FILE=deployments/envs/ocp_values.yaml \
  uv run pytest kagenti/tests/e2e/common/test_sandbox_agent.py -v --timeout=120

# Run unit tests
cd .worktrees/agent-examples/a2a/sandbox_agent && uv run pytest tests/ -v
```

## Tasks for Next Session

1. **Fix multi-turn memory** — add `MemorySaver` checkpointer (see fix above)
2. **Add E2E memory test** — "My name is Bob Beep" / "What is my name?" (see test above)
3. **Rebuild and deploy** — push, Shipwright build, rollout restart
4. **Verify E2E tests pass** — all 5 tests (4 existing + 1 new memory test)
5. **Optional: wire PostgresSaver** — for multi-pod memory persistence (needs PG connection string)

## File Map

```
.worktrees/agent-examples/a2a/sandbox_agent/
├── Dockerfile
├── pyproject.toml
├── settings.json          # allow/deny/HITL rules
├── sources.json           # allowed domains, registries, remotes
├── src/sandbox_agent/
│   ├── __init__.py
│   ├── agent.py           # A2A server, SandboxAgentExecutor ← FIX HERE
│   ├── configuration.py   # Pydantic settings
│   ├── executor.py        # SandboxExecutor, HitlRequired
│   ├── graph.py           # LangGraph graph, shell/file/web_fetch tools
│   ├── permissions.py     # PermissionChecker (allow/deny/HITL)
│   ├── sources.py         # SourcesConfig (domains, packages, limits)
│   └── workspace.py       # WorkspaceManager (per-context dirs)
├── tests/
│   ├── test_executor.py
│   ├── test_graph.py
│   ├── test_permissions.py
│   ├── test_sources.py
│   └── test_workspace.py
└── uv.lock

kagenti/kagenti/  (main repo)
├── kagenti/tests/e2e/common/test_sandbox_agent.py  # E2E tests
├── kagenti/examples/agents/sandbox_agent_*.yaml    # K8s manifests
└── docs/plans/2026-02-14-agent-context-isolation-*  # Design docs
```
