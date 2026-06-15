# Quickstart: Agent Runtime Contract (ARC)

## What is ARC?

The Agent Runtime Contract (ARC) is the versioned interface between the Kagenti platform and agent containers. It tells agents what the platform provides (identity, proxy, MCP servers, skills) and what agents must expose (A2A card, health probes).

## For Agent Developers

### Reading the contract

Every Kagenti-managed agent Pod has `/arc/AGENTS.md` mounted. Read it at startup:

```python
# Python
with open("/arc/AGENTS.md") as f:
    contract = f.read()

# Check contract version
import os
version = os.environ.get("ARC_CONTRACT_VERSION", "unknown")
```

### Using MCP servers

```python
import json, os

mcp_config = os.environ.get("ARC_MCP_CONFIG", "/arc/mcp/servers.json")
with open(mcp_config) as f:
    servers = json.load(f)["mcpServers"]

for name, config in servers.items():
    print(f"MCP server: {name} at {config['url']}")
```

### Making authenticated outbound requests

Route through the proxy. The sidecar handles mTLS automatically:

```python
import os
proxies = {
    "http": os.environ.get("HTTP_PROXY"),
    "https": os.environ.get("HTTPS_PROXY"),
}
response = requests.get("http://other-agent.team1:8080/api", proxies=proxies)
```

### Required agent endpoints

Your container must expose:
1. `/.well-known/agent-card.json` (A2A discovery)
2. Liveness probe (e.g., `/healthz`)
3. Readiness probe (e.g., `/readyz`)

## For Platform Operators

### Configuring ARC features via AgentRuntime CR

```yaml
apiVersion: agent.kagenti.dev/v1alpha1
kind: AgentRuntime
metadata:
  name: my-agent
  namespace: team1
spec:
  type: agent
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-agent
  arc:
    tracing:
      enabled: true
    obo:
      mode: token-forwarding
```

### Verifying ARC injection

```bash
# Check AGENTS.md is mounted
kubectl exec -n team1 deploy/my-agent -- cat /arc/AGENTS.md

# Check ARC env vars
kubectl exec -n team1 deploy/my-agent -- env | grep ARC_

# Check MCP servers
kubectl exec -n team1 deploy/my-agent -- cat /arc/mcp/servers.json
```
