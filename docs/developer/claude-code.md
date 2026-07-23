---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Claude Code Development Guide

This guide covers using Claude Code skills for Rossoctl development workflows, prerequisites, and productivity tips for safe and effective AI-assisted development.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Service Account Setup](#service-account-setup)
- [Quick Reference](#quick-reference)
- [TDD Workflow](#tdd-workflow-tdd)
- [RCA Workflow](#rca-workflow-rca)
- [Other Useful Skills](#other-useful-skills)
- [How Rossoctl Makes Vibe Coding Safe](#how-rossoctl-makes-vibe-coding-safe)
- [Productivity Tips](#productivity-tips)

## Prerequisites

Claude Code skills interact with various CLI tools. Install these before using the workflows.

### Required Tools

| Tool | Purpose |
|------|---------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | AI development agent |
| git | Version control |
| gh | GitHub CLI (PRs, issues, CI) |
| kubectl | Kubernetes CLI |
| helm | Kubernetes package manager |
| jq | JSON processing |
| Python 3.11+ | E2E tests, installer |
| uv | Python package manager |
| Docker | Container runtime |
| Kind | Local Kubernetes |
| pre-commit | Git hooks |

### Additional Tools (HyperShift / OpenShift)

| Tool | Purpose |
|------|---------|
| oc | OpenShift CLI |
| AWS CLI | AWS resource management |

<details>
<summary><b>macOS</b></summary>

```bash
# Core tools
brew install git gh kubectl helm jq python@3.11 kind pre-commit

# Claude Code
npm install -g @anthropic-ai/claude-code

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Docker Desktop: https://docker.com/products/docker-desktop

# Pre-commit hooks
pre-commit install

# HyperShift / OpenShift (optional)
brew install openshift-cli awscli
```
</details>

<details>
<summary><b>Linux (Ubuntu/Debian)</b></summary>

```bash
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/

# Kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
sudo install kind /usr/local/bin/

# Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# GitHub CLI
sudo mkdir -p -m 755 /etc/apt/keyrings
wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt-get update && sudo apt-get install -y gh jq python3.11 python3.11-venv pre-commit

# Claude Code
npm install -g @anthropic-ai/claude-code

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Docker: https://docs.docker.com/engine/install/ubuntu/

# Pre-commit hooks
pre-commit install

# HyperShift / OpenShift (optional)
# oc CLI: https://console.redhat.com/openshift/downloads
# AWS CLI
sudo snap install aws-cli --classic
```
</details>

<details>
<summary><b>Linux (Fedora/RHEL)</b></summary>

```bash
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/

# Kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
sudo install kind /usr/local/bin/

# Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Other tools
sudo dnf install -y gh jq python3.11 pre-commit

# Claude Code
npm install -g @anthropic-ai/claude-code

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Docker/Podman: https://docs.docker.com/engine/install/fedora/

# Pre-commit hooks
pre-commit install

# HyperShift / OpenShift (optional)
sudo dnf install -y openshift-clients awscli2
```
</details>

### Verify Installation

```bash
# Check all required tools
for tool in git gh kubectl helm jq python3 uv docker kind pre-commit; do
  printf "%-15s " "$tool:" && command -v $tool >/dev/null 2>&1 && echo "OK" || echo "MISSING"
done
```

## Service Account Setup

Claude Code needs authenticated access to GitHub, Kubernetes clusters, and optionally AWS. Use scoped service accounts rather than your personal credentials.

<details>
<summary><b>GitHub CLI Authentication</b></summary>

```bash
# Login with minimal scopes needed for PR/issue/CI operations
gh auth login --scopes repo,read:org

# Verify
gh auth status
```

For CI-only access (read PRs, check status, download artifacts), a fine-grained PAT with read-only repo access is sufficient.

</details>

<details>
<summary><b>Kubernetes Cluster Authentication (Kind)</b></summary>

Kind clusters use the default kubeconfig. No special setup needed:

```bash
# Kind sets up kubeconfig automatically
export KUBECONFIG=~/.kube/config
kubectl cluster-info
```

</details>

<details>
<summary><b>Kubernetes Cluster Authentication (HyperShift)</b></summary>

HyperShift uses scoped credentials created during one-time setup:

```bash
# One-time: create scoped AWS IAM user + OCP service account
# (requires admin access, creates .env.rossoctl-hypershift-custom)
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh

# Daily use: source the scoped credentials
source .env.rossoctl-hypershift-custom

# Hosted cluster kubeconfig is at:
export KUBECONFIG=~/clusters/hcp/rossoctl-hypershift-custom-$USER/auth/kubeconfig
```

The scoped credentials have limited permissions - they can create/destroy hosted clusters but cannot modify the management cluster or access other AWS resources.

See the [HyperShift Development Guide](./hypershift.md) for full setup details.

</details>

<details>
<summary><b>Credential Rotation Script</b></summary>

Rotate service account credentials periodically or when compromised:

```bash
#!/usr/bin/env bash
# rotate-claude-credentials.sh - Rotate service accounts used by Claude Code

set -euo pipefail

echo "=== Rotating GitHub CLI token ==="
gh auth logout --hostname github.com 2>/dev/null || true
gh auth login --scopes repo,read:org
echo "GitHub CLI: rotated"

echo ""
echo "=== Rotating HyperShift credentials ==="
if [ -f .env.rossoctl-hypershift-custom ]; then
  # Re-run setup to create fresh IAM credentials
  ./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh
  echo "HyperShift credentials: rotated"
else
  echo "HyperShift credentials: skipped (no .env file found)"
fi

echo ""
echo "=== Verification ==="
gh auth status
kubectl cluster-info 2>/dev/null && echo "Kubernetes: connected" || echo "Kubernetes: not connected (OK if no cluster running)"
```

**Best practices:**
- Rotate credentials periodically (monthly recommended)
- Use scoped service accounts, never personal admin credentials
- The `.env.rossoctl-hypershift-custom` file is git-ignored - never commit it
- Claude Code's `.claude/settings.json` defines what commands are auto-approved vs denied

</details>

## Quick Reference

Start a Claude Code session from the repo root, then invoke skills as slash commands:

```bash
# Start Claude Code from the repo root
cd rossoctl/
claude

# Inside the Claude Code session, invoke skills:
> /tdd https://github.com/rossoctl/rossoctl/issues/123
> /rca https://github.com/rossoctl/rossoctl/actions/runs/12345
> /k8s:health
> /git:worktree my-feature origin/my-feature-branch
```

| Skill | Purpose | Entry Point |
|-------|---------|-------------|
| `/tdd` | Test-driven development | Issue URL, PR URL, or local task |
| `/rca` | Root cause analysis | CI failure URL or local investigation |
| `/git:worktree` | Parallel development | Create isolated worktrees |
| `/k8s:health` | Platform health check | Verify cluster state |
| `/k8s:pods` | Debug pod issues | Crashes, failures, networking |
| `/k8s:logs` | Query component logs | Search for errors |

## TDD Workflow (`/tdd`)

The TDD skill has three entry points and auto-selects the right sub-skill based on context.

### Entry Points

```
/tdd <GitHub issue URL>     # Issue-first: analyze, plan, implement
/tdd <GitHub PR URL>        # PR-first: fix CI failures, address reviews
/tdd <local description>    # Local-first: plan and implement locally
```

### Sub-Skills

| Sub-Skill | When Used | Environment |
|-----------|-----------|-------------|
| `tdd:ci` | Final validation, CI-driven iteration | No cluster needed |
| `tdd:kind` | Fast local feedback, reproduce Kind CI failures | Local Kind cluster |
| `tdd:hypershift` | Full cluster debugging, real OpenShift features | HyperShift cluster |

### Example: Fix a CI Failure from an Issue

```
/tdd https://github.com/rossoctl/rossoctl/issues/123
```

Claude Code will:
1. Analyze the issue and check for existing PRs
2. Research the codebase for relevant code
3. Create a worktree from upstream/main
4. Enter the TDD loop: implement, test, commit, push, wait for CI
5. Escalate to `tdd:hypershift` if CI fails 3+ times

### Example: Fix a Failing PR

```
/tdd https://github.com/rossoctl/rossoctl/pull/456
```

Claude Code will:
1. Check out the PR branch
2. Analyze CI failures
3. Fix and push, iterating until CI passes
4. Address PR review comments

### Example: Local Feature Development

```
/tdd Add health check endpoint to the backend
```

Claude Code will:
1. Plan the implementation
2. Create a worktree
3. Use `tdd:kind` for fast local iteration
4. Move to `tdd:ci` when local tests pass

### Iteration Levels (tdd:kind)

| Level | Speed | When |
|-------|-------|------|
| Level 1: Test only | Fastest | Code change doesn't need reinstall |
| Level 2: Reinstall + test | Medium | Helm values or chart changes |
| Level 3: Full cluster recreate | Slow | Cluster is broken or major changes |

### Iteration Levels (tdd:hypershift)

| Level | Speed | When |
|-------|-------|------|
| Level 0: Quick patch | Seconds | ConfigMap patch, pod restart |
| Level 1: Test only | Fast | No rebuild needed |
| Level 2: Rebuild images | Minutes | Code changes need new images (Shipwright) |
| Level 3: Full reinstall | ~25 min | Chart values or CRD changes |
| Level 4: Fresh cluster | ~50 min | Cluster is broken |

## RCA Workflow (`/rca`)

The RCA skill systematically investigates failures. It auto-selects the right sub-skill based on available resources.

### Entry Points

```
/rca <CI run URL>           # Investigate a CI failure
/rca <error description>    # Investigate a local issue
```

### Sub-Skills

| Sub-Skill | When Used | Resources |
|-----------|-----------|-----------|
| `rca:ci` | CI failure, no cluster available | CI logs and artifacts only |
| `rca:kind` | Kind E2E failure | Local Kind cluster |
| `rca:hypershift` | Inconclusive CI analysis, need live inspection | HyperShift cluster |

### Example: Investigate a CI Failure

```
/rca https://github.com/rossoctl/rossoctl/actions/runs/12345
```

Claude Code will:
1. **Gather**: Download CI logs and artifacts with `gh run`
2. **Isolate**: Find the first error and analyze the error chain
3. **Hypothesize**: Categorize (timing, config, auth, network, state, resource)
4. **Verify**: Search for patterns matching specific issue types
5. **Document**: Root cause with evidence and prevention strategy

If CI logs are insufficient, escalates to `rca:hypershift` for live cluster inspection.

### Example: Debug a Kind Test Failure

```
/rca Kind E2E test_weather_agent is failing with empty response
```

Claude Code will:
1. **Reproduce**: Deploy Kind cluster if not running
2. **Inspect**: Check pod status, crashes, events
3. **Diagnose**: Component logs, Ollama model, agent namespace
4. **Fix and verify**: Re-run the specific test

### RCA to TDD Handoff

After RCA identifies the root cause, it hands off to TDD for the fix:

```
RCA finds root cause -> /tdd:ci (commit fix, push, wait for CI)
                     -> /tdd:kind (fix locally first)
                     -> /tdd:hypershift (fix on live cluster)
```

## Other Useful Skills

### Cluster Health (`/k8s:health`)

Quick platform health check across all components:

```
/k8s:health
```

### Pod Debugging (`/k8s:pods`)

Debug pod crashes, failures, and networking:

```
/k8s:pods
```

### Git Worktrees (`/git:worktree`)

Create isolated worktrees for parallel development:

```
/git:worktree my-feature origin/my-feature-branch
```

## How Rossoctl Makes Vibe Coding Safe

Vibe coding (letting AI write and ship code with minimal manual review) is risky without guardrails. The Rossoctl repo uses a layered defense approach that makes Claude Code productive while preventing it from shipping bad code.

### Layer 1: Pre-commit Hooks (Instant Feedback)

Every commit Claude Code makes goes through pre-commit hooks:

- **`make lint`** - Pylint catches code quality issues
- **`ruff format`** - Consistent code formatting
- **`gitleaks`** - Blocks commits containing secrets, API keys, or credentials

Claude Code sees failures immediately and fixes them before pushing. This is the fastest feedback loop.

### Layer 2: Permission Guardrails (`.claude/settings.json`)

The project settings define what Claude Code can and cannot do:

- **Auto-approved**: Read-only operations (git, kubectl, helm, oc, gh, docker), test execution, builds, worktree operations
- **Denied**: `rm -rf`, `git push --force`, `kubectl delete -A`, `sudo`, `gh pr merge`, `git commit --amend`, destructive AWS operations
- **Requires approval**: Management cluster operations, cluster create/destroy

This means Claude Code can freely debug and iterate but cannot accidentally destroy infrastructure or force-push over your work.

### Layer 3: CI Pipeline (Strict Validation)

Every push triggers CI with strict checks that Claude Code cannot bypass:

- Security scanning (Trivy, Gitleaks, dependency review)
- Linting and formatting validation
- E2E tests on Kind clusters
- E2E tests on HyperShift clusters (for labeled PRs)

The `/tdd` skill watches CI results and iterates until all checks pass. With agent-assisted development, strict CI becomes manageable rather than a burden - Claude Code handles the iteration loop of fixing lint warnings, security findings, and test failures.

### Layer 4: Skill-Driven Workflows

Skills enforce disciplined workflows that Claude Code follows:

- **`/tdd`** enforces: never revert, never amend, only commit when tests pass or improve
- **`/rca`** enforces: systematic investigation before proposing fixes
- **Branch verification gate**: Skills check they're on the right branch before making changes
- **Worktree isolation**: Each task gets its own worktree, preventing cross-contamination

### Layer 5: Scoped Credentials

Claude Code only has access to scoped service accounts:

- GitHub: repo-level PAT (no org admin)
- Kubernetes: cluster-scoped to sandbox clusters (Kind, HyperShift hosted)
- AWS: scoped IAM user for cluster lifecycle only
- Management cluster operations require explicit user approval

### The Result

This layered approach means you can let Claude Code iterate freely on implementation while the guardrails catch issues at every level. The stricter your CI checks, the better the output - and agent-assisted development makes strict CI practical because Claude Code handles the iteration cost.

## Productivity Tips

These patterns have been refined over months of daily Claude Code usage on the Rossoctl project.

### 1. Parallel Sessions with Git Worktrees

Run multiple Claude Code sessions in parallel using iTerm2 split panes or tabs. Each session can manage work across several worktrees - Claude Code is aware of worktrees and can find the right one for a PR or issue:

```bash
# Terminal 1: Working on a feature (manages its own worktrees)
claude

# Terminal 2: Debugging a CI failure on a different PR
claude

# Terminal 3: Investigating an issue
claude
```

Each session creates and manages worktrees via `/git:worktree`. Worktrees provide full isolation - separate branches, separate builds, separate clusters. Multiple Claude sessions can work on different worktrees simultaneously without interfering with each other.

### 2. Sandbox Clusters

Have one or more sandbox clusters available per worktree:

- **Kind**: One cluster at a time (fast local iteration)
- **HyperShift**: Multiple clusters with different suffixes (e.g., `pr529`, `mlflow`)

Claude Code can deploy, test, debug, and redeploy without affecting other work.

### 3. Script Output Management

When Claude Code writes and runs scripts, keep output minimal to avoid context pollution:

- Log verbose output to files, return just the exit code
- Use `> /tmp/rossoctl/output.log 2>&1` for noisy commands
- Claude Code can read the log file if it needs details
- Long outputs in context can cause Claude Code to crash or lose track

### 4. Let Claude Iterate on Its Own Tools

Claude Code is inconsistent at following complex rule sets in long sessions. Instead of giving it rules to follow, have it build scripts and validation tools that enforce the rules:

- Write a validation script, then use the validation script for everything
- Build meta-layers: tools that build the right tools (several meta-layers deep)
- Combine validation scripts with CI checks - accuracy increases rapidly as each layer catches what the previous missed
- For complex tasks, provide pseudo code that drives the implementation. Claude Code executes well against a clear algorithmic spec, but struggles when the spec is ambiguous prose

### 5. Strict CI Is Now Practical

In the past, even a few strict checks in CI became a huge chore fast - developers avoided adding more because every new check meant more manual fix-up work. With agent-assisted development, this inverts completely:

- Claude Code handles the iteration cost of fixing lint warnings, security findings, and test failures
- This makes it practical to have a large number of strict checks
- The stricter the CI, the better the output quality
- The result: more secure and cleaner code with human assistance than without, because the checks that were too expensive to maintain manually are now very easy to manage

### 6. Idempotent Skills (Resume from Any Session)

The `/tdd` and `/rca` skills are designed to be resumable. Start a fresh Claude Code session, point it to a PR, issue, or doc, and it picks up where the previous session left off:

```
/tdd https://github.com/rossoctl/rossoctl/pull/456
```

State recovery works through existing infrastructure rather than session state:

- **Worktrees**: `git worktree list` detects existing worktrees for the branch
- **PRs and branches**: `gh pr list --head <branch>` finds the existing PR
- **CI results**: `gh pr checks` shows current CI status
- **Clusters**: Kubeconfig files at `~/clusters/hcp/` persist across sessions
- **Commit history**: Git log shows what was already done

This means you can close a session, start fresh, and `/tdd <PR URL>` continues the loop: check CI status, analyze failures, fix, push, wait. No manual state recovery needed.

> **Note**: Phase-level tracking (which TDD phase was last completed) does not persist across sessions. Claude Code re-evaluates the current state from git/CI/cluster state rather than reading a checkpoint file.

### 7. Check Out Boris Cherny (Claude Code Creator)

Boris Cherny created Claude Code and shares workflow tips regularly:

- [Threads](https://www.threads.com/@boris_cherny) (@boris_cherny)
- [X / Twitter](https://x.com/bcherny) (@bcherny)

Key insights from his workflow:
- Run 5+ Claude Code instances in parallel
- Use slash commands for repetitive operations (like Rossoctl's `/tdd`, `/rca`, `/commit`)
- Give Claude a way to verify its work - feedback loops 2-3x the quality
- For long-running tasks, use background agents or stop hooks

## Experimental: Claude Code Plugins (Optional)

These third-party plugins extend Claude Code with additional capabilities. They are not required but can improve autonomous workflows.

Install plugins from within a Claude Code session using the `/plugin` command.

<details>
<summary><b>Superpowers Plugin</b></summary>

A collection of meta-skills that add structured workflows for common development patterns:

```
/plugin claude-plugins-official/superpowers
```

Includes skills for:
- **Brainstorming** - Structured idea exploration before implementation
- **Systematic debugging** - Step-by-step investigation before proposing fixes
- **Test-driven development** - Write tests before implementation code
- **Writing plans** - Create implementation plans from specs
- **Code review** - Request and receive code review with technical rigor
- **Verification before completion** - Run verification commands before claiming work is done
- **Git worktrees** - Smart worktree creation with directory selection
- **Parallel agents** - Dispatch independent tasks to multiple agents

These skills are invoked automatically when relevant. For example, `superpowers:brainstorming` activates before creative work, and `superpowers:systematic-debugging` activates when encountering test failures.

</details>

<details>
<summary><b>Ralph Loop Plugin</b></summary>

Implements the [Ralph Wiggum technique](https://ghuntley.com/ralph/) - iterative autonomous development where the same prompt is fed to Claude Code repeatedly. Each iteration, Claude sees its own previous work in files and git history, and incrementally improves toward the goal.

```
/plugin claude-plugins-official/ralph-loop
```

**Usage:**

```
/ralph-loop "Fix the auth token refresh logic. Output <promise>FIXED</promise> when all tests pass." --completion-promise "FIXED" --max-iterations 10
```

**Options:**

| Option | Required | Purpose |
|--------|----------|---------|
| `--max-iterations <n>` | Strongly recommended | Max iterations before auto-stop. **Always set this to avoid runaway token consumption.** There is no default limit. |
| `--completion-promise <text>` | Recommended | A keyword that Claude outputs inside a `<promise>` tag to signal the task is done (e.g., `FIXED`, `TESTS COMPLETE`) |

Without `--max-iterations` or `--completion-promise`, the loop runs indefinitely until manually cancelled with `/cancel-ralph`.

**Commands:**
- `/ralph-loop <prompt> [options]` - Start an autonomous loop
- `/cancel-ralph` - Cancel the active loop
- `/ralph-loop:help` - Explain how it works

**Good for:** Well-defined tasks with clear success criteria, iterative refinement, greenfield work.
**Not good for:** Tasks requiring human judgment, unclear success criteria, production debugging.

</details>

## Related Documentation

- [Kind Development Guide](./kind.md) - Local development with Kind
- [HyperShift Development Guide](./hypershift.md) - OpenShift on AWS
- [Script Reference](../../.github/scripts/local-setup/README.md) - All deployment and testing scripts
- [Skills Index](../../.claude/skills/README.md) - Complete skill tree and workflow diagrams
