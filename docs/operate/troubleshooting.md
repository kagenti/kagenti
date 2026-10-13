---
title: Troubleshooting
description: The failures that occur most often, and the recovery for each one.
sidebar_position: 6
---

This page has two parts. The first part is the laptop install of Cortex. The second part is the
Kubernetes platform. If your condition is not here, ask in
[Slack](https://ibm.biz/rossoctl-slack), or open an issue on
[rossoctl/rossoctl](https://github.com/rossoctl/rossoctl/issues).

## On a laptop

These conditions occur with the laptop install from
[Quickstart on a laptop](../get-started/laptop.md). You do not need a Kubernetes cluster for this
part.

<!-- VERIFY: verified against v0.8.1 — the CA path (~/.cortex/ca/ca.crt), the port (47600), the
     launchd label (io.rossoctl.cortex) and the systemd unit (cortex.service) all match
     cmd/agentop. The install itself is still a release target; see cortex#944 and cortex#945. -->

### The certificate authority is not trusted

Your agent reports a TLS error, or a certificate error, when it calls the model. The cause is that
the agent does not trust the certificate of RossoCortex.

Cortex writes its certificate authority to `~/.cortex/ca/ca.crt`. The `--claude-code` install
configures Claude Code for you. For another agent, `agentop exec` sets the certificate variables.
IBM Bob is different: it trusts the CA through the System keychain, and `agentop configure bob
enable` prints the `sudo` command that adds it, which you run yourself. See
[Other agents](../get-started/laptop.md#other-agents).

To confirm the certificate, read it:

```bash
openssl x509 -in ~/.cortex/ca/ca.crt -noout -subject -dates
```

If the file is absent, the proxy has not started since the CA files were removed. The proxy writes
the CA when it starts:

```bash
agentop service restart
```

<!-- VERIFY: verified against v0.8.1 and main — the proxy calls tlsbridge.EnsureFileSource on boot
     (cmd/cortex/main.go), which mints a new CA if any of tls.crt, tls.key or ca.crt is missing
     (core/tlsbridge/ca.go:221-231). No setup or install step writes the CA; install.sh and
     `agentop service status` do read it. -->
<!-- VERIFY v0.9.0: agentop setup (cortex#1245) is not in v0.8.1; it does not touch the CA either,
     so a restart remains what regenerates it. -->

This makes a new CA, so restart your agent afterwards. If you trusted the old CA in a keychain, for
Bob or for a Go program, run that command again for the new one. If `agentop service status`
reports no service, run `agentop service install`.

If the file is present and your agent still rejects it, check whether a *second* Cortex install is
answering on the port. Every install generates a CA with the same subject, so the certificate you
read here can look correct while your agent is being served by a different one. See
[Two installs on one machine fight over the ports](#two-installs-on-one-machine-fight-over-the-ports).

### The port 47600 is already in use

The install or the service reports that the port is in use. RossoCortex binds five loopback ports,
all on `127.0.0.1`: 47600 for the proxy, 47601 for the session interface, 47602 for the statistics,
47603 for the transparent listener and 47604 for the health endpoint.

Find the program that holds the port:

```bash
lsof -nP -iTCP@127.0.0.1:47600 -sTCP:LISTEN
```

If the program is a previous Cortex service, stop it with `agentop service stop`. If it is another
program, stop that program, or change the ports of Cortex.

If the program is *another Cortex install*, read
[Two installs on one machine fight over the ports](#two-installs-on-one-machine-fight-over-the-ports)
instead: the port is the symptom, and stopping the wrong one of the two costs you the rest of the
day.

The installer reports another program even when the program is the Cortex service:

```text
error: port 47600 is already in use by something else. Free it, or change the ports in /Users/you/.cortex/config.yaml, then re-run.
```

The installer reports this message only when it finds no file at `~/.cortex/config.yaml`. With
that file present, the installer continues past the port check. The installer reads that path from
the `HOME` variable of your shell, so a shell with a different `HOME` reads a different directory.
The installer then does not recognize its own service.

An install that you re-run from its own `HOME` adopts the Cortex that holds the ports. It reads the
process identifier from `~/.cortex/proxy.pid`, stops that process, and starts it again under the
supervisor. An install under a different `HOME` reads a different `proxy.pid`, so it adopts
nothing. It installs, and then it repeats a bind failure and a restart. Read
[Two installs on one machine fight over the ports](#two-installs-on-one-machine-fight-over-the-ports).

Run `agentop service status` from the shell that installed the service to confirm that the service
is installed. That command reads `$HOME` too, so another shell reports `not installed`. It does not
tell you which install holds the port, because it asks the port rather than the supervisor. To stop
the service, read
[You must stop the service to run Cortex yourself](#you-must-stop-the-service-to-run-cortex-yourself).

### Two installs on one machine fight over the ports

<!-- VERIFY: verified against v0.8.1 and main. All five ports come from the --local preset in
     cmd/cortex/local.go (47600 forward proxy, 47601 session API, 47602 statistics, 47603
     transparent listener, 47604 health); both that path and superviseMaxDelay moved in the
     authbridge-proxy → cortex rename. Confirmed against v0.8.1: a second install repeated the
     bind failure with restart_in growing 2s, 4s, 8s, 16s and then holding at 30s. `cortex
     --local` binds four of the five ports and skips the transparent listener; `cortex --config
     <file>`, which is how the service runs, binds all five and logs "transparent proxy listening
     addr=127.0.0.1:47603". The 30-second ceiling is the macOS supervisor's (superviseMaxDelay in
     cmd/cortex/supervise.go); the systemd unit runs without --supervise and instead retries every
     10s, giving up after 5 starts in 300s (cmd_service_platform.go:92-93,142-149). -->

**The ports are fixed, so two installs cannot coexist.** The `--local` preset pins every listener to
a literal port, not to a free one, so the second install to start never binds. This is the condition
to suspect whenever a *certificate* error and a *restart loop* appear together.

You have two installs if you have ever run the install script with a different `$HOME` — a sandbox, a
second checkout, a container that mounts your home directory — as well as the ordinary one.

**How it reads.** Two symptoms that look unrelated, from one cause:

- The service log, `~/.cortex/proxy.log`, repeats a bind failure and a restart. On macOS this
  repeats every 30 seconds and does not stop:

  ```
  level=ERROR msg="forward-proxy listen: listen tcp 127.0.0.1:47600: bind: address already in use"
  WARN supervisor: proxy exited; restarting ran=37ms err="exit status 1" restart_in=30s
  ```

  `restart_in` stays at `30s` rather than growing, because that is the backoff ceiling. The
  supervisor does not give up and does not say why it cannot win the port, so the loop looks like a
  crash rather than a conflict. On Linux the systemd unit runs without the supervisor. Its
  `proxy.log` holds only the bind failure. `journalctl --user -u cortex` shows the restarts: every
  10 seconds, giving up after 5 starts in 300 seconds, then the unit enters a failed state.

- Your agent reports a self-signed certificate, naming a corporate proxy or a private CA:

  ```
  API Error: Unable to connect to API: Self-signed certificate detected (SELF_SIGNED_CERT_IN_CHAIN).
  ```

  This one is the misleading half. The request reached the install that *won* the port, and that
  install signs with its own CA. Your agent was told to trust the *other* install's CA. Both
  certificates carry the same subject, `CN=authbridge-tls-bridge-ca`, so nothing in the error, and
  nothing in `openssl x509 -subject`, tells the two apart. Nothing is wrong with either certificate.

**Confirm it.** List every proxy process:

```bash
ps auxww | grep -E '/(cortex|authbridge-proxy) --' | grep -v grep
```

The proxy binary is `cortex`. In v0.7.0 and earlier it is `authbridge-proxy`. This section is about
a machine with both generations, so match either name.

Read the `--config` path, or the binary path, on each line: those are your installs. On macOS, one
supervisor plus one child on the same path is healthy, and a supervisor whose child keeps changing
PID is the starved one. On Linux, `ps` shows one `cortex` for each running install. The install
that lost has stopped, and `systemctl --user status cortex` shows its unit as failed.

:::caution[Do not read the PIDs as a timeline]
macOS recycles process IDs, so a five-digit PID is often *older* than a four-digit one. A supervisor
that has been looping since login shows a high PID, and the healthy install that started after a
reboot shows a low one. Use the `ps` start time, not the number.
:::

Then compare the certificate authorities by fingerprint. The subject is identical on both, so it
cannot tell them apart; the fingerprint is unambiguous:

```bash
openssl x509 -noout -fingerprint -sha256 -in ~/.cortex/ca/ca.crt
openssl x509 -noout -fingerprint -sha256 -in ~/sandbox/<name>/.cortex/ca/ca.crt
```

The CA your agent trusts must be the one belonging to the install that holds port 47600.

**Fix it by choosing one install.** Keep the one that is already serving, and point your agent at
its CA:

```bash
HTTPS_PROXY=http://localhost:47600 \
  NODE_EXTRA_CA_CERTS=$HOME/.cortex/ca/ca.crt claude -p "say hi"
```

Or keep the other one. Stop the service, stop any stray proxy by PID, and start the install you
want:

```bash
agentop service stop        # HOME set to the install that holds the port; abctl service stop on v0.7.0
kill <pid> <pid>            # each stray proxy from the ps output; on macOS, its supervisor
agentop service install     # from the install you are keeping
```

There is one service label per user, so `agentop service stop` stops whichever install holds it —
which need not be the one that holds the port. The `kill` and the `install` that follow still
converge on one install.

Re-run the two `openssl` commands afterwards: one install, one CA, one fingerprint your agent
trusts.

:::note[Go programs on macOS ignore `SSL_CERT_FILE`]
On macOS, a Go program such as `gh` or `go` reads only the keychain, so setting `SSL_CERT_FILE`
changes nothing for it. On Linux and in CI the variable works when it names the bundle,
`~/.cortex/ca/bundle.crt`. Usually you do not need to do anything: Cortex does not decrypt GitHub,
the Go module proxy or the package registries. If a Go program reports `x509: certificate signed by
unknown authority`, trust the CA in your login keychain:

```bash
security add-trusted-cert -k ~/Library/Keychains/login.keychain-db -p ssl ~/.cortex/ca/ca.crt
```

git, curl and Python read their variables on macOS too.
:::

### You must stop the service to run Cortex yourself

<!-- VERIFY: confirmed against a v0.8.1 install on macOS, with the output copied from a
     terminal. The stop output; the plist path; the print-disabled format below; that a stop
     disables the label and boots it out of the domain; that an uninstall removes the plist and
     LEAVES that disable in place; that a later install clears it (the label read "disabled"
     before an install and "enabled" after it); the port message from the preflight loop in
     scripts/install.sh, and that it depends on $HOME/.cortex/config.yaml; and that a second
     install under a different HOME adopts nothing and repeats a bind failure instead. The
     tables also agree with controlService, loadService and unloadService in
     cmd/agentop/cmd_service_platform.go. -->
<!-- VERIFY v0.9.0: one claim is still unconfirmed by observation — that a stop survives a
     LOGIN. Testing it needs a logout. It is read from the launchctl disable that `stop` writes,
     which persists in the per-user disabled database. -->

`agentop service` controls the supervisor of your operating system. On macOS it controls
`launchd`. On Linux it controls `systemd`. To run your own Cortex process, stop the service first.
The service holds port 47600, and two programs cannot hold one port.

```bash
agentop service stop
```

The command states the result, and the command that undoes it:

```text
Stopped, and it will stay stopped across logins.
  agentop service start
```

A stop persists. Cortex does not run again at your next login, and it does not run again after you
restart the computer.

If you installed with `--claude-code`, Claude Code fails while the proxy is not running. That
install fixes the proxy address in the environment of Claude Code, and Claude Code cannot use a
direct connection instead. To remove that dependency, run `agentop configure claude-code disable`.
An install without `--claude-code` configures no agent, so a stop affects only the agents that you
pointed at the proxy yourself.

#### What each command does to the supervisor

On macOS, the service is the `launchd` label `io.rossoctl.cortex`, in the `gui/<uid>` domain.

| Command | What it does on macOS |
| --- | --- |
| `agentop service stop` | Runs `launchctl bootout`, and then `launchctl disable`. |
| `agentop service start` | Runs `launchctl enable`, which clears the disable, and then loads the label and starts it. |
| `agentop service restart` | Boots out the label, and then loads it and starts it again. This also runs `launchctl enable`, so it clears the disable. |
| `agentop service uninstall` | Runs `launchctl bootout`, and removes the `plist` file from `~/Library/LaunchAgents`. |

A stop needs both steps. `launchctl bootout` removes the job from the running domain, and the `plist`
file stays in `~/Library/LaunchAgents`. Launchd reads that file again at your next login, and Cortex
starts again. `launchctl disable` writes to the disabled database of your user account, and that
database persists.

`agentop service install` also runs `launchctl enable`. A disable from an earlier stop therefore
blocks no later install, and no later start.

On Linux, the service is the `systemd` user unit `cortex.service`.

| Command | What it does on Linux |
| --- | --- |
| `agentop service stop` | Runs `systemctl --user disable --now cortex.service`. |
| `agentop service start` | Runs `systemctl --user enable --now cortex.service`. |
| `agentop service uninstall` | Disables the unit, removes the unit file, and undoes the lingering that `agentop` enabled. |

Both platforms give one meaning to a stop: the service stays stopped until you start it.

#### Confirm that the service is stopped

Ask the supervisor, and not the port. On macOS, read the disabled database:

```bash
launchctl print-disabled gui/$(id -u) | grep io.rossoctl.cortex
```

A service that you stopped reports the disable:

```text
"io.rossoctl.cortex" => disabled
```

The command prints nothing when the label has no entry in that database, which means that you did
not stop the service.

On Linux, ask `systemd`. A service that you stopped reports `disabled`:

```bash
systemctl --user is-enabled cortex.service
```

:::caution[`agentop service status` can report `healthy` after a stop]
The `healthy` line of that command is a request to the health port. It is not a question to the
supervisor, so any program that holds the port answers it. With a second Cortex install on the
machine, the command reports `healthy` immediately after you stop your service, because the other
install replies. Read
[Two installs on one machine fight over the ports](#two-installs-on-one-machine-fight-over-the-ports).

The rest of that output stays reliable. `agentop service status` reads the unit file, so the
`installed` line and the `not installed` line both state the truth.
:::

:::note
`agentop service uninstall` removes the service, and it keeps your data. Your configuration and your
certificate authority stay in `~/.cortex`.
:::

### The service does not start, or starts and stops

Read the status first:

```bash
agentop service status
```

On macOS, the service runs under `launchd`. On Linux, it runs under `systemd`. The service writes
its own output to `~/.cortex/proxy.log`:

```bash
tail -n 50 ~/.cortex/proxy.log
```

On Linux, systemd's own lines about the service — the restarts, and a unit that gave up — are in
`journalctl --user -u cortex`. A service that starts and then stops usually has a port conflict,
or a certificate that it cannot write. The log gives the cause.

### Another program stopped working

If `git`, `gh` or `curl` stops working after you install Cortex, the cause is a proxy or a
certificate variable in your environment. The most likely one **replaces** a trust store —
`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` or `GIT_SSL_CAINFO` — and points at
`~/.cortex/ca/ca.crt`. That file holds only the Cortex CA, so every other host fails to verify.
Those variables need `~/.cortex/ca/bundle.crt`, which holds the Cortex CA and the platform roots.

Cortex configures only your agent. It does not set a global proxy. Examine your shell profile and
your environment for a proxy or certificate variable that you did not intend:

```bash
env | grep -iE "PROXY|CA_CERT|CA_BUNDLE|SSL_CERT|SSL_CAINFO"
```

Remove the value that is not correct, and open a new terminal. See the tool-compatibility work in
cortex#946 and cortex#947.

### No events appear, though the agent runs

The agent runs, but `agentop observe` shows no events. Check each cause in order:

1. **The service does not run.** Run `agentop service status`. Read the caution in
   [Confirm that the service is stopped](#confirm-that-the-service-is-stopped) first: the `healthy`
   line probes the port, so another install answers it.
2. **The agent does not use the proxy.** For an agent that is not Claude Code, confirm that you set
   the proxy variable and the certificate variables. `agentop exec` sets both. For IBM Bob,
   `agentop configure bob enable` sets the proxy, and the CA needs the `sudo` command that it
   prints. See [Other agents](../get-started/laptop.md#other-agents).
3. **A second install holds the ports.** Your agent then reaches the install that won the port,
   while you watch the other one. Read
   [Two installs on one machine fight over the ports](#two-installs-on-one-machine-fight-over-the-ports).
4. **The agent sends no traffic yet.** Send a message to the agent, and watch for the events.

### The numbers are wrong or absent

- **The token count is zero.** RossoCortex reads the token counts from the reply of the model. A
  reply that Cortex cannot parse gives no counts. Confirm that the model is an OpenAI-compatible or an
  Anthropic endpoint.
- **The cost is blank, but the tokens are correct.** Cortex has no rate for that model, so it shows
  no cost rather than a misleading zero. See
  [Read the cost](../get-started/reading-the-numbers.md#read-the-cost).
- **The pruning figure is zero.** The agent has no tool definitions to remove, or you did not enable
  pruning. See [Read the pruning savings](../get-started/reading-the-numbers.md#read-the-pruning-savings).

### A figure looks wrong, but it is correct

<!-- VERIFY: verified against v0.8.1 (cmd/agentop/tui) — the em-dash rule, the narrow-terminal drop
     of the money columns, the SAVED~ marker and the precision rule all hold. The `$0.00` answer
     describes current behaviour; cortex#1046 would change it, and is open. -->

These conditions are the display that Cortex intends. Each one reads as a defect, and each one is
not.

**A cell shows an em dash (`—`) instead of a number.** An em dash means that Cortex holds no figure.
It does not mean zero. In the `COST` column, the model has no entry in the rate table, so Cortex shows
no cost rather than a wrong zero. In the `CONTEXT` column, Cortex has not read a turn for that
session yet.

**The `COST` and `SAVED~` columns are absent.** Your terminal is narrower than 97 columns. Cortex
removes both money columns rather than round a charge below one cent to `$0.00`. Make the terminal
wider, and both columns return.

**The sessions table adds up to less than `TODAY`.** The session store is in memory, so the table
reaches back only to the start of the current service process. `TODAY` reads from the cost ledger on
disk, and it survives a restart. A table that adds up to less than the band is therefore correct
after you restart the service.

**Three of the four spend cells show `—`.** `TODAY`, `7 DAYS` and `MONTH` read from the cost ledger.
A local install holds that ledger. Kubernetes does not hold it by default, so those three periods have
no figure. `LAST 1H` reads from memory, and it always has one.

**A spend cell carries a time, such as `TODAY 7m`.** The figure is seven minutes old, because the
data for that cell stopped arriving. Each cell polls on its own schedule, so the age belongs to the
cell.

**A figure carries `~`, `+` or `!`.** Each marker states what Cortex cannot state exactly: `~` is an
estimate, `+` is a floor, and `!` is short by an amount that Cortex cannot measure. See
[What a marker on a figure means](../get-started/reading-the-numbers.md#what-a-marker-on-a-figure-means).

**One request costs `$0.000038`, and the session shows `<$0.01`.** The two surfaces use two
precisions. The events table gives four decimals for one request. Every other surface gives cents,
because you read those figures down a column. See
[How precise a money figure is](../get-started/reading-the-numbers.md#how-precise-a-money-figure-is).

**The context gauge is almost empty, and the agent is busy.** The gauge follows your conversation
only. Claude Code sends the subagents that it starts, and its own short internal calls, under the same
session identifier. Cortex excludes both from the gauge.

### Where the logs are, and what to attach to a bug report

The service log is `~/.cortex/proxy.log`. To attach a useful report to an issue, include:

- The output of `agentop --version`.
- The output of `agentop service status`.
- Your operating system and your architecture (`uname -sm`).
- The name of your agent, and the model.
- The last part of the service log, with any secret removed.

Open the issue with the **Laptop feedback** form on
[rossoctl/cortex](https://github.com/rossoctl/cortex/issues/new/choose). The form asks for each item
in the list above.

## On Kubernetes

The rest of this page is the Kubernetes platform.

### During the installation

#### The installation reports "exceeded its progress deadline"

The usual cause is a slow image download, and not a defect. Find the deployment that did not start, and
run the installer again:

```bash
kubectl get deployments --all-namespaces
```

Add the `--preload-images` option to the next installation. The script then downloads the images first,
which avoids the rate limits of Docker Hub.

#### You use Podman and not Docker

The installer needs a `docker` command on your path.

```bash
sudo ln -s /opt/podman/bin/podman /usr/local/bin/docker
brew install docker-credential-helper
```

If Keycloak reports insufficient memory, give the machine more memory:

```bash
podman machine stop
podman machine set --memory=12288 --cpus=8
podman machine start
```

To start again with a new machine:

```bash
podman machine rm -f
podman machine init --rootful --memory 18432 --cpus 6
podman machine start
```

To delete the cluster and keep the Podman machine:

```bash
kind delete cluster --name rossoctl
```

#### A build pod stays in `Pending` with `Insufficient cpu`

The node has insufficient CPU. The platform pods alone can request almost 4 CPUs.

Give the runtime 6 CPUs and create the cluster again, or deploy each agent from an image and not from
source. See [Machine size](index.md#machine-size).

#### The console shows an empty page on macOS

If **Content & Privacy Restrictions** are active, the console can show an empty page. The setting is in
System Settings, then Screen Time, then Content & Privacy Restrictions.

Disable the restrictions, and then restart the console:

```bash
kubectl rollout restart -n rossoctl-system deployment rossoctl-ui
```

#### The SPIRE DaemonSets report 0 ready

```bash
kubectl get daemonsets -n zero-trust-workload-identity-manager
```

No feature that needs a workload identity operates until these DaemonSets are ready. Examine the pods for
a scheduling failure or an image download failure, and confirm that the node has capacity.

### When you deploy an agent or a tool

#### `Init:ErrImagePull` or `Init:ImagePullBackOff`

In almost all cases, your GitHub token is expired:

```
failed to authorize: failed to fetch oauth token: unexpected status from GET request to
https://ghcr.io/token?scope=repository%3Arossoctl%2F...: 403 Forbidden
```

Examine your [personal access token](https://github.com/settings/personal-access-tokens/). It needs the
`repo`, `write:packages` and `read:packages` permissions.

A 403 status from `ghcr.io` during the installation of a chart is usually a stored credential that is no
longer valid:

```bash
docker logout ghcr.io
docker login ghcr.io -u <your-github-username>
```

#### You must change a value in `.secrets.yaml`

The installer copies each secret into the namespaces. A change to the file is therefore not sufficient.
Delete the Secret in each namespace that received it, and then run the installer again:

```bash
kubectl get secret --all-namespaces
kubectl -n team1 delete secret github-token-secret
scripts/kind/setup-rossoctl.sh
```

### During operation

#### The chat page reports the status 503

The console shows this message:

```
An unexpected error occurred during A2A chat streaming: HTTP Error 503:
Network communication error: peer closed connection without sending complete message body
```

The log of the agent shows a `ConnectionResetError` message or a `ProtocolError` message.

The agent cannot reach its model. If the agent uses Ollama, the `ollama serve` command is almost certainly
not active:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

If the agent does not use Ollama, examine the model configuration of the agent:

```bash
kubectl exec -n team1 <agent-pod> -- env | grep LLM_
```

#### A service stops responding

This condition occurs with Keycloak and with the console. Restart the data plane:

```bash
kubectl rollout restart daemonset -n istio-system ztunnel
kubectl rollout restart -n rossoctl-system deployment http-istio
```

#### A cluster returns 503 after you suspend the computer

**The condition.** Each address on `*.localtest.me:8080` returns the status 503 with the message
`upstream connect error ... connection termination`. Each pod is in the `Running` state, the gateway
reports `1/1`, and the `HTTPRoute` and `Gateway` resources report `Accepted`.

**The cause.** You suspended the computer for longer than the lifetime of a SPIRE identity document. The
Istio ambient data plane, which is ztunnel and the waypoints, continues to present expired certificates.
It does not read new certificates.

**To confirm the cause:**

```bash
kubectl logs -n istio-system -l app=ztunnel --tail=100 \
  | grep -iE "certificate expired|CertificateExpired"

kubectl logs -n spire-system -l app.kubernetes.io/name=agent --tail=100 \
  | grep -iE "reattest|service account token has expired"
```

**To recover:**

```bash
scripts/k8s/mesh-recover.sh --fix
```

Without the `--fix` option, the script reports the condition and prints the commands. It makes no change.

**To detect the condition before an outage,** run the script without the `--fix` option at a regular
interval. It exits with the code 4 when the first identity document expires in less than
`CERT_WARN_SECONDS`, which is 6 hours by default. The script needs `kubectl` access and `jq`. On Kind you
can also enable the `meshSelfHeal` feature flag, which adds a CronJob that does the restart.

**Expect this condition on a development cluster.** After a long suspension, you must restart the
data plane or create a new cluster. The cause is an upstream defect:
[istio/ztunnel#1679](https://github.com/istio/ztunnel/issues/1679).

#### Keycloak reports a connection error to its database

This condition occurs after the cluster runs for one day or longer. The cause is not completely
understood. For the investigation, see
[rossoctl#115](https://github.com/rossoctl/rossoctl/issues/115).

There is no reliable method to restart the database and Keycloak. The only reliable method is a new
installation of Keycloak:

```bash
helm uninstall keycloak -n keycloak
scripts/kind/setup-rossoctl.sh

kubectl rollout restart daemonset -n istio-system ztunnel
kubectl rollout restart -n rossoctl-system deployment http-istio
kubectl rollout restart -n rossoctl-system deployment rossoctl-ui
```

You must then restart each agent, so that each agent gets its Keycloak client again.

#### The operator cannot authenticate to Keycloak

This condition occurs after you change the administrator credentials. The operator holds the credentials
in memory. Restart it:

```bash
kubectl rollout restart deployment/rossoctl-controller-manager -n rossoctl-system
```

To confirm the result:

```bash
POD=$(kubectl get pod -n rossoctl-system -l control-plane=controller-manager \
  -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n rossoctl-system "$POD" -c manager | grep -i "keycloak\|auth" | tail -5
```

#### SPIFFE authentication reports an audience error or an issuer error

The `aud` claim of the identity document must be exactly `keycloak.publicUrl/realms/<realm>`. It must be
the **external** address. Keycloak has the public address in its issuer configuration, and the check is a
comparison of two strings. The internal address of the service reaches the same server and still fails.

Examine the `keycloak.publicUrl` value in your Helm values. See
[Authentication modes](../security/authentication-modes.md#the-audience-must-be-the-public-address).

#### The Skills entry does not appear in the console

The feature flag is not set. Enable it without a new installation:

```bash
helm upgrade rossoctl charts/rossoctl -n rossoctl-system \
  --reuse-values --set featureFlags.skills=true
```

Then confirm that the backend registered the routes:

```bash
kubectl logs -n rossoctl-system -l app.kubernetes.io/name=rossoctl-backend \
  | grep "skills routes registered"
```

### Commands for diagnosis

```bash
# Each pod that is not correct, in each namespace
kubectl get pods --all-namespaces | grep -vE "Running|Completed"

# Each address and each credential
./.github/scripts/local-setup/show-services.sh

# The RossoCortex configuration of one agent
rossoctl agents authbridge get <agent>

# The environment of one pod
kubectl exec -n <namespace> <pod> -- env | sort

# The log of the RossoCortex sidecar
kubectl logs -n <namespace> <pod> -c authbridge-proxy

# The log of the operator
kubectl logs -n rossoctl-system -l control-plane=controller-manager -c manager --tail=100
```
