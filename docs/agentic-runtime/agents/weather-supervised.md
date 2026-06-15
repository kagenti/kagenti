# Weather Agent (Supervised)

> Back to [agent catalog](README.md) | [main doc](../openshell-integration.md)
>
> **Type:** Custom A2A
> **Framework:** LangGraph + OpenShell Supervisor
> **LLM:** None
> **Supervisor:** Yes (Landlock + seccomp + netns + OPA)
> **Sandbox Model:** Tier 2 (Deployment with supervisor — reference implementation)
> **Status:** Deployed, tested — all 4 protection layers verified

## 1. Overview

Weather agent running inside the OpenShell supervisor. Same weather functionality
as the non-supervised variant, but with all four sandboxing layers active. This
agent proves that the supervisor works on native K8s without modifications.

The supervisor is the container entrypoint — it applies Landlock filesystem
restrictions, seccomp BPF syscall filtering, network namespace isolation (veth
pair), and OPA/Rego policy enforcement before exec-ing the weather app.

## 2. Architecture

```mermaid
graph LR
    subgraph Pod["Sandbox Pod (privileged)"]
        SV["Supervisor<br/>(PID 1)"] -->|"exec"| Agent["Weather App<br/>(restricted child)"]
        SV --> LL["Landlock<br/>14+ rules"]
        SV --> SC["Seccomp<br/>BPF filter"]
        SV --> NS["netns<br/>10.200.0.1/2"]
        SV --> OPA["OPA Proxy<br/>:3128"]
    end
    Agent -.->|"via OPA proxy"| API["Open-Meteo"]
```

## 3. Files

```
deployments/openshell/agents/weather-agent-supervised/
├── Dockerfile            # Multi-stage: supervisor + weather image
├── deployment.yaml       # Deployment (privileged: true, SA: openshell-supervisor)
├── policy-data.yaml      # Filesystem + network policy
└── sandbox-policy.rego   # OPA Rego rules
```

## 4. Deployment

```bash
docker build -t weather-agent-supervised:latest \
  deployments/openshell/agents/weather-agent-supervised/
kind load docker-image weather-agent-supervised:latest --name kagenti
kubectl apply -f deployments/openshell/agents/weather-agent-supervised/deployment.yaml

# OCP: dedicated service account with privileged SCC
kubectl create serviceaccount openshell-supervisor -n team1
oc adm policy add-scc-to-user privileged -z openshell-supervisor -n team1
```

## 5. Capabilities

| Capability | Supported | Notes |
|-----------|-----------|-------|
| A2A protocol | **Yes** (via kubectl exec) | netns blocks port-forward |
| Multi-turn context | No | Stateless |
| Tool calling | **Yes** | MCP weather-tool via OPA proxy |
| Subagent delegation | No | |
| Memory/knowledge | No | |
| Skill execution | No | No LLM |
| HITL approval | **L0 (OPA)** | Unauthorized egress blocked by OPA proxy |

### Supervisor Enforcement (Verified by Tests)

| Layer | Status | Evidence |
|-------|--------|----------|
| Landlock ABI V3 | **Active** | `CONFIG:APPLYING`, `rules_applied:14+` in logs |
| Seccomp BPF | **Active** | Dangerous syscalls blocked |
| Network namespace | **Active** | veth pair 10.200.0.1/10.200.0.2 |
| OPA proxy | **Active** | Listening on 10.200.0.1:3128 |
| TLS MITM | **Active** | Ephemeral CA for L7 inspection |

## 6. Kagenti Integration

### 6.1 Communication Adapter
**kubectl exec** — netns blocks port-forward. Tests use `kubectl exec` to
verify supervisor logs and OPA enforcement. Future: ExecSandbox gRPC adapter
in Kagenti backend.

### 6.2 Observable Events

| Event | Source | Kagenti UI Component | Phase |
|-------|--------|---------------------|-------|
| Landlock setup | Supervisor logs | EventsPanel | Current (logs) |
| OPA deny/allow | Supervisor OPA proxy | HitlApprovalCard | Phase 2 |
| Network namespace | Supervisor logs | EventsPanel | Current |
| Seccomp filter | Pod spec | PodStatusPanel | Current |
| Policy draft chunks | Gateway DenialAggregator | HitlApprovalCard | Phase 3 |

### 6.3 HITL: Policy Advisor Integration

The supervised agent is the **only agent with live HITL** in the PoC:

```mermaid
sequenceDiagram
    Agent->>OPA Proxy: HTTP request (blocked host)
    OPA Proxy->>OPA Engine: evaluate policy
    OPA Engine->>OPA Proxy: DENY
    OPA Proxy->>DenialAggregator: DenialEvent
    DenialAggregator->>MechanisticMapper: flush (every 10s)
    MechanisticMapper->>Gateway: SubmitPolicyAnalysis
    Gateway->>UI: DraftPolicyUpdate (via WatchSandbox)
    UI->>Human: "Agent tried to reach example.com. Allow?"
    Human->>Gateway: ApproveDraftChunk
    Gateway->>Supervisor: New policy version
    Note over OPA Proxy: Next request to example.com: ALLOW
```

## 7. Skill Execution

**Not yet configured** — the weather-supervised agent currently has no LLM
connected, so skill tests are skipped. The supervisor itself does not prevent
LLM use — it's an isolation layer, not an LLM constraint.

All skill tests are explicitly skipped with reason `no_llm`:

| Skill | Test | Status | Reason |
|-------|------|--------|--------|
| PR Review | `test_pr_review__weather_supervised__no_llm` | **SKIP** | No LLM configured |
| RCA | `test_rca__weather_supervised__no_llm` | **SKIP** | No LLM configured |
| Security Review | `test_security_review__weather_supervised` | **SKIP** | No LLM configured |

### Enabling LLM Skills on This Agent

The weather-supervised agent uses LangGraph, which supports LLM reasoning.
To enable skill execution, add LiteLLM credentials via the supervisor's
OPA egress policy:

1. **Add LiteLLM endpoint to OPA policy** (`policy-data.yaml`):
   ```yaml
   network_policies:
     litellm:
       endpoints:
         - host: litellm-model-proxy.team1.svc.cluster.local
           port: 4000
           access: full
   ```

2. **Inject LLM env vars** (via LiteLLM virtual key or OpenShell provider):
   ```yaml
   env:
   - name: OPENAI_API_KEY
     valueFrom:
       secretKeyRef:
         name: litellm-virtual-keys
         key: api-key
   - name: OPENAI_API_BASE
     value: "http://litellm-model-proxy.team1.svc.cluster.local:4000/v1"
   ```

3. **Update agent code** to use LLM for reasoning (currently pure tool-calling)

This would create the most interesting test target: a **Tier 2 agent that
runs skills under full supervisor security** (Landlock + seccomp + netns +
OPA egress + credential isolation).

### Alternative: Supervised ADK or Claude SDK Agent

Instead of modifying the weather agent, deploy an existing LLM-capable
agent (ADK or Claude SDK) with the supervisor as entrypoint. This gives
skill execution + security enforcement without code changes to the weather
agent. The multi-stage Dockerfile pattern is already proven:

```dockerfile
FROM ghcr.io/nvidia/openshell/supervisor:latest AS supervisor
FROM adk-agent:latest
COPY --from=supervisor /usr/local/bin/openshell-sandbox /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/openshell-sandbox", "--", ...]
```

## 8. Testing Status

| Test File | Tests | Pass | Skip | Notes |
|-----------|-------|------|------|-------|
| test_08_supervisor_enforcement | 12 | 12 | 0 | All protection layers verified |
| test_09_hitl_policy | 3 | 1-2 | 1 | OPA deny/allow tested |
| test_02_a2a_connectivity | 1 | 1 | 0 | kubectl exec hello |
| test_05_multiturn | 2 | 1 | 1 | exec-based multi-turn |

## 9. Sandbox Deployment Models

| Model | Supported | Notes |
|-------|-----------|-------|
| Mode 1 + Supervisor | **Current** | Deployment with supervisor as entrypoint |
| Mode 1 (no supervisor) | Yes | Fallback: plain weather-agent |
| Mode 2: Sandbox CR | Not applicable | Not a builtin CLI agent |
