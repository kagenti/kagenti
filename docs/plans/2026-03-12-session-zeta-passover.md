# Session Zeta Passover — MCP Gateway CI Integration

> **Date:** 2026-03-12
> **From:** Session Epsilon
> **Cluster:** sbox42
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)

## Goal

Integrate MCP Gateway tool calls into the sandbox agent CI test suite.
Agents should be able to call MCP-registered tools (weather, fetch, etc.)
through the gateway and have these interactions tested end-to-end.

## Background

The MCP Gateway is already deployed:
- **Envoy proxy** in `gateway-system` namespace
- **MCP controller + broker** in `mcp-system` namespace
- **Agent endpoint:** `http://mcp-gateway-istio.gateway-system.svc.cluster.local:8080/mcp`
- Tools register via `HTTPRoute` + `MCPServerRegistration` CRDs

## What Session Zeta Should Do

### Priority 0: Weather Tool E2E Test

Deploy a weather MCP server and test the full flow: agent receives user
question, discovers weather tool via MCP gateway, calls it, returns result.

1. **Deploy weather MCP server** (if not already deployed)
   ```yaml
   apiVersion: gateway.networking.k8s.io/v1
   kind: HTTPRoute
   metadata:
     name: weather-tool
   spec:
     hostnames: ["weather-tool.mcp.local"]
     rules:
       - backendRefs:
           - name: weather-tool
             port: 8080
   ---
   apiVersion: mcp.kagenti.com/v1alpha1
   kind: MCPServerRegistration
   metadata:
     name: weather-tool
   spec:
     toolPrefix: "weather_"
     httpRouteRef:
       name: weather-tool
   ```

2. **Configure sandbox agent to use MCP gateway**
   - Set `MCP_URL` env var on agent deployment
   - Agent should discover and bind MCP tools at startup

3. **Write Playwright E2E test** (`e2e/sandbox-mcp-weather.spec.ts`)
   - Send message: "What's the weather in New York?"
   - Verify agent discovers `weather_get_forecast` tool via MCP
   - Verify tool call appears in loop card with MCP tool badge
   - Verify weather result appears in agent response

4. **Write backend E2E test** (`test_sandbox_mcp.py`)
   - Test agent card includes MCP tools in capabilities
   - Test tool call round-trip through gateway
   - Test error handling when MCP server is unavailable

### Priority 1: MCP Gateway in CI Pipeline

Add MCP gateway deployment to CI test infrastructure:

1. **Kind cluster setup** — add MCP gateway deployment to
   `.github/scripts/local-setup/kind-full-test.sh`
   - Deploy `mcp-gateway` chart or manifests
   - Deploy weather tool as test fixture
   - Verify gateway health before running tests

2. **HyperShift test setup** — add MCP gateway to
   `.github/scripts/local-setup/hypershift-full-test.sh`
   - Same deployment steps as Kind
   - Verify cross-namespace routing works

3. **CI workflow** — add MCP test stage after agent deployment
   - Run `sandbox-mcp-weather.spec.ts` as part of E2E suite
   - Gate on MCP gateway health check

### Priority 2: Additional MCP Tool Tests

Once weather works end-to-end, add tests for:

1. **Fetch tool** — agent uses MCP fetch to retrieve a URL
2. **Authenticated tool** (Slack) — verify OAuth credential flow through gateway
3. **Tool discovery** — verify agent dynamically discovers new tools when
   `MCPServerRegistration` is created
4. **Error scenarios** — tool server down, timeout, invalid response

### Priority 3: MCP Tool Rendering in UI

Ensure MCP tool calls render correctly in the loop cards:

- Tool call step shows MCP tool name (e.g., `weather_get_forecast`)
- Tool source badge distinguishes MCP tools from built-in tools
- Tool result displays formatted weather data
- Stats tab includes MCP tool call counts

## Items from Master Tracking

| Item | Origin | Notes |
|------|--------|-------|
| MCP gateway in sandbox agent flow | New | Agent -> MCP gateway -> tool servers |
| Weather tool E2E test | New | First MCP tool test in CI |
| MCP in Kind CI | New | Deploy gateway in local test cluster |
| MCP in HyperShift CI | New | Deploy gateway in HyperShift test cluster |
| MCP tool rendering | New | Loop cards show MCP tool badge |
