# HyperShift Prerequisites Audit

> **Date:** 2026-03-15
> **Context:** Fresh macOS setup, deploying `kagenti-team-sandbox42` via `hypershift-full-test.sh`
> **Goal:** Document every dependency actually needed vs. what the docs say

## What the Docs Say vs. What We Actually Needed

### README says (`.github/scripts/local-setup/README.md`, line 109)

> **Prerequisites**: AWS CLI, oc CLI, bash 3.2+, jq

### install.md says (Common Requirements)

| Tool | Version | Listed |
|------|---------|--------|
| Python | >=3.9 | Yes |
| uv | Latest | Yes |
| kubectl | >=1.32.1 | Yes |
| Helm | >=3.18.0, <4 | Yes |
| git | >=2.48.0 | Yes |

### What was ACTUALLY needed (discovered by trial and error)

#### CLI Tools

| Tool | How Installed | Why Needed | Documented? |
|------|---------------|------------|-------------|
| `aws` (AWS CLI) | `brew install awscli` | STS tokens, IAM, cluster create/destroy | Yes (README) |
| `oc` (OpenShift CLI) | `brew install openshift-cli` | Management cluster ops, builds, routes | Yes (README) |
| `kubectl` | Pre-installed (via Rancher Desktop) | Hosted cluster operations | Yes |
| `helm` **v3** (not v4!) | `brew install helm@3` + `export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"` | Kagenti installer, chart templating | **Partially** - docs say >=3.18.0, <4 but don't warn about helm v4 conflict |
| `jq` | Pre-installed (`/usr/bin/jq`) | JSON parsing in scripts | Yes |
| `hcp` | Installed by `local-setup.sh` to `~/.local/bin/` | HyperShift cluster create (ansible role) | Yes (via local-setup.sh) |
| `ansible-playbook` | `pip install ansible-core` (Python 3.13) | Runs hypershift-automation playbooks | **Partially** - listed as prerequisite of local-setup.sh, not in README |
| `git` | Pre-installed | Clone repos, worktrees | Yes |

#### Python Packages (for the Python used by ansible)

| Package | How Installed | Why Needed | Documented? |
|---------|---------------|------------|-------------|
| `ansible-core` | `pip install ansible-core` | ansible-playbook CLI | **Only in local-setup.sh comment** |
| `boto3` + `botocore` | `pip install boto3 botocore` | AWS modules in ansible (community.aws.sts_session_token) | **Only in local-setup.sh line 179** |
| `certifi` | `pip install certifi` + "Install Certificates.command" | SSL cert validation for ansible-galaxy | **Not documented at all** |
| `kubernetes` | Listed in local-setup.sh | Ansible k8s module | **Only in local-setup.sh** |
| `openshift` | Listed in local-setup.sh | Ansible k8s_auth module | **Only in local-setup.sh** |
| `PyYAML` | Listed in local-setup.sh | YAML parsing | **Only in local-setup.sh** |

#### Ansible Collections

| Collection | Why Needed | Documented? |
|------------|------------|-------------|
| `community.aws` | `community.aws.sts_session_token` for STS tokens | **Not in README** - only in local-setup.sh |
| `amazon.aws` | AWS resource management | **Not in README** - only in local-setup.sh |
| `kubernetes.core` | k8s module for ansible | **Not in README** - only in local-setup.sh |
| `community.general` | General ansible modules | **Not in README** - only in local-setup.sh |

#### Files & Credentials

| Item | How Obtained | Documented? |
|------|-------------|-------------|
| `.env.kagenti-team` (or `.env.kagenti-hypershift-custom`) | Created by `setup-hypershift-ci-credentials.sh` | Yes |
| `~/.pullsecret.json` | `kubectl get secret pull-secret -n openshift-config` from mgmt cluster | **Partially** - mentioned in local-setup.sh, not in README |
| `~/.kube/<mgmt>.kubeconfig` | Manual oc login / kubeconfig copy | Yes (in .env file) |
| `hypershift-automation/` repo | Cloned by local-setup.sh alongside kagenti | **Not obvious** - local-setup.sh clones it silently |

#### macOS-Specific Gotchas

| Issue | Impact | Fix |
|-------|--------|-----|
| Helm v4 is default `brew install helm` | Installer fails silently or with template errors | Must use `helm@3`: `brew install helm@3` and prepend to PATH |
| Python 3.13 SSL certs not configured | `ansible-galaxy collection install` hangs in infinite retry loop | Run `/Applications/Python 3.13/Install Certificates.command` or `pip install certifi` + symlink |
| `ansible-playbook` not in PATH | `create-cluster.sh` fails with "command not found" | Add Python's bin dir to PATH: `/Library/Frameworks/Python.framework/Versions/3.13/bin` |
| `oc` not available via Rancher Desktop | Unlike kubectl, oc is not bundled | `brew install openshift-cli` |

## Gaps in Documentation

### Critical (blocks deployment)

1. **Helm v3 requirement not enforced** - README says `>=3.18.0, <4` but doesn't mention that `helm@3` is a separate brew package, or how to override if helm v4 is default
2. **`ansible-core` prerequisite buried** - Only in a comment inside `local-setup.sh`, not in README prerequisites
3. **Python dependencies for ansible** - `boto3`, `botocore`, `certifi` needed but only in `local-setup.sh` line 179
4. **`~/.pullsecret.json`** - Must exist before cluster create, but README doesn't list it as a prerequisite; only `local-setup.sh` handles it
5. **Ansible collections** - `community.aws`, `amazon.aws` required but only installed by `local-setup.sh`

### Important (causes confusion)

6. **Two-step setup not clear** - Must run BOTH `setup-hypershift-ci-credentials.sh` AND `local-setup.sh` before first use. README mentions both but the dependency isn't obvious
7. **`.env` file location** - When using worktrees, the `.env` file must be in the worktree OR pre-sourced. `local-setup.sh` looks relative to REPO_ROOT
8. **`hypershift-automation` repo** - Needed alongside kagenti, cloned by `local-setup.sh`, but not listed as prerequisite

### Nice to Have

9. **Full PATH export one-liner** - Should document: `export PATH="/opt/homebrew/opt/helm@3/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"`
10. **`aws configure` not needed** - AWS creds come from `.env` file, not `~/.aws/credentials`. Could be clearer.

## Recommended: Complete Prerequisites Section for README

```markdown
### HyperShift Prerequisites

**CLI Tools** (install via Homebrew):
```bash
brew install awscli openshift-cli helm@3 jq
# helm@3 is required (helm v4 is NOT compatible)
export PATH="/opt/homebrew/opt/helm@3/bin:$PATH"
```

**Python** (3.9+, with ansible and AWS deps):
```bash
pip install ansible-core boto3 botocore kubernetes openshift PyYAML
# macOS: if ansible-galaxy fails with SSL errors:
pip install certifi
# Then run: /Applications/Python <version>/Install Certificates.command
```

**Ansible Collections**:
```bash
ansible-galaxy collection install kubernetes.core amazon.aws community.aws community.general
```

**One-Time Setup** (creates credentials + installs hcp CLI):
```bash
# 1. Create scoped AWS IAM + OCP credentials
./.github/scripts/hypershift/setup-hypershift-ci-credentials.sh

# 2. Install hcp CLI, clone hypershift-automation, verify pull secret
./.github/scripts/hypershift/local-setup.sh
```

**Files Required**:
- `.env.<MANAGED_BY_TAG>` - Created by step 1 above
- `~/.pullsecret.json` - Created by step 2 above (extracted from mgmt cluster)
- `../hypershift-automation/` - Cloned by step 2 above
```
