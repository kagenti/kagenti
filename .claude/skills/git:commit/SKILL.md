---
name: git:commit
description: Create properly formatted commits following repository conventions
---

# Git Commit

Create commits following the repository's conventions. Links to repo-specific guidelines for format details.

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

## CVE ID Check (Pre-Commit)

**Before every commit**, scan the commit message for CVE references:

- Pattern: `CVE-\d{4}-\d+` (e.g., CVE-2026-12345)
- Also check for: "vulnerability", "exploit", "security flaw" combined with a package name

If found in the commit message:

```
WARNING: Commit message contains CVE reference.
This will be visible in public git history.

Rewrite using neutral language:
  BAD:  "Fix CVE-2026-12345 in requests library"
  GOOD: "Bump requests to 2.32.0"

  BAD:  "Patch security vulnerability in auth module"
  GOOD: "Update auth module for compatibility"
```

If a `cve:brainstorm` hold is active, also verify the staged file diffs don't
contain CVE IDs in comments, docstrings, or documentation.

## Sign All Commits in Branch

If you have unsigned commits in your branch, sign them all:

```bash
git rebase --signoff HEAD~$(git rev-list --count upstream/main..HEAD)
```

## Commit Format

Quick reference:

| Emoji | Type |
|-------|------|
| ✨ | Feature |
| 🐛 | Bug fix |
| 📖 | Docs |
| 🌱 | Other (tests, CI, refactoring) |
| ⚠️ | Breaking change |

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
- `cve:scan` - CVE scanning (invoked by other workflows)
- `cve:brainstorm` - CVE disclosure gate (blocks CVE references in commits)
