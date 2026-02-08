# Commit and PR Convention for Kagenti Repository

When creating commits or pull requests for this repository, follow these conventions:

## Commit Message Structure

### For Individual Commits:
```
<emoji> <Short descriptive message>

<Optional longer description>

Signed-off-by: <Name> <email>
```

### For Pull Request Titles:
```
<emoji> <Short descriptive title>
```

## Emoji Prefixes

Use these emojis based on the type of change (from PR template):

- **✨** (`:sparkles:`) - Feature
- **🐛** (`:bug:`) - Bug fix
- **📖** (`:book:`) - Docs
- **📝** (`:memo:`) - Proposal
- **⚠️** (`:warning:`) - Breaking change
- **🌱** (`:seedling:`) - Other/misc (tests, tooling, CI, refactoring, etc.)
- **❓** (`:question:`) - Requires manual review/categorization

## Requirements

1. **Signed-off-by is MANDATORY**: Every commit must include `Signed-off-by: Name <email>`
2. **Use -s flag**: Always use `git commit -s` to automatically add sign-off
3. **Co-authored-by Claude**: Include `Co-authored-by: Claude <noreply@anthropic.com>` when Claude creates the initial commit
   - **Do NOT include**: `🤖 Generated with [Claude Code]` line (removed per team preference)
4. **Keep it concise**: Subject line should be clear and under 72 characters
5. **Use imperative mood**: "Add feature" not "Added feature"

## Pull Request Format

PRs use a template with the following structure:

```markdown
## Summary

<Clear description of what the PR does>

Key changes:
- <Bullet point 1>
- <Bullet point 2>
- <Bullet point 3>

## Related issue(s)

Fixes #<issue_number>
```

### Notes on PR Format:
- **Summary section is REQUIRED**
- **Related issue(s) section is OPTIONAL** - include it if you're fixing/closing an issue
- Use `Fixes #<number>` or `Closes #<number>` to auto-close issues when PR merges
- Can reference multiple issues: `Closes #362` and `Closes #293`
- If no related issue, you can omit the section or leave it as `Fixes #` (empty)

## Examples from Repository

### Commit messages:
```
🌱 Add agent-oauth-secret job to enable client registration with helm chart

Signed-off-by: Paolo Dettori <dettori@us.ibm.com>
```

```
🌱 Add E2E testing infrastructure and deployment health tests

Implements initial end-to-end testing framework for Kagenti platform
deployment validation (addresses #309).

Test Infrastructure:
- Added pytest framework with Kubernetes and Keycloak fixtures
- Created 15 deployment health tests covering platform components

Signed-off-by: Developer <dev@example.com>
Co-authored-by: Claude <noreply@anthropic.com>
```

### Pull Request:
```markdown
🌱 install mcp-gateway chart as separate chart instead than subchart

## Summary

This PR refactors the mcp-gateway deployment from a subchart dependency
of the kagenti chart to a standalone chart installed separately via Ansible.

Key changes:

- Removed mcp-gateway as a subchart dependency from the kagenti Helm chart
- Added Ansible task to install mcp-gateway as a separate Helm release
- Updated istio version from 1.26.0 to 1.28.0 in default values

## Related issue(s)

Fixes #393
```

## Workflow

### Making a commit:
```bash
git add <files>
git commit -s -m "<emoji> <message>"
```

### Amending with signature:
```bash
git commit --amend -s
```

### Creating a PR:
```bash
# 1. Create branch
git checkout -b feature/descriptive-name

# 2. Make commits with -s flag
git commit -s -m "🌱 Add tests"

# 3. Push to your fork or remote
git push -u origin feature/descriptive-name

# 4. Create PR via GitHub UI or gh CLI
gh pr create --title "🌱 Add E2E tests" --body "$(cat <<'EOF'
## Summary

Description of changes

Key changes:
- Point 1
- Point 2

## Related issue(s)

Fixes #309
EOF
)"
```

## CI Checks

The following CI checks will run automatically on PRs:

1. **CI Workflow** (`ci.yaml`) - Runs on all PRs:
   - Python lint with flake8
   - Pre-commit hooks
   - Pytest for kagenti/ui

2. **PR Kind Deployment** (`pr-kind-deployment.yaml`) - Runs on PRs affecting:
   - `kagenti/**`
   - `deployments/ui/**`
   - `.github/**`
   - `charts/**`

   This workflow:
   - Creates Kind cluster
   - Builds and deploys Kagenti platform
   - Runs deployment health checks
   - Runs E2E tests
   - Uploads test results

### Running CI checks locally:

```bash
# Run pre-commit hooks (via uv)
uv run pre-commit run --all-files

# Run flake8 syntax check (via uv)
uv run flake8 kagenti/tests/ --count --select=E9,F63,F7,F82 --show-source --statistics

# Run UI tests
cd kagenti/ui && uv run pytest

# Run E2E tests (requires deployed Kagenti platform)
cd kagenti
uv pip install -r tests/requirements.txt
uv run pytest tests/e2e/test_deployment_health.py -v
```

## Notes

- Pre-commit hooks are required for DCO sign-off verification
- All commits in a PR should follow this convention
- Multi-line commit bodies are optional but encouraged for complex changes
- CI must pass before PRs can be merged
