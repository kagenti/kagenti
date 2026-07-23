---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Skills

## Overview

**Skills** in Rossoctl are reusable capabilities stored as Kubernetes ConfigMaps and managed through the platform's REST API. They encapsulate domain expertise and workflows that agents can access on-demand. Skills are stored with the label `rossoctl.io/type=skill` and can include multiple files (code, documentation, configuration) that define their behavior.

Skills are a key component of the Rossoctl workload runtime, working alongside Agents and Tools in the platform architecture. While agents provide the reasoning and orchestration layer, and tools offer specific integrations, skills deliver specialized domain knowledge stored as ConfigMaps that can be retrieved and used by agents.

## Enabling Skills

Skills are a feature-flagged capability in Rossoctl and must be explicitly enabled before use. Two flags control the feature:

| Flag | Controls |
|------|----------|
| `featureFlags.skills` | Core skills management: import, list, delete skills; link skills to agents |
| `featureFlags.externalSkills` | External skill registry references (e.g. skillberry-store). Requires `skills` to also be true. |

The easiest way to enable both is the `--with-skills` flag described below.

### Using the Kind Setup Script

Pass `--with-skills` to enable both flags at once. It automatically enables `--with-backend` and `--with-ui`:

```bash
scripts/kind/setup-rossoctl.sh --with-skills
```

`--with-skills` also deploys an **in-cluster skillberry-store** pod and
**auto-enables autosync** against it (via the `rossoctl-skill-autosync-config`
ConfigMap), so skills sync with no external registry and no
`--skill-registry-allowed-hosts`. The store UI is browsable at
`http://skillberry-store.<domain>:8080`. Override the store image with the
`SKILLBERRY_STORE_IMAGE` / `SKILLBERRY_STORE_TAG` env vars (default tag `0.2.0`):

```bash
SKILLBERRY_STORE_TAG=0.2.1 scripts/kind/setup-rossoctl.sh --with-skills
```

To combine with other options, for example builds and locally-built images:

```bash
scripts/kind/setup-rossoctl.sh --with-skills --with-builds --build-images --skip-cluster
```

### Using the Rossoctl Installer

When using the installer, enable skills by modifying your values file (e.g., `charts/rossoctl/.secrets.yaml` or a custom values file):

```bash
cat <<EOF > /tmp/enable-flag-skills.yaml
featureFlags:
  skills: true
  externalSkills: true
EOF
```

Then run the installer:

```bash
./scripts/kind/setup-rossoctl.sh --with-all --rossoctl-values /tmp/enable-flag-skills.yaml
```

### Using Helm

When installing or upgrading Rossoctl with Helm directly:

```bash
helm upgrade --install rossoctl ./charts/rossoctl/ \
  -n rossoctl-system --create-namespace \
  --set featureFlags.skills=true \
  --set featureFlags.externalSkills=true \
  --set components.skillberryStore.enabled=true
```

`components.skillberryStore.enabled=true` deploys the in-cluster store and seeds
the autosync ConfigMap pointing at it (both default off). Override the image with
`--set skillberryStore.image.tag=0.2.1`. Omit it to use only an external registry.

To enable on an already-running cluster without full redeploy:

```bash
helm upgrade rossoctl ./charts/rossoctl/ \
  --reuse-values \
  --set featureFlags.skills=true \
  --set featureFlags.externalSkills=true \
  -n rossoctl-system
```

### Configuring skillberry-store Environment Variables

skillberry-store ships with a set of **plugins that manage the skills in the
store** — they create, evaluate, optimize, deduplicate, security-scan, and
generate documentation for skills, running inside the store process and
triggering automatically on skill lifecycle events (e.g. when a skill is added or
updated). They are *not* something agents or individual skills consume at
runtime; they are the store's own capabilities for curating its skill repository.

Most of these plugins call an LLM, so they read LLM configuration (provider,
model, API base URLs, and API keys) from environment variables on the **store
process at startup**. The in-cluster store starts with only the chart-managed
`SBS_*` / `ENABLE_UI` variables, so to enable the LLM-backed plugins you must
inject their configuration via `skillberryStore.extraEnv` — a list of standard
Kubernetes `core/v1` `EnvVar` entries, supporting both literal `value` and
`valueFrom` (`secretKeyRef` / `configMapKeyRef`). The exact variable names depend
on the LLM provider you select via `LLM_PROVIDER` (see the
[skillberry-store plugin docs](https://github.com/skillberry-ai/skillberry-store/blob/main/docs/plugins-installation.md)).

> **Keep secrets out of values files and Git.** Put non-sensitive configuration
> (provider name, model, endpoint URLs) as literal `value`s, but reference API
> keys and tokens from a Kubernetes Secret via `valueFrom.secretKeyRef`.

First create a Secret holding the sensitive values (do this out-of-band, not in a
checked-in file):

```bash
kubectl create secret generic skillberry-store-secrets -n rossoctl-system \
  --from-literal=rits-api-key="<your-key>" \
  --from-literal=third-party-api-key="<your-key>" \
  --from-literal=openai-api-key="<your-key>" \
  --from-literal=anthropic-auth-token="<your-token>"
```

Then write a values overlay referencing it. The variable **names** below are
illustrative of what a litellm/RITS-backed plugin typically expects — adjust to
match your plugin; do not commit real keys or endpoints:

```yaml
# /tmp/skillberry-env.yaml
skillberryStore:
  extraEnv:
    # --- non-sensitive config: literal values are fine ---
    - name: LLM_PROVIDER
      value: "litellm.ibm"
    - name: LLM_MODEL
      value: "rits/openai/gpt-oss-120b"
    - name: IBM_LITELLM_API_BASE
      value: "http://<your-litellm-host>:4000/"
    - name: ANTHROPIC_BASE_URL
      value: "https://<your-anthropic-gateway>"
    # --- secrets: pull from the Secret created above ---
    - name: RITS_API_KEY
      valueFrom:
        secretKeyRef:
          name: skillberry-store-secrets
          key: rits-api-key
    - name: IBM_THIRD_PARTY_API_KEY
      valueFrom:
        secretKeyRef:
          name: skillberry-store-secrets
          key: third-party-api-key
    - name: OPENAI_API_KEY
      valueFrom:
        secretKeyRef:
          name: skillberry-store-secrets
          key: openai-api-key
    - name: ANTHROPIC_AUTH_TOKEN
      valueFrom:
        secretKeyRef:
          name: skillberry-store-secrets
          key: anthropic-auth-token
```

Apply it with the Kind setup script via `--rossoctl-values` (it is passed straight
through to Helm as `--values`):

```bash
scripts/kind/setup-rossoctl.sh --with-backend --with-ui --with-skills --with-builds \
  --build-images --skill-registry-allowed-hosts "<your-allowed-host>" \
  --rossoctl-values /tmp/skillberry-env.yaml
```

…or directly with Helm:

```bash
helm upgrade --install rossoctl ./charts/rossoctl/ \
  -n rossoctl-system --create-namespace \
  --set featureFlags.skills=true \
  --set featureFlags.externalSkills=true \
  --set components.skillberryStore.enabled=true \
  -f /tmp/skillberry-env.yaml
```

The entries are appended to the store container after the chart-managed
variables. Verify they landed:

```bash
kubectl set env deploy/skillberry-store -n rossoctl-system --list
```

### Verifying Skills Are Enabled

After enabling the feature flag and restarting/upgrading your deployment:

1. **Check the UI**: Navigate to the Rossoctl UI at `http://rossoctl-ui.localtest.me:8080` (or your configured domain)
2. **Look for Skills Section**: The Skills management interface should now be visible in the navigation menu
3. **Verify Backend**: Check the backend logs to confirm skills routes are registered:
   ```bash
   kubectl logs -n rossoctl-system -l app.kubernetes.io/name=rossoctl-backend | grep "skills routes registered"
   ```

Once enabled, the Skills management interface will be accessible through the UI, allowing you to configure and deploy skills for your agents.

## Troubleshooting

### Skills not appearing after setup

If the skills feature was not enabled during initial setup (e.g., the `ROSSOCTL_FEATURE_FLAG_SKILLS` env var was set but `--with-skills` was not passed, or `--with-all` was used with an older script version), you can enable it without redeploying the full cluster:

```bash
helm upgrade rossoctl charts/rossoctl -n rossoctl-system \
  --set featureFlags.skills=true \
  --set openshift=false \
  -f charts/rossoctl/values.yaml
```

This triggers a rolling restart of the backend and UI pods with the flag enabled. Verify afterwards:

```bash
kubectl logs -n rossoctl-system -l app.kubernetes.io/name=rossoctl-backend | grep "skills routes registered"
```

## Accessing Skills via REST API

Skills are managed through the Rossoctl backend REST API. All endpoints require authentication.

### List Skills

List all skills in a namespace:

```bash
# List all skills
curl -X GET "http://rossoctl-backend/api/skills?namespace=rossoctl-system" \
  -H "Authorization: Bearer $TOKEN"

# Search skills by keyword
curl -X GET "http://rossoctl-backend/api/skills?namespace=rossoctl-system&q=code-review" \
  -H "Authorization: Bearer $TOKEN"
```

### Get Skill Details

Retrieve detailed information about a specific skill, including all files:

```bash
curl -X GET "http://rossoctl-backend/api/skills/rossoctl-system/code-review" \
  -H "Authorization: Bearer $TOKEN"
```

### Create a Skill

Create a new skill from files:

```bash
curl -X POST "http://rossoctl-backend/api/skills" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "code-review",
    "namespace": "rossoctl-system",
    "description": "Automated code review skill",
    "category": "development",
    "files": {
      "SKILL.md": "# Code Review Skill\n\nThis skill performs automated code reviews...",
      "scripts/review.py": "# Python code for review logic..."
    }
  }'
```

**Note**: `SKILL.md` is mandatory and must be included in the files dictionary.

### Delete a Skill

Remove a skill from the cluster:

```bash
curl -X DELETE "http://rossoctl-backend/api/skills/rossoctl-system/code-review" \
  -H "Authorization: Bearer $TOKEN"
```

## Using Skills in Python

Agents can interact with skills using standard HTTP libraries:

```python
import httpx

# List available skills
async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://rossoctl-backend/api/skills",
        params={"namespace": "rossoctl-system"},
        headers={"Authorization": f"Bearer {token}"}
    )
    skills = response.json()["items"]

# Get skill details
async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://rossoctl-backend/api/skills/rossoctl-system/code-review",
        headers={"Authorization": f"Bearer {token}"}
    )
    skill_detail = response.json()
    # Access skill files
    for file in skill_detail["files"]:
        print(f"File: {file['path']}, Size: {file['size']}")
```

## Configuring Skills via UI

### Prerequisites

Before configuring skills, ensure you have:

1. A running Rossoctl installation (see [Installation Guide](./install.md))
2. Access to the Rossoctl UI
3. Appropriate permissions to manage skills (ROLE_OPERATOR for create/delete, ROLE_VIEWER for read)

### Accessing Skills in the UI

1. **Navigate to the Rossoctl UI**
   ```bash
   open http://rossoctl-ui.localtest.me:8080
   ```

2. **Login** with your credentials (use `show-services.sh` to retrieve credentials if needed)

3. **Access the Skills Section**
   - From the main dashboard, navigate to the Skills management interface
   - Here you can view available skills, their status, and configuration options
   - Skills are displayed with their category, description, and usage count

### Troubleshooting and Additional Help

For additional support:

- Check the [Troubleshooting Guide](./troubleshooting.md)
- Review [Component Details](./components.md)
- See the backend implementation: `rossoctl/backend/app/routers/skills.py`
