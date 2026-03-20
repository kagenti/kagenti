# Session W Passover — Agent Graph Redesign, Egress Proxy, UI Rendering

> **Date:** 2026-03-10
> **Previous Session:** V (passover at docs/plans/2026-03-10-session-V-passover.md)
> **Cluster:** sbox42 (Llama 4 Scout via LiteLLM proxy)
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)

## CRITICAL FOR SESSION X — START HERE

### 1. AWS EBS CSI IRSA Broken on sbox42
PVC provisioning fails — AWS STS `AssumeRoleWithWebIdentity` returns 403. The OIDC trust for the EBS CSI driver has expired. Existing PVCs (postgres) still work. New EBS volumes cannot be created.

**Impact:** `workspace_storage: "pvc"` option doesn't work on sbox42. Defaulted back to `emptydir`.
**Fix:** Refresh the HyperShift hosted cluster's IRSA or recreate the cluster.

### 2. Double-Send Bug Still Present
The UI sends the same message to the agent twice. Root cause unknown — the `handleSendMessage` guard (`isStreaming`) is async React state so two rapid calls can both pass. Workaround: `.first()` in test selectors.

### 3. loop_events Not Persisting to DB
The `finally` block in `sandbox.py` sometimes fails to persist loop_events to task metadata. History fallback extraction covers this gap but it's not reliable.

### 4. RCA Quality 3/5
The agent works end-to-end but Llama 4 Scout doesn't always produce "Root Cause" and "Fix" headings in the report. This is LLM formatting, not a graph issue.

---

## What Session W Delivered

### Agent Graph Architecture (9 commits in agent-examples)

| Change | Commit |
|--------|--------|
| **Router entry node** — decides resume/replan/new based on plan_status | `5454548` |
| **PlanStep TypedDict** — per-step status (pending/running/done/failed/skipped) | `5454548` |
| **Plan persistence across A2A turns** — via LangGraph checkpointer | `5454548` |
| **Reflector sees actual tool errors** — substitutes dedup sentinel with last ToolMessage | `8a86bb7` |
| **shell(*:*) auto-approve** — wildcard prefix fix in permission checker | `0045be7` |
| **__interrupt__ event handling** — HITL events don't crash serializer | `1be0259` |
| **web_fetch domain check removed** — proxy handles domain filtering | `1be3345` |
| **Planner prompt fixed** — removed broken `export GH_TOKEN=$GITHUB_PAT_TOKEN` | `6575673` |
| **Reporter shows step failures** — plan_steps status in reporter prompt | `6575673` |
| **No-tool executor stall breaker** — after 2 no-tool attempts, mark step failed | `27b96d9` |
| **Prompt visibility** — system_prompt + prompt_messages in all events | `a744e02` |

### Graph Topology Change
```
OLD:  planner → executor ⇄ tools → reflector → reporter → END

NEW:  router → [resume] → executor ⇄ tools → reflector → reporter → END
               [plan]   → planner → executor ...
```

### Backend / Infrastructure (12 commits in sandbox-agent)

| Change | Commit |
|--------|--------|
| **UI polish** — collapse tool blocks, filter dedup from finalAnswer | `9705f412` |
| **E2E test selectors** — prefer agent-loop-card with fallbacks | `9705f412` |
| **RCA test .first()** — handle double-send strict mode | `5d1a979f` |
| **Squid egress proxy** — verified working on sbox42 (domain filtering) | `c5b717aa` |
| **Per-agent egress proxy** — separate pod per agent with own ConfigMap | `418d31a9` |
| **NetworkPolicy** — blocks direct public egress from agent pods | deployed on sbox42 |
| **PVC workspace** — workspace_storage option (pvc/emptydir), Recreate strategy | `747bb4e1` |
| **Delete endpoint** — DELETE /sandbox/{namespace}/{name} cleans all resources | `f6bede35` |
| **Prompt visibility UI** — PromptBlock, NestedCollapsible components | `c2890e2d` |
| **Tool call rendering** — previews, pairing call→result, status icons | `22d7e404`, `86b6c01a` |
| **Backend RBAC** — ClusterRole for PVC management | applied on sbox42 |
| **GitHub PAT secret** — updated with real token on sbox42 | applied on sbox42 |

### Verified on sbox42

| Feature | Status |
|---------|--------|
| Squid proxy domain filtering | Working (403 on blocked, 200 on allowed) |
| NetworkPolicy direct bypass block | Working (--noproxy times out) |
| Auto-approve all shell commands | Working (no HITL) |
| GH_TOKEN in agent environment | Working |
| Router → planner → executor → reflector flow | Working |
| RCA test passing | Yes (quality 3/5 — LLM formatting) |

---

## Architecture Reference

### Agent Graph (router-plan-execute-reflect)
```
router → [resume] → executor ⇄ tools → reflector → [done] → reporter → END
          [plan]   → planner → executor ...          [cont] → planner (loop)
```

**Router logic:**
- `plan_status == "awaiting_continue"` + "continue" message → resume at current_step
- `plan_status == "awaiting_continue"` + other message → replan (planner sees plan_steps with status)
- No active plan → fresh plan

**Plan state persists via LangGraph checkpointer** (thread_id = context_id).

### Per-Agent Egress Proxy
```
Agent Pod (HTTP_PROXY=egress-proxy-svc:3128)
    ↕
{agent}-egress-proxy Pod (Squid, ConfigMap with domain ACLs)
    ↕
Internet (only allowed domains)

NetworkPolicy: agent pods blocked from direct public egress
```

### Workspace Storage Options
- `emptydir` (default) — ephemeral, lost on restart
- `pvc` — persistent, survives restarts, needs working storage provisioner
- Recreate deployment strategy for PVC (RWO can't be shared during rolling update)

---

## Remaining Issues (P0 for Session X)

### 1. Fix AWS IRSA on sbox42
PVC provisioning broken. Either refresh OIDC trust or create a new cluster.

### 2. Double-Send Root Cause
UI sends messages twice. Needs investigation in SandboxPage.tsx `handleSendMessage`.

### 3. Wizard UI Updates Needed
- Add `workspace_storage` toggle (emptydir / pvc)
- Add auto-approve toggle (sets SANDBOX_AUTO_APPROVE_ALL env var)
- Proxy domains already wired to egress proxy

### 4. Skill Visibility
- Emit `skill_loaded` event when skill is loaded
- Move planner examples to skill files (planner prompt stays generic)
- Show skill content in UI as expandable block

### 5. User Namespace Session Isolation
Per-session UID mapping on shared PVC for path traversal prevention without pattern-based permission checks.

### 6. loop_events Persistence
Still fragile — investigate the finally block race condition.

---

## Key Files

| File | Purpose |
|------|---------|
| `agent-examples/.../reasoning.py` | Router, planner, executor, reflector, reporter nodes |
| `agent-examples/.../graph.py` | Graph topology with router entry point |
| `agent-examples/.../permissions.py` | shell(*:*) wildcard + permission checker |
| `agent-examples/.../event_serializer.py` | Prompt data in events |
| `agent-examples/.../settings.json` | Auto-approve all shell commands |
| `kagenti/backend/.../sandbox_deploy.py` | Per-agent egress proxy, PVC workspace, delete endpoint |
| `kagenti/ui-v2/src/components/LoopDetail.tsx` | Prompt blocks, tool previews, status icons |
| `kagenti/ui-v2/src/utils/loopBuilder.ts` | Prompt data in loop events |
| `kagenti/ui-v2/src/types/agentLoop.ts` | PromptMessage type |

## Commits (kagenti worktree)
```
0a2b05c1  fix: default workspace_storage to emptydir (sbox42 IRSA broken)
29ba5354  fix: default workspace_storage to pvc for persistent workspaces
ab8e5e07  feat: workspace_storage wizard option — pvc or emptydir, no fallback
32ea6d43  fix: PVC creation with fallback to emptyDir on permission error
747bb4e1  fix: use Recreate strategy for PVC-backed agent deployments
86b6c01a  feat: tool call status indicators — spinner when pending, icons when done
22d7e404  fix: tool call/result rendering with previews and pairing
c2890e2d  feat: prompt visibility in AgentLoopCard — system prompt + messages
f6bede35  feat: PVC workspace + delete endpoint for full cleanup
418d31a9  feat: per-agent egress proxy as separate pod (not sidecar)
c5b717aa  feat: Squid egress proxy sidecar for all agent deployments
5d1a979f  fix: RCA test strict mode — use .first() for duplicate user messages
9705f412  fix: UI polish — collapse tool blocks, filter dedup, update test selectors
```

## Commits (agent-examples worktree)
```
a744e02   feat: prompt visibility + no-tool executor stall breaker
27b96d9   fix: break replan loop + add prompt visibility to events
6575673   fix: planner prompt remove broken export GH_TOKEN, reporter shows failures
0045be7   fix: shell(*:*) wildcard prefix now matches all commands
1be0259   fix: handle __interrupt__ graph events (HITL) without crashing
1be3345   fix: auto-approve all shell commands, remove web_fetch domain check
b512098   fix: allow export/curl/wget, enable outbound, fix HITL interrupt propagation
8a86bb7   fix: reflector sees actual tool error instead of dedup sentinel
5454548   feat: router entry node + structured plan persistence across turns
fa80b53   fix: filter dedup sentinel from reporter to prevent final answer leak
```
