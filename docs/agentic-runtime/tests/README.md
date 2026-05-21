# OpenShell E2E Test Category Index

> Back to [main doc](../openshell-integration.md) | [Test matrix](../e2e-test-matrix.md)

## Overview

This directory contains detailed documentation for each E2E test category.
Each doc explains what's being tested, shows the architecture under test with
mermaid diagrams, and maps test functions to agent types.

For current test counts, pass/skip status, and per-agent capability coverage,
see the **[E2E Test Matrix](../e2e-test-matrix.md)** — that is the canonical
source of truth.

## Test Categories

Tests use tiered naming: `test_T{tier}_{module}_{description}.py`

### Tier 0: Infrastructure

- [T0-1 Platform Health](T0-1-infra-platform.md) — Gateway, operator, agent pods
- [T0-3 Supervisor Enforcement](T0-3-infra-supervisor.md) — Landlock, netns, seccomp, OPA
- [T0-4 NemoClaw Infrastructure](T0-4-infra-nemoclaw.md) — NemoClaw health, security, connectivity
- [T0-5 LiteLLM Infrastructure](T0-5-infra-litellm.md) — LiteLLM config, waypoint, passthrough

### Tier 1: Basic Capabilities

- [T1-1 Connectivity](T1-1-connectivity.md) — A2A JSON-RPC, agent card discovery
- [T1-2 Credentials](T1-2-credentials.md) — secretKeyRef, no hardcoded keys
- [T1-3 Sandbox Lifecycle](T1-3-sandbox-lifecycle.md) — Sandbox CR CRUD, status observability
- [T1-4 Workspace](T1-4-workspace.md) — PVC data persistence
- [T1-5 Resource Limits](T1-5-resource-limits.md) — CPU/memory limits on all agents
- T1-6 Credential Security (`test_T1_6_credential_security.py`, 5 tests) — secretKeyRef delivery, no hardcoded secrets, policy ConfigMaps
- T1-7 Sandbox Connectivity (`test_T1_7_sandbox_connectivity.py`, 5 tests) — Gateway reachable, kubectl exec into sandboxes

### Tier 2: Conversation

- [T2-1 Multi-Turn](T2-1-multiturn.md) — Sequential messages, context isolation, tool calling
- [T2-3 Session Resume](T2-3-session-resume.md) — Session resume across pod restarts

### Tier 3: Skills

- [T3-1 Skill Execution](T3-1-skill-execution.md) — PR review, RCA, security review across agents and models

### Tier 4: Security

- [T4-1 HITL Network](T4-1-hitl-network.md) — OPA egress blocking
- T4-2 Tenant Isolation (`test_T4_2_tenant_isolation.py`, 15 tests) — JWT audience auth, RBAC namespace scoping, credential isolation

### Tier 5: Backend API

- [T5-1 Backend API](T5-1-backend-api.md) — A2A proxy through kagenti-backend

### Tier 6: ACP Protocol

- [T6-1 ACP Protocol](T6-1-acp-protocol.md) — ACP WebSocket JSON-RPC 2.0

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
uv run pytest kagenti/tests/e2e/openshell/ -v --timeout=300

# Single category
uv run pytest kagenti/tests/e2e/openshell/test_T0_1_infra_platform.py -v

# With debug logging
uv run pytest kagenti/tests/e2e/openshell/ -v --log-cli-level=INFO

# Skip destructive tests
export OPENSHELL_DESTRUCTIVE_TESTS=false
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENSHELL_AGENT_NAMESPACE` | `team1` | Agent namespace |
| `OPENSHELL_GATEWAY_NAMESPACE` | `team1` | Gateway namespace |
| `OPENSHELL_LLM_AVAILABLE` | `false` | Enable LLM-dependent tests |
| `OPENSHELL_LLM_MODELS` | — | Comma-separated model list |
| `OPENSHELL_NEMOCLAW_ENABLED` | `false` | Enable NemoClaw tests |
| `OPENSHELL_BACKEND_AVAILABLE` | `false` | Enable backend API tests (T5/T6) |
| `OPENSHELL_DESTRUCTIVE_TESTS` | `false` | Enable pod restart tests |
| `OPENSHELL_AGENT_PORT` | `8080` | Agent port for port-forwarding |
| `OPENSHELL_LLM_PROVIDER` | `remote` | LLM provider type (`remote` or `ollama`) |
