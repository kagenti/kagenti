# Coding Agent Variants for Kagenti: Research & Architecture Proposals

**Date:** 2026-02-26
**Status:** Research
**Context:** Evaluating Claude Code stack, open-source alternatives, and MCP/A2A protocol integration as new agent variants alongside the existing LangGraph-based sandbox agent.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State: LangGraph + A2A Sandbox Agent](#2-current-state-langgraph--a2a-sandbox-agent)
3. [The Claude Code Stack](#3-the-claude-code-stack)
4. [Coding Agent Solutions: Comprehensive Comparison](#4-coding-agent-solutions-comprehensive-comparison)
5. [Agent UIs, API Models, and Management Concepts](#5-agent-uis-api-models-and-management-concepts)
6. [MCP vs A2A: Protocols in Depth](#6-mcp-vs-a2a-protocols-in-depth)
7. [Dual-Protocol Patterns (MCP + A2A)](#7-dual-protocol-patterns-mcp--a2a)
8. [Architecture Proposals](#8-architecture-proposals)
9. [Recommendation](#9-recommendation)
10. [References](#10-references)

---

## 1. Executive Summary

Kagenti currently deploys AI agents as **LangGraph-based A2A services** in Kubernetes pods with layered isolation (namespace RBAC, Istio mTLS, gVisor, Landlock, Squid proxy). This research evaluates whether the **Claude Code stack** (Agent SDK, MCP) or **open-source coding agents** (OpenHands, Goose, OpenCode, etc.) could serve as additional agent variants on the platform.

**Key findings:**

- **Claude Code is proprietary** (all rights reserved), but the **Claude Agent SDK** (Python/TypeScript) exposes the same agentic loop as a library and can be wrapped in an A2A server with ~200 lines of code. The Claude Code ecosystem now includes security scanning, Agent Teams, hooks, 9,000+ plugins, and 6 surfaces (Terminal, VS Code, JetBrains, Desktop, Web, Chrome).
- **OpenHands** (MIT, 68k stars) is the most Kubernetes-ready open-source alternative with Docker-native sandboxing, REST/WebSocket API, and 100+ LLM providers via LiteLLM.
- **12 solutions compared** across 4 matrices (summary, protocol/integration, security/isolation, adoption/ecosystem) — from our own Sandbox Agent to Claude Agent SDK, OpenHands, Goose, OpenCode, Aider, SWE-agent, Cline, Gemini CLI, Codex CLI, Roo Code, and Sympozium.
- **MCP and A2A are complementary, not competing** — MCP is agent-to-tool (vertical), A2A is agent-to-agent (horizontal). Both are under the Linux Foundation. A single agent can serve both protocols simultaneously. Kagenti already has an MCP gateway (partially working, not e2e tested).
- **Google ADK** is the only framework that natively supports both MCP and A2A out of the box.
- **Sympozium** (MIT, 3 days old, by k8sgpt creator) is a Kubernetes-native agent platform with interesting skill sidecar isolation patterns but no A2A/MCP support.

**Three architecture proposals** are presented: Claude Agent SDK + A2A (proprietary path), OpenHands + A2A (open-source path), and a multi-framework demo showing Kagenti's framework neutrality.

---

## 2. Current State: LangGraph + A2A Sandbox Agent

### Architecture

The sandbox agent (branch `feat/sandbox-agent`) deploys as a standard Kubernetes pod:

![Kagenti Sandbox Agent Pod](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti-platform/08-coding-agent-variants/01-sandbox-agent-pod.gif)

<details><summary>Diagram source: 01-sandbox-agent-pod</summary>

**File:** `articles/202602071828-kagenti-platform/08-coding-agent-variants/diagrams/01-sandbox-agent-pod.svg`

Kubernetes pod architecture for the current LangGraph-based sandbox agent. Shows Init container (git clone, repo sync, skills loading), main Agent Container (A2A server, LangGraph graph, litellm multi-LLM, SkillsLoader, WorkspaceManager, PermissionChecker) with A2A Protocol badge and `/.well-known/agent.json` endpoint, Squid Proxy sidecar (domain allowlist: github.com, pypi.org; evil.com = 403), nono Landlock sidecar (filesystem restrictions, kernel-level sandbox, read-only root FS). Bottom bar shows AuthBridge (SPIFFE -> OAuth) and Istio Ambient (mTLS). Animated: flow dot from Init to Agent container, pulse on A2A badge. Style: light theme, rounded rects with colored headers (blue=init, green=agent, red=proxy, yellow=landlock), drop shadows, system-ui font.
</details>

### What Works (47/48 tests passing)

| Capability | Status |
|-----------|--------|
| C1: Pod lifecycle CRDs (Sandbox, SandboxTemplate, SandboxClaim) | Done |
| C3: Kernel sandbox (nono Landlock) | Done |
| C5: Network filtering (Squid proxy) | Done |
| C6: Credential isolation (AuthBridge SVID→token) | Built |
| C9: Git workspace sync (RepoManager) | Done |
| C10: Skills/CLAUDE.md loading (SkillsLoader) | Done |
| C11: Multi-LLM pluggability (litellm) | Done |
| C13: Observability (OTEL) | Scaffolded |
| C14-C18: HITL, triggers, multi-channel approval | Scaffolded |

### A2A Integration Pattern

Every agent exposes `/.well-known/agent-card.json` and implements the A2A JSON-RPC interface:

```python
# agent.py (simplified)
from a2a.server.agent_execution import AgentExecutor
from a2a.types import AgentCard, AgentCapabilities

class SandboxAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        # Delegate to LangGraph graph
        async for event in graph.astream(input_state, config):
            await event_queue.enqueue(event)

def get_agent_card(host, port) -> AgentCard:
    return AgentCard(
        name="Sandbox Legion",
        url=f"http://{host}:{port}/",
        capabilities=AgentCapabilities(streaming=True),
        skills=[AgentSkill(id="sandbox_legion", ...)]
    )
```

**This A2A wrapper pattern is reusable for any agent framework.** The key is implementing `AgentExecutor.execute()` to delegate to whatever agent runtime you choose.

---

## 3. The Claude Code Stack

### 3.1 Claude Code CLI

| Aspect | Detail |
|--------|--------|
| **Stack** | TypeScript + React/Ink (terminal UI) + Yoga (layout) |
| **Build tool** | Bun (fast bundling; runtime is Node.js 18+) |
| **Distribution** | npm (`@anthropic-ai/claude-code`) |
| **License** | Proprietary (Anthropic Commercial Terms, all rights reserved) |
| **Self-written** | ~90% of Claude Code's code is written by Claude Code itself |

**Agentic loop:** Sends full conversation to `POST /v1/messages` with `stream: true`, receives SSE events, executes tool calls locally (Read, Write, Edit, Bash, Glob, Grep, WebSearch, etc.), loops until `stop_reason: "end_turn"`.

**API compatibility:** Standard Anthropic Messages API. Can be pointed at alternative endpoints via `ANTHROPIC_BASE_URL` (Ollama v0.14.0+, Bedrock, Vertex AI, Azure AI Foundry).

### 3.2 Claude Desktop

Electron-based GUI application. First-class **MCP host** — connects to MCP servers for tool integration. Desktop Extensions (`.mcpb`) enable one-click MCP server installation. Separate product from Claude Code.

### 3.3 Claude Code on the Web

Runs on **Anthropic-managed VMs** (not self-hostable). Isolated sandbox per session with GitHub proxy for credential isolation. Supports `--remote` for cloud execution and `/teleport` to pull sessions back to terminal. Available for Pro/Max/Team/Enterprise users.

### 3.4 Claude Agent SDK

The programmable building block. Available in **Python** (`claude-agent-sdk`) and **TypeScript** (`@anthropic-ai/claude-agent-sdk`).

```python
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(
    prompt="Find and fix the bug in auth.py",
    options=ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Bash"],
        model="claude-sonnet-4-6",
    ),
):
    print(message)
```

**Key capabilities:**
- Built-in tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
- Hooks: PreToolUse, PostToolUse, Stop, SessionStart, SessionEnd
- Subagents via `AgentDefinition` + `Task` tool
- MCP integration (connect to external MCP servers)
- Sessions with resume/fork
- Structured outputs (validated JSON)
- Supports Anthropic API, Bedrock, Vertex AI, Azure AI Foundry

### 3.5 Claude Code Security (Feb 20, 2026)

Dedicated reasoning-based vulnerability scanner built into Claude Code on the Web. **Limited research preview** for Enterprise/Team customers. Open-source maintainers can apply for free access.

**How it works:** Uses Claude Opus 4.6 to reason about code like a human security researcher — traces data flows across files, understands component interactions, catches logic-level vulnerabilities that pattern-matching SAST tools miss. Every finding goes through multi-stage verification to filter false positives.

**Results:** Found **500+ previously unknown high-severity vulnerabilities** in production open-source codebases — bugs that survived decades of expert review. In the CGIF library, discovered a heap buffer overflow by reasoning about the LZW compression algorithm (something fuzzing with 100% code coverage couldn't catch).

**Comparison with traditional SAST:**

| Tool | Strengths | Misses |
|------|-----------|--------|
| CodeQL | Most precise queries, deep semantic analysis | Logic-level auth/IDOR flaws |
| Snyk Code | AI-trained, best SCA, full platform | Logic-level auth/IDOR flaws |
| Semgrep | Fastest, simplest custom rules | Logic-level auth/IDOR flaws |
| SonarQube | Code quality focus | Limited security detection |
| **Claude Code Security** | Cross-file reasoning, logic bugs, novel zero-days | Non-deterministic, no CVE DB matching |

**Industry consensus:** Complementary, not replacement. Use AI reasoning for novel vulnerability discovery + deterministic tools for known patterns and compliance audit trails.

**Also available as:**
- `/security-review` slash command (built into Claude Code CLI)
- `anthropics/claude-code-security-review` GitHub Action (diff-aware PR scanning)

### 3.6 Agent Teams (Feb 5, 2026 — Experimental)

Multi-agent coordination within Claude Code. Enable with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`.

- One session acts as **team lead**, coordinating and synthesizing
- **Teammates** execute independently with their own context windows
- Teammates can message each other directly (peer-to-peer)
- Task claiming uses file locking to prevent race conditions
- Notable demo: 16 agents built a 100,000-line C compiler in Rust ($20K API cost)

### 3.7 Hooks System

Deterministic triggers that run shell commands at lifecycle points. Unlike prompts (suggestions), hooks are **guarantees**.

| Hook | Purpose | Security Use |
|------|---------|-------------|
| **PreToolUse** | Runs before any action. Can **block** (exit code 2) | Block dangerous commands, protect .env files |
| **PostToolUse** | Runs after action completes | Security scans on every change, audit logging |
| **SessionStart** | Runs at session start | Install dependencies, verify environment |
| **Stop** | Runs before session ends | Cleanup, final checks |

Three handler types: `command` (shell), `prompt` (single-turn LLM eval), `agent` (subagent with Read/Grep/Glob).

### 3.8 Plugin System (9,000+ plugins)

Bundles four extension types: slash commands, subagents, hooks, and skills. Official Anthropic marketplace plus community directories. Key feature: **MCP Tool Search** — lazy loading for MCP server tools, reducing context usage by 95%.

### 3.9 Claude Cowork (Separate Product — Jan 2026)

"Claude Code for the rest of your work" — general-purpose AI agent for knowledge workers. Processes XLSX, PPTX, DOCX, PDF. Parallel task queuing. Enterprise expansion (Feb 24): connectors for Google Drive, Gmail, DocuSign; 11 official plugins; department-specific agents (finance, engineering, HR).

### 3.10 Additional Surfaces

| Surface | Description |
|---------|------------|
| **Desktop App** | Electron app with visual diff review, PR monitoring, CI failure handling |
| **Chrome Extension** | Browser automation — navigate, click, fill forms, read console logs |
| **Remote Control** | Bridge local CLI to mobile/browser (Feb 25, 2026) |
| **Slack Integration** | @Claude in Slack triggers automated sessions |
| **CI/CD** | GitHub Actions (official), GitLab CI/CD (official), Jenkins (community) |

### 3.11 Containerization Options

| Option | Description |
|--------|------------|
| **Official DevContainer** | Docker-based dev container with multi-layered firewall, `--dangerously-skip-permissions` for headless |
| **claude-code-action** | GitHub Actions runner (MIT licensed) |
| **Community Helm chart** | `chrisbattarbee/claude-code-helm` — deploy to K8s |
| **Docker Sandboxes** | Docker microVMs for isolated agent execution |
| **Netclode** | Self-hosted cloud coding agent with K8s + microVM sandboxes |
| **Claude Flow** | Multi-agent orchestration with K8s architecture |

### 3.12 API Console Workspaces

Organizational units for managing API resources in the Anthropic Console. **Not a dev environment** (unlike Codespaces/Gitpod). Features: per-workspace API keys, spend limits, rate limits, access controls, cost reporting. Limit: 100 workspaces per org. Included at no additional cost.

### 3.13 Open Source Status

Claude Code CLI is **NOT open source**. The GitHub repo (`anthropics/claude-code`) hosts docs and issue tracking only. Community has requested open-sourcing (issue #22002) noting that OpenAI Codex CLI and Google Gemini CLI are both Apache 2.0. Team said they "weren't ready to be good public stewards yet" (March 2025).

**What IS open source:** claude-code-action (MIT), MCP spec/SDKs (Linux Foundation), Agent SDK packages (on npm/PyPI, governed by Anthropic terms).

---

## 4. Coding Agent Solutions: Comprehensive Comparison

This section compares **all** coding agent solutions evaluated for deployment on Kagenti — including our own sandbox-agent/sandbox-legion approach, Anthropic's proprietary stack, open-source alternatives, and Kubernetes-native platforms.

### 4.1 Comparison Matrices

#### Matrix A: Summary Overview

| Solution | Stars | License | Language | Created By | Status |
|----------|-------|---------|----------|-----------|--------|
| **Kagenti Sandbox Agent** | — | Proprietary | Python | Kagenti team | POC (47/48 tests) |
| **Claude Agent SDK** | — | Anthropic Terms | Python/TS | Anthropic | GA |
| **OpenHands** | 68k | MIT | Python | All-Hands AI | GA |
| **Cline** | 58k | Apache 2.0 | TypeScript | Cline team | GA |
| **Aider** | 41k | Apache 2.0 | Python | Paul Gauthier | GA |
| **OpenCode** | 100K+ | MIT | TS (Bun) | Anomaly (ex-SST) | GA (v1.2.14) |
| **Goose** | 31k | Apache 2.0 | Rust | Block | GA |
| **Roo Code** | 22k | Apache 2.0 | TypeScript | Roo Code Inc | GA |
| **SWE-agent** | 19k | MIT | Python | Princeton/Stanford | GA |
| **Gemini CLI** | 12k | Apache 2.0 | TypeScript | Google | GA |
| **Codex CLI** | — | Apache 2.0 | Rust | OpenAI | GA |
| **Sympozium** | 57 | MIT | Go | AlexsJones (k8sgpt) | Alpha (3 days old) |

#### Matrix B: Protocol & Integration

| Solution | A2A | MCP | Headless | K8s Ready | LLM Providers |
|----------|-----|-----|----------|-----------|---------------|
| **Kagenti Sandbox Agent** | Native | Via gateway | Yes (API) | Native | 100+ (litellm) |
| **Claude Agent SDK** | No (wrappable) | Native client | Yes (SDK) | Via DevContainer | Claude only (+Bedrock/Vertex/Azure) |
| **OpenHands** | No (wrappable) | Yes (V1 SDK) | REST/WS API | Best | 100+ (LiteLLM) |
| **Cline** | No | Yes | CLI 2.0 `-y` | In progress | Many (OpenRouter, etc.) |
| **Aider** | No | No | CLI-first | Moderate (Docker image) | Many (OpenAI-compat) |
| **OpenCode** | No (requested) | Yes (OAuth) | `opencode serve` | Good (community Helm) | 75+ (Models.dev) |
| **Goose** | Indirect (AAIF) | Core architecture | Partial | Good (Docker Compose) | Any, multi-model |
| **Roo Code** | No | Yes | Partial | Partial | Any (Claude, GPT, Gemini, Ollama) |
| **SWE-agent** | No | No | CLI-only | Good (SWE-ReX) | Any (LiteLLM) |
| **Gemini CLI** | No | Yes | Native | Moderate | Gemini only |
| **Codex CLI** | No | No | CLI-first | Yes (cloud) | OpenAI only |
| **Sympozium** | No | No | TUI/CLI | Native (CRDs) | OpenAI, Anthropic, Ollama |

#### Matrix C: Security & Isolation

| Solution | Sandbox Model | Network Isolation | Credential Isolation | Security Scanning | HITL |
|----------|--------------|-------------------|---------------------|-------------------|------|
| **Kagenti Sandbox Agent** | 5-layer (K8s + Istio + gVisor + Landlock + Squid) | Squid proxy allowlist | AuthBridge (SPIFFE→OAuth) | No | Yes (multi-channel) |
| **Claude Agent SDK** | Relies on external | External (DevContainer firewall) | API key env var | Built-in (`/security-review`) | Hooks (PreToolUse) |
| **OpenHands** | Docker per session | Docker network | Env vars in container | No | Event-based approval |
| **Cline** | Permission-per-action | None built-in | Env vars | No | Yes (approval prompts) |
| **Aider** | Git-based rollback | None built-in | Env vars | No | No |
| **OpenCode** | Process-level | None built-in | Env vars | No | No |
| **Goose** | Container Use MCP | Docker isolation | Env vars | No | No |
| **Roo Code** | Permission-per-action | None built-in | Env vars | No | Yes (approval prompts) |
| **SWE-agent** | Docker per run (SWE-ReX) | Docker network | Env vars | No | No |
| **Gemini CLI** | Process-level | None built-in | Google account | No | No |
| **Codex CLI** | Isolated cloud container | No outbound internet | OpenAI-managed | No | No |
| **Sympozium** | Sidecar + ephemeral RBAC + NetworkPolicy | NetworkPolicy deny-all | K8s Secrets | No | No |

#### Matrix D: Adoption & Ecosystem

| Solution | Community | Enterprise Support | Plugin/Extension System | CI/CD Integration | IDE Support |
|----------|-----------|-------------------|------------------------|-------------------|-------------|
| **Kagenti Sandbox Agent** | Internal | Platform-native | Skills/CLAUDE.md | GitHub Actions | Kagenti UI |
| **Claude Agent SDK** | Growing | SOC 2 / ISO 27001 | 9,000+ plugins, MCP | GitHub Actions, GitLab | VS Code, JetBrains, Desktop |
| **OpenHands** | 68k stars, $18.8M funded | K8s self-hosting | MCP tools | REST API | Web UI, VS Code |
| **Cline** | 58k stars, 5M installs | SOC 2 Type 2 | MCP, ACP | GitHub Actions, GitLab | VS Code, JetBrains, Cursor |
| **Aider** | 41k stars | Community only | Community MCP servers | Docker-based | Terminal only |
| **OpenCode** | 36k stars | None | MCP native | None | Terminal TUI |
| **Goose** | 31k stars, Linux Foundation | AAIF backing | MCP core, Extensions | Docker Compose | Terminal, Electron |
| **Roo Code** | 22k stars | SOC 2 Type 2 | MCP, Custom Modes | None | VS Code, JetBrains |
| **SWE-agent** | 19k stars | Academic (Princeton) | None | SWE-ReX parallel | Terminal only |
| **Gemini CLI** | 12k stars | Google Cloud | MCP, Google Search | None | Terminal only |
| **Codex CLI** | New | OpenAI enterprise | None | Cloud containers | Terminal only |
| **Sympozium** | 57 stars | None (3 days old) | SkillPacks CRDs | None | TUI (Charmbracelet) |

---

### 4.2 Kagenti Sandbox Agent / Sandbox Legion (Our Current Approach)

**Branch:** `feat/sandbox-agent` in `.worktrees/sandbox-agent/` and `.worktrees/agent-examples/`

**Architecture:** LangGraph-based A2A agent deployed as a Kubernetes pod with 5-layer isolation. The most security-hardened approach in this comparison.

**Unique strengths:**
- **Skills-driven execution** — loads the same `CLAUDE.md` + `.claude/skills/` as the developer uses locally, creating a unified instruction set for both human engineers and autonomous agents
- **Per-context workspace isolation** — each conversation (context_id) gets its own `/workspace/ctx-{id}/` directory with LangGraph checkpointer for multi-turn state
- **5-layer defense-in-depth** — Kubernetes RBAC → Istio mTLS → gVisor/Kata RuntimeClass → nono Landlock → application policy (settings.json, sources.json)
- **Credential injection without storage** — AuthBridge exchanges SPIFFE SVID → scoped OAuth token on-demand; agent never sees raw credentials
- **Multi-channel HITL** — risky operations route approval to GitHub PR comments, Slack messages, Kagenti UI queue, or A2A `input_required` state
- **A2A native** — built from the ground up with A2A protocol; no wrapper needed

**What's implemented (47/48 tests passing):**
- Pod lifecycle CRDs (Sandbox, SandboxTemplate, SandboxClaim) via kubernetes-sigs/agent-sandbox
- Kernel sandbox (nono Landlock filesystem restrictions)
- Network filtering (Squid proxy domain allowlist)
- Git workspace sync (RepoManager with sources.json policy)
- Skills loading (SkillsLoader → system prompt)
- Multi-LLM via litellm
- OTEL observability scaffolding
- HITL and trigger scaffolding

**Known limitations:**
- gVisor + SELinux incompatibility (workaround deferred)
- Locked to LangGraph framework (not framework-neutral yet)
- Pending PR review comments on agent-examples PR #126 (4 security fixes)

**Kagenti deployment fitness:** Already native — this IS the current approach.

---

### 4.3 Claude Agent SDK

**What it is:** Anthropic's programmable building block — the same agentic loop that powers Claude Code, exposed as a Python/TypeScript library.

**Architecture:** Simple `query()` function that sends conversation to Anthropic Messages API, streams responses, executes tool calls (Read, Write, Edit, Bash, Glob, Grep, WebSearch), loops until done. Hooks system provides lifecycle callbacks.

**Unique strengths:**
- **Exact Claude Code capabilities** — same tools, same agentic loop, same quality
- **Hooks for policy enforcement** — PreToolUse can block actions (exit code 2), PostToolUse for audit logging
- **MCP integration native** — connect to external MCP servers for additional tools
- **Subagents** — define specialized agents via `AgentDefinition`, spawned via Task tool
- **Session management** — resume, fork, structured outputs with validated JSON
- **Multi-provider** — Anthropic API, Bedrock, Vertex AI, Azure AI Foundry

**Limitations:**
- **Proprietary** (Anthropic Commercial Terms)
- **Claude models only** — no Ollama, no open-weight models
- Requires `bypassPermissions` for headless operation
- No community governance

**A2A wrappability:** Easy (~200 lines). Follow existing `SandboxAgentExecutor` pattern, delegate `execute()` to `query()`.

**Kagenti deployment fitness:** High. Minimal glue code. All Kagenti infrastructure (AuthBridge, Squid, agent-sandbox CRDs) works unchanged. Best path for "Claude Code on Kagenti."

---

### 4.4 OpenHands (formerly OpenDevin)

**GitHub:** [github.com/OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | **Stars:** 68k | **License:** MIT | **Funding:** $18.8M

**Architecture:** Python-based platform built around an event-stream abstraction capturing actions and observations. V1 architecture provides modular SDK with `BaseWorkspace` abstraction (LocalWorkspace vs RemoteWorkspace), event-sourced state with deterministic replay, built-in REST/WebSocket server.

**Unique strengths:**
- **Docker-native sandboxing** — each session gets its own container, torn down post-session
- **REST/WebSocket API** — already headless, production-ready API
- **Rich UI capabilities** — built-in browser, VS Code IDE, VNC desktop, persistent Chromium
- **100+ LLM providers** via LiteLLM routing
- **MCP support** in V1 SDK with dedicated MCP Tools and Servers
- **Enterprise self-hosting** on Kubernetes available
- **Workspace abstraction** maps cleanly to Kagenti's per-context isolation
- **Evaluation harness** — 15+ benchmarks (SWE-bench, WebArena, GAIA)

**Limitations:**
- Heavier footprint (Docker-in-Docker or remote runtime)
- Has its own sandbox model — needs reconciliation with Kagenti's agent-sandbox CRDs
- No native A2A
- Different tool model than Claude Code (event-stream vs. tool-call loop)

**A2A wrappability:** Medium. Adapt REST API to A2A `AgentExecutor`. More complex than Agent SDK due to event-stream model.

**Kagenti deployment fitness:** High but heavier. Best open-source choice. Two integration options: (1) LocalRuntime + Kagenti pod isolation, or (2) DockerRuntime with Docker-in-Docker.

---

### 4.5 Goose (by Block)

**GitHub:** [github.com/block/goose](https://github.com/block/goose) | **Stars:** 31k | **License:** Apache 2.0

**Architecture:** Modular Rust-based architecture (`goose` core, `goose-cli`, `goose-server`, `goose-mcp`). MCP is the fundamental integration layer — connects to 3,000+ tools. The official Rust MCP SDK was based on Goose's implementation.

**Unique strengths:**
- **Rust-based** — fast, low memory, safe concurrency
- **MCP is core** — not an add-on. Every extension is an MCP server
- **Linux Foundation backing** — contributed to the Agentic AI Foundation alongside Anthropic's MCP and OpenAI's AGENTS.md
- **Multi-model configuration** — optimize cost/performance per task
- **AGENTS.md support** — native support for project-specific agent guidance
- **Container Use MCP** — Docker isolation via MCP extension

**Limitations:**
- Full headless mode not yet turnkey (active roadmap item)
- No native A2A (but under AAIF with A2A)
- Electron desktop UI focused, server mode secondary

**A2A wrappability:** Medium. Would need to bridge Rust server to Python A2A wrapper, or implement A2A in Rust.

**Kagenti deployment fitness:** Good potential, but headless gap is a blocker for now. Best candidate if/when headless mode ships.

---

### 4.6 OpenCode

**GitHub:** [github.com/sst/opencode](https://github.com/sst/opencode) | **Stars:** 100K+ (113k Feb 2026) | **License:** MIT | **Monthly devs:** 2.5M

**Current version:** v1.2.14 (Feb 25, 2026). 80 releases in Jan-Feb 2026 alone. SQLite migration for all session data in v1.2.0.

**Architecture:** TypeScript on Bun with terminal TUI. Two built-in agents ("build" for full-access, "plan" for read-only) plus subagents ("General" and "Explore"). Custom agents definable via markdown files in `.opencode/agents/`. Event-driven architecture with typed event bus. Peer-to-peer agent messaging.

**Unique strengths:**
- **Dominant open-source position** — 100K+ stars, 2.5M monthly devs, 700+ contributors, fastest growing OSS coding agent
- **Desktop app** (Tauri/Rust) for macOS, Windows, Linux + IDE extensions for VS Code, JetBrains, Zed, Cursor, Windsurf, Neovim, Emacs
- **75+ model support** through Models.dev (ChatGPT Plus, GitHub Copilot subscriptions work)
- **MCP native** with remote MCP servers, full OAuth 2.0 (PKCE + dynamic client registration), auto-detection
- **`opencode serve`** — headless HTTP server mode exposing OpenAPI endpoint for remote clients
- **ACP (Agent Client Protocol)** — standardized agent-to-editor communication (co-developed by JetBrains and Zed)
- **Custom agents via markdown** — drop a `.md` file in `.opencode/agents/`, filename becomes agent name
- **AGENTS.md support** — project-specific custom instructions (like CLAUDE.md)
- **Enterprise offering** — SSO, centralized config, internal AI gateway, per-seat pricing. Deals with defense contractors and banks
- **MIT license** — fully open, no vendor lock-in
- **OpenAI partnership** — OpenAI officially supports OpenCode, allows ChatGPT subscription logins

**Limitations:**
- **No built-in sandbox** — permission system is UX only, not a true sandbox. Community plugins: `opencode-sandbox` (bubblewrap), Docker Sandboxes
- **No A2A support** (issue #3023 stalled since Nov 2025) — would need A2A wrapper
- No official Docker image or Helm chart yet (community options: `opencode-server-docker`, `fluxbase-eu/opencode-docker` with Helm)
- CVE-2026-22812 (RCE) fixed in v1.0.216 — HTTP server auth added

**A2A wrappability:** Good. `opencode serve` provides a headless HTTP server — wrap it in an A2A server that proxies requests to the OpenCode API. Alternatively, use OpenCode as a subprocess with JSON output.

**Kagenti deployment fitness:** **High** (upgraded from Moderate). The combination of `opencode serve` headless mode, 75+ model support via existing subscriptions, mature MCP, and community Docker/Helm makes this the strongest open-source candidate after our sandbox-legion. The BYOK model aligns perfectly with Kagenti's multi-LLM philosophy.

---

### 4.7 Aider

**GitHub:** [github.com/Aider-AI/aider](https://github.com/Aider-AI/aider) | **Stars:** 41k | **License:** Apache 2.0

**Architecture:** Python CLI that creates a "repository map" (function signatures + file structures) giving the LLM codebase context. Uses tree-sitter for multi-language parsing. Git-native — every change is automatically committed.

**Unique strengths:**
- **Most mature** open-source coding agent (longest track record)
- **Git-native** — atomic commits with descriptive messages, easy rollback
- **Official Docker image** — `docker pull paulgauthier/aider`
- **84.9% on polyglot benchmarks** with o3-pro
- **Model-agnostic** — GPT-4, Claude, Gemini, DeepSeek, Ollama, any OpenAI-compatible

**Limitations:**
- No MCP support (issue #3314 remains open; community MCP servers exist)
- No A2A
- No REST API — pure CLI
- No sandbox or isolation model beyond git rollback

**A2A wrappability:** Difficult. CLI-only, no API. Would need subprocess wrapper.

**Kagenti deployment fitness:** Low-moderate. Good Docker image but hard to integrate via A2A. Better suited as a standalone tool.

---

### 4.8 SWE-agent

**GitHub:** [github.com/SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent) | **Stars:** 19k | **License:** MIT

**Architecture:** Python agent from Princeton/Stanford with a custom Agent-Computer Interface (ACI) — LM-centric commands for repo browsing, viewing, editing, and code execution. Governed by single YAML config. Designed for research (simple, hackable).

**Unique strengths:**
- **Docker-native** via SWE-ReX (sandboxed code execution engine)
- **Massively parallel execution** — designed for running hundreds of tasks
- **SWE-ReX flexibility** — supports local Docker, AWS remote, Modal, other clouds
- **Research-grade benchmarks** — SOTA on SWE-bench among open-source
- **Open-weights model** — SWE-agent-LM-32b achieves SOTA on SWE-bench

**Limitations:**
- No MCP or A2A
- Research-focused (not enterprise-ready)
- Bash-only tool interface (no rich tools like browser/Jupyter)
- No built-in API server

**A2A wrappability:** Difficult. CLI-only, batch-oriented, no server mode.

**Kagenti deployment fitness:** Low. Great for batch vulnerability scanning or bulk PR generation, but not suited for interactive A2A agent conversations.

---

### 4.9 Cline

**GitHub:** [github.com/cline/cline](https://github.com/cline/cline) | **Stars:** 58k | **License:** Apache 2.0

**Architecture:** TypeScript VS Code extension evolved into multi-platform agent. CLI 2.0 supports headless mode with `-y` flag, `--json` structured output, stdin/stdout, and tmux-based parallel execution.

**Unique strengths:**
- **5M+ installs** across VS Code, JetBrains, Cursor, Windsurf
- **Headless CLI 2.0** — genuine headless mode for CI/CD
- **ACP (Agent Client Protocol)** — `--acp` flag makes Cline an ACP-compliant agent
- **MCP native** — tool integrations
- **Cline SDK API** for programmatic access
- **SOC 2 Type 2** compliant

**Limitations:**
- Containerization still in discussion phase
- No A2A
- Permission-per-action model may be noisy in autonomous mode
- Primarily IDE-oriented architecture

**A2A wrappability:** Medium. CLI 2.0 headless mode + Cline SDK could be adapted.

**Kagenti deployment fitness:** Moderate. CLI 2.0 headless makes it viable, but containerization story is immature.

---

### 4.10 Gemini CLI

**GitHub:** [github.com/google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli) | **Stars:** 12k | **License:** Apache 2.0

**Architecture:** TypeScript terminal agent with reason-and-act loop. Built-in tools include Google Search grounding, file operations, shell commands, web fetching. Native headless mode with `--output-format json/stream-json`.

**Unique strengths:**
- **Free tier** — 60 requests/min, 1,000/day with personal Google account
- **MCP native** support
- **Full architectural transparency** — Apache 2.0, no proprietary components
- **Google Search grounding** — unique capability for research tasks

**Limitations:**
- **Locked to Gemini models** — no Claude, GPT, or open-weight models
- No A2A (despite Google creating the A2A protocol)
- No built-in containerization
- Smaller community than OpenHands/Cline/Aider

**A2A wrappability:** Easy (headless JSON mode). But locked to Gemini.

**Kagenti deployment fitness:** Low. Model lock-in defeats Kagenti's multi-LLM philosophy.

---

### 4.11 Codex CLI (OpenAI)

**GitHub:** [github.com/openai/codex](https://github.com/openai/codex) | **License:** Apache 2.0

**Architecture:** Rust CLI agent. Cloud execution uses fully isolated containers with no outbound internet and whitelisted dependencies. Supports AGENTS.md for project guidance. Uses codex-mini-latest (fine-tuned o4-mini) and GPT-5-Codex.

**Unique strengths:**
- **Strongest cloud sandbox** — no outbound internet at all
- **Rust performance** — fast, safe
- **Apache 2.0** — fully open source
- **AGENTS.md support** — shares convention with Goose

**Limitations:**
- **Locked to OpenAI models** — no Claude, Gemini, or open-weight
- No MCP, no A2A
- Cloud sandbox is OpenAI-managed (not self-hostable)

**A2A wrappability:** Easy (CLI-first, could wrap).

**Kagenti deployment fitness:** Low. Model lock-in and non-self-hostable sandbox.

---

### 4.12 Roo Code (fork of Cline)

**GitHub:** [github.com/RooCodeInc/Roo-Code](https://github.com/RooCodeInc/Roo-Code) | **Stars:** 22k | **License:** Apache 2.0

**Architecture:** VS Code extension forked from Cline with focus on reliability and customizability. Mode-level customization (Architect, Code, Debug, Ask, Custom modes) with sticky model preferences per mode. Custom Modes enable specialized AI personas with scoped tool permissions.

**Unique strengths:**
- **Custom Modes** — specialized personas (security auditor, frontend dev, etc.)
- **MCP native**
- **SOC 2 Type 2** compliant
- **JetBrains integration** available

**Limitations:**
- Primarily IDE-oriented (like Cline)
- No A2A, partial headless support
- Fork of Cline — may diverge over time

**A2A wrappability:** Similar to Cline — medium difficulty.

**Kagenti deployment fitness:** Low-moderate. Same challenges as Cline.

---

### 4.13 Sympozium

**GitHub:** [github.com/AlexsJones/sympozium](https://github.com/AlexsJones/sympozium) | **Stars:** 57 | **License:** MIT

**Architecture:** Go-based, fully Kubernetes-native. Every concept is a CRD: `SympoziumInstance`, `SympoziumSchedule`, `SympoziumPolicy`, `SympoziumSkillPack`, `SympoziumPersonaPack`. Communication via NATS JetStream. Controller, API server, IPC bridge, webhook, and agent-runner as separate container images.

**Unique strengths:**
- **Everything is a CRD** — most Kubernetes-native approach in the landscape
- **Skill Sidecars** — each skill runs in its own sidecar container with ephemeral RBAC that's auto-garbage-collected after execution. More granular than pod-level isolation
- **PersonaPacks/SkillPacks** — declarative bundles of agent configurations
- **NATS JetStream event bus** — async inter-component communication
- **Chat integrations** — Telegram, Slack, Discord, WhatsApp as separate deployment pods
- **Scheduling** — cron-based recurring tasks with concurrency policies
- **Creator credibility** — AlexsJones also created k8sgpt (thousands of stars)

**Limitations:**
- **3 days old** (Feb 23, 2026) — APIs explicitly unstable
- **No A2A/MCP** — proprietary IPC/NATS protocol only
- **No enterprise auth** — K8s RBAC only, no Keycloak/SPIRE/OAuth
- **No service mesh** — NetworkPolicy only, no Istio
- **Single framework** — can only run its own agent runtime
- **Single author** — not yet a community project

**Patterns worth borrowing:**
- Ephemeral RBAC for skills (auto-created, auto-garbage-collected)
- IPC Bridge filesystem pattern (`/ipc/*.json` + fsnotify)
- SkillPack/PersonaPack CRD design for declarative agent bundles

**A2A wrappability:** Would require significant work — NATS-based architecture is fundamentally different.

**Kagenti deployment fitness:** Not deployable as a Kagenti agent. However, its skill sidecar isolation pattern and CRD design are architecturally informative.

---

### 4.14 Deployment Fitness Ranking for Kagenti

Based on the matrices above, here is the overall ranking for deploying as a Kagenti A2A agent:

| Rank | Solution | Fitness | Rationale |
|------|----------|---------|-----------|
| 1 | **Kagenti Sandbox Agent** | Already native | Current approach, A2A built-in, 5-layer security |
| 2 | **OpenCode** | **High** | `opencode serve` headless, 100K+ stars, 75+ LLMs, MCP+OAuth, community Docker/Helm, MIT. **Deploy next.** |
| 3 | **Claude Agent SDK** | High | ~200-line A2A wrapper, exact Claude Code capabilities, hooks for OTEL |
| 4 | **OpenHands** | High (heavier) | REST API, Docker sandbox, MIT, 100+ LLMs, but needs runtime reconciliation |
| 5 | **Goose** | Good | MCP-native, Rust, Linux Foundation — **headless mode now shipped!** |
| 6 | **Gemini CLI** | Moderate (upgraded) | **A2A support actively landing** — first coding agent with native A2A |
| 7 | **Cline CLI** | Moderate | Headless CLI 2.0, MCP, ACP — containerization improving |
| 8 | **Aider** | Low-moderate | Docker image exists, mature — but no API, no MCP, hard to wrap |
| 9 | **SWE-agent** | Low | Docker-native but batch-oriented, no server mode |
| 10 | **Codex CLI** | Low | Model lock-in (OpenAI only), Rust rewrite in alpha |
| 11 | **Sympozium** | Informational | Not an agent to deploy; learn from its patterns |

---

## 5. Agent UIs, API Models, and Management Concepts

This section surveys the UI and API approaches across all coding agent solutions, analyzes common patterns, and identifies the best combination for Kagenti's evolution.

### 5.1 UI Landscape by Solution

#### OpenHands — Multi-Panel Web Workspace

**UI Type:** Browser-based React SPA at `http://localhost:3000`
**API:** REST (FastAPI) + WebSocket (Socket.IO) for real-time event streaming

| Panel | Purpose |
|-------|---------|
| Chat (left, ~50% width) | User enters requirements; agent explains steps |
| Code Editor (top right) | Browser-based VS Code (Monaco) for viewing/editing files |
| Terminal (IDE tabs) | Interactive shell inside sandbox container |
| Browser Panel | Persistent Chromium for web tasks |
| Task Planner | Track agent progress (V1) |
| VNC Desktop | Full GUI access to sandbox environment |

**Key UX:** Devin/Jules-like experience. Multi-panel workspace with chat-driven interaction. Cloud and local modes share the same UI.

**Visual references:**
- [OpenHands README](https://github.com/OpenHands/OpenHands/blob/main/README.md)
- [OpenHands Frontend README](https://github.com/OpenHands/OpenHands/blob/main/frontend/README.md)
- [Rheinwerk: What Is OpenHands?](https://blog.rheinwerk-computing.com/what-is-openhands)

---

#### Claude Code Desktop — Electron App with Diff Review

**UI Type:** Standalone Electron desktop application
**API:** Anthropic proprietary API, internally spawns Claude Code CLI engine

| Feature | Description |
|---------|------------|
| Session sidebar (left) | Filter by Active/Archived, Local/Cloud/SSH |
| Prompt area (bottom) | @-mention autocomplete, file attachment, slash commands |
| Diff view (right panel) | File-by-file diff with inline commenting (click any line) |
| Live app preview | Embedded browser renders running dev server; Claude uses vision |
| CI status bar | PR monitoring with auto-fix and auto-merge toggles |
| Mode selector | Ask permissions / Auto accept / Plan mode / Bypass |

**Key UX:** Visual diff review with inline comments before PR creation. Auto-verify takes screenshots after every edit. Parallel sessions get their own git worktrees.

**Visual references:**
- [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- [Coding Beauty: Desktop Upgrade](https://codingbeautydev.com/blog/new-claude-code-desktop-upgrade-preview-review-merge/)
- [Simon Willison: Hands-on](https://simonwillison.net/2026/Feb/16/rodney-claude-code/)

**Third-party desktop GUIs:**
- [CodePilot](https://github.com/op7418/CodePilot) — Native Electron + Next.js GUI
- [Claudia GUI](https://claudia.so/) — Open-source with visual project management
- [Pilos Agents](https://dev.to/pilosdotnet/i-built-a-visual-desktop-app-for-claude-code-heres-what-i-learned-47be) — Multi-agent teams (PM, Architect, Developer, Designer)

---

#### Claude Code on the Web — Cloud Task Runner

**UI Type:** Web app at [claude.ai/code](https://claude.ai/code)
**API:** Anthropic API, GitHub CLI via secure proxy

| Feature | Description |
|---------|------------|
| Task submission | Select repo, environment, model; type task |
| Chat/steering | Interact during execution, provide feedback |
| Diff view | File list + changes; click lines to comment |
| Session list | All active/completed sessions |
| PR creation | Create PRs directly after reviewing diffs |
| Teleport | Pull web sessions to terminal (`/teleport`) |

**Key UX:** Ephemeral, task-oriented cloud sandbox. Not a persistent dev environment (unlike Codespaces). Parallel tasks via `--remote`. Mobile monitoring via iOS/Android app.

**Visual references:**
- [Claude Code on the web docs](https://code.claude.com/docs/en/claude-code-on-the-web)
- [LavX News: Web UI Analysis](https://news.lavx.hu/article/claude-code-web-ui-a-developer-friendly-interface-for-ai-agent-interactions)

---

#### Cursor — AI-First IDE

**UI Type:** Full VS Code fork with AI-native features
**API:** Cursor proprietary API wrapping multiple LLM providers

| Feature | Description |
|---------|------------|
| Agent panel (Composer) | Multi-file change interface with visual diffs |
| Mission Control | Grid view for managing multiple agent workflows simultaneously |
| Visual Editor | Drag-and-drop elements, visual sliders, "point and prompt" |
| Embedded browser | Agents launch Chromium, interact, capture screenshots |
| Cloud agents | Run in isolated VMs, produce merge-ready PRs |

**Key UX:** Cursor 2.0 is agent-centric. Mission Control provides macOS Expose-like grid for monitoring multiple agents. Remote desktop control lets you interact with agent's VM.

**Visual references:**
- [Cursor features](https://cursor.com/features)
- [Prismic: Cursor AI Review 2026](https://prismic.io/blog/cursor-ai)

---

#### Cline — VS Code Sidebar Agent

**UI Type:** VS Code sidebar extension (right side recommended)
**API:** Direct LLM API calls to chosen provider, VS Code extension API

| Feature | Description |
|---------|------------|
| Chat panel (sidebar) | Conversational interface for prompts and responses |
| Plan/Act toggle | Tab key switches between thinking and doing |
| Execution timeline | Colored bars showing progress during Act mode |
| Token/cost tracking | Real-time stats (tokens, cache, context window) |
| Timeline view | Every change with checkpoints for rollback |
| Browser automation | Headless Chromium for testing with screenshots |

**Key UX:** Plan mode analyzes without modifying; Act mode implements. YOLO mode for autonomous execution. 5M+ installs.

**Visual references:**
- [Cline official site](https://cline.bot/)
- [DataCamp: Cline guide](https://www.datacamp.com/tutorial/cline-ai)
- [Cline CLI 2.0 blog](https://cline.bot/blog/introducing-cline-cli-2-0)

---

#### Roo Code — Custom Modes Agent

**UI Type:** VS Code sidebar extension (forked from Cline)
**API:** Any LLM provider, VS Code extension API, MCP

| Feature | Description |
|---------|------------|
| Chat sidebar | Conversational interface |
| Mode menu | Below chatbox, shows current mode with settings |
| Custom Modes UI | Create specialized AI personas with scoped tool permissions |
| Mode Marketplace | Community-contributed modes installable with one click |

**Key UX:** Custom Modes define specialized personas (Security Reviewer, Test Writer, Architect). Sticky model preferences per mode. Export/import as YAML. 171+ community agents.

**Visual references:**
- [Custom Modes docs](https://docs.roocode.com/features/custom-modes)
- [This Dot Labs: Roo Custom Modes](https://www.thisdot.co/blog/roo-custom-modes)

---

#### Goose — IDE-Agnostic Desktop + CLI

**UI Type:** Electron desktop app + CLI, IDE-agnostic
**API:** MCP for tools, 25+ LLM provider APIs, local-first

| Feature | Description |
|---------|------------|
| Desktop app | Single-threaded chat with message history |
| CLI | `@goose` invocation in terminal |
| Mobile app (iOS) | Connects via secure tunnel for remote interaction |
| Extensions | MCP servers for tool integrations |

**Key UX:** Runs alongside any editor. MCP-native — 3,000+ MCP servers available. Local-first, code never leaves machine. Cross-platform sessions (desktop, CLI, mobile share session pool).

**Visual references:**
- [Goose quickstart docs](https://block.github.io/goose/docs/quickstart/)
- [Marc Nuri: Goose introduction](https://blog.marcnuri.com/goose-on-machine-ai-agent-cli-introduction)

---

#### Crush (Charmbracelet) — Terminal TUI

**UI Type:** Rich terminal UI (Go, Bubble Tea framework)
**API:** LLM providers via fantasy abstraction layer, LSP, MCP, SQLite persistence

| Feature | Description |
|---------|------------|
| Rich TUI | Clean terminal interface with Charmbracelet styling (Lip Gloss) |
| Chat area | Conversational terminal interface |
| Changed files list | Tracks modified files during session |
| Model/cost tracking | Real-time cost and token display |
| Ctrl+P menu | Quick model switching, summary options |
| Progress bar | Agent busy state (on supported terminals) |

**Key UX:** Model-agnostic, switch models mid-session preserving context. LSP integration. MCP extensible. 20+ built-in tools. Mouse support.

**Visual references:**
- [Crush GitHub README](https://github.com/charmbracelet/crush)
- [Typevar: Crush article](https://typevar.dev/articles/charmbracelet/crush)

---

#### Sympozium — Kubernetes-Native TUI

**UI Type:** Go terminal TUI (Charmbracelet Bubble Tea)
**API:** NATS JetStream event bus, IPC Bridge (`/ipc/*.json` + fsnotify), REST API server

| Feature | Description |
|---------|------------|
| TUI Dashboard | Agent status, running jobs, skill executions |
| Channel integrations | Telegram, Slack, Discord, WhatsApp as deployment pods |
| kubectl integration | All CRDs manageable via kubectl |
| Scheduling | SympoziumSchedule CRD with cron |

**Key UX:** Everything is a CRD. Chat via messaging platforms. No web UI — TUI + kubectl + chat integrations.

---

#### Kagenti UI — Enterprise Agent Management Console

**UI Type:** React SPA with PatternFly (Red Hat design system)
**API:** REST (FastAPI `/api/v1/`), SSE for streaming chat, A2A protocol

| Page | Purpose |
|------|---------|
| Agent Catalog (`/agents`) | Table: Name, Status (color labels), Labels (protocol/framework), Workload type |
| Agent Detail (`/agents/:ns/:name`) | Description, labels, agent card, YAML, Shipwright build, embedded chat |
| AgentChat component | Markdown rendering, SSE streaming, A2A event display, session management |
| Import Agent (`/agents/import`) | Form: namespace, framework, Git URL, env vars, build strategy, SPIRE toggle |
| Tool Catalog/Detail/Import | Mirror agent pages for MCP tools |
| MCP Gateway | MCP server management |
| AI Gateway | LLM gateway configuration |
| Observability | Phoenix trace monitoring |

**Key UX:** Enterprise dashboard with namespace-scoped views. Protocol-aware labels (A2A/MCP). Build pipeline visibility (Shipwright). Streaming chat with A2A event display.

---

### 5.2 API Model Comparison

| Solution | Primary API | Real-time | Auth Model | Programmatic Access |
|----------|------------|-----------|------------|-------------------|
| **OpenHands** | REST + WebSocket (Socket.IO) | WebSocket events | API key | V1 SDK (Python) |
| **Claude Code Desktop** | Anthropic API | SSE streaming | Anthropic API key | Agent SDK (Python/TS) |
| **Claude Code Web** | Anthropic API | SSE streaming | OAuth (GitHub) | `--remote` CLI flag |
| **Cursor** | Proprietary | WebSocket | Subscription | None (closed) |
| **Cline** | Direct LLM APIs | VS Code extension | API keys per provider | Cline SDK |
| **Roo Code** | Direct LLM APIs | VS Code extension | API keys per provider | None |
| **Goose** | MCP + LLM APIs | MCP events | Local (no auth) | CLI scripting |
| **Crush** | LLM APIs (fantasy) | Terminal events | API keys | CLI flags |
| **Sympozium** | NATS JetStream + REST | NATS pub/sub | K8s RBAC | kubectl + CRDs |
| **Kagenti** | REST + SSE + A2A | SSE streaming | Keycloak OIDC | REST API + A2A protocol |

### 5.3 UX Pattern Analysis

#### Patterns That Appear Everywhere

| Pattern | Prevalence | Best Implementation |
|---------|-----------|-------------------|
| Chat-based interaction | All 10 solutions | OpenHands (multi-panel), Claude Code (inline diffs) |
| Model switching | 8 of 10 | Crush (mid-session switch preserving context) |
| MCP extensibility | 7 of 10 | Goose (core architecture), Claude Code (9k+ plugins) |
| Plan/Act mode | 5 of 10 | Cline (cleanest toggle), Claude Code (Plan mode) |
| Diff view for review | 4 of 10 | Claude Code Desktop (inline commenting + auto-review) |
| Token/cost tracking | 4 of 10 | Cline (real-time per-session) |
| Browser automation | 4 of 10 | Claude Code (auto-verify screenshots) |
| Parallel sessions | 3 of 10 | Cursor Mission Control (grid view) |
| Custom agent modes | 2 of 10 | Roo Code (YAML export, marketplace) |

#### What's Missing Across the Landscape

1. **Unified multi-agent dashboard** — No tool manages heterogeneous agent frameworks from a single control plane (except Kagenti)
2. **Agent observability standards** — No standardized tracing across agent chains
3. **Cost governance at scale** — Per-session costs exist but no org-level quotas/chargeback
4. **Agent lifecycle management** — Deploy, scale, update, rollback agents as K8s workloads (only Kagenti)
5. **Identity and security layer** — SPIRE workload identity, mTLS, OAuth across agents (only Kagenti)
6. **Protocol-level interoperability** — A2A + MCP as first-class routing (only Kagenti)
7. **Build pipeline visibility** — Source-to-container builds for agents (only Kagenti with Shipwright)
8. **Agent topology visualization** — Show which agents call which agents, MCP tool dependencies, data flows

### 5.4 Best Combination for Kagenti UI Evolution

Based on this analysis, the ideal Kagenti UI combines the best patterns from each solution:

| Capability | Inspiration Source | Implementation |
|-----------|-------------------|----------------|
| **Agent Fleet Dashboard** | Cursor Mission Control | Grid/card view of all agents with health, cost, activity sparklines |
| **Multi-Panel Agent Workspace** | OpenHands | Chat + terminal + log viewer + diff view per agent |
| **Visual Diff Review** | Claude Code Desktop | Inline diff with commenting before PR creation |
| **Plan/Act Governance** | Cline | Org-level policies for agent autonomy (plan-only for prod, full for sandboxes) |
| **Custom Agent Modes** | Roo Code | Define personas with scoped permissions as YAML, marketplace sharing |
| **Session Orchestration** | Claude Code Web | Launch parallel tasks, monitor all from one view, teleport between environments |
| **Cost Tracking** | Cline + Crush | Per-agent, per-team, per-model cost dashboards with budgets and alerts |
| **Agent Topology View** | New (Kagenti-unique) | Visualize A2A relationships, MCP tool dependencies, data flow paths |
| **Inline Observability** | Kagenti + Phoenix | Embed trace views directly in agent detail page, not separate page |
| **Multi-Environment** | Claude Code Desktop | Local/cloud/SSH environment selector from same UI |

**Phase 1 (Quick wins):**
- Add agent health cards to the catalog page (replace plain table)
- Add Plan/Act mode toggle to AgentChat component
- Add per-session token/cost display in chat

**Phase 2 (Medium effort):**
- Add diff view panel for coding agents that produce code changes
- Add session orchestration — launch multiple tasks, monitor all
- Add Custom Modes/Personas with YAML export

**Phase 3 (Larger effort):**
- Agent Fleet Dashboard (Mission Control-style grid)
- Agent Topology View (A2A + MCP dependency graph)
- Inline observability with Phoenix trace embedding
- Multi-environment support (local/cloud/cluster selector)

---

## 6. MCP vs A2A: Protocols in Depth

### 6.1 Protocol Comparison

| Aspect | MCP (Model Context Protocol) | A2A (Agent-to-Agent) |
|--------|-----|-----|
| **Created by** | Anthropic (Nov 2024) | Google (Apr 2025) |
| **Focus** | Agent-to-tool (vertical) | Agent-to-agent (horizontal) |
| **Governance** | AAIF (Linux Foundation) | LF AI & Data (Linux Foundation) |
| **Transport** | JSON-RPC 2.0 (stdio, HTTP+SSE) | JSON-RPC over HTTP |
| **Discovery** | Client config (manual) | Agent Cards (`/.well-known/agent.json`) |
| **State** | Primarily stateless tool calls | Stateful task lifecycle |
| **Auth** | OAuth 2.1 with PKCE (2025-11-25 spec) | OpenAPI-like auth schema (v0.2) |
| **Long-running** | Not designed for | Yes (task states, push notifications) |
| **Best for** | Single agent accessing tools/data | Multi-agent collaboration |

### 6.2 The Auto Repair Shop Analogy (from A2A spec)

- **A2A** = how the Shop Manager talks to mechanics (agent-to-agent collaboration)
- **MCP** = how each mechanic uses diagnostic tools and repair manuals (agent-to-tool access)

They operate at different layers. An agent uses A2A to collaborate with peers and MCP to access its tools.

### 6.3 MCP Sampling with Tools (SEP-1577, Nov 2025)

The MCP 2025-11-25 spec added **Sampling with Tools**, allowing MCP servers to run their own agentic loops:

1. Server sends `sampling/createMessage` with prompt + tool definitions
2. Client invokes LLM with those tools
3. LLM responds with `stopReason: "toolUse"` — server executes tools
4. Server sends new sampling request with tool results
5. Loop continues until `stopReason: "endTurn"`

This creates an **"Inverted Agent"** pattern (coined by FastMCP creator Jared Lowin) — the server holds the workflow logic and tools, the client provides LLM intelligence. "Write Once, Run Anywhere" for AI agents.

**Does this blur the MCP/A2A line?** Yes, significantly. MCP servers can now reason autonomously. But A2A still handles discovery, multi-agent collaboration, and long-running task lifecycle — concerns that MCP sampling doesn't address.

### 6.4 Industry Convergence

- **ACP (IBM) merged into A2A** (August 2025) — same layer, redundant
- **MCP and A2A will NOT merge** — different layers, complementary
- **W3C AI Agent Protocol Community Group** working on web standards (2026-2027)
- MCP v2.0 expected March 2026, A2A v1.0-rc in progress
- All major players (Google, Microsoft, Anthropic, OpenAI, AWS) agree on complementary framing

---

## 7. Dual-Protocol Patterns (MCP + A2A)

### 7.1 Can One Agent Serve Both?

**Yes.** Multiple reference implementations exist. This is directly relevant to Kagenti — an agent could expose tools via MCP (for Claude Desktop/Code users) while being discoverable and callable via A2A (for other Kagenti agents).

### 7.2 Architecture Pattern

![Dual-Protocol Agent: MCP + A2A](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti-platform/08-coding-agent-variants/04-dual-protocol-pattern.gif)

<details><summary>Diagram source: 04-dual-protocol-pattern</summary>

**File:** `articles/202602071828-kagenti-platform/08-coding-agent-variants/diagrams/04-dual-protocol-pattern.svg`

Shows how one agent serves both MCP and A2A protocols. Top: three MCP clients (Claude Desktop, Claude Code, Cursor) connecting via dashed lines to MCP (port 8000) label. Middle: Agent Runtime box containing Agent Logic (LangGraph/ADK/Agent SDK/custom), MCP Tools (internal), and A2A Server (port 5000). A2A output flows down to "Other Kagenti Agents". Two protocol paths visualized: purple (MCP from top) and blue (A2A from bottom). Animated: flow dots on both protocol paths. Style: purple for MCP, indigo/blue for A2A, light background, arrow markers on connecting lines.
</details>

### 7.3 Implementation Options

**Option A: python-a2a library** — cleanest dual-protocol pattern:

```python
# MCP tool server (port 8000)
from python_a2a.mcp import FastMCP
calculator = FastMCP(name="Calculator MCP")

@calculator.tool()
def add(a: float, b: float) -> float:
    return a + b

# A2A agent wrapping MCP tools (port 5000)
from python_a2a.mcp import MCPAgent
agent = MCPAgent(
    name="Math Assistant",
    mcp_server_url="http://localhost:8000"
)
```

**Option B: Google ADK** — only framework with native support for both protocols:

```python
# ADK agent uses MCP for tools, exposes via A2A
from google.adk import Agent
from google.adk.tools.mcp import MCPToolset

agent = Agent(
    name="coding-agent",
    tools=[MCPToolset(server_url="http://mcp-server:8000")],
)
# ADK's A2A adapter exposes this as an A2A agent
```

**Option C: A2A-MCP Bridge servers** — existing bridge implementations:

| Bridge | Stars | Approach |
|--------|-------|----------|
| GongRzhe/A2A-MCP-Server | 137 | MCP server → A2A client (pip install) |
| regismesquita/MCP_A2A | 21 | Lightweight dev bridge (npx) |
| vishalmysore/a2a-mcp-with-security | - | Spring Boot dual-protocol + RBAC |

### 7.4 Relevance to Kagenti

Kagenti already has both protocols partially in place:

**A2A:** All Kagenti agents expose `/.well-known/agent-card.json` and speak A2A natively. This is the primary agent-to-agent communication layer.

**MCP Gateway:** Kagenti has an **existing MCP gateway** (`charts/kagenti/templates/mcp-gateway.yaml`) with Istio Gateway + HTTPRoute configuration, an Envoy-based broker-router in `mcp-system` namespace, and an MCP Inspector deployment. **However, it is not end-to-end tested** — known issues include EnvoyFilter namespace isolation on OpenShift, broker connectivity failures, and hostname resolution problems. Tool aggregation, prefixing, and OAuth-protected resource discovery remain untested.

**Current MCP tool access works** via direct Toolhive proxy services (e.g., `mcp-weather-tool-proxy`), bypassing the gateway. This is the tested path.

**Making agents dual-protocol (A2A + MCP)** would allow:
- Claude Desktop/Code users to connect directly to Kagenti agents as MCP tools (via the gateway once fixed)
- Kagenti agents to consume external MCP servers (databases, APIs, browser automation)
- Dual-protocol agents that serve both enterprise (A2A) and developer (MCP) workflows

---

## 8. Architecture Proposals

### Proposal A: Claude Agent SDK + A2A Wrapper (Proprietary Path)

**Goal:** Deploy a Claude Code-equivalent agent as an A2A service on Kagenti.

![Claude Agent SDK on Kagenti](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti-platform/08-coding-agent-variants/02-claude-agent-sdk-pod.gif)

<details><summary>Diagram source: 02-claude-agent-sdk-pod</summary>

**File:** `articles/202602071828-kagenti-platform/08-coding-agent-variants/diagrams/02-claude-agent-sdk-pod.svg`

Kubernetes pod for Claude Agent SDK integration. Shows Init container (git clone, repo sync, CLAUDE.md + skills), main Agent Container with nested A2A Server (FastAPI, `/.well-known/agent.json`) feeding into Claude Agent SDK box (query() agentic loop, built-in tools Read/Edit/Bash/Glob/Grep, Hooks PreToolUse/PostToolUse + MCP client), Squid Proxy sidecar (anthropic.com, github.com, pypi.org). Green badge: "~200 lines A2A wrapper". Bottom bar: AuthBridge (SPIFFE), Istio Ambient (mTLS), agent-sandbox CRDs. Animated: pulse on A2A server, flow dot init to agent. Style: purple/violet theme for Claude/Anthropic branding, light background.
</details>

**A2A wrapper** (~200 lines, follows existing pattern):

```python
from a2a.server.agent_execution import AgentExecutor
from claude_agent_sdk import query, ClaudeAgentOptions

class ClaudeAgentA2AExecutor(AgentExecutor):
    async def execute(self, context, event_queue):
        prompt = extract_prompt(context)
        options = ClaudeAgentOptions(
            allowed_tools=["Read", "Edit", "Bash", "Glob", "Grep"],
            system_prompt=self.skills_loader.get_system_prompt(),
        )
        async for message in query(prompt=prompt, options=options):
            artifact = to_a2a_artifact(message)
            await event_queue.enqueue(artifact)
```

**Integration with Kagenti infrastructure:**

| Component | How it integrates |
|-----------|------------------|
| AuthBridge | Unchanged — pod-level SPIFFE identity |
| Squid proxy | Unchanged — domain allowlist sidecar |
| SkillsLoader | Unchanged — loads CLAUDE.md + skills → system prompt |
| WorkspaceManager | Unchanged — per-context workspace dirs |
| kubernetes-sigs/agent-sandbox | Unchanged — SandboxTemplate/SandboxClaim CRDs |
| OTEL | Agent SDK hooks → PreToolUse/PostToolUse for span creation |
| MCP | Native — Agent SDK can connect to external MCP servers |

**Pros:**
- Exact Claude Code capabilities (same agentic loop, same tools)
- Minimal glue code — Agent SDK does the heavy lifting
- MCP integration is native
- Hooks for observability, auth, and policy enforcement
- Existing sandbox infrastructure works unchanged

**Cons:**
- Proprietary SDK (Anthropic Commercial Terms)
- Locked to Claude models (Anthropic API, Bedrock, Vertex, Azure)
- Requires `--dangerously-skip-permissions` or `bypassPermissions` for headless
- No community governance

**Effort:** Low-medium (1-2 weeks). The A2A wrapper is small; most work is in testing and OTEL hook integration.

---

### Proposal B: OpenHands + A2A Wrapper (Open-Source Path)

**Goal:** Deploy OpenHands as an open-source coding agent with A2A interface on Kagenti.

![OpenHands Agent on Kagenti](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti-platform/08-coding-agent-variants/03-openhands-pod.gif)

<details><summary>Diagram source: 03-openhands-pod</summary>

**File:** `articles/202602071828-kagenti-platform/08-coding-agent-variants/diagrams/03-openhands-pod.svg`

Kubernetes pod for OpenHands integration. Shows Init container (git clone, repo sync), main Agent Container with three stacked layers: A2A Server (FastAPI, `/.well-known/agent.json`) -> OpenHands AgentController (event stream engine, LiteLLM 100+ models, MCP tools V1 SDK) -> Sandbox Runtime (DockerRuntime or LocalRuntime, shell/browser/Jupyter). Squid Proxy sidecar. Green badge: "MIT License | 68k stars". Bottom bar: AuthBridge (SPIFFE), Istio Ambient (mTLS), agent-sandbox CRDs. Animated: pulse on A2A server. Style: orange theme for OpenHands, light background, three-layer depth showing controller architecture.
</details>

**A2A wrapper** (adapts OpenHands REST API to A2A):

```python
from a2a.server.agent_execution import AgentExecutor
from openhands.core.config import AppConfig
from openhands.controller import AgentController

class OpenHandsA2AExecutor(AgentExecutor):
    async def execute(self, context, event_queue):
        config = AppConfig(
            workspace_dir=self.workspace_manager.ensure_workspace(context.context_id),
            sandbox=SandboxConfig(runtime_cls="local"),  # or Docker
        )
        controller = AgentController(config=config)
        async for observation in controller.run(extract_prompt(context)):
            artifact = to_a2a_artifact(observation)
            await event_queue.enqueue(artifact)
```

**Key differences from Proposal A:**

| Aspect | Claude Agent SDK | OpenHands |
|--------|-----------------|-----------|
| LLM support | Claude only (+ Bedrock/Vertex) | 100+ via LiteLLM |
| License | Proprietary | MIT |
| Sandbox | Relies on external (Kagenti infra) | Built-in Docker sandbox |
| UI capabilities | None (CLI/API only) | Browser, VS Code IDE, VNC |
| MCP | Native client | V1 SDK integration |
| Tool loop | Simple (read/edit/bash) | Rich (browser, Jupyter, shell) |

**Integration considerations:**
- OpenHands has its own Docker sandbox model — needs reconciliation with Kagenti's agent-sandbox CRDs
- Option 1: Use OpenHands' `LocalRuntime` and rely on Kagenti's pod-level isolation
- Option 2: Use OpenHands' `DockerRuntime` with Docker-in-Docker (heavier, but stronger isolation)
- AuthBridge integration requires custom event handlers to inject credentials

**Pros:**
- MIT license, model-agnostic, 68k-star community
- Most mature containerization story in the open-source landscape
- Rich capabilities (browser automation, Jupyter, VS Code)
- Could expose OpenHands' web UI through Kagenti

**Cons:**
- Heavier footprint than Agent SDK approach
- Docker-in-Docker complexity if using built-in sandbox
- No native A2A — wrapper needed
- Different tool model than Claude Code (event-stream vs. tool-call loop)

**Effort:** Medium-high (3-4 weeks). OpenHands integration is more complex due to its own runtime model.

---

### Proposal C: Multi-Framework Demo (Both + Goose)

**Goal:** Deploy multiple agent frameworks side-by-side as A2A agents, proving Kagenti's framework neutrality.

![Kagenti Multi-Framework Agent Platform](https://raw.githubusercontent.com/Ladas/blog-content/main/kagenti-platform/08-coding-agent-variants/05-multi-framework-platform.gif)

<details><summary>Diagram source: 05-multi-framework-platform</summary>

**File:** `articles/202602071828-kagenti-platform/08-coding-agent-variants/diagrams/05-multi-framework-platform.svg`

Four agent frameworks deployed side-by-side in Kagenti namespace team1. From left to right: LangGraph Agent (green, "Current approach", litellm multi-LLM, LangGraph checkpointer), Claude Agent SDK (purple, "Proprietary", Claude models only, MCP native + Hooks), OpenHands Agent (orange, "MIT | 68k stars", 100+ LLMs via LiteLLM, Docker sandbox + IDE), Goose (yellow, "Apache 2.0", MCP core arch, Rust + AAIF). Each shows `kagenti.io/framework:` label. All connect via merge line to Shared Infrastructure box containing six pills: AuthBridge (SPIFFE), Istio Ambient (mTLS), Squid proxy, agent-sandbox CRDs, Phoenix observability, Keycloak OAuth. Animated: staggered pulse rings on each agent header (0s, 0.5s, 1s, 1.5s delay). Style: each agent has its own color theme, light platform background, pill-shaped infrastructure items.
</details>

**UI Discovery:** Each agent gets a framework badge in the Kagenti UI:

```yaml
# Deployment labels
metadata:
  labels:
    kagenti.io/type: agent
    kagenti.io/protocol: a2a
    kagenti.io/framework: claude-sdk    # or: langgraph, openhands, goose
```

**Optional: Add Goose** — Rust-based, MCP-native, Linux Foundation backing. Would demonstrate a fourth framework with different characteristics (compiled language, MCP-first architecture).

**Pros:**
- Strongest proof of framework neutrality
- Covers proprietary + open-source + different languages/runtimes
- Each framework brings unique strengths (Claude tools, OpenHands browser, Goose speed)
- Users choose the best agent for their task

**Cons:**
- Highest maintenance burden (3-4 A2A wrappers)
- Goose headless mode not fully turnkey yet
- Testing matrix grows multiplicatively

**Effort:** High (6-8 weeks total). But each wrapper is independent — can be parallelized across sessions/developers.

---

## 9. Recommendation

### Phased Approach

**Phase 1 (weeks 1-2): Claude Agent SDK + A2A** (Proposal A)
- Fastest path to "Claude Code on Kagenti"
- Reuses existing A2A wrapper pattern
- Validates the "any framework behind A2A" architecture
- Demonstrates MCP integration (Agent SDK → external MCP servers)

**Phase 2 (weeks 3-5): OpenHands + A2A** (Proposal B)
- Open-source alternative with richer capabilities
- Validates model-agnostic deployment (LiteLLM, any LLM)
- Shows Docker-native sandbox alongside Kagenti's agent-sandbox CRDs

**Phase 3 (weeks 6-8): Multi-Framework Demo** (Proposal C)
- Add Goose as a third variant
- UI framework badges and discovery
- Demo script showing all three frameworks collaborating via A2A

### Key Decision: MCP Gateway E2E Testing

The MCP gateway already exists in Kagenti but is not e2e tested. Independently of which framework variants to add, **fixing and testing the MCP gateway** should be a priority — it unlocks dual-protocol capabilities for all agents automatically (Claude Desktop/Code → MCP Gateway → Kagenti agents).

### What Not to Do

- **Don't build on Claude Code CLI directly** — it's proprietary, not designed for headless K8s deployment, and the Agent SDK provides the same capabilities as a library
- **Don't adopt Sympozium's architecture** — it's 3 days old with no A2A/MCP support; learn from its skill sidecar pattern instead
- **Don't try to make every agent speak MCP natively** — use A2A as the agent-to-agent layer and MCP as the tool-access layer, as the specs intend

---

## 10. Landscape Update (March 2026)

This section captures significant changes since the initial research (Feb 26, 2026).

### 10.1 OpenCode Explosion

OpenCode has become the **dominant open-source coding agent** — 100K+ GitHub stars (vs Claude Code's 71K), 2.5M monthly developers, 700+ contributors. Key developments:

- **v1.2.14** (Feb 25): SQLite migration for all session data, adaptive reasoning for Opus 4.6/Sonnet 4.6, PartDelta events
- **Desktop app** shipped (Tauri/Rust) for macOS, Windows, Linux
- **IDE extensions** for VS Code, JetBrains, Zed, Cursor, Windsurf, Neovim, Emacs
- **`opencode serve`** headless HTTP server — the key enabler for Kagenti integration
- **Enterprise deals** with defense contractors and banks; SSO/centralized config
- **OpenAI partnership** — officially supported, ChatGPT subscriptions work through OpenCode
- Growth fueled by Anthropic OAuth controversy (Jan 9, 2026) — DHH called it "very customer hostile"

**Kagenti impact:** OpenCode moves to **#2 deployment priority** (after sandbox-legion) due to: headless server mode, 75+ LLM providers matching Kagenti's multi-LLM philosophy, MIT license, massive community, and BYOK model.

### 10.2 Goose: Headless Mode Shipped

Goose v1.26.1 (Feb 27) — **headless mode is now available** with `GOOSE_MODE=auto`, `--no-session` for one-off tasks, and `CONTEXT_STRATEGY`/`MAX_TURNS` settings. This removes the previous blocker. Goose also transitioned to community governance under AAIF (Linux Foundation).

### 10.3 Gemini CLI: A2A Landing

Gemini CLI is **actively implementing A2A support** — foundational A2A client, `@a2a` tool for model-to-agent communication, service discovery via `.well-known/agent.json`. Google published an RFC proposing to standardize all Gemini CLI integrations on A2A. This makes Gemini CLI the **first coding agent with native A2A** — significant for the multi-agent ecosystem.

### 10.4 Cursor 2.0: Cloud Agents GA

Cursor shipped Cloud Agents GA (Feb 24) — each agent runs in an isolated VM, builds software, tests it, records video demos, produces merge-ready PRs. 35% of Cursor's internal merged PRs are now created by autonomous agents. Cursor crossed $1B ARR at $29.3B valuation.

### 10.5 Cline CLI 2.0 Shipped

Full terminal rebuild (Feb 13): interactive TUI with Plan/Act toggle, auto-approve (`-y`), `--json` structured output, ACP server mode (`--acp`), parallel instances. Security incident (Feb 17): compromised npm token, no malicious code delivered.

### 10.6 kubernetes-sigs/agent-sandbox v0.2.0

New docs site, OpenTelemetry tracing, shutdown policies, NetworkPolicy support, full gVisor compatibility. Active PRs: TypeScript SDK (#300), pause/resume sandbox, stateful code execution. GKE integration docs published by Google Cloud.

### 10.7 Protocol Status

- **A2A:** Draft v1.0 spec (not final v1.0 yet). Huawei open-sourced A2A-T for telecom at MWC 2026
- **MCP:** TypeScript SDK v2 expected Q1 2026. MCP Apps shipped (tools return interactive UI). 97M monthly SDK downloads
- **ACP:** Agent Client Protocol standardizing agent-to-editor communication (Cline, OpenCode, JetBrains, Zed)

### 10.8 Industry Trends

1. **Agent users > autocomplete users** for the first time (Cursor: 2:1 ratio)
2. **Scaffold > Model** — the agent framework matters more than the LLM (15-20 point SWE-bench variance)
3. **Multi-agent mainstream** — Agent Teams (Claude), Cloud Agents (Cursor), parallel instances (Cline, Codex)
4. **Revenue scale** — Claude Code $2.5B run-rate, Cursor $1B ARR, Codex 1.5M WAU
5. **Three protocol layers converging** — MCP (tools, 97M downloads), A2A (agents, Draft v1.0), ACP (editors)
6. **Kubernetes as agent runtime** — agent-sandbox and Sympozium both maturing

### 10.9 Revised Deployment Priority

Based on these updates, the recommended deployment order for Kagenti is:

| Priority | Agent | Rationale |
|----------|-------|-----------|
| **Current** | Sandbox Legion (LangGraph) | Already built, 47/48 tests passing |
| **Next** | **OpenCode** | `opencode serve` headless, 100K+ stars, 75+ LLMs, MIT, BYOK, community Docker/Helm |
| **Then** | Claude Agent SDK | Exact Claude Code capabilities, ~200-line wrapper, proprietary but powerful |
| **Then** | OpenHands | Docker-native sandbox, REST API, MIT, richest UI capabilities |
| **Watch** | Goose | Headless shipped, MCP-native, Rust — ready when we need a compiled-language variant |
| **Watch** | Gemini CLI | First with native A2A — could enable zero-wrapper integration |

---

## 11. References

### Claude Code Stack
- [How Claude Code is Built — Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/how-claude-code-is-built)
- [Claude Agent SDK — Python](https://github.com/anthropics/claude-agent-sdk-python)
- [Claude Agent SDK — TypeScript](https://github.com/anthropics/claude-agent-sdk-typescript)
- [Claude Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Claude Code DevContainer](https://code.claude.com/docs/en/devcontainer)
- [Claude Code on the Web](https://www.anthropic.com/news/claude-code-on-the-web)
- [Claude Code Helm Chart](https://github.com/chrisbattarbee/claude-code-helm)
- [Docker Sandboxes for Claude Code](https://www.docker.com/blog/docker-sandboxes-run-claude-code-and-other-coding-agents-unsupervised-but-safely/)
- [Netclode Self-Hosted Cloud Coding Agent](https://stanislas.blog/2026/02/netclode-self-hosted-cloud-coding-agent/)
- [Claude Code Security Announcement](https://www.anthropic.com/news/claude-code-security)
- [Claude Code Security Review GitHub Action](https://github.com/anthropics/claude-code-security-review)
- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
- [Claude Code Plugins](https://code.claude.com/docs/en/plugins)
- [Claude Code Agent Teams](https://code.claude.com/docs/en/agent-teams)
- [Claude Code Remote Control](https://code.claude.com/docs/en/remote-control)
- [Claude Cowork — Blog](https://claude.com/blog/cowork-research-preview)
- [Claude Code Chrome Extension](https://code.claude.com/docs/en/chrome)
- [Claude Code Desktop App](https://code.claude.com/docs/en/desktop)
- [Anthropic Console Workspaces](https://support.claude.com/en/articles/9796807-creating-and-managing-workspaces-in-the-claude-console)
- [Claude Code Security — SOC 2 Guide](https://amitkoth.com/claude-code-soc2-compliance-auditor-guide/)

### Open-Source Agents
- [OpenHands](https://github.com/OpenHands/OpenHands) (MIT, 68k stars)
- [Cline](https://github.com/cline/cline) (Apache 2.0, 58k stars)
- [Aider](https://github.com/Aider-AI/aider) (Apache 2.0, 41k stars)
- [OpenCode](https://github.com/sst/opencode) (MIT, 36k stars)
- [Goose](https://github.com/block/goose) (Apache 2.0, 31k stars)
- [SWE-agent](https://github.com/SWE-agent/SWE-agent) (MIT, 19k stars)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Apache 2.0, 12k stars)
- [Codex CLI](https://github.com/openai/codex) (Apache 2.0)
- [Roo Code](https://github.com/RooCodeInc/Roo-Code) (Apache 2.0, 22k stars)

### Protocols
- [MCP Specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [A2A and MCP — Official A2A Docs](https://a2a-protocol.org/latest/topics/a2a-and-mcp/)
- [MCP vs A2A — Auth0](https://auth0.com/blog/mcp-vs-a2a/)
- [The Inverted Agent (MCP Sampling)](https://www.jlowin.dev/blog/the-inverted-agent)
- [SEP-1577 — MCP Sampling with Tools](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1577)

### Dual-Protocol Implementations
- [python-a2a — MCP Integration](https://github.com/themanojdesai/python-a2a/wiki/MCP-Integration)
- [A2A-MCP-Server Bridge](https://github.com/GongRzhe/A2A-MCP-Server)
- [MCP_A2A Bridge](https://github.com/regismesquita/MCP_A2A)
- [JVM Dual Protocol Server](https://github.com/vishalmysore/a2a-mcp-with-security)
- [Google ADK — A2A Integration](https://google.github.io/adk-docs/a2a/)
- [Google ADK — MCP Integration](https://google.github.io/adk-docs/mcp/)
- [Google Codelab: MCP + ADK + A2A](https://codelabs.developers.google.com/codelabs/currency-agent)

### Industry Convergence
- [Agentic AI Foundation (Linux Foundation)](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation)
- [ACP Joins A2A (IBM)](https://lfaidata.foundation/communityblog/2025/08/29/acp-joins-forces-with-a2a-under-the-linux-foundations-lf-ai-data/)
- [Microsoft: Build AI Agents with Claude Agent SDK](https://devblogs.microsoft.com/semantic-kernel/build-ai-agents-with-claude-agent-sdk-and-microsoft-agent-framework/)
- [Microsoft: Azure AI Foundry MCP + A2A](https://azure.microsoft.com/en-us/blog/agent-factory-connecting-agents-apps-and-data-with-new-open-standards-like-mcp-and-a2a/)

### Kubernetes-Native Platforms
- [Sympozium](https://github.com/AlexsJones/sympozium) (MIT, by k8sgpt creator)
- [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox)
- [kagent + Claude + k8s](https://www.cloudnativedeepdive.com/kagent-claude-k8s-your-private-agentic-troubleshooter/)

### Existing Kagenti Context
- [Sandbox Agent Research](docs/plans/2026-02-23-sandbox-agent-research.md)
- [Sandbox Agent Implementation Passover](docs/plans/2026-02-24-sandbox-agent-implementation-passover.md)
- [Sandbox Agent Latest Status](docs/plans/2026-02-25-sandbox-agent-passover.md)

### Claude Code Security Comparisons
- [Snyk: Claude Code Remediation Loop Evolution](https://snyk.io/blog/claude-code-remediation-loop-evolution/)
- [Sonar: Thoughts on Claude Code Security](https://www.sonarsource.com/blog/thoughts-on-claude-code-security/)
- [Forrester: Claude Code Security SaaS-pocalypse](https://www.forrester.com/blogs/claude-code-security-causes-a-saas-pocalypse-in-cybersecurity/)
- [2025 AI Code Security Benchmark](https://sanj.dev/post/ai-code-security-tools-comparison/)

### Agent UI and Management Interfaces
- [OpenHands Frontend README](https://github.com/OpenHands/OpenHands/blob/main/frontend/README.md)
- [Claude Code Desktop Docs](https://code.claude.com/docs/en/desktop)
- [Claude Code on the Web Docs](https://code.claude.com/docs/en/claude-code-on-the-web)
- [Cursor Features](https://cursor.com/features)
- [Cline Official Site](https://cline.bot/)
- [Cline CLI 2.0 Blog](https://cline.bot/blog/introducing-cline-cli-2-0)
- [Roo Code Custom Modes](https://docs.roocode.com/features/custom-modes)
- [Continue.dev New VS Code Interface](https://blog.continue.dev/a-fresh-coat-of-code-continues-new-vs-code-interface/)
- [Goose Quickstart Docs](https://block.github.io/goose/docs/quickstart/)
- [Crush GitHub (Charmbracelet TUI)](https://github.com/charmbracelet/crush)
- [CodePilot — Desktop GUI for Claude Code](https://github.com/op7418/CodePilot)
- [Claudia GUI](https://claudia.so/)
- [Conductor — Multi-Agent Orchestration](https://www.conductor.build/)
- [VS Code Multi-Agent Development](https://code.visualstudio.com/blogs/2026/02/05/multi-agent-development)

### Claude Code Market Context
- [Claude Opus 4.6 Launch — CNBC](https://www.cnbc.com/2026/02/05/anthropic-claude-opus-4-6-vibe-working.html)
- [Claude Code vs GitHub Copilot 2026](https://learn.ryzlabs.com/ai-coding-assistants/claude-code-vs-github-copilot-a-developer-s-decision-in-2026)
- [Claude Code COBOL Modernization](https://claude.com/blog/how-ai-helps-break-cost-barrier-cobol-modernization)
