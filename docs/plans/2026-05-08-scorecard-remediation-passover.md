---
draft: true       # excluded from https://www.rossoctl.dev/
---

# OpenSSF Scorecard Remediation — Passover

**Date:** 2026-05-08
**Current score:** 6.8/10 (was 7.2)
**Branch:** new worktree needed
**Priority:** Medium — non-blocking but visible regression

## Score Drop Analysis

Overall dropped from **7.2 → 6.8** after recent merges (2026-05-07).

### Check-by-check breakdown

| Check | Score | Change | Action needed |
|-------|-------|--------|---------------|
| Code-Review | **5** | **10→5** | Main drop — 4/8 sampled changesets approved |
| Token-Permissions | 9 | unchanged | 4 new alerts from PR #1489 (openshell workflows) |
| Pinned-Dependencies | 6 | unchanged | Dockerfiles + scripts use unpinned installs |
| Security-Policy | 4 | unchanged | Policy file exists but needs linked content |
| Branch-Protection | 1 | unchanged | Only 1 approval required, force push allowed on release |
| Vulnerabilities | 0 | unchanged | 12 open CVEs |
| CII-Best-Practices | 0 | unchanged | No OpenSSF badge |
| Fuzzing | 0 | unchanged | No fuzzing integration |

### Root cause: Code-Review 10→5

Scorecard sampled 8 recent changesets and only 4 met its review criteria. The issue is **dependabot PRs** — 5 of the 8 most recent merges are dependabot bumps, each with exactly 1 approval. Scorecard may require 2+ reviewers or treat auto-merge differently.

Recently merged PRs (all have approvals, but many are 1-approval dependabot):
- #1501 dependabot node bump — 1 approval
- #1503 dependabot minor-patch — 1 approval
- #1504 dependabot ubi-minimal — 1 approval
- #1505 dependabot minor-patch — 1 approval
- #1506 dependabot setup-uv — 1 approval
- #1509 readme fix — 1 approval
- #1511 UI fix — 1 approval
- #1484 hypershift cleanup — 2 approvals

### Token-Permissions: 4 alerts from PR #1489

Alerts on main (all `statuses: write` at job level):
- `.github/workflows/e2e-openshell-kind.yaml` lines 60, 129
- `.github/workflows/e2e-openshell-hypershift.yaml` lines 35, 234

PR #1498 adds `e2e-openshell-pending.yaml` to consolidate pending status into one workflow, which should reduce 2 of these 4 alerts (removing `statuses: write` from authorize jobs).

## Remediation Plan

### Quick wins (can fix immediately)

1. **Dependabot auto-merge policy** — require 2 approvals for dependabot PRs, or configure dependabot to batch updates (fewer PRs = fewer review samples)
   - File: `.github/dependabot.yml` — add grouping strategy
   - File: `.github/workflows/` — review auto-merge workflow

2. **Token-Permissions cleanup** — PR #1498 already moves pending status to a dedicated workflow. After merge, 2 of 4 alerts should clear. For the remaining 2 (`statuses: write` in post-results jobs), these are unavoidable for commit status reporting.

### Medium effort

3. **Pinned-Dependencies (6→8+)** — pin Dockerfile base images and `pip install` to hashes
   - Dockerfiles using `FROM python:3.14-slim` → add `@sha256:...`
   - Scripts using `pip install boto3` → pin versions
   - ~15 files to update

4. **Security-Policy (4→7+)** — enhance SECURITY.md with:
   - Vulnerability disclosure process
   - Security contact email
   - Link to security advisories

5. **Branch-Protection (1→5+)** — GitHub repo settings:
   - Require 2 approvals (currently 1)
   - Disable force push on main
   - Require status checks to pass
   - Require branches to be up to date

### Longer term

6. **Vulnerabilities (0→5+)** — triage and fix the 12 open CVEs
7. **CII-Best-Practices (0→5+)** — apply for OpenSSF Best Practices badge
8. **Signed-Releases (-1→5+)** — set up GitHub releases with signing

## Session Startup Text

For the new worktree session working on Scorecard remediation:

```
I need to fix the OpenSSF Scorecard regression — the project score dropped from 7.2 to 6.8.
The main issue is Code-Review (10→5) because dependabot PRs with 1 approval are dragging
the sample down. The passover doc is at docs/plans/2026-05-08-scorecard-remediation-passover.md.

Focus areas:
1. Dependabot PR grouping to reduce review sample noise
2. Branch protection: bump to 2 required approvals
3. Token-Permissions: merge PR #1498 which consolidates pending status workflows
4. Pin dependencies in Dockerfiles and scripts
5. Enhance SECURITY.md

Target: 7.5+ overall score. Quick wins (1-2) should recover Code-Review to 8+.
```
