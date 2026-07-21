---
sidebar_label: Sandbox Agents
sidebar_position: 6
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# Sandbox Agents

Some agents run arbitrary code, rewrite their own files, and act without being asked. You want those agents contained so a mistake — or a prompt injection — can't reach the rest of your systems. Rossoctl's sandboxing (**OpenShell**) gives each agent a kernel-isolated execution environment with a policy-controlled egress.

## What the sandbox isolates

- **Kernel-level isolation** — Landlock, seccomp, and network namespaces restrict what the process can touch.
- **Egress policy** — an OPA/Rego policy decides which network destinations the agent may reach.
- **Zero-secret credentials** — the sandbox injects short-lived credentials at call time instead of mounting long-lived secrets.
- **Per-user ownership** — each sandbox is owned by the requesting user's identity.

## Enable and request a sandbox

Sandboxing is behind a feature flag:

```bash
rossoctl config set features.sandbox=true
```

Request an isolated environment for an agent with a `Sandbox` resource:

```yaml
apiVersion: rossoctl.dev/v1
kind: Sandbox
metadata:
  name: coding-agent
  namespace: team1
spec:
  agentRef: coding-agent
  egress:
    allow:
      - github.com
      - registry.rossoctl-system.svc
```

## When to use it

:::tip Rule of thumb
If an agent executes code it generated, edits a workspace, or runs unattended for long periods,
sandbox it. If it only calls a couple of read-only tools, you may not need to.
:::

:::warning
An egress policy is a security control, not a suggestion. Start from deny-all and add only the
destinations the agent genuinely needs.
:::

:::note For contributors
Expand from `kagenti/docs/sandbox-guide.md` and `kagenti/docs/agentic-runtime/*`. Confirm the `Sandbox`
CR shape, the `openshell` CLI's role, and the isolation layers list.
:::
