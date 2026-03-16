# Stream: Sandbox Agent

Created: 2026-03-13
Source branches: `feat/sandbox-agent` (kagenti/kagenti), `feat/sandbox-agent` (kagenti/agent-examples)
Stream worktrees: `.worktrees/stream-sandbox-agent`, `.worktrees/stream-agent-examples`

## Analysis

### stream-sandbox-agent (kagenti/kagenti) — Branch: feat/sandbox-agent

**Base**: main | **Files**: 476 | **+Lines**: 68,945 | **-Lines**: 15,671 | **Net**: 53,274

| PR | Category | Files | +Lines | -Lines | Net | Depends On |
|----|----------|-------|--------|--------|-----|------------|
| K1 | Infrastructure & Deployment | 97 | +3,172 | -1,683 | 1,489 | - |
| K2 | Skills Update | 37 | +342 | -3,557 | -3,215 | - |
| K3 | Backend Core | 33 | +8,749 | -90 | 8,659 | K1 |
| K4 | LLM Budget Proxy | 3 | +524 | -0 | 524 | K1 |
| K5 | Sandbox Agent Deployments | 62 | +6,372 | -0 | 6,372 | K1 |
| K6 | Frontend/UI | 52 | +13,798 | -291 | 13,507 | K3 |
| K7 | UI E2E Tests | 37 | +10,550 | -184 | 10,366 | K6 |
| K8 | Backend E2E Tests | 12 | +2,116 | -1,293 | 823 | K3 |
| K9 | Documentation | 73 | +22,249 | -336 | 21,913 | - |
| K10 | Other/Cleanup (TUI removal) | 70 | +1,073 | -8,237 | -7,164 | - |
| **TOTAL** | | **476** | **+68,945** | **-15,671** | **53,274** | |

### stream-agent-examples (kagenti/agent-examples) — Branch: feat/sandbox-agent

**Base**: upstream/main | **Files**: 169 | **+Lines**: 13,582 | **-Lines**: 6,004 | **Net**: 7,578

| PR | Category | Files | +Lines | -Lines | Net | Depends On |
|----|----------|-------|--------|--------|-----|------------|
| A1 | Sandbox Agent Core | 13 | +5,851 | -0 | 5,851 | - |
| A2 | Sandbox Agent Tests | 9 | +2,208 | -0 | 2,208 | A1 |
| A3 | Sandbox Agent Deployment | 6 | +3,069 | -0 | 3,069 | A1 |
| A4 | Other A2A Agents | 108 | +13,098 | -1,472 | 11,626 | - |
| A5 | MCP Tools | 23 | +437 | -505 | -68 | - |
| A6 | Integration Tests (removals) | 10 | +0 | -518 | -518 | - |
| A7 | Skills/Claude Config | 14 | +0 | -2,861 | -2,861 | - |
| A8 | CI/Workflows + Root Config | 16 | +47 | -648 | -601 | - |
| **TOTAL** | | **169** | **+13,582** | **-6,004** | **7,578** | |

## Cross-Repo Summary

| Repo | Worktree | PRs | Files | Lines |
|------|----------|-----|-------|-------|
| kagenti/kagenti | stream-sandbox-agent | 10 | 476 | +68,945 / -15,671 |
| kagenti/agent-examples | stream-agent-examples | 8 | 169 | +13,582 / -6,004 |
| **TOTAL** | | **18** | **645** | **+82,527 / -21,675** |

## Merge Order

Independent PRs (can merge in any order, in parallel):
1. K10 — Other/Cleanup (TUI removal, terraform removal) — kagenti
2. K2 — Skills Update (portable LOG_DIR, new UI test skills) — kagenti
3. K9 — Documentation (design docs, passover docs) — kagenti
4. A4 — Other A2A Agents (non-sandbox agents) — agent-examples
5. A5 — MCP Tools — agent-examples
6. A6 — Integration Tests removals — agent-examples
7. A7 — Skills/Claude Config cleanup — agent-examples
8. A8 — CI/Workflows + Root Config — agent-examples

Sequential chain (kagenti/kagenti):
9. K1 — Infrastructure & Deployment (CI, Helm, Ansible, scripts)
10. K4 — LLM Budget Proxy (after K1)
11. K5 — Sandbox Agent Deployments (after K1)
12. K3 — Backend Core (after K1)
13. K6 — Frontend/UI (after K3)
14. K7 — UI E2E Tests (after K6)
15. K8 — Backend E2E Tests (after K3)

Sequential chain (kagenti/agent-examples):
16. A1 — Sandbox Agent Core
17. A2 — Sandbox Agent Tests (after A1)
18. A3 — Sandbox Agent Deployment (after A1)

## PR Status

| # | Repo | Phase | Title | Branch | PR | Status |
|---|------|-------|-------|--------|----|--------|
| K1 | kagenti | 1/10 | Infrastructure & Deployment | - | - | pending |
| K2 | kagenti | 2/10 | Skills Update | - | - | pending |
| K3 | kagenti | 3/10 | Backend Core | - | - | pending |
| K4 | kagenti | 4/10 | LLM Budget Proxy | - | - | pending |
| K5 | kagenti | 5/10 | Sandbox Agent Deployments | - | - | pending |
| K6 | kagenti | 6/10 | Frontend/UI | - | - | pending |
| K7 | kagenti | 7/10 | UI E2E Tests | - | - | pending |
| K8 | kagenti | 8/10 | Backend E2E Tests | - | - | pending |
| K9 | kagenti | 9/10 | Documentation | - | - | pending |
| K10 | kagenti | 10/10 | Other/Cleanup | - | - | pending |
| A1 | agent-examples | 1/8 | Sandbox Agent Core | - | - | pending |
| A2 | agent-examples | 2/8 | Sandbox Agent Tests | - | - | pending |
| A3 | agent-examples | 3/8 | Sandbox Agent Deployment | - | - | pending |
| A4 | agent-examples | 4/8 | Other A2A Agents | - | - | pending |
| A5 | agent-examples | 5/8 | MCP Tools | - | - | pending |
| A6 | agent-examples | 6/8 | Integration Tests | - | - | pending |
| A7 | agent-examples | 7/8 | Skills/Claude Config | - | - | pending |
| A8 | agent-examples | 8/8 | CI/Workflows + Root Config | - | - | pending |

## Session Log

- 2026-03-13: Initial analysis complete. 2 repos, 18 PRs planned. Stream worktrees created.
