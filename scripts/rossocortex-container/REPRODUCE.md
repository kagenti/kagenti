# Reproducing rossocortex + AuthBridge from source

This captures how to rebuild the rossocortex proxy and its embedded AuthBridge
binary in a **fresh, independent environment** using only public GitHub sources.

The steps below were verified clean-room on 2026-07-14 (macOS arm64, Go 1.26.3):
`authbridge-proxy` built successfully and started with all four plugins loaded.

## What rossocortex depends on

- **`rossoctlx.py`** (CLI) — Python `httpx` + `jinja2`; external CLIs `docker`/`podman`,
  `lsof`, `ps`, `tail`.
- **`rossocortex.py`** (proxy) — Python `httpx` + stdlib; spawns the AuthBridge binary
  **per agent** for HTTPS `CONNECT` tunnels; `openssl` for the local TLS-bridge CA.
- **AuthBridge** — a Go binary (`authbridge-proxy`) built from `kagenti-extensions`,
  running a plugin pipeline: `placeholder-resolve` (credential injection),
  `inference-parser`, `mcp-parser` (outbound) and `litellm-budget-track` (inbound).

## Source repos / branches

AuthBridge needs two plugins that are **not** in upstream `kagenti/kagenti-extensions`;
they live on two forks:

| Component | Repo / branch |
|-----------|---------------|
| rossocortex + `rossoctlx.py` | `aslom/kagenti.git` @ `rossoctlx` (this dir: `scripts/rossocortex-container/`) |
| authbridge base + `litellm_budgettrack` (+ `inferenceparser`, `mcpparser`) | `aslom/kagenti-extensions.git` @ `litellm_budgettrack_plugin` |
| `placeholderresolve` (+ `credinject`, `openshell` support pkgs) | `huang195/kagenti-extensions.git` @ `feat/placeholder-resolve-plugin` |

## Prerequisites

- Go **1.25+** (verified with 1.26.3), `git`, `openssl`
- `docker` or `podman` (only needed to build/run the container image)
- A **LiteLLM virtual key** and the **upstream LiteLLM URL** (runtime secrets — not in any repo)

## Path A — run the prebuilt image (no Go build)

```bash
export ROSSOCORTEX_UPSTREAM=https://<your-litellm>
printf '%s' 'sk-litellm-...' > ~/.config/rossocortex/credentials/LITELLM_API_KEY
./rossoctlx.py start          # pulls quay.io/aslomnet/rosscortex:latest
```

> **Caveat:** the published image is **linux/arm64 only**. On amd64 hosts it will not
> run — use Path B to build a native image.

## Path B — build from source (clean-room verified)

```bash
# 1. Get kagenti-extensions with the litellm_budgettrack plugin
git clone --depth 1 -b litellm_budgettrack_plugin \
    https://github.com/aslom/kagenti-extensions.git
cd kagenti-extensions

# 2. Overlay the placeholderresolve plugin from the huang195 fork
git remote add huang195 https://github.com/huang195/kagenti-extensions.git
git fetch --depth 1 huang195 feat/placeholder-resolve-plugin
git checkout huang195/feat/placeholder-resolve-plugin -- \
    authbridge/authlib/plugins/placeholderresolve \
    authbridge/authlib/credinject \
    authbridge/authlib/openshell \
    authbridge/cmd/authbridge-proxy/plugins_placeholderresolve.go
cd ..

# 3. Build the AuthBridge binary (build.sh automates steps 2+3 and the container image)
KAGENTI_EXTENSIONS_DIR="$PWD/kagenti-extensions" \
    <path-to>/kagenti/scripts/rossocortex-container/build.sh
# ... or build the binary directly:
CGO_ENABLED=0 go build -C kagenti-extensions/authbridge \
    -ldflags="-s -w" -o ./authbridge-proxy ./cmd/authbridge-proxy
```

`build.sh` also fetches the huang195 plugin automatically if missing, builds a
`linux/<arch>` binary into `bin/authbridge-proxy-linux`, and builds the container
image (`ROSSCORTEX_IMAGE`, default `quay.io/aslomnet/rosscortex:latest`).

## Verifying the build

Generate a CA + config referencing all four plugins and start the binary — it must
come up with no `unknown plugin` / `not registered` errors:

```bash
mkdir -p ca && openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
    -subj '/CN=Cleanroom CA/O=kagenti' \
    -addext 'basicConstraints=critical,CA:TRUE' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign' \
    -keyout ca/tls.key -out ca/tls.crt
# write a config.yaml (see entrypoint.sh for the exact structure) then:
./authbridge-proxy --config config.yaml
# expect: "tls-bridge enabled", "forward-proxy listening", no plugin errors
```

## Known gaps / risks

- **`placeholderresolve` is fork-only and untracked** in the working checkouts — it
  exists only on `huang195/kagenti-extensions@feat/placeholder-resolve-plugin`.
  Reproducibility depends on that fork/branch staying public. Consider committing it
  into `aslom/kagenti-extensions` to make the build self-contained.
- **`BUILD_INFO.json` drift:** the shipped binary records authbridge commit `b06cc91`,
  but the source branch head differs. The binary is not guaranteed bit-reproducible;
  rebuild from the branches above rather than trusting the recorded commit.
- **Image is single-arch (arm64).** Publish a multi-arch image or rebuild per host.
- **Base coupling:** the plugins import `github.com/kagenti/kagenti-extensions/authbridge/authlib/{pipeline,plugins}`; build against the `litellm_budgettrack_plugin` branch (which carries the compatible base), not pristine upstream.
- **Secrets are runtime inputs** (LiteLLM key, upstream URL); the TLS-bridge CA is
  generated at startup. None are — or should be — stored in the repos.
