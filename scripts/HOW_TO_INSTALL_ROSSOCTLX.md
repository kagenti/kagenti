# How to Install `rossoctlx`

`rossoctlx` is the CLI for managing a **rossocortex budget proxy** (Python package
`kagenti-rossoctl`). It manages a proxy that sits in front of an upstream LLM
API (LiteLLM / Anthropic-compatible), enforcing per-agent daily budgets and
issuing per-agent proxy credentials.

The package is published from a Git subdirectory:

```
git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts
```

This guide covers installation and all dependencies on **macOS**, **Windows**,
and **Linux**.

---

## 1. Requirements at a glance

| Requirement | Needed for | Notes |
|---|---|---|
| **Python ≥ 3.11** | Always | Package declares `Requires-Python: >=3.11`. `uv` can provision this for you. |
| **An installer**: `uv` **or** `pipx` **or** `pip` | Install | `uv tool install` recommended (isolates the CLI and can fetch the right Python); pipx is the standard alternative. |
| **git** | Install | The package is fetched from a Git repo/subdirectory. |
| **Container runtime** (`docker` **or** `podman`) | `rossoctlx cortex start` (default mode) | Runs image `quay.io/aslomnet/rosscortex:latest`. **The published image is `linux/arm64` only** — see the arch note in §6. |
| **LiteLLM/LLM API key** | `rossoctlx cortex start`, `rossoctlx agent` | Injected by the proxy. `start` refuses to run without one — set it before starting (see §7). |
| Source checkout + **`uv`** + **Go** | `rossoctlx cortex start --local` (native mode) only | Native mode builds/runs the AuthBridge helper from source. **Not available from a pip install** (the wheel ships only the CLI) — point `ROSSOCORTEX_CONTAINER_LOCAL_DIR` at a `kagenti` checkout. |
| Network access | Install + runtime | To reach GitHub, PyPI, the container registry, and the upstream LLM API. |

### Python dependencies

Direct dependencies (declared by the package):

- `httpx >= 0.27`
- `jinja2 >= 3.1`

These pull in the following transitive dependencies automatically:

- `anyio`, `sniffio`, `httpcore`, `h11`, `certifi`, `idna` (via `httpx`)
- `markupsafe` (via `jinja2`)

You do **not** install these manually — `pip`/`pipx` resolves them.

### External (non-Python) dependencies

These are **not** installed by pip and must be present on your system depending
on how you run the proxy:

- **Container runtime** — `docker` or `podman`. Required for the default
  `rossoctlx cortex start` (container) mode. `rossoctlx` auto-detects whichever is on
  your `PATH`.
- **`uv` + Go + a `kagenti` source checkout** — needed only for
  `rossoctlx cortex start --local` (native mode), which runs `rossocortex.py` directly and
  builds an AuthBridge proxy binary. **A pip/pipx install cannot do `--local`** on
  its own — the wheel ships only the CLI module. Set
  `ROSSOCORTEX_CONTAINER_LOCAL_DIR` to a checkout's
  `scripts/rossocortex-container/` if you need native mode.

---

## 2. Install Python 3.11+

Check what you have:

```bash
python3 --version    # macOS/Linux
python --version     # Windows
```

If it's older than 3.11 (or missing):

### macOS
```bash
brew install python        # Homebrew
# or download from https://www.python.org/downloads/macos/
```

### Windows
- Install from the Microsoft Store ("Python 3.12"+), **or**
- `winget install Python.Python.3.12`, **or**
- Download from <https://www.python.org/downloads/windows/> (check
  "Add python.exe to PATH" during setup).

### Linux
```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git

# Fedora/RHEL
sudo dnf install -y python3 python3-pip git

# Arch
sudo pacman -S python python-pip git
```

---

## 3. Install `git`

- **macOS:** `brew install git` (or run `git` once to trigger Xcode CLT install).
- **Windows:** `winget install Git.Git` or <https://git-scm.com/download/win>.
- **Linux:** included in the package commands above (`apt`/`dnf`/`pacman`).

---

## 4. Install `rossoctlx`

Pick **one** method. Options A and B both install `rossoctlx` into an isolated
environment and put the command on your `PATH` — the right choice for a CLI tool.
**`uv tool install` (Option A) is recommended.**

> **Already installed? Jump to the "Upgrade" line under your option below.**
> Because the package is fetched from a moving git **branch** (`@rossoctlx`, not a
> version tag), installers treat it as *already satisfied* and a plain re-install
> **no-ops** — you must **force a reinstall** to pull the latest branch tip. Each
> option below shows the exact upgrade command.

### Try it first without installing (optional)

If you have `uv`, run a one-shot to validate your machine before committing to an
install — this provisions a throwaway environment and runs the built-in
preflight check:

```bash
uvx --from "git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts" rossoctlx doctor
```

### Option A — `uv tool install` (recommended)

`uv` is a fast Python package/tool manager. `uv tool install` isolates the CLI in
its own environment, and can fetch a suitable Python for you — sidestepping
PEP 668 (`externally-managed-environment`) and Python-version issues in one step.

**Install uv** (if you don't have it):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh     # or: brew install uv
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # or: winget install astral-sh.uv
```

**Install rossoctlx:**

```bash
uv tool install --python 3.11 "git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts"
uv tool update-shell     # ensures uv's bin dir is on PATH (open a new terminal after)
```

> **Note:** like pipx, uv places the `rossoctlx` shim in a bin dir that must be on
> your `PATH`. If `rossoctlx` isn't found after install, run `uv tool update-shell`
> (or add the printed dir to `PATH`) and open a **new terminal**.

**Upgrade (already installed):**

```bash
uv tool install --reinstall "git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts"
```

> `uv tool upgrade kagenti-rossoctl` or a plain `uv tool install` usually **no-ops**
> on a branch ref (it looks "already satisfied"). `--reinstall` forces a fresh fetch
> of the branch tip. Verify with `rossoctlx --version`.

### Option B — pipx

The standard tool for installing globally-scoped Python CLIs in isolated venvs.

```bash
# Install pipx
brew install pipx                       # macOS
sudo apt install -y pipx                # Linux (Debian/Ubuntu)
python3 -m pip install --user pipx      # any OS with pip ("python -m pip" on Windows)

# Install rossoctlx
pipx install "git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts"
pipx ensurepath          # adds pipx's bin dir to PATH (open a new terminal after)
```

> **Note:** `pipx ensurepath` installs to `~/.local/bin` on macOS/Linux and
> `%USERPROFILE%\.local\bin` on Windows. Open a **new terminal** (or
> `source ~/.zshrc` / `source ~/.bashrc`) so the `rossoctlx` command is found.

**Upgrade (already installed):**

```bash
pipx reinstall kagenti-rossoctl
```

> `pipx upgrade kagenti-rossoctl` can **no-op** on a branch ref; `pipx reinstall`
> re-clones the branch tip. Verify with `rossoctlx --version`.

### Option C — virtual environment (if you want to import the package)

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts"
```

**Windows (PowerShell):**
```powershell
# If activation is blocked by the execution policy, allow it for this session only:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install "git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts"
```

You must activate the venv each time before using `rossoctlx`.

**Upgrade (venv activated):**

```bash
pip install --upgrade --force-reinstall "git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts"
```

> `--force-reinstall` is needed because the branch ref looks "already satisfied" to
> pip, so `--upgrade` alone won't move you to a newer branch commit.

### Option D — user install (quick, discouraged on Homebrew Python)

```bash
python3 -m pip install --user "git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts"
```

> ⚠️ On macOS/Linux with a **Homebrew- or system-managed Python** (PEP 668) this
> is blocked with an `externally-managed-environment` error. Prefer Option A (uv)
> or B (pipx). If you must, add `--break-system-packages` — but this can interfere
> with your system Python.

**Upgrade (already installed):**

```bash
python3 -m pip install --user --upgrade --force-reinstall "git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts"
```

> `--force-reinstall` forces pip to re-fetch the branch tip (a plain `--upgrade`
> sees the branch ref as already satisfied).

---

## 5. Verify the install

```bash
rossoctlx --version      # prints the client version, e.g. "rossoctlx 0.2.0"
rossoctlx doctor         # environment preflight: green/red checklist + fixes
```

`rossoctlx doctor` (alias `rossoctlx preflight`) checks — **without needing a running
proxy** — Python version, git, container runtime *and whether its daemon responds*,
host-vs-image architecture, credential presence, upstream, config-dir writability,
and port availability. It exits `0` when all required checks pass and `1` otherwise,
so you can gate scripts/CI on it. Add `--local` to also check native-mode deps.

> **Note:** `rossoctlx version` and `rossoctlx status` query a **running** proxy, so
> before you run `rossoctlx cortex start` they report it's not running and exit non-zero.
> That's expected — use `rossoctlx --version` / `rossoctlx doctor` as your
> post-install checks.

---

## 6. Install the runtime dependencies

### Container runtime (for default `rossoctlx cortex start`)

`rossoctlx cortex start` runs the proxy in a container from
`quay.io/aslomnet/rosscortex:latest`. Install **docker** or **podman**:

> ⚠️ **Architecture:** the published image is **`linux/arm64` only** (Apple Silicon,
> arm64 Linux). On **amd64/x86-64** hosts (most Intel/AMD Linux, WSL2, Intel Macs)
> `rossoctlx cortex start` will fail with an `exec format error` / platform-mismatch. On
> those hosts, build a native image from source — see
> [`rossocortex-container/REPRODUCE.md`](rossocortex-container/REPRODUCE.md) — then
> `rossoctlx cortex start --image <your-image>`.
>
> ℹ️ **First start downloads the image** (a few hundred MB). It can take a minute and
> may look idle while pulling; subsequent starts reuse the cached image.

**macOS**
```bash
brew install --cask docker      # Docker Desktop
# or
brew install podman && podman machine init && podman machine start
```

**Windows**
```powershell
winget install Docker.DockerDesktop
# or
winget install RedHat.Podman
```
(Docker Desktop on Windows requires WSL2.)

**Linux**
```bash
# Docker (Debian/Ubuntu) — see https://docs.docker.com/engine/install/
sudo apt install -y docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"   # log out/in afterwards

# Podman
sudo apt install -y podman        # or: sudo dnf install -y podman
```

### Native mode (`rossoctlx cortex start --local`)

Skip this unless you run the proxy natively instead of in a container. Native mode
needs **all** of: `uv` (install shown in §4 Option A), **Go**, and a **`kagenti`
source checkout** (the AuthBridge helper and its templates aren't shipped in the
pip package). Point `rossoctlx` at the checkout:

```bash
export ROSSOCORTEX_CONTAINER_LOCAL_DIR=/path/to/kagenti/scripts/rossocortex-container
rossoctlx doctor --local     # verifies the native-mode prerequisites
```

---

## 7. Quick start

### Fastest: reuse `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`

If you already have these exported (e.g. for Claude Code against a LiteLLM /
Anthropic-compatible endpoint), **no credential file and no `--upstream` flag are
needed** — `rossoctlx cortex start` reads the URL from `ANTHROPIC_BASE_URL` and the key
from `ANTHROPIC_AUTH_TOKEN` automatically:

```bash
# Already set in your shell? Then just start — nothing else required:
export ANTHROPIC_BASE_URL=https://<your-litellm-or-anthropic-base-url>
export ANTHROPIC_AUTH_TOKEN=sk-your-key

rossoctlx cortex start          # picks up URL + key from the env above
```

`rossoctlx` resolves the **upstream** from `ROSSOCORTEX_UPSTREAM` → `ANTHROPIC_BASE_URL`,
and the **credential** from the first of `LITELLM_API_KEY` → `ROSSOCORTEX_API_KEY` →
`ANTHROPIC_AUTH_TOKEN` → `OPENAI_API_KEY` (files under
`~/.config/rossocortex/credentials/` are checked before env vars).

### Alternative: a credential file + explicit `--upstream`

Use this if you don't already have the env vars set. A credential file (chmod 600)
keeps the key out of shell history and the process list:

```bash
mkdir -p ~/.config/rossocortex/credentials
printf '%s' 'sk-your-litellm-key' > ~/.config/rossocortex/credentials/LITELLM_API_KEY
chmod 600 ~/.config/rossocortex/credentials/LITELLM_API_KEY

rossoctlx cortex start --upstream <your-litellm-or-anthropic-base-url> --budget 5.0
```

### Then, either way

```bash
# Check status / version
rossoctlx status
rossoctlx version

# Register an agent and get its proxy credentials
rossoctlx agent my-agent --budget 2.0
rossoctlx agents            # list registered agents

# Tail the request log
rossoctlx log -f

# Stop the proxy
rossoctlx stop
```

Useful environment variables the CLI reads:

- `ROSSOCORTEX_UPSTREAM` or `ANTHROPIC_BASE_URL` — upstream LLM API URL.
- `ROSSOCORTEX_CONFIG_DIR` — config location (default:
  `~/.config/rossocortex`).
- Credentials it looks for (in order): `LITELLM_API_KEY`, `ROSSOCORTEX_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`.

Enable shell tab-completion (bash/zsh/fish):

```bash
rossoctlx completions        # prints setup instructions for your $SHELL
```

---

## 8. Run an agent container through rossocortex (no isolation)

Any container can route its LLM and outbound HTTPS through the running proxy. For
LLM calls the proxy injects the real credential; for tunnelled HTTPS it enforces
the agent's daily budget and `--network-allow` / `--network-deny` policy. The
examples use the multi-agent image `quay.io/aslomnet/agents:test` (Claude Code,
Codex, Gemini, Qwen, Pi, Aider), but any image with `curl` works.

> **Image source:** `quay.io/aslomnet/agents:test` is built from
> [`scripts/Dockerfile-agent`](https://github.com/aslom/kagenti/blob/rossoctlx/scripts/Dockerfile-agent)
> (build/push via
> [`scripts/build-and-push-agent-image.sh`](https://github.com/aslom/kagenti/blob/rossoctlx/scripts/build-and-push-agent-image.sh)).
> Build your own with `./build-and-push-agent-image.sh` (auto-detects docker/podman).

`rossoctlx agent <name>` already prints a ready-to-copy `docker run` recipe (to
stderr). Two container-specific adjustments vs. the host `eval` env:

- `localhost` → **`host.docker.internal`** (a container's own localhost is itself).
- the interception CA is **mounted** into the container and `SSL_CERT_FILE` points
  at the in-container path.

### Start the proxy and register an agent

```bash
export ROSSOCORTEX_API_KEY=sk-your-litellm-key      # or use a credential file (§7)
rossoctlx cortex start --upstream https://<your-litellm-or-anthropic-base-url>

# Allow the hosts this agent may reach through the proxy (everything else is denied)
rossoctlx agent demo --budget 5 \
  --network-allow=api.anthropic.com \
  --network-allow=github.com
```

### Run the agent container

```bash
KEY="$(rossoctlx agent demo | awk -F= '/ANTHROPIC_AUTH_TOKEN/{print $2}')"
CA="$HOME/.config/rossocortex/ca/tls.crt"           # adjust if XDG_CONFIG_HOME is set
PORT=8185                                            # `rossoctlx status` shows the actual port

docker run --rm -it \
  --add-host=host.docker.internal:host-gateway \
  -e OPENAI_API_BASE=http://host.docker.internal:$PORT \
  -e OPENAI_API_KEY=$KEY \
  -e ANTHROPIC_BASE_URL=http://host.docker.internal:$PORT \
  -e ANTHROPIC_AUTH_TOKEN=$KEY \
  -e HTTP_PROXY=http://$KEY@host.docker.internal:$PORT \
  -e HTTPS_PROXY=http://$KEY@host.docker.internal:$PORT \
  -e NO_PROXY=host.docker.internal,localhost,127.0.0.1 \
  -e SSL_CERT_FILE=/etc/rossocortex/ca.crt \
  -v "$CA:/etc/rossocortex/ca.crt:ro" \
  -v "$PWD:/workspace" -w /workspace \
  quay.io/aslomnet/agents:test bash
```

(podman: identical flags — `host.docker.internal` works with `podman machine`.)

### Test it

Run these **inside** the container (`connect=200` = the proxy established the
tunnel; a `401` from the endpoint just means the keyless request was rejected —
HTTPS access through the proxy still worked):

```bash
curl -sS -o /dev/null -w "anthropic: connect=%{http_connect}\n" https://api.anthropic.com/v1/models
curl -sS -o /dev/null -w "github:    connect=%{http_connect}\n" https://github.com
curl -sS -o /dev/null -w "pypi:      connect=%{http_connect}\n" https://pypi.org/simple/
```

Expected — allowed hosts tunnel, the unlisted host is refused:

```
anthropic: connect=200
github:    connect=200
pypi:      connect=403
```

> ⚠️ **No isolation here.** The container still has a normal network with direct
> internet, so only traffic that *opts in* via `HTTPS_PROXY` is policed. A call
> that bypasses the proxy (e.g. `curl --noproxy '*' https://pypi.org`) reaches the
> internet directly. To force **all** egress through the proxy, use §9.

---

## 9. Run an agent container with network isolation

To make the proxy the **only** possible egress, put the agent container on a
Docker `--internal` network (no route to the internet) and attach the
`rossocortex` container to that same network so it's reachable by name. Now the
container cannot bypass the proxy: only the agent's `--network-allow` hosts are
reachable — everything else, and every direct call, is denied.

### One command: `rossoctlx sandbox run`

`rossoctlx sandbox run <agent>` **prints** the exact commands (network create +
connect + `docker run`) with all env vars container-adjusted (`localhost` →
`rossocortex`, CA mounted). Review them, then pipe to a shell to run:

```bash
rossoctlx sandbox run demo                 # just print the commands
rossoctlx sandbox run demo | sh            # ... or run them
rossoctlx sandbox run demo -- bash -lc '<cmd>'   # one-shot (no interactive -it)
```

Flags: `--image` (default `quay.io/aslomnet/agents:test`), `--network` (default
`isolated-net`), `--workspace` (default: current dir, mounted at `/workspace`).

### The commands it prints (equivalent to running by hand)

```bash
docker network create --internal isolated-net 2>/dev/null || true
docker network connect isolated-net rossocortex 2>/dev/null || true

KEY="$(rossoctlx agent demo | awk -F= '/ANTHROPIC_AUTH_TOKEN/{print $2}')"
CA="$HOME/.config/rossocortex/ca/tls.crt"
docker run --rm -it --network isolated-net \
  -e OPENAI_API_BASE=http://rossocortex:8185 \
  -e OPENAI_API_KEY=$KEY \
  -e ANTHROPIC_BASE_URL=http://rossocortex:8185 \
  -e ANTHROPIC_AUTH_TOKEN=$KEY \
  -e HTTP_PROXY=http://$KEY@rossocortex:8185 \
  -e HTTPS_PROXY=http://$KEY@rossocortex:8185 \
  -e NO_PROXY=rossocortex \
  -e SSL_CERT_FILE=/etc/rossocortex/ca.crt \
  -v "$CA:/etc/rossocortex/ca.crt:ro" \
  -v "$PWD:/workspace" -w /workspace \
  quay.io/aslomnet/agents:test bash
```

### Test it

```bash
rossoctlx sandbox run demo -- bash -lc '
  # 1. direct internet (bypass proxy) — FAILS: --internal net has no route/DNS
  curl -sS -m8 --noproxy "*" -o /dev/null -w "direct github:       %{http_code}\n" https://github.com 2>&1 || echo "direct github:       BLOCKED"
  # 2. allowed hosts via proxy → connect=200
  curl -sS -o /dev/null -w "github via proxy:    connect=%{http_connect}\n" https://github.com
  curl -sS -o /dev/null -w "anthropic via proxy: connect=%{http_connect}\n" https://api.anthropic.com/v1/models
  # 3. denied host via proxy → connect=403
  curl -sS -o /dev/null -w "pypi via proxy:      connect=%{http_connect}\n" https://pypi.org/simple/
' | sh
```

Expected:

```
direct github:       BLOCKED          # no route off the --internal network
github via proxy:    connect=200
anthropic via proxy: connect=200
pypi via proxy:      connect=403
```

Every request is recorded in the proxy log with its verdict:

```bash
rossoctlx log -n 10
#   agent=demo  CONNECT github.com:443  status=200
#   agent=demo  CONNECT pypi.org:443    status=403  denied=network_policy:pypi.org
```

### Clean up

```bash
docker network disconnect isolated-net rossocortex
docker network rm isolated-net
rossoctlx stop
```

---

## 10. Upgrade / uninstall

**uv (Option A):**
```bash
uv tool upgrade kagenti-rossoctl        # re-resolve from the pinned git ref
uv tool uninstall kagenti-rossoctl
```

**pipx:**
```bash
pipx upgrade kagenti-rossoctl
# or force a reinstall from the latest git ref:
pipx reinstall kagenti-rossoctl
pipx uninstall kagenti-rossoctl
```

**venv / pip:**
```bash
pip install --upgrade "git+https://github.com/aslom/kagenti.git@rossoctlx#subdirectory=scripts"
pip uninstall kagenti-rossoctl
```

---

## 11. Troubleshooting

> Tip: `rossoctlx doctor` diagnoses most of the runtime rows below in one shot.

| Symptom | Fix |
|---|---|
| `error: externally-managed-environment` | Use `uv tool install` (Option A) or pipx (Option B) instead of a bare `pip install`. |
| `rossoctlx: command not found` after install | Run `uv tool update-shell` (uv) or `pipx ensurepath` (pipx), then open a new terminal or `source` your shell rc file. |
| `git` errors during install / `Cannot find command 'git'` | Git is required because the package installs from a Git repo — install Git (§3) and rerun. |
| `ERROR: Cannot connect to rossocortex …` from `version`/`status` | Expected until you run `rossoctlx cortex start`. Use `rossoctlx --help` to check the install. |
| `rossoctlx cortex start` reports no LiteLLM key | Create `~/.config/rossocortex/credentials/LITELLM_API_KEY` (see §7). |
| `rossoctlx cortex start` can't find a runtime | Install and start docker or podman; ensure it's on your `PATH`. |
| `port already in use` / bind failure on start | `start` auto-picks free ports (proxy defaults to `8185`, control `8186`). If it can't, run `rossoctlx stop` to clear an old instance, or pass `--port`/`--control-port`. |
| PowerShell: "running scripts is disabled" on venv activate | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first (see §4 Option C). |
| `exec format error` / `no matching manifest for linux/amd64` on `start` | The published image is arm64-only. Build a native image (§6 / REPRODUCE.md) and use `--image`. |
| `start` hangs / looks idle on first run | It's pulling the image (~hundreds of MB). Wait, or pre-pull with `docker pull quay.io/aslomnet/rosscortex:latest`. |
| Install fails behind a corporate proxy / TLS interception | Set `HTTPS_PROXY`/`HTTP_PROXY`; for a custom CA use `pip install --proxy … ` and `PIP_CERT`/`GIT_SSL_CAINFO`. |
| `--local` mode fails | Native mode needs a source checkout + `uv` + Go and `ROSSOCORTEX_CONTAINER_LOCAL_DIR`; it is not available from a pip install. |
| `Requires-Python: >=3.11` error at install | Upgrade Python (step 2). |
