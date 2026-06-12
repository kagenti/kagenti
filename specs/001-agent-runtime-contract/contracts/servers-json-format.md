# Contract: /arc/mcp/servers.json Format

**Version**: v1alpha1
**Compatible with**: The `mcpServers` de facto standard used by Claude Code, Claude Desktop, Cursor, Windsurf, Gemini, LM Studio, and ToolHive

## Format

JSON file with a top-level `mcpServers` object. Each key is a server name, value is an object with at minimum a `url` field. Extended fields (`transport`, `auth`) are Kagenti additions ignored by standard tooling.

## Schema

```json
{
  "mcpServers": {
    "<server-name>": {
      "url": "<endpoint-url>",
      "transport": "<transport-type>",
      "auth": {
        "type": "<auth-type>",
        "credentialRef": "<credential-reference>"
      }
    }
  }
}
```

**Field details**:

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `url` | yes | - | Endpoint URL |
| `transport` | no | `streamable-http` | Transport type |
| `auth` | no | - | Auth hints (no cleartext credentials) |
| `auth.type` | no | `none` | Auth type (e.g., `none`, `bearer`, `mtls`) |
| `auth.credentialRef` | no | - | Reference to Secret or ServiceBinding path |

## Examples

### Gateway + individual servers (with extended fields)

```json
{
  "mcpServers": {
    "gateway": {
      "url": "http://mcp-gateway-broker.mcp-system:8080/mcp",
      "transport": "streamable-http"
    },
    "weather-tool": {
      "url": "http://weather-tool-service.team1:8080/mcp",
      "transport": "streamable-http"
    },
    "github-tool": {
      "url": "http://github-tool-service.team1:8080/mcp",
      "transport": "streamable-http",
      "auth": {
        "type": "bearer",
        "credentialRef": "/bindings/model-access/api-key"
      }
    }
  }
}
```

### No servers configured

```json
{
  "mcpServers": {}
}
```

### Partial resolution (some references failed)

```json
{
  "mcpServers": {
    "weather-tool": {
      "url": "http://weather-tool-service.team1:8080/mcp",
      "transport": "streamable-http"
    }
  }
}
```

In this case, any unresolved references are noted in AGENTS.md and an `MCPResolutionFailed` status condition is set on the AgentRuntime CR.

## Generation Rules

1. **Platform defaults**: If an MCP Gateway is configured at the platform or namespace level, add a `gateway` entry. Merged automatically without per-agent declaration.
2. **Direct URL references**: `spec.mcp.servers[]` entries with a `url` field are included as-is.
3. **Symbolic references**: `spec.mcp.servers[]` entries with `type` + `ref` are resolved by the registered resolver plugin for that type. Failed resolutions are omitted from the file.
4. **Label discovery**: The `label` resolver discovers Deployments with `kagenti.io/protocol=mcp` in the agent's namespace and adds entries for their Services.
5. **Empty state**: If no gateway, no direct URLs, and no tools discovered, the file MUST contain `{"mcpServers": {}}`.
6. **Regeneration**: Controller regenerates when AgentRuntime CR changes, MCP tool Deployments are created/deleted, or gateway config changes.
7. **No cleartext credentials**: Auth entries reference Secrets or ServiceBinding paths, never inline credentials.

## URL Convention

- Gateway: `http://<gateway-service>.<gateway-namespace>:<port>/mcp`
- Individual tool: `http://<tool-service>.<agent-namespace>:<port>/mcp`
- Transport: `streamable-http` (default for all Kagenti MCP tools)
