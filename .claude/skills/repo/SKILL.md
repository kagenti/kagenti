---
name: repo
description: Repository-specific conventions for PRs and issues
---

# Repository Conventions

Kagenti-specific conventions for pull requests and issues.

## Auto-Select Sub-Skill

```
What are you doing?
    │
    ├─ Making a commit → git:commit
    ├─ Creating a PR → repo:pr
    └─ Filing an issue → repo:issue
```

## Available Skills

| Skill | Purpose |
|-------|---------|
| `repo:pr` | PR template, summary format, issue linking |
| `repo:issue` | Issue templates (bug, feature, epic) |

## Related Skills

- `git:commit` - Commit format and mechanics
- `git:rebase` - Rebase and sign-off
- `tdd:ci` - TDD workflow that produces commits and PRs
