# Passover: Run orchestrate:scan on kagenti/kagenti

**Date:** 2026-02-25
**From session:** Expanded orchestrate:ci skill + org-wide CI analysis

## Objective

Run `/orchestrate:scan` against kagenti/kagenti itself to identify CI improvements,
then apply them. Iterate on the orchestrate skills as needed, sending skill changes
to PR #691 and CI improvements to a separate branch.

## Two Branches in Play

| Branch | Worktree | Purpose |
|--------|----------|---------|
| `feat/repo-orchestration-skills` | `.worktrees/repo-orchestration` | Skill definitions (PR #691) |
| `orchestrate/kagenti-ci` | `.worktrees/orchestrate-kagenti-ci` | Actual CI improvements to kagenti/kagenti |

**Run Claude from:** `.worktrees/repo-orchestration` (has the skills registered)

## What Was Done

### 1. PR #691 Rebased and Extended

- Rebased `feat/repo-orchestration-skills` onto latest main (eff318c4)
- Expanded `orchestrate:ci` from 157 → 411 lines (comprehensive 3-tier CI blueprint)
- Updated `orchestrate:scan` from 180 → 300 lines (detects security scanning, dependabot coverage, action pinning, permissions model)
- Narrowed `orchestrate:security` to governance-only (CODEOWNERS, SECURITY.md, CONTRIBUTING.md, LICENSE, .gitignore)
- Fixed `orchestrate:plan` phase ordering and task lists
- PR: https://github.com/kagenti/kagenti/pull/691

### 2. All 8 Kagenti Org Repos Analyzed

Cloned to `/tmp/kagenti-ci-analysis/` (shallow clones). Full analysis results:

| Repo | Score | Tech Stack | CI Workflows | Tests in CI | Security Scanning | Dependabot |
|------|-------|-----------|-------------|-------------|-------------------|------------|
| **kagenti** | 4/5 | Python, React, Helm, Ansible | 14 | E2E only | Yes (8 jobs) | Actions only |
| **kagenti-operator** | 3.5/5 | Go, Helm | 5 (nested issue) | Yes (inner) | No | Actions only |
| **plugins-adapter** | 3/5 | Python (gRPC) | 1 | Yes | No | No |
| **.github** | 3/5 | Hugo | 4 (2 reusable) | N/A | No | No |
| **kagenti-extensions** | 2/5 | Go, Helm | 4 | No (commented) | No | Actions only |
| **agent-examples** | 1.5/5 | Python, Go | 2 | No (commented) | No | Actions only |
| **agentic-control-plane** | 1/5 | Python | 0 | No | No | No |
| **workload-harness** | 0.5/5 | Python | 0 | No | No | No |

### 3. New Worktree Created

`orchestrate/kagenti-ci` branch created from main at `.worktrees/orchestrate-kagenti-ci`.
This is where actual CI improvements to kagenti/kagenti will land.

## What To Do Next

### Step 1: Run orchestrate:scan on kagenti/kagenti

From `.worktrees/repo-orchestration`:

```
/orchestrate:scan
```

Target: the kagenti/kagenti repo itself. Since you're IN the repo, the scan
should assess the current directory. The scan report goes to
`/tmp/kagenti/orchestrate/kagenti/scan-report.md`.

### Step 2: Review scan findings

The scan should detect these known gaps for kagenti/kagenti:

**CI gaps (for orchestrate:ci to fix):**
- No unit tests in CI (backend has pytest config but no CI workflow runs them)
- No frontend CI (ui-v2 has no lint/test/typecheck workflow)
- Dependabot only covers GitHub Actions (missing: pip, npm, docker)
- Helm lint is non-blocking (exit 1 commented out, TODO)
- Flake8 warnings non-blocking (--exit-zero)
- No concurrency group on e2e-kind-pr.yaml
- pr-verifier.yaml uses unpinned action (@v0.4.3 tag, not SHA)
- spellcheck_action.yml disabled (if: false)
- Duplicate checkout/setup in bandit job (security-scans.yaml)
- No dependency caching in ci.yaml
- No test coverage reporting
- No container image signing
- Trivy k8s cluster scan always passes (continue-on-error: true)

**Governance gaps (for orchestrate:security):**
- No CODEOWNERS file
- SECURITY.md exists (good)
- No CONTRIBUTING.md

### Step 3: Iterate on skills

If the scan reveals things the skill should detect but doesn't, update the
skills in `.worktrees/repo-orchestration` and commit to `feat/repo-orchestration-skills`.

### Step 4: Apply CI improvements

After the scan, run `/orchestrate:ci` (or manually apply improvements) in
`.worktrees/orchestrate-kagenti-ci`. Create a separate PR for the actual CI changes.

### Step 5: Rebase as needed

```bash
# In repo-orchestration worktree
cd .worktrees/repo-orchestration
git fetch upstream && git rebase upstream/main
git rebase --signoff HEAD~N  # N = commits ahead
git push origin feat/repo-orchestration-skills --force-with-lease
```

## Key Files

| File | Location |
|------|----------|
| orchestrate:ci skill | `.worktrees/repo-orchestration/.claude/skills/orchestrate:ci/SKILL.md` |
| orchestrate:scan skill | `.worktrees/repo-orchestration/.claude/skills/orchestrate:scan/SKILL.md` |
| orchestrate:security skill | `.worktrees/repo-orchestration/.claude/skills/orchestrate:security/SKILL.md` |
| orchestrate:plan skill | `.worktrees/repo-orchestration/.claude/skills/orchestrate:plan/SKILL.md` |
| Design doc | `.worktrees/repo-orchestration/docs/plans/2026-02-24-orchestrate-ci-expansion-design.md` |
| Scan report (output) | `/tmp/kagenti/orchestrate/kagenti/scan-report.md` |

## After kagenti/kagenti

Once kagenti/kagenti CI is improved, run the same process on other org repos
in priority order:

1. **agentic-control-plane** (1/5, no CI at all)
2. **workload-harness** (0.5/5, no CI at all)
3. **agent-examples** (1.5/5, tests commented out)
4. **kagenti-extensions** (2/5, tests commented out)
5. **plugins-adapter** (3/5, decent but missing security)
6. **kagenti-operator** (3.5/5, nested structure to fix)
