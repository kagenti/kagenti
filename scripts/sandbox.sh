#!/usr/bin/env bash
set -euo pipefail

HOST_HOME="$HOME"

# Root of all allowed projects
SANDBOX_DIR="${SANDBOX_DIR:-"$HOME/sandbox"}"
if [[ ! -d "$SANDBOX_DIR" ]]; then
  # Fall back to parent of current directory (supports running from any location)
  SANDBOX_DIR="$(dirname "$(pwd -P)")"
fi

# Canonical SANDBOX_DIR — use `pwd -P` so the value matches the *physical*
# path the kernel sandbox sees. macOS sandbox-exec resolves symlinks before
# testing `(subpath ...)` rules, so a logical (un-resolved) path in a -D
# parameter will not match the kernel's resolved path when any component is a
# symlink, and the rule silently never fires.
if [[ ! -d "$SANDBOX_DIR" ]]; then
  echo "SANDBOX_DIR '$SANDBOX_DIR' does not exist" >&2
  exit 1
fi
SANDBOX_REAL="$(cd "$SANDBOX_DIR" && pwd -P)"

# Sandbox profile: defaults to agent-sandbox.sb sitting next to *this* script
# (following symlinks). The launcher and profile are co-versioned — pairing
# them by directory eliminates a footgun where SANDBOX_DIR holds a stale
# agent-sandbox.sb (or a stale symlink to one) and silently loads it instead
# of the profile in the live repo.
_self="${BASH_SOURCE[0]}"
while [[ -L "$_self" ]]; do
  _link="$(readlink "$_self")"
  case "$_link" in
    /*) _self="$_link" ;;
    *)  _self="$(cd "$(dirname "$_self")" && pwd -P)/$_link" ;;
  esac
done
SCRIPT_DIR="$(cd "$(dirname "$_self")" && pwd -P)"
unset _self _link

SANDBOX_PROFILE="${SANDBOX_PROFILE:-"$SCRIPT_DIR/agent-sandbox.sb"}"
if [[ ! -f "$SANDBOX_PROFILE" ]]; then
  echo "Sandbox profile not found: $SANDBOX_PROFILE" >&2
  exit 1
fi

# PROJECT_DIR is always the current directory — must be under SANDBOX_DIR.
PROJECT_REAL="$(pwd -P)"

if [[ "$PROJECT_REAL" != "$SANDBOX_REAL"/* ]]; then
  echo "Error: must run from a subdirectory of SANDBOX_DIR '$SANDBOX_REAL'." >&2
  echo "  current dir: $PROJECT_REAL" >&2
  exit 1
fi

# --- Private temp directory ------------------------------------------------
# Create a project-local temp dir so the sandbox can deny /tmp, /private/tmp,
# /var/tmp — preventing cross-process data leaks and symlink attacks in shared
# temp directories. The private temp lives under PROJECT_DIR, so the existing
# PROJECT_DIR file-read*/file-write* rule covers it with no extra sandbox param.

PRIVATE_TMPDIR="$PROJECT_REAL/.tmp"
CLAUDE_CODE_TMPDIR="$PRIVATE_TMPDIR/claude-$(id -u)"
mkdir -p "$PRIVATE_TMPDIR" "$CLAUDE_CODE_TMPDIR"

# --- Shim sandbox-exec inside the sandbox ---------------------------------
# Place the shim inside the private temp (accessible inside the sandbox).

SHIM_DIR="$PRIVATE_TMPDIR/claude-sbx.$$"
mkdir -p "$SHIM_DIR"
# When this script exits (normally or on error), delete the shim directory
trap 'rm -rf "$SHIM_DIR"' EXIT

cat > "$SHIM_DIR/sandbox-exec" <<'EOF'
#!/usr/bin/env bash
# No-op sandbox-exec shim for processes running *inside* the outer sandbox.
# Always succeed without actually sandboxing or running a nested sandbox.
exit 0
EOF

chmod +x "$SHIM_DIR/sandbox-exec"

# Shim dir is prepended to _filtered_path after PATH filtering below.

# --- Seed project-local Claude config from shared credentials --------------

CLAUDE_CFG="$PROJECT_REAL/.claude"
mkdir -p "$CLAUDE_CFG"

# SRC_CREDS="$SANDBOX_REAL/.claude/.credentials.json"

# # Prefer the keychain — it holds the current token after any refresh.
# # Fall back to the credentials file if the keychain entry is absent.
# KC_JSON="$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null || true)"
# if [[ -n "$KC_JSON" ]]; then
#   printf '%s' "$KC_JSON" > "$CLAUDE_CFG/.credentials.json"
#   chmod 600 "$CLAUDE_CFG/.credentials.json"
# elif [[ -f "$SRC_CREDS" ]]; then
#   cp "$SRC_CREDS" "$CLAUDE_CFG/.credentials.json"
# else
#   echo "No credentials found in keychain or at '$SRC_CREDS'." >&2
#   #echo "  Run 'claude auth login' once from outside the sandbox to set up credentials." >&2
# fi

# --- Ensure showThinkingSummaries is enabled in settings.json ----------------

SETTINGS_FILE="$CLAUDE_CFG/settings.json"
if [[ ! -f "$SETTINGS_FILE" ]]; then
  printf '{\n  "showThinkingSummaries": true\n}\n' > "$SETTINGS_FILE"
elif ! grep -q '"showThinkingSummaries"' "$SETTINGS_FILE"; then
  # Insert "showThinkingSummaries": true after the opening brace on line 1
  _tmp="$(mktemp "${TMPDIR:-/tmp}/settings.XXXXXX")"
  {
    echo '{'
    echo '  "showThinkingSummaries": true,'
    # Copy all lines except the first (the opening brace)
    tail -n +2 "$SETTINGS_FILE"
  } > "$_tmp"
  mv "$_tmp" "$SETTINGS_FILE"
fi

# --- SSH agent handling ----------------------------------------------------
# Block by default; ENABLE_SSH_AGENT=1 passes through the socket.

SSH_AGENT_DIR=""
if [[ "${ENABLE_SSH_AGENT:-}" != "1" && -n "${SSH_AUTH_SOCK:-}" ]]; then
  SSH_AGENT_DIR="$(dirname "$SSH_AUTH_SOCK")"
  unset SSH_AUTH_SOCK
fi
# If SSH_AGENT_DIR is empty, use a non-existent sentinel path
# so (subpath ...) in the sandbox profile becomes a no-op.
if [[ -n "$SSH_AGENT_DIR" ]]; then
  SSH_AGENT_DIR_PARAM="$SSH_AGENT_DIR"
else
  SSH_AGENT_DIR_PARAM="/private/var/no-ssh-agent-placeholder"
fi

# --- Additional sandboxed directory ----------------------------------------
# Optional second project-style directory that gets the same read/write access
# as PROJECT_DIR. Used when an agent needs to share data with, or work across,
# a sibling directory under SANDBOX_DIR (e.g., a shared cache, generated
# artifacts, or a companion repository). Same sentinel-path pattern as
# ENABLE_DOCKER: when unset, a non-existent placeholder makes the SBPL allow a
# no-op.
#
# Constraint: like PROJECT_DIR, it must resolve to a path under SANDBOX_DIR.
# This prevents an attacker (or a misconfigured invocation) from passing an
# arbitrary directory — including HOST_HOME or / — as the additional dir.

if [[ -n "${SANDBOX_ADDITIONAL_DIR:-}" ]]; then
  if [[ ! -d "$SANDBOX_ADDITIONAL_DIR" ]]; then
    echo "SANDBOX_ADDITIONAL_DIR '$SANDBOX_ADDITIONAL_DIR' does not exist or is not a directory" >&2
    exit 1
  fi
  # `pwd -P` resolves all symlinks. Without -P, a symlinked target dir produces
  # a logical path that does not match what the kernel sandbox sees (the kernel
  # resolves symlinks before evaluating subpath rules), and the SBPL allows for
  # this dir silently never fire — symptom: cd into the dir works (covered by
  # path-ancestors metadata), but ls fails with EPERM.
  SANDBOX_ADDITIONAL_REAL="$(cd "$SANDBOX_ADDITIONAL_DIR" && pwd -P)"
  if [[ "$SANDBOX_ADDITIONAL_REAL" != "$SANDBOX_REAL"/* ]]; then
    echo "Error: SANDBOX_ADDITIONAL_DIR must resolve to a subdirectory of SANDBOX_DIR '$SANDBOX_REAL'." >&2
    echo "  resolved: $SANDBOX_ADDITIONAL_REAL" >&2
    echo "  (symlinks are resolved; the resolved real path must be inside SANDBOX_DIR)" >&2
    exit 1
  fi
  SANDBOX_ADDITIONAL_DIR_PARAM="$SANDBOX_ADDITIONAL_REAL"
else
  SANDBOX_ADDITIONAL_DIR_PARAM="/private/var/no-additional-dir-placeholder"
fi

# --- Shared skills directory -----------------------------------------------
# Optional shared Claude Code skills directory. When set, grants the same
# read/write access pattern as SANDBOX_ADDITIONAL_DIR, AND creates a project-
# local symlink at .claude/skills -> $SANDBOX_SKILLS_DIR so Claude finds
# skills at the well-known path. If .claude/skills already exists (per-project
# skills, or a previously-created symlink), the existing entry is left alone.
#
# Same containment rule as SANDBOX_ADDITIONAL_DIR: the resolved real path must
# live under SANDBOX_DIR. Same pwd -P requirement (kernel resolves symlinks
# before evaluating subpath rules — see the SANDBOX_ADDITIONAL_DIR comment).

if [[ -n "${SANDBOX_SKILLS_DIR:-}" ]]; then
  if [[ ! -d "$SANDBOX_SKILLS_DIR" ]]; then
    echo "SANDBOX_SKILLS_DIR '$SANDBOX_SKILLS_DIR' does not exist or is not a directory" >&2
    exit 1
  fi
  SANDBOX_SKILLS_REAL="$(cd "$SANDBOX_SKILLS_DIR" && pwd -P)"
  if [[ "$SANDBOX_SKILLS_REAL" != "$SANDBOX_REAL"/* ]]; then
    echo "Error: SANDBOX_SKILLS_DIR must resolve to a subdirectory of SANDBOX_DIR '$SANDBOX_REAL'." >&2
    echo "  resolved: $SANDBOX_SKILLS_REAL" >&2
    echo "  (symlinks are resolved; the resolved real path must be inside SANDBOX_DIR)" >&2
    exit 1
  fi
  SANDBOX_SKILLS_DIR_PARAM="$SANDBOX_SKILLS_REAL"

  # Symlink .claude/skills -> $SANDBOX_SKILLS_REAL only if nothing exists at
  # that path (no file, no dir, no symlink — broken or otherwise). Use -e for
  # the existence test and -L separately so a dangling symlink is also detected.
  if [[ ! -e "$CLAUDE_CFG/skills" && ! -L "$CLAUDE_CFG/skills" ]]; then
    ln -s "$SANDBOX_SKILLS_REAL" "$CLAUDE_CFG/skills"
  fi
else
  SANDBOX_SKILLS_DIR_PARAM="/private/var/no-skills-dir-placeholder"
fi

# --- Docker handling ----------------------------------------------------------
# Block by default; ENABLE_DOCKER=1 passes through the socket.

DOCKER_SOCK_PATH=""
if [[ "${ENABLE_DOCKER:-}" == "1" ]]; then
  if [[ -n "${DOCKER_HOST:-}" ]]; then
    # Remove the "unix://" prefix to get the filesystem path
    DOCKER_SOCK_PATH="${DOCKER_HOST#unix://}"
  else
    # Detect from current docker context
    _ctx_endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
    if [[ -n "$_ctx_endpoint" ]]; then
      DOCKER_HOST="$_ctx_endpoint"
      # Remove the "unix://" prefix to get the filesystem path
      DOCKER_SOCK_PATH="${_ctx_endpoint#unix://}"
    else
      echo "Warning: ENABLE_DOCKER=1 but no DOCKER_HOST set and 'docker context' unavailable." >&2
    fi
    unset _ctx_endpoint
  fi
fi
# If DOCKER_SOCK_PATH is set, get its parent directory.
# Otherwise use a non-existent sentinel path so (subpath ...) in the
# sandbox profile becomes a no-op deny.
if [[ -n "$DOCKER_SOCK_PATH" ]]; then
  DOCKER_SOCK_DIR_PARAM="$(dirname "$DOCKER_SOCK_PATH")"
else
  DOCKER_SOCK_DIR_PARAM="/private/var/no-docker-placeholder"
fi

# --- Filter PATH --------------------------------------------------------------
# Keep only entries under directories the sandbox allows for file-read.
# Node.js (libuv) uses posix_spawnp for spawnSync, which walks PATH entries
# calling execveat/stat on each. If a directory is denied by the sandbox, the
# kernel returns EPERM, and libuv treats that as a fatal error (unlike ENOENT
# or EACCES which just skip to the next entry). Filtering out inaccessible
# dirs prevents "spawnSync <cmd> EPERM" errors for programs like gemini-cli
# that call spawnSync('sysctl', ...) without a full path.

# Split PATH on ":" into an array
IFS=':' read -ra _path_parts <<< "$PATH"

_filtered_path=""
for _p in "${_path_parts[@]}"; do
  # Skip paths containing ~ (unexpanded home dir)
  if [[ "$_p" == *"~"* ]]; then
    continue
  fi
  # Skip paths under the real home directory
  if [[ "$_p" == "$HOST_HOME"* ]]; then
    continue
  fi
  # Only keep paths the sandbox allows for file-read
  case "$_p" in
    /usr/*|/usr|/bin/*|/bin|/sbin/*|/sbin|/opt/homebrew/*|/opt/homebrew|"$PROJECT_REAL"/*)
      ;; # allowed — fall through
    *)
      continue ;;
  esac
  # Append to filtered PATH with ":" separator
  if [[ -z "$_filtered_path" ]]; then
    _filtered_path="$_p"
  else
    _filtered_path="$_filtered_path:$_p"
  fi
done
unset _p _path_parts

# Ensure /bin is always in the sandbox PATH — essential POSIX utilities
# (/bin/bash, /bin/sh, /bin/cat, /bin/rm, etc.) live there and the filter
# above may not have kept it if the host PATH omitted /bin.
if [[ ":$_filtered_path:" != *":/bin:"* ]]; then
  _filtered_path="$_filtered_path:/bin"
fi

# Prepend shim dir so inner calls see the no-op sandbox-exec first.
# Done here (after filtering) because the HOST_HOME filter above would
# otherwise strip it — the shim lives under PROJECT_REAL which is a
# subdirectory of HOST_HOME.
_filtered_path="$SHIM_DIR:$_filtered_path"

# --- Build clean environment (allowlist) -----------------------------------
# Start with env -i so nothing leaks through implicitly.

_env=(
  # Sandbox detection (lets kosh CLI know we're inside a local sandbox)
  "KOSH_SANDBOX=1"
  "KOSH_SANDBOX_DIR=$PROJECT_REAL"

  # Identity & home (HOME redirected to project dir)
  "HOME=$PROJECT_REAL"
  "USER=${USER:-}"
  "LOGNAME=${LOGNAME:-${USER:-}}"
  "SHELL=${SHELL:-/bin/zsh}"

  # Executable resolution — host-home entries stripped above
  "PATH=$_filtered_path"

  # Temp dir (private to this project; /tmp and /var/tmp are denied)
  "TMPDIR=$PRIVATE_TMPDIR"

  # zsh here-documents use TMPPREFIX (defaults to /tmp/zsh) — redirect
  # into our private temp so it isn't blocked by the /tmp deny rule.
  "TMPPREFIX=$PRIVATE_TMPDIR/zsh"

  # Claude Code temp (override hardcoded /tmp/claude-<uid> into project-private temp)
  "CLAUDE_CODE_TMPDIR=$CLAUDE_CODE_TMPDIR"

  # Claude config (redirected to project dir)
  "CLAUDE_CONFIG_DIR=$PROJECT_REAL/.claude"

  # Locale
  "LANG=${LANG:-en_US.UTF-8}"

  # Terminal identity & capabilities
  "TERM=${TERM:-xterm-256color}"

  # macOS internals required by Cocoa/CoreFoundation and XPC
  "__CF_USER_TEXT_ENCODING=${__CF_USER_TEXT_ENCODING:-0x0:0:0}"
  "COMMAND_MODE=${COMMAND_MODE:-unix2003}"
  "XPC_FLAGS=${XPC_FLAGS:-0x0}"
  "XPC_SERVICE_NAME=${XPC_SERVICE_NAME:-0}"
)

# Optional pass-throughs: added only when set in the outer environment.
_optional=(
  # Terminal UX (color, pager, ls colors)
  COLORTERM TERM_PROGRAM TERM_PROGRAM_VERSION TERM_FEATURES TERM_SESSION_ID
  LC_TERMINAL LC_TERMINAL_VERSION
  ITERM_PROFILE ITERM_SESSION_ID
  LESS PAGER LS_COLORS LSCOLORS

  # Shell depth indicator
  SHLVL

  # Claude API authentication
  ANTHROPIC_AUTH_TOKEN
  ANTHROPIC_API_KEY
  ANTHROPIC_BASE_URL
  ANTHROPIC_MODEL
  ANTHROPIC_DEFAULT_OPUS_MODEL
  ANTHROPIC_DEFAULT_SONNET_MODEL

  # IBM BOB
  BOBSHELL_API_KEY

  # needed if Claude models hosted somewhere else
  CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS
  CLAUDE_CODE_DEFAULT_MODEL
  CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING

  # for LSP optimizatinons and Claude Code's built-in LSP client
  ENABLE_LSP_TOOL
  ENABLE_PROMPT_CACHING_1H

  # Codex etc
  OPENROUTER_API_KEY

  # Gemini
  GEMINI_API_KEY

  # # Node.js via NVM (needed if project uses Node)
  # NVM_DIR NVM_BIN NVM_INC NVM_CD_FLAGS
  # COREPACK_ENABLE_AUTO_PIN

  # # Python via Conda
  # CONDA_DEFAULT_ENV CONDA_PREFIX CONDA_EXE CONDA_PYTHON_EXE
  # CONDA_SHLVL CONDA_PROMPT_MODIFIER _CE_CONDA _CE_M

  # # Java via jenv
  # JENV_LOADED JENV_SHELL

  # # OpenTelemetry
  # OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE

  # # Machine/env tag (used in project config)
  # TEST_ENV_NAME
)

for _var in "${_optional[@]}"; do
  # ${!_var} looks up the value of the variable whose name is stored in _var
  _val="${!_var:-}"
  if [[ -n "$_val" ]]; then
    _env+=("$_var=$_val")
  fi
done

# SSH agent: opt-in only
if [[ "${ENABLE_SSH_AGENT:-}" == "1" && -n "${SSH_AUTH_SOCK:-}" ]]; then
  _env+=("SSH_AUTH_SOCK=$SSH_AUTH_SOCK")
fi

# Docker: opt-in only
if [[ "${ENABLE_DOCKER:-}" == "1" && -n "${DOCKER_HOST:-}" ]]; then
  _env+=("DOCKER_HOST=$DOCKER_HOST")
fi

# Additional sandboxed directory: pass the resolved real path through so
# tooling inside the sandbox (e.g., test-sandbox.sh) can locate it. Only
# exposed when actually configured — when unset, the env var stays absent.
if [[ -n "${SANDBOX_ADDITIONAL_DIR:-}" ]]; then
  _env+=("SANDBOX_ADDITIONAL_DIR=$SANDBOX_ADDITIONAL_REAL")
fi

# Skills directory: same conditional pass-through pattern.
if [[ -n "${SANDBOX_SKILLS_DIR:-}" ]]; then
  _env+=("SANDBOX_SKILLS_DIR=$SANDBOX_SKILLS_REAL")
fi

# --- Resource limits -------------------------------------------------------
# Limits are inherited by sandbox-exec and all descendant processes.
#
# File size: 512 MB max per file. Guards against runaway writes filling the
# disk. Value is in 512-byte blocks: 1048576 × 512 = 536870912 bytes (512 MB).
ulimit -f 1048576

# Open file descriptors: Node.js/libuv opens many fds for watchers and
# network connections. macOS default of 256 is too low; 4096 is generous
# without being unbounded.
ulimit -n 4096

# Max processes: caps fork-bomb style subprocess proliferation.
# Note: on macOS RLIMIT_NPROC is per-user (not per-subtree), so this limit
# applies to all processes running as this user. Set high enough not to
# interfere with normal use, but low enough to contain runaway spawning.
ulimit -u "${SANDBOX_MAX_PROCS:-2048}"

# Virtual memory / RSS: intentionally NOT set. V8 JIT reserves large virtual
# address ranges (often >4 GB) even for small workloads; any practical ulimit -v
# would crash Node.js. Memory over-consumption is best addressed at the OS
# level (swap pressure, jetsam) or via Node --max-old-space-size if needed.

# --- Launch ----------------------------------------------------------------
# Use absolute /usr/bin/sandbox-exec so our own call is NOT intercepted.
# cwd must be inside PROJECT_DIR (SANDBOX_DIR is read-denied inside the sandbox).
cd "$PROJECT_REAL"
/usr/bin/sandbox-exec \
  -f "$SANDBOX_PROFILE" \
  -D PROJECT_DIR="$PROJECT_REAL" \
  -D HOST_HOME="$HOST_HOME" \
  -D SANDBOX_DIR="$SANDBOX_REAL" \
  -D SSH_AGENT_DIR="$SSH_AGENT_DIR_PARAM" \
  -D CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}" \
  -D DOCKER_SOCK_DIR="$DOCKER_SOCK_DIR_PARAM" \
  -D SANDBOX_ADDITIONAL_DIR="$SANDBOX_ADDITIONAL_DIR_PARAM" \
  -D SANDBOX_SKILLS_DIR="$SANDBOX_SKILLS_DIR_PARAM" \
  env -i "${_env[@]}" \
  "$@"
