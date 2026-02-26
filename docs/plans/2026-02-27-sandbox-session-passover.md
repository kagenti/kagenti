# Agent Sandbox — Session Passover (2026-02-27)

> **For next session:** Focus on (1) multi-user shared sessions with UI tests, (2) tool call display rendering, (3) test every agent deployment style, (4) clone public repos in sandbox (kagenti/kagenti as test case). See detailed next steps below.

## Session Stats (2026-02-26 full day)

- **Duration:** ~6 hours wall time
- **Cost:** ~$150 (Opus 4.6 orchestrator + 4 parallel subagents + Haiku analysis)
- **Code:** ~6,000 lines added across kagenti + agent-examples
- **Commits:** 22 on feat/sandbox-agent (kagenti), 3 on feat/sandbox-agent (agent-examples)
- **Tests:** 19/19 Playwright UI tests on sbox, 18/18 on sbox1
- **Subagents:** 5 parallel Opus 4.6 subagents for infrastructure

## What's Built and Deployed

### Backend APIs (all deployed on sbox + sbox1)

| Endpoint | Purpose |
|----------|---------|
| `GET /sandbox/{ns}/sessions` | List sessions (deduplicated by context_id) |
| `GET /sandbox/{ns}/sessions/{ctx}` | Session detail (latest task per context_id) |
| `GET /sandbox/{ns}/sessions/{ctx}/history` | Paginated history with parsed tool calls |
| `PUT /sandbox/{ns}/sessions/{ctx}/rename` | Custom session title |
| `DELETE /sandbox/{ns}/sessions/{ctx}` | Delete session |
| `POST /sandbox/{ns}/sessions/{ctx}/kill` | Cancel running session |
| `POST /sandbox/{ns}/cleanup` | TTL cleanup for stuck submitted tasks |
| `POST /sandbox/{ns}/chat` | Non-streaming chat proxy |
| `POST /sandbox/{ns}/chat/stream` | SSE streaming chat proxy |
| `POST /sandbox/{ns}/create` | Deploy sandbox agent via K8s API |
| `GET /sandbox/{ns}/agents` | List sandbox deployments with session counts |

### UI Pages

| Page | Route | What |
|------|-------|------|
| Sessions | `/sandbox` | Chat with agents, session sidebar, history, tool calls |
| Sessions Table | `/sandbox/sessions` | Full table with search, pagination, kill/delete |
| Import Wizard | `/sandbox/create` | 6-step wizard for deploying agents |
| Sandboxes | `/sandboxes` | Deployed agents with session lists |

### Playwright Tests (19 total)

| Suite | Tests |
|-------|-------|
| sandbox.spec.ts | 12: health check, nav, chat, sidebar, table, config, agents panel, import button, root toggle |
| sandbox-walkthrough.spec.ts | 1: full user journey |
| sandbox-debug.spec.ts | 1: session switching + history |
| sandbox-create-walkthrough.spec.ts | 6: Basic/Hardened/Enterprise agent + navigation |

### Agent Infrastructure

| Feature | Repo | Status |
|---------|------|--------|
| Per-context_id concurrency locks | agent-examples | Deployed |
| Shell interpreter bypass detection | agent-examples | Deployed |
| TOFU verification on startup | agent-examples | Deployed |
| Sources policy in interpreter bypass | agent-examples | Deployed |
| HITL interrupt() design | agent-examples | Documented |
| HPA autoscaling (1-5 replicas) | kagenti | Manifest created |

## Open Design Questions (Need Brainstorming)

### 1. Multi-User Shared Sessions

**Current:** Each user gets their own `context_id`. No session sharing.

**Needed:** Multiple users can join the same session (like a shared terminal):
- User A starts a session with sandbox-legion
- User B joins the same session, sees the conversation history
- Both can send messages — LangGraph serializes via checkpointer
- UI shows who sent each message (user identity in parts metadata)

**Design questions:**
- How does User B discover/join User A's session? (share link? team session list?)
- Should messages show which user sent them? (role: "user" needs user ID)
- What RBAC controls session joining? (team membership? explicit invite?)
- Does the shared session share the workspace too? (same `/workspace/ctx-xxx/`)

**A2A protocol support:** contextId already supports this — multiple `message/send` requests with the same contextId go to the same LangGraph thread. The challenge is UI/UX, not protocol.

### 2. Personal vs Team Sessions

| Type | Who sees it | Workspace | Use case |
|------|------------|-----------|----------|
| Personal | Creator only | Per-user dir | Individual dev work |
| Team | Team members | Shared dir | Collaborative debugging |
| Public | Everyone | Read-only | Demo/reference |

**Implementation:** Add `visibility` field to task metadata: `personal` (default), `team`, `public`. Sidebar filters by visibility + user identity.

### 3. Agent Deployment Styles to Test

Each deployment style uses different sandbox configurations. We need E2E tests for each:

| Style | Config | What to test |
|-------|--------|------------|
| Basic (stateless) | No persistence, shared pod | Chat works, responses not persisted after restart |
| Legion (persistent) | PostgreSQL, shared pod | Chat works, history persists across pod restarts |
| Hardened | Landlock + proxy + non-root | Tool calls work within sandbox restrictions |
| Pod-per-session | Each session gets own pod | Isolation between sessions, resource cleanup |
| With git clone | Public repo, no auth | Clone kagenti/kagenti, read files, answer questions |
| With GitHub PAT | Authenticated, scoped repos | Clone private repo, push branch, create PR |

**Test plan:** The import wizard deploys each style, then a Playwright test sends specific commands to verify the sandbox works:
- Basic: "Say hello" → get response
- Legion: "Say hello" → restart pod → reload → history exists
- Hardened: "cat /etc/passwd" → blocked by Landlock
- Git clone: "git clone https://github.com/kagenti/kagenti && ls kagenti/" → shows files
- GitHub PAT: "git clone https://github.com/Ladas/kagenti && git branch" → works with auth

### 4. Tool Call Display

**Current:** History endpoint returns parsed tool call data (`tool_call`, `tool_result`, `thinking`). Frontend has `ToolCallStep` component with expandable sections.

**Problem:** The regex parsing of graph event dumps is fragile. The text format is Python repr, not JSON. Complex tool arguments or outputs with special characters break the regex.

**Better approach:**
- Agent-side: structure the status update messages as JSON instead of Python repr
- Backend: parse JSON instead of regex
- Frontend: rich rendering with syntax highlighting

**Agent change needed in agent.py:**
```python
# Current (Python repr dump):
await task_updater.update_status(
    TaskState.working,
    new_agent_text_message(
        "\n".join(f"{key}: {str(value)[:256]}" for key, value in event.items())
    ),
)

# Proposed (structured JSON):
await task_updater.update_status(
    TaskState.working,
    new_agent_text_message(
        json.dumps({"event": key, "data": _serialize_event(value)})
    ),
)
```

### 5. Keycloak Multi-Persona

| User | Password | Role | Group | What they can do |
|------|----------|------|-------|-----------------|
| admin | (random) | kagenti-admin | all | Full access |
| dev-user | (random) | kagenti-viewer | team1-dev | Chat, view sessions |
| ns-admin | (random) | kagenti-operator | team1-admin | Chat, kill, delete, deploy |

**show-services.sh:** Print credentials using `kubectl get secret` command (not plaintext).

## Clusters

| Cluster | KUBECONFIG | Tests |
|---------|-----------|-------|
| sbox | ~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig | 19/19 pass |
| sbox1 | ~/clusters/hcp/kagenti-team-sbox1/auth/kubeconfig | 18/18 pass |

## Worktrees

| Repo | Worktree | Branch | Last Commit |
|------|----------|--------|-------------|
| kagenti | .worktrees/sandbox-agent | feat/sandbox-agent | `317fbd8f` |
| agent-examples | .worktrees/agent-examples | feat/sandbox-agent | `ec6fe43` |

## Next Session Tasks (Priority Order)

### Phase 1: Multi-User Sessions (High Priority)
1. Add `user_id` to A2A message metadata (from Keycloak token)
2. "Share session" button → generates shareable link with context_id
3. Session sidebar shows user avatars for multi-user sessions
4. Playwright test: User A sends message, User B (different login) sees it

### Phase 2: Tool Call Display Fix (High Priority)
1. Change agent to emit structured JSON status updates
2. Backend parses JSON instead of regex
3. Frontend renders rich tool call cards with syntax highlighting
4. Test: send "ls" command, verify tool_call + tool_result render correctly

### Phase 3: Agent Deployment Style Tests
1. Deploy Basic agent via wizard → test chat
2. Deploy Hardened agent → test Landlock blocks
3. Deploy with git clone → clone kagenti/kagenti (public, no token), read CLAUDE.md
4. Each as a separate Playwright test scenario

### Phase 4: Keycloak Personas
1. Random admin password generation
2. Create dev-user + ns-admin test users
3. Multi-persona Playwright tests (dev can chat but not kill, ns-admin can kill)

### Phase 5: Remaining Infrastructure
1. HITL interrupt() implementation (graph restructuring)
2. Per-context Landlock isolation (fork/exec per session)
3. Keycloak redirect_uri fix (preserve SPA path)
4. SSE streaming verification on live cluster

## Startup Command

```bash
cd /Users/ladas/Projects/OCTO/kagenti/kagenti
export MANAGED_BY_TAG=kagenti-team
source .env.kagenti-team
export KUBECONFIG=~/clusters/hcp/kagenti-team-sbox/auth/kubeconfig
export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"
claude
```

Then say:

> Read docs/plans/2026-02-27-sandbox-session-passover.md. Continue: (1) fix tool call rendering with structured JSON events, (2) add multi-user shared session support, (3) test agent deployment styles (basic, hardened, git clone of kagenti/kagenti), (4) Keycloak multi-persona setup. Use /tdd:hypershift on sbox and sbox1.
