# Developer Guides

This directory contains comprehensive development guides for working with Kagenti on different environments.

## Choose Your Environment

| Environment | Use Case | Guide |
|-------------|----------|-------|
| **Kind** | Local development, quick iteration, no cloud resources | [kind.md](./kind.md) |
| **HyperShift** | Create OpenShift clusters on AWS, CI testing, cloud-native features | [hypershift.md](./hypershift.md) |
| **OpenShift** | Standard RHOCP clusters, persistent environments | Under construction - see [Installation Guide](../install.md) |
| **Claude Code** | AI-assisted development with TDD, RCA, and debugging skills | [claude-code.md](./claude-code.md) |
| **Daily Commands** | Quick reference for daily/weekly Claude Code skills | [claude-code-daily-commands.md](./claude-code-daily-commands.md) |

## Quick Decision Tree

```
Do you have an OpenShift cluster?
├─ No → Use [Kind](./kind.md) (local Docker-based Kubernetes)
│
└─ Yes → Do you need to create the cluster?
         ├─ Yes → Use [HyperShift](./hypershift.md) (hosted control plane on AWS)
         └─ No → See [Installation Guide](../install.md) (OpenShift dev guide under construction)
```

## Environment Comparison

| Feature | Kind | OpenShift | HyperShift |
|---------|------|-----------|------------|
| **Entry Script** | `kind-full-test.sh` | `openshift-full-test.sh` | `hypershift-full-test.sh` |
| **SPIRE** | Vanilla | ZTWIM Operator | ZTWIM Operator |
| **Values File** | `dev_values.yaml` | `ocp_values.yaml` | `ocp_values.yaml` |
| **Cluster Lifecycle** | Persistent | Persistent | Create/Destroy |
| **AWS Required** | No | No | Yes |
| **Min OCP Version** | N/A | 4.19+ | 4.19+ |

## Common Setup (All Environments)

### Credentials Setup

Before deploying to any environment, create the secrets file:

```bash
# Copy the example file
cp deployments/envs/secret_values.yaml.example deployments/envs/.secret_values.yaml

# Edit with your values
vi deployments/envs/.secret_values.yaml
```

Required values in `.secret_values.yaml`:

```yaml
charts:
  kagenti:
    values:
      secrets:
        # Required for agent LLM features (weather-service chat, etc.)
        openaiApiKey: "sk-..."

        # Required for private repos and Shipwright builds
        githubUser: "your-username"
        githubToken: "ghp_..."

        # Optional: Slack integration
        slackBotToken: "xoxb-..."
        adminSlackBotToken: "xoxb-..."
```

### Alternative: Environment Variables

Instead of editing the file, you can set environment variables:

```bash
export OPENAI_API_KEY="sk-..."
export GITHUB_USER="your-username"
export GITHUB_TOKEN_VALUE="ghp_..."

# Force regeneration from env vars
rm -f deployments/envs/.secret_values.yaml
```

## Documentation Structure

```
docs/developer/
├── README.md                       # This file - overview and environment selection
├── kind.md                         # Kind (local Kubernetes) development guide
├── hypershift.md                   # HyperShift (hosted OpenShift on AWS) development guide
├── claude-code.md                  # Claude Code skills for TDD, RCA, and debugging
└── claude-code-daily-commands.md   # Daily/weekly skill quick reference
```

## Related Documentation

- [Installation Guide](../install.md) - Comprehensive installation options
- [Developer Guide](../dev-guide.md) - Git workflow, UI development
- [Components](../components.md) - Architecture and component details
- [Local Setup Scripts](../../.github/scripts/local-setup/README.md) - Script reference and quick commands (primary developer flow reference)
- [Claude Code Skills](../../.claude/skills/README.md) - Skill index and workflow diagrams
