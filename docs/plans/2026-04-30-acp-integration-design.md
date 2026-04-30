# ACP Integration Design for Kagenti

**Date**: 2026-04-30
**Status**: Draft
**Author**: Ladislav Smola

## 1. Executive Summary

This document proposes adding **Agent Client Protocol (ACP)** support to the
kagenti backend, enabling any ACP-speaking client — humr, IDE extensions
(VS Code, JetBrains, Cursor), CLI tools, or custom frontends — to interact
with kagenti-managed agents. The design uses a **hybrid protocol split**:
openshell/coding agents speak ACP, framework agents (LangGraph, CrewAI, ADK)
continue using A2A, with an optional bridge for cross-protocol access.

## 2. Problem Statement

Kagenti currently exposes agents exclusively via the **A2A (Agent-to-Agent)**
protocol — HTTP JSON-RPC with SSE streaming. This works well for autonomous
framework agents but creates friction for:

1. **Coding agents** (Claude Code, Codex, Gemini CLI) that need file system
   access, terminal operations, and human-in-the-loop permission gates — none
   of which A2A supports.

2. **Humr** (kagenti/humr), a sibling project that already uses ACP as its
   primary protocol. Humr explicitly chose ACP over A2A (ADR-004) but
   acknowledges they "must eventually reconcile both protocols."

3. **IDE extensions** and developer tools that implement ACP for coding agent
   integration — they cannot connect to kagenti today.

4. **Openshell harnesses** — the kubernetes-sigs/agent-sandbox workload type
   needs a protocol that supports workspace isolation, file operations, and
   interactive sessions.

## 3. ACP Protocol Overview

### 3.1 What is ACP?

The **Agent Client Protocol** standardizes communication between code
editors/IDEs (clients) and coding agents. It is modeled after LSP (Language
Server Protocol) — just as LSP standardized language intelligence, ACP
standardizes agentic coding interactions.

### 3.2 Core Concepts

```
┌─────────────────────────────────────────────────────────────────┐
│                     ACP Protocol Stack                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐    JSON-RPC 2.0     ┌──────────────────────┐     │
│  │  Client  │◄───────────────────►│   Agent (Server)     │     │
│  │          │                     │                      │     │
│  │  - IDE   │  Transport:         │  - Claude Code       │     │
│  │  - CLI   │  - stdio (primary)  │  - Codex             │     │
│  │  - humr  │  - WebSocket        │  - Gemini CLI        │     │
│  │  - UI    │  - HTTP (draft)     │  - Custom agents     │     │
│  └──────────┘                     └──────────────────────┘     │
│                                                                 │
│  Key Protocol Methods:                                          │
│  ────────────────────                                           │
│  initialize          Capability exchange & version negotiation  │
│  authenticate        Agent-defined authentication               │
│  session/new         Create session with cwd + MCP configs      │
│  session/prompt      Send user message, receive streaming reply  │
│  session/update      Streaming notifications (text, tool calls) │
│  session/cancel      Cancel in-progress turn                    │
│  session/close       Terminate session                          │
│  session/resume      Reconnect to existing session              │
│  session/list        Enumerate active sessions                  │
│  fs/read_text_file   Agent reads file via client                │
│  fs/write_text_file  Agent writes file via client               │
│  terminal/create     Agent runs terminal command                │
│  terminal/output     Get terminal output                        │
│  terminal/wait       Block until command exits                  │
│                                                                 │
│  Permission Model:                                              │
│  ────────────────                                               │
│  session/request_permission  →  allow_once | allow_always       │
│                                 reject_once | reject_always     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 ACP Session Lifecycle

```
Client                                    Agent
  │                                         │
  │─── initialize ─────────────────────────►│
  │    {protocolVersion: 1,                 │
  │     clientCapabilities: {fs, terminal}} │
  │◄── response ────────────────────────────│
  │    {agentCapabilities: {loadSession},   │
  │     authMethods: [{id, name, type}]}    │
  │                                         │
  │─── authenticate ───────────────────────►│
  │    {methodId: "keycloak-oidc"}          │
  │◄── response ────────────────────────────│
  │                                         │
  │─── session/new ────────────────────────►│
  │    {cwd: "/workspace",                  │
  │     mcpServers: [{name, command}]}      │
  │◄── response ────────────────────────────│
  │    {sessionId: "sess_abc123"}           │
  │                                         │
  │─── session/prompt ─────────────────────►│
  │    {sessionId: "sess_abc123",           │
  │     prompt: [{type: "text",             │
  │              text: "fix the auth bug"}]}│
  │                                         │
  │◄── session/update (notification) ───────│  ← streaming text
  │    {sessionUpdate: "agent_message_chunk"│
  │     content: [{type: "text", ...}]}     │
  │                                         │
  │◄── session/update (notification) ───────│  ← tool call
  │    {sessionUpdate: "tool_call",         │
  │     toolCallId: "call_001",             │
  │     title: "Reading auth.py",           │
  │     kind: "read", status: "pending"}    │
  │                                         │
  │◄── session/request_permission ──────────│  ← permission gate
  │    {toolCall: {...},                    │
  │     options: [allow_once, reject_once]} │
  │─── permission response ────────────────►│
  │    {outcome: "selected",                │
  │     selectedOptionId: "allow_once"}     │
  │                                         │
  │◄── session/update (notification) ───────│  ← tool result
  │    {sessionUpdate: "tool_call_update",  │
  │     status: "completed",               │
  │     content: [{type: "text", ...}]}     │
  │                                         │
  │◄── session/prompt response ─────────────│
  │    {stopReason: "end_turn"}             │
  │                                         │
  │─── session/close ──────────────────────►│
  │◄── response ────────────────────────────│
  └─────────────────────────────────────────┘
```

### 3.4 ACP Content Blocks

ACP supports rich content types in prompts and responses:

| Type            | Fields                                 | Use Case                    |
|-----------------|----------------------------------------|-----------------------------|
| `text`          | `text`, `annotations?`                 | Chat messages, code         |
| `image`         | `data` (base64), `mimeType`            | Screenshots, diagrams       |
| `resource_link` | `uri`, `name`, `mimeType?`             | File references             |
| `resource`      | `resource: {uri, text\|blob}`          | Embedded file content       |

### 3.5 ACP vs A2A Comparison

```
┌────────────────────┬─────────────────────────┬─────────────────────────┐
│     Aspect         │         ACP             │         A2A             │
├────────────────────┼─────────────────────────┼─────────────────────────┤
│ Purpose            │ IDE / client → agent    │ Agent → agent (peers)   │
│ Transport          │ stdio, WebSocket        │ HTTP REST + SSE         │
│ Message format     │ JSON-RPC 2.0            │ JSON-RPC 2.0            │
│ Discovery          │ Registry + initialize   │ /.well-known/agent-card │
│ Session model      │ Sessions with cwd, MCP  │ Tasks with messages     │
│ Auth               │ Agent-defined           │ OAuth 2.0 / OIDC        │
│ File operations    │ First-class (fs/*)      │ Not applicable          │
│ Terminal ops       │ First-class (terminal/*)│ Not applicable          │
│ Permission model   │ allow/reject once/always│ Not specified            │
│ Streaming          │ JSON-RPC notifications  │ SSE event stream        │
│ MCP integration    │ First-class             │ Not specified            │
│ Plan tracking      │ Built-in (plan entries) │ Not specified            │
│ Agent type         │ Coding agents           │ Autonomous services     │
│ Human-in-the-loop  │ Core design principle   │ Optional                │
└────────────────────┴─────────────────────────┴─────────────────────────┘
```

**Key insight**: ACP and A2A are complementary, not competing. ACP is designed
for human-operated coding agents that need workspace context. A2A is designed
for autonomous agent services that communicate as peers. Kagenti needs both.

## 4. Architecture

### 4.1 Hybrid Protocol Split + Bridge

The architecture adds ACP support alongside existing A2A, with a clean split
by agent type and an optional bridge for cross-protocol access.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL CLIENTS                                │
│                                                                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────┐    │
│  │   Humr   │   │ VS Code  │   │ JetBrains│   │  Kagenti UI      │    │
│  │ API Srvr │   │Extension │   │Extension │   │  (React)         │    │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └────────┬─────────┘    │
│       │              │              │                    │              │
│       │    ACP/WebSocket            │              A2A/SSE             │
│       │              │              │              + ACP/WS            │
└───────┼──────────────┼──────────────┼────────────────────┼──────────────┘
        │              │              │                    │
┌───────▼──────────────▼──────────────▼────────────────────▼──────────────┐
│                       KAGENTI BACKEND (FastAPI)                         │
│                                                                         │
│  ┌─────────────────────────┐    ┌──────────────────────────────────┐   │
│  │     ACP Gateway         │    │      A2A Endpoint                │   │
│  │                         │    │                                  │   │
│  │  WS /acp/ws             │    │  POST /chat/{ns}/{name}         │   │
│  │                         │    │  POST /chat/{ns}/{name}/stream  │   │
│  │  • initialize handler   │    │                                  │   │
│  │  • authenticate handler │    │  • message/send                  │   │
│  │  • session management   │    │  • message/stream                │   │
│  │  • prompt relay         │    │  • agent card discovery          │   │
│  │  • permission proxy     │    │                                  │   │
│  └────────┬────────────────┘    └──────────┬───────────────────────┘   │
│           │                                │                           │
│           │         ┌──────────────────┐   │                           │
│           │         │   ACP ↔ A2A      │   │                           │
│           ├────────►│   Bridge         │◄──┤                           │
│           │         │                  │   │                           │
│           │         │  • session → task│   │                           │
│           │         │  • prompt → msg  │   │                           │
│           │         │  • update → SSE  │   │                           │
│           │         │  • card → caps   │   │                           │
│           │         └──────────────────┘   │                           │
│           │                                │                           │
│  ┌────────▼────────────────────────────────▼───────────────────────┐   │
│  │                    Agent Router                                 │   │
│  │                                                                 │   │
│  │  Workload Type → Protocol:                                      │   │
│  │    Sandbox / SandboxClaim   →  ACP (via agent runtime sidecar)  │   │
│  │    Deployment / StatefulSet →  A2A (direct HTTP)                │   │
│  │    Job                      →  A2A (direct HTTP)                │   │
│  │                                                                 │   │
│  └─────────┬───────────────────────────────────┬───────────────────┘   │
│            │                                   │                       │
└────────────┼───────────────────────────────────┼───────────────────────┘
             │                                   │
┌────────────▼───────────────────┐   ┌───────────▼───────────────────────┐
│   OPENSHELL AGENT POD          │   │   FRAMEWORK AGENT POD             │
│   (SandboxClaim workload)      │   │   (Deployment workload)           │
│                                │   │                                   │
│  ┌──────────────────────────┐  │   │  ┌─────────────────────────────┐  │
│  │   Agent Runtime Sidecar  │  │   │  │   Agent HTTP Server         │  │
│  │                          │  │   │  │                             │  │
│  │   • WS server (←gateway) │  │   │  │   • A2A JSON-RPC endpoint  │  │
│  │   • stdio mgr (→agent)   │  │   │  │   • /.well-known/agent-card│  │
│  │   • MCP config           │  │   │  │   • SSE streaming          │  │
│  │   • file sync            │  │   │  │                             │  │
│  │   • terminal mux         │  │   │  │   (LangGraph / CrewAI /    │  │
│  │   • session persistence  │  │   │  │    ADK / custom)           │  │
│  └──────────┬───────────────┘  │   │  └─────────────────────────────┘  │
│             │ stdio            │   │                                   │
│  ┌──────────▼───────────────┐  │   │  ┌─────────────────────────────┐  │
│  │   Agent Process          │  │   │  │   AuthBridge Sidecar        │  │
│  │                          │  │   │  │   (mTLS / SPIFFE / Envoy)   │  │
│  │   Claude Code / Codex /  │  │   │  └─────────────────────────────┘  │
│  │   Gemini CLI / Custom    │  │   │                                   │
│  └──────────────────────────┘  │   └───────────────────────────────────┘
│                                │
│  ┌──────────────────────────┐  │
│  │   AuthBridge Sidecar     │  │
│  │   (mTLS / SPIFFE / Envoy)│  │
│  └──────────────────────────┘  │
│                                │
│  Volumes:                      │
│   /workspace  (PVC)            │
│   /app/.cache (emptyDir)       │
│   /shared     (emptyDir)       │
└────────────────────────────────┘
```

### 4.2 Component Details

#### 4.2.1 ACP Gateway (new FastAPI router)

The ACP Gateway is a WebSocket endpoint in the kagenti backend that speaks
ACP to external clients and routes to agent pods.

**Endpoint**: `ws://{backend}/acp/ws/{namespace}/{agent_name}`

**Responsibilities**:
- Accept WebSocket connections from ACP clients
- Handle `initialize` → return kagenti-specific capabilities
- Handle `authenticate` → validate Keycloak OIDC token
- Handle `session/new` → create session in kagenti sessions DB, connect to agent runtime
- Relay `session/prompt` → agent runtime → agent process
- Relay `session/update` ← agent runtime ← agent process
- Proxy `session/request_permission` with kagenti RBAC integration
- Handle `session/resume`, `session/list`, `session/close`

**Authentication flow**:
```
Client                    ACP Gateway                Keycloak
  │                           │                          │
  │── initialize ────────────►│                          │
  │◄── {authMethods: [{       │                          │
  │      id: "keycloak-oidc", │                          │
  │      name: "Keycloak",    │                          │
  │      type: "agent"}]} ────│                          │
  │                           │                          │
  │── authenticate ──────────►│                          │
  │   {methodId: "keycloak",  │                          │
  │    token: "<OIDC token>"} │── validate token ───────►│
  │                           │◄── token info ───────────│
  │◄── {} (success) ──────────│                          │
  │                           │                          │
  │  (session/new now uses    │                          │
  │   authenticated identity  │                          │
  │   for RBAC checks)        │                          │
  └───────────────────────────┘                          │
```

#### 4.2.2 Agent Runtime Sidecar

A lightweight container injected into openshell agent pods that bridges
WebSocket (from gateway) to stdio (to agent process).

```
┌─────────────────────────────────────────────────────────┐
│                  Agent Runtime Sidecar                   │
│                                                         │
│  ┌─────────────────┐                                    │
│  │ WebSocket Server │◄──── from ACP Gateway             │
│  │ (port 8081)      │                                   │
│  └────────┬─────────┘                                   │
│           │                                             │
│  ┌────────▼─────────┐    ┌───────────────────────────┐  │
│  │ ACP Frame Router │    │ Session Store             │  │
│  │                  │    │                           │  │
│  │ • parse JSON-RPC │    │ • in-memory session log   │  │
│  │ • route by method│    │ • 2MB soft cap per session│  │
│  │ • multiplex chans│    │ • persist to sessions DB  │  │
│  └────────┬─────────┘    └───────────────────────────┘  │
│           │                                             │
│  ┌────────▼─────────┐    ┌───────────────────────────┐  │
│  │ Process Manager  │    │ MCP Config Manager        │  │
│  │                  │    │                           │  │
│  │ • spawn AGENT_CMD│    │ • write .mcp.json         │  │
│  │ • stdin/stdout   │    │ • configure MCP servers   │  │
│  │ • health probes  │    │ • inject humr-outbound    │  │
│  │ • restart policy │    └───────────────────────────┘  │
│  └────────┬─────────┘                                   │
│           │ stdio (JSON-RPC, newline-delimited)          │
│  ┌────────▼─────────┐    ┌───────────────────────────┐  │
│  │ Terminal Mux     │    │ File Sync                 │  │
│  │                  │    │                           │  │
│  │ • terminal/create│    │ • fs/read_text_file       │  │
│  │ • terminal/output│    │ • fs/write_text_file      │  │
│  │ • terminal/wait  │    │ • workspace volume mount  │  │
│  │ • terminal/kill  │    │ • path validation         │  │
│  └──────────────────┘    └───────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Key design choice**: The agent runtime is architecturally similar to humr's
`packages/agent-runtime` but implemented in Python to align with kagenti's
backend stack. Alternatively, kagenti could vendor humr's TypeScript runtime
as-is and run it as a sidecar — this would maximize compatibility with humr's
proven ACP implementation.

#### 4.2.3 ACP-A2A Bridge

An optional translation layer that allows ACP clients to access A2A agents
and vice versa.

```
┌──────────────────────────────────────────────────────────┐
│                    ACP ↔ A2A Bridge                      │
│                                                          │
│  ACP → A2A (client wants to reach a framework agent):    │
│  ─────────────────────────────────────────────────────    │
│                                                          │
│  session/new      →  (create internal task tracking)     │
│  session/prompt    →  message/send or message/stream     │
│  session/update   ←  SSE events mapped to JSON-RPC       │
│  session/close    →  (cleanup task)                      │
│                                                          │
│  Capabilities mapped:                                    │
│  • Agent card skills    → ACP slash commands              │
│  • Agent card streaming → ACP promptCapabilities         │
│  • No fs/terminal ops   (framework agents don't need)    │
│                                                          │
│  ─────────────────────────────────────────────────────    │
│  A2A → ACP (framework agent wants to reach coding agent):│
│  ─────────────────────────────────────────────────────    │
│                                                          │
│  message/send     →  session/prompt (auto-create session)│
│  message/stream   →  session/prompt + relay updates      │
│  agent-card       ←  initialize capabilities mapped      │
│                                                          │
│  Limitations:                                            │
│  • Permission requests auto-allowed (no human in loop)   │
│  • File/terminal ops not exposed via A2A                 │
│  • Session persistence managed by bridge, not caller     │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 4.3 Data Flow: Humr → Kagenti → Agent

End-to-end flow showing how a humr user interacts with a kagenti-managed
Claude Code agent:

```
┌──────────┐    ┌──────────┐    ┌───────────┐    ┌──────────┐    ┌──────────┐
│  Humr UI │    │Humr API  │    │ Kagenti   │    │ Agent    │    │ Claude   │
│ (browser)│    │ Server   │    │ Backend   │    │ Runtime  │    │ Code     │
└────┬─────┘    └────┬─────┘    └─────┬─────┘    └────┬─────┘    └────┬─────┘
     │               │               │               │               │
     │ 1. User types │               │               │               │
     │    prompt      │               │               │               │
     ├──────────────►│               │               │               │
     │    (WS)       │               │               │               │
     │               │ 2. Relay ACP  │               │               │
     │               │    frame      │               │               │
     │               ├──────────────►│               │               │
     │               │    (WS)       │               │               │
     │               │               │ 3. RBAC check │               │
     │               │               │    + route    │               │
     │               │               ├──────────────►│               │
     │               │               │    (WS)       │               │
     │               │               │               │ 4. stdin      │
     │               │               │               │    JSON-RPC   │
     │               │               │               ├──────────────►│
     │               │               │               │               │
     │               │               │               │ 5. Agent reads│
     │               │               │               │    files, runs│
     │               │               │               │    commands   │
     │               │               │               │◄─────────────►│
     │               │               │               │  (stdio)      │
     │               │               │               │               │
     │               │               │ 6. stream     │               │
     │               │               │    updates    │               │
     │               │               │◄──────────────┤               │
     │               │ 7. relay      │               │               │
     │               │◄──────────────┤               │               │
     │ 8. render     │               │               │               │
     │◄──────────────┤               │               │               │
     │               │               │               │               │
     │               │               │ 9. permission │               │
     │               │               │    request    │               │
     │               │               │◄──────────────┤               │
     │               │ 10. relay     │               │               │
     │               │◄──────────────┤               │               │
     │ 11. user      │               │               │               │
     │     decides   │               │               │               │
     ├──────────────►│               │               │               │
     │               ├──────────────►│               │               │
     │               │               ├──────────────►│               │
     │               │               │               ├──────────────►│
     │               │               │               │               │
     │               │               │ 12. final     │               │
     │               │               │     response  │               │
     │               │               │◄──────────────┤               │
     │               │ 13. relay     │               │               │
     │               │◄──────────────┤               │               │
     │ 14. render    │               │               │               │
     │◄──────────────┤               │               │               │
     │               │               │               │               │
```

### 4.4 Data Flow: IDE → Kagenti → Agent

Direct IDE-to-kagenti flow (no humr intermediary):

```
┌──────────┐    ┌───────────┐    ┌──────────┐    ┌──────────┐
│ VS Code  │    │ Kagenti   │    │ Agent    │    │ Codex    │
│Extension │    │ Backend   │    │ Runtime  │    │          │
└────┬─────┘    └─────┬─────┘    └────┬─────┘    └────┬─────┘
     │               │               │               │
     │ 1. WS connect │               │               │
     ├──────────────►│               │               │
     │               │               │               │
     │ 2. initialize │               │               │
     ├──────────────►│               │               │
     │◄──────────────┤ capabilities  │               │
     │               │               │               │
     │ 3. authenticate                │               │
     ├──────────────►│               │               │
     │ (OIDC token)  │── Keycloak ──►│               │
     │◄──────────────┤               │               │
     │               │               │               │
     │ 4. session/new│               │               │
     │   {cwd: ".",  │               │               │
     │    mcpServers} │               │               │
     ├──────────────►│               │               │
     │               │── create pod ─►│               │
     │               │   (if needed)  │               │
     │◄──────────────┤ {sessionId}   │               │
     │               │               │               │
     │ 5. prompt     │               │               │
     ├──────────────►├──────────────►├──────────────►│
     │               │               │    stdio      │
     │  updates ◄────┤◄──────────────┤◄──────────────┤
     │               │               │               │
```

## 5. How Humr Uses ACP Today

Understanding humr's current ACP implementation is critical for designing
kagenti's ACP support to be compatible.

### 5.1 Humr's ACP Communication Chain

```
┌──────────────────────────────────────────────────────────────────┐
│                     Humr Architecture                            │
│                                                                  │
│  ┌────────┐    ┌─────────────┐    ┌──────────────┐   ┌───────┐ │
│  │ Humr   │    │ Humr API    │    │ Humr Agent   │   │Agent  │ │
│  │ UI     │◄──►│ Server      │◄──►│ Runtime      │◄─►│Process│ │
│  │(React) │ WS │(tRPC/Fastify│ WS │(TypeScript)  │ IO│       │ │
│  └────────┘    │ + WebSocket)│    │              │   │Claude │ │
│                └──────┬──────┘    └──────────────┘   │Code   │ │
│                       │                               └───────┘ │
│                       │                                         │
│              Mandatory ACP relay                                │
│              (ADR-007: all ACP traffic                           │
│               proxied through api-server)                       │
│                                                                  │
│  Key Design Decisions:                                           │
│  • ADR-004: ACP chosen over A2A                                  │
│  • ADR-006: ConfigMaps only (no CRDs)                            │
│  • ADR-007: ACP relay mandatory (no direct connections)          │
│  • ADR-012: Jobs replacing StatefulSets (in progress)            │
│                                                                  │
│  Domain Model:                                                   │
│  • Template  → catalog blueprint (image, mounts, env)            │
│  • Agent     → user-owned executable harness                     │
│  • Instance  → active/dormant deployment                         │
│  • Session   → single conversation cycle                         │
│  • Schedule  → time-triggered task (cron/RRULE)                  │
│  • Fork      → ephemeral per-turn env (Slack multi-player)       │
│  • Secret    → user-owned credential for egress injection        │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 Humr's Agent Abstraction

Each humr agent is an ACP subprocess. The single integration point is
`AGENT_COMMAND` — the runtime spawns this command and speaks ACP over stdio:

```typescript
// Humr agent-runtime (simplified)
const proc = child_process.spawn(AGENT_COMMAND, args, {
  stdio: ["pipe", "pipe", "inherit"],  // stdin, stdout, stderr
  cwd: workspaceDir,
  env: { ...process.env, ...agentEnv }
});

// JSON-RPC frames over stdin/stdout (newline-delimited)
proc.stdout.on("data", (chunk) => parseJsonRpcFrame(chunk));
proc.stdin.write(JSON.stringify(request) + "\n");
```

### 5.3 What Kagenti's ACP Must Be Compatible With

For humr to use kagenti as a backend, kagenti's ACP gateway must:

1. **Accept WebSocket connections** — humr's api-server connects via WS
2. **Support the full ACP lifecycle** — initialize, authenticate, session/*
3. **Relay JSON-RPC frames transparently** — humr expects raw ACP frames
4. **Handle multi-channel fan-out** — multiple WS connections per session
5. **Provide session persistence** — humr expects sessions to survive reconnects

## 6. Integration with Existing Kagenti Components

### 6.1 Feature Flag

```python
# kagenti/backend/app/core/config.py
kagenti_feature_flag_acp: bool = False  # ACP gateway endpoint
```

### 6.2 Sessions Database

ACP sessions map to kagenti's existing sessions table:

```
┌──────────────────────────────────────────────────────────────┐
│                    sessions (PostgreSQL)                      │
├──────────────────────────────────────────────────────────────┤
│  context_id      │  ← maps to ACP sessionId                 │
│  agent_name      │  ← agent receiving the session            │
│  namespace       │  ← K8s namespace                          │
│  title           │  ← derived from first prompt              │
│  owner           │  ← authenticated user (from OIDC token)   │
│  protocol        │  ← NEW: "acp" | "a2a"                    │
│  session_state   │  ← NEW: ACP session state blob            │
│  updated_at      │  ← last activity timestamp                │
│  model_override  │  ← LLM model selection                    │
│  budget_limit    │  ← token budget                           │
└──────────────────────────────────────────────────────────────┘
```

### 6.3 RBAC Integration

ACP permission requests are layered with kagenti's existing RBAC:

```
ACP Permission Request Flow:
────────────────────────────

  Agent Process                Kagenti Backend              Client
       │                            │                         │
       │── request_permission ──────►│                         │
       │   {toolCall: "rm -rf /"}   │                         │
       │                            │                         │
       │                     ┌──────▼──────────┐              │
       │                     │ RBAC Pre-check   │              │
       │                     │                  │              │
       │                     │ User has         │              │
       │                     │ namespace access?│              │
       │                     │ Agent policy     │              │
       │                     │ allows tool kind?│              │
       │                     └──────┬───────────┘              │
       │                            │                         │
       │                     [RBAC allows]                    │
       │                            │                         │
       │                            │── request_permission ──►│
       │                            │   (forwarded to client) │
       │                            │                         │
       │                            │◄── user decision ───────│
       │                            │   {allow_once}          │
       │                            │                         │
       │◄── permission granted ─────│                         │
       │                            │                         │
```

### 6.4 Agent Discovery

ACP agents are discovered through kagenti's existing agent registry, with
ACP-specific metadata:

```yaml
# Agent manifest (extended)
apiVersion: kagenti.dev/v1alpha1
kind: Agent
metadata:
  name: claude-code-agent
  namespace: team1
  labels:
    kagenti.dev/protocol: acp           # NEW: protocol indicator
    kagenti.dev/workload-type: sandbox
spec:
  workloadType: Sandbox
  image: ghcr.io/kagenti/claude-code-agent:latest
  acp:                                   # NEW: ACP-specific config
    agentCommand: "claude"               # AGENT_COMMAND for runtime
    capabilities:
      loadSession: true
      promptCapabilities:
        image: true
      mcpCapabilities:
        http: true
    authMethods:
      - id: keycloak-oidc
        name: Keycloak OIDC
        type: agent
```

## 7. Deployment Topology

### 7.1 Kind Cluster (Local Development)

```
┌──────────────────────────────────────────────────────────────┐
│                     Kind Cluster                              │
│                                                              │
│  kagenti-system namespace                                    │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  kagenti-backend (Deployment)                          │  │
│  │    • /chat/* endpoints (A2A)                           │  │
│  │    • /acp/ws/* endpoint (ACP) ← NEW                    │  │
│  │    • /api/* endpoints (REST)                           │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │  kagenti-ui (Deployment)                               │  │
│  │  postgres-sessions (StatefulSet)                        │  │
│  │  litellm-proxy (Deployment)                            │  │
│  │  keycloak (StatefulSet)                                │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  team1 namespace                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                                                        │  │
│  │  claude-code-agent (SandboxClaim)  ← ACP agent         │  │
│  │    ├── agent-runtime (sidecar, port 8081)              │  │
│  │    ├── claude-code (main, stdio)                       │  │
│  │    └── authbridge (sidecar)                            │  │
│  │                                                        │  │
│  │  weather-agent (Deployment)        ← A2A agent         │  │
│  │    ├── weather-server (main, port 8080)                │  │
│  │    └── authbridge (sidecar)                            │  │
│  │                                                        │  │
│  │  adk-agent (Deployment)            ← A2A agent         │  │
│  │    ├── adk-server (main, port 8080)                    │  │
│  │    └── authbridge (sidecar)                            │  │
│  │                                                        │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  openshell-system namespace                                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  agent-sandbox-controller                              │  │
│  │  openshell-gateway                                     │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 7.2 External Access

```
┌──────────────────────────────────────────────────────┐
│  External Clients                                    │
│                                                      │
│  Humr ───► wss://kagenti.example.com/acp/ws/team1/   │
│            claude-code-agent                         │
│                                                      │
│  IDE  ───► wss://kagenti.example.com/acp/ws/team1/   │
│            codex-agent                               │
│                                                      │
│  UI   ───► https://kagenti.example.com/chat/team1/   │
│            weather-agent/stream                      │
│                                                      │
│  Ingress / Istio Gateway:                            │
│    /acp/ws/*  →  kagenti-backend (WebSocket upgrade) │
│    /chat/*    →  kagenti-backend (HTTP + SSE)         │
│    /api/*     →  kagenti-backend (HTTP)               │
│                                                      │
└──────────────────────────────────────────────────────┘
```

## 8. Protocol Translation (ACP ↔ A2A Bridge)

### 8.1 Mapping Table

```
┌─────────────────────────┬──────────────────────────────────────┐
│      ACP Method         │           A2A Equivalent             │
├─────────────────────────┼──────────────────────────────────────┤
│ initialize              │ GET /.well-known/agent-card.json     │
│ authenticate            │ OAuth 2.0 Bearer token               │
│ session/new             │ (internal: create task context)       │
│ session/prompt          │ POST / {method: "message/send"}      │
│ session/prompt (stream) │ POST /stream {method: "message/stream│
│ session/update          │ SSE event (text/event-stream)         │
│   agent_message_chunk   │   data: {type: "text", text: "..."}  │
│   tool_call             │   (no A2A equivalent)                │
│   tool_call_update      │   (no A2A equivalent)                │
│   plan                  │   (no A2A equivalent)                │
│ session/cancel          │ (no A2A equivalent)                   │
│ session/close           │ (close SSE connection)                │
│ request_permission      │ (no A2A equivalent — auto-allow)     │
│ fs/read_text_file       │ (not applicable)                     │
│ fs/write_text_file      │ (not applicable)                     │
│ terminal/*              │ (not applicable)                     │
│                         │                                      │
│ ACP content blocks:     │ A2A parts:                           │
│   text                  │   TextPart                           │
│   image                 │   FilePart (inline data)             │
│   resource_link         │   FilePart (URI reference)           │
│   resource              │   DataPart                           │
└─────────────────────────┴──────────────────────────────────────┘
```

### 8.2 Bridge Limitations

The bridge provides best-effort translation with known limitations:

- **No permission proxying**: A2A has no permission model. Bridge auto-allows
  all tool calls when an A2A agent is accessed via ACP.
- **No file/terminal ops**: A2A agents don't support fs/terminal operations.
  Bridge returns `-32601` (method not found) for these.
- **Session semantics differ**: ACP sessions are stateful with cwd context.
  A2A tasks are stateless message exchanges. Bridge maintains synthetic
  session state.
- **Streaming granularity**: A2A SSE is coarser than ACP session/update.
  Bridge maps SSE data events to `agent_message_chunk` updates.

## 9. Security Considerations

### 9.1 Trust Boundaries

```
┌─────────────────────────────────────────────────────────┐
│                    Trust Boundaries                      │
│                                                         │
│  UNTRUSTED          │  TRUSTED            │  ISOLATED   │
│  ──────────         │  ───────            │  ────────   │
│                     │                     │             │
│  External clients   │  Kagenti backend    │  Agent pod  │
│  (humr, IDEs)       │  (ACP gateway)      │  (sandbox)  │
│                     │                     │             │
│  • Must authenticate│  • Validates OIDC   │  • No svc   │
│  • Rate limited     │  • Enforces RBAC    │    account  │
│  • WS connection    │  • Session mgmt     │  • Network  │
│    validated        │  • Audit logging    │    policy   │
│                     │  • Permission proxy │  • Landlock  │
│                     │                     │  • seccomp   │
│                     │                     │  • ReadOnly  │
│                     │                     │    rootFS    │
└─────────────────────┴─────────────────────┴─────────────┘
```

### 9.2 WebSocket Security

- All WebSocket connections require OIDC token in the initial HTTP upgrade
- Connections are per-user, per-agent, per-namespace
- Rate limiting on session creation and prompt frequency
- Message size limits (16 MB per frame, matching ACP defaults)
- Idle timeout: 30 minutes (configurable)
- Connection audit trail in kagenti backend logs

### 9.3 Agent Isolation

Openshell agent pods maintain the existing kagenti security model:
- `securityContext.readOnlyRootFilesystem: true`
- Seccomp profile enforced
- No privilege escalation
- NetworkPolicy: ingress from kagenti-system only
- Workspace PVC with size limits
- Landlock kernel sandboxing (where supported)

## 10. Implementation Phases

### Phase 1: ACP Gateway (MVP)

- New feature flag: `kagenti_feature_flag_acp`
- WebSocket endpoint: `/acp/ws/{namespace}/{agent_name}`
- ACP lifecycle: initialize, authenticate (Keycloak), session management
- Prompt relay to agent runtime sidecar
- Session persistence in existing sessions DB
- Single agent support: Claude Code via SandboxClaim

### Phase 2: Agent Runtime Sidecar

- Container image with ACP stdio manager
- WebSocket server for gateway connection
- Process lifecycle management (spawn, health, restart)
- MCP configuration management
- File system operations (scoped to /workspace)
- Terminal multiplexing

### Phase 3: Multi-Harness Support

- Codex agent integration
- Gemini CLI agent integration
- Custom agent harness documentation
- Agent template catalog for ACP agents

### Phase 4: ACP-A2A Bridge

- Translation service for cross-protocol access
- Content block mapping (ACP ↔ A2A)
- Session-to-task state management
- Kagenti UI support for ACP agents

### Phase 5: Humr Integration

- Humr api-server connects to kagenti ACP gateway
- Shared Keycloak realm / token exchange
- Agent template synchronization
- Unified session history

## 11. Open Questions

1. **Agent runtime language**: Python (align with kagenti backend) vs
   TypeScript (reuse humr's proven implementation)?

2. **Session state storage**: Store ACP session state in kagenti's PostgreSQL
   or let the agent runtime manage its own state?

3. **Humr convergence timeline**: Should kagenti's ACP gateway eventually
   replace humr's api-server, or do they remain separate?

4. **ACP spec stability**: ACP is still evolving (streamable HTTP transport
   is draft). How much should we invest in the current spec vs waiting?

5. **Permission model integration**: Should kagenti's RBAC pre-filter ACP
   permissions (reducing UI prompts) or pass all permissions through?

## 12. References

- [ACP Specification](https://agentclientprotocol.com/specification)
- [ACP GitHub](https://github.com/agentclientprotocol/agent-client-protocol)
- [kagenti/humr](https://github.com/kagenti/humr)
- [Humr ADR-004: ACP over A2A](https://github.com/kagenti/humr) (internal)
- [A2A Protocol](https://google.github.io/A2A/)
- [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox)
- [Agent Card Spec](https://google.github.io/A2A/#/documentation?id=agentcard)
