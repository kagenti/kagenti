---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Kubernetes-Native Architecture for Dynamic Agent Composition

*Extending Rossoctl with on-demand, task-specific agent assembly from
verified components — governed, observable, and least-privilege by design.
Built on OpenShell's sandbox runtime for full workload isolation.*

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

This means the composition engine doesn't need to know how each framework
configures tools — it writes to standard paths that the sidecar translates,
while OpenShell enforces the security boundary at the kernel level.

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

Benefits:
- Clients use session IDs, not pod names — gateway handles routing
- mTLS between backend and gateway (cert-manager managed)
- Credentials driver handles OIDC token exchange via Keycloak
- Supervisor-enforced security for all sessions
- Session state survives gateway restarts (SQLite)
- Full audit trail via gateway logs and OTel traces
- Sub-sessions can be modeled (agent creates sub-agent via new session)

---

## How This Connects to Rossoctl Today

Rossoctl already has most of the building blocks:

| Component | Exists Today | Extension for Dynamic Agents |
|-----------|-------------|------------------------------|
| **OpenShell Gateway** | gRPC session management, TLS, SQLite state | Route to dynamically composed agent pods |
| **OpenShell Compute Driver** | Injects supervisor init via gateway socket | Inject composition sidecar alongside supervisor |
| **OpenShell Credentials Driver** | OIDC token exchange via Keycloak | Scope credentials per dynamic agent identity |
| **OpenShell Supervisor** | Landlock, seccomp, netns, embedded OPA | Apply security profile from component manifest |
| **Agent Sandbox Controller** | Watches Sandbox CRs → creates pods (k8s-sigs) | Shared CRD for composition requests |
| **ACP WebSocket (Backend)** | JSON-RPC 2.0 over WebSocket, ExecSandbox gRPC | Add sub-session support for orchestrator visibility |
| **LiteLLM Proxy** | Model routing and translation | Inject per-agent model config via sidecar |
| **Feature Flags** | `rossoctl_feature_flag_*` | `rossoctl_feature_flag_dynamic_composition` |
| **Teleport Script** | Package context → sandbox | Extend to package arbitrary component sets |
| **Helm Charts** | Static agent deployment | Add dynamic agent template with sidecar |

### From Teleport to Composition

The `sandbox:teleport` skill (PR #1498) is a precursor to dynamic composition:

```mermaid
flowchart LR
    subgraph TODAY["Teleport (today)"]
        direction TB
        T1["Package context"]
        T2["Deploy Sandbox CR"]
        T3["Execute + cleanup"]
        T1 --> T2 --> T3
    end

    subgraph NEXT["Session Management (next)"]
        direction TB
        N1["Snapshot active session"]
        N2["Cold store (OCI/PVC)"]
        N3["Restore / migrate harness"]
        N1 --> N2 --> N3
    end

    subgraph FUTURE["Dynamic Composition (future)"]
        direction TB
        F1["Resolve task → components"]
        F2["Sign + validate + compose"]
        F3["Deploy + lifecycle (TTL)"]
        F1 --> F2 --> F3
    end

    TODAY -->|"adds snapshot"| NEXT
    NEXT -->|"adds registry"| FUTURE

    style TODAY fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style NEXT fill:#8a6d3b,color:#fff,stroke:#666,stroke-width:2px
    style FUTURE fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px

    linkStyle default stroke:#444,stroke-width:3px
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

## Session Backup, Restore, and Migration

### The Insight: Teleport Is Bidirectional

Teleport today packages context **into** a sandbox (CLAUDE.md, skills,
settings → ConfigMap → Sandbox CR → pod). The reverse — extracting session
state **out of** a sandbox — enables powerful capabilities:

- **Cold storage**: inactive sessions don't need running pods
- **Resume from cold**: spin up a new pod, restore state, continue working
- **Cross-cluster migration**: move a session from Kind to HyperShift
- **Cross-harness migration**: start in Claude Code, continue in OpenCode or ADK

```mermaid
flowchart TB
    POD["Active Session\n(sandbox pod running)"]

    POD -->|"teleport\n--snapshot"| SNAP

    subgraph SNAP["Session Snapshot"]
        CTX["Context"]
        HIST["History"]
        FILES["Files"]
        ENV["Config"]
    end

    SNAP -->|"push"| COLD

    subgraph COLD["Cold Storage"]
        OCI["OCI Artifact"]
        PVC["PVC Snapshot"]
        OBJ["S3 / MinIO"]
    end

    COLD -->|"pull"| SNAP2["Restored Snapshot"]
    SNAP2 -->|"teleport\n--restore"| POD2["New Session\n(new pod, same state)"]

    style POD fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style POD2 fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style SNAP fill:#8a6d3b,color:#fff,stroke:#666,stroke-width:2px
    style COLD fill:#7a5c8a,color:#fff,stroke:#666,stroke-width:2px
    style SNAP2 fill:#8a6d3b,color:#fff,stroke:#666,stroke-width:2px

    linkStyle default stroke:#444,stroke-width:3px
```

Session snapshot contents:

| Layer | What's captured |
|-------|----------------|
| **Context** | CLAUDE.md, skills, settings.json |
| **History** | Conversation turns, tool calls, results |
| **Files** | Workspace files created/modified during session |
| **Config** | Model endpoints, LiteLLM config, budget state |

### What Constitutes Session State?

| Layer | Contents | Size | Portability |
|-------|----------|------|-------------|
| **Context** | CLAUDE.md, skills, settings.json | ~10-100 KB | High (already teleported) |
| **Conversation** | Turns, tool calls, results, thinking | ~100 KB-5 MB | Medium (format varies by harness) |
| **Workspace** | Files created/modified during session | ~1 KB-100 MB | High (just files) |
| **Environment** | Model endpoints, LiteLLM config, budget state | ~1 KB | High (env vars + config) |
| **Agent memory** | `.claude/memory/`, learned preferences | ~10-50 KB | Low (harness-specific) |

Context and workspace are harness-agnostic. Conversation history is the
key challenge for cross-harness migration — it needs a portable format.

### Storage Options

```mermaid
flowchart LR
    SNAP["Session Snapshot"] --> OCI["OCI Artifacts\n(recommended)"]
    SNAP --> PVC["PVC Snapshots"]
    SNAP --> OBJ["Object Storage\n(S3/MinIO)"]

    OCI --> R1["Cross-cluster\nVersioned & signed\nExisting registry"]
    PVC --> R2["Same-cluster only\nFast restore\nCSI snapshot API"]
    OBJ --> R3["Cross-cluster\nCheapest at scale\nRequires new infra"]

    style SNAP fill:#555,color:#fff,stroke:#666,stroke-width:2px
    style OCI fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style PVC fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style OBJ fill:#8a6d3b,color:#fff,stroke:#666,stroke-width:2px

    linkStyle default stroke:#444,stroke-width:3px
```

**Recommended: OCI Artifacts** as the primary format because:

1. **Registry already exists** — every K8s cluster has a container registry
2. **Signed and versioned** — aligns with the component signing principle
3. **Cross-cluster portable** — push to shared registry, pull from any cluster
4. **Fits the composition model** — a session snapshot is just another component
   in the registry, alongside tools, skills, and models
5. **Existing tooling** — `oras`, `crane`, `skopeo` all handle OCI artifacts

PVC snapshots as a **fast path** for same-cluster resume (no network transfer) —
PVC-backed workspace persistence already works today (T1.4, T2.3 tests validate
this). Object storage as a **future option** when MLflow or MinIO is already deployed.

> **Current state**: PVC workspace persistence works. Conversation state is NOT
> persisted across pod restarts (marked TODO in T2.3). OCI artifact tooling
> (oras, cosign) is not yet in the codebase — this is the primary gap to close.

### Session Lifecycle with Cold Storage

```mermaid
flowchart TB
    START((" ")) -->|"Deploy sandbox"| ACTIVE["Active"]
    ACTIVE -->|"Execute turns"| ACTIVE

    ACTIVE -->|"--snapshot"| SNAP["Snapshotting"]
    SNAP -->|"Push to registry/PVC"| COLD["Cold Storage"]

    COLD -->|"--restore"| ACTIVE
    COLD -->|"--migrate --harness"| MIG["Migrating"]
    MIG -->|"New pod, different harness"| ACTIVE

    ACTIVE -->|"Task finished"| DONE["Completed"]
    ACTIVE -->|"TTL expired"| TOUT["TimedOut"]
    TOUT -->|"Auto-snapshot"| COLD
    DONE -->|"Optional archive"| COLD

    COLD -->|"Retention expired"| END((" "))

    style ACTIVE fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style COLD fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style SNAP fill:#8a6d3b,color:#fff,stroke:#666,stroke-width:2px
    style MIG fill:#7a5c8a,color:#fff,stroke:#666,stroke-width:2px
    style TOUT fill:#8b4c4c,color:#fff,stroke:#666,stroke-width:2px
    style DONE fill:#555,color:#fff,stroke:#666,stroke-width:2px
    style START fill:#333,color:#fff,stroke:#666
    style END fill:#333,color:#fff,stroke:#666

    linkStyle default stroke:#444,stroke-width:3px
```

Key behaviors:
- **TTL auto-snapshot**: when a session's TTL expires, snapshot before deletion
  instead of losing state. The session can be resumed later from cold storage.
- **Explicit snapshot**: `teleport --snapshot --session <id>` at any time
- **Restore**: `teleport --restore --session <id>` creates a new pod with
  the snapshotted state — new pod name, same session content
- **Migration**: `teleport --migrate --session <id> --harness opencode`
  converts the portable session format to the target harness

### Cross-Harness Migration

The composition sidecar pattern already handles framework-specific config
injection. Migration extends this: the portable session format carries
the context and workspace, while the sidecar translates to the target
harness's conventions:

```mermaid
flowchart LR
    SOURCE["Source\nClaude Code"] -->|"snapshot"| PORTABLE["Portable Format\n(context + workspace\n+ history + config)"]
    PORTABLE -->|"sidecar"| CC["Claude Code\n(.claude/, CLAUDE.md)"]
    PORTABLE -->|"sidecar"| OC["OpenCode\n(.opencode/, SQLite)"]
    PORTABLE -->|"sidecar"| ADK["ADK Agent\n(checkpoint, A2A)"]

    style SOURCE fill:#3d6b8e,color:#fff,stroke:#666,stroke-width:2px
    style PORTABLE fill:#8a6d3b,color:#fff,stroke:#666,stroke-width:2px
    style CC fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style OC fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px
    style ADK fill:#4a7c59,color:#fff,stroke:#666,stroke-width:2px

    linkStyle default stroke:#444,stroke-width:3px
```

Migration layers:
1. **Context**: direct copy (CLAUDE.md, skills are harness-agnostic)
2. **Workspace**: direct copy (just files)
3. **Conversation**: needs translation (Claude Code JSON ↔ A2A turns ↔ ADK checkpoints)
4. **Memory**: best-effort (`.claude/memory/` → target format, may lose structure)

The conversation translation is the hardest part. MVP: carry context and workspace,
start a fresh conversation in the target harness with a system prompt summarizing
the prior session. Full conversation replay is a stretch goal.

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

## Relation to graph-loop Test Matrix

The graph-loop test matrix (T0-T7) validates the infrastructure that
dynamic composition depends on:

| Tier | What It Tests | Why It Matters for Composition |
|------|--------------|-------------------------------|
| T0 | Platform health | Controller, CRDs, networking must work |
| T1 | Agent connectivity | Composed agents must be reachable |
| T2 | Multi-turn conversation | Context preservation across turns, session resume |
| T3 | Skill execution | Skills are components to compose |
| T4 | Security + tenant isolation | OPA egress policy + namespace/credential isolation |
| T5 | Backend API proxy | Single ingress for all agents |
| T6 | ACP WebSocket | Session-based communication protocol |
| T7 | Teleport | Full session teleport lifecycle — precursor to composition |

Dynamic composition and session management add new tiers:

**T8: Session Backup & Restore (next)**
- Snapshot active session → OCI artifact / PVC
- Restore from cold → new pod with same workspace and context
- TTL auto-snapshot → session preserved on expiry
- Resume from cold → conversation context available
- PVC round-trip → write, delete pod, recreate, verify data

**T9: Cross-Harness Migration (future)**
- Claude Code → OpenCode: context and workspace transfer
- Portable session format → target harness sidecar translation
- Conversation summary injection on harness switch
- Skills portability across harness conventions

**T10: Composition (future)**
- Composition request → deployment created
- Privilege scoping validated
- Component signing verified
- TTL lifecycle works
- Sub-session visibility

---

*This document extends the WIP design from the Rossoctl team. Built on
Rossoctl's existing infrastructure — OpenShell (gateway, compute driver,
credentials driver, supervisor), Agent Sandbox Controller (k8s-sigs),
ACP WebSocket bridge (ExecSandbox gRPC), LiteLLM, and the teleport MVP
from PR #1498. Session backup/restore and cross-harness migration extend
the teleport pattern into a full session lifecycle management system.*
