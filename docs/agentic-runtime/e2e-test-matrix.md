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
`NEMOCLAW_AGENTS`, `SKILL_AGENTS`, `ALL_AGENTS`.

## Capability Matrix (CI Kind)

208 tests total. P=pass, S=skip, —=not tested.

**Tier 1: Infrastructure**

| Capability | Claude Code | OpenCode | Claude SDK | ADK | Weather | OpenClaw | Hermes |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Connectivity | P | P | P | P | P | P | P |
| Credentials | P | P | P | P | P | P | P |
| Sandbox lifecycle | P | — | — | — | — | — | — |
| Workspace | P | P | — | — | — | — | — |
| Credential security | P | P | P | P | P | P | P |
| Sandbox connectivity | P | — | — | — | — | — | — |
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
| Tenant isolation (auth) | — | S (needs Keycloak port-forward in CI) |
| Tenant isolation (RBAC) | — | P |
| Tenant isolation (credentials) | — | P |
| Audit logging | — | P (Claude Code, OpenCode) |

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
| `test_T1_6_credential_security.py` | 1 | 14 | Secret delivery, no hardcoded keys, K8s token leak, policy mount |
| `test_T1_7_sandbox_connectivity.py` | 1 | 5 | Gateway health, endpoints, port-forward, kubectl exec |
| `test_T4_1_hitl_network.py` | 4 | 3 | HITL network egress |
| `test_T4_2_tenant_isolation.py` | 4 | 15 | JWT audience, RBAC scoping, credential isolation |

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
