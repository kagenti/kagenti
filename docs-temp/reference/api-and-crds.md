---
sidebar_label: API & Custom Resources
sidebar_position: 2
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# API & Custom Resources

Rossoctl is driven by Kubernetes custom resources, so you can manage everything declaratively and with GitOps. This page lists the main resources and their purpose; field-level schemas belong in each resource's generated CRD reference.

:::info Naming
Resources on this site use the `rossoctl.dev` API group. During the rename, live clusters may still use
`kagenti.dev` / `agent.kagenti.dev`. Field shapes are the same; only the group name differs.
:::

## Core resources

| Kind | Group/Version | Purpose |
|------|---------------|---------|
| `AgentRuntime` | `rossoctl.dev/v1` | Enrolls and manages an agent workload |
| `MCPServerRegistration` | `rossoctl.dev/v1` | Registers an MCP tool with the gateway |
| `Sandbox` | `rossoctl.dev/v1` | Requests an isolated (OpenShell) execution environment |
| `ToolAccessPolicy` | `rossoctl.dev/v1` | Grants an agent scoped access to a tool |

## Example: `AgentRuntime`

```yaml
apiVersion: rossoctl.dev/v1
kind: AgentRuntime
metadata:
  name: orders-agent
  namespace: team1
spec:
  image: ghcr.io/my-org/orders-agent:1.3.0
  replicas: 2
  env:
    - name: LLM_MODEL
      value: llama3.1
```

## Platform API

The platform also exposes a REST API (used by the CLI and UI) secured with OAuth2 bearer tokens and the `rossoctl-viewer` / `rossoctl-operator` / `rossoctl-admin` roles — see [Authentication](../security/authentication.md).

:::note For contributors
Replace this with generated CRD docs (fields, defaults, validation) once the `rossoctl.dev` API group is
published. Confirm the real kinds against `kagenti/docs/components.md` (`AgentRuntime`,
`MCPServerRegistration`, `Sandbox`); `ToolAccessPolicy` is illustrative and needs confirmation.
:::
