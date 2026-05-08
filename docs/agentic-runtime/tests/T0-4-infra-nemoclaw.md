# NemoClaw Infrastructure

> **Test file:** `kagenti/tests/e2e/openshell/test_T0_4_infra_nemoclaw.py`
> **Tests:** 11

## What This Tests

Validates that NemoClaw agents (Hermes and OpenClaw) deployed via OpenShell are healthy, reachable, and properly secured. These agents use native APIs rather than A2A JSON-RPC -- Hermes exposes an OpenAI-compatible API on port 8642 and OpenClaw uses a gateway API on port 18789. Tests cover deployment health, health probes, basic inference smoke tests, and security posture (AuthBridge disabled, no privilege escalation, capabilities dropped, LLM keys from secrets). The entire suite is gated behind the `OPENSHELL_NEMOCLAW_ENABLED` environment variable.

## Test Functions

- `test_deployment_exists[agent]` -- NemoClaw agent deployment exists and has at least one available replica.
- `test_pod_running[agent]` -- NemoClaw agent pod is in Running phase.
- `test_framework_label[agent]` -- NemoClaw agents carry the `kagenti.io/framework=NemoClaw` label.
- `test_hermes_health` -- Hermes gateway is reachable via TCP connect (no HTTP health endpoint).
- `test_openclaw_health` -- OpenClaw agent responds to its gateway health endpoint with 200.
- `test_hermes_chat_completion` -- Hermes processes an OpenAI-compatible chat completion request (skips if LLM unavailable or HTTP API not deployed).
- `test_openclaw_gateway_interaction` -- OpenClaw gateway root returns a valid HTTP response.
- `test_authbridge_disabled[agent]` -- NemoClaw agents have `kagenti.io/inject=disabled` to skip AuthBridge sidecar injection.
- `test_no_privilege_escalation[agent]` -- All containers set `allowPrivilegeEscalation: false`.
- `test_capabilities_dropped[agent]` -- All containers drop ALL Linux capabilities.
- `test_llm_key_from_secret[agent]` -- OPENAI_API_KEY is sourced via `secretKeyRef`, not a literal env value.
