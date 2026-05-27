# Skills

## Overview

**Skills** in Kagenti are reusable capabilities stored as Kubernetes ConfigMaps and managed through the platform's REST API. They encapsulate domain expertise and workflows that agents can access on-demand. Skills are stored with the label `kagenti.io/type=skill` and can include multiple files (code, documentation, configuration) that define their behavior.

Skills are a key component of the Kagenti workload runtime, working alongside Agents and Tools in the platform architecture. While agents provide the reasoning and orchestration layer, and tools offer specific integrations, skills deliver specialized domain knowledge stored as ConfigMaps that can be retrieved and used by agents.

## Enabling Skills

Skills are currently a feature flag in Kagenti and must be explicitly enabled before use. The method for enabling skills depends on your deployment approach:

### Using Kind and OpenShift Setup Script

When using the `scripts/kind/setup-kagenti.sh` script, skills can be enabled by setting the environment variable before running the script:

```bash
# Enable skills with the setup script
export KAGENTI_FEATURE_FLAG_SKILLS=true
./scripts/kind/setup-kagenti.sh --with-backend --with-ui
```

**Note**: The `--with-backend` and `--with-ui` flags are required to deploy the Kagenti backend and UI components where the skills feature is used.

### Using Ansible Installer

When using the Ansible installer, enable skills by modifying your values file (e.g., `deployments/envs/.secret_values.yaml` or a custom values file):

```yaml
charts:
  kagenti:
    values:
      featureFlags:
        skills: true
```

Then run the installer:

```bash
cd deployments/ansible
./run-install.sh
```

### Using Helm

When installing or upgrading Kagenti with Helm, enable skills by setting the feature flag in your values:

```bash
# Using --set flag
helm upgrade --install kagenti ./charts/kagenti/ \
  -n kagenti-system --create-namespace \
  --set featureFlags.skills=true
```

### Verifying Skills Are Enabled

After enabling the feature flag and restarting/upgrading your deployment:

1. **Check the UI**: Navigate to the Kagenti UI at `http://kagenti-ui.localtest.me:8080` (or your configured domain)
2. **Look for Skills Section**: The Skills management interface should now be visible in the navigation menu
3. **Verify Backend**: Check the backend logs to confirm skills routes are registered:
   ```bash
   kubectl logs -n kagenti-system -l app.kubernetes.io/name=kagenti-backend | grep "skills routes registered"
   ```

Once enabled, the Skills management interface will be accessible through the UI, allowing you to configure and deploy skills for your agents.

## Troubleshooting

### Skills not appearing after setup

If the skills feature was not enabled during initial setup (e.g., the `KAGENTI_FEATURE_FLAG_SKILLS` env var was set but `--with-skills` was not passed, or `--with-all` was used with an older script version), you can enable it without redeploying the full cluster:

```bash
helm upgrade kagenti charts/kagenti -n kagenti-system \
  --set featureFlags.skills=true \
  --set openshift=false \
  -f charts/kagenti/values.yaml
```

This triggers a rolling restart of the backend and UI pods with the flag enabled. Verify afterwards:

```bash
kubectl logs -n kagenti-system -l app.kubernetes.io/name=kagenti-backend | grep "skills routes registered"
```

## Accessing Skills via REST API

Skills are managed through the Kagenti backend REST API. All endpoints require authentication.

### List Skills

List all skills in a namespace:

```bash
# List all skills
curl -X GET "http://kagenti-backend/api/skills?namespace=kagenti-system" \
  -H "Authorization: Bearer $TOKEN"

# Search skills by keyword
curl -X GET "http://kagenti-backend/api/skills?namespace=kagenti-system&q=code-review" \
  -H "Authorization: Bearer $TOKEN"
```

### Get Skill Details

Retrieve detailed information about a specific skill, including all files:

```bash
curl -X GET "http://kagenti-backend/api/skills/kagenti-system/code-review" \
  -H "Authorization: Bearer $TOKEN"
```

### Create a Skill

Create a new skill from files:

```bash
curl -X POST "http://kagenti-backend/api/skills" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "code-review",
    "namespace": "kagenti-system",
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
curl -X DELETE "http://kagenti-backend/api/skills/kagenti-system/code-review" \
  -H "Authorization: Bearer $TOKEN"
```

## Using Skills in Python

Agents can interact with skills using standard HTTP libraries:

```python
import httpx

# List available skills
async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://kagenti-backend/api/skills",
        params={"namespace": "kagenti-system"},
        headers={"Authorization": f"Bearer {token}"}
    )
    skills = response.json()["items"]

# Get skill details
async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://kagenti-backend/api/skills/kagenti-system/code-review",
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

1. A running Kagenti installation (see [Installation Guide](./install.md))
2. Access to the Kagenti UI
3. Appropriate permissions to manage skills (ROLE_OPERATOR for create/delete, ROLE_VIEWER for read)

### Accessing Skills in the UI

1. **Navigate to the Kagenti UI**
   ```bash
   open http://kagenti-ui.localtest.me:8080
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
- See the backend implementation: `kagenti/backend/app/routers/skills.py`
