# Platform-Owned Agent Runtime — Design & Implementation Plan

> **Date:** 2026-03-04
> **Author:** Session G (design), Session N (implementation)
> **Status:** Ready for Implementation
> **PR:** #758 (feat/sandbox-agent)
> **Cluster:** Isolated HyperShift (to be created)

## 1. Vision

Kagenti provides a **framework-neutral agent runtime** where the platform owns
infrastructure (A2A server, auth, security, workspace, observability) and agents
provide only their business logic (graph, tools, LLM calls).

This is validated by deploying **two different agent frameworks** on the same
platform and proving they pass the same tests with the same features.

```mermaid
graph TB
    subgraph "Platform Layer (Kagenti-owned)"
        A2A["A2A Server<br/>(JSON-RPC 2.0, SSE)"]
        WS["Workspace Manager<br/>(per-context /workspace)"]
        SK["Skills Loader<br/>(CLAUDE.md + .claude/skills/<br/>+ custom loaders e.g. superpowers)"]
        PM["Permission Checker<br/>(allow/deny/HITL)"]
        TOFU["TOFU Verification<br/>(SHA-256 config integrity)"]
        OTEL["OTEL Instrumentation<br/>(Phoenix, MLflow)"]
        CP["Session DB<br/>(PostgreSQL checkpointer)"]
    end

    subgraph "Security Layer (sidecars, transparent)"
        AB["AuthBridge<br/>(SPIFFE + OAuth2)"]
        SQ["Squid Proxy<br/>(domain allowlist)"]
        LL["Landlock<br/>(filesystem sandbox)"]
        GV["gVisor<br/>(kernel sandbox)"]
    end

    subgraph "Orchestration Layer (optional)"
        SC["kubernetes-sigs SandboxClaim<br/>(ephemeral sandbox pods)"]
        TRIG["Trigger Controller<br/>(cron/webhook/alert → SandboxClaim)"]
    end

    SC -->|"creates"| LG
    SC -->|"creates"| OC
    TRIG -->|"triggers"| SC

    subgraph "Agent Layer (pluggable)"
        LG["LangGraph Agent<br/>(graph.py + tools)"]
        OC["OpenCode Agent<br/>(opencode serve + wrapper)"]
        CS["Claude Agent SDK<br/>(query() + wrapper)"]
        OH["OpenHands Agent<br/>(controller + wrapper)"]
    end

    A2A --> LG
    A2A --> OC
    A2A --> CS
    A2A --> OH

    AB -.->|transparent| LG
    AB -.->|transparent| OC
    SQ -.->|transparent| LG
    SQ -.->|transparent| OC
    LL -.->|transparent| LG
    LL -.->|transparent| OC

    style A2A fill:#4CAF50,color:white
    style AB fill:#3F51B5,color:white
    style SQ fill:#3F51B5,color:white
    style LL fill:#3F51B5,color:white
    style GV fill:#3F51B5,color:white
    style LG fill:#FF9800,color:white
    style OC fill:#FF9800,color:white
    style CS fill:#FF9800,color:white
    style OH fill:#FF9800,color:white
```

## 2. Architecture: The A2A Boundary

The A2A protocol is the **hard contract** between platform and agent. Everything
below it is platform infrastructure. Everything above it is agent business logic.

```mermaid
graph LR
    subgraph "User"
        UI["Kagenti UI<br/>(React)"]
    end

    subgraph "Platform Backend"
        BE["FastAPI Backend<br/>(chat proxy, session API)"]
        MCP["MCP Gateway<br/>(tool routing)"]
    end

    subgraph "Kubernetes Infrastructure"
        subgraph "Agent Pod (T3 Security)"
            direction TB
            INIT["proxy-init<br/>(iptables)"]
            ENV["envoy-proxy<br/>(AuthBridge ext-proc)"]
            SPF["spiffe-helper<br/>(SPIFFE identity)"]
            CR["client-registration<br/>(Keycloak)"]
            PROXY["squid-proxy<br/>(domain filter)"]
            AGENT["Agent Container<br/>(business logic)"]
        end
    end

    subgraph "External Services"
        KC["Keycloak<br/>(OAuth2/OIDC)"]
        LLM["LLM Provider<br/>(Llama 4 Scout)"]
        GH["GitHub<br/>(repos, PRs)"]
    end

    UI -->|"HTTP/SSE"| BE
    BE -->|"A2A JSON-RPC"| AGENT
    MCP -->|"MCP protocol"| AGENT
    ENV -->|"validate JWT"| KC
    AGENT -->|"LLM API"| LLM
    AGENT -->|"web_fetch"| GH
    PROXY -->|"filtered egress"| GH
    SPF -->|"SVID"| KC
    CR -->|"register client"| KC

    style UI fill:#2196F3,color:white
    style BE fill:#4CAF50,color:white
    style MCP fill:#4CAF50,color:white
    style AGENT fill:#FF9800,color:white
    style ENV fill:#3F51B5,color:white
    style KC fill:#9C27B0,color:white
    style LLM fill:#F44336,color:white
```

## 3. Request Flow: End-to-End

```mermaid
sequenceDiagram
    participant U as User (UI)
    participant B as Backend (FastAPI)
    participant E as Envoy (AuthBridge)
    participant A as Agent (LangGraph/OpenCode)
    participant L as LLM (Llama 4 Scout)
    participant T as Tool (shell/file/web)

    U->>B: POST /chat/stream {message, agent_name, skill}
    B->>B: Validate JWT (Keycloak)
    B->>E: Forward A2A request
    E->>E: Validate inbound JWT
    E->>A: Request (pre-validated)

    rect rgb(255, 243, 224)
        Note over A: Agent Loop (framework-specific)
        A->>A: Parse skill, build plan
        A->>L: LLM completion (with tools bound)
        L-->>A: tool_calls: [{name: "shell", args: {cmd: "ls"}}]
        A->>T: Execute tool
        T-->>A: Tool result
        A->>L: LLM completion (with tool result)
        L-->>A: Final text response
    end

    A-->>B: SSE events (tool_call, tool_result, text)
    B-->>U: SSE stream to UI

    Note over U,B: Platform handles auth, streaming, session DB
    Note over A,T: Agent handles loop, tools, LLM calls
```

## 4. Platform Base Image

The platform provides a base container image that handles all infrastructure
concerns. Agents extend it with their framework-specific code.

```mermaid
graph TB
    subgraph "kagenti-agent-base:latest"
        direction TB
        BASE["Python 3.12 + uv"]
        A2ASDK["a2a-sdk<br/>(A2A server, task store)"]
        SKILLS["skills_loader.py<br/>(CLAUDE.md + .claude/skills/<br/>+ pluggable custom loaders<br/>e.g. superpowers, org skills)"]
        WORKSPACE["workspace_manager.py<br/>(per-context dirs)"]
        PERMS["permission_checker.py<br/>(allow/deny/HITL)"]
        TOFUV["tofu.py<br/>(config integrity, optional)"]
        OTELI["OTEL instrumentation<br/>(auto-hooks)"]
        ENTRY["entrypoint.py<br/>(loads AGENT_MODULE)"]
    end

    subgraph "sandbox-legion:latest (FROM base)"
        direction TB
        GRAPH["graph.py<br/>(StateGraph + tools)"]
        TOOLS["tools: shell, file_read,<br/>file_write, web_fetch,<br/>explore, delegate"]
    end

    subgraph "opencode-agent:latest (FROM base)"
        direction TB
        OCBIN["opencode CLI binary"]
        WRAP["opencode_wrapper.py<br/>(A2A ↔ OpenCode HTTP)"]
    end

    BASE --> A2ASDK
    A2ASDK --> SKILLS
    SKILLS --> WORKSPACE
    WORKSPACE --> PERMS
    PERMS --> TOFUV
    TOFUV --> OTELI
    OTELI --> ENTRY

    ENTRY -->|"AGENT_MODULE=<br/>sandbox.graph"| GRAPH
    ENTRY -->|"AGENT_MODULE=<br/>opencode_wrapper"| WRAP

    style BASE fill:#607D8B,color:white
    style ENTRY fill:#4CAF50,color:white
    style GRAPH fill:#FF9800,color:white
    style WRAP fill:#FF9800,color:white
```

### Entrypoint Pattern

```python
# entrypoint.py (platform-owned)
import importlib, os

# Agent provides a build_graph() or build_executor() function
module_name = os.environ["AGENT_MODULE"]  # e.g., "sandbox.graph"
agent_module = importlib.import_module(module_name)

# Platform builds the A2A server around it
executor = agent_module.build_executor(
    workspace_manager=workspace_manager,
    permissions_checker=permissions_checker,
    skills_loader=skills_loader,
    sources_config=sources_config,
)

server = A2AStarletteApplication(
    agent_card=agent_module.get_agent_card(host, port),
    http_handler=DefaultRequestHandler(
        agent_executor=executor,
        task_store=PostgresTaskStore(db_url),
    ),
)
uvicorn.run(server.build(), host="0.0.0.0", port=8000)
```

## 4b. Skills Loader: Pluggable Skill Sources

The platform's Skills Loader reads skills from the workspace and injects them
into the agent's system prompt. It supports **pluggable custom loaders** for
organization-specific skill sources.

```mermaid
graph TB
    subgraph "Skills Loader (platform-owned)"
        direction TB
        CL["Core Loader<br/>CLAUDE.md + .claude/skills/"]
        SP["Superpowers Loader<br/>(brainstorming, TDD,<br/>debugging, code review)"]
        ORG["Org Skills Loader<br/>(company-specific skills<br/>from ConfigMap or git)"]
        MCP2["MCP Skill Discovery<br/>(skills from MCP servers<br/>via agent card)"]
    end

    subgraph "Skill Sources"
        WS2["/workspace/CLAUDE.md"]
        SK2["/workspace/.claude/skills/"]
        CM["ConfigMap:<br/>org-skills"]
        MCPS["MCP Server<br/>(tool → skill mapping)"]
    end

    subgraph "Output"
        SYS["System Prompt<br/>(injected into LLM)"]
        CARD["Agent Card<br/>(skills array for UI)"]
    end

    WS2 --> CL
    SK2 --> CL
    CM --> ORG
    MCPS --> MCP2

    CL --> SYS
    SP --> SYS
    ORG --> SYS
    MCP2 --> CARD

    style CL fill:#4CAF50,color:white
    style SP fill:#FF9800,color:white
    style ORG fill:#9C27B0,color:white
```

**How it works:**

1. **Core loader** — Reads `CLAUDE.md` + `.claude/skills/` from workspace (always active)
2. **Superpowers loader** — Loads brainstorming, TDD, debugging, code review skills
   from a plugin directory (Session M adding custom loader support)
3. **Org skills loader** — Loads company-specific skills from K8s ConfigMap
   (e.g., internal coding standards, deployment procedures)
4. **MCP skill discovery** — Reads skills from connected MCP servers' tool
   definitions and maps them to the agent card's skills array

When a user invokes `/rca:ci #758`, the frontend parses the skill name and sends
it in the request body. The platform loads the full skill content and prepends it
to the system prompt before calling the agent's graph.

## 5. Security Tiers with Platform Features

```mermaid
graph TB
    subgraph "T0: Development"
        T0A["Agent Container"]
        T0N["Istio Ambient mTLS"]
        T0K["Keycloak RBAC"]
    end

    subgraph "T1: Hardened Container"
        T1A["Agent Container<br/>(non-root, drop caps, seccomp)"]
        T1N["Istio Ambient mTLS"]
        T1K["Keycloak RBAC"]
    end

    subgraph "T2: Filesystem Sandbox"
        T2A["Agent Container (hardened)"]
        T2L["Landlock<br/>(FS restrictions)"]
        T2T["TOFU<br/>(hash verification)"]
        T2N["Istio + NetworkPolicy"]
    end

    subgraph "T3: Network Sandbox"
        T3A["Agent Container (hardened)"]
        T3L["Landlock + TOFU"]
        T3S["Squid Proxy<br/>(domain allowlist)"]
        T3AB["AuthBridge<br/>(SPIFFE + OAuth)"]
        T3N["Istio + NetworkPolicy"]
    end

    subgraph "T4: Kernel Sandbox (planned)"
        T4A["Agent Container (hardened)"]
        T4ALL["All T3 features"]
        T4G["gVisor runsc<br/>(syscall interception)"]
    end

    T0A -->|"add secctx"| T1A
    T1A -->|"add landlock"| T2A
    T2A -->|"add proxy"| T3A
    T3A -->|"add gvisor"| T4A

    style T0A fill:#4CAF50,color:white
    style T1A fill:#8BC34A,color:white
    style T2A fill:#FFC107,color:black
    style T3A fill:#FF9800,color:white
    style T4A fill:#F44336,color:white
    style T3AB fill:#3F51B5,color:white
    style T3S fill:#3F51B5,color:white
```

**Key:** All tiers work with ANY agent framework. Adding AuthBridge or Squid
requires ZERO changes to agent code.

### Deployment Mechanisms

Agents can be deployed via two mechanisms:

| Mechanism | What | When to Use |
|-----------|------|-------------|
| **Deployment** (default) | Standard K8s Deployment + Service | Long-running agents, always-on |
| **SandboxClaim** (optional) | kubernetes-sigs ephemeral pod | Short-lived tasks, triggered by cron/webhook/alert, auto-cleanup via TTL |

```mermaid
graph LR
    subgraph "Deployment (always-on)"
        WIZ["Wizard / API"] --> DEP["K8s Deployment"]
        DEP --> SVC["Service"]
        SVC --> ROUTE["OpenShift Route"]
    end

    subgraph "SandboxClaim (ephemeral)"
        TRIG2["Trigger<br/>(cron/webhook/alert)"] --> SC2["SandboxClaim CRD"]
        SC2 --> CTRL["SandboxClaim Controller"]
        CTRL --> POD["Ephemeral Pod<br/>(TTL-based cleanup)"]
    end

    WIZ -->|"managed_lifecycle=true"| SC2

    style DEP fill:#4CAF50,color:white
    style SC2 fill:#FF9800,color:white
    style CTRL fill:#607D8B,color:white
```

SandboxClaim enables **autonomous agent spawning**: a cron job triggers an RCA
analysis every night, a webhook triggers a code review on PR creation, an alert
triggers an incident response agent. The pod auto-destroys after TTL.

## 6. Full Platform Component Map

```mermaid
graph TB
    subgraph "Kagenti Platform"
        direction TB

        subgraph "UI Layer"
            UI["Kagenti UI<br/>(React + PatternFly)"]
            SW["SkillWhisperer<br/>(/ autocomplete)"]
            FB["FileBrowser<br/>(pod filesystem)"]
            SG["SessionGraph<br/>(DAG visualization)"]
            ALC["AgentLoopCard<br/>(expandable reasoning)"]
        end

        subgraph "Backend Layer"
            API["FastAPI Backend"]
            CHAT["Chat Proxy<br/>(SSE streaming)"]
            SESS["Session API<br/>(history aggregation)"]
            DEPLOY["Deploy API<br/>(wizard manifests)"]
            FILES["Files API<br/>(pod exec)"]
            TRIG["Trigger API<br/>(cron/webhook)"]
        end

        subgraph "Gateway Layer"
            MCPGW["MCP Gateway<br/>(tool routing)"]
            AIGW["AI Gateway<br/>(model routing)"]
            GWPOL["Gateway Policies<br/>(rate limits)"]
        end

        subgraph "Infrastructure Layer"
            KC["Keycloak<br/>(OAuth2/OIDC)"]
            SPIRE["SPIRE<br/>(workload identity)"]
            ISTIO["Istio Ambient<br/>(mTLS mesh)"]
            SHIP["Shipwright<br/>(container builds)"]
            PHX["Phoenix<br/>(LLM observability)"]
            OTELC["OTEL Collector<br/>(trace pipeline)"]
            MLF["MLflow<br/>(experiment tracking)"]
        end

        subgraph "Operator Layer"
            OP["Kagenti Operator<br/>(CRD controller)"]
            WH["Mutating Webhook<br/>(AuthBridge injection)"]
        end
    end

    subgraph "Agent Pods (namespace: team1)"
        SL["sandbox-legion<br/>(LangGraph)"]
        SB["sandbox-basic<br/>(LangGraph, no persist)"]
        SH["sandbox-hardened<br/>(T2 security)"]
        SR["sandbox-restricted<br/>(T3 security)"]
        OCA["opencode-agent<br/>(OpenCode serve)"]
        WS["weather-service<br/>(MCP tools)"]
    end

    UI --> API
    API --> CHAT
    API --> SESS
    API --> DEPLOY
    API --> FILES
    API --> TRIG

    CHAT -->|"A2A"| SL
    CHAT -->|"A2A"| OCA
    CHAT -->|"A2A"| WS
    MCPGW -->|"MCP"| WS
    WH -->|"inject sidecars"| SL
    WH -->|"inject sidecars"| OCA
    OP -->|"manage CRDs"| SL
    OTELC --> PHX
    OTELC --> MLF

    style UI fill:#2196F3,color:white
    style API fill:#4CAF50,color:white
    style MCPGW fill:#4CAF50,color:white
    style KC fill:#9C27B0,color:white
    style SL fill:#FF9800,color:white
    style OCA fill:#FF9800,color:white
    style OP fill:#607D8B,color:white
    style WH fill:#3F51B5,color:white
```

## 7. A2A Wrapper Pattern for Non-Native Agents

```mermaid
sequenceDiagram
    participant P as Platform (A2A Server)
    participant W as A2A Wrapper (~200 lines)
    participant O as OpenCode Serve (localhost:19876)
    participant L as LLM Provider

    P->>W: A2A request {contextId, message, skill}
    W->>W: Extract prompt + skill context
    W->>O: POST /sessions {prompt, skill_context}

    loop Agent Loop (OpenCode-owned)
        O->>L: LLM call (with tools)
        L-->>O: Response (text or tool_calls)
        O->>O: Execute tool if needed
        O-->>W: SSE event (tool_use, text, done)
        W->>W: Translate to A2A event
        W-->>P: A2A SSE (tool_call, tool_result, text)
    end

    O-->>W: Session complete
    W-->>P: TaskState.completed + artifacts
```

## 8. Validation Plan

### Phase 1: Platform Base Image

```
Files to create:
  deployments/sandbox/platform_base/
  ├── Dockerfile.base          # Platform base image
  ├── entrypoint.py            # Plugin loader (AGENT_MODULE)
  ├── requirements.txt         # a2a-sdk, langchain, otel
  └── test_entrypoint.py       # Unit tests
```

### Phase 2: Sandbox Legion on Platform Base

```
Changes:
  - Extract graph.py from agent-examples container into deployments/sandbox/
  - Create Dockerfile.legion (FROM kagenti-agent-base)
  - Set AGENT_MODULE=sandbox_agent.graph
  - Build + deploy on isolated cluster
  - Run existing 192 Playwright tests → must pass
```

### Phase 3: OpenCode on Platform Base

```
Files to create:
  deployments/sandbox/opencode/
  ├── Dockerfile.opencode      # FROM base + opencode binary
  ├── opencode_wrapper.py      # A2A ↔ OpenCode HTTP adapter
  └── test_wrapper.py          # Unit tests

Deploy as new variant → run Playwright tests
```

### Phase 4: Feature Parity Matrix

| Feature | Test File | Legion | OpenCode |
|---------|-----------|:------:|:--------:|
| A2A agent card | agent-catalog.spec.ts | ✓ | ✓ |
| Chat streaming | sandbox-sessions.spec.ts | ✓ | ✓ |
| Tool execution | sandbox-walkthrough.spec.ts | ✓ | ✓ |
| File browser | sandbox-file-browser.spec.ts | ✓ | ✓ |
| Session persist | sandbox-sessions.spec.ts | ✓ | ✓ |
| HITL approval | sandbox-hitl.spec.ts | ✓ | ✓ |
| Security tiers | sandbox-variants.spec.ts | ✓ | ✓ |
| Skills loading | agent-rca-workflow.spec.ts | ✓ | ✓ |
| Multi-user auth | agent-chat-identity.spec.ts | ✓ | ✓ |

## 9. Agent Wizard Integration

The wizard (SandboxCreatePage) gains a **Framework** selector:

```mermaid
graph LR
    subgraph "Wizard Step 1: Source"
        NAME["Agent Name"]
        REPO["Git Repository"]
        FW["Framework Selector<br/>● LangGraph (default)<br/>○ OpenCode<br/>○ Claude Agent SDK<br/>○ Custom"]
    end

    subgraph "Wizard Step 2: Security"
        TIER["Security Tier<br/>(T0-T3)"]
        AB2["☑ AuthBridge"]
        OTEL2["☑ Observability"]
    end

    subgraph "Generated Manifest"
        DEP["Deployment<br/>image: kagenti-agent-base<br/>env: AGENT_MODULE=..."]
        SVC["Service"]
        SEC["SecurityContext<br/>+ sidecars"]
    end

    FW -->|"langgraph"| DEP
    FW -->|"opencode"| DEP
    TIER --> SEC
    AB2 --> SEC
```

## 10. MAAS Model Compatibility

Tested 2026-03-03 on Red Hat AI Services:

| Model | tool_choice=auto | Recommended For |
|-------|:----------------:|-----------------|
| **Llama 4 Scout 17B-16E** (109B MoE) | ✅ 10/10 | Tool-calling agents (default) |
| Mistral Small 3.1 24B | ❌ 0/10 | Chat-only (no structured tool_calls with auto) |
| DeepSeek R1 Qwen 14B | ❌ | Reasoning tasks (no tool support) |
| Llama 3.2 3B | ❌ | Too small for function calling |

All clusters use **Llama 4 Scout** for sandbox agents.

## 11. Success Criteria

Session N is complete when:
1. Platform base image builds and passes unit tests
2. Sandbox Legion deploys FROM base and passes 192/196 Playwright tests
3. OpenCode deploys FROM base and passes core chat/session tests
4. Both agents work with AuthBridge (if deployed on T3)
5. Feature parity matrix shows identical platform feature coverage
6. Documentation updated with deployment instructions
