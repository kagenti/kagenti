# Audit Skills Design

## Overview

A skill family (`audit`) for periodic codebase quality assessment. Four sub-skills
scan for TODOs, CI check gaps, UI test coverage, and backend test coverage.
All produce timestamped markdown drafts in the worktree before optionally creating
GitHub issues. A CVE gate (from the `cve` skill family, separate PR) runs as a
background subagent to prevent accidental public disclosure of vulnerabilities.

## Skill Family

```
audit/SKILL.md                   # Parent router + orchestrator
audit:todos/SKILL.md             # TODO/FIXME/HACK scan
audit:ci/SKILL.md                # CI checks state + new candidate research
audit:ui-tests/SKILL.md          # UI E2E test coverage + assertion quality
audit:backend-tests/SKILL.md     # Backend test coverage + assertion quality
```

## Architecture

### Parent Orchestrator (`audit`)

Responsibilities:

1. **Worktree management** — Creates/reuses a worktree on `upstream/main` (or custom
   branch). All sub-skills run against this single worktree.
2. **Subagent dispatch** — Launches all 4 sub-skills as parallel Task agents.
3. **CVE gate** — Launches `cve:scan` as a background subagent (does not pollute
   main context). Scans iteratively (Python deps, Node deps, containers, Helm).
   Reports back only when findings exist, then continues scanning. Pending
   `cve-awareness` PR.
4. **Draft-first flow** — Sub-skills write markdown drafts to
   `docs/audits/YYYY-MM-DD/` in the worktree. Parent presents file paths to user.
   Issues are created only on user confirmation.
5. **Real cluster option** — When a `KUBECONFIG` is available, dispatches
   `rca:hypershift` / hypershift skills for live analysis (deployed versions,
   runtime config drift, security posture).

### Orchestration Flow

```
User invokes: audit
    │
    ▼
1. Create/reuse worktree on upstream/main
    │
    ▼
2. Launch cve:scan as BACKGROUND subagent        ← pending cve-awareness PR
   - iterates: Python → Node → containers → Helm
   - reports back only on findings
   - keeps scanning after each report
    │
    ▼
3. Dispatch audit sub-skills as PARALLEL subagents:
   - audit:todos
   - audit:ci
   - audit:ui-tests
   - audit:backend-tests
    │
    ▼
4. Collect all drafts, show paths to user
   docs/audits/YYYY-MM-DD/
    │
    ▼
5. Check CVE subagent results
   If findings → ALERT user, create local CVE doc (gitignored)
   Block public disclosure, surface cve:brainstorm instructions
    │
    ▼
6. Offer to create/update GH issues from drafts
   Only non-CVE findings go to public issues
   CVE items stripped from public content
```

### Output Directory Structure

```
docs/audits/YYYY-MM-DD/
├── todos.md
├── ci-checks.md
├── ui-test-coverage.md
├── backend-test-coverage.md
└── CVE-HOLD/                    # gitignored, local only
    ├── cve-findings.md
    └── DO-NOT-COMMIT.md
```

## Issue Lifecycle

All sub-skills share the same lifecycle.

### Issue Naming

`[Audit] <type> scan - <YYYY-MM-DD>`

Examples:
- `[Audit] TODO scan - 2026-02-15`
- `[Audit] CI checks - 2026-02-15`
- `[Audit] UI test coverage - 2026-02-15`
- `[Audit] Backend test coverage - 2026-02-15`

### Monthly Rotation

1. Search for existing open issue by prefix `[Audit] <type> scan` + `audit` label.
2. If exists and < 30 days old: update with new findings, append to update log.
3. If exists and >= 30 days old: close with summary comment, create new issue
   linking back.
4. If none exists: create new issue.

### Update Log

Every issue ends with:

```markdown
## Update Log
| Date | Action | Summary |
|------|--------|---------|
| 2026-02-15 | Created | Initial scan: 47 TODOs found |
| 2026-02-22 | Updated | 3 resolved, 2 new. Net: 46 |
| 2026-03-15 | Closed | Rotated → #189. 12 resolved in cycle. |
```

When an issue is closed and a new one created, the update log starts fresh in the
new issue with a link to the predecessor.

## Sub-skill: `audit:todos`

### Purpose

Scan for TODO/FIXME/HACK/XXX/WORKAROUND/TEMPORARY comments. Categorize by topic
and outline the proper fix for each.

### Workflow

1. Grep worktree for patterns. Exclude `.venv/`, `node_modules/`, `.worktrees/`,
   vendor directories.
2. Group by topic: security, error handling, missing tests, performance,
   cleanup/refactoring, incomplete features.
3. For each: file path, line, surrounding context, fix recommendation.
4. Summary stats: total count, by severity, by area, delta from previous scan.

### Draft Template

```markdown
# TODO Scan - YYYY-MM-DD

## Summary
- **Total**: N TODOs across M files
- **By severity**: X security, Y error handling, Z missing tests, W cleanup
- **Delta from last scan**: +A new, -B resolved

## 1. Security-Related
### 1.1 <title>
- **File**: `path/to/file.py:42`
- **TODO**: `# TODO: remove hardcoded fallback`
- **Recommendation**: Use Keycloak service account, remove fallback path

## 2. Error Handling Gaps
...

## Update Log
| Date | Action | Summary |
```

## Sub-skill: `audit:ci`

### Purpose

Audit CI security and quality checks. Two sections: current state assessment
(first), then new candidate research.

### Workflow

**Section A — Current State Assessment:**

1. Read all workflow files under `.github/workflows/`.
2. For each check determine:
   - Scope (language/files covered)
   - Severity threshold (fails on critical? high? all?)
   - Strict mode availability and whether it is enabled
   - Blocking (required check) vs informational
   - Exit code behavior
3. Fetch last CI run on main (post-merge) via `gh run list --branch main`.
4. Download logs, parse warnings/errors by check.
5. Produce sorted list of warnings/errors by topic.
6. Stats table per check.

**Section B — New Candidate Research:**

1. Curated list for this stack:
   - Python: semgrep, pyright/mypy, safety, pip-audit
   - TypeScript: biome, oxlint
   - Helm: helm-unittest, pluto (deprecated APIs)
   - Docker: dockle, grype
   - K8s manifests: kubesec, kube-linter, polaris
   - General: megalinter, checkov
   - Markdown: markdownlint
2. Web search for recent additions (2025-2026).
3. For each candidate: coverage, overlap, value-add, integration effort.
4. Flag areas with no CI coverage.

### Draft Template

```markdown
# CI Checks Audit - YYYY-MM-DD

## Summary
- **Active checks**: N tools across M workflows
- **Blocking**: X | **Informational**: Y
- **Total warnings in last run**: Z
- **Uncovered areas**: list

## 1. Current Check Assessment

| Check | Scope | Threshold | Strict Mode? | Enabled? | Blocking? | Warnings | Errors |
|-------|-------|-----------|-------------|----------|-----------|----------|--------|

## 2. Warnings/Errors Detail (last main CI run)
### 2.1 <check> (N warnings)
- `file:line` — description

## 3. New Candidate Recommendations
### 3.1 <tool>
- **Covers**: ...
- **Overlap**: ...
- **Value-add**: ...
- **Effort**: ...

## Update Log
| Date | Action | Summary |
```

## Sub-skill: `audit:ui-tests`

### Purpose

Deep analysis of UI E2E test coverage and assertion quality. Verify tests are
assertive and actually testing the right thing.

### Workflow

1. **Inventory** — Map all pages/components in `kagenti/ui-v2/src/` to test files
   in `kagenti/ui-v2/e2e/`.
2. **Coverage gap analysis** — Which pages/components have zero test coverage.
3. **Assertion quality audit** — For each test file:
   - Are assertions present and specific (not just visibility checks)?
   - Are tests testing actual behavior vs mock behavior?
   - Empty test bodies, `test.skip` without justification?
   - Overly broad try/catch swallowing failures?
   - Edge cases vs happy path only?
4. **Structural quality** — Test naming, selector resilience (data-testid vs
   fragile selectors), wait strategies, auth flow coverage, fixture quality,
   test isolation, flaky test indicators.
5. **TLDR + detailed findings**.

### Draft Template

```markdown
# UI E2E Test Coverage Audit - YYYY-MM-DD

## TLDR
**Well tested**: <brief list>
**Gaps**: X of Y pages have zero coverage. <key issues>

## Summary
- **Pages**: Y total, A tested, B untested
- **Components**: C total, D unit tested
- **Test files**: E specs, F lines
- **Assertion quality**: G% strong, H% weak

## 1. Coverage Matrix
| Module | Test File | Assertions | Quality |
|--------|-----------|------------|---------|

## 2. Assertion Quality Issues
### 2.1 <file>:<line> — <issue>
- **Test**: "test name"
- **Issue**: description
- **Recommendation**: fix

## 3. Untested Pages
### 3.1 <page>
- **Risk**: impact
- **What to test**: suggestions

## 4. Structural Issues
### 4.1 <issue>

## Update Log
| Date | Action | Summary |
```

## Sub-skill: `audit:backend-tests`

### Purpose

Deep analysis of backend test coverage and assertion quality. Same depth as
`audit:ui-tests` but targeting Python pytest tests.

### Workflow

1. **Inventory** — Map all routers/services/models in `kagenti/backend/app/` to
   test files in `kagenti/backend/tests/`.
2. **Coverage gap analysis** — Which modules have no tests.
3. **Assertion quality audit** — For each test file:
   - Specific assertions vs `assert True`?
   - Testing actual logic vs testing mocks?
   - Parametrized tests for edge cases?
   - Proper async test patterns?
   - `pytest.skip` / `pytest.mark.skip` without justification?
4. **Structural quality** — Fixture scope, test isolation, naming conventions,
   proper teardown, conftest organization.
5. **TLDR + detailed findings**.

### Draft Template

```markdown
# Backend Test Coverage Audit - YYYY-MM-DD

## TLDR
**Well tested**: <brief list>
**Gaps**: X routers have zero direct tests. <key issues>

## Summary
- **Modules**: Y total, A tested, B untested
- **Test files**: C files, D lines
- **Assertion quality**: E% strong, F% weak

## 1. Coverage Matrix
| Module | Test File | Assertions | Quality |
|--------|-----------|------------|---------|

## 2. Assertion Quality Issues
### 2.1 <file>:<line> — <issue>

## 3. Untested Modules
### 3.1 <module>
- **Risk**: impact
- **What to test**: suggestions

## 4. Structural Issues

## Update Log
| Date | Action | Summary |
```

## CVE Integration (pending cve-awareness PR)

The `cve` skill family (being built in `.worktrees/cve-awareness`) provides:

- `cve:scan` — Hybrid vulnerability detection (Trivy + LLM + WebSearch)
- `cve:brainstorm` — Responsible disclosure and public output blocking

### Integration Points in Audit

1. `cve:scan` runs as a **background subagent** via `Task` with
   `run_in_background: true`.
2. Iterates over dependency categories without polluting main audit context.
3. Reports back to parent only when findings exist, then continues scanning.
4. If ANY CVE found:
   - User gets immediate terminal alert.
   - Findings written to `docs/audits/YYYY-MM-DD/CVE-HOLD/` (gitignored).
   - `cve:brainstorm` instructions surfaced.
   - Public GH issues are scrubbed of CVE-related content.
   - No CVE details in commit messages, PR descriptions, or issue comments.
5. Resolution paths per `cve:brainstorm`: proper disclosure channel, silent
   dependency bump, false positive, or explicit user override.

### Dependency

This PR depends on the `cve-awareness` PR. Skill files will include placeholder
sections marked `# CVE GATE (pending cve-awareness PR)` until that work merges.

## Real Cluster Scanning

When a `KUBECONFIG` is set or user requests live analysis:

1. Parent dispatches `rca:hypershift` for runtime assessment.
2. Additional checks: deployed image versions vs latest, runtime config drift
   from Helm values, exposed ports, missing network policies.
3. Findings merged into relevant draft sections (ci-checks for config drift,
   backend-tests for runtime behavior, etc.).

## Labels

All audit issues use the `audit` GitHub label. Sub-types are distinguished by
the issue title prefix.

## Decisions

- **Parent name**: `audit` — chosen for periodic review/assessment connotation.
- **Issue rotation**: Close old + create new after 30 days. Update log starts
  fresh with link to predecessor.
- **Draft-first**: Always write markdown drafts before creating issues. User
  confirms before any GH issue creation.
- **Test depth**: Structural + code-level analysis. Check assertion quality,
  test naming, fixture patterns, skip justifications.
- **CI research**: Curated list of known tools + live web search for recent
  additions.
- **CVE handling**: Background subagent, local-only findings, public disclosure
  blocked. Pending separate PR.
