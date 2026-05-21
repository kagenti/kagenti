# OpenShell E2E Test Matrix

> Back to [main doc](openshell-integration.md) | Tests: `kagenti/tests/e2e/openshell/`

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
`NEMOCLAW_AGENTS`, `ALL_AGENTS`.

## Capability Matrix (CI Kind)

174 tests total. P=pass, S=skip, —=not tested.

**Tier 1: Infrastructure**

| Capability | Claude Code | OpenCode | Claude SDK | ADK | Weather | OpenClaw | Hermes |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Connectivity | P | P | P | P | P | P | P |
| Credentials | P | P | P | P | P | P | P |
| Sandbox lifecycle | P | — | — | — | — | — | — |
| Workspace | P | P | — | — | — | — | — |
| Resource limits | S | — | P | S | S | P | P |

**Tier 2: Capabilities**

| Capability | Claude Code | OpenCode | Claude SDK | ADK | Weather | OpenClaw | Hermes |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Multiturn | S | S | P | P | S | P | — |
| Context isolation | S | S | P | P | S | P | — |
| Tool calling | P | — | — | — | — | — | — |
| Concurrent sessions | P | — | — | — | — | — | — |

S for Claude Code/OpenCode: CLI is single-invocation (by design).

**Tier 3: Skills (parametrized x 6 agents)**

| Capability | Claude SDK | ADK | Claude Code | OpenCode | OpenClaw | Weather |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| PR review | P | P | P | P | S | S |
| RCA | P | P | P | P | S | S |
| Security | P | P | P | P | S | S |
| GitHub PR | P | P | P | P | S | S |

S for OpenClaw: gateway doesn't expose REST chat API.
S for Weather: no LLM capability.
Per-model: `llama-scout-17b` + `deepseek-r1` (both 100% via LiteMaaS).

**Tier 4: Security**

| Capability | Weather | Others |
|---|:---:|:---:|
| HITL: Network egress | P | — |
| Audit logging | — | P (Claude Code, OpenCode) |

**Tier 5: Backend API (via kagenti-backend A2A proxy)**

All A2A agents are tested through the backend proxy (`/api/v1/chat/{ns}/{agent}/send|stream`).
This validates the production path — one port-forward to the backend replaces per-agent port-forwards.

| Capability | Claude SDK | ADK | Weather | Claude Code | OpenCode | OpenClaw |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Health check | — | — | — | — | — | — |
| Agent card proxy | — | — | — | — | — | — |
| Send proxy | — | — | S | — | — | — |
| Stream proxy | — | — | S | — | — | — |
| Multiturn proxy | — | — | S | — | — | — |
| Agent list | — | — | — | — | — | — |
| Error handling | — | — | — | — | — | — |
| Concurrent proxy | — | — | — | — | — | — |

S for Weather send/stream/multiturn: no LLM capability (by design).
Claude Code/OpenCode: CLI sandbox agents, not A2A — backend proxy N/A (use ACP instead).
OpenClaw: gateway protocol, not A2A — backend proxy N/A (needs adapter).
Requires `OPENSHELL_BACKEND_AVAILABLE=true`.

**Tier 6: ACP Protocol (WebSocket)**

Tests the ACP WebSocket endpoint (`/api/v1/acp/ws/{ns}/{agent}`) with JSON-RPC 2.0.
Currently bridges to A2A agents; future: direct ACP for Claude Code/OpenCode sandboxes.

| Capability | Claude SDK | ADK | Weather | Claude Code | OpenCode | OpenClaw |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Initialize | — | — | — | — | — | — |
| Session new/close | — | — | — | — | — | — |
| Prompt relay | — | — | S | — | — | — |
| Context preserved | — | — | S | — | — | — |
| Session list | — | — | — | — | — | — |
| Session resume | — | — | — | — | — | — |
| Permission gate | — | — | — | — | — | — |
| Error handling | — | — | — | — | — | — |

S for Weather: no LLM.
Claude Code/OpenCode: future — ACP native (session/prompt → sandbox exec).
OpenClaw: future — ACP-NemoClaw bridge.
Requires `KAGENTI_FEATURE_FLAG_ACP=true` on the backend.

## Skip Reasons

| Reason | Count | Agents | Resolution |
|---|:---:|---|---|
| CLI single-invocation | 6 | Claude Code, OpenCode | ExecSandbox gRPC adapter (Phase 2) |
| No LLM | 9 | Weather, generic | By design |
| No resource limits | 5 | ADK, Weather, sandbox | Add limits to deployment YAMLs |
| Gateway protocol | 4 | OpenClaw | A2A adapter or NemoClaw plugin |
| Waypoint not deployed | 3 | All | Add to deploy-shared.sh |
| Session resume | 5 | All | Kagenti backend session store |

## Test File Organization

Test counts include parametrized instances (e.g., a test parametrized across 3 agents counts as 3).

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

## Running Tests

### CI (via PR comment on any PR)

Comment `/run-e2e-openshell` on a PR to trigger both:
- **OpenShell PoC (Kind)** — `e2e-openshell-kind.yaml` (~20 min)
- **OpenShell PoC (HyperShift)** — `e2e-openshell-hypershift.yaml` (~45 min, creates ephemeral cluster)

The Kind workflow also auto-triggers on `pull_request` for paths under
`deployments/openshell/**` and `kagenti/tests/e2e/openshell/**`.

### Local

```bash
# Full deploy + test on Kind
.github/scripts/local-setup/openshell-full-test.sh --skip-cluster-destroy

# Iterate on existing Kind cluster (skip deploy)
.github/scripts/local-setup/openshell-full-test.sh --skip-cluster-create --skip-cluster-destroy

# Full deploy + test on HyperShift
source .env.kagenti-hypershift-custom
.github/scripts/local-setup/openshell-full-test.sh --platform ocp --skip-cluster-destroy ostest

# Direct pytest (no deploy, existing cluster)
export OPENSHELL_LLM_AVAILABLE=true OPENSHELL_LLM_MODELS="llama-scout-17b,deepseek-r1"
export OPENSHELL_NEMOCLAW_ENABLED=true OPENSHELL_GATEWAY_NAMESPACE=team1
uv run pytest kagenti/tests/e2e/openshell/ -v --timeout=300
```
