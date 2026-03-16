# Session Beta Handoff — 2026-03-15

> **Cluster:** kagenti-team-sandbox42 (all components deployed and running)
> **Worktrees:** `.worktrees/sandbox-agent` (`d34cb73e`), `.worktrees/agent-examples` (`0b72ff7`)
> **sbox42:** UNTOUCHED (kagenti-team-sbox42)

## Deployed on sandbox42

| Component | Build | Commit | Status |
|-----------|-------|--------|--------|
| Backend | #7 | `a1689b2` | Running |
| UI | #4 | `d34cb73` | Running |
| Sandbox Agent | #2 | `e21ecfa` | Running |
| Budget Proxy | #2 | — | Running |
| LiteLLM | — | — | Running (5 models) |
| All variants | — | — | Running (sandbox-{agent,legion,basic,hardened,restricted}) |

## For Next Session (Beta)

### P0: Message Loading Refactor

The current rendering has rogue message blocks and broken pairing. The fix:

**Current approach** (broken):
- `messages[]` + `agentLoops` map are separate states
- Positional pairing: `loops[i].userMessage = userMessages[i]`
- Breaks on cancels, system messages, multi-task sessions

**Proposed approach:**
- Group rendering by **task_id** — each A2A task = one user message + one event loop
- The backend history endpoint already returns task_id per message
- Each task renders as an invisible wrapper: `[UserBubble] + [AgentLoopCard]`
- Ordered by task creation time (latest at bottom)
- No separate `messages[]` state — everything flows through the task/loop structure

**Key files:**
```
kagenti/ui-v2/src/pages/SandboxPage.tsx:2214-2283  # rendering logic
kagenti/ui-v2/src/utils/loopBuilder.ts             # event reducer
kagenti/ui-v2/src/utils/historyPairing.ts          # broken pairing
```

### P1: Wizard Per-Node Model Page

Add wizard step with 6 model selectors:
- Planner, Executor, Reflector, Reporter
- Thinking (bare LLM), Micro-Reasoning (LLM+tools)

Agent code already supports `LLM_MODEL_{NODE_TYPE}` env vars.
Backend `sandbox_deploy.py` already has `model_planner` etc. fields.

### P1: Remaining E2E Failures

E2E test run in progress. Previous results: 96/141 passing (68%).

Final results: **93 passed, 44 failed, 4 skipped** (66% pass rate)

| Test File | Failed | Root Cause |
|-----------|--------|-----------|
| `test_sandbox_variants.py` | 24 | Connection errors / timeouts on variant agents |
| `test_sandbox_sessions_api.py` | 7 | Sessions not persisting (metadata/auth) |
| `test_litellm_proxy.py` | 4 | OpenAI key = MAAS key (not real OpenAI) |
| `test_sandbox_legion.py` | 3 | DB cleaned mid-test (transient) |
| `test_sandbox_legion_tasks.py` | 2 | Timeout on complex tasks |
| `test_agent_conversation.py` | 2 | Weather agent empty response |
| `test_platform_health.py` | 1 | Pod restart during test |
| `test_mlflow_traces.py` | 1 | Missing span attribute |

### P2: Budget Proxy in Helm Chart

Currently deployed by `76-deploy-sandbox-agents.sh` script.
Should be part of team namespace provisioning in the Helm chart
(`agent-namespaces.yaml`) or a dedicated template.

### P1: Test Rationalization

We have ~260 test assertions across 15 sandbox spec files + more in agent/session/platform tests.
Many are redundant conversations that test overlapping capabilities. Proposed consolidation:

**Core smoke (must pass, fast):**
- `sandbox.spec.ts` — login, navigate to sandbox, send message, see response
- `sandbox-sessions.spec.ts` — create session, switch sessions, history persists

**Workflow (must pass, slower):**
- `agent-rca-workflow.spec.ts` — full agent pipeline (plan → execute → reflect → report)
- `sandbox-create-walkthrough.spec.ts` — wizard deploy flow

**Can merge/reduce:**
- `sandbox-variants.spec.ts` (13 tests × 4 variants = redundant) → test 1 variant thoroughly, spot-check others
- `sandbox-rendering.spec.ts` + `sandbox-debug.spec.ts` → merge into rendering suite
- `sandbox-walkthrough.spec.ts` overlaps with `sandbox.spec.ts` → merge
- `sandbox-chat-identity.spec.ts` + `session-ownership.spec.ts` → merge auth tests

**Feature-specific (keep as-is):**
- `sandbox-budget.spec.ts`, `sandbox-graph.spec.ts`, `sandbox-file-browser.spec.ts`
- `sandbox-hitl.spec.ts`, `sandbox-delegation.spec.ts`, `sandbox-sidecars.spec.ts`

**Target: ~150 assertions (from ~260), covering same capabilities with less redundancy.**

### P2: Per-Agent Virtual Keys from Wizard

Wizard `llm_key_source="new"` currently creates a raw k8s secret.
Should call `/api/v1/llm/keys` to create a litellm virtual key
with model restrictions from the `allowedModels` field.

## Setup for Next Session

```bash
export KUBECONFIG=~/clusters/hcp/kagenti-team-sandbox42/auth/kubeconfig
export LOG_DIR=/tmp/kagenti/tdd/sandbox42 && mkdir -p $LOG_DIR
export KEYCLOAK_PASSWORD=$(kubectl -n keycloak get secret kagenti-test-users -o jsonpath='{.data.admin-password}' | base64 -d)
export KAGENTI_UI_URL="https://$(kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}')"
export PATH="/opt/homebrew/opt/helm@3/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"
```

## All Commits This Session (13 total)

### kagenti repo
| Commit | Description |
|--------|-------------|
| `9e83dc1a` | feat: LLM virtual key management API |
| `c2b0d91d` | fix(ui): prompt fields for all nodes |
| `1cde5e42` | fix(backend): idempotent key creation |
| `6d504ccf` | feat: model selector + wizard allowed models |
| `fa941ce3` | feat(backend): per-node model overrides |
| `b8ac5e6e` | fix(test): litellm port-forward for E2E |
| `132c6e0c` | fix(deploy): agents direct to litellm (reverted) |
| `39f095a1` | feat: budget proxy in team provisioning |
| `8230b0b7` | fix(deploy): budget proxy DB password |
| `3850d351` | fix(backend): guard None in history |
| `a1689b2f` | fix(backend): metadata=None in history |
| `d34cb73e` | fix(ui): remove helperText TS error |

### agent-examples repo
| Commit | Description |
|--------|-------------|
| `e21ecfa` | fix(agent): workspace_path in invoke_with_tool_loop |
| `0b72ff7` | feat(agent): per-node LLM model overrides |
