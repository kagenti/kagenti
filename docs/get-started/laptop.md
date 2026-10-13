---
title: Quickstart on a laptop
sidebar_label: Quickstart — laptop
description: Run RossoCortex as one program and see the traffic of your agent.
sidebar_position: 2
---

RossoCortex is the data plane of Rossoctl. It runs as one program on macOS or Linux. It is a proxy on the request path of your agent. It shows each model call, each tool call and each
agent message as it happens. You do not need Kubernetes.

The traffic stays on your computer. RossoCortex does not send it to Rossoctl or to any other service.

This procedure needs approximately 5 minutes.

## Before you start

You need:

- macOS or Linux, on amd64 or arm64.
- An agent. The installer configures [Claude Code](https://claude.com/claude-code) for you. Any agent
  operates. See [Other agents](#other-agents).

## Step 1: install the program

<!-- This install command is duplicated in the Cortex repository README:
     rossoctl/cortex -> README.md ("Quick start").
     Change both, or they drift - the --ref wording already did once. -->

```bash
curl -fsSL https://raw.githubusercontent.com/rossoctl/cortex/main/scripts/install.sh \
  | sh -s -- --claude-code
```

The script asks for your permission before it changes the settings of Claude Code. It then runs
RossoCortex as a background service. The service restarts after a failure and after you sign in again.

:::note
The address of the script is on the `main` branch, but the script then runs the copy from the most
recent release, so the command does not run unreleased code. To pin or override that, use `--ref`:
`--ref=vX.Y.Z` selects a release and `--ref=main` installs the unreleased tip. See
[Installing an unreleased build](https://github.com/rossoctl/cortex/blob/main/CONTRIBUTING.md#installing-an-unreleased-build).
:::

If the install fails, read [Troubleshooting](../operate/troubleshooting.md#on-a-laptop) first. It
covers a certificate that your agent does not trust, a port that another program holds, and a service
that does not start. If your condition is not there, go to [Give feedback](#give-feedback) — a pasted
error is exactly what the form asks for.

## Step 2: watch the traffic

Open two terminals. In the first terminal, run the viewer:

```bash
agentop observe
```

In the second terminal, run your agent:

```bash
claude
```

Use Claude Code in the normal way. There is no environment variable to set. The calls of the agent
appear in `agentop`.

In `agentop observe`, press `Enter` on a session to see its events. Press `Enter` on an event to see
its full content. Press `/` to filter the events by a text match. Press `q` to quit. To learn what
the filter matches, read [Read the numbers](reading-the-numbers.md#watch-a-session).

RossoCortex reads this traffic. It does not change the traffic until you enable a plugin that changes
it.

## Step 3: read the numbers

Each session shows a token count and a cost. To learn what each number means, and how to act on it,
read [Read the numbers](reading-the-numbers.md).

## Manage the service

```bash
agentop service status
agentop service stop
agentop service start
agentop service restart
agentop service uninstall
```

`agentop service` controls the supervisor of your operating system, which is `launchd` on macOS and
`systemd` on Linux. A stop persists across a login, and a start undoes it. An uninstall removes the
service and keeps your data: your configuration and your certificate authority stay in `~/.cortex`.
To set the service up again after an uninstall, run `agentop service install`.

To read what each command does to the supervisor, and to stop the service so that you can run your
own Cortex process, read
[You must stop the service to run Cortex yourself](../operate/troubleshooting.md#you-must-stop-the-service-to-run-cortex-yourself).

## Stop and remove

To stop the traffic for one session, quit `agentop observe` with `q` and stop your agent. RossoCortex
continues to run as a background service.

To stop the service, run `agentop service stop`. To remove it, run `agentop service uninstall`. Both
are in [Manage the service](#manage-the-service). The service holds no traffic after a stop. It
reads traffic again after you start it.

## Other agents

Any agent operates with RossoCortex. For the agents below, `agentop configure` sets the values for
you. `claude-code` and `bob` read them from `~/.cortex/config.yaml`.

<!-- VERIFY v0.9.0: once the release carrying cortex#1243 is out, switch the OpenCode paragraph
     below to `agentop configure opencode enable`, and say that enable/disable restart OpenCode's
     service, which interrupts its open sessions (it asks first, cmd_opencode.go:101-108). -->

| Agent | Command | What it changes |
| --- | --- | --- |
| Claude Code | `agentop configure claude-code enable` | The proxy and CA variables, and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, in the `env` block of `~/.claude/settings.json`. |
| IBM Bob | `agentop configure bob enable` | The `http.proxy` key in Bob's `settings.json` (macOS). It prints a `sudo` command that trusts the CA in the System keychain, which you run yourself. Restart Bob afterwards. |
| Bob Shell | `agentop configure bobshell enable` | A `bob` function in `~/.zshrc` or `~/.bashrc` that runs Bob Shell through `agentop exec`. This is separate from the IBM Bob row. |

Each one takes `disable` to undo the change and `status` to report what is set. Run
`agentop configure <agent> --help` for the detail.

Codex reads only its environment. Run it with `agentop exec -- codex`. Nothing persists after the
command ends.

OpenCode sends its traffic from one background service. The first `opencode` starts that service,
and later ones reuse it. It keeps the environment that it started with. So
`agentop exec -- opencode` routes OpenCode only if no OpenCode service runs yet. `opencode service
status` tells you. The service then stays on Cortex after the command ends, until it restarts.

For an agent that is not listed, run it with `agentop exec -- <agent>`. That sets the proxy and the
CA variables, each with the right file. To see them, run `agentop exec --print`. To set them
yourself:

- `HTTP_PROXY`, `HTTPS_PROXY`, `http_proxy` and `https_proxy` set to `http://localhost:47600`
- `NODE_EXTRA_CA_CERTS` set to `$HOME/.cortex/ca/ca.crt`
- `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` and `GIT_SSL_CAINFO` set to
  `$HOME/.cortex/ca/bundle.crt`

The last four **replace** the trust store rather than adding to it, so they need the bundle — the
bridge CA together with the platform roots. Pointed at `ca.crt`, a program trusts only the Cortex CA,
and every host that Cortex does not bridge fails to verify.

:::note[Go programs on macOS ignore `SSL_CERT_FILE`]
On macOS, a Go program such as `gh` or `go` reads only the keychain. Usually you do not need to do
anything: Cortex does not decrypt GitHub, the Go module proxy or the package registries. If a Go
program reports `x509: certificate signed by unknown authority`, trust the CA in your login keychain:

```bash
security add-trusted-cert -k ~/Library/Keychains/login.keychain-db -p ssl ~/.cortex/ca/ca.crt
```

git, curl and Python read their variables on macOS too.
:::

To run agents against a cluster rather than this laptop, read
[Install the cluster CLI](cli.md).

## Next

- To understand the numbers that `agentop observe` shows, read [Read the numbers](reading-the-numbers.md).
- To reduce the token cost of your agent, read
  [Cost control](../concepts/experiments/cost-control.md).
- To make large tool output smaller, read
  [Context compaction](../concepts/experiments/context-compaction.md).
- To understand the program that you installed, read [RossoCortex](../concepts/core/cortex.md).
- To get deployment, discovery and the web console, read [Quickstart on Kubernetes](kubernetes.md).

## Give feedback

:::info[Tell us when it breaks]

Cortex on a laptop is new. Report an install that failed, a figure that looked wrong, or a step that
was not clear.

Read [Troubleshooting](../operate/troubleshooting.md#on-a-laptop) first. It covers the most frequent
conditions, and it answers a set of figures that look wrong and are correct.

- Open the **Laptop feedback** form on
  [rossoctl/cortex](https://github.com/rossoctl/cortex/issues/new/choose)
- Or write a message in [Slack](https://ibm.biz/rossoctl-slack)

A half-finished install, with the error in the report, is more useful than a complete report that you
do not send.

:::
