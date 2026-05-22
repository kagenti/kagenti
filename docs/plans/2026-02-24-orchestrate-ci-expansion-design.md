# Orchestrate:CI Expansion Design

**Date:** 2026-02-24
**Status:** Approved

## Problem

The `orchestrate:ci` skill generates basic lint/test/build workflows but the kagenti/kagenti
main repo has evolved a comprehensive CI standard with 14 workflows covering security scanning,
dependency review, action pinning, least-privilege permissions, and more. Satellite repos in the
kagenti org score 0.5-3.5 out of 5 on CI maturity. The orchestrate skills need to encode the
full standard.

## Analysis

### Kagenti Org CI Maturity

| Repo | Score | Key Gaps |
|------|-------|----------|
| kagenti (main) | 4/5 | No unit tests in CI, no CODEOWNERS, dependabot Actions-only |
| kagenti-operator | 3.5/5 | Nested workflow structure, no security scanning |
| plugins-adapter | 3/5 | No dependabot, no security scanning |
| .github | 3/5 | Org config, reusable workflows |
| kagenti-extensions | 2/5 | Tests commented out, no security scanning |
| agent-examples | 1.5/5 | Tests commented out, no pre-commit |
| agentic-control-plane | 1/5 | No CI at all |
| workload-harness | 0.5/5 | No CI at all |

### Org-Wide Gaps

- No repo has CODEOWNERS
- No satellite repo has security scanning
- Only 2/7 satellites run tests in CI
- Dependabot never covers application dependencies
- No coverage reporting anywhere

## Design

### Skill Restructuring

**orchestrate:ci** expands from basic lint/test/build to comprehensive CI blueprint:

- **Tier 1 (Universal):** ci.yml, security-scans.yml, dependabot.yml (all ecosystems), scorecard, action pinning check
- **Tier 2 (Conditional):** Container builds, multi-arch, stale/PR-verifier (org reusable workflows)
- **Tier 3 (Advanced Optional):** Comment-triggered E2E, post-merge security, TOCTOU protection

**orchestrate:security** narrows to governance-only: CODEOWNERS, SECURITY.md, CONTRIBUTING.md, LICENSE, .gitignore audit, branch protection docs.

**orchestrate:scan** gains CI maturity detection: security scanning coverage, dependabot ecosystem completeness, action pinning compliance, permissions model, container build presence.

### Output Style

Hybrid: structured guidance for architecture decisions + verbatim YAML snippets for security-critical patterns (permissions blocks, Trivy config, dependabot multi-ecosystem, CodeQL setup, dependency review with license deny list).

### Size Estimates

- orchestrate:ci: ~350-400 lines (up from 157)
- orchestrate:scan: ~220 lines (up from 180)
- orchestrate:security: ~140 lines (down from 173)
