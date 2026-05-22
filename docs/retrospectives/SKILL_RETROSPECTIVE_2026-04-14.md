# Skill Retrospective Plan - 2026-04-14

## Session Context

Dependabot PR triage session: analyzed 21 open Dependabot PRs, created 4 new
PRs (pylint fix, python image bundle, test toolchain bundle, TypeScript 6.0
upgrade), approved 6 low-risk PRs, and created the `github:dependabot` skill.

## Key Session Learnings

### What Went Well
- The phased approach (discover → categorize → execute) worked cleanly
- Bundling saved 8 PRs worth of review overhead (5 python images + 3 test tools)
- Catching the TypeScript 6.0 `baseUrl` deprecation before merge prevented a broken build

### Blind Paths Taken
1. **Subagent file edits didn't persist** — delegated router file edits to a
   subagent, but changes weren't saved to disk. Had to redo manually. This is a
   known limitation: subagent writes may not persist in the main session's
   working tree.
2. **Attempted `gh pr merge` 3 times before discovering permission block** —
   should have checked permissions first or caught the pattern after the first
   denial.

### Anti-Patterns to Encode
- Always verify subagent file writes with `git diff` before moving on
- After a single `gh pr merge` denial, switch to approve-only and inform user

## Proposed Changes

### Skills to Update

| Skill | Change | Reason | Priority |
|-------|--------|--------|----------|
| `github:prs` | Add Troubleshooting section | Missing per audit | Medium |
| `github:issues` | Add Troubleshooting section | Missing per audit | Medium |
| `github:my-status` | Add TOC | Over 50 lines, no TOC | Low |
| `github:last-week` | Add TOC | Over 50 lines, no TOC | Low |
| `github:streamer` | Add TOC | Over 50 lines, no TOC | Low |

### Skills to Refactor

| Action | Skills | Reason | Priority |
|--------|--------|--------|----------|
| Parameterize | All 7 hardcoded github skills | Use `$OWNER/$REPO` variables instead of `kagenti/kagenti` | High |

This is the single highest-impact improvement. 7 of 9 github skills hardcode
`kagenti/kagenti`, making them unusable in other repos. The new
`github:dependabot` skill already uses variables — the others should follow.

**Approach**: Add a "Variables" section at the top of each skill (matching
`github:dependabot` pattern), then find-replace `kagenti/kagenti` with
`$OWNER/$REPO` in all commands. For skills that reference repo-specific details
(like namespace names or file paths), keep those as-is but add a note that they
are repo-specific.

### New Skills

None proposed — the `github:dependabot` skill was already created during this
session.

### Skills to Delete

None.

## Estimated Effort

- Parameterize 7 skills (bulk find-replace + add Variables section): ~30 min
- Add Troubleshooting to 2 skills: ~10 min
- Add TOCs to 3 skills: ~5 min

Total: ~45 min of skill maintenance work
