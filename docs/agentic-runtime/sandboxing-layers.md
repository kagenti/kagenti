# OpenShell Sandboxing Layers

> Back to [main doc](openshell-integration.md)

## Supervisor as Container Entrypoint

Each agent pod uses the OpenShell supervisor as the container entrypoint:

1. Supervisor starts (`ENTRYPOINT`)
2. Connects to OpenShell Gateway via `OPENSHELL_GATEWAY` env var
3. Reads OPA/Rego policy
4. Applies Landlock (filesystem restrictions) + custom seccomp (syscall filtering)
5. Drops all capabilities
6. Execs the agent process as a restricted child

The agent inherits kernel-enforced isolation for its entire lifetime. Normal pod
networking is preserved (no network namespace in PoC), so Istio mesh works unchanged.

### Protection layers

| Layer | Mechanism | Locked? | Reloadable? |
|-------|-----------|---------|-------------|
| **Filesystem** | Linux Landlock LSM — kernel-level path allowlist | At sandbox creation | No |
| **Network** | HTTP CONNECT proxy (forced via veth/netns) + OPA/Rego | At sandbox creation | Yes (hot-reload) |
| **Process** | Seccomp BPF — syscall allowlist | At sandbox creation | No |
| **Inference** | Credential stripping + backend injection + model ID rewriting | At sandbox creation | Yes (hot-reload) |

### Credential isolation

OpenShell implements zero-secret credential isolation. Agent env vars contain
**placeholder tokens** (`openshell:resolve:env:API_KEY`), not real secrets. The
supervisor proxy resolves placeholders to real credentials at the HTTP layer
via TLS termination before forwarding upstream.

For LLM calls, the supervisor's inference router strips agent-supplied auth
headers entirely and injects backend API keys from the gateway's credential store.

### Egress policy enforcement

| Agent | Supervisor? | OPA Enforced? | Egress |
|-------|------------|---------------|--------|
| weather-agent-supervised | Yes | Yes | Tier 2 (supervisor + port bridge) |
| weather-agent-supervised | **Yes** | **Yes** | Restricted to `*.svc.cluster.local` + LiteMaaS |
| adk-agent-supervised | Yes | Yes (supervisor enforced) | Tier 2 |
| claude-sdk-agent | No | No (policy mounted but not enforced) | **Open** |

Non-supervised agents have OPA policy files mounted at `/etc/openshell/policy.yaml`
as preparation for supervisor integration. The policies are NOT enforced until the
supervisor binary is the container entrypoint.

**Blocker for full enforcement:** The supervisor creates a network namespace
that blocks `kubectl port-forward` and K8s readiness probes. Solutions:
1. Upstream: supervisor exposes agent port through the proxy
2. Workaround: run tests from inside the cluster (test runner pod)
3. Workaround: sidecar that bridges the netns port to the pod network

## Security: Init Container Pattern (TODO)

The PoC uses `privileged: true` on the supervised agent container because
the supervisor needs `CAP_SYS_ADMIN` + `CAP_NET_ADMIN` for network namespace
creation.

**Minimum capability set** (from codebase research):

| Capability | Required for | Can be dropped? |
|------------|-------------|-----------------|
| `CAP_NET_ADMIN` | veth pairs, netns, IPs, routes | No |
| `CAP_SYS_ADMIN` | `unshare()`, `setns()`, Landlock ABI | No |
| `CAP_SYS_PTRACE` | OPA proxy process inspection | Possibly |

**Target (production):** Use an **init container** for the supervisor:

```yaml
initContainers:
- name: supervisor-init
  image: ghcr.io/nvidia/openshell/supervisor:latest
  securityContext:
    privileged: true   # Only init container is privileged
  command: ["/usr/local/bin/openshell-sandbox", "--setup-only"]

containers:
- name: agent
  image: agent:latest
  securityContext:
    allowPrivilegeEscalation: false
    capabilities:
      drop: [ALL]      # Agent has zero capabilities
```

**Requires:** Upstream OpenShell support for `--setup-only` mode.

## OpenShell RFC 0001

OpenShell is being rearchitected via [RFC 0001](https://github.com/NVIDIA/OpenShell/pull/836)
into a composable, driver-based system with four pluggable subsystems:

| Subsystem | Purpose | Kagenti Mapping |
|-----------|---------|-----------------|
| **Compute** | Sandbox lifecycle (K8s, Podman, VM) | Kagenti as compute driver (Phase 2) |
| **Credentials** | Secret resolution (Vault, K8s Secrets) | Delivers secrets to supervisor proxy |
| **Control-plane identity** | User/operator auth (mTLS, OIDC) | Keycloak OIDC |
| **Sandbox identity** | Workload identity (SPIFFE) | SPIRE |

## AuthBridge + Supervisor Integration (Phase 3)

Kagenti's [AuthBridge](../authbridge-combined-sidecar.md) and the OpenShell
supervisor provide complementary security layers. In the current PoC they
are **mutually exclusive** — supervised agents disable AuthBridge injection
via `kagenti.io/inject: disabled`. Phase 3 resolves the architectural
conflict and combines both.

### What Each Layer Provides

| Concern | AuthBridge | Supervisor | Combined Value |
|---------|-----------|-----------|----------------|
| **Inbound auth** | JWT validation (Keycloak JWKS) | — | Who can talk to the agent |
| **Egress filtering** | — | OPA/Rego policy (allow/deny by endpoint) | What the agent can reach |
| **Outbound auth** | RFC 8693 token exchange (audience-scoped) | — | How the agent authenticates to external APIs |
| **Credential injection** | — | Gateway provider injection (API keys) | Zero-trust secret delivery |
| **Workload identity** | SPIFFE SVID via SPIRE | — | Cryptographic agent identity |
| **Filesystem isolation** | — | Landlock LSM | Kernel-enforced path allowlist |
| **Syscall filtering** | — | Seccomp BPF | Dangerous syscalls blocked |
| **Network isolation** | — | netns + veth pair | Agent in separate network namespace |
| **Observability** | OTel span injection on every request | — | Distributed tracing |

### Why They Don't Work Together Today

AuthBridge's `proxy-init` installs iptables rules in the pod's default network
namespace. The supervisor then moves the agent process into a **separate network
namespace** (10.200.0.2). This breaks both directions:

```
Inbound: Caller → iptables (default netns) → Envoy → localhost:8080
                                                       ↑ agent is NOT here
                                                         agent is at 10.200.0.2:8080
                                                         in supervisor's netns

Outbound: Agent (10.200.0.2) → OPA proxy (10.200.0.1:3128)
            → exits to default netns → iptables → Envoy (token exchange)
            → upstream
            ↑ outbound COULD work (double-proxied) but credential
              injection conflicts: supervisor strips auth headers,
              Envoy injects different tokens
```

### Current Deployment: AuthBridge Disabled for Supervised Agents

Supervised agents use `kagenti.io/inject: disabled` to prevent the webhook
from injecting AuthBridge sidecars. This is correct for Phase 1 because:
- The supervisor provides its own egress control (OPA proxy)
- The supervisor provides its own credential injection (gateway providers)
- AuthBridge's iptables rules break in the supervisor's netns

| Agent | AuthBridge | Supervisor | Why |
|-------|-----------|-----------|-----|
| weather-agent-supervised | **Injected** | No | Standard Kagenti agent (Tier 3) |
| adk-agent-supervised | **Injected** | No | Standard Kagenti agent (Tier 3) |
| claude-sdk-agent | **Injected** | No | Standard Kagenti agent (Tier 3) |
| weather-supervised | **Disabled** | **Yes** | Supervisor's netns breaks AuthBridge |
| openshell sandboxes | **Not present** | **Yes** | Gateway-managed, no webhook |

### Phase 3 Resolution Paths

**Option A — Supervisor `--setup-only` mode (no netns):**
Use the supervisor only for Landlock + seccomp (filesystem + syscall isolation).
Skip netns creation. Delegate egress control to AuthBridge's Envoy with an
OPA ext_authz filter. This avoids the netns conflict entirely.

```
Pod (single netns):
  proxy-init (iptables) → Envoy (AuthBridge)
    ↳ inbound: JWT validation
    ↳ outbound: OPA ext_authz (egress filter) + token exchange
  supervisor --setup-only (Landlock + seccomp only)
  agent (restricted filesystem + syscalls, standard networking)
```

**Option B — Socat bridge + Envoy upstream rewrite:**
Keep the supervisor's netns. Add a socat bridge sidecar (`Pod:8080 → 10.200.0.2:8080`).
Configure AuthBridge's Envoy to forward validated inbound traffic to the bridge
instead of localhost. Outbound: OPA proxy forwards to Envoy for token exchange.

```
Inbound:  Caller → iptables → Envoy (JWT) → socat bridge → 10.200.0.2:8080
Outbound: Agent → OPA proxy → Envoy (token exchange) → upstream
```

**Option C — AuthBridge as supervisor plugin (RFC 0001):**
OpenShell's rearchitecture (RFC 0001) introduces pluggable subsystems. The
"Credentials" subsystem could delegate to Keycloak token exchange (AuthBridge).
The "Sandbox identity" subsystem could use SPIRE/SPIFFE. This makes AuthBridge
a native part of the supervisor rather than a separate sidecar.

### Use Cases Enabled by AuthBridge + Supervisor

| Use Case | AuthBridge Provides | Supervisor Provides |
|----------|-------------------|-------------------|
| **MCP tool auth** | OAuth2 token exchange for GitHub, Jira, Slack APIs | Egress policy limits which MCP endpoints are reachable |
| **Multi-tenant isolation** | JWT audience validation per team | Filesystem + network isolation per sandbox |
| **Audit trail** | OTel spans on every request with identity | OPA decision logs (allow/deny) |
| **Zero-trust LLM access** | Audience-scoped token for LLM provider | Credential stripping + model ID rewriting |
| **Agent-to-agent auth** | SPIFFE SVID mutual authentication | Network policy enforcement |

### Phase 3 Test Matrix

These tests become possible when AuthBridge + supervisor are combined:

| Test | Agents | What It Validates |
|------|--------|-------------------|
| `authbridge_jwt_validates_inbound` | Tier 2 | Inbound request rejected without valid JWT |
| `authbridge_token_exchange_outbound` | Tier 2 | Outbound MCP call gets audience-scoped token |
| `supervisor_egress_plus_token` | Tier 2 | OPA allows endpoint + AuthBridge adds token |
| `spiffe_identity_assigned` | Tier 2 | SPIRE issues SVID for supervised agent |
| `combined_audit_trail` | Tier 2 | OTel span + OPA decision log for same request |
| `mcp_tool_with_egress_policy` | Tier 2 | Agent calls MCP tool, OPA allows, token exchanged |

## LLM Compatibility Matrix

| Agent / CLI | LiteMaaS (llama-scout, deepseek) | Anthropic API | OpenAI API |
|-------------|----------------------------------|---------------|------------|
| **Claude CLI** (base image) | **No** — validates model name | **Yes** (native) | No |
| **Claude SDK agent** (custom) | **Yes** — OpenAI-compatible format | Yes (native SDK) | Yes |
| **ADK agent** (Google ADK) | **Yes** — via LiteLLM wrapper | N/A | Yes |
| **OpenCode** (base image) | **Yes** — OpenAI-compatible | N/A | Yes |
| **Codex** (base image) | Partial — may need real OpenAI key | N/A | Yes |
| **Copilot** (base image) | No — proprietary GitHub API | N/A | N/A |

**Key limitation:** Claude CLI requires a real Anthropic API key. Our custom
Claude SDK agent works with LiteMaaS because it uses httpx with the OpenAI
chat/completions format, bypassing Claude CLI's model validation.
