# Pending Questions and Investigation Paths

> Back to [main doc](openshell-integration.md) |
> Sources: [Paolo's integration proposal](https://github.com/kagenti/kagenti/pull/1300),
> PoC implementation (PR #1300), alignment analysis, codebase research

## Status Legend

- **ANSWERED** — Our PoC has a concrete answer with evidence
- **OPEN** — Needs discussion with OpenShell/Kagenti teams
- **INVESTIGATING** — Research in progress, partial answers
- **BLOCKED** — Needs upstream OpenShell changes
- **TESTED** — Covered by E2E tests with pass/skip status

---

## 1. Agent Interaction Model

### Q1.1: How do long-running A2A agents fit the OpenShell model?

**Status:** ANSWERED — MVP design doc ([#1364](https://github.com/kagenti/kagenti/pull/1364)) defines 3 deployment tiers. PoC validated Tier 2 (supervised) and Tier 3 (plain). MVP adds gateway-per-tenant ([#1363](https://github.com/kagenti/kagenti/issues/1363)).

The goal is to use OpenShell for ALL agents — not just interactive CLI sandboxes.
Custom A2A agents (ADK, Claude SDK, LangGraph) should get the same security
benefits (Landlock, seccomp, OPA egress, zero-secret credentials) as builtin
sandbox agents.

**Current PoC:** Two separate deployment models coexist:
- Custom A2A agents → Kagenti Deployment (no supervisor, K8s Secrets for creds)
- Builtin sandboxes → OpenShell Sandbox CR (supervisor, gateway creds)

**Target architecture — 3 deployment tiers:**

| Tier | Deployment | Supervisor | Creds | OPA Egress | Port Access | When |
|------|-----------|-----------|-------|-----------|-------------|------|
| **Tier 1: Full OpenShell** | Sandbox CR via gateway | Yes (all layers) | Gateway provider injection | Yes (netns + OPA proxy) | SSH/ExecSandbox only | Builtin sandboxes (current) |
| **Tier 2: Supervised Deployment** | K8s Deployment + supervisor entrypoint + port bridge sidecar | Yes (all layers) | Gateway provider injection | Yes (netns + OPA proxy) | A2A via port bridge | Custom A2A agents (next step) |
| **Tier 3: Plain Deployment (fallback)** | K8s Deployment | No | K8s Secrets (secretKeyRef) | No (policy mounted but not enforced) | A2A direct | Current PoC for custom agents |

**After OpenShell rearchitecture (RFC 0001):** The composable driver model
enables partial adoption of OpenShell components:
- Use **credential subsystem only** (gateway provider store) without supervisor
- Use **Landlock + seccomp only** without network namespace (no port access issue)
- Use **OPA policy only** as a sidecar (no netns required)
- Mix and match per agent based on security requirements

**What blocks moving from Tier 3 → Tier 2:**
- Port bridge sidecar needed (socat — can implement now, no upstream needed)
- Supervisor binary delivery via init container (proposal Option C)
- Gateway provider injection for Deployment-backed agents (needs `OPENSHELL_SANDBOX_ID`)

**What the rearchitecture enables (Tier 2 without workarounds):**
- Supervisor `--expose-port` flag for native A2A port exposure
- Pluggable credential backend (K8s Secrets as alternative to gateway store)
- Selective security layers (Landlock without netns)

**Fallback path:** Tier 3 (plain Deployment with K8s Secrets) always works.
No OpenShell dependency. Tests pass. Production-grade with Istio mTLS.
The upgrade path to Tier 2/1 is additive — existing agents don't break.

**Test coverage:**
- Tier 1 (builtin sandboxes): Sandbox CR creation, PVC persistence (passes)
- Tier 2 (supervised A2A): `weather-agent-supervised` — all 12 enforcement tests pass
- Tier 3 (plain deployment): All A2A connectivity, skill execution tests pass

### Q1.2: How should the Kagenti UI expose sandbox sessions?

**Status:** OPEN

**Candidates:**
1. **A2A-first (recommended):** All agent interaction via A2A protocol + AgentChat UI.
   CLI+SSH as escape hatch for debugging. Simplest to implement.
2. **Embedded terminal:** xterm.js in the UI connected via WebSocket → SSH tunnel.
   Requires gateway ingress (L4 passthrough) and browser-to-SSH bridging.
3. **Hybrid:** UI for lifecycle (create/destroy), A2A for programmatic, SSH for interactive.

**Impact on tests:** None immediate. Phase 2 UI integration work.

### Q1.3: How does `openshell sandbox sessions` interact with Kagenti session management?

**Status:** PARTIALLY ANSWERED — MVP uses per-gateway SQLite (design doc §3.1). Session persistence via dtach ([#1354](https://github.com/kagenti/kagenti/issues/1354)). Full Kagenti backend integration is beyond-MVP (design doc §10).

OpenShell gateway tracks sessions in its own DB (SQLite/Postgres). Kagenti backend
has a separate session store in PostgreSQL. These are independent systems.

**Candidates:**
1. **Single session store:** Kagenti backend IS the session store. Gateway delegates via gRPC.
2. **Dual stores with sync:** Both store sessions. A reconciliation loop syncs state.
3. **Gateway sessions for SSH, backend sessions for A2A:** Each system owns its protocol.

**Impact on tests:** `test_multiturn_context_continuity` (4 skips) — backend session store
would enable context persistence without agent-side changes.

### Q1.4: How does multi-agent orchestration work within a team namespace?

**Status:** OPEN

Our PoC deploys 4 agents in `team1`. The proposal's model is one agent per sandbox.

**Candidates:**
1. **Independent agents:** Each agent is a separate Deployment/Sandbox. Backend orchestrates.
2. **Agent delegation:** One agent delegates sub-tasks to others via A2A.
3. **Shared sandbox:** Multiple agents in one sandbox pod (not currently supported).

---

## 2. Security and Privileges

### Q2.1: What is the minimum privilege set for the supervisor?

**Status:** ANSWERED

Research confirms: `CAP_NET_ADMIN` + `CAP_SYS_ADMIN` + `CAP_SYS_PTRACE` (not `privileged: true`).
The supervisor's seccomp filter blocks mount syscalls. Our Kind-specific need for
`privileged: true` was due to `mount --make-shared` in the container setup, not the
supervisor binary itself.

**Answer:** Custom SCC with specific capabilities. See `sandboxing-layers.md`.

**TODO:** Test `weather-agent-supervised` with reduced capabilities on both platforms.

**Impact on tests:** Would validate supervisor enforcement without `privileged: true`.

### Q2.2: Has the proposed SCC been tested on OCP with SELinux enforcing?

**Status:** TESTED (partial)

Our PoC runs on HyperShift (OCP 4.20) with SELinux enforcing. 75 tests pass, 0 fail.
However, we use `privileged: true` SCC, not the reduced capability set.

**TODO:** Test with `allowPrivilegedContainer: false` + specific capabilities on OCP.

### Q2.3: K8s Secrets (Kagenti) vs placeholder tokens (OpenShell)?

**Status:** ANSWERED — MVP uses Keycloak credentials driver ([#1355](https://github.com/kagenti/kagenti/issues/1355)) for OAuth2 client_credentials. Static API keys via OpenShell native provider store. K8s Secrets remain for Tier 3 agents. | **Related:** Q1.1 (3-tier model), Q8.1 (port bridge), Q8.3 (rearchitecture)

Two credential models exist:
- **Kagenti:** API keys in K8s Secrets, injected via `secretKeyRef`
- **OpenShell:** Placeholder tokens (`openshell:resolve:env:*`) resolved by supervisor proxy

**Candidates:**
1. **K8s Secrets for custom agents, placeholders for builtin sandboxes:** Each model
   where it's strongest. Custom agents don't have supervisor; builtin sandboxes do.
2. **Placeholders everywhere:** All agents use supervisor proxy for credential resolution.
   Requires supervisor on every agent (Phase 3).
3. **K8s Secrets everywhere:** Simpler but loses zero-secret isolation benefit.

**Impact on tests:** `test_credential__placeholder_tokens` (2 skips) — needs supervisor integration.

### Q2.4: How should live egress blocking be validated?

**Status:** TESTED (new)

Our `test_09_hitl_policy.py` tests OPA egress blocking via `kubectl exec` into
the supervised agent. Three tests: deny unauthorized, allow authorized, log denials.

**Hurdle:** `curl` not available in supervised agent pod. Fixed by using python3 urllib.

---

## 3. LLM Integration and Inference Routing

### Q3.1: OpenShell inference router vs Kagenti LiteLLM — which is canonical?

**Status:** OPEN | **Related:** Q8.2 (model validation), Q1.1 (tier determines routing)

Both route LLM traffic. OpenShell's inference router strips credentials and injects
backend keys. Kagenti's LiteLLM provides model routing, virtual keys, and budget tracking.

**Candidates:**
1. **LiteLLM as backend for inference router:** OpenShell proxy routes to LiteLLM endpoint.
   Best of both: zero-secret isolation + budget tracking.
2. **LiteLLM replaces inference router:** Agents call LiteLLM directly (current PoC model).
   Simpler but loses supervisor-level credential stripping.
3. **Inference router for builtin, LiteLLM for custom:** Each where appropriate.

**Impact on tests:** Affects how we configure LLM for `openshell_opencode` tests.

### Q3.2: Per-session budget enforcement across both systems?

**Status:** OPEN

LiteLLM has per-key budgets. Budget Proxy has per-session budgets. OpenShell's
inference router has no budget concept.

**Candidates:**
1. **LiteLLM virtual keys per session:** Create a unique LiteLLM key per conversation.
2. **Budget Proxy per sandbox:** Each sandbox gets its own Budget Proxy instance.
3. **Gateway-level quota:** Add budget tracking to OpenShell gateway (upstream contribution).

### Q3.3: Can openshell_opencode use LiteMaaS for skill execution?

**Status:** INVESTIGATING

OpenCode uses OpenAI-compatible format. LiteMaaS provides that. The gateway needs
`OPENAI_API_KEY` + `OPENAI_BASE_URL` env vars (already configured by fulltest script).

**Hurdle:** The builtin sandbox runs OpenCode CLI which reads provider config from the
gateway's credential store (not env vars directly). Need to verify the gateway's
provider auto-discovery actually injects credentials into sandbox pods via
`GetProviderEnvironment` gRPC.

**Impact on tests:** Would enable 3 `openshell_opencode` skill execution tests (currently skip).
Test: `test_pr_review__openshell_opencode__litemaas_provider`

---

## 4. Session Persistence and Context

### Q4.1: How should multi-turn context work for A2A agents?

**Status:** OPEN — highest priority for test coverage | **Related:** Q7.3 (testing hurdle)

No A2A agent currently preserves context across requests. The ADK agent returns
`contextId` but creates a new one per request (upstream ADK gap).

**Candidates:**
1. **Backend-managed context (recommended):** Kagenti backend stores history in PostgreSQL.
   Each turn, backend sends full history as part of the A2A request. Agent is stateless.
   - Investigation: Implement in `kagenti/backend/app/services/session_db.py`
   - Effort: Medium (backend code + A2A adapter)
2. **Agent-side PVC session store:** Agent reads/writes session state to PVC.
   - Investigation: Add PVC to ADK/Claude SDK deployments, implement checkpoint/resume
   - Effort: High (agent code changes per framework)
3. **Upstream ADK contextId fix:** Wait for Google ADK to support client-sent contextId.
   - Investigation: File issue on google/adk-python, track PR
   - Effort: Zero (waiting)

**Impact on tests:** Would enable 4 `test_context_continuity` tests (currently skip).

### Q4.2: Do Claude Code and OpenCode store sessions on disk that can be resumed?

**Status:** ANSWERED

Yes. Claude Code stores in `~/.claude/projects/<hash>/` (JSONL transcripts).
OpenCode stores in `~/.opencode/`. In the sandbox, these paths are on the
PVC-mounted `/sandbox` directory. The data survives pod restart.

However, **session resume is not automatic** — the agent CLI loads prior sessions
when opening a project but doesn't automatically continue a previous conversation.
The user must explicitly reference prior context.

**Impact on tests:** `test_resume__generic_sandbox__write_delete_recreate_read` tests
file persistence. A conversation-level resume test needs the agent CLI to actually
process prior session data — requires ExecSandbox gRPC adapter (Phase 2).

### Q4.3: How does the ExecSandbox gRPC work for sending prompts to builtin agents?

**Status:** ANSWERED

The gateway's `ExecSandbox` RPC supports:
- Command + args execution
- Optional stdin payload
- Streaming stdout/stderr/exit response
- Environment overrides
- Timeout configuration
- PTY support

The Kagenti backend would call `ExecSandbox(command=["opencode", "--prompt", "..."])`
to send a prompt to an OpenCode sandbox. Response is streamed back.

**Hurdle:** No Kagenti backend adapter for ExecSandbox gRPC exists yet. Need to
implement a gRPC client in the FastAPI backend that bridges A2A requests to
ExecSandbox calls.

**Impact on tests:** Would enable 8 `openshell_opencode` and `openshell_claude` tests.

---

## 5. Observability and Audit

### Q5.1: How should supervisor events reach Kagenti's OTel pipeline?

**Status:** OPEN

The supervisor logs to stdout. The gateway receives logs via `PushSandboxLogs` gRPC.
Neither exports to OTLP.

**Candidates:**
1. **Supervisor OTLP exporter:** Upstream contribution — add OTLP exporter to supervisor.
2. **Gateway OTLP exporter:** Gateway aggregates supervisor logs and exports via OTLP.
3. **Sidecar collector:** OTel collector sidecar in sandbox pod scrapes supervisor logs.

### Q5.2: How does Kagenti get LLM usage data from the supervisor proxy?

**Status:** OPEN

The supervisor's HTTP CONNECT proxy handles LLM egress but doesn't instrument
token counts, latency, or cost. Kagenti tracks these via `LlmUsagePanel`.

**Candidates:**
1. **Proxy-level instrumentation:** Upstream — supervisor proxy emits OTLP spans with
   token counts extracted from HTTP response bodies.
2. **Agent-side instrumentation:** Each agent SDK (ADK, Anthropic) emits its own spans.
   Already partially implemented in agent code.
3. **LiteLLM tracking:** LiteLLM records all requests. Kagenti reads from LiteLLM's DB.

### Q5.3: OCSF vs Kagenti event schema for audit trail?

**Status:** OPEN

OpenShell uses OCSF (Open Cybersecurity Schema Framework). Kagenti uses custom
event schema stored in PostgreSQL.

**Candidates:**
1. **OCSF everywhere:** Kagenti adopts OCSF for audit events. More industry-standard.
2. **Kagenti schema everywhere:** OpenShell exports events in Kagenti's format.
3. **Dual export:** Both formats via adapters. Most flexible, most complex.

---

## 6. Multi-Tenancy and Lifecycle

### Q6.1: Should Kagenti operator manage per-tenant gateway lifecycle?

**Status:** OPEN

The proposal recommends gateway-per-tenant (one gateway per team namespace).

**Candidates:**
1. **Operator-managed:** Kagenti operator creates gateway StatefulSet per namespace.
   AgentRuntime CR triggers gateway provisioning.
2. **Helm-per-team:** Each team onboarded via `helm install openshell-team-X`.
3. **Shared gateway:** Single gateway with namespace-scoped RBAC (needs upstream multi-tenancy).

### Q6.2: Sandbox garbage collection and TTL?

**Status:** OPEN

Orphaned PVCs and Sandbox CRs accumulate. No automatic cleanup exists.

**Candidates:**
1. **CronJob cleanup:** Per-namespace CronJob deletes sandboxes older than TTL.
2. **Operator finalizers:** Kagenti operator adds finalizers to Sandbox CRs for cleanup.
3. **Gateway TTL:** Upstream — gateway auto-deletes sandboxes after configurable timeout.

### Q6.3: AgentTask CRD vs AgentRuntime CRD?

**Status:** OPEN

The proposal introduces AgentTask CRD for headless agents. Kagenti has AgentRuntime CRD.

**Recommendation:** Extend AgentRuntime CRD with a `mode: headless` field rather
than creating a separate CRD. Avoids CRD proliferation.

### Q6.4: Supervisor-gateway version consistency?

**Status:** ANSWERED

Current state: version `0.0.0`, all images use `:latest`. Tight coupling exists
via gRPC protobuf — supervisor and gateway must match versions.

**Answer:** Pin to git SHA tags. Init container approach makes this easy — Helm
chart controls both supervisor and gateway image tags.

---

## 7. Testing Hurdles

### Q7.1: How to test OPA egress blocking without `curl`?

**Status:** ANSWERED (fixed)

The supervised agent pod doesn't have `curl` installed. Use `python3 -c "import urllib.request; ..."` instead — python3 is available in all agent images.

**Impact:** Fixes `test_hitl__opa_denies_unauthorized_egress` (was failing).

### Q7.2: How to test openshell_opencode skill execution with LiteMaaS?

**Status:** INVESTIGATING

OpenCode uses OpenAI-compatible API. LiteMaaS provides that endpoint. The gateway
has `OPENAI_API_KEY` + `OPENAI_BASE_URL` env vars set by the fulltest script.

**Hurdles:**
1. Need to verify gateway's provider auto-discovery injects credentials into sandbox pods
2. Need to create a sandbox with OpenCode and send a skill prompt via ExecSandbox or kubectl exec
3. OpenCode may need specific config files (`.opencode/config.yaml`) to use the provider

**Investigation path:**
- Create a sandbox with the base image
- `kubectl exec` into it and check `env | grep OPENAI` to see if credentials are injected
- Try running `opencode --help` to understand CLI flags for non-interactive mode
- If credentials are injected, try `echo "review this code: def f(x): eval(x)" | opencode`

**Impact:** Would enable 3 `openshell_opencode` skill tests.

### Q7.3: How to test context continuity without backend session store?

**Status:** BLOCKED (needs Kagenti backend work) | **Related:** Q4.1 (architecture decision)

No agent preserves contextId across requests. The ADK agent creates a new contextId
per request (upstream `to_a2a()` behavior).

**Workaround options:**
1. **Backend session store:** Kagenti backend reconstructs context from DB each turn.
   This is the long-term solution (Phase 2).
2. **Agent-side history in prompt:** Include prior conversation in each A2A request text.
   Quick hack: `a2a_send(url, f"Previous: {history}\n\nNew: {msg}")`.
   Test would verify agent references prior context in response.
3. **ADK session fixture:** Use ADK's built-in session management (not exposed via to_a2a).

**Impact:** Would enable 4 `test_context_continuity` tests.

### Q7.4: How to test PVC data persistence across sandbox restarts?

**Status:** TESTED (partial — gated behind OPENSHELL_DESTRUCTIVE_TESTS)

The `test_resume__generic_sandbox__write_delete_recreate_read` test works but is
gated because it deletes sandbox pods. The `test_workspace_read` test skips if
the gateway doesn't recreate the pod fast enough.

**Hurdles:**
1. Sandbox controller may not recreate pods automatically after CR re-apply
2. Base image pull (1.1GB) takes time on first run
3. PVC binding is `WaitForFirstConsumer` — PVC stays Pending until a pod references it

**Investigation path:**
- Pre-pull base image in fulltest script (already done)
- Increase timeout for pod recreation (from 15s to 60s)
- Verify Sandbox controller reconciles after CR re-apply

**Impact:** Would enable `test_workspace_read__generic` and `test_resume__generic_sandbox`.

### Q7.5: How to test supervised agent connectivity without port-forward?

**Status:** OPEN

The supervisor's network namespace blocks `kubectl port-forward`. A2A tests
require port-forward to reach agents from the test runner.

**Candidates:**
1. **kubectl exec:** Test via `kubectl exec` into the supervised pod, not port-forward.
   Already used for HITL and supervisor enforcement tests.
2. **Test runner pod:** Run pytest from inside the cluster as a Job. Pods can reach
   ClusterIP services directly — no port-forward needed.
3. **Supervisor proxy port:** Upstream — supervisor exposes agent port through the
   OPA proxy (not yet supported).

**Impact:** Would enable `test_agent_card__weather_supervised` and
`test_context_isolation__weather_supervised`.

### Q7.6: How to test Claude Code native skill execution?

**Status:** BLOCKED (needs real Anthropic API key)

Claude Code CLI validates model names against Anthropic's model catalog. It cannot
use LiteMaaS (which provides llama-scout-17b, not a Claude model).

**Candidates:**
1. **Real Anthropic key:** Provide `ANTHROPIC_API_KEY` as a CI secret. Most direct.
2. **Mock API:** Deploy a mock Anthropic API that accepts any model name. Complex.
3. **OpenCode instead:** Test native skill execution with OpenCode (uses OpenAI format,
   works with LiteMaaS). OpenCode can also read `.claude/skills/` if configured.

**Impact:** Would enable 3 `openshell_claude` skill tests. The OpenCode alternative
would enable 3 `openshell_opencode` tests instead — similar validation value.

### Q7.7: How to enable destructive tests in CI safely?

**Status:** OPEN

Destructive tests (scale-down/up) are gated behind `OPENSHELL_DESTRUCTIVE_TESTS=true`
because they kill session-scoped port-forward fixtures.

**Candidates:**
1. **Separate test run:** CI runs non-destructive tests first, then destructive tests
   in a second pytest invocation. Port-forwards are fresh for each run.
2. **Test runner pod:** Run tests from inside the cluster. No port-forward needed.
3. **Port-forward resilience:** Make port-forward fixtures reconnect after agent restart.
   Complex — kubectl port-forward doesn't support reconnection.

**Impact:** Would enable 4 `test_restart` tests and 1 `test_resume` test.

---

## 8. Upstream Dependencies — What Waits on OpenShell Rearchitecture

### Q8.1: Can custom A2A agents use OpenShell credential management today?

**Status:** ANSWERED (2026-04-27) — **port-bridge sidecar implemented**

Custom A2A agents need to be accessible via K8s Service on port 8080.
The supervisor's netns blocks this. Solved with a port-bridge sidecar:

```yaml
- name: port-bridge
  image: python:3.12-slim
  command: ["python3", "-c"]
  args: ["<TCP forwarder: 0.0.0.0:8080 → 10.200.0.2:8080>"]
```

**Validated:** `adk-agent-supervised` runs LLM skill tests (PR review,
RCA, security review) through the port-bridge on both Kind and HyperShift.
All 3 skill tests pass under full supervisor security (Landlock + seccomp +
netns + OPA).

**Related:** Q1.1 (Tier 2), Q2.3 (credential model)

### Q8.2: Can builtin sandbox agents use LiteMaaS without model validation issues?

**Status:** PARTIALLY ANSWERED (2026-04-27)

| Agent | Model Validation | LiteMaaS Status | Fix |
|-------|-----------------|-----------------|-----|
| **OpenCode** | Uses `@ai-sdk/openai` (calls `/v1/responses`) | **WORKING** | `@ai-sdk/openai-compatible` provider config (calls `/v1/chat/completions`) |
| **Claude Code** | Validates against Anthropic model catalog | **BLOCKED** | Needs real Anthropic key or LiteLLM routing to real Anthropic model |

OpenCode is solved. Claude Code remains blocked because it requires the
Anthropic messages API format and validates `claude-*` model names.

### Q8.3: Does the OpenShell RFC 0001 rearchitecture address these blockers?

**Status:** INVESTIGATING

[RFC 0001](https://github.com/NVIDIA/OpenShell/pull/836) introduces:
- Pluggable compute drivers (Kagenti as driver)
- Pluggable credential backends (K8s Secrets, Vault)
- Composable subsystems (compute, credentials, identity, sandbox identity)

This architecture would enable:
- Kagenti-managed credential injection without supervisor netns issues
- Model routing through the credential subsystem
- Custom compute drivers that don't create netns when not needed

**Impact:** Would resolve Q8.1 and Q8.2 cleanly.

### Q8.4: What upstream PRs exist for our blockers?

**Status:** ANSWERED (2026-04-24 research)

| Blocker | Upstream Status | PR | Notes |
|---------|----------------|-----|-------|
| Port exposure for A2A+supervisor | **No PRs** | N/A | PR #867 (merged) removed direct gateway→sandbox; arch is outbound-only |
| Model ID rewriting | **Closed PR** | #618 | Proposed per-request model aliases; closed. Merged approach: static model binding |
| Provider injection for Sandbox CRs | **Implemented** | Production | Works when sandbox created via gateway (has OPENSHELL_SANDBOX_ID) |
| RFC 0001 rearchitecture | **Open** | #836 | Documentation RFC, not feature implementation |

**Key finding:** Provider injection (blocker 3) is already solved upstream.
Our tests create Sandbox CRs via kubectl which bypasses the gateway. Creating
via gateway's `CreateSandbox` gRPC would give us credential injection for free.

**Action items:**
1. Port bridge sidecar: Kagenti contribution (no upstream changes needed)
2. Model rewriting: Use LiteLLM model aliases as workaround
3. Sandbox creation: Use gateway `CreateSandbox` gRPC instead of kubectl

### Q8.5: How to enable OpenCode skill execution in builtin sandboxes?

**Status:** ANSWERED (2026-04-27) — **working, 3 tests pass**

OpenCode's built-in `@ai-sdk/openai` provider calls `/v1/responses`, which
LiteMaaS doesn't support. The fix uses `@ai-sdk/openai-compatible` provider
which calls `/v1/chat/completions` instead.

**Solution implemented:**
1. Deploy LiteLLM v1.83.10 with model aliases + `use_chat_completions_api: true`
2. Sandbox gets virtual key from `litellm-virtual-keys` (secretKeyRef)
3. Test helper writes `$HOME/.config/opencode/config.json` with:
   ```json
   {"provider":{"litellm":{"npm":"@ai-sdk/openai-compatible",
     "options":{"baseURL":"http://litellm-model-proxy.team1.svc:4000/v1"},
     "models":{"gpt-4o-mini":{}}}}}
   ```
4. Runs: `opencode run -m litellm/gpt-4o-mini "<prompt>"`

**Results:** PR review, RCA, security review all PASS on Kind.

Sources: [OpenCode providers docs](https://opencode.ai/docs/providers),
[LiteLLM /responses docs](https://docs.litellm.ai/docs/response_api)

**Related:** Q3.1 (inference routing), Q2.3 (credential model), Q1.1 (Tier 1)

---

## 9. AuthBridge + Supervisor Integration

### Q9.1: How should AuthBridge and the OpenShell supervisor coexist in Tier 2 agents?

**Status:** OPEN (architecture decision) | **Related:** Q1.1 (tiers), Q2.3 (credential model)

AuthBridge (Kagenti's [identity sidecar](../authbridge-combined-sidecar.md))
and the OpenShell supervisor provide complementary security layers:
- AuthBridge: inbound JWT validation, outbound token exchange, SPIFFE identity
- Supervisor: Landlock, seccomp, netns, OPA egress filtering, credential injection

They cannot currently coexist because:
1. AuthBridge's `proxy-init` installs iptables rules in the pod's default netns
2. The supervisor moves the agent into a separate netns (10.200.0.2)
3. Inbound traffic hits AuthBridge but can't reach the agent in the supervisor's netns
4. Outbound credential injection conflicts: supervisor strips headers, AuthBridge injects tokens

**Current PoC fix:** Supervised agents use `kagenti.io/inject: disabled` to
prevent AuthBridge injection. This means supervised agents have no inbound
JWT validation, no SPIFFE identity, and no outbound token exchange.

**Resolution paths:**
- **A) Supervisor `--setup-only`:** Landlock + seccomp only, no netns. AuthBridge handles networking.
- **B) Socat bridge:** Keep netns, bridge traffic through socat sidecar. Configure AuthBridge upstream.
- **C) RFC 0001 plugin:** AuthBridge becomes a supervisor subsystem (long-term).

See [sandboxing-layers.md § AuthBridge + Supervisor Integration](sandboxing-layers.md#authbridge--supervisor-integration-phase-3) for the full analysis.

### Q9.2: Should AuthBridge replace the OPA proxy for egress control?

**Status:** OPEN | **Related:** Q9.1

AuthBridge's Envoy already intercepts all outbound traffic. It could serve
as the egress policy enforcement point via `ext_authz` with OPA, eliminating
the need for the supervisor's netns-based OPA proxy entirely.

**Advantages:**
- No netns conflict — single network namespace
- AuthBridge adds token exchange on top of OPA allow/deny
- OTel spans on every egress request (observability)
- Works with Istio ambient mesh (standard pod networking)

**Disadvantages:**
- Moves egress control from supervisor (kernel-enforced) to sidecar (userspace)
- Agent could bypass Envoy by speaking raw TCP (supervisor's netns prevents this)
- Requires OPA policy format compatible with ext_authz (different from supervisor's Rego)

### Q9.3: How does AuthBridge's token exchange interact with the supervisor's credential injection?

**Status:** OPEN | **Related:** Q2.3 (credential model), Q3.1 (inference routing)

Two credential injection mechanisms exist:

| Mechanism | How | When | For What |
|-----------|-----|------|----------|
| **Supervisor provider injection** | Gateway stores encrypted credential, supervisor injects at runtime | Pod startup | LLM API keys (ANTHROPIC_AUTH_TOKEN, OPENAI_API_KEY) |
| **AuthBridge token exchange** | Envoy ext_proc calls Keycloak RFC 8693, gets audience-scoped token | Per-request | MCP tool auth (GitHub, Jira, Slack APIs) |

These serve different use cases:
- **LLM access:** Supervisor injects static API key (long-lived, per-provider)
- **MCP tool access:** AuthBridge exchanges short-lived audience-scoped token (per-request)

**Question:** Should LLM access eventually use AuthBridge too? If Keycloak holds
LLM provider credentials and issues audience-scoped tokens, the supervisor's
provider injection becomes unnecessary. This would unify all credential
management under Keycloak/AuthBridge.

### Q9.4: What use cases does combined AuthBridge + supervisor enable?

**Status:** INVESTIGATING

| Use Case | AuthBridge | Supervisor | Both |
|----------|-----------|-----------|------|
| Agent calls GitHub API via MCP | Token exchange → OAuth2 token | OPA policy allows github.com | Egress filtered + authenticated |
| Multi-tenant agent isolation | JWT validates team membership | Landlock restricts filesystem | Identity + sandbox |
| LLM call audit trail | OTel span with caller identity | OPA decision log | Full request lineage |
| Agent-to-agent communication | SPIFFE mTLS between pods | Egress policy allows target | Mutual auth + policy |
| CI/CD agent running in sandbox | — | Seccomp blocks dangerous syscalls | Identity + process isolation |

**Phase 3 tests:** See [e2e-test-matrix.md § AuthBridge Integration](e2e-test-matrix.md#authbridge-integration-tests-phase-3)
for the planned test matrix.

### Q9.5: Which `authbridge-unified-config` ConfigMap version is required?

**Status:** ANSWERED (2026-04-26 debugging)

The Kagenti operator webhook (`0.2.0-alpha.24`) injects sidecars expecting
`authbridge-unified-config` ConfigMap. Older clusters may have `authbridge-config`
(different name). When the ConfigMap is missing, the `envoy-proxy` container
crashes with `open /etc/authbridge/config.yaml: no such file or directory`.

**Fix for supervised agents:** Use `kagenti.io/inject: disabled` label.
**Fix for non-supervised agents:** Ensure the ConfigMap name matches the
webhook version. The Kagenti Helm chart should create both ConfigMaps
or the webhook should detect which exists.
