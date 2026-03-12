# Session Alpha (continued) — Main Design Doc Rewrite

> **Date:** 2026-03-12
> **Context:** Alpha session context was cleaned. Resume with this task only.
> **Cluster:** sbox42 (KUBECONFIG=/tmp/kagenti/sbox42-kubeconfig)
> **Worktree:** `.worktrees/sandbox-agent` (kagenti repo, branch: feat/sandbox-agent)

## Task

Rewrite the main design doc at `docs/plans/2026-03-01-sandbox-platform-design.md`.

Current state: 1400 lines, outdated architecture, wrong component status.
Target: ~535 lines, accurate architecture, 5 mermaid diagrams, relative links.

## Inputs to Read

1. **Draft outline:** `docs/plans/2026-03-12-design-doc-rewrite-draft.md`
   — Section structure, link list, diagram plan

2. **Current state of all items:** `docs/plans/2026-03-12-session-gamma-passover.md`
   — 39-item tracking list, what's done vs remaining, architecture change table

3. **Sub-design docs to link (all in `docs/plans/`):**
   - `2026-03-12-llm-budget-proxy-design.md` — LLM proxy + budget (🔲 Beta)
   - `2026-03-12-db-multi-tenancy-design.md` — Schema-per-agent DB (🔲 Beta)
   - `2026-03-03-sandbox-reasoning-loop-design.md` — Plan-execute-reflect (✅ Built)
   - `2026-03-03-agent-loop-ui-design.md` — Loop cards UI (✅ Built)
   - `2026-03-07-litellm-proxy-design.md` — LiteLLM deployment (✅ Built)
   - `2026-03-08-litellm-analytics-design.md` — Token usage tab (✅ Built)
   - `2026-03-09-loop-event-pipeline-design.md` — SSE + persistence (✅ Built)
   - `2026-03-10-visualizations-design.md` — Session graph DAG (🔲 Epsilon)
   - `2026-03-02-sandbox-file-browser-design.md` — File browser (✅ Built)
   - `2026-03-05-tabbed-session-view-design.md` — Tabbed layout (✅ Built)
   - `2026-03-04-platform-agent-runtime-design.md` — Wizard deploy (🔧 Partial)
   - `2026-02-27-session-orchestration-design.md` — Session passover (🔲 Not built)
   - `2026-02-27-session-ownership-design.md` — Per-user sessions (🔧 Partial)
   - `2026-03-04-skill-packs-design.md` — Skill loading (🔧 Partial)
   - `2026-03-12-budget-limits-design.md` — Budget naming (✅ Reference)

4. **Current design doc to overwrite:** `docs/plans/2026-03-01-sandbox-platform-design.md`

## Target Document Structure (~535 lines)

### Sections with estimated sizes

| # | Section | Lines | Diagram |
|---|---------|-------|---------|
| 1 | Goal + header | 10 | — |
| 2 | Architecture (C4 Container) | 80 | C4Container mermaid (~40 lines) |
| 3 | Component status matrix | 50 | — |
| 4 | Security model | 40 | — |
| 5 | Agent reasoning architecture | 55 | Flowchart mermaid (~15 lines) |
| 6 | HITL flow | 50 | Sequence diagram (~30 lines) |
| 7 | Database architecture | 50 | ER diagram mermaid (~20 lines) |
| 8 | LLM budget enforcement | 40 | Flow diagram (~15 lines) |
| 9 | Sidecar agents | 25 | — |
| 10 | Event pipeline | 25 | — |
| 11 | Planned work | 25 | — |
| 12 | Sub-design doc index | 35 | — |
| | **Total** | **~535** | **5 diagrams** |

## Key Architecture Changes to Reflect

| Area | Old (in doc) | Current |
|------|-------------|---------|
| Squid proxy | Sidecar container | Separate Deployment (`{agent}-egress-proxy`) |
| LiteLLM | Not shown | In kagenti-system, shared model routing |
| LLM Budget Proxy | Doesn't exist | Designed: per-namespace, agent→proxy→LiteLLM |
| DB isolation | Shared public schema | Schema-per-agent for checkpoints, team schema for sessions |
| Agent naming | Composable suffixes (`-secctx-landlock-proxy`) | Profiles: legion, basic, hardened, restricted |
| gVisor | T4 tier | Removed (OpenShift SELinux incompatible) |
| Agent reasoning | Basic tool loop | Plan-execute-reflect with micro-reasoning |
| Sidecar agents | Not designed | Looper, Hallucination Observer, Context Guardian |
| Budget | Not enforced | In-memory → LLM proxy (in progress) |

## Process

1. Read the draft outline and gamma passover
2. Read 3-4 key sub-design docs for accurate descriptions
3. Write the full doc (~535 lines)
4. Verify all relative links:
   ```bash
   grep -oP '\./[^)]+\.md' docs/plans/2026-03-01-sandbox-platform-design.md | sort -u | while read f; do
     path="docs/plans/${f#./}"
     if [ -f "$path" ]; then echo "✅ $f"; else echo "❌ $f MISSING"; fi
   done
   ```
5. Commit and push
6. Review the GitHub PR file view to verify links render correctly

## Do NOT

- Do not implement any code — this is a documentation task only
- Do not change any sub-design docs — only the main design doc
- Do not add detail that belongs in sub-designs — main doc is the index/map
