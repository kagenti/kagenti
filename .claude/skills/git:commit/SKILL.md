---
name: git:commit
description: Create properly formatted commits following Kagenti conventions
---

# Git Commit

Create commits following Kagenti conventions with proper formatting and sign-off.

## When to Use

- Every time you commit code
- After TDD fix iterations
- Before creating a PR

## Quick Commit

```bash
git add <files>
```

```bash
git commit -s -m "🌱 Short descriptive message"
```

The `-s` flag adds the required `Signed-off-by` line.

## Commit Format

```
<emoji> <Short descriptive message>

<Optional longer description>

Signed-off-by: <Name> <email>
Co-authored-by: Claude <noreply@anthropic.com>
```

### Emoji Prefixes

| Emoji | Type | When |
|-------|------|------|
| ✨ | Feature | New functionality |
| 🐛 | Bug fix | Fixing broken behavior |
| 📖 | Docs | Documentation only |
| 📝 | Proposal | Design proposals |
| ⚠️ | Breaking change | API or behavior changes |
| 🌱 | Other | Tests, CI, refactoring, tooling |

### Requirements

1. **Signed-off-by is MANDATORY** — always use `git commit -s`
2. **Co-authored-by Claude** — include when Claude creates the commit
3. **Imperative mood** — "Add feature" not "Added feature"
4. **Under 72 characters** — subject line
5. **No "Generated with Claude Code" line** — removed per team preference

### Examples

```
🌱 Add E2E testing infrastructure and deployment health tests

Implements initial end-to-end testing framework for Kagenti platform.

Signed-off-by: Developer <dev@example.com>
Co-authored-by: Claude <noreply@anthropic.com>
```

```
🐛 Fix VPC cleanup order: delete subnets before route tables

Signed-off-by: Developer <dev@example.com>
```

## Sign All Commits in Branch

If you have unsigned commits in your branch, sign them all:

```bash
git rebase --signoff HEAD~$(git rev-list --count upstream/main..HEAD)
```

## Amending

```bash
git commit --amend -s --no-edit
```

## After Committing

Check the commit:

```bash
git log --oneline -1
```

Verify sign-off:

```bash
git log -1 --format='%B' | grep 'Signed-off-by'
```

## Related Skills

- `repo:pr` - PR creation conventions
- `git:rebase` - Rebase before pushing
- `tdd:ci` - TDD workflow commit step
