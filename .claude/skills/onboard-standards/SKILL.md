---
name: onboard:standards
description: Apply kagenti-specific conventions to an onboarded repo - commit format, PR template, issue templates
---

# Onboard: Apply Kagenti Standards

Apply kagenti-specific conventions to a repository linked via `onboard:link`.

## Conventions

### 1. Commit message format

Kagenti uses emoji prefixes and sign-off:

| Emoji | Type | Usage |
|-------|------|-------|
| ✨ | feat | New feature |
| 🐛 | fix | Bug fix |
| 📝 | docs | Documentation |
| 🔧 | config | Configuration |
| ⬆️ | deps | Dependency update |
| ♻️ | refactor | Refactoring |
| ✅ | test | Tests |
| 👷 | ci | CI/CD changes |

Sign-off required: `git commit -s`

### 2. PR template

Create `.github/pull_request_template.md`:

```markdown
## Summary
<!-- What does this PR do? Why? -->

## Test Plan
- [ ] Unit tests pass
- [ ] E2E tests pass (if applicable)
- [ ] Manual verification documented below

## Additional Context
<!-- Link issues, screenshots, etc. -->
```

### 3. Issue templates

Create `.github/ISSUE_TEMPLATE/bug_report.md`:

```markdown
---
name: Bug Report
about: Report a bug
labels: bug
---

## Describe the Bug

## Steps to Reproduce
1.
2.

## Expected Behavior

## Actual Behavior

## Environment
- Kubernetes version:
- Cluster type:
```

Create `.github/ISSUE_TEMPLATE/feature_request.md`:

```markdown
---
name: Feature Request
about: Suggest an enhancement
labels: enhancement
---

## Problem Statement

## Proposed Solution

## Alternatives Considered
```

### 4. Branch naming

| Prefix | Usage |
|--------|-------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `docs/` | Documentation |
| `orchestrate/` | Orchestration changes |

## Workflow

### Step 1: Create branch

```bash
git -C .repos/<repo-name> checkout -b orchestrate/onboard-standards
```

### Step 2: Apply conventions

Create or update the files above. Skip any that already match.

### Step 3: Commit and push

```bash
git -C .repos/<repo-name> add .github/
```

```bash
git -C .repos/<repo-name> commit -s -m "✨ Add kagenti PR and issue templates"
```

```bash
git -C .repos/<repo-name> push -u origin orchestrate/onboard-standards
```

### Step 4: Create PR

```bash
gh pr create --repo org/repo --title "Add kagenti project conventions" --body "Applies kagenti standards: commit format, PR template, issue templates, branch naming."
```

### Step 5: Update inventory

Set status to `Onboarded` in `.repos/README.md`.

## Related Skills

- `onboard` — Router skill
- `onboard:link` — Clone and register (prerequisite)
- `orchestrate:precommit` — Pre-commit hooks (complementary)
