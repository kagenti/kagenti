# Agent Sandbox Research: Running Skills-Driven Coding Agents in Kubernetes Isolation

> **Date:** 2026-02-23 (updated 2026-02-25) | **Clusters:** `kagenti-hypershift-custom-lpvc`, `kagenti-team-sbox` (2 workers each, v1.33.6) | **Worktree:** `.worktrees/sandbox-agent` (branch `feat/sandbox-agent`)

## Executive Summary

This document synthesizes research across 7 open-source projects, the Kubernetes SIG agent-sandbox roadmap, the broader sandboxing landscape, and Kagenti's own prototype work to answer a concrete question: **how do we run a repo that has `CLAUDE.md` and `.claude/skills/` — the same repo an engineer operates locally with Claude Code — inside a Kubernetes-hosted sandbox with any LLM plugged in, reusing the exact same skills, under zero-trust identity and token exchange?**

The answer is a layered architecture combining:
1. **Container/microVM isolation** (gVisor, Kata, or Firecracker via kubernetes-sigs/agent-sandbox)
2. **Kernel-enforced capability restriction** (Landlock/Seatbelt via nono)
3. **Credential isolation and network filtering** (Squid proxy per paude, credential scoping per devaipod/service-gator)
4. **Git-as-trust-boundary workspace sync** (per devaipod, ai-shell, paude)
5. **Token exchange via SPIFFE/Keycloak** (Kagenti's existing SPIRE + Keycloak stack)
6. **Skills/CLAUDE.md mounted as the agent's instruction set** (repo cloned at sandbox init time)

---

## Table of Contents

1. [The Vision: Skills-Driven Agent Sandbox](#1-the-vision)
2. [Agent Sandbox Design: Required Capabilities](#2-design)
3. [Architecture: Kagenti Agent Sandbox](#3-architecture)
4. [Kagenti Prototype: What We Already Built](#4-prototype)
5. [Research: Open-Source Agent Sandbox Projects](#5-research)
   - [5.1 kubernetes-sigs/agent-sandbox](#51-kubernetes-sigsagent-sandbox)
   - [5.2 always-further/nono](#52-always-furthernono)
   - [5.3 cgwalters/devaipod](#53-cgwaltersdevaipod)
   - [5.4 arewm/ai-shell](#54-arewmai-shell)
   - [5.5 bbrowning/paude](#55-bbrowningpaude)
   - [5.6 HKUDS/nanobot](#56-hkudsnanobot)
   - [5.7 openclaw/openclaw](#57-openclawopenclaw)
6. [Broader Landscape: Commercial & Emerging Options](#6-broader-landscape)
7. [Container Runtime & OCI Standardization](#7-container-runtime)
8. [Zero-Trust Identity & Token Exchange](#8-zero-trust)
9. [Kagenti AuthBridge: Token Exchange & Observability](#9-authbridge)
10. [Mapping Projects to Architecture Layers](#10-mapping)
11. [Roadmap Alignment with kubernetes-sigs/agent-sandbox](#11-roadmap)
12. [References](#12-references)

---

## 1. The Vision: Skills-Driven Agent Sandbox {#1-the-vision}

### The Starting Point: Skills and CLAUDE.md Live in Your Repo

Teams using Claude Code today have repositories that look like this:

```
my-project/
├── CLAUDE.md              # Project instructions, coding conventions, architecture
├── .claude/skills/        # Guided workflows (deploy, test, debug, tdd, etc.)
│   ├── k8s:health/SKILL.md
│   ├── tdd:kind/SKILL.md
│   ├── git:commit/SKILL.md
│   └── ...
├── src/                   # Application source code
├── tests/                 # Test suite
├── charts/                # Helm charts
└── deployments/           # Deployment configs
```

`CLAUDE.md` encodes **organizational knowledge** — how to build, test, deploy, and debug this specific codebase. Skills encode **repeatable workflows** — guided procedures that any engineer (or agent) can follow. Together, they are the operating manual for the repository.

Today, an engineer runs `claude` in this repo locally. Claude Code reads `CLAUDE.md`, loads skills, and operates the codebase with full context. The question is: **how do we take this exact same setup and run it in a Kubernetes sandbox — both interactively (engineer-driven) and autonomously (agent-driven)?**

### Mode 1: Engineer-Driven (Claude Code in Sandbox)

The engineer wants to use Claude Code but in a sandboxed environment — either because the work involves untrusted code, because they want stronger isolation than their laptop provides, or because the codebase requires access to cluster-internal resources.

```
Engineer → Kagenti UI / CLI
    │
    ├── "Create sandbox for github.com/myorg/my-project"
    │
    ▼
Sandbox Pod (gVisor isolation)
    ├── Init: git clone → /workspace
    ├── Claude Code (or any coding agent)
    │   ├── Reads /workspace/CLAUDE.md → system prompt
    │   ├── Reads /workspace/.claude/skills/ → available workflows
    │   ├── Shell tools: grep, sed, git, python, pip (permission-controlled)
    │   └── Network: filtered via proxy (LLM API + pypi + GitHub API only)
    ├── Identity: SPIFFE SVID (zero-trust, no static tokens)
    └── Storage: PVC (persists across sessions)
```

The engineer attaches to the sandbox via SSH, web terminal, or IDE remote — similar to how [devaipod](https://github.com/cgwalters/devaipod) and [ai-shell](https://github.com/arewm/ai-shell) work locally, but Kubernetes-hosted. Changes stay in the sandbox until the engineer explicitly pulls them via git.

### Mode 2: Autonomous Agent (Cron, Alert, Webhook)

The same repo, same CLAUDE.md, same skills — but now triggered without a human in the loop:

```
Trigger (cron / alert / webhook / A2A message)
    │
    ├── "Run skill tdd:kind on PR #42"
    │   or "Run skill k8s:health on cluster lpvc"
    │   or "Fix failing CI on branch feature/x"
    │
    ▼
Sandbox Pod (gVisor isolation)
    ├── Init: git clone → /workspace (+ checkout PR branch)
    ├── Agent (any LLM via litellm)
    │   ├── Reads /workspace/CLAUDE.md → system prompt
    │   ├── Reads /workspace/.claude/skills/ → available workflows
    │   ├── Executes the requested skill autonomously
    │   ├── Shell tools: permission-controlled (settings.json)
    │   └── Network: filtered (proxy sidecar, allowlist only)
    ├── Identity: SPIFFE SVID → Keycloak token exchange → scoped GitHub access
    ├── Results: git commit + push draft PR, or A2A response, or alert update
    └── Lifecycle: auto-delete after completion (or TTL)
```

**Autonomous trigger examples:**

- **Nightly CI health check:**
  A cron fires at 2 AM. The agent runs `/rca:ci` against main — analyzes recent CI failures, identifies flaky tests and broken pipelines. If it finds issues, it runs `/tdd:ci` to write fixes, then pushes a draft PR with the diagnosis and proposed changes. The team reviews the PR in the morning.

- **Implement a GitHub Issue:**
  Someone comments `/agent implement` on Issue #234 ("Add retry logic to the API client"). The agent spawns a sandbox, clones the repo, reads the issue description, and starts working. It asks a clarifying question in the issue thread ("Should retries use exponential backoff or fixed intervals?"). The engineer replies in the issue comment. The agent reads the reply, continues, and opens a draft PR linking to #234. The conversation continues in both the issue and Slack as the engineer reviews.

- **Incident response:**
  PagerDuty fires an alert for pod crashloops in production. The agent spawns a sandbox with the cluster kubeconfig, runs `/k8s:health` and `/k8s:logs` skills, identifies the root cause (OOM on the new deployment), and posts a diagnosis to the PagerDuty incident timeline. If confident, it also prepares a resource limit fix as a draft PR.

- **PR CI failure assistance:**
  A PR's CI checks fail. GitHub sends a `check_suite` webhook. The agent spawns a sandbox, checks out the PR branch, and runs `/rca:ci` against the failed job logs. It identifies the issue — a new dependency broke an import path — and pushes a fix commit directly to the PR branch. If the fix requires a design choice (e.g., "pin to v2.3 or upgrade the caller?"), it comments on the PR asking the author. The author replies in the PR thread, the agent reads the reply, applies the chosen approach, and pushes again. CI goes green.

- **Addressing PR review feedback:**
  A reviewer leaves comments on PR #87: "This needs unit tests for the error paths" and "The retry logic should be tested against a real cluster, not just mocks." The engineer comments `/agent address-reviews`. The agent spawns a sandbox, reads all pending review comments via GitHub API (scoped token), and plans the work: it runs `/tdd:ci` to add unit tests for the error paths (local, fast), then runs `/tdd:hypershift` against the live HyperShift cluster to add an E2E test for the retry logic under real conditions. It pushes the new tests as a commit to the PR branch and replies to each review comment with what it did: "Added `test_retry_on_connection_error` and `test_retry_exhaustion` — see commit abc123" and "Added E2E test `test_retry_against_live_cluster` on HyperShift — see commit def456, CI running." The reviewer gets notified, reviews the new tests, and resolves the threads.

- **Agent-to-agent delegation:**
  A planning agent working on a feature request determines it needs test coverage. It sends an A2A message to spawn a sandbox agent with the task "Write E2E tests for the new /users endpoint following the patterns in tests/e2e/". The sandbox agent works independently, pushes results, and reports back to the planning agent.

### Why This Matters

| Property | Engineer-Driven | Autonomous Agent |
|----------|----------------|------------------|
| **Same skills/CLAUDE.md** | Yes | Yes |
| **Same isolation** | Yes | Yes |
| **Same identity model** | SPIFFE SVID | SPIFFE SVID |
| **Human in loop** | Always (interactive) | Optional (HITL for risky ops) |
| **LLM pluggable** | Claude Code (default) | Any model via litellm |
| **Lifecycle** | Long-running, persistent | Ephemeral or TTL-based |
| **Git trust boundary** | Engineer pulls changes | Agent pushes draft PR |

The key insight: **skills and CLAUDE.md are the portable instruction set**. Whether a human drives Claude Code or an autonomous agent runs on a cron, the same skills produce the same workflows. The sandbox provides the isolation, identity, and network controls regardless of who — or what — is executing.

---

## 2. Agent Sandbox Design: Required Capabilities {#2-design}

Based on the two execution modes above and research across 7 projects + 15 commercial platforms, these are the 18 capabilities a proper agent sandbox must provide. For each capability, we identify which project **to use directly** (adopt as dependency) versus which **to replicate the concept** (build our own inspired by). C18 (HITL delivery) has a dedicated deep-dive section below the matrix.

### Capability Matrix

| # | Capability | Why Needed | Best Source | Use or Replicate? |
|---|-----------|-----------|-------------|-------------------|
| **C1** | **Pod lifecycle CRD** — Sandbox creation, warm pools, shutdown policies, PVC persistence | Standard K8s API for singleton stateful agent pods; warm pools for fast provisioning | [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) | **USE** — deploy controller directly |
| **C2** | **Runtime isolation** — gVisor or Kata RuntimeClass for kernel-level separation | Untrusted LLM-generated code must not share host kernel | [gVisor](https://gvisor.dev/) via agent-sandbox [SandboxTemplate](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/extensions/api/v1alpha1/sandboxtemplate_types.go) | **USE** — RuntimeClass config |
| **C3** | **In-container kernel sandbox** — Landlock/seccomp restricting filesystem, network, syscalls | Defense-in-depth: even inside gVisor, agent process should be capability-restricted | [always-further/nono](https://github.com/always-further/nono) | **USE** — nono as agent launcher (Python bindings via PyO3) |
| **C4** | **Instruction file attestation** — verify CLAUDE.md/skills provenance before agent ingests them | Prevent poisoned instruction files from being loaded | [nono trust module](https://github.com/always-further/nono/tree/main/crates/nono/src/trust) (Sigstore) | **REPLICATE** concept — integrate with Kagenti's own signing pipeline |
| **C5** | **Network filtering** — proxy sidecar with domain allowlist (LLM API, pypi, GitHub API) | Block data exfiltration; agent cannot reach arbitrary URLs | [paude squid.conf](https://github.com/bbrowning/paude/blob/main/containers/proxy/squid.conf) | **REPLICATE** — build Squid sidecar container for Kagenti |
| **C6** | **Credential isolation** — agent never receives raw tokens; external access via scoped proxy | Prevent credential theft even if agent is compromised | Kagenti [AuthBridge ext_proc](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge) (already built); concept from [devaipod service_gator.rs](https://github.com/cgwalters/devaipod/blob/main/src/service_gator.rs) | **ALREADY BUILT** — AuthBridge exchanges SVID → scoped token via Envoy ext_proc |
| **C7** | **Permission model** — three-tier allow/deny/HITL for shell commands, file ops, network | Granular control over what agent can do without human approval | Kagenti prototype ([settings.json](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/permissions.py)) | **ALREADY BUILT** — extend with more operations |
| **C8** | **Capability declaration** — sources.json declaring registries, domains, languages, limits | Per-agent-type resource and access boundaries | Kagenti prototype ([sources.json](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/sources.py)) | **ALREADY BUILT** |
| **C9** | **Git workspace sync** — primary repo at init + dynamic multi-repo cloning at runtime | Primary repo (with skills/config) cloned at init; additional repos cloned live by agent, controlled by sources.json allowed_remotes, authenticated via AuthBridge | [paude cli.py](https://github.com/bbrowning/paude/blob/main/src/paude/cli.py), [devaipod git.rs](https://github.com/cgwalters/devaipod/blob/main/src/git.rs) | **REPLICATE** — init container (primary) + shell tool (dynamic) + AuthBridge (auth) |
| **C10** | **Skills/CLAUDE.md loading** — parse repo instruction files into agent system prompt | Reuse existing organizational knowledge with any LLM | [nanobot context.py](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/context.py) | **REPLICATE** concept — build SkillsLoader for Kagenti |
| **C11** | **Multi-LLM pluggability** — any model via unified API (Claude, GPT, Gemini, Llama, Qwen) | Skills should work with any model, not lock to one provider | [litellm](https://github.com/BerriAI/litellm) (used by nanobot) | **USE** — litellm as LLM abstraction layer |
| **C12** | **Token exchange** — SPIFFE SVID → Keycloak → scoped access token (no static secrets) | Zero-trust identity for sandbox-to-service communication | Kagenti [AuthBridge](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge) + [identity-guide.md](https://github.com/kagenti/kagenti/blob/main/docs/identity-guide.md) | **ALREADY BUILT** — AuthBridge ext_proc does RFC 8693 exchange transparently |
| **C13** | **Observability** — OTEL traces for every agent action, GenAI semantic conventions | Audit trail, cost tracking, debugging | Kagenti [AuthBridge OTEL root spans](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge) + [components.md](https://github.com/kagenti/kagenti/blob/main/docs/components.md) | **ALREADY BUILT** — AuthBridge creates root spans with GenAI/MLflow attributes, zero agent changes |
| **C14** | **Execution approval** — allowlist + interactive approval backend for risky operations | HITL safety net for autonomous mode | Kagenti [permissions.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/permissions.py) (already built); OpenClaw's [exec-approvals.ts](https://github.com/openclaw/openclaw/blob/main/src/infra/exec-approvals.ts) for reference only — see [security lessons](#57-openclawopenclaw) | **ALREADY BUILT** — extend settings.json HITL |
| **C15** | **Config trust (TOFU)** — hash-based trust store for project configs | Prevent silent injection of malicious agent configs | [ai-shell loader.go](https://github.com/arewm/ai-shell/blob/main/internal/config/loader.go) | **REPLICATE** concept — hash verification in sandbox init |
| **C16** | **Container hardening defaults** — read-only root, all caps dropped, no network, non-root user | Security baseline for every sandbox pod | [agent-sandbox SandboxTemplate](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/extensions/api/v1alpha1/sandboxtemplate_types.go) NetworkPolicy defaults; [Anthropic secure deployment guide](https://platform.claude.com/docs/en/agent-sdk/secure-deployment) | **REPLICATE** — apply as SandboxTemplate defaults |
| **C17** | **Autonomous triggers** — cron, webhook, alert, A2A message spawning sandboxes | Agent mode 2 requires event-driven sandbox creation | [agent-sandbox SandboxClaim](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/extensions/api/v1alpha1/sandboxclaim_types.go) + [nanobot cron/service.py](https://github.com/HKUDS/nanobot/blob/main/nanobot/cron/service.py) | **BUILD** — Kagenti backend creates SandboxClaims on triggers |
| **C18** | **HITL delivery for autonomous agents** — approval requests reach authorized humans via multiple channels, responses routed back securely | Autonomous agents hitting HITL operations need a safe, authenticated way to ask a human and get a decision back | [nono ApprovalBackend trait](https://github.com/always-further/nono/blob/main/crates/nono/src/supervisor/mod.rs); A2A [`input_required` task state](https://google.github.io/A2A/#/documentation?id=task-states) | **BUILD** — multi-channel approval router (see below) |
| **C19** | **Multi-conversation isolation** — concurrent conversations on the same agent must not leak workspace, context, or state | Multi-tenant agents handle requests from different users/A2A callers simultaneously; one conversation's data must not be visible to another | Kagenti prototype ([workspace.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/workspace.py)) per-context dirs; kubernetes-sigs/agent-sandbox Sandbox-per-user | **BUILD** — pod-per-conversation (autonomous) + shared pod with per-context dirs (interactive) |
| **C20** | **Sub-agent spawning** — parent agent delegates tasks to child agents with scoped tools and skills | Complex tasks require parallel work (research, testing, implementation) with different skill sets and isolation levels | [nanobot subagent.py](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/subagent.py); LangGraph [StateGraph composition](https://langchain-ai.github.io/langgraph/); A2A delegation | **BUILD** — in-process (LangGraph asyncio) + out-of-process (A2A to separate sandbox pods) |
| **C21** | **A2A-generic session persistence** — tasks, messages, artifacts persisted at the A2A protocol level via DatabaseTaskStore, framework-agnostic | UI needs to display sessions/history for any agent regardless of framework; LangGraph-specific persistence only serves one framework | [a2a-sdk DatabaseTaskStore](https://github.com/a2aproject/a2a-python), per-namespace PostgreSQL | **USE** — a2a-sdk[postgresql] DatabaseTaskStore |

### C1: Pod Lifecycle CRD

Agents need isolated, ephemeral compute that spins up fast, shuts down automatically, and doesn't require operators to hand-craft pod specs. The Sandbox CRD provides a declarative API for this: create a Sandbox, get a locked-down pod with stable DNS, automatic expiry, and warm-pool pre-provisioning.

**How it works:** The CRD family includes four resources. **SandboxTemplate** defines the pod shape (image, RuntimeClass, resource limits, security context). **Sandbox** is a running instance — a singleton pod (replicas: 0 or 1) with a headless Service for stable DNS (`sandbox-name.namespace.svc.cluster.local`). **SandboxWarmPool** maintains pre-created Sandbox instances in a suspended state so that claiming one is sub-second. **SandboxClaim** is the request object — a controller creates a claim, the warm-pool binds it to an available Sandbox, and the pod transitions to running. Lifecycle is governed by `shutdownTime` (absolute UTC expiry) and `shutdownPolicy` (`Delete` or `Retain` for forensics).

**What we use:** [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) — deploy controller directly.

**Note on observability:** The agent-sandbox controller has its own OTEL tracing (`--enable-tracing`) for **lifecycle events** (pod creation, scheduling, shutdown) — but this is infrastructure-level, not agent-level. It does NOT create MLflow-compatible root spans, parse A2A bodies, or set GenAI semantic conventions. That remains AuthBridge's responsibility (C13). The two are complementary: agent-sandbox traces the pod lifecycle, AuthBridge traces the agent invocation.

**Relationship to other capabilities:** C2 (RuntimeClass in template), C13 (AuthBridge handles agent-level OTEL, agent-sandbox handles lifecycle OTEL), C16 (hardening in template), C17 (SandboxClaim is the trigger mechanism).

---

### C2: Runtime Isolation

Even with a correctly configured pod, a kernel exploit in the shared host kernel can escape any container. Runtime isolation interposes an additional kernel boundary — either a user-space syscall filter (gVisor) or a lightweight VM (Kata) — so that a compromised agent never touches the real host kernel.

**How it works:** A Kubernetes `RuntimeClass` resource is created for each backend. **gVisor** intercepts syscalls in user space, imposing 10-30% I/O overhead but adding negligible startup latency and supporting high pod density. **Kata Containers** boots a minimal guest kernel per pod, providing near-native CPU at the cost of 100-500ms boot time. The choice is workload-dependent: gVisor for most agent tasks, Kata when running untrusted native binaries.

**What we use:** [gVisor](https://gvisor.dev/) (default) and [Kata Containers](https://katacontainers.io/) (option), via standard Kubernetes RuntimeClass.

**Implementation status (Feb 2026): ⏸️ Deferred.** gVisor (`runsc`) rejects ALL SELinux labels, but CRI-O on RHCOS always applies SELinux labels to containers. This makes gVisor incompatible with OpenShift's default security model. A wrapper script approach was prototyped (strips SELinux from OCI spec before calling `runsc`) but requires node rollout to test. A custom SCC (`gvisor-sandbox`, priority 20) was created to bypass SELinux for sandbox-agent service accounts.

**Security comparison without gVisor:**

| Layer | gVisor (ideal) | runc + hardening (current) | Delta |
|-------|---------------|--------------------------|-------|
| Kernel isolation | User-space kernel (syscall interception) | Shared host kernel | gVisor is stronger |
| Filesystem | gVisor's internal VFS | nono Landlock ABI v5 (irreversible) | Comparable — Landlock is kernel-enforced |
| Capabilities | All dropped by gVisor | All dropped via SecurityContext | Equivalent |
| SELinux | Incompatible (rejected) | Enforced via restricted-v2 SCC | runc is actually stronger here |
| seccomp | gVisor has own syscall table | RuntimeDefault profile | gVisor is more restrictive |
| Network | gVisor's netstack | NetworkPolicy + Squid proxy + AuthBridge | Comparable at L3/L4/L7 |
| Overall | Stronger kernel boundary | Adequate with defense-in-depth (4 layers) | Acceptable for current threat model |

**Decision:** The current runc + SecurityContext hardening (C16) + nono Landlock (C3) + Squid proxy (C5) + NetworkPolicy provides 4 layers of isolation. While gVisor adds a stronger kernel boundary, the current stack is adequate for the threat model (LLM-generated code execution with network filtering). Kata Containers is the path forward for workloads requiring VM-level isolation — it does not have the SELinux incompatibility.

**Relationship to other capabilities:** C1 (RuntimeClass is a field in SandboxTemplate), C3 (nono provides defense-in-depth inside the container — even if gVisor is bypassed, nono's Landlock still restricts filesystem and network).

---

### C3: In-Container Kernel Sandbox (nono)

Runtime isolation (C2) protects the host from the container. But the agent process still has broad access *within* its own container. nono locks down the process from the inside, using OS-level mandatory access controls that are **irreversible once applied** — no API can loosen them, in direct contrast to OpenClaw's CVE-2026-25253 where the sandbox was disabled via a tool call.

**How it works:** On Linux, nono uses **Landlock LSM** for filesystem restrictions and **seccomp-BPF** for syscall filtering. Policies are built with a **CapabilitySet builder**: the launcher specifies which paths are readable/writable, whether network is allowed, and which executables may run. A hardcoded **never-grant blocklist** ensures `~/.ssh`, `~/.kube`, `~/.aws`, `/etc/shadow` are always denied. For runtime capability expansion, a **supervisor process** can inject pre-opened file descriptors into the sandboxed process without relaxing the Landlock policy itself. Python bindings via PyO3 let the Kagenti agent launcher call `nono.sandbox()` directly.

**What we use:** [nono](https://github.com/always-further/nono) — Python bindings via PyO3.

**Relationship to other capabilities:** C2 (nono is layered on top of gVisor/Kata — they protect the host, nono protects the container's filesystem from the agent), C7 (the application-level permission model is a third layer above nono's OS-level enforcement).

---

### C4: Instruction File Attestation

Agents load instructions from `CLAUDE.md` and `.claude/skills/`. If an attacker modifies these files, the agent executes poisoned instructions with full tool access. Attestation verifies instruction files against a known-good signature before the agent reads them — preventing supply chain attacks like OpenClaw's ClawHavoc skill poisoning.

**How it works:** Before loading any instruction file, the launcher computes a **SHA-256 digest** and verifies it against a **Sigstore bundle** (DSSE envelope signed with an OIDC-linked identity). Three enforcement modes: `Deny` (hard block), `Warn` (log + allow), `Audit` (silent record). We **replicate the concept** from nono's trust module rather than adopting it directly — Kagenti has its own signing pipeline tied to Keycloak OIDC identities.

**What we use:** [sigstore-python](https://github.com/sigstore/sigstore-python) for verification, integrated into the Kagenti agent launcher. Concept from [nono trust module](https://github.com/always-further/nono/tree/main/crates/nono/src/trust).

**Relationship to other capabilities:** C10 (skills loading depends on attestation passing), C15 (TOFU is a simpler alternative for dev environments where Sigstore infrastructure is unavailable).

---

### C5: Network Filtering

A compromised agent could exfiltrate data to arbitrary endpoints or connect to internal services it shouldn't access. Network filtering enforces a domain-level allowlist so the agent can only reach explicitly approved destinations.

**How it works:** A **Squid forward-proxy sidecar** runs in the pod. The agent's `HTTP_PROXY`/`HTTPS_PROXY` point to `localhost:3128`. Squid's config: `acl allowed_domains dstdomain .api.openai.com .pypi.org .api.github.com` → `http_access allow allowed_domains` → `http_access deny all`. Any request to an unlisted domain gets HTTP 403. HTTPS uses `CONNECT` tunneling (Squid checks the domain but doesn't terminate TLS). Works alongside Istio Ambient mTLS and Kubernetes NetworkPolicy.

**What we use:** [Squid](http://www.squid-cache.org/) as sidecar, following the [paude](https://github.com/bbrowning/paude/blob/main/containers/proxy/squid.conf) pattern.

**Relationship to other capabilities:** C6 (Squid controls *where* the agent connects; AuthBridge controls *with what identity* — complementary, not overlapping), C16 (NetworkPolicy is L3/L4 backstop beneath Squid's L7 domain filtering).

---

### C6: Credential Isolation (AuthBridge)

The most dangerous thing a compromised sandbox can leak is a long-lived credential. If the agent never possesses raw credentials, a sandbox escape yields nothing reusable. AuthBridge ensures agents authenticate using their workload identity, never raw secrets.

**How it works:** AuthBridge is an **Envoy ext_proc** in the Istio mesh. When an agent makes an outbound request, ext_proc intercepts it and performs a **token exchange**: presents the pod's **SPIFFE SVID** to Keycloak, which returns a **scoped OAuth2 token** (e.g., GitHub App installation token limited to specific repos/permissions). The token is injected as the `Authorization` header. The agent code never sees the token. If the sandbox is compromised, the attacker gets only the SVID (short-lived, scoped, useless outside the SPIRE trust domain).

**What we use:** [AuthBridge](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge) — already built. Uses Envoy ext_proc, SPIRE for SVID, Keycloak for token exchange.

**Relationship to other capabilities:** C5 (Squid filters *where*, AuthBridge controls *as whom*), C12 (AuthBridge IS the token exchange — same component), C3 (nono blocks filesystem access to credential files, complementing AuthBridge's network-level isolation).

---

### C7: Permission Model (settings.json)

Without a permission model, every agent action either requires human approval (too slow) or runs unchecked (too dangerous). The three-tier policy balances autonomy with safety.

**How it works:** `settings.json` defines `allow`, `deny`, and `ask` lists with glob patterns like `shell(grep:*)` or `shell(sudo:*)`. At runtime: deny checked first (always wins), then allow (auto-approved), then HITL for anything unmatched. HITL triggers LangGraph `interrupt()` which pauses execution until a human responds.

**What we use:** Custom policy engine in sandbox agent + LangGraph interrupt. Already built.

**Relationship to other capabilities:** C3 (nono is kernel-level enforcement, settings.json is application-level — defense in depth), C14 (HITL is the escalation when settings.json says neither allow nor deny), C8 (sources.json complements with resource limits).

---

### C8: Capability Declaration (sources.json)

Even when an operation is permitted, the agent needs boundaries on *what resources* it can touch. An agent allowed to `pip install` shouldn't install arbitrary packages from untrusted registries.

**How it works:** `sources.json` is baked into the agent image (immutable at runtime). It declares: package managers (enabled/disabled, blocked packages, registries), web access (domain allowlist), git (allowed remotes, max clone size), and runtime (languages, execution time limits, memory ceiling). The agent checks this before executing any tool.

**What we use:** Custom JSON schema, enforced by sandbox agent runtime. Already built.

**Relationship to other capabilities:** C7 controls *what operations*, C8 controls *what resources* — complementary. The domain allowlist in C8 is enforced at network level by C5 (egress proxy), providing defense-in-depth.

---

### C9: Git Workspace Sync (Primary + Dynamic Multi-Repo)

Agents need source code access but shouldn't have direct write access to shared repositories. Git workspace sync provides a two-tier approach: the primary repo is cloned at init (for skills/config), and additional repos are cloned live by the agent as needed.

**How it works:**

*Primary repo (init container):* An init container clones the **primary repo** — the one containing `CLAUDE.md`, `.claude/skills/`, `settings.json`, and `sources.json` — into `/workspace` on a PVC. This must happen before the agent starts because the skills and permissions define the agent's operating instructions.

*Additional repos (runtime, dynamic):* During execution, the agent can clone additional repos via `shell(git clone:*)` into `/workspace/repos/`. This is controlled by `sources.json` `allowed_remotes` — only repos matching the allowlist patterns (e.g., `https://github.com/kagenti/*`) can be cloned. All git operations are authenticated transparently by AuthBridge (C6): the agent runs `git clone https://github.com/kagenti/extensions` and AuthBridge injects the scoped GitHub token via Envoy — the agent never handles credentials.

*Multi-repo workflow example:* An agent implementing a feature that spans `kagenti/kagenti` and `kagenti/extensions` clones both repos, makes changes in each, commits to isolated branches, and pushes draft PRs to both. The human reviews each PR independently.

*Trust boundary:* Changes stay in the sandbox until a human explicitly merges. The agent can push draft PRs (if `sources.json` allows `create-draft` scope for the target repo) but cannot merge, delete branches, or perform admin operations — those scopes are never granted via AuthBridge token exchange.

**What we use:** Kubernetes init container (primary clone), agent shell tool (dynamic clones), AuthBridge for git auth, PVC for persistence. Patterns from paude (git `ext::` protocol), devaipod (`git clone --shared`), ai-shell (per-project volumes).

**Relationship to other capabilities:** C1 (PVC persistence across restarts), C6 (AuthBridge provides scoped git auth — agent never handles tokens), C8 (sources.json `allowed_remotes` controls which repos can be cloned), C10 (skills loading reads from the primary clone), C4 (attestation verifies primary repo content after clone).

---

### C10: Skills/CLAUDE.md Loading

An agent without project context produces generic results. Skills loading parses repo instruction files into structured LLM context, giving the agent project-specific knowledge and workflows without manual configuration.

**How it works:** `SkillsLoader` scans the cloned workspace for `CLAUDE.md` (system prompt) and `.claude/skills/` (workflow definitions). Each skill is loaded as a named workflow. The loader assembles a unified, model-agnostic context payload. Pattern from nanobot's context builder (SOUL.md, AGENTS.md, IDENTITY.md).

**Security boundary:** Skills and CLAUDE.md are loaded **only from the primary repo** (the init container clone at `/workspace`). Dynamically cloned repos (C9 runtime clones at `/workspace/repos/`) are treated as data — the agent operates on their code but never loads instruction files from them. This prevents an attacker from crafting a malicious repo with poisoned skills that the agent clones and executes.

**What we use:** Custom Python `SkillsLoader` class.

**Relationship to other capabilities:** C9 (depends on primary repo being cloned; dynamic repos are data-only), C4 (depends on instruction files being verified), C11 (context is passed to any LLM via litellm).

---

### C11: Multi-LLM Pluggability

Locking to a single LLM provider creates vendor dependency. Skills should work identically regardless of which model powers the agent.

**How it works:** litellm provides a unified `completion()` API across 100+ providers. Model selection via environment variables: `LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY`. Switching models requires no code changes. The context from C10 is plain text, transferable across models.

**What we use:** [litellm](https://github.com/BerriAI/litellm) — direct Python dependency.

**Relationship to other capabilities:** C10 (receives assembled context), C5 (LLM API calls go through proxy sidecar).

---

### C12: Token Exchange (AuthBridge)

Sandbox agents need credentials for external services but storing static secrets violates least privilege and creates blast radius. Token exchange eliminates static secrets entirely.

**How it works:** AuthBridge ext_proc performs RFC 8693 token exchange: presents the pod's SPIFFE SVID to Keycloak, receives a scoped, short-lived OAuth2 token, injects it into the outbound request. The agent code never handles credentials. Keycloak logs every exchange for audit.

**What we use:** [AuthBridge](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge), Keycloak, SPIRE. Already built.

**Relationship to other capabilities:** C6 (AuthBridge IS the credential isolation implementation), C5 (proxy decides WHERE, AuthBridge decides WITH WHAT IDENTITY), C13 (same ext_proc does both token exchange and OTEL).

---

### C13: Observability (AuthBridge OTEL)

Understanding what an agent did is essential for debugging, auditing, and cost management. AuthBridge creates distributed traces at the mesh level with zero agent code changes.

**How it works:** AuthBridge ext_proc intercepts inbound A2A requests, parses the body, and creates a root OTEL span `invoke_agent {name}` with GenAI semantic conventions (MLflow and OpenInference compatible). A `traceparent` header is injected so that auto-instrumented agent spans (LangChain, OpenAI SDK) become children of this root span. This is Approach A — the default on OpenShift. Alternative Approach B requires ~50 lines of agent boilerplate.

**What we use:** AuthBridge ext_proc with OTEL SDK, MLflow. Already built.

**Relationship to other capabilities:** C12 (same ext_proc handles both token exchange and trace creation), C6 (same infrastructure).

---

### C14: Execution Approval

When a tool call falls outside allow/deny rules, the agent must pause and ask a human. This is the escalation mechanism that turns static policy (C7) into a live decision point.

**How it works:** The sandbox runtime classifies the operation as `requires_approval`. LangGraph calls `interrupt()`, suspending the graph and persisting state. The A2A task transitions to `input_required`. The approval request is delivered through C18's multi-channel system. The agent remains frozen until the human responds. Critically, the kernel-level sandbox (C3: nono) remains active throughout — unlike OpenClaw's approval system, Kagenti's enforcement cannot be disabled by any userspace process.

**What we use:** LangGraph `interrupt()` + A2A `input_required` + settings.json HITL. Already built; needs extension for autonomous mode.

**Relationship to other capabilities:** C7 (policy rules determine when approval is needed), C18 (delivers the request to humans), C3 (nono guarantees sandbox holds even if approval system were bypassed).

---

### C15: Config Trust (TOFU)

Agent configs directly control what the agent can do. A silently modified config could grant capabilities the operator never intended.

**How it works:** On first load, the sandbox controller hashes each trust-sensitive file (SHA-256) and stores fingerprints in a ConfigMap. On subsequent sandbox creations, it re-hashes and compares. If any hash differs, the sandbox is not created — the controller emits a `ConfigTrustViolation` event and requires explicit re-approval. Pattern from ai-shell's `loader.go`.

**What we use:** SHA-256 hashing + Kubernetes ConfigMap trust store. Replicate the concept independently (ai-shell has no license).

**Relationship to other capabilities:** C4 (TOFU is simpler than Sigstore attestation — first-use trust vs cryptographic verification), C9 (runs after git clone, before agent loads configs), C10 (skills loading proceeds only after TOFU passes).

---

### C16: Container Hardening Defaults

Every sandbox pod must start from a secure baseline. Without enforced defaults, a single misconfigured template could expose the host kernel.

**How it works:** The SandboxTemplate controller injects non-negotiable settings: read-only root filesystem, all capabilities dropped, non-root user, no service account token auto-mount, default-deny NetworkPolicy. Defined in Helm `values.yaml` under `sandboxDefaults`. Individual templates can add permissions but cannot weaken the baseline.

**What we use:** Kubernetes SecurityContext + NetworkPolicy + PodSecurity admission, configured as SandboxTemplate defaults. Pattern from agent-sandbox and [Anthropic secure deployment guide](https://platform.claude.com/docs/en/agent-sdk/secure-deployment).

**Relationship to other capabilities:** C1 (SandboxTemplate carries these defaults), C2 (gVisor/Kata adds kernel isolation above), C3 (nono adds syscall enforcement below), C5 (NetworkPolicy refined with per-agent egress rules).

---

### C17: Autonomous Triggers

Agents become substantially more useful when invoked automatically in response to events rather than only through manual interaction.

**How it works:** The Kagenti backend exposes FastAPI endpoints for trigger registrations. A trigger binds an event source (cron expression, webhook URL, PagerDuty alert filter, A2A message pattern) to a SandboxTemplate and parameters. When an event arrives, the backend creates a `SandboxClaim` CRD via kubernetes-client. The agent-sandbox controller provisions the pod, clones the repo (C9), validates config trust (C15), and starts the agent.

**What we use:** New Kagenti backend feature — FastAPI trigger endpoints + SandboxClaim CRD. To be built.

**Relationship to other capabilities:** C1 (SandboxClaim is the API for programmatic creation), C18 (triggers spawn sandboxes, HITL is how the sandbox talks back to humans), C9 (each trigger clones the relevant repo/branch).

---

### C18 Deep-Dive: Multi-Source Conversational HITL for Autonomous Agents

This goes beyond simple approve/deny. An autonomous agent working on a GitHub PR, an incident, or a scheduled task needs the ability to have a **multi-turn conversation** with humans through contextual channels — asking clarifying questions, presenting options, receiving design input — all tied to the relevant external resource (PR, Issue, incident) and routed to the right session.

#### The Problem

When an autonomous agent encounters something it cannot resolve alone — an ambiguous requirement, a design decision, a risky operation — it needs to:

1. **Ask a question** (not just request a binary approval)
2. **In the right context** (the PR thread, the Slack channel, the incident timeline)
3. **To the right person** (the PR author, the on-call engineer, the team lead)
4. **And get the answer back** into the same agent session (same `contextId`)
5. **Securely** — only authorized humans can inject input into the agent session

#### Context Binding: `contextId` ↔ External Resource

Every agent session has an A2A `contextId`. The key design: **bind the `contextId` to one or more external resources** so that human input from those resources routes to the correct session.

![Context Registry binding sessions to external resources](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti/sandbox-research/06-context-registry.gif)

![System Context: Where the sandbox fits in the Kagenti ecosystem](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti/sandbox-research/01-system-context.gif)

Source: A2A protocol [multi-turn via contextId](https://a2a-protocol.org/latest/tutorials/python/7-streaming-and-multiturn/)

#### Multi-Turn Conversation Flow

![Multi-turn HITL conversation via PR comments](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti/sandbox-research/07-hitl-sequence.gif)

#### Channel Adapters

Each channel adapter handles bidirectional routing: **outbound** (agent → human) and **inbound** (human → agent).

| Channel | Outbound (Agent → Human) | Inbound (Human → Agent) | Thread Binding | Auth |
|---------|-------------------------|------------------------|----------------|------|
| **GitHub PR** | [`POST /repos/{owner}/{repo}/issues/{pr}/comments`](https://docs.github.com/en/rest/issues/comments) | [`issue_comment` webhook](https://docs.github.com/en/webhooks/webhook-events-and-payloads#issue_comment) filtered by PR | PR number → contextId | [OWNERS file](https://www.kubernetes.dev/docs/guide/owners/) or Keycloak role |
| **GitHub Issue** | Same API, issue number | Same webhook, issue number | Issue number → contextId | OWNERS or Keycloak role |
| **Slack** | [`chat.postMessage`](https://api.slack.com/methods/chat.postMessage) with `thread_ts` | [Events API `message`](https://api.slack.com/events/message) with `thread_ts` matching | Slack thread `ts` → contextId | Slack user ID → Keycloak user via SSO |
| **Kagenti UI** | WebSocket push to session | WebSocket message from session | UI session → contextId | Session JWT (Keycloak-issued) |
| **PagerDuty** | [Incident note](https://developer.pagerduty.com/api-reference/3df2b685a0dbc-create-a-note-on-an-incident) | [Incident webhook v3](https://developer.pagerduty.com/docs/db0fa8c8984fc-overview) `incident.annotated` | Incident ID → contextId | PD user → Keycloak via SCIM/SSO |
| **A2A** | A2A `message/send` with contextId | A2A `message/send` with contextId | Native: contextId is the binding | SPIFFE SVID (mutual) |
| **Prow-style commands** | Bot posts comment with available commands | [`issue_comment` webhook](https://docs.github.com/en/webhooks/webhook-events-and-payloads#issue_comment) parses `/approve`, `/deny`, `/retry`, `/ask <question>` | PR/Issue → contextId | [OWNERS approvers](https://docs.prow.k8s.io/docs/components/plugins/approve/approvers/) |

#### Prow-Style Slash Commands for Agent Interaction

Following the [Kubernetes Prow model](https://docs.prow.k8s.io/docs/components/plugins/approve/approvers/) (also available as [GitHub Actions](https://github.com/jpmcb/prow-github-actions)), humans interact with the agent via slash commands in PR/Issue comments:

| Command | Effect | Who Can Use |
|---------|--------|-------------|
| `/approve` | Approve pending HITL operation | OWNERS approvers only |
| `/deny` | Deny pending HITL operation | OWNERS approvers + reviewers |
| `/retry` | Re-run the last failed skill | OWNERS approvers |
| `/ask <question>` | Send a message to the agent session | Any authorized commenter |
| `/cancel` | Cancel the agent's current task | OWNERS approvers |
| `/status` | Agent posts current status summary | Any authorized commenter |
| `/logs` | Agent posts last N lines of output | Any authorized commenter |

Commands are parsed by the Kagenti backend from `issue_comment` webhooks, authorized against OWNERS/Keycloak, and routed to the bound `contextId` as A2A messages.

#### Security Model

![HITL security pipeline: 5 gates a message must pass](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti/sandbox-research/08-security-layers.gif)

| Security Property | How Enforced |
|-------------------|-------------|
| **Only authorized humans can inject input** | Channel identity → Keycloak user → RBAC role check (`sandbox:interact` or `sandbox:approve`) |
| **Input reaches the right session** | Context Registry binds external resources to contextIds; webhook payload identifies the resource |
| **Sandbox cannot self-approve** | SPIFFE identity of sandbox pod lacks `sandbox:approve` role |
| **Replay protection** | Approval nonces are single-use; conversational messages are idempotent (deduplicated by messageId) |
| **Channel spoofing** | GitHub webhook secrets, Slack signed payloads, PagerDuty webhook signatures |
| **Prompt injection via human input** | Human messages injected as `role: user` (not `role: system`); agent treats them as untrusted input per CLAUDE.md instructions |
| **Cross-session leakage** | Context Registry enforces: input from PR #42 can only reach the contextId bound to PR #42 |
| **Time-bounded approvals** | HITL approvals expire (configurable, default 30 min); conversational messages have no expiry |
| **Audit trail** | Every inbound message logged to OTEL: who sent, from which channel, to which contextId, at what time |

#### Architecture Alignment

This design extends two existing patterns:

1. **nono's [`ApprovalBackend` trait](https://github.com/always-further/nono/blob/main/crates/nono/src/supervisor/mod.rs)** — a pluggable interface where the supervisor delegates decisions. nono has [`TerminalApproval`](https://github.com/always-further/nono/blob/main/crates/nono-cli/src/terminal_approval.rs) and planned `WebhookApproval`. Kagenti's Approval Backend is a multi-channel `WebhookApproval` that routes to GitHub/Slack/UI/PagerDuty.

2. **A2A protocol's [`input_required` state](https://a2a-protocol.org/latest/tutorials/python/7-streaming-and-multiturn/)** — the agent pauses and waits for the next `message/send` with the same `contextId`. The Kagenti backend acts as a bridge: it receives human input from any channel and forwards it as an A2A message to the sandbox.

The lesson from [OpenClaw's CVE-2026-25253](https://thehackernews.com/2026/02/openclaw-bug-enables-one-click-remote.html): their control API could disable the sandbox from outside. In Kagenti's design, the human input channel can only **send messages** to the agent — it cannot reconfigure the sandbox, disable permissions, or change the execution host. Those controls are enforced at the kernel level (nono Landlock) and cannot be modified via any API.

### C19: Multi-Conversation Isolation

When a sandbox agent handles multiple concurrent conversations — different users or different A2A callers hitting the same pod — each conversation's workspace, memory, and credentials must be isolated. Without this, one user's data could leak into another user's session.

**How it works:** Two modes based on security requirements:

*Pod-per-conversation (autonomous mode):* The agent-sandbox controller creates a separate Sandbox (and pod) for each conversation. This provides process-level, filesystem-level, and network-level isolation between conversations. Higher resource cost, but the only safe option for autonomous agents handling untrusted input.

```yaml
# Each conversation gets its own SandboxClaim
apiVersion: agents.x-k8s.io/v1alpha1
kind: SandboxClaim
metadata:
  name: conv-abc123
  labels:
    kagenti.io/conversation-id: abc123
    kagenti.io/user: alice
spec:
  sandboxTemplateName: coding-agent
```

*Shared pod with per-context directories (interactive mode):* A single pod handles multiple conversations, each in a separate workspace directory under the shared PVC. The `WorkspaceManager` creates `/workspace/ctx-<id>/` directories with separate `.context.json` metadata. Acceptable when a human is watching (interactive mode), because the human provides the trust boundary.

```
/workspace/
├── ctx-abc123/    # Alice's conversation
│   ├── .context.json   # {user: alice, created_at: ..., ttl_days: 7}
│   ├── repo/           # Cloned code
│   └── .cache/         # Conversation-specific cache
├── ctx-def456/    # Bob's conversation
│   ├── .context.json   # {user: bob, created_at: ..., ttl_days: 7}
│   └── repo/
```

*Memory isolation:* For pod-per-conversation, each pod has its own `MemorySaver` — no shared state. For shared-pod mode, the checkpointer uses conversation-scoped keys: `thread_id = f"ctx-{context_id}"` so that LangGraph's state graph never crosses conversation boundaries.

*Credential isolation:* AuthBridge handles this at the request level — each inbound A2A request carries the caller's JWT, and ext_proc exchanges it for a scoped token tied to that caller's identity. Different conversations get different scoped tokens automatically.

**What we use:** Kubernetes SandboxClaim (autonomous) + WorkspaceManager per-context dirs (interactive). AuthBridge for credential scoping.

**Relationship to other capabilities:** C1 (SandboxClaim creates pods per conversation), C6 (AuthBridge scopes credentials per caller), C14 (HITL approval is per-conversation), C18 (context registry binds contextId to external resources).

---

### C20: Sub-Agent Spawning via LangGraph

Complex tasks require the parent agent to delegate work to specialized sub-agents — similar to how Claude Code uses `Task` with `subagent_type=Explore` for research. The sandbox must support spawning sub-agents at two isolation levels.

**How it works:** Two spawning modes:

*In-process sub-agents (fast, same pod):* LangGraph `StateGraph` composition — the parent graph has tool nodes that invoke child graphs as asyncio tasks within the same Python process. Each sub-agent gets a scoped tool set (e.g., explore sub-agent gets only read tools, no write/execute). Good for research, analysis, and codebase exploration.

```python
from langgraph.graph import StateGraph

@tool
async def explore(query: str) -> str:
    """Spawn an explore sub-agent for codebase research."""
    sub_graph = create_explore_graph(
        workspace="/workspace/repo",
        tools=["grep", "read_file", "glob"],  # Scoped: no write, no execute
        max_iterations=15,
    )
    result = await sub_graph.ainvoke({"query": query})
    return result["summary"]

@tool
async def analyze(file_path: str, question: str) -> str:
    """Spawn an analysis sub-agent for code review."""
    sub_graph = create_analysis_graph(
        workspace="/workspace/repo",
        tools=["read_file"],  # Read-only
        max_iterations=10,
    )
    result = await sub_graph.ainvoke({"file": file_path, "question": question})
    return result["analysis"]
```

*Out-of-process sub-agents (isolated, separate pods):* The parent agent creates a `SandboxClaim` with the sub-task description and waits for the result via A2A polling. Each sub-agent gets its own sandbox pod with full isolation. Good for untrusted or long-running tasks.

```python
@tool
async def delegate(task: str, skill: str) -> str:
    """Spawn a sandbox sub-agent for a delegated task."""
    trigger = SandboxTrigger(namespace="team1")
    claim_name = trigger.create_from_webhook(
        event_type="a2a_delegation",
        repo="kagenti/kagenti",
        branch="main",
        skill=skill,  # Sub-agent loads this skill as primary workflow
    )
    # Poll A2A endpoint until task completes
    return await poll_sandbox_result(claim_name, timeout=300)
```

*Skill-driven sub-agent selection:* The parent agent reads the skills index from `CLAUDE.md` / `.claude/skills/` and uses the LLM to decide which skill to invoke and whether to use in-process or out-of-process spawning:

| Task Type | Spawning Mode | Example |
|-----------|---------------|---------|
| Codebase research | In-process (asyncio) | "Find all API endpoints" |
| Code analysis | In-process (asyncio) | "Review this function for bugs" |
| Test writing | Out-of-process (A2A) | "Write E2E tests for /users endpoint" |
| CI debugging | Out-of-process (A2A) | "Run /rca:ci on failing pipeline" |
| Multi-repo changes | Out-of-process (A2A) | "Update extensions repo to match" |

**What we use:** LangGraph StateGraph composition (in-process), SandboxClaim + A2A (out-of-process), SkillsLoader for sub-agent skill selection.

**Relationship to other capabilities:** C1 (SandboxClaim for out-of-process sub-agents), C10 (skills determine which sub-agent type), C19 (each sub-agent conversation is isolated), C11 (sub-agents can use different LLM models via litellm).

---

### C21: A2A-Generic Session Persistence

Session data must be available to the Kagenti UI regardless of which agent framework produced it. Rather than building framework-specific persistence (e.g., LangGraph AsyncPostgresSaver), the A2A SDK's DatabaseTaskStore persists tasks, messages, artifacts, and contextId at the protocol level.

**How it works:** The A2A SDK's `DatabaseTaskStore` replaces `InMemoryTaskStore` in the agent's server configuration. It uses SQLAlchemy async with PostgreSQL (asyncpg driver). Every `message/send` and task state change is persisted automatically. The Kagenti backend reads from the same database to power the session UI.

**Two-layer persistence:**
- **A2A TaskStore (all agents):** Tasks, messages, artifacts, contextId. Framework-agnostic. Read by UI.
- **Framework checkpointer (optional):** LangGraph AsyncPostgresSaver for graph pause/resume. Internal to Sandbox Legion.

**Agent variant: Sandbox Legion** — the flagship LangGraph-based multi-sub-agent orchestrator that uses both layers. Future agents (CrewAI, AG2) use only the A2A TaskStore.

**What we use:** [a2a-sdk[postgresql]](https://github.com/a2aproject/a2a-python) `DatabaseTaskStore`, per-namespace PostgreSQL (postgres-sessions StatefulSet).

**Relationship to other capabilities:** C19 (contextId links conversations to workspaces), C20 (sub-agent results stored as nested tasks), C14 (HITL state persisted as task state transitions).

---

### Capability Overlaps and Alignment

Several capabilities share infrastructure or address the same threat from different angles. Understanding these relationships prevents redundant work and ensures defense-in-depth.

**AuthBridge cluster (C6 + C12 + C13):** These three capabilities are implemented by the same component — AuthBridge ext_proc in the Envoy mesh. Token exchange (C12), credential isolation (C6), and observability (C13) all happen in a single request interception path. This is an architectural strength: one component, one interception point, minimal latency overhead.

**Permission stack (C3 + C7 + C14):** Three layers of execution control at different levels. nono (C3) operates at the kernel level — it cannot be disabled. settings.json (C7) operates at the application level — it defines policy. Execution approval (C14) is the escalation mechanism when C7 encounters an ambiguous operation. If C14's approval system were somehow bypassed, C3's kernel enforcement still holds. This layering is what prevented OpenClaw-style sandbox escapes.

**Trust verification chain (C4 + C15 + C9):** Three capabilities that verify content integrity at different stages. C9 (git clone) brings the code into the sandbox. C15 (TOFU) checks that config files haven't changed since the last trusted load. C4 (attestation) provides cryptographic proof of provenance. They form a pipeline: clone → hash check → signature verification → load.

**Network control stack (C5 + C6 + C16):** Three capabilities controlling network access at different layers. C16 (NetworkPolicy) restricts at L3/L4 (IP/port). C5 (Squid proxy) restricts at L7 (domain names). C6 (AuthBridge) controls the identity used for authenticated connections. A compromised agent must bypass all three to exfiltrate data.

**Agent context chain (C9 → C15 → C4 → C10 → C11):** Sequential dependencies for loading and using skills. Repo is cloned (C9), configs are hash-checked (C15), instruction files are signature-verified (C4), skills are parsed into context (C10), and context is sent to any LLM (C11). Breaking any link in this chain prevents the agent from loading poisoned instructions.

**Trigger-to-response cycle (C17 → C1 → C14 → C18):** The full autonomous lifecycle. A trigger creates a SandboxClaim (C17), the controller provisions a pod (C1), the agent runs until it hits a HITL operation (C14), the approval request is delivered to a human (C18), and the response is routed back to the sandbox. This cycle can repeat multiple times within a single sandbox session.

---

### Projects: Use Directly vs. Replicate Concepts

**Use directly as dependencies (Apache-2.0 compatible):**

| Project | License | What to adopt | Why direct adoption |
|---------|---------|---------------|---------------------|
| [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) | Apache-2.0 | Sandbox CRD, controller, warm pools | K8s-native standard; no reason to rebuild |
| [always-further/nono](https://github.com/always-further/nono) | Apache-2.0 | Kernel sandbox (Landlock/Seatbelt), Python bindings | Kernel-enforced isolation cannot be replicated at application level |
| [litellm](https://github.com/BerriAI/litellm) | MIT | Multi-LLM API abstraction | 100+ providers, battle-tested, no reason to rebuild |

**Replicate concepts (build Kagenti-native implementations inspired by):**

| Project | License | Concept to replicate | Why replicate instead of adopt |
|---------|---------|---------------------|-------------------------------|
| [bbrowning/paude](https://github.com/bbrowning/paude) | MIT | Squid proxy sidecar for network filtering | Paude is Claude-specific; we need a generic proxy sidecar |
| [cgwalters/devaipod](https://github.com/cgwalters/devaipod) | MIT/Apache-2.0 | Credential isolation via scoped MCP proxy | Devaipod uses Podman; we map this to Keycloak token exchange |
| [HKUDS/nanobot](https://github.com/HKUDS/nanobot) | MIT | Context builder from bootstrap files (SOUL.md → CLAUDE.md) | Nanobot is a full agent framework; we only need the loader pattern |
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | MIT | **Cautionary example** — exec approval concepts, but platform has had [512 vulnerabilities](https://www.kaspersky.com/blog/openclaw-vulnerabilities-exposed/55263/), [312K exposed instances](https://www.infosecurity-magazine.com/news/researchers-40000-exposed-openclaw/), and [1-click RCE via sandbox bypass](https://thehackernews.com/2026/02/openclaw-bug-enables-one-click-remote.html) | Study the failure modes, do not adopt the implementation |
| [arewm/ai-shell](https://github.com/arewm/ai-shell) | **No license** | TOFU config trust, per-project volume isolation | ⚠️ Cannot use directly — no license file. Concept is simple enough to implement independently |

**Already built in Kagenti (POC + Phases 1-9):**

| Capability | Status | Source |
|-----------|--------|--------|
| **Application-level (agent-examples repo)** | | |
| settings.json (allow/deny/HITL) (C7) | ✅ Working | [permissions.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/permissions.py) |
| sources.json (capability declaration) (C8) | ✅ Working | [sources.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/sources.py) |
| Per-context workspace isolation (C19 shared-pod) | ✅ Working | [workspace.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/workspace.py) |
| **Infrastructure-level (kagenti repo, Phases 1-9)** | | |
| Sandbox CRDs + controller (C1) | ✅ Deployed | [35-deploy-agent-sandbox.sh](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/.github/scripts/kagenti-operator/35-deploy-agent-sandbox.sh) — on-cluster build, SandboxTemplate + SandboxClaim working |
| Container hardening (C16) | ✅ Verified | Read-only root, caps dropped, non-root UID, seccomp RuntimeDefault, SELinux enforced via restricted-v2 SCC |
| Squid proxy sidecar (C5) | ✅ Verified | [proxy/Dockerfile](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/deployments/sandbox/proxy/), [squid.conf](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/deployments/sandbox/proxy/squid.conf) — UBI9 + Squid, domain allowlist |
| nono Landlock (C3) | ✅ Verified | [nono-launcher.py](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/deployments/sandbox/nono-launcher.py) — ABI v5 on RHCOS 5.14 kernel |
| SkillsLoader (C10) | ✅ Verified | [skills_loader.py](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/deployments/sandbox/skills_loader.py) — parses CLAUDE.md + .claude/skills/ |
| RepoManager (C9 dynamic) | ✅ Verified | [repo_manager.py](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/deployments/sandbox/repo_manager.py) — sources.json allowed_remotes enforcement |
| TOFU hash verification (C4, C15) | ✅ Verified | [tofu.py](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/deployments/sandbox/tofu.py) — SHA-256, tamper detection, ConfigMap storage |
| SandboxTrigger (C17) | ✅ Module | [triggers.py](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/deployments/sandbox/triggers.py) — cron/webhook/alert → SandboxClaim |
| HITLManager (C14, C18) | ✅ Module | [hitl.py](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/deployments/sandbox/hitl.py) — ContextRegistry + channel adapters |
| OTEL verification (C13) | ✅ Module | [otel_verification.py](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/deployments/sandbox/otel_verification.py) — MLflow/trace/GenAI attribute checks |
| gVisor RuntimeClass (C2) | ⏸️ Deferred | gVisor + SELinux incompatible on RHCOS; runc + hardening + nono provides comparable security (see C2 section) |
| A2A TaskStore persistence (C21) | ✅ Implemented | DatabaseTaskStore from a2a-sdk[postgresql], per-namespace Postgres |
| **Platform-level (already existed)** | | |
| AuthBridge: credential isolation (C6) | ✅ Platform-level | [kagenti-extensions/AuthBridge](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge) — Envoy ext_proc exchanges SVID → scoped token |
| AuthBridge: token exchange (C12) | ✅ Platform-level | [identity-guide.md](https://github.com/kagenti/kagenti/blob/main/docs/identity-guide.md) — RFC 8693 via Keycloak |
| AuthBridge: OTEL root spans (C13) | ✅ Platform-level | [AuthBridge](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge) — creates GenAI/MLflow root spans, zero agent code changes |
| SPIRE workload identity | ✅ Platform-level | [components.md](https://github.com/kagenti/kagenti/blob/main/docs/components.md) |
| MLflow + OTEL Collector | ✅ Platform-level | [components.md](https://github.com/kagenti/kagenti/blob/main/docs/components.md) |

---

## 3. Architecture: Kagenti Agent Sandbox {#3-architecture}

### Level 1: System Context — Where Sandbox Fits

![System Context: Where the sandbox fits in the Kagenti ecosystem](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti/sandbox-research/01-system-context.gif)

### Level 2: Container Diagram — Inside the Sandbox Pod

The sandbox pod contains multiple containers working together. The **AuthBridge ext_proc** runs inside the Envoy sidecar (Istio Ambient mesh) — it is not a separate container but intercepts all traffic transparently, handling JWT validation, token exchange, and OTEL root span creation. The agent container has zero credential awareness.

![Inside the Sandbox Pod: init container, agent, proxy sidecar, PVC, AuthBridge in Envoy](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti/sandbox-research/02-container-diagram.gif)

### Level 3: Component Diagram — Agent Container Internals

![Agent Container internals inside the nono Landlock sandbox](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti/sandbox-research/03-component-diagram.gif)

### Sandbox Lifecycle — From Trigger to Completion

The lifecycle includes AuthBridge initialization: after the git clone init container, a client-registration init container registers the workload with Keycloak using the pod's SPIFFE ID. Once running, all external access flows through AuthBridge transparently — the agent just makes HTTP calls and ext_proc handles authentication.

![Sandbox lifecycle from trigger through completion](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti/sandbox-research/04-lifecycle-sequence.gif)

### Isolation Layers — Defense-in-Depth

![Defense in depth: 5 isolation layers protecting the agent process](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti/sandbox-research/05-isolation-layers.gif)

**Implementation status of each layer (Feb 2026):**

```
Layer 5 (outermost): Kubernetes NetworkPolicy + Istio Ambient mTLS
  Status: ✅ Deployed — default-deny ingress, OVN-Kubernetes DNS fix applied
  Note: Requires explicit namespaceSelector for openshift-dns namespace

Layer 4: Squid Proxy Sidecar (L7 domain filtering)
  Status: ✅ Built + verified — UBI9 image, domain allowlist
  Verified: github.com=200, pypi.org=200, evil.com=403, google.com=403

Layer 3: Container Hardening (SecurityContext)
  Status: ✅ Enforced — read-only root, all caps dropped, non-root UID 1000770000,
          seccomp RuntimeDefault, SELinux via restricted-v2 SCC, no SA token

Layer 2: Runtime Isolation (gVisor/Kata RuntimeClass)
  Status: ⏸️ Deferred — gVisor incompatible with SELinux on RHCOS
  Mitigation: Layers 1+3+4+5 provide adequate isolation without gVisor

Layer 1 (innermost): nono Landlock (kernel-enforced, irreversible)
  Status: ✅ Verified — ABI v5 on RHCOS 5.14 kernel
  Verified: /workspace=writable, /tmp=writable, /etc=blocked by Landlock
```

### C19/C20 Architecture — Multi-Conversation and Sub-Agent Spawning

Building on the isolation layers above, C19 and C20 introduce two new architectural patterns:

```
┌─── Autonomous Mode (C19: pod-per-conversation) ────────────────────┐
│                                                                     │
│  SandboxClaim (conv-abc123)         SandboxClaim (conv-def456)     │
│  ┌──────────────────────┐           ┌──────────────────────┐       │
│  │ Pod: sandbox-abc123  │           │ Pod: sandbox-def456  │       │
│  │ User: Alice          │           │ User: Bob            │       │
│  │ /workspace/repo/     │           │ /workspace/repo/     │       │
│  │ Own PVC, own nono    │           │ Own PVC, own nono    │       │
│  │ Own MemorySaver      │           │ Own MemorySaver      │       │
│  └──────────────────────┘           └──────────────────────┘       │
│  Full isolation: process, filesystem, network, memory               │
└─────────────────────────────────────────────────────────────────────┘

┌─── Interactive Mode (C19: shared pod) ─────────────────────────────┐
│                                                                     │
│  Single Sandbox Pod                                                 │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │ /workspace/                                               │      │
│  │ ├── ctx-abc123/ (Alice)  ├── ctx-def456/ (Bob)           │      │
│  │ │   ├── .context.json    │   ├── .context.json           │      │
│  │ │   └── repo/            │   └── repo/                   │      │
│  │ Shared process, per-context dirs, scoped checkpointer    │      │
│  └──────────────────────────────────────────────────────────┘      │
│  Acceptable: human watching provides trust boundary                 │
└─────────────────────────────────────────────────────────────────────┘

┌─── Sub-Agent Spawning (C20) ───────────────────────────────────────┐
│                                                                     │
│  Parent Agent Pod                                                   │
│  ┌──────────────────────────────────────────────────────┐          │
│  │ LangGraph StateGraph (parent)                         │          │
│  │ ├── explore_tool ──→ Sub-graph (asyncio, same process)│          │
│  │ │   └── Tools: grep, read_file, glob (read-only)     │          │
│  │ ├── analyze_tool ──→ Sub-graph (asyncio, same process)│          │
│  │ │   └── Tools: read_file (read-only)                  │          │
│  │ └── delegate_tool ──→ SandboxClaim (new pod, A2A)     │          │
│  │     └── Full sandbox, own skills, own nono            │          │
│  └──────────────────────────────────────────────────────┘          │
│                                                                     │
│  ┌── Delegated Sub-Agent Pod ──────────────────────────────┐       │
│  │ Own Sandbox, own SandboxClaim, A2A communication        │       │
│  │ Skills: loaded from primary repo + skill parameter      │       │
│  │ Results: returned via A2A polling                       │       │
│  └─────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

### Skills Loading

```python
# Agent startup (simplified)
class SkillsLoader:
    def __init__(self, workspace_path: str):
        self.workspace = Path(workspace_path)

    def load_system_prompt(self) -> str:
        """Load CLAUDE.md as the agent's system prompt."""
        claude_md = self.workspace / "CLAUDE.md"
        if claude_md.exists():
            return claude_md.read_text()
        return "You are a helpful coding assistant."

    def load_skills(self) -> list[Skill]:
        """Load skills from .claude/skills/."""
        skills_dir = self.workspace / ".claude" / "skills"
        skills = []
        for skill_file in skills_dir.rglob("SKILL.md"):
            skills.append(Skill.from_file(skill_file))
        return skills

    def build_context(self, model_provider: str) -> str:
        """Build full context for any LLM."""
        system = self.load_system_prompt()
        skills = self.load_skills()
        skill_index = "\n".join(
            f"- {s.name}: {s.description}" for s in skills
        )
        return f"{system}\n\n## Available Skills\n{skill_index}"
```

### Model Pluggability

Any LLM can be plugged via environment variables and [litellm](https://github.com/BerriAI/litellm):

```yaml
env:
- name: LLM_MODEL
  value: "claude-sonnet-4-20250514"  # or "gpt-4o", "qwen2.5:3b", "ollama/llama3"
- name: LLM_API_BASE
  valueFrom:
    configMapKeyRef: { name: llm-config, key: api-base }
- name: LLM_API_KEY
  valueFrom:
    secretKeyRef: { name: llm-secret, key: api-key }
```

```python
import litellm
response = litellm.completion(
    model=os.environ["LLM_MODEL"],
    messages=[{"role": "system", "content": context}, ...],
    api_base=os.environ.get("LLM_API_BASE"),
    api_key=os.environ.get("LLM_API_KEY"),
)
```

---

## 4. Kagenti Implementation: From POC to Phases 1-9 {#4-prototype}

> **Status (Feb 25, 2026):** The sandbox agent has progressed from a rapid POC to a 9-phase implementation verified on two HyperShift clusters (`lpvc` and `sbox`). 22 files, +2,601 lines across two repos. The implementation covers container-level isolation (CRDs + controller), network filtering (Squid proxy), kernel sandboxing (nono Landlock), skills loading, TOFU verification, autonomous triggers, and HITL scaffolding. gVisor runtime isolation is deferred due to SELinux incompatibility on RHCOS (see C2 section). Draft PRs: [kagenti/kagenti#1](https://github.com/Ladas/kagenti/pull/1), [kagenti/agent-examples#126](https://github.com/kagenti/agent-examples/pull/126).

### Implementation Architecture (Post Phase 9)

The sandbox agent now spans two repos and implements all 5 isolation layers described in Section 3:

```
┌──────────────────────────────────────────────────────────────────────┐
│  Sandbox Pod (kubernetes-sigs/agent-sandbox CRD)                     │
│                                                                      │
│  ┌── Init Container ──────────────────────────────────────────────┐ │
│  │  alpine/git → git clone primary repo → /workspace              │ │
│  │  TOFU hash check (C4/C15) → verify CLAUDE.md + sources.json   │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌── Agent Container (nono Landlock sandbox) ─────────────────────┐ │
│  │  ├── A2A Server (Starlette)                                    │ │
│  │  ├── LangGraph Agent + MemorySaver Checkpointer                │ │
│  │  ├── SandboxExecutor (asyncio subprocess)                      │ │
│  │  ├── PermissionChecker (settings.json: allow/deny/HITL)        │ │
│  │  ├── SourcesConfig (sources.json: registries/domains)          │ │
│  │  ├── SkillsLoader (CLAUDE.md + .claude/skills/ → system prompt)│ │
│  │  ├── RepoManager (sources.json allowed_remotes enforcement)    │ │
│  │  ├── WorkspaceManager (/workspace/<context_id>/)               │ │
│  │  ├── HITLManager (approval routing via ContextRegistry)        │ │
│  │  └── litellm (multi-LLM: Claude, GPT, Gemini, Llama, Qwen)    │ │
│  │  Security: read-only root, caps dropped, non-root UID,         │ │
│  │           seccomp RuntimeDefault, Landlock ABI v5               │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌── Squid Proxy Sidecar ─────────────────────────────────────────┐ │
│  │  Domain allowlist: github.com, pypi.org, LLM APIs              │ │
│  │  Deny all unlisted domains (HTTP 403)                          │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌── Envoy (Istio Ambient) + AuthBridge ext_proc ─────────────────┐ │
│  │  Token exchange: SVID → scoped OAuth2 token (C6/C12)           │ │
│  │  OTEL root spans with GenAI semantic conventions (C13)         │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Volumes: /workspace (PVC), /tmp (emptyDir), /app/.cache (emptyDir) │
│  Network: NetworkPolicy (L3/L4) + Squid (L7) + AuthBridge (identity)│
│  DNS: headless Service → sandbox-name.namespace.svc.cluster.local    │
└──────────────────────────────────────────────────────────────────────┘
```

### Phase-by-Phase Implementation Status

| Phase | Capabilities | Status | Verified On | Key Files |
|-------|-------------|--------|-------------|-----------|
| 1 | C1, C16 — CRDs, controller, SandboxTemplate, hardening | **Done** | lpvc + sbox clusters | `35-deploy-agent-sandbox.sh`, `sandbox-template.yaml` |
| 2 | C5, C6 — Squid proxy sidecar, domain allowlist | **Done** | sbox (github.com=200, pypi.org=200, evil.com=403) | `proxy/Dockerfile`, `squid.conf`, `sandbox-template-with-proxy.yaml` |
| 3 | C3 — nono Landlock kernel sandbox | **Done** | sbox (Landlock ABI v5 on RHCOS 5.14) | `nono-launcher.py` |
| 4 | C9, C10, C11 — Init container, SkillsLoader, litellm | **Done** | sbox (3 skills loaded, 378-char prompt) | `skills_loader.py`, `agent_server.py`, `sandbox-template-full.yaml` |
| 5 | C9 dynamic — RepoManager with sources.json enforcement | **Done** | sbox (allowed/denied repo patterns verified) | `repo_manager.py`, `sources.json` |
| 6 | C4, C15 — TOFU hash verification | **Done** | sbox (SHA-256, tamper detection verified) | `tofu.py` |
| 7 | C17 — SandboxTrigger (cron/webhook/alert → SandboxClaim) | **Done** | Design + module | `triggers.py` |
| 8 | C14, C18 — HITLManager + ContextRegistry + channel adapters | **Done** | Design + module | `hitl.py` |
| 9 | C13 — OTEL verification scaffolding | **Done** | Design + module | `otel_verification.py` |

### Application-Level Features (agent-examples repo)

| Feature | Status | Source |
|---------|--------|--------|
| Shell execution (grep, sed, ls, python, pip, git) | ✅ Working | [executor.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/executor.py) |
| File read/write with path-traversal prevention | ✅ Working | [graph.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/graph.py) |
| Per-context workspace directories | ✅ Working | [workspace.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/workspace.py) |
| settings.json three-tier permission control | ✅ Working | [permissions.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/permissions.py) |
| sources.json capability declaration | ✅ Working | [sources.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/sources.py) |
| web_fetch with domain allowlist | ✅ Working | [graph.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/graph.py) |
| A2A agent card + streaming | ✅ Working | [agent.py](https://github.com/Ladas/agent-examples/blob/feat/sandbox-agent/a2a/sandbox_agent/src/sandbox_agent/agent.py) |
| Multi-turn memory (MemorySaver) | ✅ Working | Fixed in commit `04f7cd5` |
| 68 unit tests + 5 E2E tests | ✅ Passing | [test_sandbox_agent.py](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/kagenti/tests/e2e/common/test_sandbox_agent.py) |

### Design Documents

- [Agent Context Isolation Design](https://github.com/kagenti/kagenti/blob/main/docs/plans/2026-02-14-agent-context-isolation-design.md) — Full architecture with mermaid diagrams
- [Agent Context Isolation Implementation Plan](https://github.com/kagenti/kagenti/blob/main/docs/plans/2026-02-14-agent-context-isolation-impl.md) — 10-task TDD plan
- [Sandbox Agent Implementation Passover (Feb 24)](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/docs/plans/2026-02-24-sandbox-agent-implementation-passover.md) — Phases 1-9 implementation details
- [Sandbox Agent Session Passover (Feb 25)](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/docs/plans/2026-02-25-sandbox-agent-passover.md) — C19/C20 designs, review comments, cluster state

### HyperShift Test Results (sbox cluster)

| Run | Result | Notes |
|-----|--------|-------|
| Run 1 (initial deploy) | 47 passed, 0 failed, 30 errors, 3 skipped | All 30 errors: Keycloak `Invalid user credentials` (RHBK operator uses `temp-admin` with random password) |
| Run 2 (Keycloak fix) | 47 passed, 1 failed, 29 errors, 3 skipped | 1 failure: pre-existing OTEL metrics issue. 29 errors: MLflow OAuth clients lost after Keycloak DB wipe |

**Keycloak root cause:** RHBK operator creates `keycloak-initial-admin` secret with `temp-admin` + random password. The bootstrap admin is temporary and gets consumed/deleted. Fix: created permanent admin user via `kcadm.sh`. The proper fix is ensuring the installer creates a persistent admin after RHBK operator initialization.

### Gaps: POC → Phase 9 → Full Production

| Gap | POC State | Phase 9 State | Remaining for Production |
|-----|-----------|---------------|-------------------------|
| Container-level isolation (C1, C2) | Regular pod | ✅ CRDs + controller deployed, SandboxTemplate working | gVisor deferred (SELinux incompatibility); Kata as alternative |
| Kernel-enforced sandboxing (C3) | None | ✅ nono Landlock ABI v5 verified on RHCOS | Wire nono as default agent launcher in SandboxTemplate |
| Credential isolation (C6, C12) | LLM API key in env var | ✅ AuthBridge already built (platform-level) | Integrate AuthBridge with sandbox pod spec |
| Network filtering (C5) | None | ✅ Squid proxy sidecar built + verified | Parameterize domain allowlist per SandboxTemplate |
| Git workspace sync (C9) | None | ✅ Init container + RepoManager with sources.json | Wire AuthBridge for git auth (scoped tokens) |
| Skills/CLAUDE.md loading (C10) | None | ✅ SkillsLoader parses skills into system prompt | Production testing with real repos |
| Instruction attestation (C4, C15) | None | ✅ TOFU hash verification implemented | Sigstore integration for cryptographic attestation |
| Multi-pod persistence | MemorySaver (in-memory) | MemorySaver (in-memory) | AsyncPostgresSaver or Redis for cross-pod state |
| Autonomous triggers (C17) | Manual only | ✅ SandboxTrigger module (cron/webhook/alert) | FastAPI endpoints in Kagenti backend |
| HITL delivery (C14, C18) | None | ✅ HITLManager + ContextRegistry + channel adapter design | Wire LangGraph `interrupt()`, implement channel adapters |
| Multi-conversation isolation (C19) | Per-context dirs | Per-context dirs + design for pod-per-conversation | Implement pod-per-conversation for autonomous mode |
| Sub-agent spawning (C20) | None | Design only | Implement LangGraph sub-graphs + A2A delegation |
| Shell interpreter bypass | Not addressed | ⚠️ Infra mitigated (Squid + nono) but app-level fix needed | Add recursive argument inspection in `_match_shell()` |
| sources.json enforcement | Defined but not wired | ⚠️ Methods exist but not called in executor | Wire `is_package_blocked()` into executor pre-hooks |

### Security Review Findings (PR #126)

Code review by pdettori on [agent-examples PR #126](https://github.com/kagenti/agent-examples/pull/126) identified 4 issues. Each has both an infrastructure mitigation (from Phases 1-9) and an application-level fix needed:

| # | Finding | Severity | Infrastructure Mitigation | App Fix Needed | Status |
|---|---------|----------|--------------------------|----------------|--------|
| 1 | **Shell interpreter bypass** — `bash -c "curl ..."` matches `shell(bash:*)` allow rule, bypassing `shell(curl:*)` deny rule. The LLM can trivially wrap any denied command in an allowed interpreter. | Critical | Squid proxy blocks `curl` at the network level (domain allowlist). nono Landlock blocks filesystem access. NetworkPolicy blocks direct IP connections. **Three layers prevent actual exfiltration even if the permission check is bypassed.** | Add recursive argument inspection in `_match_shell()` for interpreter commands (detect `-c` flags, pipe chains, subprocess spawning). Or: remove blanket `shell(bash:*)` / `shell(python:*)` from allow rules and whitelist specific scripts instead. | 🔄 Pending |
| 2 | **HITL has no `interrupt()` call** — `HitlRequired` exception is caught and converted to a string (`"APPROVAL_REQUIRED: ..."`), returned to the LLM. No LangGraph `interrupt()` is called, so the graph continues and the LLM can ignore or work around the approval request. | Critical | Phase 8 HITLManager provides the proper approval backend infrastructure (ContextRegistry, channel adapters, ApprovalRequest/Decision model). **The infrastructure is ready; the agent code just needs to call `interrupt()` instead of returning a string.** | Replace `except HitlRequired` handler with LangGraph `interrupt()` that pauses graph execution. Agent resumes only after explicit human approval via the HITLManager channel. | 🔄 Pending |
| 3 | **No TTL / workspace cleanup** — `ttl_days` is accepted and stored in `.context.json` but never enforced. No cleanup job, no eviction, no disk quota enforcement. Workspaces accumulate indefinitely on shared PVC. | Medium | SandboxClaim has `shutdownTime` + `Delete` policy (Phase 1, C1). **The Sandbox controller handles pod lifecycle and PVC cleanup.** However, within a shared pod (interactive mode, C19), per-context dirs are not cleaned up. | Add `cleanup_expired()` method to `WorkspaceManager`, wire into CronJob or startup hook. Or: document `ttl_days` as advisory and defer enforcement to Sandbox controller lifecycle. | 🔄 Pending |
| 4 | **Package/remote blocking not wired** — `is_package_blocked()`, `is_git_remote_allowed()`, `is_package_manager_enabled()` exist in `sources.py` but are never called from the executor. `pip install <blocked-package>` succeeds if `shell(pip install:*)` is in the allow list. | Medium | Phase 5 RepoManager enforces `sources.json` `allowed_remotes` for `git clone` operations. Squid proxy blocks access to unlisted package registries at the network level. **Infrastructure enforcement partially covers this, but the app-level check provides defense in depth.** | Wire `is_package_blocked()` and `is_git_remote_allowed()` into executor pre-hooks. Before executing any `pip install`, `git clone`, or `npm install` command, check against `sources.json`. | 🔄 Pending |

**Defense-in-depth analysis:** The infrastructure layers (Phases 1-9) mitigate the real-world impact of all 4 findings. Even if the application-level permission checker is bypassed (Finding 1), the Squid proxy blocks unauthorized network access, nono Landlock blocks unauthorized filesystem access, and NetworkPolicy prevents direct IP connections. However, the application-level fixes are still important for: (a) defense in depth, (b) providing clear feedback to the LLM about why an operation was denied, and (c) preventing the LLM from wasting tokens on operations that will ultimately fail at the infrastructure level.

---

## 5. Research: Open-Source Agent Sandbox Projects {#5-research}

### 5.1 kubernetes-sigs/agent-sandbox {#51-kubernetes-sigsagent-sandbox}

**Repository:** https://github.com/kubernetes-sigs/agent-sandbox

**What It Is:** A Kubernetes SIG Apps project providing a `Sandbox` CRD and controller for managing isolated, stateful, singleton workloads. Directly targets AI agent runtimes, dev environments, and notebooks.

**Core API:**
```yaml
apiVersion: agents.x-k8s.io/v1alpha1
kind: Sandbox
metadata:
  name: coding-agent
spec:
  podTemplate:
    spec:
      containers:
      - name: agent
        image: my-agent:v1
  volumeClaimTemplates:
  - metadata:
      name: workspace
    spec:
      accessModes: [ReadWriteOnce]
      resources:
        requests:
          storage: 10Gi
  lifecycle:
    shutdownTime: "2026-02-24T00:00:00Z"
    shutdownPolicy: Delete
```

Source: [sandbox_types.go](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/api/v1alpha1/sandbox_types.go)

**Key Features:**
- **SandboxTemplate** — reusable templates with built-in NetworkPolicy (default-deny ingress). Source: [sandboxtemplate_types.go](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/extensions/api/v1alpha1/sandboxtemplate_types.go)
- **SandboxClaim** — user-facing API to request sandboxes from templates. Source: [sandboxclaim_types.go](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/extensions/api/v1alpha1/sandboxclaim_types.go)
- **SandboxWarmPool** — pre-warmed sandbox pools with HPA for rapid provisioning. Source: [sandboxwarmpool_types.go](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/extensions/api/v1alpha1/sandboxwarmpool_types.go)
- **OpenTelemetry tracing** — W3C Trace Context propagation via annotations. Source: [tracing.go](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/internal/metrics/tracing.go)
- **Python SDK** — Client with tunnel/gateway modes. Source: [clients/python/](https://github.com/kubernetes-sigs/agent-sandbox/tree/main/clients/python/agentic-sandbox-client)
- **Headless Services** — stable DNS per sandbox (`sandbox-name.namespace.svc.cluster.local`)
- **gVisor & Kata support** — pluggable runtime isolation

**Roadmap highlights** (from [roadmap.md](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/roadmap.md)):
- Scale-down/Resume PVC-based (pause/resume preserving PVC)
- API support for other isolation technologies (QEMU, Firecracker, process isolation)
- Integration with kAgent (Kagenti)
- DRA controllers for advanced networking
- OCI sandbox manifest standardization

**Kagenti Relevance:** **HIGH** — This is the Kubernetes-native foundation for Kagenti's sandbox. The Sandbox CRD provides lifecycle management, warm pools, and NetworkPolicy enforcement. The roadmap includes "Integration with kAgent" which refers to [kagent](https://github.com/kagent-dev/kagent) (Solo.io / CNCF sandbox project) — a different project from Kagenti, but the same Sandbox CRD and controller are directly usable by Kagenti.

---

### 5.2 always-further/nono {#52-always-furthernono}

**Repository:** https://github.com/always-further/nono

**What It Is:** Capability-based kernel-enforced sandboxing (Landlock LSM on Linux, Seatbelt on macOS) for AI agents. Created by Luke Hinds (creator of Sigstore). Makes dangerous operations "structurally impossible" via OS-level enforcement.

**Key Architecture:**
- **CapabilitySet builder** — declares what agent can access. Source: [capability.rs](https://github.com/always-further/nono/blob/main/crates/nono/src/capability.rs) (~1,056 lines)
- **Landlock enforcement** — irreversible kernel sandbox via `ruleset.restrict_self()`. Source: [linux.rs](https://github.com/always-further/nono/blob/main/crates/nono/src/sandbox/linux.rs)
- **Supervisor with fd injection** — seccomp user notification for transparent capability expansion. Source: [supervisor/](https://github.com/always-further/nono/tree/main/crates/nono/src/supervisor)
- **Never-grant paths** — hardcoded blocklist: `~/.ssh`, `~/.aws`, `~/.kube`, `/etc/shadow`. Source: [policy.json](https://github.com/always-further/nono/blob/main/crates/nono-cli/data/policy.json)
- **Instruction file attestation** — Sigstore-based verification of CLAUDE.md/SKILLS.md before agent ingests them. Source: [trust/](https://github.com/always-further/nono/tree/main/crates/nono/src/trust)
- **System keystore integration** — secrets injected at runtime, never on disk. Source: [keystore.rs](https://github.com/always-further/nono/blob/main/crates/nono/src/keystore.rs)
- **Python & TypeScript bindings** via PyO3/napi-rs

**Security Model:**
| Protection | Mechanism | Layer |
|-----------|-----------|-------|
| Filesystem exfiltration | Landlock/Seatbelt path rules | Kernel |
| Credential theft | Never-grant blocklist (29 paths) | Kernel + Policy |
| Command injection | Dangerous command blocklist | Binary scanning |
| Privilege escalation | No CAP_SYS_ADMIN required | Kernel LSM |
| Network exfiltration | Landlock ABI v4+ TCP filtering | Kernel |
| Instruction file tampering | Sigstore bundle verification | Cryptographic |

**Kagenti Relevance:** **HIGH** — nono provides the in-container sandboxing layer that complements kubernetes-sigs/agent-sandbox's pod-level isolation. Deploy nono as the agent process launcher inside sandbox pods. The Sigstore attestation of CLAUDE.md/skills is directly relevant for verifying instruction file provenance.

**Integration Pattern:**
```
Sandbox Pod (gVisor/Kata via agent-sandbox)
  └── nono supervisor (runs as init process)
       └── agent process (Landlock-sandboxed)
            ├── Can access: /workspace/<context>/
            ├── Cannot access: ~/.ssh, ~/.kube, ~/.aws
            └── Network: filtered via Landlock ABI v4+
```

---

### 5.3 cgwalters/devaipod {#53-cgwaltersdevaipod}

**Repository:** https://github.com/cgwalters/devaipod

**What It Is:** Container-based sandboxing for AI coding agents using Podman with multi-container pod architecture and credential isolation via service-gator MCP server.

**Key Innovation — Multi-Container Pod with Credential Isolation:**
```
Podman Pod (shared network namespace)
├── Workspace Container   — human dev environment, HAS GH_TOKEN
├── Task Owner Container  — primary agent, NO GH_TOKEN, only LLM keys
├── Worker Container      — secondary agent, even more isolated
└── Gator Container       — service-gator MCP, HAS GH_TOKEN, enforces scopes
```

Source: [pod.rs](https://github.com/cgwalters/devaipod/blob/main/src/pod.rs) (~800 lines)

**Credential Scoping via service-gator MCP:**
```toml
[service-gator.gh.repos]
"*/*" = { read = true }                    # Global read-only
"myorg/main-project" = { create-draft = true }  # Draft PRs only
"myorg/trusted-repo" = { write = true }         # Full access (rare)
```

Source: [service_gator.rs](https://github.com/cgwalters/devaipod/blob/main/src/service_gator.rs)

**Workspace Isolation via Git:**
- Agent's `/workspaces/project` is `git clone --shared` (separate worktree, shared objects)
- Human reviews agent changes via explicit `git merge`
- Cross-mounts are read-only

Source: [git.rs](https://github.com/cgwalters/devaipod/blob/main/src/git.rs)

**Kagenti Relevance:** **MEDIUM-HIGH** — The credential isolation pattern (agent never receives GH_TOKEN; all external operations go through scoped MCP) is directly applicable to Kagenti. The service-gator concept maps to Kagenti's Keycloak-based token exchange: instead of passing raw tokens, the sandbox gets a scoped proxy.

---

### 5.4 arewm/ai-shell {#54-arewmai-shell}

**Repository:** https://github.com/arewm/ai-shell

**What It Is:** Per-project sandboxed development environment for AI coding agents on macOS/Linux using Podman. Focus on security defaults and path fidelity.

**Key Innovations:**

1. **Path Fidelity** — host directory mounted at exact same path inside container (e.g., `/Users/ladas/project` → `/Users/ladas/project`). Source: [configure.sh](https://github.com/arewm/ai-shell/blob/main/internal/assets/files/base/configure.sh) (lines 8-41)

2. **Trust-on-First-Use (TOFU)** — project-level configs prompt user approval; fingerprint stored in trust store. Source: [loader.go](https://github.com/arewm/ai-shell/blob/main/internal/config/loader.go) (lines 131-189)

3. **Per-Project Volume Isolation** — hash-based volume naming (`ai-home-<project>-<sha256[:12]>`) prevents cross-project contamination. Source: [project.go](https://github.com/arewm/ai-shell/blob/main/internal/container/project.go)

4. **Default-Deny Security:**
   - SSH keys NOT mounted by default
   - Only whitelisted env vars passed
   - Network isolated (no `--network=host`)

Source: [run.go](https://github.com/arewm/ai-shell/blob/main/internal/container/run.go) (lines 66-73)

**Kagenti Relevance:** **MEDIUM** — TOFU for agent instruction files (verify CLAUDE.md hash before trusting), per-project volume isolation pattern, and the security-by-default philosophy are applicable. The path fidelity concept is useful for tool compatibility.

---

### 5.5 bbrowning/paude {#55-bbrowningpaude}

**Repository:** https://github.com/bbrowning/paude

**What It Is:** Python-based containerization platform for running Claude Code in isolated environments with network-filtered security. Supports both Podman and OpenShift backends.

**Key Innovation — Network Filtering via Squid Proxy:**
```
┌── Paude Container ────────────────────────────────┐
│  Claude Code / Agent                               │
│  HTTP_PROXY=http://localhost:3128                   │
│  HTTPS_PROXY=http://localhost:3128                  │
└────────────────────────┬──────────────────────────┘
                         │
┌────────────────────────▼──────────────────────────┐
│  Squid Proxy Container                             │
│  ALLOW: .googleapis.com, .pypi.org                 │
│  DENY: everything else                             │
└───────────────────────────────────────────────────┘
```

Source: [containers/proxy/squid.conf](https://github.com/bbrowning/paude/blob/main/containers/proxy/squid.conf) (42 lines)

**Pluggable Backend Architecture:**
- `Backend` protocol with Podman and OpenShift implementations
- OpenShift backend uses StatefulSet + PVC for persistent sessions
- Source: [backends/openshift/backend.py](https://github.com/bbrowning/paude/blob/main/src/paude/backends/openshift/backend.py) (1,132 lines)

**Git-as-Trust-Boundary:**
- Code transfers only through explicit `git pull/push`
- Agent commits inside container; user pulls changes
- `git ext::` protocol for operations through paude CLI

Source: [cli.py](https://github.com/bbrowning/paude/blob/main/src/paude/cli.py) (1,542 lines)

**Security Properties:**
| Attack Vector | Status | Prevention |
|--------------|--------|------------|
| HTTP/HTTPS exfiltration | ✅ Blocked | Proxy ACL + internal network |
| Git SSH push | ✅ Blocked | No ~/.ssh mounted |
| Git HTTPS push | ✅ Blocked | No credential helpers |
| GitHub CLI operations | ✅ Blocked | `gh` not installed |
| Cloud credential modification | ✅ Blocked | ~/.config/gcloud mounted RO |

Source: [README.md security section](https://github.com/bbrowning/paude/blob/main/README.md)

**Kagenti Relevance:** **HIGH** — The Squid proxy sidecar pattern for network filtering is directly implementable in Kagenti. The OpenShift backend with StatefulSet + PVC is close to our deployment model. The `--yolo` mode safety (safe when combined with network filtering) maps to Kagenti's autonomous agent execution.

---

### 5.6 HKUDS/nanobot {#56-hkudsnanobot}

**Repository:** https://github.com/HKUDS/nanobot

**What It Is:** Ultra-lightweight (~4K LOC core) personal AI agent framework with multi-LLM support via litellm, MCP integration, and multi-channel deployment (Telegram, Discord, Slack, WhatsApp, etc.).

**Relevant Patterns:**

1. **Tool Registry with Safety Guards:**
   - Dangerous command pattern detection (rm -rf, fork bombs, dd)
   - Optional `restrictToWorkspace` mode for filesystem isolation
   - Timeout enforcement (60s default), output truncation (10KB)

   Source: [shell.py](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/tools/shell.py) (152 lines)

2. **Subagent Isolation:**
   - Limited tool set (no message tool, no spawn recursion)
   - Focused system prompts, max 15 iterations

   Source: [subagent.py](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/subagent.py) (258 lines)

3. **Context Builder from Bootstrap Files:**
   - Loads SOUL.md, AGENTS.md, USER.md, IDENTITY.md (analogous to CLAUDE.md)
   - Skills loaded as always-loaded (full content) or available (summary only)

   Source: [context.py](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/context.py)

4. **Multi-LLM via litellm:**
   - Unified API across 100+ providers (Claude, GPT, Gemini, local models)

   Source: [litellm_provider.py](https://github.com/HKUDS/nanobot/blob/main/nanobot/providers/litellm_provider.py) (272 lines)

**Kagenti Relevance:** **MEDIUM** — The context builder pattern (loading instruction files as system prompts) and multi-LLM pluggability via litellm are directly applicable. The tool registry with safety guards provides a reference implementation.

---

### 5.7 openclaw/openclaw — Security Lessons from Failure {#57-openclawopenclaw}

**Repository:** https://github.com/openclaw/openclaw

**What It Is:** AI assistant platform with multi-channel support (15+ platforms), Docker-based sandboxing, and an execution approval system. Formerly known as Clawdbot, then Moltbot.

**Why This Section Focuses on Failures:** OpenClaw experienced one of the most significant AI agent security crises to date. Between January-February 2026, the platform suffered [512 discovered vulnerabilities](https://www.kaspersky.com/blog/openclaw-vulnerabilities-exposed/55263/) (8 critical), [40,000+ exposed instances](https://www.infosecurity-magazine.com/news/researchers-40000-exposed-openclaw/) found via Shodan, [1-click RCE](https://thehackernews.com/2026/02/openclaw-bug-enables-one-click-remote.html) via sandbox bypass ([CVE-2026-25253](https://depthfirst.com/post/1-click-rce-to-steal-your-moltbot-data-and-keys), CVSS 8.8), a supply chain attack via the skills marketplace ([ClawHavoc](https://blog.cyberdesserts.com/openclaw-malicious-skills-security/)), and [1.5M API tokens exposed](https://www.kaspersky.com/blog/moltbot-enterprise-risk-management/55317/) in the adjacent Moltbook platform. [Cyera published a comprehensive security analysis](https://www.cyera.com/research-labs/the-openclaw-security-saga-how-ai-adoption-outpaced-security-boundaries).

**Critical Lessons for Kagenti:**

| OpenClaw Failure | Root Cause | Kagenti Mitigation |
|-----------------|-----------|-------------------|
| **Sandbox bypass via API** ([CVE-2026-25253](https://thehackernews.com/2026/02/openclaw-bug-enables-one-click-remote.html)) — attacker disables sandbox by sending `config.patch` to set `tools.exec.host: "gateway"` | Sandbox was a software toggle, not a kernel-enforced boundary. Control plane API could reconfigure it. | **C3: nono Landlock sandbox is irreversible** — once applied, it cannot be lifted from within the process. No API can disable it. |
| **Docker sandbox escape via PATH manipulation** ([CVE-2026-24763](https://www.kaspersky.com/blog/moltbot-enterprise-risk-management/55317/)) | Container sandbox relied on application-level PATH validation, not kernel enforcement | **C2: gVisor RuntimeClass** — even if application-level checks fail, gVisor intercepts syscalls at kernel level |
| **Cross-site WebSocket hijacking** — gateway didn't validate WebSocket origin header | Control plane exposed on localhost with no origin validation | **C5: Proxy sidecar** — agent has no direct network access; all traffic goes through Squid with domain allowlist |
| **Skills marketplace poisoning** ([ClawHavoc](https://blog.cyberdesserts.com/openclaw-malicious-skills-security/)) — backdoored skills uploaded to ClawHub, installed infostealer malware | Open publishing model, no code review, no attestation | **C4: Instruction file attestation** — Sigstore/hash verification of CLAUDE.md and skills before agent loads them. **C15: TOFU** for config trust |
| **312K instances exposed on default port** with no authentication | Default config had no auth; users deployed without changing defaults | **C12: SPIFFE/SPIRE** — every sandbox pod gets cryptographic identity; no unauthenticated access possible via Istio mTLS |
| **API keys and messages leaked** from exposed instances | Credentials stored in application state, accessible via control API | **C6: Credential isolation** — agent never receives raw tokens; scoped access via Keycloak token exchange only |

**What OpenClaw got right conceptually** (but failed to secure in practice):
- Three-tier execution approval (`deny`/`allowlist`/`full`) — good concept, but [bypassable via API](https://depthfirst.com/post/1-click-rce-to-steal-your-moltbot-data-and-keys). Source: [exec-approvals.ts](https://github.com/openclaw/openclaw/blob/main/src/infra/exec-approvals.ts)
- Container hardening defaults (read-only root, caps dropped) — good defaults, but [the sandbox itself was a software toggle](https://depthfirst.com/post/1-click-rce-to-steal-your-moltbot-data-and-keys). Source: [sandbox/config.ts](https://github.com/openclaw/openclaw/blob/main/src/agents/sandbox/config.ts)
- Path validation with symlink escape detection — useful pattern. Source: [sandbox-paths.ts](https://github.com/openclaw/openclaw/blob/main/src/agents/sandbox-paths.ts)

**Kagenti Relevance:** **HIGH (as cautionary study)** — OpenClaw demonstrates that application-level sandboxing without kernel enforcement is insufficient. Every security control that can be disabled via an API will be disabled by an attacker. The MITRE ATLAS investigation is required reading for anyone building agent sandboxing. Kagenti's architecture addresses each of these failure modes through kernel-enforced isolation (nono/gVisor), cryptographic identity (SPIRE), and network-level enforcement (proxy sidecar + Istio mTLS).

---

## 6. Broader Landscape: Commercial & Emerging Options {#6-broader-landscape}

| Platform | Isolation | Cold Start | K8s Native | BYOC | Maturity |
|----------|-----------|-----------|------------|------|----------|
| **[E2B](https://e2b.dev/)** | Firecracker microVM | ~150ms | No | [Terraform](https://github.com/e2b-dev/E2B) | Production (8.9K stars) |
| **[Northflank](https://northflank.com/)** | Kata/gVisor/Cloud Hypervisor | ~200ms | Yes | Yes (BYOC) | Production ([2M+ workloads/mo](https://northflank.com/blog/how-to-sandbox-ai-agents)) |
| **[Modal](https://modal.com/)** | gVisor | ~200ms | No | No | Production ([50K+ simultaneous](https://modal.com/blog/top-code-agent-sandbox-products)) |
| **[Daytona](https://www.daytona.io/)** | Docker (default) / Kata | <90ms | Yes (Helm) | Yes | Production |
| **[Docker Sandboxes](https://www.docker.com/products/docker-sandboxes/)** | [microVM](https://www.docker.com/blog/docker-sandboxes-a-new-approach-for-coding-agent-safety/) | ~500ms | No | No | Preview |
| **[microsandbox](https://github.com/zerocore-ai/microsandbox)** | microVM | <200ms | No | Self-hosted | Experimental (3.3K stars) |
| **[Cloudflare Sandboxes](https://developers.cloudflare.com/sandbox/)** | V8 isolates + containers | <5ms | No | No | Beta |
| **[Coder](https://coder.com/)** | Container/VM | ~5s | Yes | Yes | [Mature](https://coder.com/blog/launch-dec-recap) |
| **[SkyPilot](https://blog.skypilot.co/skypilot-llm-sandbox/)** | VMs (16+ clouds) | ~30s | Yes | Yes | Production |
| **[vcluster](https://www.vcluster.com/)** | Virtual K8s cluster | ~10s | Yes | Yes | [Mature](https://www.vcluster.com/docs/) |
| **[Edera Protect](https://edera.dev/)** | [Type-1 hypervisor zones](https://arxiv.org/html/2501.04580v1) | ~800ms | Yes (drop-in) | Yes | [GA 1.0](https://thenewstack.io/kubecon-eu-2025-edera-protect-offers-a-secure-container/) |
| **[Fly.io / Sprites](https://sprites.dev)** | Firecracker microVM | 1-12s | No | Planned | [GA](https://fly.io/blog/code-and-let-live/) |
| **[Koyeb](https://www.koyeb.com/)** | microVM + eBPF | 250ms wake | No | No | GA |
| **[Blaxel](https://blaxel.ai/)** | microVM | 25ms resume | No | No | Beta |
| **[Kuasar](https://kuasar.io/)** | Multi (VM/Wasm/runc) | Varies | Yes | Yes | [CNCF Sandbox](https://github.com/kuasar-io/kuasar) |

### Isolation Strength Tiers

| Tier | Technology | Kernel Shared? | Startup | Source |
|------|-----------|----------------|---------|--------|
| 1 (Weakest) | Standard containers (runc) | Yes | ~50ms | - |
| 2 | OS-level sandbox (Landlock/seccomp) | Yes | ~50ms | [nono](https://github.com/always-further/nono), [Claude Code sandbox-runtime](https://code.claude.com/docs/en/sandboxing) |
| 3 | gVisor (runsc) | No (user-space kernel) | ~100ms | [gvisor.dev](https://gvisor.dev/) |
| 4 | WebAssembly | No (no kernel) | <1ms | [SpinKube](https://www.cncf.io/blog/2024/03/12/webassembly-on-kubernetes-from-containers-to-wasm-part-01/), [Cosmonic](https://blog.cosmonic.com/engineering/2025-03-25-sandboxing-agentic-developers-with-webassembly/) |
| 5 | Kata/Firecracker microVM | No (dedicated kernel) | 125-500ms | [katacontainers.io](https://katacontainers.io/) |
| 6 (Strongest) | Edera Zones (Type-1 hypervisor) | No (bare-metal) | ~800ms | [arXiv paper](https://arxiv.org/html/2501.04580v1) |

**Additional references:** [Northflank: Best sandbox for AI agents](https://northflank.com/blog/best-code-execution-sandbox-for-ai-agents), [Better Stack: 10 Best Sandbox Runners 2026](https://betterstack.com/community/comparisons/best-sandbox-runners/), [awesome-sandbox](https://github.com/restyler/awesome-sandbox)

**Key Insight:** For Kagenti's use case (Kubernetes-native, BYOC, enterprise), the strongest options are:
1. **kubernetes-sigs/agent-sandbox** — native CRD, the standard
2. **Northflank** — production-proven microVM, BYOC (but commercial)
3. **gVisor RuntimeClass** — available today on GKE, configurable elsewhere

---

## 7. Container Runtime & OCI Standardization {#7-container-runtime}

### The containerd Comment (KubeCon EU 2026 Context)

The comment referenced in the issue highlights active work at the container runtime level:

> *"We have a fairly new containerd sandbox service at the container runtime level for integrating runtimes like katacontainers/nvidia/cri pod sandbox/…, and are looking to expand that to cover more use cases."*

**Key runtime developments relevant to agent sandboxing:**

| Initiative | Status | Impact on Agent Sandboxing |
|-----------|--------|---------------------------|
| **containerd sandbox service** | Active | Unified API for Kata/gVisor/nvidia sandboxes |
| **Shim API unification** | In discussion (containerd + CRI-O) | Common sandbox creation interface |
| **Sandbox networking refactor** | Proposed | DRA controllers managing sandbox netns |
| **NRI v1.0** (Node Resource Interface) | Pre-release | Pod spec mutation for isolation config |
| **OCI sandbox manifest** | WG forming | Standard definition of sandbox containers + shared resources |
| **Checkpoint/Restore** | KEP stage | Sandbox hibernation/migration |

**containerd Maintainer Summit (Feb 27, 2026)** will cover sandbox service expansion, shim API collaboration, and networking refactor.

**KubeCon EU CNCF Containerd Update** will present NRI, sandbox networking, and OCI standardization.

### What This Means for Kagenti

1. **Short term:** Use gVisor RuntimeClass (available today) or Kata via agent-sandbox
2. **Medium term:** Adopt containerd sandbox service API when stable — enables transparent runtime swapping
3. **Long term:** OCI sandbox manifest standardization will allow Kagenti to define "sandbox recipes" that work across containerd and CRI-O

---

## 8. Zero-Trust Identity & Token Exchange {#8-zero-trust}

### Kagenti's Existing Stack

Kagenti already has the building blocks:
- **SPIRE** — SPIFFE workload identity for pods ([components.md](https://github.com/kagenti/kagenti/blob/main/docs/components.md))
- **Keycloak** — OAuth/OIDC with token exchange support ([keycloak-patterns.md](https://github.com/kagenti/kagenti/blob/main/docs/install.md))
- **Istio Ambient** — mTLS between services without sidecars

### Token Exchange for Agent Sandboxes

The flow for a sandboxed agent accessing external resources:

```
┌─── Sandbox Pod ────────────────────────────────────┐
│  Agent Process                                      │
│  ├── Has: SPIFFE SVID (x509 cert from SPIRE)       │
│  ├── Wants: GitHub API access (scoped to org/repo)  │
│  └── Action: Token Exchange via Keycloak            │
└──────────────┬─────────────────────────────────────┘
               │ 1. Present SPIFFE SVID
               ▼
┌─── Keycloak ───────────────────────────────────────┐
│  Token Exchange Endpoint (RFC 8693)                 │
│  ├── Validates SPIFFE SVID (trust domain check)     │
│  ├── Maps SPIFFE ID → Keycloak client               │
│  ├── Applies scope restrictions (read-only, etc.)   │
│  └── Issues scoped access token                     │
└──────────────┬─────────────────────────────────────┘
               │ 2. Scoped access token
               ▼
┌─── External Service (GitHub API) ──────────────────┐
│  Accepts Keycloak-issued token                      │
│  Agent can: read code, create draft PR              │
│  Agent cannot: merge, delete, admin                 │
└────────────────────────────────────────────────────┘
```

**Key properties:**
- No static GitHub token in sandbox environment
- SPIFFE SVID is pod-scoped (sandbox identity)
- Keycloak enforces scope restrictions
- Token is short-lived (minutes, not days)
- Audit trail: Keycloak logs every token exchange

**Reference:** [Keycloak token exchange issue #36151](https://github.com/keycloak/keycloak/issues/36151) — enabling workload identity via token exchange, and [Microsoft Entra Agent ID guide](https://blog.christianposta.com/a-guide-to-microsoft-entra-agent-id-on-kubernetes/) for the agent identity pattern.

### Identity & Auth Landscape

| Solution | Type | K8s Native? | Agent-Specific? | Maturity | Source |
|----------|------|-------------|-----------------|----------|--------|
| **SPIFFE/SPIRE** | Workload identity (X.509/JWT) | Yes ([CSI driver](https://medium.com/universal-workload-identity/developer-friendly-zero-trust-using-spiffe-spire-part-5-container-storage-interface-csi-6119770cdfea)) | General workload | Graduated CNCF | [spiffe.io](https://spiffe.io/) |
| **MS Entra Agent ID** | Agent identity + OBO flows | Yes (sidecar) | Yes (first-class) | GA | [Guide](https://blog.christianposta.com/a-guide-to-microsoft-entra-agent-id-on-kubernetes/) |
| **Keycloak Token Exchange** | OAuth2 token exchange | Yes | General workload | In development | [#36151](https://github.com/keycloak/keycloak/issues/36151) |
| **GKE Workload Identity** | Token exchange to Cloud IAM | Yes (native) | General workload | GA | [GKE docs](https://docs.google.com/kubernetes-engine/docs/concepts/workload-identity) |
| **AKS Workload Identity** | OIDC federation to Entra | Yes (native) | General workload | GA | [AKS docs](https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview) |
| **Tailscale WIF** | OIDC federation | Yes ([operator](https://tailscale.com/blog/workload-identity-ga)) | General workload | GA | [Blog](https://tailscale.com/blog/workload-identity-ga) |

### Claude Code's Native Sandbox Runtime

Worth noting: Claude Code itself ships an open-source [`sandbox-runtime`](https://code.claude.com/docs/en/sandboxing) npm package that uses Landlock + seccomp for OS-level sandboxing without Docker. Anthropic's [secure deployment guide](https://platform.claude.com/docs/en/agent-sdk/secure-deployment) recommends combining it with gVisor RuntimeClass on Kubernetes for production. A community [Helm chart](https://metoro.io/blog/claude-code-kubernetes) is available for running Claude Code in K8s pods.

---

## 9. Kagenti AuthBridge: Token Exchange & Observability for Sandboxed Agents {#9-authbridge}

Kagenti already has an implementation of the token exchange and observability patterns described in sections 2 (C6, C12, C13) and 8: the **AuthBridge** extension.

### What AuthBridge Is

AuthBridge is an Envoy ext_proc (external processor) sidecar that runs alongside every agent pod. It provides two capabilities that are critical for sandboxed agents:

1. **Token Exchange** — Validates inbound JWTs and exchanges SPIFFE SVIDs for scoped access tokens via Keycloak (RFC 8693). The agent never sees raw credentials.
2. **OTEL Root Span Creation** — Creates infrastructure-level observability spans so that LLM observability platforms (MLflow) can trace agent invocations without any agent code changes.

Source: [identity-guide.md (AuthBridge section)](https://github.com/kagenti/kagenti/blob/main/docs/identity-guide.md), [kagenti-extensions/AuthBridge](https://github.com/kagenti/kagenti-extensions/tree/main/AuthBridge)

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Agent Pod (Sandbox)                                    │
│                                                         │
│  ┌── Envoy Sidecar (Istio Ambient) ──────────────────┐ │
│  │  ext_proc gRPC handler (Go)                        │ │
│  │  ├── [Inbound]  Validate JWT (JWKS from Keycloak) │ │
│  │  ├── [Outbound] Exchange SVID → scoped token      │ │
│  │  └── [OTEL]     Create root span + inject         │ │
│  │                  traceparent header                 │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌── Agent Container ────────────────────────────────┐ │
│  │  No credentials, no Keycloak knowledge            │ │
│  │  Just calls external services normally            │ │
│  │  → ext_proc transparently adds scoped tokens      │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

Configuration: [agent-namespaces.yaml (AuthBridge ConfigMap + Envoy config)](https://github.com/kagenti/kagenti/blob/main/charts/kagenti/templates/agent-namespaces.yaml)

### Token Exchange Flow for Sandboxed Agents

```
1. SPIFFE Helper obtains SVID from SPIRE Agent
2. Client Registration init container registers workload with Keycloak
   (using SPIFFE ID as client identity)
3. Caller (another agent or UI) gets JWT from Keycloak, scoped to caller's identity
4. Caller sends A2A request to sandbox agent with JWT
5. Envoy ext_proc intercepts:
   a. Validates JWT signature, expiration, issuer via Keycloak JWKS
   b. Exchanges caller's JWT for target-audience token
   c. Creates OTEL root span with GenAI semantic conventions
   d. Injects traceparent header
6. Request reaches agent container — no credentials exposed
7. Agent's auto-instrumented spans (LangChain, OpenAI) become children of root span
```

### Three Observability Approaches (Issue #667)

Research on branch [`feat/otel-authbridge-root-span-667`](https://github.com/Ladas/kagenti/tree/feat/otel-authbridge-root-span-667) evaluated three approaches. Each has a dedicated worktree:

| Approach | Worktree | Agent Changes | How It Works | Status |
|----------|----------|---------------|-------------|--------|
| **A: AuthBridge ext_proc** | `.worktrees/otel-authbridge-approach` | **Zero** | ext_proc parses A2A body, creates root span, injects traceparent | ✅ Default on OpenShift |
| **B: Minimal boilerplate** | `.worktrees/otel-minimal-agent` | ~50 lines | Agent creates root span, OTEL Collector enriches with MLflow/GenAI attributes | ✅ Alternative |
| **C: Correlation sidecar** | `.worktrees/otel-correlation-sidecar` | **Zero** | Envoy creates infra spans, post-hoc temporal backtracking reconstructs chains | 🔄 Complementary only |

**Approach A** is the default because:
- Agent needs zero code changes — just standard OTEL SDK + auto-instrumentation
- All GenAI/MLflow/OpenInference attributes set by ext_proc
- Centralized: update observability logic in one place, all agents benefit
- All 32 MLflow E2E tests pass

### How AuthBridge Maps to Sandbox Capabilities

| Sandbox Capability | AuthBridge Implementation |
|-------------------|--------------------------|
| **C6: Credential isolation** | ext_proc exchanges SVID → scoped token transparently; agent never receives raw credentials |
| **C12: Token exchange** | RFC 8693 via Keycloak; SPIFFE SVID as subject token, Keycloak client as target |
| **C13: Observability** | Root span creation with GenAI semantic conventions; traceparent injection into agent request |
| **C18: HITL delivery** | AuthBridge validates inbound JWTs from approval channels — only authorized callers can send messages to sandbox |

### Implication for Agent Sandbox Design

AuthBridge is **already built** and provides the token exchange (C6, C12) and observability (C13) layers described in the architecture (Section 3). For the full sandbox design, AuthBridge needs to be combined with:
- **gVisor/Kata RuntimeClass** (C1, C2) — pod-level isolation
- **nono Landlock** (C3) — kernel-level filesystem restriction
- **Squid proxy sidecar** (C5) — network-level domain filtering
- **SkillsLoader** (C10) — repo cloning + CLAUDE.md/skills loading

The AuthBridge ext_proc already runs as a sidecar in the Envoy mesh — it does not need a separate container. In the sandbox pod architecture, it coexists with the Squid proxy sidecar (different concerns: AuthBridge handles identity/tokens, Squid handles network filtering).

---

## 10. Mapping Projects to Architecture Layers {#10-mapping}

| Architecture Layer | Project | What It Provides | Integration |
|-------------------|---------|------------------|-------------|
| **Pod Lifecycle & CRD** | [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) | Sandbox CRD, warm pools, headless services, lifecycle | Direct adoption: deploy agent-sandbox controller |
| **Runtime Isolation** | gVisor / Kata (via agent-sandbox) | Kernel-level syscall interception / VM isolation | RuntimeClass in SandboxTemplate |
| **In-Container Sandbox** | [always-further/nono](https://github.com/always-further/nono) | Landlock/Seatbelt, capability builder, fd injection | nono as agent launcher (Python bindings) |
| **Instruction Attestation** | [always-further/nono](https://github.com/always-further/nono) trust module | Sigstore verification of CLAUDE.md/skills | Verify before agent loads instructions |
| **Credential Isolation** | [cgwalters/devaipod](https://github.com/cgwalters/devaipod) service-gator | MCP-based scoped access to GitHub/GitLab | Kagenti MCP gateway + Keycloak scoping |
| **Network Filtering** | [bbrowning/paude](https://github.com/bbrowning/paude) Squid proxy | Domain allowlist proxy sidecar | Sidecar container in sandbox pod |
| **Git Workspace Sync** | [bbrowning/paude](https://github.com/bbrowning/paude), [cgwalters/devaipod](https://github.com/cgwalters/devaipod), [arewm/ai-shell](https://github.com/arewm/ai-shell) | Git-as-trust-boundary, init-container clone | Init container + PVC persistence |
| **Config Trust (TOFU)** | [arewm/ai-shell](https://github.com/arewm/ai-shell) | Hash-based trust store for configs | Verify repo config hashes before exec |
| **Execution Approval** | Kagenti prototype + [OpenClaw lessons](#57-openclawopenclaw) | Three-tier allowlist — but OpenClaw showed software-only controls are [bypassable via API](https://thehackernews.com/2026/02/openclaw-bug-enables-one-click-remote.html) | settings.json HITL + kernel enforcement (nono) ensures controls cannot be disabled |
| **Permission Model** | Kagenti prototype | settings.json (allow/deny/HITL) + sources.json | Already implemented in sandbox agent |
| **Context Builder** | [HKUDS/nanobot](https://github.com/HKUDS/nanobot) | Bootstrap file loading, skills, multi-LLM | Adapt for CLAUDE.md + skills loading |
| **Multi-LLM API** | [HKUDS/nanobot](https://github.com/HKUDS/nanobot) litellm | Unified API for 100+ LLM providers | litellm as LLM abstraction layer |
| **Token Exchange** | Kagenti SPIRE + Keycloak | SPIFFE SVID → Keycloak → scoped access token | Existing infrastructure |
| **Observability** | Kagenti MLflow + OTEL | LLM trace capture, GenAI semantic conventions | Already integrated |
| **HITL Delivery** | [nono ApprovalBackend](https://github.com/always-further/nono/blob/main/crates/nono/src/supervisor/mod.rs) + Kagenti backend | Multi-channel approval routing (UI, Slack, GitHub, PagerDuty) with RBAC, nonce, expiry | Build: Kagenti Approval Backend with channel adapters |

---

## 11. Roadmap Alignment with kubernetes-sigs/agent-sandbox {#11-roadmap}

The [agent-sandbox roadmap](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/roadmap.md) includes "Integration with kAgent" (Kagenti). Here's how our needs map:

| Kagenti Need | Agent-Sandbox Roadmap Item | Status |
|-------------|---------------------------|--------|
| Sandbox CRD for agent pods | Core Sandbox API | ✅ v1alpha1 |
| Warm pool for fast provisioning | SandboxWarmPool + HPA | ✅ v1alpha1 |
| gVisor/Kata runtime | API support for isolation tech | ✅ gVisor, 🔄 expanding |
| PVC persistence across restart | Scale-down/Resume PVC-based | 🔄 In progress |
| NetworkPolicy defaults | SandboxTemplate with NetworkPolicy | ✅ v1alpha1 |
| OTEL tracing | Runtime API OTEL Instrumentation | 🔄 Planned |
| Multi-sandbox per pod (proxy sidecar) | API Support for Multi-Sandbox per Pod | 🔄 Planned |
| Auto-cleanup of ephemeral sandboxes | Auto-deletion of Bursty Sandboxes | 🔄 Planned |
| Status/health monitoring | Status Updates [#119] | 🔄 Planned |
| Creation latency metrics | Creation Latency Metrics [#123] | 🔄 Planned |
| Python SDK for sandbox management | PyPI Distribution [#146] | 🔄 Planned |

---

## 12. References {#12-references}

### Repositories Analyzed

| Repository | License | Compatible? | Key Contribution |
|-----------|---------|-------------|------------------|
| [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) | Apache-2.0 | ✅ Yes | Sandbox CRD, warm pools, K8s-native |
| [always-further/nono](https://github.com/always-further/nono) | Apache-2.0 | ✅ Yes | Kernel-enforced sandbox, Sigstore attestation |
| [cgwalters/devaipod](https://github.com/cgwalters/devaipod) | MIT OR Apache-2.0 | ✅ Yes | Credential isolation, service-gator MCP |
| [arewm/ai-shell](https://github.com/arewm/ai-shell) | **No license** | ⚠️ Cannot use | TOFU, path fidelity, per-project volumes |
| [bbrowning/paude](https://github.com/bbrowning/paude) | MIT | ✅ Yes | Squid proxy, OpenShift backend, git sync |
| [HKUDS/nanobot](https://github.com/HKUDS/nanobot) | MIT | ✅ Yes | Multi-LLM via litellm, context builder |
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | MIT | ✅ Yes | **Cautionary study** — [512 vulns](https://www.kaspersky.com/blog/openclaw-vulnerabilities-exposed/55263/), [1-click RCE](https://thehackernews.com/2026/02/openclaw-bug-enables-one-click-remote.html), [security saga](https://www.cyera.com/research-labs/the-openclaw-security-saga-how-ai-adoption-outpaced-security-boundaries) |

### Kagenti Sources

- [Agent Context Isolation Design](https://github.com/kagenti/kagenti/blob/main/docs/plans/2026-02-14-agent-context-isolation-design.md)
- [Agent Context Isolation Implementation](https://github.com/kagenti/kagenti/blob/main/docs/plans/2026-02-14-agent-context-isolation-impl.md)
- [Sandbox Agent Passover (Feb 18)](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/docs/plans/2026-02-18-sandbox-agent-passover.md)
- [Sandbox Agent E2E Tests](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/kagenti/tests/e2e/common/test_sandbox_agent.py)
- [Sandbox Agent Deployment YAML](https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/kagenti/examples/agents/sandbox_agent_deployment.yaml)

### External References

- [Northflank: How to sandbox AI agents](https://northflank.com/blog/how-to-sandbox-ai-agents) — Comprehensive isolation comparison
- [Northflank: Best code execution sandbox](https://northflank.com/blog/best-code-execution-sandbox-for-ai-agents) — Platform ranking
- [Microsoft Entra Agent ID on Kubernetes](https://blog.christianposta.com/a-guide-to-microsoft-entra-agent-id-on-kubernetes/) — Agent identity + token exchange
- [Keycloak: Workload identity via token exchange #36151](https://github.com/keycloak/keycloak/issues/36151) — Token exchange for K8s workloads
- [Docker Sandboxes](https://www.docker.com/products/docker-sandboxes/) — microVM isolation for coding agents
- [OpenAI Codex Security](https://developers.openai.com/codex/security/) — Sandbox modes documentation
- [E2B](https://e2b.dev/) — Firecracker-based agent sandbox
- [microsandbox](https://github.com/zerocore-ai/microsandbox) — Open-source self-hosted microVM sandbox
- [InfoQ: Agent Sandbox on Kubernetes](https://www.infoq.com/news/2025/12/agent-sandbox-kubernetes/) — SIG announcement
- [agent-sandbox roadmap](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/roadmap.md) — Full 2026+ roadmap

### Container Runtime References

- containerd sandbox service — discussed at containerd maintainer summit (Feb 27, 2026)
- NRI (Node Resource Interface) — approaching v1.0, supported by containerd and CRI-O
- OCI sandbox manifest — WG forming for standardization
- DRA (Dynamic Resource Allocation) — proposed for sandbox networking

---

*This document was generated from deep analysis of 7 cloned repositories (at `.worktrees/sandbox_research/`), Kagenti's existing sandbox prototype, web research on 20+ sandboxing platforms, license verification of all projects, and the containerd maintainer summit discussion. All licenses verified as Apache-2.0 compatible except arewm/ai-shell (no license file — concepts only, do not use code directly).*

*Updated Feb 25, 2026: Added C19 (multi-conversation isolation) and C20 (sub-agent spawning) to capability matrix. Updated Section 4 from POC to Phases 1-9 implementation status. Added security review findings from PR #126. Updated C2 with gVisor/SELinux deferral analysis. Updated isolation layers with implementation status. Added C19/C20 architecture diagrams. Updated "already built" table with all Phase 1-9 implementations.*
