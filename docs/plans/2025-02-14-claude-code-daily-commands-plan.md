# Claude Code Daily Commands - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a daily commands reference doc for developers and maintainers, a `github:my-status` skill, and clean up redundant skills.

**Architecture:** New markdown doc at `docs/developer/claude-code-daily-commands.md` with two audience sections. New skill at `.claude/skills/github:my-status/SKILL.md`. Merge `repo:commit` format spec into `git:commit`, delete `repo:commit` directory, update all cross-references.

**Tech Stack:** Markdown docs, Claude Code skills (SKILL.md format), `gh` CLI for the new skill.

---

### Task 1: Create `github:my-status` Skill

**Files:**
- Create: `.claude/skills/github:my-status/SKILL.md`

**Step 1: Create the skill directory**

```bash
mkdir -p .claude/skills/github:my-status
```

**Step 2: Write the skill file**

Create `.claude/skills/github:my-status/SKILL.md` with this content:

```markdown
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
|----------|--------|----|
| ... |
```

## Related Skills

- `github:prs` - Full PR health analysis (all PRs, not just mine)
- `github:issues` - Full issue triage (all issues, not just mine)
- `git:status` - Worktree and TODO file overview
- `github:last-week` - Weekly repository report
```

**Step 3: Commit**

```bash
git add .claude/skills/github:my-status/SKILL.md
git commit -s -m "✨ Add github:my-status skill for personal status dashboard"
```

---

### Task 2: Update `github` Router to Include `my-status`

**Files:**
- Modify: `.claude/skills/github/SKILL.md`

**Step 1: Add my-status to the mermaid diagram**

Add a new node `GH -->|My status| MYSTATUS["github:my-status"]:::github` to the flowchart.

**Step 2: Add my-status to the auto-select decision tree**

Add entry:
```
    ├─ What needs my attention today?
    │   → github:my-status
```

**Step 3: Add my-status to the available skills table**

Add row:
```
| `github:my-status` | Personal dashboard: your open PRs, pending reviews, assigned issues |
```

**Step 4: Commit**

```bash
git add .claude/skills/github/SKILL.md
git commit -s -m "🌱 Add github:my-status to github router skill"
```

---

### Task 3: Merge `repo:commit` into `git:commit`

**Files:**
- Modify: `.claude/skills/git:commit/SKILL.md`
- Delete: `.claude/skills/repo:commit/SKILL.md` (entire directory)

**Step 1: Merge the format spec into git:commit**

Replace the current `git:commit/SKILL.md` content. The new file combines:
- The git mechanics from current `git:commit` (quick commit, sign-off, amending)
- The format spec from `repo:commit` (emoji table with "When" column, requirements list, examples)
- Remove the "See `repo:commit` for the full repository-specific format" reference since it's now inline

The merged file should have these sections:
1. Quick Commit (existing)
2. Commit Format (moved from repo:commit - full emoji table, requirements, examples)
3. Sign All Commits in Branch (existing)
4. Amending (existing)
5. After Committing (existing)
6. Related Skills (updated - remove repo:commit reference)

**Step 2: Delete repo:commit directory**

```bash
rm -rf .claude/skills/repo:commit
```

**Step 3: Commit**

```bash
git add .claude/skills/git:commit/SKILL.md
git rm -r .claude/skills/repo:commit
git commit -s -m "🌱 Merge repo:commit format spec into git:commit"
```

---

### Task 4: Update All `repo:commit` References

**Files to modify (change `repo:commit` → `git:commit`):**
- `.claude/skills/repo/SKILL.md` — remove `repo:commit` row, update auto-select tree
- `.claude/skills/tdd:ci/SKILL.md:563` — change reference
- `.claude/skills/tdd/SKILL.md:326,378` — change references
- `.claude/skills/repo:pr/SKILL.md:14,60` — change references
- `.claude/skills/repo:issue/SKILL.md:41` — change reference
- `.claude/skills/git:rebase/SKILL.md:86` — change reference
- `.claude/skills/README.md:365` — remove `repo:commit` from tree

**Step 1: Update each file**

In each file, replace `repo:commit` with `git:commit`. For `repo/SKILL.md`, remove the `repo:commit` row from the table and auto-select tree entirely (since `git:commit` is in the `git` category, not `repo`).

For `.claude/skills/repo/SKILL.md`, the auto-select becomes:
```
What are you doing?
    │
    ├─ Creating a PR → repo:pr
    └─ Filing an issue → repo:issue
```

And the table becomes:
```
| Skill | Purpose |
|-------|---------|
| `repo:pr` | PR template, summary format, issue linking |
| `repo:issue` | Issue templates (bug, feature, epic) |
```

For `README.md`, remove the `│   ├── repo:commit` line from the skill tree.

**Step 2: Commit**

```bash
git add .claude/skills/repo/SKILL.md .claude/skills/tdd:ci/SKILL.md .claude/skills/tdd/SKILL.md \
  .claude/skills/repo:pr/SKILL.md .claude/skills/repo:issue/SKILL.md .claude/skills/git:rebase/SKILL.md \
  .claude/skills/README.md
git commit -s -m "🌱 Update all repo:commit references to git:commit"
```

---

### Task 5: Delete `testing` Router Skill

**Files:**
- Delete: `.claude/skills/testing/SKILL.md` (the router only, NOT `testing:kubectl-debugging`)
- Modify: `.claude/skills/README.md` — update skill tree
- Modify: `.claude/skills/skills:validate/SKILL.md:118` — remove `testing` from category list if needed (check if `testing:kubectl-debugging` still needs it)

**Step 1: Delete the testing router**

```bash
rm .claude/skills/testing/SKILL.md
rmdir .claude/skills/testing 2>/dev/null || true
```

Note: `testing:kubectl-debugging` lives in its own directory `.claude/skills/testing:kubectl-debugging/` so deleting `.claude/skills/testing/` does not affect it.

**Step 2: Update README.md skill tree**

Change:
```
└── testing/                        Debugging techniques
    └── testing:kubectl-debugging
```
To:
```
└── testing:kubectl-debugging       Common kubectl debugging commands
```

**Step 3: Commit**

```bash
git rm .claude/skills/testing/SKILL.md
git add .claude/skills/README.md
git commit -s -m "🌱 Remove thin testing router skill (test skill is the proper router)"
```

---

### Task 6: Create `docs/developer/claude-code-daily-commands.md`

**Files:**
- Create: `docs/developer/claude-code-daily-commands.md`

**Step 1: Write the doc**

The doc should have this structure:

```markdown
# Claude Code Daily Commands

Quick reference for the skills and commands you'll use regularly when working on
Kagenti. For setup, prerequisites, and workflow details, see the
[Claude Code Development Guide](./claude-code.md).

## Developer Commands

### Morning Orientation

Start your day by checking what needs your attention:

| Command | What it does |
|---------|-------------|
| `/github:my-status` | Your open PRs, pending reviews, assigned issues, worktree status |
| `/git:status` | All worktrees with PR status and TODO files overview |

**Example morning workflow:**
```
> /github:my-status
> /git:status
```

### During Development

| Command | What it does | When to use |
|---------|-------------|-------------|
| `/git:worktree <name>` | Create isolated worktree for a feature/fix | Starting new work |
| `/git:rebase` | Rebase onto upstream/main (gfur alias) | Before push, when PR has conflicts |
| `/ci:status <PR#>` | Check CI status for a specific PR | After pushing changes |
| `/ci:monitoring` | Watch running CI, get notified on completion | After push, waiting for results |
| `/k8s:health` | Platform health check across all components | Before testing, after deploy |
| `/k8s:pods` | Debug pod crashes, failures, networking | Pod not starting or crashing |
| `/k8s:logs` | Search component logs for errors | Investigating runtime issues |

### Committing and Shipping

| Command | What it does | When to use |
|---------|-------------|-------------|
| `/git:commit` | Properly formatted commit with emoji + sign-off | Every commit |
| `/tdd <issue/PR/desc>` | Full TDD loop (implement, test, push, iterate) | Feature work or bug fixes |
| `/rca <failure URL>` | Systematic failure investigation | CI failure or runtime issue |

## Maintainer Commands

### Weekly Repository Health

Run these weekly (or before standup) to stay on top of repository health:

| Command | What it does |
|---------|-------------|
| `/github:last-week` | Full weekly report: merged PRs, new issues, CI trends, recommendations |
| `/github:issues` | Issue triage: stale, unattended, blocking, close candidates |
| `/github:prs` | PR health: needs review, stale, failing CI, merge conflicts |

**Example weekly workflow:**
```
> /github:last-week
```
This calls `github:issues` and `github:prs` internally, so you get everything
in one command. Use the individual skills when you need focused triage.

### CI and Quality

| Command | What it does | When to use |
|---------|-------------|-------------|
| `/ci:status <PR#>` | Detailed CI check analysis for a PR | Reviewing contributor PRs |
| `/skills:retrospective` | End-of-session skill improvement review | After debugging sessions |

### Issue and PR Management

| Command | What it does |
|---------|-------------|
| `/repo:issue` | Create properly formatted issue (bug, feature, epic) |
| `/repo:pr` | Create properly formatted PR with summary |

## Skill Map

All skills organized by how often you'll use them:

### Daily Use
| Skill | Purpose |
|-------|---------|
| `github:my-status` | Personal status dashboard |
| `git:status` | Worktree and PR overview |
| `git:commit` | Commit with proper format |
| `git:rebase` | Keep branch current |

### Weekly Use
| Skill | Purpose |
|-------|---------|
| `github:last-week` | Weekly repository report |
| `github:issues` | Issue triage |
| `github:prs` | PR health analysis |
| `skills:retrospective` | Session review |

### Per-Task Use
| Skill | Purpose |
|-------|---------|
| `tdd` | Test-driven development loop |
| `rca` | Root cause analysis |
| `git:worktree` | Create isolated worktree |
| `ci:status` | Check PR CI |
| `ci:monitoring` | Watch running CI |
| `k8s:health` | Cluster health check |
| `k8s:pods` | Debug pods |
| `k8s:logs` | Search logs |

### Infrastructure (Occasional)
| Skill | Purpose |
|-------|---------|
| `kind:cluster` | Manage local Kind cluster |
| `hypershift:cluster` | Create/destroy HyperShift clusters |
| `hypershift:quotas` | Check AWS quotas |
| `kagenti:deploy` | Deploy platform |
| `helm:debug` | Debug Helm charts |
| `auth:keycloak-confidential-client` | Create OAuth2 clients |

## Related Documentation

- [Claude Code Development Guide](./claude-code.md) - Setup, TDD/RCA workflows, safety
- [Skills Index](../../.claude/skills/README.md) - Complete skill tree
- [Script Reference](../../.github/scripts/local-setup/README.md) - Deployment scripts
```

**Step 2: Commit**

```bash
git add docs/developer/claude-code-daily-commands.md
git commit -s -m "📖 Add Claude Code daily commands reference for developers and maintainers"
```

---

### Task 7: Update `docs/developer/README.md` to Link New Doc

**Files:**
- Modify: `docs/developer/README.md`

**Step 1: Add daily commands to the environment table**

Add a row to the "Choose Your Environment" table:

```markdown
| **Daily Commands** | Quick reference for daily/weekly Claude Code skills | [claude-code-daily-commands.md](./claude-code-daily-commands.md) |
```

**Step 2: Add to documentation structure**

Add to the docs structure section:
```
├── claude-code-daily-commands.md  # Daily/weekly skill quick reference
```

**Step 3: Commit**

```bash
git add docs/developer/README.md
git commit -s -m "📖 Link daily commands doc from developer README"
```

---

### Task 8: Run Pre-commit and Verify

**Step 1: Run pre-commit on all changed files**

```bash
pre-commit run --all-files
```

**Step 2: Verify skill structure**

```bash
# Confirm repo:commit is gone
ls .claude/skills/repo:commit/ 2>&1 && echo "ERROR: repo:commit still exists" || echo "OK: repo:commit removed"

# Confirm testing router is gone
ls .claude/skills/testing/SKILL.md 2>&1 && echo "ERROR: testing router still exists" || echo "OK: testing router removed"

# Confirm testing:kubectl-debugging still exists
ls .claude/skills/testing:kubectl-debugging/SKILL.md && echo "OK: kubectl-debugging preserved"

# Confirm new skill exists
ls .claude/skills/github:my-status/SKILL.md && echo "OK: my-status created"

# Confirm new doc exists
ls docs/developer/claude-code-daily-commands.md && echo "OK: daily commands doc created"
```

**Step 3: Verify no broken references**

```bash
# Check no remaining references to repo:commit (should return nothing)
grep -r "repo:commit" .claude/skills/ --include="*.md"
```

**Step 4: Fix any issues found, commit if needed**

```bash
git add -A && git commit -s -m "🌱 Fix pre-commit issues" || echo "Nothing to fix"
```
