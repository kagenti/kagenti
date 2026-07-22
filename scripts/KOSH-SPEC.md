# KOSH-SPEC: Kagenti OpenShell CLI Specification

## Overview

**Kosh** (Kagenti OpenShell) is a Python CLI that wraps NVIDIA's `openshell` binary and adds Kagenti-specific commands for managing sandboxed AI agent environments. It supports two runtime modes:

1. **Remote sandboxes** via OpenShell gateway (containers managed by the gateway server)
2. **Local sandboxes** via macOS `sandbox-exec` (sandboxed shell processes on the host)

## Architecture

```
                     +-----------------+
                     |    kosh.py      |  Click CLI (Python 3.12+, uv inline deps)
                     +--------+--------+
                              |
         +--------+-----------+-----------+--------+
         |        |           |           |        |
    sandbox    teleport     pull     local-sandbox  allow/deploy/...
    (group)    (Python)    (Python)     (-> sandbox.sh)
         |        |           |
    +----+---+ +--+--+   +---+---+
    |openshell| |upload|  |tarball|
    |  CLI    | |+exec |  |+download|
    +---------+ +-----+  +--------+
```

## Components

| File | Purpose |
|------|---------|
| `kosh.py` | Main CLI entry point (Click + uv inline metadata) |
| `teleport.sh` | **Deprecated stub** — prints message to use `kosh teleport` |
| `sandbox.sh` | macOS sandbox-exec wrapper for local shells |
| `agent-sandbox.sb` | macOS SBPL sandbox profile |
| `litellm_sandbox_policy.yaml` | OpenShell network/filesystem policy for remote sandboxes |
| `kagenti-teleport-setup.py` | Self-contained setup script (downloads kosh, configures gateway, OIDC login) |
| `kosh-release.py` | Stable release tag management and channel sync |
| `deploy-kosh-user-namespace.py` | Automated OpenShell tenant deployment on OpenShift (namespace, CA, Helm) |
| `sync-kagenti-teleport-setup.py` | Multi-channel (stable/dev) file sync to teleport setup server |
| `setup-kosh-completions.sh` | Shell completion setup for bash/zsh |
| `bob-install.sh` | Bob shell installer (tarball method, bypasses npm proxy issues) |
| `HOW_TO_KOSH_GITHUB.md` | Step-by-step guide for GitHub OIDC login via Keycloak |

---

## 1. kosh.py

**Invocation**: `uv run kosh.py <command> [args...]` or via alias `kosh <command>`

**Version**: 0.1.0-dev+{build_hash}

**Dependencies** (inline `uv` script metadata):
- `openshell` (Python SDK + CLI)
- `click>=8.0`

### Command Architecture

Uses a custom `KoshGroup` that delegates unknown subcommands to the `openshell` binary. Native kosh commands take priority; unrecognized names are checked against a passthrough allowlist.

### Sandbox Group

`kosh sandbox` is a Click Group (not a passthrough) with explicit subcommands for shell completion support:

```
create, get, list, delete, exec, connect, upload, download, ssh-config, provider, sb
```

All subcommands delegate to `openshell sandbox <subcmd> [args...]` with seccomp noise filtering.

### Passthrough Commands

These are forwarded directly to `openshell <cmd> [args...]` with PTY-based noise filtering:

```
gateway, status, forward, logs, policy, settings,
provider, inference, doctor, term, ssh-proxy
```

### Seccomp Noise Filtering

All openshell commands filter `DEBUG openshell_sandbox::sandbox::linux::seccomp` messages:
- **Non-interactive** (exec, list): threaded stdout+stderr filtering
- **Interactive** (connect, term): PTY with `pty.openpty()` + line-by-line filtering + SIGWINCH forwarding
- **Internal helpers** (`_openshell_exec`, `_openshell_pipe_stdin`): pipe both streams with pattern matching

### OpenShell Binary Resolution

`_find_openshell()` searches in order:
1. `<workspace>/.local/bin/openshell` (workspace-local install)
2. `shutil.which("openshell")` (PATH lookup)

### Native Commands

#### `kosh completions`

Generate shell completions for kosh.

| Argument | Values | Default | Description |
|----------|--------|---------|-------------|
| `SHELL` | `bash`, `zsh`, `fish` | `zsh` | Target shell |

#### `kosh teleport`

Set up and sync a project into a remote OpenShell sandbox. Implemented entirely in Python (`_teleport_impl()`).

| Option | Default | Description |
|--------|---------|-------------|
| `NAME` | last local sandbox | Positional: sandbox name, directory path, or `.` |
| `--directory, -d` | (hidden/deprecated) | Use positional argument instead |
| `--watch, -w` | off | After initial upload, watch for file changes and sync continuously |
| `--connect / --no-connect` | `--no-connect` | Connect to sandbox after setup |
| `--custom-image` | off | Build from Dockerfile.sandbox |
| `--model` | `claude-opus-4-6` (or `KOSH_MODEL` env) | Claude model for ANTHROPIC_MODEL |
| `--allow-profile` | (none) | Domain profile to apply after teleport (repeatable) |
| `--reapply-allowlist / --no-reapply-allowlist` | `--reapply-allowlist` | Reapply saved allowlists from config |

**Behavior**:
1. Resolves project directory (positional NAME, explicit path, or last local sandbox)
2. Creates sandbox if it doesn't exist (with litellm provider + policy)
3. One-time setup on create: pipes `.bashrc`/`.profile` via stdin, installs Bob shell
4. Uploads files via `openshell sandbox upload` (respects .gitignore, excludes sensitive files)
5. Stores path mapping in `metadata.json` for `kosh pull`
6. Applies domain profiles and saves to metadata
7. If `--watch`: polls every 2s for mtime changes, uploads individually
8. If `--connect`: opens `openshell sandbox connect`

**First run**: Create → wait ready → .bashrc → Bob install → upload (~60s)
**Subsequent runs**: Wait ready → upload only (~20s)

#### `kosh pull`

Pull files from a remote OpenShell sandbox back to local directory.

| Option | Default | Description |
|--------|---------|-------------|
| `NAME` | last teleported sandbox | Positional: sandbox name |
| `--dry-run` | off | Show what would change without writing |
| `--force` | off | Overwrite even git-dirty files |
| `--path` | (none) | Pull only a specific file or directory |

**Behavior**:
1. Lists remote files via `find` (filters sensitive patterns, `.git/`)
2. Detects git-dirty files locally (`git diff --name-only` + `--cached`)
3. Classifies: new, updated, dirty (skipped unless `--force`)
4. Creates tarball at `/sandbox/.kosh-pull.tar.gz` (handles binary files)
5. Downloads via `openshell sandbox download` (restricted to `/sandbox/` workspace)
6. Extracts locally, cleans up remote tarball

**Safety**: Git-dirty files never overwritten by default. Sensitive patterns excluded.

#### `kosh local-sandbox create`

Create a local macOS sandboxed environment.

| Option | Default | Description |
|--------|---------|-------------|
| `NAME` | (required, positional) | Sandbox name (used as directory name) |
| `--name` | (hidden/deprecated) | Use positional argument |
| `--model` | `claude-opus-4-6` | Claude model for ANTHROPIC_MODEL |

**Requires**: `ANTHROPIC_AUTH_TOKEN` environment variable.

#### `kosh local-sandbox connect`

Reconnect to an existing local sandbox.

| Option | Default | Description |
|--------|---------|-------------|
| `NAME` | last used (positional) | Sandbox name to connect to |

#### `kosh local-sandbox list`

List all registered local sandboxes with name, status, directory, and last-used marker.

#### `kosh local-sandbox delete`

Delete a sandbox directory and metadata entry.

| Option | Default | Description |
|--------|---------|-------------|
| `NAME` | (required, positional) | Sandbox to delete |

#### `kosh allow`

Manage domain allowlists for OpenShell sandboxes.

##### `kosh allow add`

| Option | Default | Description |
|--------|---------|-------------|
| `DOMAINS` | (positional) | Domains to allow (space or comma-separated) |
| `--sandbox, -s` | last used | Sandbox name |
| `--port, -p` | 443 | Port to allow |
| `--binary, -b` | claude + node + curl | Binary paths (repeatable) |
| `--all-binaries` | off | Allow for all binaries (no restriction) |
| `--no-wait` | off | Don't wait for policy reload |
| `--no-save` | off | Don't persist to config |
| `--from-file, -f` | (none) | Read domains from file |
| `--from-json, -j` | (none) | Read from JSON (`allow denied --json` output) |

##### `kosh allow denied`

Show domains denied by the sandbox proxy (OCSF logs).

| Option | Default | Description |
|--------|---------|-------------|
| `--sandbox, -s` | last used | Sandbox name |
| `--since` | `1h` | How far back to look |
| `--apply` | off | Immediately allow all denied domains |
| `--json` | off | Output as JSON list |

##### `kosh allow list`

Show allowed domains and applied profiles for a sandbox.

##### `kosh allow remove`

Remove domains from saved config (NOT from running sandbox — policy is additive-only).

##### `kosh allow reapply`

Reapply all saved profiles and domains to a sandbox.

##### `kosh allow profile` (subgroup)

- `kosh allow profile list` — List available profiles
- `kosh allow profile show <name>` — Show profile endpoints
- `kosh allow profile apply <name>` — Apply profile to sandbox
- `kosh allow profile create <name>` — Create user-defined profile
- `kosh allow profile delete <name>` — Delete user-defined profile

#### Built-in Profiles

| Profile | Domains | Description |
|---------|---------|-------------|
| `claude-infra` | api.anthropic.com, statsig.anthropic.com, sentry.io, platform.claude.com | Claude Code infrastructure |
| `web-search` | google.com, *.google.com, bing.com, duckduckgo.com, etc. | Search engines |
| `dev-tools` | github.com, stackoverflow.com, npmjs.com, pypi.org, readthedocs.io, etc. | Developer resources |
| `ibm-litellm` | ete-litellm.ai-models.vpc-int.res.ibm.com | IBM LiteLLM proxy |

#### `kosh login`

Authenticate with Kagenti API (Keycloak).

| Option | Description |
|--------|-------------|
| `--kagenti-url` | Kagenti backend URL |
| `--keycloak-url` | Keycloak URL |
| `--user` | Username |
| `--password` | Password |
| `--realm` | Keycloak realm (default: kagenti) |
| `--client-id` | Client ID (default: kagenti-cli) |

#### `kosh deploy agent/tool`

Deploy agents or tools via Kagenti API.

| Option | Description |
|--------|-------------|
| `--name` | Agent/tool name |
| `--namespace` | Target namespace |
| `--image` | Container image |
| `--protocol` | Communication protocol (a2a, streamable_http) |
| `--framework` | Agent framework (LangGraph, etc.) |
| `--port` / `--target-port` | Service ports |
| `--authbridge` | Enable AuthBridge (agents only) |
| `--spire` | Enable SPIRE identity (agents only) |

#### `kosh catalog agents/tools`

List deployed agents or tools from Kagenti API.

#### `kosh undeploy agent/tool`

Remove deployed agents or tools.

#### `kosh sync-openshell`

Sync local openshell CLI and kosh script versions to match the gateway.

### Configuration

Stored at `$XDG_CONFIG_HOME/kosh/` (defaults to `~/.config/kosh/`):

| File | Format | Purpose |
|------|--------|---------|
| `metadata.json` | JSON | Registry of sandboxes, paths, allowlists, applied profiles |
| `last_local_sandbox` | Plain text | Most recently used sandbox path |
| `profiles.json` | JSON | User-defined domain profiles |
| `kagenti_token.json` | JSON | Kagenti backend auth token |

**metadata.json**:
```json
{
  "sandboxes": {
    "my-project": {
      "path": "/Users/user/projects/my-project",
      "remote_path": "/Users/user/projects/my-project",
      "allowed_domains": [{"host": "custom-api.com", "port": 443}],
      "applied_profiles": ["dev-tools", "web-search"]
    }
  }
}
```

### Sandbox Boundary Model

- **Inside local sandbox**: `kosh` alias prints helpful message; ALL commands blocked
- **Inside remote sandbox**: Same — `kosh` alias explains to exit
- **From host terminal**: All commands work
- **Detection**: `KOSH_SANDBOX=1` and `KOSH_SANDBOX_DIR` env vars inside local sandboxes

### Sensitive File Patterns

Files matching these patterns are excluded from teleport upload and pull download:
```
.config/, openshell/, oidc_token.json, token.json,
edge_token.json, rossconfig.json, *.key, *.crt, *.pem
```

---

## 2. teleport.sh (deprecated)

Now a stub that prints:
```
NOTE: teleport functionality has moved into kosh.py
Use: kosh teleport <name>
```

All teleport logic lives in `_teleport_impl()` in kosh.py.

---

## 3. sandbox.sh

**Invocation**: `bash sandbox.sh <shell>` (e.g., `bash sandbox.sh zsh`)

macOS `sandbox-exec` wrapper that creates a hardened, isolated shell environment.

### Security Model

- **Deny-all default**: Everything blocked unless explicitly allowed
- **HOME redirection**: `HOME=<project_dir>` (not real home)
- **PATH filtering**: Only allows `/usr`, `/bin`, `/sbin`, `/opt/homebrew`, and project dir entries
- **Private temp**: Creates `.tmp/` in project dir; denies `/tmp`, `/private/tmp`, `/var/tmp`
- **Environment allowlist**: `env -i` with explicit variable passthrough
- **sandbox-exec shim**: Places a no-op `sandbox-exec` in PATH to prevent nested sandboxing
- **Boundary detection**: Sets `KOSH_SANDBOX=1` and `KOSH_SANDBOX_DIR` for kosh to detect

### Resource Limits

| Limit | Value | Purpose |
|-------|-------|---------|
| File size (`ulimit -f`) | 512 MB | Prevent runaway writes |
| Open FDs (`ulimit -n`) | 4096 | Node.js/libuv watchers |
| Max procs (`ulimit -u`) | 2048 (or `SANDBOX_MAX_PROCS`) | Fork bomb protection |

---

## 4. agent-sandbox.sb

macOS SBPL (Sandbox Profile Language) profile for `sandbox-exec`. Defines the security boundary for local sandboxes.

### Key Security Properties

- Agent cannot read files outside project directory
- Agent cannot modify its own Claude binary
- Agent cannot use `lsof` to inspect other processes
- Agent cannot access SSH keys or Docker unless explicitly opted in
- Network restricted to outbound + localhost binding

---

## 5. litellm_sandbox_policy.yaml

OpenShell sandbox policy for remote sandboxes. Defines filesystem and network access.

```yaml
version: 1
filesystem_policy:
  read_write: [/sandbox, /tmp, /Users]
network_policies:
  ibm_litellm:     # IBM LiteLLM proxy
  claude_code:     # Anthropic API, statsig, sentry, downloads, PyPI, COS, npm
  bob_install:     # Bob shell runtime (bob.ibm.com, COS, npm, *.npmjs.org)
  web_search:      # Google, Bing, DuckDuckGo
  web_fetch:       # GitHub, Stack Overflow, Wikipedia, npm, PyPI, ReadTheDocs (includes git binaries)
```

---

## 6. kagenti-teleport-setup.py

Self-contained setup script. Downloads all kosh files, configures gateway, performs OIDC login.

**Version tracking**: Prints `build {hash} ({date})` and channel (stable/dev) on startup.

**Steps**: Check uv → Check Python 3.12+ → Download files → Configure gateway → Install mTLS certs → OIDC login (PKCE with ROPC fallback) → Persist alias → Test

**Token staleness**: Checks `expires_at` in `oidc_token.json`; skips login if token valid (>60s remaining), refreshes if expired.

**Channels**: `--dev` flag downloads from `/dev/` path on server.

---

## 7. kosh-release.py

Manages the `kosh-release` git tag and stable channel sync.

```bash
python3 kosh-release.py              # Show status + commits
python3 kosh-release.py --set HEAD   # Tag current commit
python3 kosh-release.py --sync       # Sync stable from tag
python3 kosh-release.py --set HEAD --sync  # Both
```

The tag is never moved automatically — requires explicit `--set`.

---

## 8. deploy-kosh-user-namespace.py

Automated OpenShell tenant deployment script for OpenShift clusters. Handles all the pre-requisites and fixes that `deploy-tenant.sh` alone cannot resolve on HyperShift-hosted clusters.

**Invocation**: `uv run scripts/deploy-kosh-user-namespace.py <tenant-name> [options]`

| Option | Default | Description |
|--------|---------|-------------|
| `tenant` | (required) | Tenant namespace name (e.g., `aslom`, `team1`) |
| `--dry-run` | off | Print what would be done without executing |
| `--gateway-image` | (from values.yaml) | Override gateway image tag (e.g., `v0.0.56`) |
| `--skip-keycloak-check` | off | Skip waiting for Keycloak readiness |
| `--skip-helm` | off | Only apply pre-requisites, skip Helm deploy |

**Steps**:
1. Discover kubeconfig (`.kube/config-ykt1` or `$KUBECONFIG`)
2. Create namespace with pod-security labels
3. Create `config-trusted-cabundle` ConfigMap (needed before CA assembly)
4. Build combined trusted CA bundle (system CAs + ingress operator CA)
5. Check Keycloak readiness (gateway OIDC init fails without it)
6. Helm install/upgrade with `openshift.enabled=true`, route ingress, OIDC config
7. Auto-retry on certgen job failure (deletes stale job, retries Helm)
8. Verify gateway pod reaches 3/3 Ready state

**OpenShift fixes applied automatically**:
- `openshift.enabled=true` → SCC template + restricted securityContext
- `trustedCABundle` → mounted at `/etc/ssl/certs/ca-certificates.crt`
- Namespace labels for privileged pod security

---

## 9. sync-kagenti-teleport-setup.py

Syncs kosh files to the remote teleport setup server. Supports multi-namespace deployment and two channels (stable from GitHub, dev from local).

**Invocation**: `uv run scripts/sync-kagenti-teleport-setup.py [options]`

| Option | Description |
|--------|-------------|
| `--deploy` | Initial deployment (create Deployment, Service, Route, ConfigMap) |
| `--dev` | Sync dev channel (files stored with `dev--` prefix in ConfigMap) |
| `--status` | Check sync status only (no changes) |
| `--force` | Redeploy even if all files match (force restart) |
| `--namespace, -n` | Target namespace (default: `$OPENSHELL_NAMESPACE` or `team1`) |
| `--cluster` | Cluster name hint for kubeconfig discovery (e.g., `ykt1`) |
| `--skip-certs` | Skip certificate extraction (rewrite URLs only) |
| `--tag` | Sync from a specific git tag/ref |
| `--url` | Override route URL |

**Multi-namespace support**: The `--namespace` flag (or `OPENSHELL_NAMESPACE` env var) allows deploying the teleport setup server to any tenant namespace. The manifest's hardcoded `namespace: team1` is substituted at apply time.

**Certificate embedding**: Automatically extracts mTLS certificates from the target cluster's `cert-manager` namespace and embeds them into the served `kagenti-teleport-setup.py` so users can authenticate without manual cert configuration.

**Channels**:
- Stable: `https://<server>/kagenti-teleport-setup.py` (from GitHub `kosh` branch)
- Dev: `https://<server>/dev/kagenti-teleport-setup.py` (from local working tree)

---

## 10. HOW_TO_KOSH_GITHUB.md

Step-by-step guide for enabling GitHub as an identity provider for OpenShell gateway authentication via Keycloak. Covers:

1. Creating a GitHub OAuth App (with Device Flow for CLI)
2. Configuring Keycloak GitHub IdP in the `openshell` realm
3. Attribute mappers for auto-importing name/email from GitHub
4. Group-based access control (`openshell-users` group)
5. Pre-authorizing users via Keycloak Admin API
6. Testing login via browser and kosh CLI
7. Optional org-gated login (custom Keycloak image for `kaslomorg` membership check)

---

## Model Configuration

Default model: `claude-opus-4-6` (override via `KOSH_MODEL` env or `--model` flag)

LiteLLM base URL: `https://ete-litellm.ai-models.vpc-int.res.ibm.com`

---

## Dependencies

- **Python 3.12+** with `uv` (for inline script dependencies)
- **openshell CLI** (`uv tool install -U openshell` or auto-resolved)
- **macOS** (for local sandbox mode via `sandbox-exec`)
- **Docker** (optional, for custom sandbox images)
- **ANTHROPIC_AUTH_TOKEN** (required for provider creation and local sandbox)
