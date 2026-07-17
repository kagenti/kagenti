# How to Install `rossoctl` (Go CLI)

`rossoctl` is a small, single-binary **Go** CLI. Its command surface mirrors the
Python `rossoctlx` tool (`version`, `status`, `doctor`, `start`, `stop`, `log`,
`agents`, `agent`, `completions`) — but this is currently a **stub**: those
commands are wired up and do nothing yet. What *is* real is the packaging and the
**self-update** flow, which follow current best practices for distributing a Go
CLI.

- Source: `kagenti/scripts/rossoctl/` (module `github.com/aslom/kagenti/scripts/rossoctl`)
- For the fully-featured Python CLI, see [`HOW_TO_INSTALL_ROSSOCTLX.md`](HOW_TO_INSTALL_ROSSOCTLX.md).

---

## 1. Requirements

| To install via… | You need |
|---|---|
| `go install` / `go run` | Go **1.23+** (`go version`) |
| `docker run` | Docker or Podman |
| `curl \| sh` (bootstrap, production) | just a shell; downloads a prebuilt binary |

No other runtime dependencies — it's a static binary.

---

## 2. Install

### Option A — `go install` (recommended for Go users)

Install a **tagged release** (recommended — `@latest` needs a version tag to exist):

```bash
go install github.com/aslom/kagenti/scripts/rossoctl@latest    # newest tag
go install github.com/aslom/kagenti/scripts/rossoctl@v0.1.0    # pinned
```

This builds and drops `rossoctl` into `$(go env GOBIN)` (or `$(go env GOPATH)/bin`).
Make sure that directory is on your `PATH`:

```bash
export PATH="$(go env GOPATH)/bin:$PATH"   # add to ~/.zshrc / ~/.bashrc
```

> **Note (nested module):** `rossoctl` lives in a subdirectory module, so its version
> tags are prefixed with the path — e.g. `scripts/rossoctl/v0.1.0` — while you install
> it as `…/scripts/rossoctl@v0.1.0`. Installing a **branch** (`@rossoctlx`) works only
> if at least one such tag exists (Go's `@latest` deprecation lookup needs it); prefer
> `@latest`/`@vX.Y.Z`. For an untagged commit use `@<sha>` with `GOPROXY=direct GOSUMDB=off`.

### Option B — `go run` (no install)

```bash
go run github.com/aslom/kagenti/scripts/rossoctl@latest version
go run github.com/aslom/kagenti/scripts/rossoctl@v0.1.0 doctor
```

### Option C — Docker / Podman

```bash
docker run --rm quay.io/aslomnet/rossoctl version
docker run --rm quay.io/aslomnet/rossoctl doctor
```

Build it yourself from the source dir (7 MB distroless image):

```bash
cd kagenti/scripts/rossoctl
docker build -t quay.io/aslomnet/rossoctl \
  --build-arg VERSION="$(git describe --tags --always)" \
  --build-arg COMMIT="$(git rev-parse --short HEAD)" .
```

### Option D — `curl | sh` bootstrap (production pattern)

The recommended distribution model separates **install** from **update**: a
`curl | sh` script only bootstraps the first install into a user-writable dir
(`~/.local/bin`), and the binary updates itself thereafter (see §4). On Windows the
bootstrap is PowerShell (`irm …/install.ps1 | iex`) since `curl | sh` isn't native.

```bash
# (once release assets are published — see "Release plumbing" below)
curl -LsSf https://github.com/aslom/kagenti/releases/latest/download/install.sh | sh
```

---

## 3. Verify

```bash
rossoctl --version      # e.g. "rossoctl 0.1.0 (commit abc1234)"
rossoctl doctor         # (stub) mirrors rossoctlx doctor
rossoctl help           # full command list
```

---

## 4. Updating (`self-update`)

The binary owns its own lifecycle. Update model follows CLI best practices:
**manual update + a throttled passive notice** — never silent auto-replacement
(which breaks reproducibility and surprises CI).

```bash
rossoctl self-update --check          # is a newer release available?
rossoctl self-update --dry-run        # show what would happen, change nothing
rossoctl self-update                  # download, verify, atomically replace
rossoctl self-update --version v0.3.1 # pin a specific version (up/downgrade)
```

**Passive "update available" notice.** On normal commands, at most once per 24h,
`rossoctl` does a fast (~2s) check and prints a single stderr line if a newer
release exists:

```
rossoctl 0.3.1 available (you have 0.2.0) — run 'rossoctl self-update'
```

It is **suppressed** when any of these hold (so it never disrupts scripts/CI):

| Condition | Why |
|---|---|
| stdout is not a TTY | piped/redirected output stays clean |
| `CI` env var is set | CI runs stay deterministic |
| `ROSSOCTL_NO_UPDATE_CHECK=1` | explicit opt-out |
| dev build (`version == "dev"`) | local builds don't nag |

The version check uses a `HEAD` on `…/releases/latest` and reads the redirect tag —
it does **not** call the rate-limited GitHub API. Override the source for testing:

```bash
ROSSOCTL_UPDATE_BASE=http://localhost:8080 ROSSOCTL_UPDATE_SLUG=you/repo \
  rossoctl self-update --check
```

**Package-manager installs are respected.** If `rossoctl` was installed via
Homebrew/Scoop (detected from its path), `self-update` defers:
`"installed via Homebrew — run 'brew upgrade rossoctl'"`.

---

## 5. Production release recipe (best practice)

This stub implements the client side; a full release setup adds:

1. **GoReleaser** — one config builds the `darwin/linux/windows × amd64/arm64`
   matrix, `checksums.txt`, optional cosign/minisign signatures, and a GitHub
   Release per tag. Embed the version: `-ldflags "-X main.version={{.Version}}"`.
2. **Verifiable self-update** — [`creativeprojects/go-selfupdate`](https://github.com/creativeprojects/go-selfupdate)
   (or `minio/selfupdate`) finds the right asset by naming convention, verifies
   the checksum/signature, downloads to a temp file, and atomically swaps it in.
   On Windows it applies the rename-to-`.old` trick automatically.
3. **Idempotent `install.sh` + `install.ps1`** — bootstrap and fallback updater,
   installing into a **user-writable** dir (no `sudo`/elevation).
4. **Package managers** — GoReleaser can emit a Homebrew tap, Scoop bucket, and
   winget manifest; `self-update` detects a managed install and defers.

Asset naming (updater keys off this):

```
rossoctl_Darwin_arm64.tar.gz   rossoctl_Darwin_x86_64.tar.gz
rossoctl_Linux_arm64.tar.gz    rossoctl_Linux_x86_64.tar.gz
rossoctl_Windows_x86_64.zip    checksums.txt
```

---

## 6. Notes

- **This is a stub.** Every command except `version`, `self-update`, and `help`
  prints `"[stub] … not implemented"` and exits 0. The real behavior lives in the
  Python `rossoctlx` (see the sibling install guide).
- **Install to a user-writable path.** Both `go install` (GOPATH/bin) and the
  recommended `~/.local/bin` avoid elevation, so `self-update` never needs `sudo`.
- **Reproducibility.** Pin with `@v0.1.0` (go) or `--version vX.Y.Z` (self-update);
  the embedded version + commit are printed by `rossoctl version`.
