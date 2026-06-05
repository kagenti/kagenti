# Teleport: Local Claude Code → Kagenti Sandbox

Package your local Claude Code context (CLAUDE.md, skills, settings) and deploy
it into a Kagenti OpenShell sandbox with full isolation (Landlock, seccomp, netns).
Execute instructions remotely and retrieve results.

## Prerequisites

- Kagenti cluster with OpenShell gateway deployed (Kind or HyperShift)
- Sandbox CRD installed (`kubectl get crd sandboxes.agents.x-k8s.io`)
- LiteLLM proxy running in the target namespace
- `litellm-virtual-keys` secret with `api-key`

## Quick Start

### Spawn a remote session (no local context)

```bash
scripts/openshell/teleport-session.sh --spawn
# Output: session ID (e.g., 00ed517d)

scripts/openshell/teleport-session.sh --session 00ed517d --prompt "your task"
scripts/openshell/teleport-session.sh --cleanup --session 00ed517d
```

### Teleport local context + prompt (all-in-one)

```bash
scripts/openshell/teleport-session.sh --full "What project is this? Summarize CLAUDE.md"
```

## Step-by-Step Usage

### 1. Package context into a ConfigMap

```bash
SESSION_ID=$(scripts/openshell/teleport-session.sh --package)
echo "Session: $SESSION_ID"
```

What gets packaged:
- `CLAUDE.md` from repo root
- Selected skills via `TELEPORT_SKILLS` env var (comma-separated names)
- `.claude/settings.json` (sensitive fields stripped)

Size limit: 800KB total (ConfigMap max ~1MB).

To include skills:

```bash
TELEPORT_SKILLS="sandbox:teleport,graph-loop" \
  scripts/openshell/teleport-session.sh --package
```

### 2. Deploy sandbox with context

```bash
scripts/openshell/teleport-session.sh --deploy --session $SESSION_ID
```

Creates a Sandbox CR with:
- Base image: `ghcr.io/nvidia/openshell-community/sandboxes/base:latest`
- Claude CLI pre-installed
- Context mounted and unpacked into `$HOME` (`/sandbox`)
- LiteLLM virtual key injected via K8s secret (real API keys never exposed)

### 3. Send instruction

```bash
scripts/openshell/teleport-session.sh --session $SESSION_ID \
  --prompt "Review the skills in .claude/skills/ and list the top 5 most useful ones"
```

Executes `claude --print --bare` inside the sandbox pod. The remote Claude Code
has access to the teleported CLAUDE.md and skills.

### 4. Clean up

```bash
scripts/openshell/teleport-session.sh --cleanup --session $SESSION_ID
```

Deletes the Sandbox CR, ConfigMap, and waits for pod termination.

## What Gets Teleported

| Item | Source | Destination in sandbox |
|------|--------|-----------------------|
| CLAUDE.md | `$REPO_ROOT/CLAUDE.md` | `$HOME/CLAUDE.md` |
| Skills | `.claude/skills/<name>/SKILL.md` | `$HOME/.claude/skills/<name>/SKILL.md` |
| Settings | `.claude/settings.json` | `$HOME/.claude/settings.json` |

## Actions

| Flag | Description |
|------|-------------|
| `--package` | Bundle local context into a ConfigMap |
| `--deploy` | Create sandbox with mounted context |
| `--spawn` | Create bare sandbox (no local context) |
| `--prompt "text"` | Send instruction and get result |
| `--cleanup` | Delete sandbox and ConfigMap |
| `--full "text"` | All-in-one: package → deploy → prompt → cleanup |

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--namespace <ns>` | Target namespace | `team1` |
| `--session <id>` | Session ID (auto-generated for `--package`/`--spawn`) | — |
| `--timeout <secs>` | Prompt timeout | `120` |

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEPORT_NS` | Target namespace | `team1` |
| `TELEPORT_SKILLS` | Comma-separated skill names to include | — (none) |

## Credential Isolation

The sandbox only sees a LiteLLM virtual key (`ANTHROPIC_AUTH_TOKEN`), never
real API keys. `ANTHROPIC_BASE_URL` points to the LiteLLM proxy, which
routes to the actual provider (MaaS, Vertex AI, etc.).

## Limitations

- **One-shot execution**: each `--prompt` is a single Claude Code invocation
  (`claude --print --bare`). No multi-turn or persistent sessions yet.
- **ConfigMap size**: context must be under 800KB. For larger bundles, PVC
  support is planned.
- **No result sync**: changes made by Claude Code inside the sandbox are not
  synced back to your local machine. Use `--prompt` to ask for specific outputs.

## Full documentation

See `docs/agentic-runtime/teleport.md` for architecture diagrams, test matrix,
and credential isolation details.
