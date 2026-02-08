# Claude Code Configuration

This directory contains Claude Code configuration for the Kagenti project.

## Directory Structure

```
.claude/
├── README.md           # This file
├── settings.json       # Project-level settings (committed)
├── settings.local.json # Local user settings (git-ignored)
├── commands/           # Custom slash commands
│   └── commit.md       # /commit command for PR conventions
└── skills/             # AI Ops skills
    ├── hypershift/     # AWS HyperShift cluster management
    ├── kind/           # Local Kind cluster management
    ├── kagenti/        # Platform deployment
    ├── k8s/            # Kubernetes debugging
    └── local/          # Development workflows
```

## Settings Files

### settings.json (Committed)

Project-level permissions that apply to all team members:

**Allowed (safe read-only operations):**
- Git: status, log, diff, show, branch, fetch
- Kubernetes: get, describe, logs, top, config, cluster-info
- Helm: list, status, get, show, template, history
- OpenShift: get, describe, logs, whoami, project
- GitHub CLI: pr/issue list/view, run list/view, api
- Docker: images, ps, inspect, logs, stats
- Development: make lint/test, uv run pytest, pre-commit
- General: ls, cat, find, grep, tree, jq, yq

**Denied (dangerous operations):**
- `rm -rf` - Recursive deletion
- `git push --force` - Force push
- `git reset --hard` - Hard reset
- `kubectl delete namespace` - Namespace deletion
- `helm uninstall` - Helm release deletion
- `kind delete cluster` - Cluster deletion
- `docker system prune` - Docker cleanup
- `sudo` - Privileged commands

### settings.local.json (Git-ignored)

Create this file for your own auto-approved commands:

```json
{
  "permissions": {
    "allow": [
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "Bash(git push:*)",
      "Bash(kubectl apply:*)",
      "Bash(kubectl delete:*)",
      "Bash(helm upgrade:*)",
      "Bash(./local-testing/*:*)"
    ]
  }
}
```

Claude Code merges both files, with local settings taking precedence.

## Using Skills

Skills are automatically discovered. Reference them naturally:

```
> Use k8s/health to check platform status
> Use kind/cluster to deploy locally
> Use hypershift/cluster for AWS testing
```

Or ask naturally:

```
> Check if all pods are healthy
> Deploy Kagenti to a local Kind cluster
> Debug the failing keycloak pod
```

## Documentation

See [docs/ai-ops/](../docs/ai-ops/) for:
- [Quick Start](../docs/ai-ops/README.md)
- [Claude Code Setup](../docs/ai-ops/quickstart-claude-code.md)
- [Kind Local Testing](../docs/ai-ops/quickstart-kind.md)
- [HyperShift Cloud Testing](../docs/ai-ops/quickstart-hypershift.md)
