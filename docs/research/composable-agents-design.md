---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Composable Agents: Kubernetes-Native Dynamic Agent Architecture

*On-demand assembly of task-specific agents from verified components —
governed, observable, and least-privilege by design.
Built on OpenShell's sandbox runtime for full workload isolation.*

> **Companion doc**: [Session Teleport & Management](session-teleport-and-management.md) —
> the implementation layer that uses this design for context packaging,
> session backup/restore, cross-harness migration, and the test matrix.

---

## The Problem: Static Agents Don't Scale

Static agents are predefined workloads — fixed combinations of model, prompt,
tools, skills, and permissions deployed in advance. They work well for stable
use cases but create fundamental tensions as platforms grow:

```mermaid
flowchart LR
    subgraph STATIC["Static: 1 agent per task variant"]
        direction TB
        SA["PR Review Agent\n🔧 12 tools loaded\n🔑 broad RBAC"]
        SB["RCA Agent\n🔧 12 tools loaded\n🔑 broad RBAC"]
        SC["Security Agent\n🔧 12 tools loaded\n🔑 broad RBAC"]
    end

    subgraph DYNAMIC["Dynamic: 1 engine, any task"]
        direction TB
        REQ["Task: review PR #42"] --> DA["Composed Agent\n🔧 2 tools: git, lint\n🔑 read-only repo"]
        DA --> DEL["Done → deleted"]
    end

    style STATIC fill:#8b4c4c,color:#fff,stroke:#666,stroke-width:2px
    style DYNAMIC fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style SA fill:#6b3c3c,color:#fff,stroke:#666
    style SB fill:#6b3c3c,color:#fff,stroke:#666
    style SC fill:#6b3c3c,color:#fff,stroke:#666
    style REQ fill:#3a5a3a,color:#fff,stroke:#666
    style DA fill:#3a5a3a,color:#fff,stroke:#666
    style DEL fill:#3a5a3a,color:#fff,stroke:#666

    linkStyle default stroke:#444,stroke-width:3px
```

| Problem | Static Agent | Dynamic Agent |
|---------|-------------|---------------|
| **Privilege scope** | All tools loaded, broad permissions | Only tools needed for this task |
| **Attack surface** | Large (unused tools exploitable) | Minimal (nothing extra loaded) |
| **Auditability** | Hard (which tool was actually used?) | Clear (agent = one task, one audit trail) |
| **Scalability** | N agents for N task types | 1 composition engine for any task |
| **Cost** | Always running, always allocated | Ephemeral, pay only for execution |

---

## The Solution: Dynamic Agent Composition

Instead of deploying a permanent agent for every scenario, the platform
assembles the **minimum sufficient agent** at runtime from approved components:

```mermaid
flowchart TB
    REQ["🔷 Task Request\n\nuser, workflow, or parent agent"]

    REQ ==> COMPOSE["🟢 Composition Control Plane\n\nresolve → validate → assemble"]

    subgraph REGISTRY["📦 Component Registry — signed & verified"]
        direction TB
        subgraph ROW1[" "]
            direction LR
            TOOLS["🔧 Tools\nweather, search, db"]
            SKILLS["📋 Skills\nRCA, PR review, security"]
            MODELS["🧠 Models\nllama, deepseek, claude"]
        end
        subgraph ROW2[" "]
            direction LR
            PROMPTS["💬 Prompts\nsystem, persona, guardrails"]
            POLICIES["🔒 Policies\nOPA, egress, budget"]
            PROFILES["⚙️ Runtime Profiles\nsandbox, supervised, bare"]
        end
    end

    COMPOSE ==> REGISTRY
    COMPOSE ==> AGENT["🔵 Dynamic Agent\n\nassembled for THIS task only"]

    AGENT ==> EXEC["Execute task"]
    EXEC ==> RESULT["Return result"]
    RESULT ==> TTL["🔴 TTL expires → agent deleted"]

    style COMPOSE fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style AGENT fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style TTL fill:#8b4c4c,color:#fff,stroke:#666,stroke-width:2px
    style REQ fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style REGISTRY fill:#2a2a3d,color:#fff,stroke:#666,stroke-width:2px
    style ROW1 fill:transparent,stroke:none
    style ROW2 fill:transparent,stroke:none
    style TOOLS fill:#4a7c59,color:#fff,stroke:#666,stroke-width:1px
    style SKILLS fill:#4a7c59,color:#fff,stroke:#666,stroke-width:1px
    style MODELS fill:#4a7c59,color:#fff,stroke:#666,stroke-width:1px
    style PROMPTS fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:1px
    style POLICIES fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:1px
    style PROFILES fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:1px

    linkStyle default stroke:#444,stroke-width:3px
```

The composition control plane translates task requirements into an authorized
assembly of exactly the components needed — no more, no less.

---

## Architecture: Flat Resource Model

### Why Not Hierarchical Spawning?

Most prototypes (including Claude Code's subagents) use in-process spawning —
the parent agent creates child agents as threads or subprocesses inside its
own container. This is simple but breaks enterprise requirements:

```mermaid
flowchart TB
    subgraph HIERARCHICAL["Hierarchical (rejected)"]
        direction TB
        P1["Parent Agent Container"]
        C1["child-1 (thread)"]
        C2["child-2 (thread)"]
        P1 --> C1
        P1 --> C2
    end

    subgraph FLAT["Flat Resource Model (chosen)"]
        direction TB
        CR["AgentCompositionRequest CR"]
        CP["Composition Controller"]
        ASC["Agent Sandbox Controller\n(k8s-sigs)"]
        CD["Compute Driver"]
        D1["Pod: dynamic-agent-abc"]
        D2["Pod: dynamic-agent-def"]
        CR --> CP
        CP --> ASC
        ASC --> D1
        ASC --> D2
        CD -.->|"supervisor"| D1
        CD -.->|"supervisor"| D2
    end

    style HIERARCHICAL fill:#8b4c4c,color:#fff,stroke:#666,stroke-width:2px
    style FLAT fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style P1 fill:#6b3c3c,color:#fff,stroke:#666
    style C1 fill:#6b3c3c,color:#fff,stroke:#666
    style C2 fill:#6b3c3c,color:#fff,stroke:#666
    style CR fill:#3d6b8e,color:#fff,stroke:#666
    style CP fill:#3d6b8e,color:#fff,stroke:#666
    style ASC fill:#3d6b8e,color:#fff,stroke:#666
    style CD fill:#8a6d3b,color:#fff,stroke:#666
    style D1 fill:#4a7c59,color:#fff,stroke:#666
    style D2 fill:#4a7c59,color:#fff,stroke:#666

    linkStyle default stroke:#444,stroke-width:3px
```

Each dynamic agent is a **separate Kubernetes pod** created by the
agent-sandbox-controller and hardened by the OpenShell compute driver
(supervisor injection), with:
- Its own ServiceAccount and RBAC
- Its own resource limits (CPU, memory, ephemeral storage)
- Its own network policy and egress rules (OPA via supervisor)
- OpenShell supervisor enforcing Landlock, seccomp, and network namespace isolation
- Full visibility in `kubectl`, monitoring, and audit logs
- TTL-based lifecycle management (no zombie accumulation)

### Control Plane Flow

Today's pod creation involves two components that must coordinate:
the **agent-sandbox-controller** (kubernetes-sigs, watches Sandbox CRs and creates
pods) and the **OpenShell compute driver** (injects supervisor init containers
via gateway Unix socket). A known race condition exists where both create
Services for the same pod (rossoctl#1581). The composition controller must
orchestrate both and handle this coordination:

```mermaid
sequenceDiagram
    participant Req as Requester<br/>(agent, workflow, user)
    participant API as K8s API Server
    participant Ctrl as Composition Controller
    participant Reg as Component Registry
    participant ASC as Agent Sandbox<br/>Controller (k8s-sigs)
    participant CD as Compute Driver<br/>(via gateway socket)
    participant Pod as Dynamic Agent Pod

    Req->>API: Create AgentCompositionRequest CR
    Note over API: CR specifies: task description,<br/>required capabilities,<br/>security context, TTL

    API->>Ctrl: Watch event: new CR
    Ctrl->>Reg: Resolve components<br/>(tools, model, skills, prompt)
    Reg-->>Ctrl: Signed component manifests

    Ctrl->>Ctrl: Validate permissions<br/>(requestor ⊇ agent privileges)
    Ctrl->>Ctrl: Generate Sandbox CR<br/>(sidecar, env, volumes, OPA policy)

    Ctrl->>API: Create Sandbox CR
    API->>ASC: Watch event: new Sandbox CR
    ASC->>Pod: Create pod from podTemplate
    CD->>Pod: Inject supervisor init container

    Pod->>Pod: Execute task
    Pod-->>Req: Return result (via ACP/A2A session)

    Note over Ctrl: TTL timer starts
    Ctrl->>API: Delete Sandbox CR after TTL
```

---

## Security: Least Privilege by Construction

Dynamic agents are inherently more secure than static agents because they
are assembled with **only** what the task requires:

```mermaid
flowchart TB
    subgraph SECURITY["Security Stack for Dynamic Agents"]
        direction TB
        L1["1. Component Signing\nOnly verified, signed tools/skills/models can be assembled"]
        L2["2. Privilege Scoping\nDynamic agent cannot exceed requestor's permissions"]
        L3["3. External Policy Enforcement\nOPA rules embedded in supervisor, evaluated per action"]
        L4["4. OpenShell Runtime Isolation\nSupervisor enforces Landlock, seccomp, netns per pod"]
        L5["5. Budget & TTL\nToken limits, time limits, auto-deletion"]
        L1 --> L2 --> L3 --> L4 --> L5
    end

    style L1 fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style L2 fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style L3 fill:#7a5c8a,color:#fff,stroke:#666,stroke-width:2px
    style L4 fill:#8a6d3b,color:#fff,stroke:#666,stroke-width:2px
    style L5 fill:#8b4c4c,color:#fff,stroke:#666,stroke-width:2px

    linkStyle default stroke:#444,stroke-width:3px
```

### Privilege Propagation

The critical constraint: a dynamic agent **never exceeds** the privileges
of the entity that requested it.

```mermaid
flowchart LR
    PARENT["Parent Agent\n(permissions: A, B, C, D)"]
    CHILD["Dynamic Agent\n(permissions: B, C only)"]
    PARENT -->|"request: need B, C"| CTRL["Controller"]
    CTRL -->|"validate: B ⊆ {A,B,C,D}\nC ⊆ {A,B,C,D}"| CHILD
    CTRL -->|"deny if requested > available"| DENY["Rejected"]

    style PARENT fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style CHILD fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style DENY fill:#8b4c4c,color:#fff,stroke:#666,stroke-width:2px

    linkStyle default stroke:#444,stroke-width:3px
```

---

## Creating Dynamic Agents: The Sidecar Pattern

Different agent frameworks (Claude SDK, ADK, LangGraph, CrewAI) have
different harness requirements. A **sidecar proxy** decouples the
composition engine from framework-specific details:

```mermaid
flowchart TB
    GW["OpenShell Gateway\n(gRPC, TLS)"] --> POD
    REGISTRY["Component Registry"] --> SIDECAR
    POLICY["Policy Engine"] --> SIDECAR

    subgraph POD["Dynamic Agent Pod"]
        direction TB
        INIT["OpenShell Supervisor\n(Landlock, seccomp, netns)"]
        SIDECAR["Composition Sidecar\n(tools, skills, model, prompt, OPA)"]
        AGENT["Agent Container\n(Claude Code, ADK, LangGraph, ...)"]
        INIT --> AGENT
        SIDECAR --> AGENT
    end

    style GW fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style REGISTRY fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style POLICY fill:#7a5c8a,color:#fff,stroke:#666,stroke-width:2px
    style POD fill:#2a2a3d,color:#fff,stroke:#666,stroke-width:2px
    style INIT fill:#8a6d3b,color:#fff,stroke:#666,stroke-width:2px
    style SIDECAR fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style AGENT fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px

    linkStyle default stroke:#444,stroke-width:3px
```

The sidecar handles:
- **Tool injection**: Mounting MCP server configs into the agent's filesystem
- **Skill loading**: Copying skill definitions to `.claude/skills/` or equivalent
- **Model routing**: Setting `OPENAI_API_BASE` / `ANTHROPIC_BASE_URL` to the correct LiteLLM endpoint
- **Prompt templating**: Injecting system prompts via environment or file mount
- **Policy composition**: Assembling OPA rules from component requirements into supervisor config

OpenShell provides the runtime foundation beneath the sidecar:
- **Gateway**: gRPC entry point with TLS, session state in SQLite, delegates to drivers via Unix socket
- **Compute driver**: Injects supervisor binary as init container into pods created by the
  agent-sandbox-controller (communicates with gateway via `/run/drivers/compute.sock`)
- **Credentials driver**: Exchanges OIDC tokens via Keycloak for sandbox authentication
- **Supervisor binary**: Injected as init container, enforces Landlock filesystem restrictions,
  seccomp syscall filtering, network namespace isolation, and embedded OPA policy evaluation
  (via `--policy-rules` and `--policy-data` flags — not a separate sidecar)
- **Sandbox base images**: Pre-built container images (`ghcr.io/nvidia/openshell-community/sandboxes/base`)
  for ad-hoc sandboxes; agent-specific images built on top for production deployments

---

## Interaction: Session-Based Protocol

All agent access — interactive (SSH/terminal) and programmatic (ACP WebSocket) —
routes through the OpenShell gateway. The Rossoctl backend bridges ACP WebSocket
to the gateway's `ExecSandbox` gRPC, providing a unified session layer with
mTLS, credential injection, and audit logging:

```mermaid
sequenceDiagram
    participant Client as Client<br/>(IDE, CLI, workflow)
    participant Backend as Rossoctl Backend<br/>(ACP WebSocket)
    participant GW as OpenShell Gateway<br/>(gRPC, mTLS, SQLite)
    participant CD as Compute Driver<br/>(Unix socket)
    participant Agent as Sandbox Pod<br/>(supervisor + agent)

    Client->>Backend: ACP WebSocket connect
    Backend->>GW: gRPC: ExecSandbox (mTLS)
    GW->>CD: Route to sandbox pod
    CD->>Agent: Execute command via supervisor

    Agent-->>GW: Stream stdout/stderr/exit
    GW-->>Backend: gRPC stream
    Backend-->>Client: WebSocket stream

    Note over GW: Session state in SQLite<br/>Gateway handles credential injection<br/>Full audit trail per session
```

---

## Lifecycle: From Request to Deletion

```mermaid
flowchart TB
    START((" ")) -->|"Create CR"| REQ["Requested"]
    REQ -->|"Controller picks up"| VAL["Validating"]
    VAL -->|"Privilege check fails"| REJ["Rejected"]
    VAL -->|"Components resolved"| COMP["Composing"]
    COMP -->|"Sandbox CR generated"| DEP["Deploying"]
    DEP -->|"Pod created"| RUN["Running"]
    RUN -->|"Task finished"| DONE["Completed"]
    RUN -->|"TTL expired"| TOUT["TimedOut"]
    RUN -->|"Budget exceeded"| FAIL["Failed"]
    DONE --> CLEAN["Cleaning"]
    TOUT --> CLEAN
    FAIL --> CLEAN
    CLEAN -->|"Resources deleted"| END((" "))
    REJ -->|"CR marked failed"| END

    style RUN fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style REJ fill:#8b4c4c,color:#fff,stroke:#666,stroke-width:2px
    style FAIL fill:#8b4c4c,color:#fff,stroke:#666,stroke-width:2px
    style TOUT fill:#8a6d3b,color:#fff,stroke:#666,stroke-width:2px
    style DONE fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style CLEAN fill:#555,color:#fff,stroke:#666,stroke-width:2px
    style REQ fill:#555,color:#fff,stroke:#666
    style VAL fill:#555,color:#fff,stroke:#666
    style COMP fill:#555,color:#fff,stroke:#666
    style DEP fill:#555,color:#fff,stroke:#666
    style START fill:#333,color:#fff,stroke:#666
    style END fill:#333,color:#fff,stroke:#666

    linkStyle default stroke:#444,stroke-width:3px
```

---

## Design Principles

1. **Composition over configuration** — don't configure a big agent, compose a small one
2. **Flat over hierarchical** — every agent is a K8s pod (via Sandbox CR), not a subprocess
3. **External policy** — governance lives outside the agent process
4. **Signed components** — only verified tools, skills, models can be assembled
5. **Least privilege by construction** — dynamic agent gets exactly what it needs
6. **Session abstraction** — orchestrators use sessions, not pod details
7. **TTL by default** — dynamic agents are ephemeral, not persistent
8. **Observable by default** — OTel traces, structured logs, audit trail per agent

---

*This document defines the composable agents architecture. For the
implementation layer — teleport, session management, backup/restore,
cross-harness migration, and the test matrix — see
[Session Teleport & Management](session-teleport-and-management.md).*
