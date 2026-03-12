# Design Doc Rewrite — Draft Content for Gamma Session

> This is a draft for the main design doc rewrite. Gamma session should
> expand this into the full `2026-03-01-sandbox-platform-design.md` with
> ~600 lines, mermaid diagrams for each section, and concise descriptions.

## Sections to include (with diagrams)

### 1. Goal + System Context (C4 Level 1)
Keep the existing C4Context diagram but update:
- Remove references to MLflow (using Phoenix instead)
- Add LiteLLM as explicit LLM routing layer

### 2. Architecture (C4 Level 2) — FULL REWRITE
New container diagram showing:
- LiteLLM in kagenti-system
- LLM Budget Proxy per namespace (planned Beta)
- Egress proxy as separate Deployment (not sidecar)
- Schema-per-agent DB (team schema + agent schemas)
- Sidecar agents concept

### 3. Security Model
- 7-layer defense-in-depth table
- Agent profiles (legion, basic, hardened, restricted)
- Remove gVisor (blocked)
- Egress proxy now separate deployment
- Composable wizard toggles (keep but simplify)

### 4. Agent Reasoning Architecture — NEW SECTION
- Plan-execute-reflect flowchart
- Micro-reasoning after each tool call
- Budget enforcement points
- Stall detection removed (reflector decides)
- Tool call limits → reflector decides continue/replan

### 5. HITL Sequence Diagram
- Keep existing diagram, update status
- Note: resume partially wired, sidecar agents can trigger

### 6. Database Architecture — NEW SECTION
- Schema-per-agent diagram
- Team schema vs agent schema
- Wizard creates/drops schemas
- Connection string management

### 7. LLM Budget Architecture — NEW SECTION
- Proxy between agent and LiteLLM
- Per-session token tracking in llm_calls table
- Per-agent monthly budget via LiteLLM virtual keys
- Error flow → visible in UI

### 8. Sidecar Agents — NEW SECTION
- Looper (auto-continue)
- Hallucination Observer (planned)
- Context Guardian (planned)
- Backend SidecarManager architecture

### 9. Event Pipeline
- SSE streaming from agent → backend → UI
- Loop event persistence
- Subscribe/resubscribe
- Recovery polling

### 10. Component Status Matrix
One big table: Component | Status | Design Doc | Sessions | Tests

### 11. Planned Work
Beta/Gamma/Delta/Epsilon with links

### 12. Sub-Design Document Index
All docs with relative links

## Relative links to verify

All must resolve at:
`https://github.com/Ladas/kagenti/blob/feat/sandbox-agent/docs/plans/{filename}`

```
./2026-03-12-llm-budget-proxy-design.md
./2026-03-12-db-multi-tenancy-design.md
./2026-03-03-sandbox-reasoning-loop-design.md
./2026-03-03-agent-loop-ui-design.md
./2026-03-07-litellm-proxy-design.md
./2026-03-08-litellm-analytics-design.md
./2026-03-09-loop-event-pipeline-design.md
./2026-03-10-visualizations-design.md
./2026-03-02-sandbox-file-browser-design.md
./2026-03-05-tabbed-session-view-design.md
./2026-03-04-platform-agent-runtime-design.md
./2026-02-27-session-orchestration-design.md
./2026-02-27-session-ownership-design.md
./2026-03-04-skill-packs-design.md
./2026-03-12-budget-limits-design.md
./2026-03-12-session-beta-passover.md
./2026-03-12-session-gamma-passover.md
./2026-03-11-session-Y-passover.md
./2026-03-11-session-Z-passover.md
./2026-03-12-session-alpha-passover.md
```
