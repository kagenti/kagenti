---
name: github:my-status
description: Personal status dashboard - your PRs, reviews, issues, and worktrees at a glance
---

# My Status

Personal action items: what needs your attention right now.

## When to Use

- Morning orientation: what do I need to work on today?
- Before standup: quick summary of my open work
- After being away: catch up on what happened

> **Auto-approved**: All `gh` commands are read-only and auto-approved.

## Workflow

### 1. Detect Current User

```bash
GH_USER=$(gh api user --jq '.login')
echo "Status for: $GH_USER"
```

### 2. My Open PRs (with CI + review status)

```bash
gh pr list --repo kagenti/kagenti --author @me --state open \
  --json number,title,createdAt,updatedAt,reviewDecision,statusCheckRollup,headRefName \
  --jq '.[] | "#\(.number) [\(.headRefName)] \(.title)\n  Review: \(.reviewDecision // "NONE")\n  CI: \([.statusCheckRollup[]? | .conclusion] | group_by(.) | map("\(.[0]): \(length)") | join(", "))\n  Updated: \(.updatedAt)\n"'
```

### 3. Reviews Requested From Me

```bash
gh pr list --repo kagenti/kagenti --search "review-requested:@me" --state open \
  --json number,title,author,createdAt,updatedAt \
  --jq '.[] | "#\(.number) by @\(.author.login): \(.title) (updated: \(.updatedAt))"'
```

### 4. Issues Assigned to Me

```bash
gh issue list --repo kagenti/kagenti --assignee @me --state open \
  --json number,title,labels,createdAt,updatedAt \
  --jq '.[] | "#\(.number) \(.title)\n  Labels: \([.labels[].name] | join(", "))\n  Updated: \(.updatedAt)\n"'
```

### 5. PRs Where I Am Mentioned (last 7 days)

```bash
gh pr list --repo kagenti/kagenti --search "mentions:@me" --state open \
  --json number,title,author,updatedAt \
  --jq '.[] | "#\(.number) by @\(.author.login): \(.title) (updated: \(.updatedAt))"'
```

### 6. My Worktree Status

```bash
echo "=== Worktrees ===" && \
git worktree list --porcelain | grep -E "^worktree|^branch" | paste - - | \
while read wt branch; do
  dir=$(basename "$(echo "$wt" | sed 's/worktree //')")
  br=$(echo "$branch" | sed 's|branch refs/heads/||')
  pr=$(gh pr list --head "$br" --json number,state,title --jq '.[0] | "PR #\(.number) [\(.state)]"' 2>/dev/null || echo "No PR")
  printf "%-40s %-30s %s\n" "$dir" "$br" "$pr"
done
```

## Output Format

Present results as a summary:

```markdown
## Status for @username

### My Open PRs: N
| # | Branch | Title | CI | Review |
|---|--------|-------|----|--------|
| ... |

### Reviews Waiting for Me: N
| # | Author | Title | Age |
|---|--------|-------|-----|
| ... |

### Issues Assigned to Me: N
| # | Title | Labels | Updated |
|---|-------|--------|---------|
| ... |

### Active Worktrees: N
| Worktree | Branch | PR |
|----------|--------|---|
| ... |
```

## Related Skills

- `github:prs` - Full PR health analysis (all PRs, not just mine)
- `github:issues` - Full issue triage (all issues, not just mine)
- `git:status` - Worktree and TODO file overview
- `github:last-week` - Weekly repository report
