# Resource Limits

> **Test file:** `kagenti/tests/e2e/openshell/test_T1_5_resource_limits.py`
> **Tests:** 4

## What This Tests

Validates that agent and sandbox pods have CPU and memory resource limits and requests configured. Checks A2A agents, NemoClaw agents, and Claude Code sandbox pods to ensure Kubernetes resource governance is in place. Tests currently skip (rather than fail) for containers that lack limits, since not all upstream agent charts set them yet.

## Test Functions

- `test_resource_limits__agent__has_limits[agent]` -- A2A agent deployment containers have CPU or memory `limits` set.
- `test_resource_limits__agent__has_requests[agent]` -- A2A agent deployment containers have CPU or memory `requests` set.
- `test_resource_limits__nemoclaw__has_limits[agent]` -- NemoClaw deployment containers have CPU or memory `limits` set (skips if NemoClaw disabled).
- `test_resource_limits__openshell_claude__sandbox_pod_limits` -- Claude Code sandbox pod has resource limits on the sandbox container (skips if Sandbox CRD not installed).
