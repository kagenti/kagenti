---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Teleport: Remote Claude Code Execution in OpenShell Sandboxes

Teleport packages your local Claude Code context (CLAUDE.md, skills, settings)
into a Rossoctl OpenShell sandbox and executes prompts remotely with full
isolation (Landlock, seccomp, network namespace, OPA policy).

## Prerequisites

- **kubectl** configured for your Kind or HyperShift cluster
- **Sandbox CRD** installed (`agents.x-k8s.io/v1alpha1`)
- **OpenShell gateway** running (`openshell-server` pod in target namespace)
- **LiteLLM proxy** running for LLM access (`litellm-model-proxy` in target namespace)

Check readiness:

```bash
# Sandbox CRD installed?
kubectl api-resources | grep sandboxes

# Gateway running?
kubectl get pods -n team1 -l app.kubernetes.io/name=openshell --no-headers

# LiteLLM running?
kubectl get pods -n team1 -l app=litellm-model-proxy --no-headers
```

## Quick Start

### Spawn a remote session (no local context)

Create a bare sandbox and delegate tasks to it:

```bash
# Spawn a sandbox
scripts/openshell/teleport-session.sh --spawn
# Output: session ID (e.g., 00ed517d)

# Send prompts
scripts/openshell/teleport-session.sh --session 00ed517d --prompt "What is 2+2?"

# Send more prompts (same sandbox)
scripts/openshell/teleport-session.sh --session 00ed517d --prompt "List files in /etc"

# Cleanup when done
scripts/openshell/teleport-session.sh --cleanup --session 00ed517d
```

### Teleport local context + prompt (all-in-one)

Packages your CLAUDE.md and skills, deploys, prompts, cleans up:

```bash
scripts/openshell/teleport-session.sh --full "What project is described in CLAUDE.md?"
```

## Step-by-Step Usage

### 1. Package context

Bundles CLAUDE.md, settings.json, and selected skills into a ConfigMap:

```bash
scripts/openshell/teleport-session.sh --package
# Output: 8-char session ID (e.g., a3da31dd)
```

To include specific skills:

```bash
TELEPORT_SKILLS="sandbox:teleport,graph-loop" \
  scripts/openshell/teleport-session.sh --package
```

### 2. Deploy sandbox

Creates a Sandbox CR with the packaged context mounted:

```bash
scripts/openshell/teleport-session.sh --deploy --session a3da31dd
```

This creates:
- A Sandbox CR named `teleport-a3da31dd`
- A pod with the OpenShell base image (`ghcr.io/nvidia/openshell-community/sandboxes/base`)
- ConfigMap mounted at `/workspace/.claude-context`
- Context unpacked to `$HOME` (CLAUDE.md, .claude/skills/, .claude/settings.json)
- `ANTHROPIC_BASE_URL` pointing to LiteLLM proxy
- `ANTHROPIC_AUTH_TOKEN` from `litellm-virtual-keys` secret

### 3. Send prompts

```bash
scripts/openshell/teleport-session.sh --session a3da31dd \
  --prompt "List the Kubernetes namespaces mentioned in CLAUDE.md"
```

Claude Code runs inside the sandbox with:
- `claude --print --bare --model claude-sonnet-4-20250514`
- Read-only access to the teleported context
- Network isolated (OPA egress policy)
- Filesystem isolated (Landlock)

### 4. Cleanup

Deletes the Sandbox CR, pod, and ConfigMap:

```bash
scripts/openshell/teleport-session.sh --cleanup --session a3da31dd
```

## Actions

| Flag | Description |
|------|-------------|
| `--package` | Bundle local context into a ConfigMap |
| `--deploy` | Create sandbox with mounted context (requires `--session`) |
| `--spawn` | Create bare sandbox without local context |
| `--prompt "text"` | Send instruction to running sandbox (requires `--session`) |
| `--cleanup` | Delete sandbox and ConfigMap (requires `--session`) |
| `--full "text"` | All-in-one: package, deploy, prompt, cleanup |

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--namespace <ns>` | Target K8s namespace | `team1` |
| `--session <id>` | Session ID (auto-generated for `--package`/`--spawn`) | — |
| `--timeout <secs>` | Prompt timeout | `120` |

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEPORT_NS` | Target namespace | `team1` |
| `TELEPORT_SKILLS` | Comma-separated skill names to include | — (none) |

## What Gets Teleported

| Item | Source | Destination in sandbox |
|------|--------|-----------------------|
| CLAUDE.md | Repo root | `$HOME/CLAUDE.md` |
| settings.json | `.claude/settings.json` (secrets stripped) | `$HOME/.claude/settings.json` |
| Skills | `.claude/skills/<name>/SKILL.md` (selected via `TELEPORT_SKILLS`) | `$HOME/.claude/skills/<name>/SKILL.md` |

**Size limit**: 800 KB total (ConfigMap max ~1 MB). If exceeded, reduce skills
or use fewer context files.

**Not teleported**: memory files, conversation history, workspace files,
git state. This is a one-shot context transfer, not a session migration.

## Credential Isolation

The sandbox never sees real API keys. LiteLLM virtual keys provide a
security boundary between the sandbox and the actual LLM provider:

```
Your machine                    Kind/HyperShift cluster
────────────                    ──────────────────────
                                litellm-proxy-secret (rossoctl-system)
                                  └─ master-key: sk-real-master-key
                                  └─ .env.maas: MAAS_API_KEY=real-key
                                         │
                                    LiteLLM Proxy
                                         │
                                litellm-virtual-keys (team1)
                                  └─ api-key: sk-ZSFBf... (virtual)
                                         │
                                    Sandbox Pod
                                  └─ ANTHROPIC_AUTH_TOKEN=sk-ZSFBf... (virtual)
                                  └─ ANTHROPIC_BASE_URL=http://litellm-model-proxy:4000
```

What the sandbox sees:
- `ANTHROPIC_BASE_URL` — points to LiteLLM proxy, not to any provider
- `ANTHROPIC_AUTH_TOKEN` — a LiteLLM virtual key, not the real API key

What the sandbox **cannot** see:
- Real MaaS/Vertex AI API keys (in `litellm-proxy-secret`)
- LiteLLM master key
- Any `OPENAI_API_KEY`, `GOOGLE_*`, or `VERTEX_*` credentials

This means you can use Claude models (via LiteLLM → MaaS/Vertex) in
sandbox sessions without exposing your real credentials to the agent.

## How It Works

```
Local machine                     Kind/HyperShift cluster
─────────────                     ──────────────────────
CLAUDE.md ─┐
skills/  ──┼─→ ConfigMap ──→ Sandbox CR ──→ Pod
settings ──┘      │              │            │
                  │              │            ├─ supervisor (Landlock, seccomp)
                  │              │            ├─ claude --print --bare
                  │              │            └─ ANTHROPIC_BASE_URL → LiteLLM
                  │              │
                  └──────────────┴─→ cleanup deletes both
```

The sandbox pod runs Claude Code via `claude --print --bare`, which:
- Skips CLAUDE.md auto-discovery (context loaded via `--bare`)
- Uses the LiteLLM proxy as the LLM backend
- Has no network access except to LiteLLM (OPA policy)
- Runs as non-root user (uid 998) in the sandbox container

## Claude Code Skill

Use `/sandbox:teleport` in Claude Code for guided teleport workflow.

## Testing

Run T7 teleport tests:

```bash
# Without LLM (infrastructure only):
uv run pytest rossoctl/tests/e2e/openshell/test_T7_1_teleport.py -v

# With LLM (full lifecycle including prompt):
OPENSHELL_LLM_AVAILABLE=true \
  uv run pytest rossoctl/tests/e2e/openshell/test_T7_1_teleport.py -v
```

Test coverage (12 tests):

| Test | What it validates |
|------|-------------------|
| `test_teleport__script_exists` | Script exists and is executable |
| `test_teleport__package_creates_configmap` | ConfigMap created with session ID |
| `test_teleport__cleanup_removes_resources` | ConfigMap deleted after cleanup |
| `test_teleport__full_lifecycle` | Package → deploy → verify CLAUDE.md → prompt → cleanup |
| `test_teleport__full_mode` | `--full` flag runs entire lifecycle |
| `test_teleport__skills_packaged` | `TELEPORT_SKILLS` includes skills in ConfigMap |
| `test_teleport__spawn_creates_sandbox` | `--spawn` creates running sandbox, responds to prompts |
| `test_teleport__spawn_credential_isolation` | Only LiteLLM virtual key visible, no real API keys |
| `test_teleport__hermes_responds` | Hermes chat returns response via LiteLLM |
| `test_teleport__hermes_uses_litellm` | Hermes env vars point to LiteLLM proxy |
| `test_teleport__no_action` | Script fails without action flag |
| `test_teleport__deploy_without_session` | Deploy requires `--session` |
| `test_teleport__prompt_without_session` | Prompt requires `--session` |
| `test_teleport__cleanup_without_session` | Cleanup requires `--session` |

## Example: Delegating a GitHub Issue

Solve a GitHub issue by delegating analysis to a sandbox agent:

```bash
# One-shot: teleport context and ask the sandbox to analyze an issue
scripts/openshell/teleport-session.sh --full \
  "Read CLAUDE.md. GitHub issue #1132 says the feature flag endpoint path
   '/api/config/features' in the docs is incorrect. Check what the actual
   path should be based on the project structure. Report your finding."
```

For iterative work, use a persistent session:

```bash
# Spawn a session
SESSION=$(scripts/openshell/teleport-session.sh --spawn 2>/dev/null | tail -1)

# Send multiple prompts
scripts/openshell/teleport-session.sh --session $SESSION \
  --prompt "List all Python files that define FastAPI routes"

scripts/openshell/teleport-session.sh --session $SESSION \
  --prompt "What endpoints does the config router expose?"

# Cleanup
scripts/openshell/teleport-session.sh --cleanup --session $SESSION
```

**Limitation**: The sandbox only has teleported context (CLAUDE.md, skills,
settings), not the full git repo. For source code analysis, the agent can
only reason about what's described in CLAUDE.md. Full repo access requires
a PVC-backed workspace (future).

## Using Hermes Agent

Hermes (Nous Research) runs as a persistent deployment with its own tool
ecosystem (17 tools: file access, code execution, memory, browser).

```bash
# Quick query
kubectl exec deploy/nemoclaw-hermes -n team1 -- \
  timeout 30 hermes chat -q "What is the capital of France?"

# Longer task with tool use
kubectl exec deploy/nemoclaw-hermes -n team1 -- \
  timeout 60 hermes chat -q "Write a Python function that calculates fibonacci numbers"
```

Hermes uses the same LiteLLM proxy → Vertex AI path as Claude Code sandboxes.
It identifies itself as "Hermes Agent by Nous Research" even when the
underlying LLM is Claude.

## Vertex AI Setup (Real Claude Models)

By default, LiteLLM routes `claude-sonnet-4-20250514` through MaaS
(llama-scout-17b). To use real Anthropic Claude via Vertex AI:

**1. Create credentials secret from your GCP application default credentials:**

```bash
kubectl create secret generic vertex-ai-credentials \
  --from-file=credentials.json=$HOME/.config/gcloud/application_default_credentials.json \
  -n team1
```

**2. Mount into LiteLLM deployment:**

```bash
kubectl patch deploy litellm-model-proxy -n team1 --type=json -p='[
  {"op":"add","path":"/spec/template/spec/volumes/-",
   "value":{"name":"vertex-creds","secret":{"secretName":"vertex-ai-credentials"}}},
  {"op":"add","path":"/spec/template/spec/containers/0/volumeMounts/-",
   "value":{"name":"vertex-creds","mountPath":"/vertex-creds","readOnly":true}}
]'
```

**3. Add Vertex AI model to LiteLLM config:**

Update the `litellm-config` ConfigMap — change the `claude-sonnet-4-20250514`
model from MaaS to Vertex:

```yaml
- model_name: "claude-sonnet-4-20250514"
  litellm_params:
    model: "vertex_ai/claude-sonnet-4@20250514"
    vertex_project: "<your-gcp-project>"
    vertex_location: "us-east5"
    vertex_credentials: "/vertex-creds/credentials.json"
```

Available Vertex AI model IDs:
- `claude-sonnet-4@20250514` (Sonnet 4)
- `claude-sonnet-4-6` (Sonnet 4.6, latest)
- `claude-haiku-4-5@20251001` (Haiku 4.5)
- `claude-opus-4-8` (Opus 4.8)

**4. Restart LiteLLM:**

```bash
kubectl rollout restart deploy/litellm-model-proxy -n team1
```

The sandbox agents don't need any changes — they still use `ANTHROPIC_BASE_URL`
pointing to LiteLLM with the virtual key. Only LiteLLM knows about Vertex AI.

## Agent Budget Control

LiteLLM virtual keys support per-key spending limits:

```bash
# Set $5 max budget on the sandbox virtual key
MASTER_KEY=$(kubectl get secret litellm-proxy-secret -n rossoctl-system \
  -o jsonpath='{.data.master-key}' | base64 -d)

kubectl port-forward deploy/litellm-model-proxy -n team1 4000:4000 &
curl -X POST http://localhost:4000/key/update \
  -H "Authorization: Bearer $MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key": "sk-<virtual-key>", "max_budget": 5.0, "budget_duration": "30d"}'
```

Budget enforcement happens at LiteLLM — agents see HTTP 429 when budget
is exceeded. Per-agent budgets can be set by creating separate virtual keys
for each agent.

## Limitations

- **One-shot only**: no multi-turn conversation, no streaming
- **No session persistence**: pod deletion loses all state
- **CLI output includes tool calls**: `claude --print` outputs tool-call
  text alongside the answer
- **No workspace sync**: files created in the sandbox are lost on cleanup
- **ConfigMap size limit**: 800 KB for all context combined
