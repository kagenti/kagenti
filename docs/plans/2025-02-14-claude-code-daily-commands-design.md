# Claude Code Daily Commands - Design Document

**Date:** 2025-02-14
**Branch:** claude-code-daily-commands
**Status:** Approved

## Problem

Kagenti has 60+ Claude Code skills but no documentation that tells developers
and maintainers "what should I run daily/weekly to stay oriented?" The existing
`docs/developer/claude-code.md` covers setup, TDD, and RCA workflows but not
the daily orientation use case. Contributors with many open PRs, issues, and
worktrees need a quick reference for staying on top of everything.

## Goals

1. Create `docs/developer/claude-code-daily-commands.md` with developer and
   maintainer sections showing which skills to run and when.
2. Create a new `github:my-status` skill that auto-detects the user's GH handle
   and shows personal action items (PRs, reviews, issues, mentions).
3. Clean up skill redundancies: merge `repo:commit` into `git:commit`, delete
   the thin `testing` router skill.

## Deliverables

### 1. `docs/developer/claude-code-daily-commands.md`

Two main sections:

**Developer Daily Commands:**
- Morning orientation: `/github:my-status`, `/git:status`
- During development: `/git:worktree`, `/git:rebase`, `/ci:status`,
  `/ci:monitoring`, `/k8s:health`, `/k8s:pods`, `/k8s:logs`
- Committing and shipping: `/git:commit`, `/tdd`, `/rca`

**Maintainer Commands:**
- Weekly health check: `/github:last-week`, `/github:issues`, `/github:prs`
- CI and quality: `/ci:status`, `/skills:retrospective`
- Issue and PR management: `/repo:issue`, `/repo:pr`

**Quick reference table** categorizing all skills by frequency:
daily / weekly / occasional / infrastructure.

### 2. `github:my-status` Skill

New skill at `.claude/skills/github:my-status/SKILL.md`.

- Auto-detects GH handle via `gh api user --jq '.login'`
- Shows: my open PRs (with CI + review status), reviews requested from me,
  issues assigned to me, PRs where I'm mentioned, local worktree status
- Output as formatted markdown tables sorted by urgency
- Related skills: `github:prs`, `github:issues`, `git:status`

### 3. Skill Cleanup

**Merge `repo:commit` into `git:commit`:**
- Move the format spec (emoji table, requirements, examples) from `repo:commit`
  into `git:commit`
- Delete `repo:commit` skill directory
- Update references in other skills that point to `repo:commit`

**Delete `testing` router:**
- The `testing` skill is a thin 40-line wrapper with 3 generic kubectl commands
- The `test` skill is the proper router for test workflows
- `k8s:pods` and `k8s:logs` cover the kubectl debugging use case
- Keep `testing:kubectl-debugging` as-is (useful standalone)
- Delete only the `testing/SKILL.md` router, not `testing:kubectl-debugging`

## Non-Goals

- Not reorganizing the `repo:*` skill family (repo:pr, repo:issue stay as-is)
- Not creating a separate weekly-summary skill with person filtering
- Not restructuring the existing `claude-code.md` guide

## Dependencies

- The new doc links to `claude-code.md` for setup/prerequisites
- The `github:my-status` skill is referenced in the doc
- Skill cleanup must update cross-references in affected skills
