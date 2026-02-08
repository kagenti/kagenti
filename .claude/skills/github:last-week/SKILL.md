---
name: github:last-week
description: Weekly repository report - merged PRs, new issues, CI health, priority analysis
---

# Last Week Report

Generate a weekly summary of repository activity, CI health, and priority issues.

## When to Use

- Weekly standup preparation
- Sprint retrospective input
- Tracking project health over time

> **Auto-approved**: All `gh` commands are read-only and auto-approved.

## Workflow

Save output to `/tmp/kagenti/github/`:

```bash
mkdir -p /tmp/kagenti/github
```

### 1. Merged PRs (last 7 days)

```bash
gh pr list --repo kagenti/kagenti --state merged --limit 50 --json number,title,author,mergedAt,labels --jq '.[] | select(.mergedAt > (now - 7*24*3600 | strftime("%Y-%m-%dT%H:%M:%SZ"))) | "#\(.number) \(.title) (@\(.author.login))"'
```

### 2. New Issues (last 7 days)

```bash
gh issue list --repo kagenti/kagenti --state all --limit 50 --json number,title,author,createdAt,labels,state --jq '.[] | select(.createdAt > (now - 7*24*3600 | strftime("%Y-%m-%dT%H:%M:%SZ"))) | "#\(.number) [\(.state)] \(.title)"'
```

### 3. CI Health (last 10 runs on main)

```bash
gh run list --repo kagenti/kagenti --branch main --limit 10 --json conclusion,name,createdAt --jq '.[] | "\(.conclusion)\t\(.name)\t\(.createdAt)"'
```

### 4. Failed CI Runs

```bash
gh run list --repo kagenti/kagenti --branch main --status failure --limit 5 --json databaseId,name,conclusion,createdAt --jq '.[] | "#\(.databaseId) \(.name) \(.createdAt)"'
```

### 5. Generate Summary

Compile into a report:

```markdown
## Weekly Report: [date range]

### Merged PRs: N
- [list with authors]

### New Issues: N
- [list by priority/label]

### CI Health
- Pass rate: X/Y runs
- Failing workflows: [list]

### Priority Analysis
1. **Blocking**: Issues labeled `priority/critical` or blocking other work
2. **Security**: Issues labeled `security` or CVE-related
3. **Stale**: Issues with no activity > 30 days
4. **Quick wins**: Issues labeled `good first issue` with no assignee
```

### 6. Optionally Create Summary Issue

If the user wants, create a GitHub issue with the report:

```bash
gh issue create --repo kagenti/kagenti --title "📊 Weekly Report [date]" --body "$(cat /tmp/kagenti/github/weekly-report.md)"
```

## Related Skills

- `github:issues` - Deep dive into issue triage
- `github:prs` - Deep dive into PR health
- `git:status` - Worktree and PR status overview
- `ci:status` - Detailed CI check analysis
- `repo:issue` - Issue creation format
