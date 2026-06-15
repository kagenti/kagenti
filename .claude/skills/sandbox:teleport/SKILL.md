# Teleport: Local Claude Code → Kagenti Sandbox

Delegate tasks to a remote Claude Code or Hermes agent running in an
isolated Kagenti OpenShell sandbox on Kind or HyperShift. The agent has
LLM access via LiteLLM (MaaS or Vertex AI) but cannot see real API keys.

## Prerequisites

- Kagenti cluster with OpenShell gateway (`kubectl get pods -n team1 | grep openshell`)
- Sandbox CRD installed (`kubectl get crd sandboxes.agents.x-k8s.io`)
- LiteLLM proxy running (`kubectl get pods -n team1 | grep litellm`)

## Quick Delegation (one-shot)

Send a task to a sandbox agent and get the result back:

```bash
scripts/openshell/teleport-session.sh --full "Analyze this error and suggest a fix: <paste error>"
```

## Spawn a Persistent Session

Create a sandbox that stays running. Send multiple prompts, then clean up:

```bash
# Spawn (bare sandbox, no local context)
SESSION=$(scripts/openshell/teleport-session.sh --spawn 2>/dev/null | tail -1)

# Send tasks
scripts/openshell/teleport-session.sh --session $SESSION --prompt "your task here"

# Cleanup when done
scripts/openshell/teleport-session.sh --cleanup --session $SESSION
```

## Teleport Local Context

Package CLAUDE.md and skills into the sandbox so the remote agent knows
the project:

```bash
# Package + deploy + prompt
SESSION=$(scripts/openshell/teleport-session.sh --package 2>/dev/null | tail -1)
scripts/openshell/teleport-session.sh --deploy --session $SESSION
scripts/openshell/teleport-session.sh --session $SESSION --prompt "Read CLAUDE.md and run the E2E tests"
scripts/openshell/teleport-session.sh --cleanup --session $SESSION
```

Include specific skills:

```bash
TELEPORT_SKILLS="sandbox:teleport,graph-loop" scripts/openshell/teleport-session.sh --package
```

## Use Hermes Agent Instead of Claude Code

```bash
kubectl exec deploy/nemoclaw-hermes -n team1 -- hermes chat -q "your task here"
```

Hermes uses the same LiteLLM proxy → Vertex AI Claude path but with its
own agent framework (17 tools, file access, code execution).

## LiteLLM Model Configuration

### Using MaaS (default, free tier)

Models are pre-configured via `.env.maas`. Claude model names route to
llama-scout-17b via MaaS.

### Using Vertex AI (real Claude)

To use real Anthropic Claude models via your Vertex AI project:

1. Create credentials secret:
```bash
kubectl create secret generic vertex-ai-credentials \
  --from-file=credentials.json=$HOME/.config/gcloud/application_default_credentials.json \
  -n team1
```

2. Mount into LiteLLM and add model config — see `docs/agentic-runtime/teleport.md`
   for the full LiteLLM Vertex AI setup.

3. Available Vertex AI model IDs:
   - `vertex_ai/claude-sonnet-4@20250514` (Sonnet 4, deprecated)
   - `vertex_ai/claude-sonnet-4-6` (Sonnet 4.6, latest)
   - `vertex_ai/claude-haiku-4-5@20251001` (Haiku 4.5)
   - `vertex_ai/claude-opus-4-8` (Opus 4.8)

## Credential Isolation

The sandbox only sees a LiteLLM virtual key (`ANTHROPIC_AUTH_TOKEN`).
Real API keys (MaaS, Vertex AI, OpenRouter) stay in LiteLLM's pod.

## Agent Budget Control

LiteLLM supports per-key budgets via virtual keys:

```bash
# Set max $5 budget on the sandbox virtual key
curl -X POST http://localhost:4000/key/update \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"key": "sk-ZSFBf...", "max_budget": 5.0}'
```

Budget enforcement happens at the LiteLLM proxy level — the sandbox
agent is unaware of limits. Requests exceeding budget return 429.

See LiteLLM docs: https://docs.litellm.ai/docs/proxy/virtual_keys

## Actions

| Flag | Description |
|------|-------------|
| `--package` | Bundle local context into a ConfigMap |
| `--deploy` | Create sandbox with mounted context |
| `--spawn` | Create bare sandbox (no local context) |
| `--prompt "text"` | Send instruction to running sandbox |
| `--cleanup` | Delete sandbox and ConfigMap |
| `--full "text"` | All-in-one: package, deploy, prompt, cleanup |

## Options

| Flag | Default |
|------|---------|
| `--namespace <ns>` | `team1` |
| `--session <id>` | auto-generated |
| `--timeout <secs>` | `120` |

| Env Var | Description |
|---------|-------------|
| `TELEPORT_NS` | Target namespace |
| `TELEPORT_SKILLS` | Comma-separated skill names to include |

## Full Documentation

- Usage and architecture: `docs/agentic-runtime/teleport.md`
- Credential isolation diagram: `docs/agentic-runtime/teleport.md#credential-isolation`
- OpenShell fork analysis: `docs/research/openshell-fork-analysis.md`
- Composable agents design: `docs/research/composable-agents-design.md`
