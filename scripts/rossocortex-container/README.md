# RossoCortex

Budget proxy and credential bridge for AI agents running through LiteLLM.

## Architecture

```
Agent (Claude Code, custom agent, etc.)
  |
  |-- POST http://localhost:8185/v1/messages       (ANTHROPIC_BASE_URL, direct)
  |     |
  |     v
  |   rossocortex.py (budget proxy)
  |     |-- identifies agent from x-api-key / Authorization header
  |     |-- checks per-agent budget (reject if exceeded)
  |     |-- injects real LiteLLM credential (agent never sees it)
  |     |-- forwards to upstream LiteLLM
  |     |-- reads x-litellm-response-cost from response, tracks spend
  |     v
  |   Upstream LiteLLM (e.g. ete-litellm.ai-models.vpc-int.res.ibm.com)
  |
  |-- CONNECT github.com:443                       (HTTPS_PROXY, tunneled)
        |
        v
      rossocortex.py (CONNECT handler)
        |-- identifies agent from Proxy-Authorization header
        |-- checks network policy (allow/deny lists per agent)
        |-- establishes tunnel to AuthBridge forward proxy
        v
      AuthBridge (Go binary, TLS bridge)
        |-- terminates TLS with forged cert (signed by local CA)
        |-- runs pipeline plugins on decrypted traffic:
        |     - placeholder-resolve: swaps placeholder keys for real secrets
        |     - inference-parser: identifies LLM request/response structure
        |     - litellm-budget-track: tracks spend from response headers
        |     - mcp-parser: parses MCP protocol frames
        |-- re-encrypts and forwards to real upstream
        v
      Target host (github.com, npm registry, PyPI, etc.)
```

## Components

| Component | Role |
|-----------|------|
| `rossocortex.py` | HTTP/CONNECT proxy: agent identity, budget enforcement, credential injection, network policy, request logging |
| `authbridge-proxy` | Go binary: TLS interception, plugin pipeline (placeholder-resolve, budget-track), forward/reverse proxy modes |
| `rossoctlx.py` | CLI: start/stop, agent registration, budget/policy management, log viewing |
| `entrypoint.sh` | Container init: CA generation, credential file setup, config generation |

## Design Principles

1. **Agent never holds real credentials.** The agent receives an opaque identity token (`name:random`). rossocortex injects the real LiteLLM key on every request. If the agent is compromised, the token is worthless outside the proxy.

2. **All traffic is identified.** Every HTTP request and HTTPS CONNECT tunnel must carry agent identity. Unidentified connections get 401 (HTTP) or 407 (CONNECT). No anonymous access.

3. **Per-agent budget enforcement.** Each agent has an independent daily spend cap. rossocortex reads `x-litellm-response-cost` from upstream responses and accumulates per-agent spend. Requests exceeding the budget are rejected before forwarding.

4. **Per-agent network policy.** Allow/deny lists (fnmatch globs) control which hosts an agent can reach via CONNECT tunnels. Deny is checked first; if an allow list exists, the host must match at least one pattern.

5. **Credential injection via pipeline.** AuthBridge's `placeholder-resolve` plugin can swap placeholder tokens in request bodies (for CONNECT-tunneled traffic) with real secrets from a mounted directory. This enables agents to use APIs without ever seeing real keys.

6. **Single CA trust root.** AuthBridge generates a local CA certificate. Agents trust it via `SSL_CERT_FILE`. All MITM'd connections present certificates signed by this CA. The CA is ephemeral (30-day expiry) and local to the host.

## AuthBridge Integration

AuthBridge runs as a sidecar process managed by rossocortex. It provides:

- **Forward proxy** (port auto-allocated): Accepts CONNECT tunnels from rossocortex, performs TLS interception, runs the plugin pipeline, then forwards to the real destination.
- **TLS bridge**: Forges per-host certificates signed by the local CA. Clients see valid certs as long as they trust `SSL_CERT_FILE`.
- **Plugin pipeline** (outbound): Processes decrypted request/response bytes through ordered plugins before re-encryption.
- **TLS skip-list**: If a host's MITM handshake fails (e.g., client uses certificate pinning), AuthBridge permanently marks it as passthrough for that process lifetime.
- **Spend tracking**: The `litellm-budget-track` plugin reads cost headers from responses flowing through CONNECT tunnels (complementing rossocortex's tracking on direct HTTP requests).

### Configuration

AuthBridge config (`config.yaml`) is generated fresh on every startup with dynamically-allocated ports. The template lives in `templates/config.yaml.j2`. Key sections:

```yaml
listener:
  forward_proxy_addr: "0.0.0.0:<auto-port>"  # rossocortex CONNECT tunnels land here

tls_bridge:
  mode: enabled
  ca_dir: <config_dir>/ca                    # CA cert/key for forging certs
  ports: [443]                               # intercept standard HTTPS

pipeline:
  outbound:
    plugins:
      - placeholder-resolve                  # inject real keys into request bodies
      - inference-parser                     # identify LLM traffic structure
      - mcp-parser                           # parse MCP protocol
  inbound:
    plugins:
      - litellm-budget-track                 # read x-litellm-response-cost
```

## Agent Identity Flow

```
1. rossoctlx.py agent <name> --budget=5.00
   -> generates token, saves to agents.json
   -> prints eval-ready env vars

2. Agent sets env:
   ANTHROPIC_BASE_URL=http://localhost:8185
   ANTHROPIC_AUTH_TOKEN=name:token
   HTTPS_PROXY=http://name:token@localhost:8185
   NO_PROXY=localhost,127.0.0.1
   SSL_CERT_FILE=~/.config/rossocortex/ca/tls.crt

3. LLM calls (POST /v1/messages):
   -> bypass HTTPS_PROXY (NO_PROXY)
   -> hit rossocortex directly via ANTHROPIC_BASE_URL
   -> identity from x-api-key header (ANTHROPIC_AUTH_TOKEN)

4. External HTTPS (github.com, npm, etc.):
   -> routed through HTTPS_PROXY
   -> CONNECT tunnel with Proxy-Authorization from URL userinfo
   -> rossocortex identifies agent, checks network policy
   -> tunnels through AuthBridge for TLS interception
```

## Capabilities

- **Budget proxy**: Global and per-agent daily spend limits with real-time tracking
- **Credential injection**: Real API keys never exposed to agents
- **Network policy**: Per-agent allow/deny lists on HTTPS destinations
- **TLS interception**: Full visibility into agent HTTPS traffic via AuthBridge
- **Request logging**: Every request logged with agent, status, model, cost, denial reason
- **Log rotation**: Daily rotation, 10-day retention
- **Container or local mode**: Same code, same config, different deployment
- **Dynamic port allocation**: No port conflicts even with multiple instances
- **Agent management CLI**: Register, update, delete, list agents with copy-pasteable config

## Prerequisites

1. **LiteLLM virtual key** — rossocortex proxies to a LiteLLM instance. Make sure ANTHROPIC_AUTH_TOKEN environment variables is available (saved automatically in config file on first start):
   ```bash
   export ANTHROPIC_AUTH_TOKEN=sk-your-litellm-key
   ```

2. **Docker or Podman** — for container mode (default). Force one with `--runtime=podman`.

## Getting the Code

The `rossoctlx` branch lives on the `aslom` fork, not the upstream org repo:

```bash
git remote add aslom https://github.com/aslom/kagenti.git  # skip if already added
git fetch aslom rossoctlx
git checkout -B rossoctlx aslom/rossoctlx
```

## Running

### Container (default)

```bash
rossoctlx.py start --upstream https://litellm.example.com
# Or force podman:
rossoctlx.py --runtime=podman start --upstream https://litellm.example.com
```

Pulls `quay.io/aslomnet/rosscortex:latest`, mounts `~/.config/rossocortex` for persistence.
Never copy the printed `docker run` command — it contains expanded absolute paths specific
to the current machine. Always use `rossoctlx.py start`.

### Local

```bash
export ROSSOCORTEX_CONTAINER_LOCAL_DIR=/path/to/kagenti/scripts/rossocortex-container
rossoctlx.py start --local --upstream https://litellm.example.com
```

Requires the AuthBridge binary (auto-built on first run via `authbridge_wrapper.py`).

## File Layout

```
rossocortex-container/
  rossocortex.py          # The proxy server (runs in both modes)
  authbridge_wrapper.py   # Builds/inits the Go AuthBridge binary
  templates/config.yaml.j2  # AuthBridge config template
  Dockerfile              # Container image definition
  entrypoint.sh           # Container startup script
  build.sh                # Build container image
  push.sh                 # Push to registry
```

## State Files

All under `~/.config/rossocortex/` (or `$XDG_CONFIG_HOME/rossocortex/`):

| File | Purpose |
|------|---------|
| `rossocortex-state.json` | Runtime state: ports, upstream, mode, image, docker command |
| `agents.json` | Registered agents: tokens, budgets, network policies |
| `rossocortex.log` | Request log (rotated daily) |
| `ca/tls.crt`, `ca/tls.key` | AuthBridge CA certificate |
| `credentials/` | Real API keys (never exposed to agents) |
| `agents/<name>/` | Per-agent config and spend tracking |
| `config.yaml` | Generated AuthBridge config (regenerated on each start) |
