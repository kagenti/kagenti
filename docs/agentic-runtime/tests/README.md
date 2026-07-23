---
draft: true       # excluded from https://www.rossoctl.dev/
---

# OpenShell E2E Test Category Index

> Back to [main doc](../openshell-integration.md) | [Test matrix](../e2e-test-matrix.md)

## Overview

This directory contains detailed documentation for each E2E test category. Each doc explains what's being tested, shows the architecture under test with mermaid diagrams, and maps test functions to agent types.

## Test Categories

| # | Category | Test File | Tests | Pass | Skip | Focus |
|---|----------|-----------|-------|------|------|-------|
| 01 | [Platform Health](01-platform-health.md) | `test_01_platform_health.py` | 7 | 7 | 0 | Gateway, operator, agent pods |
| 02 | [A2A Connectivity](02-a2a-connectivity.md) | `test_02_a2a_connectivity.py` | 8 | 7 | 1 | JSON-RPC, agent card discovery |
| 03 | [Credential Security](03-credential-security.md) | `test_T1_6_credential_security.py` | 15 | 15 | 0 | secretKeyRef, policy mounting |
| 04 | [Sandbox Lifecycle](04-sandbox-lifecycle.md) | `test_04_sandbox_lifecycle.py` | 7 | 7 | 0 | Sandbox CR CRUD, status observability |
| 05 | [Multi-Turn Conversation](05-multiturn-conversation.md) | `test_05_multiturn_conversation.py` | 12 | 9 | 3 | Sequential messages, context isolation |
| 06 | [Conversation Resume](06-conversation-resume.md) | `test_06_conversation_resume.py` | 5 | 0 | 5 | Pod restart, PVC session restore |
| 07 | [Skill Execution](07-skill-execution.md) | `test_07_skill_execution.py` | 27 | 18 | 9 | PR review, RCA, security review |
| 08 | [Supervisor Enforcement](08-supervisor-enforcement.md) | `test_08_supervisor_enforcement.py` | 11 | 11 | 0 | Landlock, netns, OPA policy |
| 09 | [HITL Policy](09-hitl-policy.md) | `test_09_hitl_policy.py` | 3 | 2 | 1 | OPA egress blocking |
| 10 | [Workspace Persistence](10-workspace-persistence.md) | `test_10_workspace_persistence.py` | 8 | 7 | 1 | PVC data persistence |

**Totals:** 136 tests, 102 passed (local Kind+LLM+NemoClaw), 34 skipped (Kind, fresh cluster)

## Agent Type Coverage

Each test category covers ALL 7 agent types where applicable:

| Agent ID | Type | Tests Cover |
|----------|------|-------------|
| `weather_agent` | Custom A2A | A2A connectivity, multi-turn, security |
| `adk_agent` | Custom A2A | Skill execution, LLM interaction |
| `claude_sdk_agent` | Custom A2A | Skill execution, LLM interaction |
| `weather_supervised` | Custom A2A + supervisor | Supervisor enforcement, HITL policy |
| `openshell_claude` | Builtin sandbox | Workspace persistence, sandbox lifecycle |
| `openshell_opencode` | Builtin sandbox | Workspace persistence, sandbox lifecycle |
| `openshell_generic` | Builtin sandbox | Workspace persistence, sandbox lifecycle |

Unsupported combinations are explicitly skipped with documented reasons.

## Using These Docs

Each test doc includes:

1. **What This Tests** — capability being validated
2. **Architecture Under Test** — mermaid diagram showing components + data flow
3. **Test Matrix** — which agents pass/skip each test
4. **Test Details** — per-test assertions, debug points, skip reasons
5. **Future Expansion** — what's needed to enable skipped tests

## Running Tests

```bash
# All tests
uv run pytest rossoctl/tests/e2e/openshell/ -v --timeout=300

# Single category
uv run pytest rossoctl/tests/e2e/openshell/test_01_platform_health.py -v

# With debug logging
uv run pytest rossoctl/tests/e2e/openshell/ -v --log-cli-level=INFO

# Skip destructive tests
export OPENSHELL_DESTRUCTIVE_TESTS=false
```

## Test Status Legend

- **✅** — test runs and passes
- **⏭️** — test skips with documented reason (shown in test matrix)
- **—** — test not applicable for this agent type

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENSHELL_AGENT_NAMESPACE` | `team1` | Agent namespace |
| `OPENSHELL_GATEWAY_NAMESPACE` | `openshell-system` | Gateway namespace |
| `OPENSHELL_LLM_AVAILABLE` | `false` | Enable LLM-dependent tests |
| `OPENSHELL_DESTRUCTIVE_TESTS` | `false` | Enable pod restart tests |

## Test File Organization

Tests are organized by capability, not by agent type. This ensures:

- All agents are tested for each capability
- Gaps are explicit (skipped with reason)
- Test structure matches architecture docs
- Easy to add new agent types (add column to matrix)
