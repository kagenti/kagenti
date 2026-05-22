# Agent Sandbox

> Skills-Driven Coding Agents in Kubernetes Isolation

**Date**: 2026-02-23 (updated 2026-02-25)
**Status**: Research + Prototype (22 files, +2,601 LOC across two repos)

---

## Motivation

Engineers use Claude Code with `CLAUDE.md` and `.claude/skills/` to encode organizational
knowledge into repeatable, LLM-driven workflows. Today these only run on a developer's
laptop. There is no supported path to execute the same skills inside a Kubernetes-hosted
sandbox with proper isolation, identity, and credential management.

This gap matters for three reasons:

1. **Autonomous execution** -- Agents triggered by cron, alerts, webhooks, or A2A messages
   need isolated, ephemeral compute that no human is watching.
2. **Untrusted-code safety** -- Engineers working on external or AI-generated code need
   stronger isolation than a local shell provides.
3. **Lessons from [OpenClaw](https://github.com/openclaw/openclaw)** --
   [CVE-2026-25253](https://www.cve.org/CVERecord?id=CVE-2026-25253) demonstrated
   that application-level sandboxing without kernel enforcement leads to 1-click RCE,
   supply-chain attacks, and 40K+ exposed instances. Software toggles are not
   security boundaries.

## Goals

- Run a repo's `CLAUDE.md` and `.claude/skills/` inside Kubernetes with **any LLM**
  (via litellm), reusing the exact same skills an engineer uses locally.
- Support two modes: **interactive** (engineer-driven, SSH/web terminal) and
  **autonomous** (triggered by cron/alert/webhook/A2A, no human in loop).
- Achieve defense-in-depth through five isolation layers, ensuring no single bypass
  compromises the system.

## Key Features

The design defines 20 capabilities (C1-C20). The most significant:

| Capability | What it provides |
|------------|------------------|
| **Sandbox CRDs** (C1) | Declarative pod lifecycle with warm pools, stable DNS, and automatic expiry via [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) |
| **Kernel Sandbox** (C3) | Landlock LSM + seccomp-BPF via [nono](https://github.com/always-further/nono); irreversible once applied, with hardcoded blocklist for sensitive paths |
| **Network Filtering** (C5) | Squid forward-proxy sidecar with domain allowlist; unlisted domains get HTTP 403 |
| **Credential Isolation** (C6) | AuthBridge (Envoy ext_proc) exchanges pod's SPIFFE SVID for scoped OAuth2 tokens; agent code never sees credentials |
| **Skills Loading** (C10) | SkillsLoader parses CLAUDE.md and .claude/skills/ into structured, model-agnostic LLM context |
| **Multi-LLM** (C11) | litellm unified API across 100+ providers; model selection via env vars, no code changes |
| **Token Exchange** (C12) | RFC 8693 flow: SPIFFE SVID presented to Keycloak returns short-lived, scope-restricted OAuth2 tokens |
| **Observability** (C13) | AuthBridge creates OTEL root spans with GenAI semantic conventions; zero agent code changes |
| **Execution Approval** (C14) | LangGraph interrupt() + A2A input_required for human-in-the-loop gating |
| **Autonomous Triggers** (C17) | FastAPI endpoints binding cron, webhooks, PagerDuty, and A2A events to SandboxTemplates |

## Proposed Architecture

### Defense-in-Depth: Five Isolation Layers

```
Outer ──────────────────────────────────────────────── Inner

  NetworkPolicy        Squid Proxy       Container       Runtime        nono Landlock
  + Istio mTLS         L7 Domain         Hardening       Isolation      Kernel-Enforced
  (L3/L4)              Filtering         SecurityContext  gVisor/Kata    Irreversible
  [deployed]           [built]           [enforced]      [deferred*]    [verified]
```

\* gVisor deferred due to SELinux incompatibility on RHCOS; Kata Containers is the forward path.

### Sandbox Pod Anatomy

```
┌─────────────────────────────────────────────────────────┐
│  Sandbox Pod                                            │
│                                                         │
│  ┌─────────────┐  ┌──────────────────────────────────┐  │
│  │ Init:       │  │ Agent Container                  │  │
│  │ git clone   │  │  A2A Server (Starlette)          │  │
│  │ TOFU check  │  │  LangGraph Agent + MemorySaver   │  │
│  │             │  │  SandboxExecutor (asyncio)       │  │
│  └─────────────┘  │  PermissionChecker               │  │
│                   │  SkillsLoader                    │  │
│  ┌─────────────┐  │  RepoManager                     │  │
│  │ Squid Proxy │  │  litellm                         │  │
│  │ (sidecar)   │  │  ── Landlock + seccomp ───────── │  │
│  └─────────────┘  └──────────────────────────────────┘  │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐│
│  │ Envoy (Istio Ambient) + AuthBridge ext_proc         ││
│  │  Token exchange (SVID -> OAuth2) + OTEL root spans  ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

### Zero-Trust Identity Flow

1. SPIFFE Helper obtains a pod-scoped SVID from SPIRE Agent
2. Client Registration registers the workload identity with Keycloak
3. On each outbound request, AuthBridge intercepts via Envoy ext_proc:
   validates the caller's JWT, exchanges it for a target-audience token,
   creates an OTEL root span, and injects traceparent
4. The agent container never holds or sees any credential

### Trust Verification Chain

```
git clone -> TOFU hash check -> Sigstore attestation -> skills loading
```

Breaking any link prevents poisoned instructions from reaching the agent.

## Research: Open-Source Projects

Seven projects were evaluated across the agent sandboxing landscape:

| Project | Relationship | Key Contribution |
|---------|-------------|------------------|
| [**kubernetes-sigs/agent-sandbox**](https://github.com/kubernetes-sigs/agent-sandbox) | Direct dependency | Sandbox CRDs, warm pools, SandboxClaim lifecycle |
| [**always-further/nono**](https://github.com/always-further/nono) | Direct dependency | Landlock + seccomp kernel enforcement, Sigstore attestation, Python bindings (PyO3) |
| [**cgwalters/devaipod**](https://github.com/cgwalters/devaipod) | Concepts replicated | Credential isolation via MCP proxy (agent never receives tokens) |
| [**arewm/ai-shell**](https://github.com/arewm/ai-shell) | Concepts replicated | TOFU for project configs, per-project volume isolation |
| [**bbrowning/paude**](https://github.com/bbrowning/paude) | Pattern replicated | Squid proxy sidecar for L7 domain filtering |
| [**HKUDS/nanobot**](https://github.com/HKUDS/nanobot) | Patterns adopted | Tool registry with safety guards, multi-LLM via litellm |
| [**openclaw/openclaw**](https://github.com/openclaw/openclaw) | Cautionary tale | CVE-2026-25253 (1-click RCE); proves kernel enforcement is non-negotiable |

Commercial landscape also surveyed: Northflank (microVM/BYOC), E2B (Firecracker),
Docker Sandboxes, OpenAI Codex, microsandbox.

## Key Design Decisions

1. **gVisor deferred, Kata forward path** -- gVisor rejects all SELinux labels required
   by CRI-O on RHCOS. Four other isolation layers provide adequate protection today.

2. **Skills from primary repo only** -- Dynamically cloned repos are data; their
   instruction files are never loaded. Prevents supply-chain poisoning.

3. **AuthBridge as single interception point** -- Token exchange and observability in
   one Envoy ext_proc component. Already built and deployed.

4. **Pod-per-conversation for autonomous mode** -- Full process/filesystem/network
   isolation between conversations. Shared-pod mode only when a human is watching.

5. **Two sub-agent modes** -- In-process (LangGraph StateGraph, scoped tools, fast)
   for analysis; out-of-process (SandboxClaim + A2A, full isolation) for untrusted work.

6. **litellm for LLM pluggability** -- Skills are plain text, transferable across models.
   Supports Claude, GPT, Gemini, Llama, Qwen, and local models via Ollama.

## Roadmap Alignment

The kubernetes-sigs/agent-sandbox roadmap includes scale-down/resume, Firecracker/QEMU
support, DRA controllers, OCI sandbox manifest standardization, and explicit
"Integration with kAgent" -- all directly beneficial to Kagenti.
