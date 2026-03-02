# Kagenti Sandbox Platform — System Design

> Architecture design for the AI agent sandbox platform.
> Research reference: [2026-02-23-sandbox-agent-research.md](2026-02-23-sandbox-agent-research.md)
> Coordination: [2026-03-01-multi-session-passover.md](2026-03-01-multi-session-passover.md)

---

## 1. System Context (C4 Level 1)

Who uses the system and what external systems does it connect to.

```mermaid
C4Context
    title Kagenti Platform — System Context

    Person(engineer, "Engineer", "Deploys agents, reviews sessions")
    Person(cibot, "CI / Webhook", "Automated triggers")

    System(kagenti, "Kagenti Platform", "Agent orchestration + sandbox execution")

    System_Ext(llm, "LLM APIs", "Claude, Mistral, GPT, Llama")
    System_Ext(git, "GitHub / GitLab", "Source repos, webhooks, PRs")
    System_Ext(obs, "Observability", "Phoenix, MLflow, OTEL")

    Rel(engineer, kagenti, "Browser + SSO")
    Rel(cibot, kagenti, "Webhook / cron trigger")
    Rel(kagenti, llm, "litellm (OpenAI-compat)")
    Rel(kagenti, git, "MCP tools, git clone")
    Rel(kagenti, obs, "OTEL traces")
```

---

## 2. Platform Containers (C4 Level 2)

Internal services that make up the platform.

```mermaid
graph LR
    subgraph UI["UI (React)"]
        sessions["Sessions Page"]
        agents["Agent Catalog"]
        integrations["Integrations"]
        sandboxes["Sandboxes"]
    end

    subgraph API["Backend (FastAPI)"]
        chat["Chat Proxy"]
        sandbox_api["Session CRUD"]
        integ_api["Integration API"]
        auth_api["Auth / RBAC"]
    end

    subgraph Agents["Sandbox Agents"]
        legion["sandbox-legion"]
        hardened["sandbox-hardened"]
        basic["sandbox-basic"]
        restricted["sandbox-restricted"]
    end

    UI -->|"REST + SSE"| API
    API -->|"A2A JSON-RPC"| Agents
```

```mermaid
graph LR
    subgraph Identity["Identity & Auth"]
        kc["Keycloak"]
        spire["SPIRE"]
        bridge["AuthBridge"]
    end

    subgraph Data["Data"]
        pg["PostgreSQL<br/>(sessions per NS)"]
        otel["OTEL Collector"]
    end

    subgraph Mesh["Service Mesh"]
        istio["Istio Ambient"]
    end

    kc -->|"JWT"| bridge
    spire -->|"SVID"| bridge
    bridge -->|"scoped token"| pg
    istio -->|"mTLS"| bridge
```

---

## 3. Session & Chat Flow

How a user message travels through the system.

```mermaid
sequenceDiagram
    actor User
    participant UI
    participant Backend
    participant Agent
    participant LLM
    participant DB as PostgreSQL

    User->>UI: Type message
    UI->>Backend: POST /sandbox/{ns}/chat/stream
    Backend->>Agent: A2A message/stream (SSE)
    Agent->>LLM: Chat completion (tools)
    LLM-->>Agent: tool_call response
    Agent->>Agent: Execute tool
    Agent-->>Backend: SSE events (status, artifact)
    Agent->>DB: Store task + history
    Backend-->>UI: SSE relay + username
    UI->>User: Render chat + tool steps
```

---

## 4. HITL Approval Flow

When an agent requests human approval for a risky operation.

```mermaid
sequenceDiagram
    actor User
    participant UI
    participant Backend
    participant Agent

    Agent-->>Backend: SSE: INPUT_REQUIRED
    Backend-->>UI: hitl_request event
    UI->>User: Show Approve / Deny card

    alt Approved
        User->>UI: Click Approve
        UI->>Backend: POST /sandbox/chat/stream
        Backend->>Agent: Resume
        Agent->>Agent: Execute tool
    else Denied
        User->>UI: Click Deny
        UI->>Backend: POST (Denied)
        Agent->>Agent: Skip tool
    else Auto-approved
        UI->>UI: Safe tool detected
        UI->>Backend: Auto-send approval
    end
```

**Status:** UI cards built, auto-approve works. `graph.resume()` wiring pending (Session C).

---

## 5. Session Ownership & RBAC

```mermaid
graph TD
    Admin["kagenti-admin"] -->|sees all| AllSessions["All Sessions"]
    Operator["kagenti-operator"] -->|sees own + shared| OwnShared["Own + namespace-shared"]
    Viewer["kagenti-viewer"] -->|sees own only| OwnOnly["Own sessions"]

    OwnShared -->|can modify| OwnOnly2["Only own sessions"]
    Admin -->|can modify| AllSessions
    Viewer -->|read only| OwnOnly
```

**Status:** Built and deployed. Owner column, visibility toggle (Private/Shared), actions restricted.

---

## 6. Agent Variants & Security Layers

Four agent variants with progressive hardening:

```mermaid
graph TD
    subgraph Variants["Deployed Agent Variants"]
        L["sandbox-legion<br/>PostgreSQL · default"]
        H["sandbox-hardened<br/>PostgreSQL · non-root · seccomp"]
        B["sandbox-basic<br/>ephemeral · hardened"]
        R["sandbox-restricted<br/>PostgreSQL · Squid proxy"]
    end

    subgraph Security["Defense-in-Depth (7 layers)"]
        S1["1. Pod: namespace RBAC + NetworkPolicy"]
        S2["2. Container: non-root, drop caps, seccomp"]
        S3["3. Kernel: Landlock (planned)"]
        S4["4. Network: Squid allowlist (planned)"]
        S5["5. Credentials: AuthBridge (SVID→token)"]
        S6["6. App: settings.json allow/deny/HITL"]
        S7["7. Attestation: Sigstore (planned)"]
    end
```

**Built:** Layers 1, 2, 5, 6. **Planned:** Layers 3, 4, 7.

---

## 7. Integrations Hub

Automated triggers that spawn sandbox agent sessions.

```mermaid
graph LR
    cron["⏰ Cron"] --> router["Event Router"]
    webhook["🔗 GitHub Webhook"] --> router
    alert["🚨 PagerDuty"] --> router
    manual["👤 Manual"] --> router

    router --> crd["Integration CRD"]
    crd --> agent["Sandbox Agent"]
    agent --> skill["Skill Execution"]
```

**Status:** UI pages built (24/24 tests pass). CRD + controller + webhook receiver pending.

---

## 8. Session Continuity (Passover)

Long-running agents need to hand off context when approaching token limits.

```mermaid
graph LR
    A["Session A<br/>msg 1-500"] -->|"80% tokens"| monitor["context_monitor"]
    monitor --> passover["passover_node"]
    passover -->|"parent_context_id"| B["Session B<br/>summary + msg 501+"]
    B -->|"80% tokens"| monitor2["context_monitor"]
    monitor2 --> C["Session C..."]
```

**Status:** `parent_context_id` field exists. Passover logic not implemented.

---

## 9. Tool Call Rendering Pipeline

How agent tool calls flow from execution to UI rendering.

```mermaid
graph LR
    agent["Agent<br/>LangGraphSerializer"] -->|"JSON events"| backend["Backend<br/>JSON parser<br/>+ regex fallback"]
    backend -->|"SSE stream"| ui["UI<br/>ToolCallStep"]

    ui --> tc["tool_call<br/>expandable block"]
    ui --> tr["tool_result<br/>collapsible output"]
    ui --> llm["llm_response<br/>italic text"]
    ui --> err["error<br/>red border"]
    ui --> hitl["hitl_request<br/>approve/deny card"]
```

**Status:** UI components built. Agent serializer not in image (Session B blocker). History ordering fixed (timestamp-based).

---

## 10. Current Status by Work Stream

| Stream | Owner | Pass/Fail | Key Blocker |
|--------|-------|-----------|-------------|
| **Identity & Sessions** | This session | ~27 pass | Multi-user needs Keycloak users (Session D) |
| **HITL Approval** | Session C | UI done | `graph.resume()` not wired |
| **Tool Call Rendering** | Session A+B | 0/4 pass | Serializer not in agent image |
| **Integrations Hub** | Session C | 24/24 pass | CRD + controller pending |
| **Source Builds** | Session B | — | Shipwright reliability |
| **Keycloak Multi-User** | Session D | 0/4 pass | Test users not provisioned |
| **Sandboxing Fixes** | New session | — | Active |
| **Catalog Tests** | This session | ~8/21 pass | Auth added, some selectors wrong |

---

## 11. Cluster Topology

```mermaid
graph TB
    subgraph AWS["AWS (us-east-1)"]
        subgraph mgmt["Management Cluster"]
            hcp["HyperShift Control Planes"]
        end

        subgraph sbox["sbox (dev)"]
            sbox_sys["kagenti-system"]
            sbox_t1["team1 (5 agents)"]
            sbox_kc["keycloak"]
        end

        subgraph sbox42["sbox42 (integration)"]
            s42_sys["kagenti-system"]
            s42_t1["team1 (5 agents)"]
            s42_kc["keycloak"]
        end

        subgraph sbox1["sbox1 (staging)"]
            s1_sys["kagenti-system"]
        end
    end

    hcp --> sbox
    hcp --> sbox42
    hcp --> sbox1
```

**All agents on Mistral** (mistral-small-24b-w8a8). Keycloak passwords randomized.
