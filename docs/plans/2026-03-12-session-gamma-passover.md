# Session Gamma Passover — Remaining Items from Sessions Y/Z/Alpha

> **Date:** 2026-03-12
> **From:** Session Alpha (which inherited from Z, Y, X, W, V...)
> **Cluster:** sbox42
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)

## Master Status — All Items from Sessions Y/Z

Items marked ✅ were completed by session Alpha or earlier.
Items marked 🔲 are still open. Grouped by priority.

### P0 Items

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | loop_events persistence | ✅ Y | Background task, immune to GeneratorExit |
| 2 | Budget enforcement (add_tokens) | ✅ Alpha | Added to all nodes. But replacing with LLM proxy (see design doc) |
| 3 | budget_update events not emitted | ✅ Alpha | `_budget_summary` added to SandboxState |
| 4 | budget_update event type mismatch | ✅ Alpha | loopBuilder matched `budget` but agent emits `budget_update` |
| 5 | Reporter leaks reflector text | ✅ Alpha | Removed single-step shortcut, always runs LLM |
| 6 | Stall detector force-terminates | ✅ Alpha | Removed entirely, reflector LLM decides |
| 7 | Infinite polling (token/tool inflation) | ✅ Alpha | Backend returns task_state, UI stops on terminal |
| 8 | Micro-reasoning tokens not counted | ✅ Alpha | LoopSummaryBar includes micro-reasoning |
| 9 | Step naming / numbering | 🔲 | `Step 29` should be `Step 2 [29]`. UI code exists but needs `plan_step` in events. Partially working — verify |
| 10 | Step numbering with replan suffix | 🔲 Z | `Step 2a [5]` for replanned steps. Track replan count per plan step |
| 11 | Reflector decides "done" too early | 🔲 Z | Llama 4 Scout sometimes says "done" after step 1 with 8 remaining. Need stronger prompt |
| 12 | Executor steps after reporter | 🔲 Z | Late events appear below "Final answer". Guard in loopBuilder |
| 13 | Page load jankiness | 🔲 Z | Blank flash on session switch. Show overlay instead of clearing state |
| 14 | Reflector gets no conversation context | ✅ Alpha analyzed | Prompt IS populated (prompt_messages > 0). Some early-termination paths had empty prompts — fixed with _system_prompt on force_done |
| 15 | Stats counter = 0 | ✅ Z | Fixed stats counting to include loops |
| 16 | Subscribe not firing on reload | ✅ Z | Subscribe + AbortController fixed |
| 17 | Token budget via LLM proxy | 🔲 Alpha designed | Design doc: `2026-03-12-llm-budget-proxy-design.md` — implement in Beta |
| 18 | DB multi-tenancy (schema per agent) | 🔲 Alpha designed | Design doc: `2026-03-12-db-multi-tenancy-design.md` — implement in Beta |

### P1 Items

| # | Item | Status | Notes |
|---|------|--------|-------|
| 19 | Budget controls in wizard | 🔲 Y | Wizard step exists but needs reconfigure support |
| 20 | RCA quality 3/5 → 5/5 | ✅ Alpha | RCA test passes with 5/5 sections |
| 21 | Message queue + cancel button | 🔲 Y | Queue messages during loop |
| 22 | Visualizations tab | 🔲 Y | Design doc at `2026-03-10-visualizations-design.md` |
| 23 | Kiali ambient mesh labels | 🔲 Y | LiteLLM + Squid need `istio.io/dataplane-mode: ambient` |
| 24 | Agent redeploy E2E test | 🔲 Y | Test reconfigure, session continuation |
| 25 | Per-session UID isolation | 🔲 Y | fsGroup is stopgap |
| 26 | LLM usage panel (OTEL) | 🔲 Y | Phoenix trace export broken |
| 27 | Subsessions panel | 🔲 Y | Show "No sub-sessions" instead of empty. Looper creates child sessions but looper is broken (0 observations) |
| 28 | Loop failure reason not shown | 🔲 Y | Failed loops should show error next to failure icon |
| 29 | Agent writes outside workspace | 🔲 Y | Skills reference paths outside /workspace |
| 30 | Context window management | 🔲 Y | No message trimming, UI shows wrong metric. Token-based windowing added (30K cap) but UI still confusing |
| 31 | DB metadata race condition | 🔲 Y | A2A SDK's save() overwrites metadata. MergingDatabaseTaskStore partial fix |
| 32 | Double-send UI bug | 🔲 Y | Message sent twice (3rd session created) |
| 33 | Ghost sessions after cleanup | 🔲 Y | Recovery tasks survive pod rollout |
| 34 | PVC test timeout | 🔲 Z | Wizard deploy variant needs longer timeout |
| 35 | Micro-reasoning system prompt hints | ✅ Alpha | Added gh CLI, cd, stderr hints |
| 36 | In-process sub-agent visibility | 🔲 Alpha | explore/delegate have zero UI visibility |
| 37 | Looper 0 observations | 🔲 Alpha | Looper never triggers auto-continue. Test moved to sandbox-hardened |
| 38 | Agent crash recovery (LangGraph resume) | 🔲 Alpha analyzed | LangGraph supports `ainvoke(None, config)`. Design needed. See LangGraph research in Alpha session |
| 39 | Resilience test (agent restart) | ✅ Alpha | Moved to sandbox-hardened, PASSING |

### Test Status

| Test Suite | Passing | Failing | Notes |
|-----------|---------|---------|-------|
| RCA workflow | ✅ | | 5/5 quality sections |
| Agent resilience | ✅ | | Moved to sandbox-hardened |
| Budget enforcement | | ❌ | Needs LLM proxy |
| Budget persistence | | ❌ | Needs LLM proxy |
| Import wizard (3) | | ❌ | Model selector timeout |
| HITL events (5) | | ❌ | Textarea not found after navigation |
| Skill whisperer (5) | | ❌ | Sidebar agent not found |
| Skill invocation (4) | | ❌ | Sidebar agent not found |
| Sidecars/looper (1) | | ❌ | 0 observations |
| Sessions (1) | | ❌ | Session persist on reload |
| Session ownership (1) | | ❌ | Type filter toggle |
| All others (~160) | ✅ | | |

## Recommended Session Priorities

### Session Beta — LLM Budget Proxy + DB Schemas
See `docs/plans/2026-03-12-session-beta-passover.md`

### Session Gamma — UI Polish + Remaining P0s
Focus on items 9-13 (step naming, reflector prompt, event ordering, page load):

1. **Step numbering format** (#9, #10) — `Step 2 [5]` and `Step 2a [7]` for replans
2. **Reflector "done" too early** (#11) — stronger prompt for remaining steps
3. **Executor events after reporter** (#12) — guard in loopBuilder
4. **Page load jankiness** (#13) — overlay instead of blank
5. **Loop failure reason** (#28) — show error in loop card
6. **Subsessions panel** (#27) — "No sub-sessions" message + investigate looper
7. **In-process sub-agent visibility** (#36) — delegation events

### Session Delta — Infrastructure
1. **Kiali ambient mesh** (#23)
2. **OTEL/Phoenix traces** (#26)
3. **DB metadata race** (#31)
4. **Ghost sessions** (#33)
5. **Agent crash recovery** (#38)

### Session Epsilon — Advanced Features
1. **Visualizations tab** (#22)
2. **Message queue + cancel** (#21)
3. **Per-session UID** (#25)
4. **Context window UI** (#30)
5. **Agent redeploy test** (#24)

## Design Docs (review for updates)

| Doc | Status | Topic |
|-----|--------|-------|
| `2026-03-12-llm-budget-proxy-design.md` | Ready for Beta | LLM proxy, llm_calls table, budget enforcement |
| `2026-03-12-db-multi-tenancy-design.md` | Ready for Beta | Schema-per-agent, wizard creates/drops schemas |
| `2026-03-10-visualizations-design.md` | Pending (Epsilon) | Session graph visualization |
| `2026-03-03-sandbox-reasoning-loop-design.md` | Reference | Plan-execute-reflect architecture |
| `2026-03-01-sandbox-platform-design.md` | Reference | Overall sandbox agent platform |

## Main Design Doc Updates Needed

The top-level design doc `docs/plans/2026-03-01-sandbox-platform-design.md` is
outdated. The following architectural changes from sessions V-Alpha need to be
reflected:

| Area | Old (in doc) | Current (deployed) |
|------|-------------|-------------------|
| Squid proxy | Sidecar container in agent pod | Separate Deployment per agent (`{agent}-egress-proxy`) |
| LiteLLM | Not in container diagram | Deployed in `kagenti-system`, shared LLM routing |
| LLM Budget Proxy | Doesn't exist | Designed (per-namespace, between agent→LiteLLM) |
| DB isolation | Single shared postgres, public schema | Schema-per-agent for checkpoints, team schema for sessions |
| Agent naming | Composable suffixes (`-secctx-landlock-proxy`) | Simplified profiles (`-legion`, `-hardened`, `-basic`, `-restricted`) |
| gVisor | T4 tier with RuntimeClass | Removed (incompatible with OpenShift SELinux) |
| Sidecar agents | Not designed | Looper, Hallucination Observer, Context Guardian |
| Budget enforcement | Not in design | In-memory → LiteLLM proxy (in progress) |
| Agent reasoning | Basic tool loop | Plan-execute-reflect with micro-reasoning |
| Test count | 192/196 Playwright | 196 total, 173 passing |
| Session history | A-K | A-K, L, M, N, R-Z, Alpha, Beta |

**Container diagram needs update** to show:
- LiteLLM proxy in kagenti-system
- LLM budget proxy per namespace (new)
- Egress proxy as separate deployment (not sidecar)
- Per-agent DB schema isolation
- Sidecar agent architecture

**Component status table** needs full refresh — many items moved from
"Not built" to "Built" or changed scope.

## Main Issue

TODO: Update the main GitHub issue tracking the sandbox agent feature with:
- Current status (what works, what's remaining)
- Links to design docs
- Test status
- Session history (V→W→X→Y→Z→Alpha→Beta→...)
