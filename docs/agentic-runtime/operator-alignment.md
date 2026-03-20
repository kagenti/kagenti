# Operator Alignment

How the Agentic Runtime connects to the kagenti-operator CRDs and what
needs to change to make agent deployment declarative.

> **Epic:** [#862 — AgentRuntime CR](https://github.com/kagenti/kagenti/issues/862)
> **Operator repo:** kagenti/kagenti-operator

---

## The Problem

The Agentic Runtime is currently **script-driven** (imperative). The
operator is **CR-driven** (declarative). They need to converge.

```mermaid
flowchart TB
    subgraph today["Today: Two Parallel Paths"]
        direction TB

        subgraph scripts["Script Path (Agentic Runtime)"]
            S1["76-deploy-sandbox-agents.sh"]
            S2["Creates Deployment + Service"]
            S3["Creates PostgreSQL StatefulSet"]
            S4["Creates Budget Proxy"]
            S5["sandbox_profile.py computes security"]
            S1 --> S2 --> S3 --> S4
            S5 --> S2
        end

        subgraph operator["CR Path (Operator)"]
            O1["AgentRuntime CR<br/><small>targetRef → Deployment</small>"]
            O2["Controller applies labels"]
            O3["AgentCard CR indexes agent card"]
            O1 --> O2
            O3 -.-> O2
        end
    end

    subgraph target["Target: Unified CR Path"]
        direction TB
        T1["Developer Deployment<br/><small>(clean, no kagenti labels)</small>"]
        T2["AgentRuntime CR<br/><small>targetRef → Deployment</small>"]
        T3["Controller manages labels + infra"]
        T4["Webhook injects sidecars"]
        T5["AgentCard indexes card + graph card"]

        T2 -->|"targetRef"| T1
        T2 --> T3
        T3 -->|"labels"| T4
        T5 -.->|"fetches"| T1
    end
```

---

## What the Operator Has Today

| CRD | Purpose | Status |
|-----|---------|--------|
| **AgentRuntime** | Declarative sidecar injection + config. `targetRef` points to a standard Deployment. | [Phase 1 PR](https://github.com/kagenti/kagenti-operator/pull/218) |
| **AgentCard** | Indexes `/.well-known/agent-card.json` from agents | Complete |
| **AgentBuild** | Source-to-image via Tekton pipelines | Complete |

> **Note:** The [consolidated design (PR #770)](https://github.com/kagenti/kagenti/pull/770)
> establishes that **AgentRuntime CR targets standard Deployments**.
> Developers deploy a clean Deployment and create an AgentRuntime CR with
> `targetRef` pointing to it. The controller applies labels, the webhook
> injects sidecars. Developer manifests stay clean.

## Deployed Structure (Controller-Managed)

**Diagram 1: Namespace layout** — What a fully controller-managed agent
namespace looks like. Shows which resources are managed by AgentRuntime CR
(agent pod with sidecars, optional egress proxy), which are per-namespace
infra (PostgreSQL, budget proxy, secrets), and which controllers manage what
from their respective system namespaces.

```mermaid
flowchart TB
    subgraph ns["team1 namespace"]
        subgraph managed_by_cr["Managed by AgentRuntime CR"]
            subgraph pod["sandbox-legion Pod"]
                AB_S["AuthBridge sidecars<br/><small>envoy-proxy :15123/:15124<br/>spiffe-helper<br/>client-registration<br/>(injected by webhook)</small>"]
                Agent["Agent Container :8000<br/><small>LangGraph reasoning loop<br/>auto-creates checkpoint tables</small>"]
            end

            EgressDep["Egress Proxy (optional)<br/><small>Squid :3128<br/>domain allowlist</small>"]
        end

        subgraph namespace_infra["Per-Namespace Infra (script/Helm today, controller future)"]
            PG["postgres-sessions<br/><small>StatefulSet :5432<br/>2 databases</small>"]
            BP["llm-budget-proxy<br/><small>Deployment :8080<br/>auto-creates budget tables</small>"]
            Secrets["Secrets<br/><small>postgres-sessions-secret<br/>litellm-virtual-keys</small>"]
            CMs["ConfigMaps<br/><small>authbridge-config<br/>envoy-config</small>"]
        end

        subgraph card["Managed by AgentCard CR"]
            AC["AgentCard CR<br/><small>indexes agent-card.json<br/>+ graph-card.json (planned)</small>"]
        end
    end

    subgraph webhook_ns["kagenti-webhook-system"]
        Webhook["Webhook Controller<br/><small>Injects sidecars into<br/>labeled pods</small>"]
    end

    subgraph operator_ns["kagenti-operator-system"]
        RuntimeCtrl2["AgentRuntime Controller<br/><small>Applies labels + config-hash<br/>to PodTemplateSpec</small>"]
        CardCtrl2["AgentCard Controller<br/><small>Fetches card from agent</small>"]
    end

    RuntimeCtrl2 -->|"labels + hash"| pod
    Webhook -->|"injects sidecars"| pod
    CardCtrl2 -->|"GET /.well-known/"| Agent
    Agent -->|"asyncpg"| PG
    BP -->|"asyncpg"| PG
    Agent -->|"HTTP"| BP
    Agent -->|"HTTP_PROXY"| EgressDep
```



## Database Access Model

### Current State: Shared User, Single Schema

**Diagram 2: Current DB access** — All components connect as the same
`kagenti` user with full access to all tables. No DB-level isolation
between agents.

```mermaid
flowchart TB
    subgraph pg["postgres-sessions.team1 (port 5432)"]
        subgraph sessions_db["Database: sessions — Schema: public"]
            T_sessions["public.sessions"]
            T_events["public.events"]
            T_tasks["public.tasks"]
            T_ckpt["public.langgraph_checkpoint"]
            T_blobs["public.langgraph_checkpoint_blobs"]
            T_writes["public.langgraph_writes"]
        end

        subgraph budget_db["Database: llm_budget — Schema: public"]
            T_calls["public.llm_calls"]
            T_limits["public.budget_limits"]
        end
    end

    User_K["DB User: kagenti<br/><small>Password: postgres-sessions-secret<br/>FULL ACCESS to all tables</small>"]

    User_K --> sessions_db
    User_K --> budget_db

    Backend["Backend"] -->|"user: kagenti"| User_K
    Agent["Agent"] -->|"user: kagenti"| User_K
    BudgetProxy["Budget Proxy"] -->|"user: kagenti"| User_K
```

**Problem:** A compromised agent can read sessions from other agents,
read budget limits, and even modify event records. No DB-level isolation.

### Target State: Schema-Per-Agent, Scoped Users

**Diagram 3: Target DB access** — Each agent gets its own PostgreSQL
schema (`{namespace}_{agent_name}`) and DB user (`kagenti_{agent}`).
Platform tables stay in `public` schema. Agents can only access their own
schema + read their own rows in `public.sessions` via Row-Level Security.

```mermaid
flowchart TB
    subgraph pg2["postgres-sessions.team1 (port 5432)"]
        subgraph sessions_db2["Database: sessions"]
            subgraph schema_shared["Schema: public (platform-owned)"]
                S_sessions["sessions<br/><small>Owner: kagenti_backend</small>"]
                S_events["events<br/><small>Owner: kagenti_backend</small>"]
            end

            subgraph schema_legion["Schema: team1_sandbox_legion"]
                L_tasks["tasks<br/><small>Owner: kagenti_legion</small>"]
                L_ckpt["langgraph_checkpoint<br/><small>Owner: kagenti_legion</small>"]
                L_blobs["langgraph_checkpoint_blobs<br/><small>Owner: kagenti_legion</small>"]
                L_writes["langgraph_writes<br/><small>Owner: kagenti_legion</small>"]
            end

            subgraph schema_rca["Schema: team1_rca_agent"]
                R_tasks["tasks<br/><small>Owner: kagenti_rca</small>"]
                R_ckpt["langgraph_checkpoint<br/><small>Owner: kagenti_rca</small>"]
            end
        end

        subgraph budget_db2["Database: llm_budget"]
            subgraph schema_budget["Schema: public"]
                B_calls["llm_calls<br/><small>Owner: kagenti_budget</small>"]
                B_limits["budget_limits<br/><small>Owner: kagenti_budget</small>"]
            end
        end
    end

    subgraph users["DB Users (scoped GRANT)"]
        U_backend["kagenti_backend<br/><small>sessions: RW public.sessions, public.events<br/>llm_budget: READ public.llm_calls</small>"]
        U_legion["kagenti_legion<br/><small>sessions: RW team1_sandbox_legion.*<br/>READ public.sessions (own context_id only via RLS)</small>"]
        U_rca["kagenti_rca<br/><small>sessions: RW team1_rca_agent.*<br/>READ public.sessions (own context_id only via RLS)</small>"]
        U_budget["kagenti_budget<br/><small>llm_budget: RW public.*</small>"]
    end

    U_backend --> schema_shared
    U_legion --> schema_legion
    U_rca --> schema_rca
    U_budget --> schema_budget
```

### Schema Naming Convention

| Component | Schema Name | Pattern |
|-----------|------------|---------|
| Platform (backend) | `public` | Fixed |
| Agent `sandbox-legion` in `team1` | `team1_sandbox_legion` | `{namespace}_{agent_name}` |
| Agent `rca-agent` in `team1` | `team1_rca_agent` | `{namespace}_{agent_name}` |
| Agent `sandbox-legion` in `team2` | `team2_sandbox_legion` | `{namespace}_{agent_name}` |
| Budget proxy | `public` (in `llm_budget` DB) | Fixed |

### DB User Access Matrix

| DB User | Created By | Sessions DB Access | LLM Budget DB Access |
|---------|-----------|-------------------|---------------------|
| `kagenti_backend` | Helm chart | `public.sessions` RW, `public.events` RW | `public.llm_calls` READ |
| `kagenti_{agent}` | Wizard / AgentRuntime controller | `{ns}_{agent}.*` RW, `public.sessions` READ (RLS: own context_id) | None |
| `kagenti_budget` | Deploy script / controller | None | `public.*` RW |

**How agents are scoped:**
- Each agent's `search_path` is set to its own schema: `SET search_path TO team1_sandbox_legion`
- Agent's checkpoint/task tables are in its own schema — invisible to other agents
- Agent can READ `public.sessions` but only rows matching its own `context_id` (via Row-Level Security)
- Agent **cannot** read other agents' checkpoints, tasks, or events

**How users are created:**
- **Current:** Helm chart creates single `kagenti` user
- **Target:** Import wizard (or AgentRuntime controller) creates per-agent user with `CREATE ROLE kagenti_{agent} WITH LOGIN PASSWORD '...'` and `GRANT` on the agent's schema
- Password stored in a per-agent Secret: `{agent}-db-secret`
- With Vault (Pillar 3): dynamic credentials replace static passwords

### Migration Path

| Phase | Schema | Users | Isolation |
|-------|--------|-------|-----------|
| **Current** | Single `public` per database | Single `kagenti` user | Application-level (context_id filtering) |
| **Phase 1** | Create `{ns}_{agent}` schemas | Single `kagenti` user with search_path | Schema-level (tables separated) |
| **Phase 2** | Same | Per-agent `kagenti_{agent}` users with GRANT | User-level (GRANT scoping) |
| **Phase 3** | Same | Same + Row-Level Security on `public.sessions` | Row-level (RLS policies) |
| **Phase 4** | Same | Vault dynamic credentials (1h TTL per pod) | Credential-level (ephemeral, auto-revoked) |

## What the Agentic Runtime Deploys Today

### Per-Namespace Resources (created by deploy script)

| Resource | Type | Purpose |
|----------|------|---------|
| `postgres-sessions` | StatefulSet + Service + PVC | Two databases: `sessions` (session/event/checkpoint tables) and `llm_budget` (call tracking + limits) |
| `postgres-sessions-secret` | Secret | Connection strings for both databases |
| `llm-budget-proxy` | Deployment + Service | Per-session token enforcement (HTTP 402) |
| `authbridge-config` | ConfigMap | Keycloak token URL, issuer, audience |
| `envoy-config` | ConfigMap | Envoy listener config for AuthBridge sidecar |
| `litellm-virtual-keys` | Secret | Per-namespace LLM API key |

### Per-Agent Resources (created by deploy script per variant)

| Resource | Type | Purpose |
|----------|------|---------|
| Agent Deployment | Deployment | Agent pod (1 replica, workspace volume) |
| Agent Service | Service | ClusterIP on port 8000 |
| Egress Proxy | Deployment + Service | **Optional** — Squid domain allowlist (only for hardened/restricted profiles) |
| Route | Route (OpenShift only) | External access with TLS edge termination |

### Database Schemas (auto-created at startup, not by scripts)

Each component creates its own tables — **the agent deploys its own DB schema**:

| Component | Database | Tables Created | Created By |
|-----------|----------|---------------|------------|
| **Backend** | `sessions` | `sessions`, `events` | Auto-migration on backend startup |
| **A2A SDK** | `sessions` | `tasks` | `DatabaseTaskStore` on first task |
| **Agent (LangGraph)** | `sessions` | `langgraph_checkpoint`, `langgraph_checkpoint_blobs`, `langgraph_writes` | `AsyncPostgresSaver.setup()` on agent startup |
| **Budget Proxy** | `llm_budget` | `llm_calls`, `budget_limits` | Auto-migration on proxy startup |

This means **8 tables across 2 databases** are auto-created by 4 different
components. No manual schema management. The operator needs to be aware that
agents bring their own schema — it's not just a pod, it's a pod that
provisions database tables on startup.

### Per-Session Resources (created at runtime by agent)

| Resource | Location | Purpose |
|----------|----------|---------|
| Workspace directory | `/workspace/{context_id}/` | Per-session file isolation |
| Workspace subdirs | `scripts/`, `data/`, `repos/`, `output/` | Organized workspace |
| Context metadata | `.context.json` | Created timestamp, TTL, disk usage |
| Checkpoint rows | `langgraph_checkpoint` table | LangGraph state snapshots for session resume |

### Skills (loaded at agent startup)

Agents clone skill repos from `SKILL_REPOS` env var at startup. Skills
are git repositories containing prompts, tools, and workflow definitions.
This is agent-side and doesn't need operator support.

## What the Agentic Runtime Adds (Not in Operator)

| Component | How It's Managed Today | Where It Should Live |
|-----------|----------------------|---------------------|
| Composable security (L4-L7) | `sandbox_profile.py` (Python, backend) | AgentRuntime CR `spec.security` |
| PostgreSQL per namespace | `76-deploy-sandbox-agents.sh` (script) | Namespace CR or AgentRuntime controller |
| LLM Budget Proxy per namespace | `76-deploy-sandbox-agents.sh` (script) | Namespace CR or AgentRuntime controller |
| Egress Proxy per agent | `sandbox_profile.py` (optional, per profile) | AgentRuntime CR `spec.security.egressProxy` |
| Agent DB schema (checkpoints) | Agent auto-creates tables on startup | Agent-side (stay — operator doesn't need to manage) |
| Budget DB schema | Budget proxy auto-creates tables on startup | Budget proxy side (stay) |
| Session DB schema | Backend auto-creates tables on startup | Backend side (stay) |
| Workspace directories | Agent creates per-session at runtime | Agent-side (stay) |
| Feature flags | Helm values → backend env → UI config | Helm values (stay) |
| Agent import wizard | Backend REST API → kubectl | Backend → creates Deployment + AgentRuntime CR |
| Event serialization | Agent-side `FrameworkEventSerializer` | Agent-side (stay) |
| AgentGraphCard | Agent-side `/.well-known/agent-graph-card.json` | AgentCard CR could index it |
| Skills loading | Agent clones git repos at startup | Agent-side (stay) |

---

## Alignment Map

### 1. Agent Deployment

```mermaid
flowchart LR
    subgraph today_deploy["Today"]
        Script["76-deploy script"] --> Deployment["kubectl create Deployment"]
        Wizard["Import Wizard API"] --> Deployment
    end

    subgraph target_deploy["Target"]
        Dep2["Deployment<br/>(clean manifest)"]
        ARCR["AgentRuntime CR<br/>targetRef → Deployment"]
        Controller["AgentRuntime Controller<br/>applies labels + hash"]
        WizardCR["Import Wizard API"] --> Dep2
        WizardCR --> ARCR
        ARCR --> Controller
    end

    today_deploy --> |"migrate"| target_deploy
```

**Today:** Scripts and the backend import wizard create raw Kubernetes
Deployments with manual `kagenti.io/*` labels.

**Target:** The import wizard creates a clean Deployment (no kagenti labels)
plus an AgentRuntime CR with `targetRef` pointing to it. The controller
applies labels and config-hash, the webhook injects sidecars.

**Changes needed:**
- Backend import wizard: `POST /sandbox/{ns}/create` → creates Deployment + AgentRuntime CR
- Deploy scripts: create Deployments + AgentRuntime CRs
- Backend agent discovery: watch AgentCard CRs (or continue DNS, both work)

### 2. AuthBridge Injection

```mermaid
flowchart LR
    subgraph today_auth["Today"]
        Label["Manual label:<br/>kagenti.io/inject: enabled"] --> Webhook["Webhook injects sidecars"]
    end

    subgraph target_auth["Target (#862)"]
        ARCR["AgentRuntime CR<br/>spec.identity"] --> Controller2["AgentRuntime Controller"]
        Controller2 --> Label2["Applies label to PodTemplateSpec"]
        Label2 --> Webhook2["Webhook injects sidecars"]
    end

    today_auth --> |"migrate"| target_auth
```

**This is well-designed in #862.** AgentRuntime CR replaces manual labels
with declarative config. The webhook behavior stays the same — only the
label management changes from manual to controller-driven.

**Our docs impact:** `security.md` should mention AgentRuntime CR as the
declarative way to configure AuthBridge instead of manual labels.

### 3. Composable Security Profiles

```mermaid
flowchart TB
    subgraph today_sec["Today: Python-driven"]
        Profile["sandbox_profile.py"]
        Profile --> |"SandboxProfile(secctx=True,<br/>landlock=True, proxy=True)"| Manifest["Builds Deployment YAML<br/>with security layers"]
    end

    subgraph target_sec["Target: CR-driven"]
        ARCR2["AgentRuntime CR"]
        ARCR2 --> |"spec.security.profile: hardened"| Controller3["Controller resolves profile"]
        Controller3 --> |"Applies layers"| Labels3["Labels + annotations<br/>on PodTemplateSpec"]
    end
```

**Gap in #862:** The AgentRuntime CR has `spec.identity` and `spec.trace`
but **no `spec.security` section** for composable layers (L4-L7). This
is critical for the Agentic Runtime.

**Proposed addition to AgentRuntime spec:**

```yaml
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: sandbox-legion
  namespace: team1
spec:
  type: agent
  targetRef:
    kind: Deployment
    name: sandbox-legion
  security:
    profile: hardened              # preset: legion|basic|hardened|restricted
    # OR individual layer toggles:
    securityContext: true           # L4: non-root, drop ALL
    landlock: true                  # L6: per-tool-call filesystem isolation
    egressProxy:                    # L7: Squid domain allowlist
      enabled: true
      allowedDomains:
        - api.github.com
        - pypi.org
  identity:
    spiffe:
      trustDomain: kagenti.io
    clientRegistration:
      provider: keycloak
      realm: kagenti
  trace:
    endpoint: otel-collector.kagenti-system:4317
    sampling:
      rate: 1.0
```

### 4. Per-Namespace Infrastructure

```mermaid
flowchart TB
    subgraph today_ns["Today: Script creates per-namespace"]
        Script2["76-deploy script"] --> PG["postgres-sessions StatefulSet"]
        Script2 --> BP["llm-budget-proxy Deployment"]
        Script2 --> Secrets["postgres-sessions-secret"]
    end

    subgraph target_ns["Target: CR or Helm manages"]
        option_a["Option A: AgentRuntime controller<br/>detects first agent in namespace<br/>→ provisions infra automatically"]
        option_b["Option B: Helm chart<br/>agent-namespaces.yaml already<br/>creates secrets + labels"]
        option_c["Option C: New AgentNamespace CR<br/>explicit namespace provisioning"]
    end
```

**Gap in #862:** No mechanism for per-namespace infrastructure (PostgreSQL,
budget proxy). The AgentRuntime CR is per-workload, not per-namespace.

**Options:**
- **A: Controller auto-provisions** — When first AgentRuntime CR is created
  in a namespace, controller ensures postgres + budget proxy exist. Simple
  but implicit.
- **B: Helm chart (current)** — `agent-namespaces.yaml` already creates
  per-namespace resources. Works but requires Helm upgrade to add namespaces.
- **C: AgentNamespace CRD** — Explicit namespace provisioning with quotas,
  features, members. Matches the TUI's `kagenti team create` flow.

**Recommendation:** Option B (Helm) for near-term, Option C for full
declarative lifecycle. Option A is too magical.

### 5. AgentCard + AgentGraphCard

```mermaid
flowchart LR
    subgraph today_card["Today"]
        Agent3["Agent exposes<br/>/.well-known/agent-card.json"]
        Graph["Agent exposes<br/>/.well-known/agent-graph-card.json"]
        Backend3["Backend fetches both<br/>via httpx at runtime"]
    end

    subgraph target_card["Target"]
        AgentCardCR["AgentCard CR<br/>indexes agent-card.json<br/>(already exists)"]
        GraphIndex["AgentCard CR also indexes<br/>agent-graph-card.json<br/>(if extension present)"]
        Backend4["Backend reads from<br/>AgentCard CR status"]
    end

    today_card --> |"migrate"| target_card
```

**The operator already indexes agent cards** via the AgentCard CRD. But
it doesn't index graph cards. The controller could check for the
`urn:kagenti:agent-graph-card:v1` extension in the agent card, fetch the
graph card endpoint, and cache it in the AgentCard status.

**Changes needed in operator:**
- AgentCard controller: if `extensions` contains graph card URI, also fetch
  `/.well-known/agent-graph-card.json` and store in `status.graphCard`
- Backend: read graph card from AgentCard CR status instead of runtime fetch

---

## What #862 Is Missing for Sandbox Agents

| Missing from #862 | Why It Matters | Priority |
|-------------------|---------------|----------|
| `spec.security.profile` | Composable L4-L7 layers (secctx, landlock, egress proxy) | P0 |
| `spec.security.egressProxy` | Per-agent Squid allowlist | P1 |
| `spec.llm.model` | Default LLM model for the agent | P1 |
| `spec.llm.budgetProxy` | Link to budget proxy service | P2 |
| `spec.workspace.storage` | EmptyDir vs PVC for workspace | P2 |
| `spec.workspace.ttlDays` | Workspace TTL | P2 |
| Per-namespace infra provisioning | PostgreSQL, budget proxy, secrets | P1 |
| Graph card indexing in AgentCard | Cache graph card in CR status | P2 |

**What #862 already covers well:**
- AuthBridge injection via labels (the core problem)
- Config hash for rolling updates (clean GitOps)
- Duck-typed targetRef (works with any workload kind)
- Identity overrides (SPIFFE trust domain, Keycloak realm)
- Trace config (OTel endpoint, sampling rate)
- Finalizer handling (graceful cleanup)

---

## What Changes on Our Side

### Docs Changes

| File | Change |
|------|--------|
| `deployment.md` | Add CR-based deployment path alongside scripts |
| `security.md` | Show AgentRuntime CR as declarative security config |
| `configuration.md` | Add AgentRuntime CR as config mechanism |
| `agents.md` | Show Deployment + AgentRuntime CRD as deployment target |
| `quickstart.md` | Keep script path (quickest for Kind dev) |

### Code Changes (Future)

| Component | Change | Priority |
|-----------|--------|----------|
| Import wizard | Create Deployment + AgentRuntime CR instead of raw Deployment | P1 |
| Backend agent discovery | Watch Agent/AgentCard CRs (optional, DNS still works) | P2 |
| Deploy scripts | Create Deployments + AgentRuntime CRs | P1 |
| `sandbox_profile.py` | Move logic to AgentRuntime controller (Go) | P2 |
| TUI `kagenti team create` | Create AgentNamespace CR (if Option C) | P2 |

---

## The Full Picture

```mermaid
flowchart TB
    subgraph user["User Actions"]
        Deploy["Deploy agent<br/>(wizard or kubectl)"]
        Config["Configure security<br/>(wizard or CR)"]
        Provision["Provision namespace<br/>(TUI or Helm)"]
    end

    subgraph workloads["Workloads"]
        Dep["Deployment<br/><small>Clean manifest,<br/>no kagenti labels</small>"]
        RuntimeCR["AgentRuntime CR<br/><small>targetRef → Deployment<br/>security, identity, trace</small>"]
        CardCR["AgentCard CR<br/><small>indexes agent-card.json<br/>+ agent-graph-card.json</small>"]
    end

    subgraph controllers["Controllers"]
        RuntimeCtrl["AgentRuntime Controller<br/><small>Applies labels + hash,<br/>provisions infra</small>"]
        CardCtrl["AgentCard Controller<br/><small>Fetches + caches<br/>agent/graph cards</small>"]
    end

    subgraph webhook_layer["Webhook"]
        Webhook["AuthBridge Webhook<br/><small>Injects sidecars at<br/>Pod CREATE time</small>"]
    end

    subgraph runtime["Runtime"]
        Pod["Agent Pod<br/><small>Agent + AuthBridge +<br/>spiffe-helper sidecars</small>"]
        Infra["Namespace Infra<br/><small>PostgreSQL, budget proxy,<br/>egress proxy</small>"]
    end

    subgraph backend_layer["Platform"]
        Backend5["Backend<br/><small>Reads AgentCard CRs<br/>Manages sessions/events</small>"]
        UI2["UI / TUI<br/><small>Renders based on<br/>graph card from CR</small>"]
    end

    Deploy --> Dep
    Deploy --> RuntimeCR
    Config --> RuntimeCR
    Provision --> Infra

    RuntimeCR -->|"targetRef"| Dep
    RuntimeCR --> RuntimeCtrl
    RuntimeCtrl -->|"labels"| Pod
    RuntimeCtrl -->|"provisions"| Infra
    Pod --> Webhook -->|"injects"| Pod
    CardCR --> CardCtrl -->|"fetches card"| Pod

    CardCtrl --> Backend5 --> UI2
```

---

## Phased Convergence

| Phase | What | Owner |
|-------|------|-------|
| **Now** | Script-based deployment works, docs describe current state | Agentic Runtime team |
| **#862 Phase 1** | AgentRuntime CRD + controller for label management | Operator team |
| **#862 Phase 2** | Webhook coordination (inject at Pod CREATE) | Extensions team |
| **Post-#862** | Add `spec.security` to AgentRuntime for composable layers | Both teams |
| **Post-#862** | Import wizard creates Deployment + AgentRuntime CR | Agentic Runtime team |
| **Post-#862** | AgentCard controller indexes graph cards | Operator team |
| **Post-#862** | Namespace provisioning (Helm or AgentNamespace CRD) | Platform team |
| **Post-#862** | `sandbox_profile.py` logic moves to AgentRuntime controller | Both teams |
