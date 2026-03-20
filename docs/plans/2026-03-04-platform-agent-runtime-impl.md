# Platform Agent Runtime — Implementation Plan (Session N)

> **Date:** 2026-03-04
> **Session:** N (Platform Agent Runtime)
> **Clusters:** sandbox42 (dev), sandbox44 (clean E2E)
> **Worktree:** New worktree based on `feat/sandbox-agent` (from `.worktrees/sandbox-agent/`)
> **Branch:** `feat/platform-agent-runtime` (new, based on `feat/sandbox-agent`)
> **Cherry-pick to:** `.worktrees/sandbox-agent/` (`feat/sandbox-agent`) when done
> **Design Doc:** `docs/plans/2026-03-04-platform-agent-runtime-design.md` (in worktree)
> **Depends On:** Session G findings (Llama 4 Scout 10/10, 192/196 tests)

---

## Goal

Validate the **platform base image pattern** with two agent frameworks:
1. **Legion** (LangGraph) — existing, extracted to platform base
2. **OpenCode** — new, A2A wrapper over `opencode serve`

Both must pass the existing Playwright test suite on a clean cluster deploy.

## Architecture

```
kagenti-agent-base:latest (platform-owned)
├── entrypoint.py          # Loads AGENT_MODULE, wires platform services
├── workspace_manager.py   # Per-context /workspace/{context_id}/
├── permission_checker.py  # allow/deny/HITL three-tier rules
├── skills_loader.py       # CLAUDE.md + .claude/skills/ + MCP discovery
├── tofu.py                # SHA-256 config integrity
├── a2a-sdk                # A2A server, task store
└── OTEL instrumentation   # Phoenix, MLflow

sandbox-legion:latest (FROM kagenti-agent-base)
├── AGENT_MODULE=sandbox_agent.graph
├── graph.py               # LangGraph plan-execute-reflect
├── reasoning.py           # Planner, executor, reflector, reporter
├── budget.py              # Iteration/token limits
└── tools (shell, file, web, explore, delegate)

opencode-agent:latest (FROM kagenti-agent-base)
├── AGENT_MODULE=opencode_agent.wrapper
├── opencode_wrapper.py    # A2A ↔ OpenCode HTTP adapter (~200 lines)
└── opencode CLI binary    # Installed via curl
```

### Plugin Contract

```python
# Every agent module MUST export:
def build_executor(
    workspace_manager: WorkspaceManager,
    permissions_checker: PermissionChecker,
    skills_loader: SkillsLoader,
    sources_config: SourcesConfig,
) -> AgentExecutor:
    """Return an A2A AgentExecutor."""

def get_agent_card(host: str, port: int) -> AgentCard:
    """Return the agent's A2A card."""
```

---

## Phase 1: Platform Base Image

**Goal:** Create `kagenti-agent-base` image with entrypoint.py + platform services.

### Files to Create

```
deployments/sandbox/platform_base/
├── Dockerfile.base
├── entrypoint.py
├── workspace_manager.py    # Extract from agent-examples
├── permission_checker.py   # Extract from agent-examples
├── skills_loader.py        # Already exists in deployments/sandbox/
├── tofu.py                 # Already exists in deployments/sandbox/
├── sources_config.py       # Extract from agent-examples
├── requirements.txt
└── tests/
    ├── test_entrypoint.py
    └── test_workspace_manager.py
```

### entrypoint.py (core)

```python
import importlib, os, uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler

module_name = os.environ["AGENT_MODULE"]
agent_module = importlib.import_module(module_name)

# Wire platform services
executor = agent_module.build_executor(
    workspace_manager=workspace_manager,
    permissions_checker=permissions_checker,
    skills_loader=skills_loader,
    sources_config=sources_config,
)

server = A2AStarletteApplication(
    agent_card=agent_module.get_agent_card(host, port),
    http_handler=DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    ),
)
uvicorn.run(server.build(), host="0.0.0.0", port=8000)
```

### Acceptance Criteria
- `entrypoint.py` loads AGENT_MODULE dynamically
- Unit tests pass for plugin loading, workspace creation, permission checking
- Docker image builds successfully

---

## Phase 2: Legion on Platform Base (sandbox42)

**Goal:** Sandbox Legion deploys FROM base image, passes 192/196 Playwright tests.

### Files to Create

```
deployments/sandbox/agents/legion/
├── Dockerfile              # FROM kagenti-agent-base
├── graph.py                # Extracted from agent-examples
├── reasoning.py            # Extracted from agent-examples
├── budget.py               # Extracted from agent-examples
├── executor.py             # Extracted from agent-examples
├── permissions.py          # Extracted (wraps platform permission_checker)
├── workspace.py            # Extracted (wraps platform workspace_manager)
├── event_serializer.py     # Extracted from agent-examples
├── subagents.py            # Extracted from agent-examples
├── configuration.py        # Extracted from agent-examples
├── settings.json           # Permission rules
├── sources.json            # Runtime policy
└── pyproject.toml
```

### Deployment
- Build image on sandbox42 via Shipwright
- Deploy as `sandbox-legion-platform` (new name, doesn't replace existing)
- Point existing Playwright tests at the new agent
- Target: 192/196 pass (matching Session G baseline)

---

## Phase 3: OpenCode on Platform Base (sandbox42)

**Goal:** OpenCode wrapped as A2A agent, deployed alongside Legion.

### Files to Create

```
deployments/sandbox/agents/opencode/
├── Dockerfile              # FROM kagenti-agent-base + opencode binary
├── opencode_wrapper.py     # ~200 lines A2A ↔ OpenCode HTTP
├── pyproject.toml
└── tests/
    └── test_wrapper.py
```

### opencode_wrapper.py (core pattern)

```python
class OpenCodeExecutor(AgentExecutor):
    async def execute(self, context, event_queue):
        # 1. Start opencode serve subprocess (if not running)
        # 2. Health check localhost:19876
        # 3. POST /sessions {prompt} to opencode
        # 4. Stream response → A2A events
        # 5. Return TaskState.completed
```

### Deployment
- Build image on sandbox42
- Deploy as `opencode-agent` in team1 namespace
- Run core Playwright tests (chat streaming, session management)

---

## Phase 4: Clean sandbox44 Redeploy + Full E2E

**Goal:** Prove the platform base pattern works on a fresh cluster.

### Steps
1. Clean redeploy of Kagenti on sandbox44
2. Deploy both agents (Legion + OpenCode) FROM platform base
3. Run full Playwright suite
4. Generate feature parity matrix

### Feature Parity Matrix

| Feature | Test File | Legion | OpenCode |
|---------|-----------|:------:|:--------:|
| A2A agent card | agent-catalog | ✓ | ✓ |
| Chat streaming | sandbox-sessions | ✓ | ✓ |
| Tool execution | sandbox-walkthrough | ✓ | ? |
| File browser | sandbox-file-browser | ✓ | ? |
| Session persist | sandbox-sessions | ✓ | ✓ |
| HITL approval | (manual) | ✓ | N/A |
| Security tiers | sandbox-variants | ✓ | ✓ |

---

## Session N File Ownership

| Path | Ownership |
|------|-----------|
| `deployments/sandbox/platform_base/` | EXCLUSIVE (NEW) |
| `deployments/sandbox/agents/legion/` | EXCLUSIVE (NEW) |
| `deployments/sandbox/agents/opencode/` | EXCLUSIVE (NEW) |

### Does NOT Touch
- `.worktrees/sandbox-agent/` (Session L+2)
- `kagenti/ui-v2/` (Sessions L+2, M)
- `kagenti/backend/` (Sessions K, L+2)
- `deployments/sandbox/sandbox_profile.py` (Session F)
- `deployments/sandbox/sandbox_trigger.py` (Session F)
- Existing Playwright test files (acceptance criteria, read-only)

---

## Workflow: Worktree + Cherry-Pick

```
1. Create new worktree from feat/sandbox-agent:
   git worktree add .worktrees/platform-runtime feat/sandbox-agent -b feat/platform-agent-runtime

2. All Session N development happens in .worktrees/platform-runtime/

3. Deploy to sandbox42 from this worktree for testing

4. Once new tests pass on sandbox42:
   cd .worktrees/sandbox-agent
   git cherry-pick <commits from feat/platform-agent-runtime>
   → Test everything together on sandbox42 (existing 192+ tests + new platform tests)

5. Clean sandbox44 redeploy from .worktrees/sandbox-agent with all cherry-picked commits
```

**Key:** Session N never directly modifies `.worktrees/sandbox-agent/`. All changes flow
through cherry-pick after validation on the isolated branch.

---

## Risks

| Risk | Mitigation |
|------|-----------|
| Agent-examples code has implicit deps | Extract carefully, run unit tests first |
| OpenCode `opencode serve` may not be stable | Black-box wrapper with health check + retry |
| Shipwright builds may timeout | Use pre-built base image, only rebuild agent layer |
| Sandbox44 may have stale state | Clean redeploy script |
| OpenAI quota exhaustion | Use Llama 4 Scout via MaaS (confirmed 10/10 reliable) |
