---
sidebar_label: CLI (rossoctl)
sidebar_position: 1
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# CLI Reference: `rossoctl`

`rossoctl` is the command-line interface for installing Rossoctl and managing agents, tools, and configuration. This page is a starter reference; run `rossoctl <command> --help` for the authoritative, up-to-date flags.

:::info Naming
The CLI is `rossoctl` on this site. During the rename it may still be distributed as `kagenti`; the
subcommands map one-to-one.
:::

## Common commands

| Command | Does |
|---------|------|
| `rossoctl install` | Install the platform (`--local`, `--openshift`, `--with-*`) |
| `rossoctl status` | Show platform health |
| `rossoctl login` | Authenticate via Keycloak |
| `rossoctl agent deploy` | Deploy an agent (image or `--source`) |
| `rossoctl agent list` | List agents in a namespace |
| `rossoctl agent describe` | Show an agent's status, revision, tools |
| `rossoctl agent connect` | Connect an agent to a tool |
| `rossoctl agent chat` | Open a chat session with an agent |
| `rossoctl agent hibernate` / `wake` | Pause / resume an agent |
| `rossoctl tool deploy` | Deploy an MCP tool |
| `rossoctl apply -f` | Apply a resource manifest |
| `rossoctl config set` | Set a configuration value or feature flag |
| `rossoctl ui open` | Open the dashboard |

## Global flags

| Flag | Meaning |
|------|---------|
| `--namespace, -n` | Target namespace |
| `--all-namespaces` | Operate across namespaces |
| `--output, -o` | Output format (`table`, `json`, `yaml`) |

## Example

```bash
rossoctl login
rossoctl agent deploy orders-agent --source https://github.com/my-org/orders-agent -n team1
rossoctl agent connect orders-agent --tool ticketing -n team1
rossoctl agent chat orders-agent -n team1
```

:::note For contributors
Generate this table from `rossoctl --help` output once the CLI stabilizes, and keep it in sync. Confirm
which verbs exist today vs. planned (some, like `hibernate`/`promote`, may be roadmap).
:::
