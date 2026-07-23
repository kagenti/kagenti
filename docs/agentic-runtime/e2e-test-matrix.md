---
draft: true       # excluded from https://www.rossoctl.dev/
---

# OpenShell E2E Test Matrix

> Back to [main doc](openshell-integration.md) | Tests: `rossoctl/tests/e2e/openshell/`

## Agents

| Agent | Protocol | LLM | Skill Support |
|---|---|---|---|
| `claude-sdk-agent` | A2A JSON-RPC | LiteMaaS | Via prompt |
| `adk-agent-supervised` | A2A via port-bridge | LiteMaaS (supervised) | Via prompt |
| `weather-agent-supervised` | kubectl exec | No | N/A |
| `openshell-claude` | kubectl exec (sandbox) | Anthropic/LiteLLM | Native `.claude/skills/` |
| `openshell-opencode` | kubectl exec (sandbox) | OpenAI-compat | Via prompt |
| `nemoclaw-openclaw` | HTTP gateway | LiteMaaS | Gateway protocol (skip) |
| `nemoclaw-hermes` | TCP (internal) | LiteMaaS | Internal protocol (skip) |

Agent lists defined in `conftest.py`: `A2A_AGENTS`, `EXEC_AGENTS`, `CLI_AGENTS`,
`NEMOCLAW_AGENTS`, `SKILL_AGENTS`, `ALL_AGENTS`.

## Capability Matrix (CI Kind — 107 passed, 0 failed, 112 skipped)

219 tests total. P=pass, S=skip(reason), FL=flaky, —=not tested.

**Latest CI result:** 107/0/112 on SHA `43f1f03` (2026-05-10, issue_comment run with full secrets).

**Stability:** 4/4 consecutive runs with 0 failures (3 local Kind + 1 CI Kind).

**Tier 1: Infrastructure**

| Capability | Claude Code | OpenCode | Claude SDK | ADK | Weather | OpenClaw | Hermes |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Connectivity | P | S¹ | P | S² | S² | P | S³ |
| Credentials | S¹ | S¹ | P | P | P | P | P |
| Sandbox lifecycle | P | S¹ | — | — | — | — | — |
| Workspace | S¹ | S¹ | — | — | — | — | — |
| Resource limits | S¹ | S¹ | P | S⁴ | S⁴ | P | P |

**Tier 2: Capabilities**

| Capability | Claude Code | OpenCode | Claude SDK | ADK | Weather | OpenClaw | Hermes |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Multiturn | S⁵ | S⁵ | P | S² | S⁶ | P | — |
| Context isolation | S⁵ | S⁵ | P | S² | S⁶ | P | — |
| Session resume | S⁵ | S⁵ | P | S² | — | — | — |
| Tool calling | S¹ | — | — | — | — | — | — |
| Concurrent sessions | S¹ | — | — | — | — | — | — |

**Tier 3: Skills (parametrized x 6 agents, x 2 models)**

| Capability | Claude SDK | ADK | Claude Code | OpenCode | OpenClaw | Weather |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| PR review | P | S² | S¹ | S¹ | S⁷ | S⁶ |
| RCA | P/FL⁸ | S² | S¹ | S¹ | S⁷ | S⁶ |
| Security | P/FL⁸ | S² | S¹ | S¹ | S⁷ | S⁶ |
| GitHub PR | P | S² | S¹ | S¹ | S⁷ | S⁶ |

Per-model: `llama-scout-17b` + `deepseek-r1` (both via LiteMaaS).

**Tier 4: Security**

| Capability | Weather | Others |
|---|:---:|:---:|
| HITL: Network egress | P | — |
| Audit logging | — | S¹ (Claude Code, OpenCode) |

**Tier 5: Backend API (via rossoctl-backend A2A proxy)**

Tests go through the backend at `/api/v1/chat/{ns}/{agent}/send|stream`.
One port-forward to the backend replaces per-agent port-forwards.

| Capability | Claude SDK | ADK | Weather | Claude Code | OpenCode | OpenClaw |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Health check | P | P | P | — | — | — |
| Agent card proxy | P | S² | S² | — | — | — |
| Send proxy | P | S² | S² | — | — | — |
| Stream proxy | S⁸ | S² | S² | — | — | — |
| Multiturn proxy | P | S² | S⁶ | — | — | — |
| Agent list | S⁹ | — | — | — | — | — |
| Error handling | P | P | P | — | — | — |
| Concurrent proxy | P | — | — | — | — | — |

**Tier 6: ACP Protocol (WebSocket)**

Tests the ACP WebSocket endpoint with JSON-RPC 2.0 lifecycle.

| Capability | Claude SDK | ADK | Weather | Claude Code | OpenCode | OpenClaw |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Initialize | P | P | — | — | — | — |
| Session new/close | P | P | — | — | — | — |
| Prompt relay | P | P | — | — | — | — |
| Context preserved | P | P | — | — | — | — |
| Session list | P | — | — | — | — | — |
| Session resume | P | — | — | — | — | — |
| Permission gate | P | — | — | — | — | — |
| Error handling | P | P | — | — | — | — |

**Tier 7: Teleport (Sandbox CRD + LLM)**

Tests session teleporting — packaging local context into a sandbox and executing with it.

| Capability | Claude Code |
|---|:---:|
| Package context → ConfigMap | P |
| Deploy sandbox with context | P |
| Context unpacked in pod | P |
| Prompt reads teleported context | P |
| Cleanup removes resources | P |
| Script exists and executable | P |

MVP targets Claude Code only. OpenCode teleport planned as extension.

## Skip Reasons

| Code | Reason | Count | Resolution Path |
|------|--------|-------|-----------------|
| S¹ | Sandbox CRD not installed in CI | ~25 | Install agent-sandbox CRD before tests |
| S² | Supervised agent netns blocks backend (503) | ~15 | Port-bridge sidecar integration |
| S³ | NemoClaw tests disabled in CI | ~5 | Set `OPENSHELL_NEMOCLAW_ENABLED=true` |
| S⁴ | No resource limits set on deployment | ~5 | Add limits to agent deployment YAMLs |
| S⁵ | CLI sandbox is single-invocation (by design) | ~6 | ACP session/prompt for multiturn |
| S⁶ | No LLM capability (weather) or not deployed | ~10 | By design |
| S⁷ | NemoClaw gateway protocol (not A2A) | ~8 | NemoClaw adapter in backend |
| S⁸ | LLM returned empty response (llama-scout-17b ~17% flake) | ~3 | Skip guard, track as flaky |
| S⁹ | Agents lack `rossoctl.io/type=agent` label | 1 | Label alignment |

## Flaky Tests

| Test | Agent | Model | Flake Rate | Root Cause |
|------|-------|-------|-----------|-----------|
| `test_skill_rca[claude_sdk]` | Claude SDK | llama-scout-17b | ~17% | LLM returns empty response |
| `test_skill_security[claude_sdk]` | Claude SDK | llama-scout-17b | ~17% | Same |
| `test_T5_stream[claude_sdk_agent]` | Claude SDK | llama-scout-17b | ~10% | Empty SSE stream |

All flaky tests have skip guards — they skip instead of fail when the LLM returns empty.
deepseek-r1 model does NOT exhibit these flakes.

## Test File Organization

| File | Tier | Tests | What it covers |
|---|---|:---:|---|
| `test_T0_1_infra_platform.py` | 0 | 9 | Gateway, operator, agent pods |
| `test_T0_3_infra_supervisor.py` | 0 | 12 | Supervisor enforcement (weather) |
| `test_T0_4_infra_nemoclaw.py` | 0 | 18 | NemoClaw health, security |
| `test_T0_5_infra_litellm.py` | 0 | 14 | LiteLLM config, waypoint, passthrough |
| `test_T1_1_connectivity.py` | 1 | 12 | A2A, sandbox, NemoClaw connectivity |
| `test_T1_2_credentials.py` | 1 | 15 | Secret delivery, no hardcoded keys |
| `test_T1_3_sandbox_lifecycle.py` | 1 | 10 | Sandbox CRUD, status observability |
| `test_T1_4_workspace.py` | 1 | 5 | PVC persistence |
| `test_T1_5_resource_limits.py` | 1 | 9 | CPU/memory limits on all agents |
| `test_T2_1_multiturn.py` | 2 | 20 | Multiturn, context, tool calling, concurrent |
| `test_T2_3_session_resume.py` | 2 | 7 | Session resume across restarts |
| `test_T3_1_skill_execution.py` | 3 | 32 | Skills x 6 agents + per-model + audit |
| `test_T4_1_hitl_network.py` | 4 | 3 | HITL network egress |
| `test_T5_1_backend_api.py` | 5 | ~15 | Backend A2A proxy |
| `test_T6_1_acp_protocol.py` | 6 | ~15 | ACP WebSocket protocol |
| `test_T7_1_teleport.py` | 7 | 6 | Session teleport lifecycle |

## Running Tests

### CI (via PR comment on any PR)

Comment `/run-e2e-openshell` on a PR to trigger both:
- **OpenShell PoC (Kind)** — `e2e-openshell-kind.yaml` (~20 min)
- **OpenShell PoC (HyperShift)** — `e2e-openshell-hypershift.yaml` (~45 min, creates ephemeral cluster)

The Kind workflow also auto-triggers on `pull_request` for paths under
`deployments/openshell/**` and `rossoctl/tests/e2e/openshell/**`.

### Local

```bash
# Full deploy + test on Kind
.github/scripts/local-setup/openshell-full-test.sh --skip-cluster-destroy

# Iterate on existing Kind cluster (skip deploy)
.github/scripts/local-setup/openshell-full-test.sh --skip-cluster-create --skip-cluster-destroy

# Full deploy + test on HyperShift
source .env.rossoctl-hypershift-custom
.github/scripts/local-setup/openshell-full-test.sh --platform ocp --skip-cluster-destroy ostest

# Direct pytest (no deploy, existing cluster)
export OPENSHELL_LLM_AVAILABLE=true OPENSHELL_LLM_MODELS="llama-scout-17b,deepseek-r1"
export OPENSHELL_NEMOCLAW_ENABLED=true OPENSHELL_GATEWAY_NAMESPACE=team1
uv run pytest rossoctl/tests/e2e/openshell/ -v --timeout=300
```
