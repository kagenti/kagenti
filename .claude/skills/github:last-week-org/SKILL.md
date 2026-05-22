---
name: github:last-week-org
description: Org-wide weekly report - covers all kagenti repos with proportional depth based on activity
---

# Org-Wide Weekly Report

Deep weekly analysis across all kagenti org repositories. Active repos get full analysis; quiet repos get a one-liner summary.

## Variables

Set at session start:

```bash
export OWNER=<org-or-user>
export REPO=<repo-for-report-issue>   # where the weekly report issue is posted
```

## When to Use

- Org-wide weekly standup / leadership update
- Cross-repo coordination check
- Tracking health of the entire kagenti org

> **Auto-approved**: All `gh` read commands and `gh repo list` are auto-approved.

## Workflow

### Phase 0: Gather Org Data (MUST run first)

Run the org data gathering script to snapshot all repos:

```bash
./.github/scripts/reports/weekly-report-org-data.sh 7 > /tmp/kagenti/github/org-data-gather.log 2>&1; echo "EXIT:$?"
```

Then read the org summary (small file, OK inline):

```bash
jq . /tmp/kagenti/github/data/org-summary.json
```

This creates:
- `/tmp/kagenti/github/data/<repo>/` — Per-repo JSON files (merged-prs, open-prs, open-issues, new-issues, ci-runs)
- `/tmp/kagenti/github/data/org-summary.json` — Totals and per-repo counts with active/quiet classification

**IMPORTANT**: All subsequent phases MUST read from these JSON files, NOT re-query `gh`. This ensures consistency.

### Phase 1: Org-Wide Summary Table

Read totals from `org-summary.json` and present:

```markdown
## Org-Wide Summary

| Repo | Merged PRs | Open PRs | Open Issues | New Issues | CI Pass Rate | Status |
|------|-----------|----------|-------------|------------|-------------|--------|
| kagenti | ... | ... | ... | ... | .../... | active |
| repo2 | ... | ... | ... | ... | .../... | quiet |
| **TOTAL** | **N** | **N** | **N** | **N** | | |
```

Order repos by activity (most merged PRs + new issues first).

### Linking Convention (ALL phases)

**IMPORTANT**: All issue and PR references in the report MUST use absolute GitHub URLs,
not shorthand references like `#N` or `kagenti/<repo>#N`. Shorthand references are
ambiguous when the report is posted as a GitHub issue — GitHub auto-links them relative
to the repo where the issue lives.

Use this format for **every** repo, including kagenti itself:
- Issues: `[kagenti/<repo>#N](https://github.com/kagenti/<repo>/issues/N)`
- PRs: `[kagenti/<repo>#N](https://github.com/kagenti/<repo>/pull/N)`

Examples:
- `[kagenti/kagenti#960](https://github.com/kagenti/kagenti/issues/960)`
- `[kagenti/kagenti-extensions#239](https://github.com/kagenti/kagenti-extensions/pull/239)`

### Phase 2: Deep Dive per Active Repo

For each repo classified as `active` in org-summary.json, analyze in order of activity level.

#### For `kagenti` (local checkout available) — Full Depth

This is the main repo with local checkout. Apply the full `github:last-week` analysis:

1. **Issue Analysis**: For every open issue, search the local codebase for affected code/component. Check if a fix was merged. Classify severity (security, blocking, bug, feature, epic, stale).
2. **PR Analysis**: For every open PR, check CI status, review status, staleness, conflicts. Classify health (ready to merge, needs review, needs /run-e2e, CI failing, stale, conflicts).
3. **CI Failure Timeline**: Map failures on main to triggering commits. Identify recurring vs one-off failures. Correlate with merged PRs between last success and failure.
4. **Root Cause Correlation**: For each CI failure, identify candidate PRs by checking file paths touched (charts/, deployments/, .github/, kagenti/backend/).

Use subagents for log analysis:

```
Agent(subagent_type='Explore'):
  "Read /tmp/kagenti/github/data/kagenti/merged-prs.json and summarize:
   - Count by author
   - Which areas changed most (charts, backend, tests, CI)
   Return a brief summary, not the raw data."
```

#### For Other Active Repos (API-only) — Moderate Depth

No local checkout. Use gathered JSON data only.

Use absolute URLs for all references (see [Linking Convention](#linking-convention-all-phases) above).

1. **Issue Triage**: Read `open-issues.json`. Group by labels. Flag stale issues (>30 days no update). Note issues linked to PRs.
2. **PR Status**: Read `open-prs.json`. Check CI/review status from JSON. Flag PRs waiting >7 days for review.
3. **CI Health**: Read `ci-runs.json`. Count pass/fail. Flag any failures on main.
4. **Merged PR Summary**: Read `merged-prs.json`. List with author and title.

Present each active repo as:

```markdown
## <repo> (Deep Dive)

### Merged PRs (N)
| # | Title | Author | Merged |
| [kagenti/\<repo\>#N](https://github.com/kagenti/\<repo\>/pull/N) | ... | ... | ... |

### Open PRs (N)
| # | Title | Author | CI | Review | Health |
| [kagenti/\<repo\>#N](https://github.com/kagenti/\<repo\>/pull/N) | ... | ... | ... | ... | ... |

### Open Issues (N)
| # | Title | Labels | Age | Status |
| [kagenti/\<repo\>#N](https://github.com/kagenti/\<repo\>/issues/N) | ... | ... | ... | ... |

### CI Health
- Main branch: X/Y passed (Z%)
- Failures: [list if any]
```

### Phase 3: Quiet Repos

For repos with no merged PRs and no new issues, present a single table:

```markdown
## Quiet Repos

| Repo | Open PRs | Open Issues | Last Activity | Note |
|------|----------|-------------|---------------|------|
| repo-x | 0 | 2 | 45 days ago | dormant |
| repo-y | 1 | 0 | 12 days ago | low activity |
```

Check the oldest issue/PR update date to determine "last activity".

### Phase 4: Cross-Repo Insights

Analyze patterns across all repos:

1. **Shared Contributors**: Which authors contributed to multiple repos this week?
2. **Related PRs**: Any PRs in different repos that reference each other or the same issue?
3. **Org CI Health**: Overall pass rate across all repos. Any repo dragging down the average?
4. **Dependency Patterns**: Any repo changes that might affect others (shared charts, common libs)?

Present as bullet list:

```markdown
## Cross-Repo Highlights

- **@author** contributed to kagenti (3 PRs) and repo-x (1 PR)
- Org CI pass rate: X% (kagenti: Y%, repo-x: Z%)
- [any notable cross-repo patterns]
```

### Phase 5: Generate Consolidated Report

Write the full report to `/tmp/kagenti/github/org-weekly-report.md`:

```markdown
# Kagenti Org Weekly Report: [start-date] - [end-date]

## Org-Wide Summary
[table from Phase 1]

## Cross-Repo Highlights
[bullets from Phase 4]

## kagenti (Deep Dive)
[full analysis from Phase 2]

## <other-active-repo> (Deep Dive)
[moderate analysis from Phase 2]

## Quiet Repos
[table from Phase 3]

## Action Items

| # | Action | Repo | Owner | Priority |
|---|--------|------|-------|----------|
| 1 | [highest priority] | kagenti | @author | P0 |
| 2 | [next action] | repo-x | @author | P1 |
...
```

Action items are a single flat list across ALL repos, ordered by priority. No timescales.

Save the report:

```bash
# Write to /tmp/kagenti/github/org-weekly-report.md
```

### Phase 6: Ask User

After generating the report, ask:

> Org-wide weekly report ready at `/tmp/kagenti/github/org-weekly-report.md`.
> Want me to create a GitHub issue in $OWNER/$REPO with this report?
> Suggested title: "Org Weekly Report [start-date] - [end-date]"
>
> You can also suggest a different repo or title.

Only create the issue after user confirms title, repo, and content.

## Context Budget

Follow the CLAUDE.md context budget rules strictly:

- **Redirect large output**: The Phase 0 script output goes to a log file
- **Use subagents for analysis**: Never read full JSON files in the main context. Use Explore subagents to extract summaries.
- **Small output OK inline**: `jq length`, `jq .totals`, repo counts — these are fine inline.

## Related Skills

- `github:last-week` - Deep single-repo report (used as the template for kagenti deep dive)
- `github:issues` - Deep dive into individual issue triage
- `github:prs` - Deep dive into individual PR health
- `ci:status` - Detailed CI check analysis
- `rca:ci` - Investigate CI failures
