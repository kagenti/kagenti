---
name: github:pr-review
description: Automated PR review for Kagenti - conventions, security, CI status, inline comments
---

```mermaid
flowchart TD
    START([PR Review]) --> GATHER["Phase 1: Gather"]:::github
    GATHER --> ANALYZE["Phase 2: Analyze"]:::github
    ANALYZE --> REVIEW["Phase 3: Review"]:::github
    REVIEW --> DRAFT["Phase 4: Draft"]:::github
    DRAFT -->|User approves| SUBMIT["Phase 5: Submit"]:::github
    DRAFT -->|User edits| DRAFT

    classDef github fill:#E91E63,stroke:#333,color:white
```

> Follow this diagram as the workflow.

# PR Review

Automated code review workflow for the kagenti/kagenti repository. Gathers PR data,
analyzes the diff, checks against repo conventions and CI, drafts inline review
comments, and posts a GitHub review after user approval.

## Table of Contents

- [When to Use](#when-to-use)
- [Context-Safe Execution](#context-safe-execution-mandatory)
- [Phase 1: Gather PR Data](#phase-1-gather-pr-data)
- [Phase 2: Analyze Changes](#phase-2-analyze-changes)
- [Phase 3: Review Checklist](#phase-3-review-checklist)
- [Phase 4: Draft Review](#phase-4-draft-review)
- [Phase 5: Submit Review](#phase-5-submit-review)
- [Troubleshooting](#troubleshooting)
- [Related Skills](#related-skills)

## When to Use

- Reviewing a PR before approving or requesting changes
- Checking a PR against Kagenti conventions before merge
- Providing structured, inline feedback on PRs
- Invoked as `/github:pr-review <PR-number>`

## Context-Safe Execution (MANDATORY)

PR diffs can be very large. **Always redirect diff output to files and analyze with subagents.**

```bash
export LOG_DIR=/tmp/kagenti/review/$(basename $(git rev-parse --show-toplevel))
mkdir -p $LOG_DIR
```

Small output OK inline: `gh pr checks`, `gh pr view --json` (metadata only).

Large output MUST redirect: `gh pr diff`, commit logs, file contents.

## Phase 1: Gather PR Data

Collect all PR metadata, diff, CI status, and commit history.

### 1.1 PR Metadata

```bash
gh pr view <number> --json number,title,body,author,baseRefName,headRefName,commits,files,reviews,reviewDecision,labels,createdAt,updatedAt
```

### 1.2 PR Diff

```bash
gh pr diff <number> > $LOG_DIR/pr-<number>.diff 2>&1; echo "EXIT:$?"
```

### 1.3 CI Status

```bash
gh pr checks <number>
```

If checks are failing, delegate to `ci:status` for detailed analysis.

### 1.4 Commit History

```bash
gh pr view <number> --json commits --jq '.commits[] | "\(.oid[:7]) \(.messageHeadline)"'
```

## Phase 2: Analyze Changes

Use a subagent to categorize the diff by area and produce a summary.

```
Task(subagent_type='Explore'):
  "Read $LOG_DIR/pr-<number>.diff. Categorize changed files into these areas:
   Python, Helm/K8s, Shell, YAML, Dockerfile, CI/GitHub Actions, Docs, Frontend, Other.
   For each area return: files changed, lines added/removed.
   Return a brief summary of what the PR does overall (2-3 sentences).
   Do NOT return the full diff content."
```

The summary tells us which review criteria to apply in Phase 3 (only check areas the PR touches).

## Phase 3: Review Checklist

Apply Kagenti-specific review criteria **only for areas the PR touches**.

### 3.1 Commit Conventions

Check all commits against `git:commit` conventions:

| Check | Criteria |
|-------|----------|
| Signed-off | Every commit has `Signed-off-by:` line |
| Emoji prefix | Subject starts with recognized emoji (see `git:commit`) |
| Imperative mood | "Add feature" not "Added feature" |
| Length | Subject line under 72 characters |

```bash
# Check sign-off on all PR commits
gh pr view <number> --json commits --jq '.commits[].messageBody' | grep -c 'Signed-off-by'
```

### 3.2 PR Format

Check against `repo:pr` conventions:

| Check | Criteria |
|-------|----------|
| Title | Has emoji prefix, under 72 chars |
| Summary section | Body contains `## Summary` |
| Issue linking | `Fixes #N` or `Closes #N` if applicable (optional) |

### 3.3 Python Changes

If the PR touches `.py` files:

| Check | What |
|-------|------|
| Formatting | Would `ruff format --check` pass? |
| Linting | Any pylint/ruff issues in changed files? |
| Security | No `bandit` HIGH severity issues in changed code |
| Imports | Clean imports, no unused |

### 3.4 Helm / Kubernetes Changes

If the PR touches `charts/`, K8s manifests, or values files:

| Check | What |
|-------|------|
| Chart lint | `helm lint` would pass |
| Labels | Uses `kagenti.io/*` labels where appropriate |
| Resource limits | Containers have resource requests/limits |
| Values | New values documented or self-explanatory |

### 3.5 Security

Always check regardless of area:

| Check | What |
|-------|------|
| Secrets | No hardcoded secrets, tokens, passwords in diff |
| Actions | GitHub Action versions pinned to SHA (not `@main` or `@v1`) |
| Dependencies | New dependencies reviewed for supply-chain risk |
| Dockerfiles | Non-root user, pinned base images |

### 3.6 Shell Scripts

If the PR touches `.sh` files:

| Check | What |
|-------|------|
| Shellcheck | Would `shellcheck` pass? |
| Error handling | Uses `set -euo pipefail` or equivalent |
| Quoting | Variables properly quoted |

### 3.7 YAML

If the PR touches `.yaml`/`.yml` files:

| Check | What |
|-------|------|
| yamllint | Would `yamllint` pass? |
| Indentation | Consistent indentation |

### 3.8 Tests

| Check | What |
|-------|------|
| Coverage | New features have corresponding tests |
| Quality | Tests are assertive, no hidden skips (delegate to `test:review`) |
| E2E | User-facing changes have E2E coverage |

### 3.9 Documentation

| Check | What |
|-------|------|
| Updated | User-facing changes have docs/README updates |
| Accurate | Docs match the actual behavior |

## Phase 4: Draft Review

Present proposed review to user for approval before posting.

### 4.1 Inline Comments Table

```markdown
## Proposed Review Comments

### Inline Comments
| # | File | Line | Severity | Comment |
|---|------|------|----------|---------|
| 1 | path/to/file.py | 42 | must-fix | Description of issue... |
| 2 | charts/values.yaml | 15 | suggestion | Consider adding... |
| 3 | scripts/deploy.sh | 8 | nit | Minor style issue... |
```

Severity levels:
- **must-fix** - Blocks merge. Security issues, broken functionality, missing sign-off.
- **suggestion** - Should fix but not blocking. Better patterns, missing tests.
- **nit** - Trivial. Style, naming, minor improvements.
- **praise** - Highlight good patterns worth calling out.

### 4.2 Summary Comment

```markdown
### Summary
[2-3 sentence overview of the review findings]

**Areas reviewed**: Python, Helm, CI (list areas actually checked)
**Commits**: N commits, all signed-off: yes/no
**CI status**: passing/failing/pending
```

### 4.3 Verdict

One of:
- **APPROVE** - No must-fix issues, PR follows conventions
- **REQUEST_CHANGES** - Has must-fix issues that block merge
- **COMMENT** - Suggestions only, author can decide

### 4.4 User Approval

Present the full draft and ask user to approve, edit, or cancel:

```
AskUserQuestion:
  "Review draft ready. Approve to submit, or edit first?"
  Options: ["Submit as-is", "Edit comments first", "Cancel review"]
```

## Phase 5: Submit Review

After user approves, post the review via GitHub API.

### 5.1 Post Review with Inline Comments

```bash
# Build the review payload
# For each inline comment: path, line (in the diff), body
# event: APPROVE, REQUEST_CHANGES, or COMMENT

gh api repos/{owner}/{repo}/pulls/<number>/reviews \
  --method POST \
  -f body="Review summary text..." \
  -f event="COMMENT" \
  -f 'comments[0][path]=path/to/file.py' \
  -f 'comments[0][line]=42' \
  -f 'comments[0][body]=Comment text...' \
  -f 'comments[1][path]=charts/values.yaml' \
  -f 'comments[1][line]=15' \
  -f 'comments[1][body]=Another comment...'
```

> **Note**: `gh api` is NOT auto-approved. The user will be prompted to approve
> the review submission. This is intentional — reviews are write operations.

### 5.2 Confirm Submission

After posting, confirm with a link:

```markdown
Review submitted on PR #<number>: https://github.com/kagenti/kagenti/pull/<number>
- Verdict: APPROVE / REQUEST_CHANGES / COMMENT
- Inline comments: N
```

## Troubleshooting

### Line numbers in diff vs file

The `line` parameter in the review API refers to the line number in the **diff hunk**,
not the file. Use the diff output to determine correct line numbers. The `line` field
should be the line number in the file on the HEAD side of the diff.

### Review already exists

GitHub allows multiple reviews. A new review will be added alongside existing ones.

### Large PRs (> 500 changed lines)

For very large PRs, focus the review on:
1. Security issues (always)
2. Architecture / design concerns
3. Convention violations
4. Skip nit-level comments to avoid noise

### PR from fork

For PRs from forks, `gh pr diff` still works but branch checkout may not.
Use the diff file for all analysis.

## Related Skills

- `ci:status` - Detailed CI check analysis for failing PRs
- `test:review` - Deep test quality review
- `repo:pr` - PR format conventions
- `git:commit` - Commit format conventions
- `github:prs` - PR health overview (batch analysis)
- `rca:ci` - Root cause analysis when CI fails
