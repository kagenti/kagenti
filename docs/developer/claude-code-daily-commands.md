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

All skills organized by how often you'll use them.

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
