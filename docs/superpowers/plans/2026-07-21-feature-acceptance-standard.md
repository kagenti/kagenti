# Feature Acceptance Standard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `FEATURE_ACCEPTANCE.md` — a documented, tiered feature-acceptance standard for Rossoctl — and wire it into CONTRIBUTING and a new PR template so contributors and reviewers actually use it.

**Architecture:** Three deliverables, all in the `rossoctl` (local dir `kagenti/`) repo: (1) a new root-level `FEATURE_ACCEPTANCE.md` holding the standard; (2) a link + one-paragraph pointer added to `CONTRIBUTING.md`; (3) a new `.github/pull_request_template.md` whose checklist mirrors the standard's tiers and pillars. No application code changes. The standard is human-judged, so there is no CI gate in this plan (deferred, per the spec's "Future hardening").

**Tech Stack:** Markdown only. Verification is by rendered-content grep and manual link check, not a test runner.

**Source spec:** `docs/superpowers/specs/2026-07-21-feature-acceptance-standard-design.md`

**Working-directory note:** All paths below are relative to the `kagenti/` repo root (`/Users/sabath/sandbox/kagenti-project/kagenti`). Commit with `-s` (DCO) and use `Assisted-By: Claude Code` per repo policy — never `Co-authored-by`. Before the first commit, confirm `.claude/` is gitignored (sandbox policy). Do the work on a feature branch, never on the default branch.

---

## File Structure

- **Create:** `FEATURE_ACCEPTANCE.md` (repo root) — the standard itself. One file, one responsibility: define the acceptance bar.
- **Modify:** `CONTRIBUTING.md` — add a pointer to the standard in the Pull Requests section. Minimal, non-duplicating.
- **Create:** `.github/pull_request_template.md` — the reviewer/contributor-facing checklist that operationalizes the standard.

These change together (they cross-reference), so they ship in one PR but as separate commits for reviewability.

---

## Task 1: Create FEATURE_ACCEPTANCE.md

**Files:**
- Create: `FEATURE_ACCEPTANCE.md`

- [ ] **Step 1: Write the standard document**

Create `FEATURE_ACCEPTANCE.md` at the repo root with exactly this content:

```markdown
# Feature Acceptance Standard

This document defines what makes a new feature good enough to be accepted into a
Rossoctl release. It complements — and does not replace — [CONTRIBUTING.md](./CONTRIBUTING.md)
(how to contribute) and [GOVERNANCE.md](./GOVERNANCE.md) (who decides). It defines
only *what makes a feature acceptable*.

Maintainers apply this standard at review time. It is authoritative: a maintainer
may request changes to, or decline, a feature that does not meet the applicable
bar. It is human-judged, not machine-enforced.

## How to use this document

1. When you open a pull request, state which **tier** your change is (see below)
   and complete the applicable checklist in the PR template.
2. A reviewer confirms or raises the tier and checks each applicable pillar.
3. Where a requirement already has an automated check (lint, tests, DCO sign-off,
   feature-flag config), the reviewer relies on that check rather than re-verifying
   by hand.

## Tiers

Every change is classified into one tier, which sets how much of the standard
applies. **When in doubt, go up a tier.** A reviewer may raise a change's tier at
any point.

| Tier | What it is | What applies |
|------|-----------|--------------|
| **Tier 0 — Maintenance** | Bugfix, docs-only change, dependency bump, or refactor with no behavior change | Pillar 1 (Code quality) only. No value test, no environment matrix, no feature flag. |
| **Tier 1 — Standard feature** | Net-new user-facing behavior or capability | All four pillars at baseline. Feature flag off by default. |
| **Tier 2 — Large / contested feature** | New subsystem, cross-repo change, or anything a maintainer flags as high-risk or of disputed value | Everything in Tier 1, **plus** the value scorecard and a linked design doc/spec. |

## The four pillars

### Pillar 1 — Code quality *(all tiers)*

- Passes `make lint` and pre-commit hooks.
- Tests added or updated; existing tests pass.
- Follows repository conventions and matches surrounding code.
- **Feature-flagged, off by default** (Tier 1+). See the "Feature Flags (REQUIRED)"
  section of the repo's development guide; the flag lives in
  `rossoctl/backend/app/core/config.py` and is exposed via
  `GET /api/v1/config/features`.
- DCO sign-off on every commit (`git commit -s`).
- Reviewed and approved per [GOVERNANCE.md](./GOVERNANCE.md).

### Pillar 2 — Documentation *(all tiers; scope scales with tier)*

- **Tier 0:** update any docs affected by the change.
- **Tier 1+:** user-facing docs (how to use the feature), configuration/developer
  docs (how it is wired), the **feature flag documented** in `config.py` and its
  flag table, and updated examples where applicable.
- **Tier 2:** a linked design doc or spec (under `docs/superpowers/specs/` or `docs/`).

### Pillar 3 — Real value *(Tier 1+)*

Value is established in layers, escalating with tier:

1. **Baseline (Tier 1):** the feature names a **persona / use-case** (see
   [PERSONAS_AND_ROLES.md](./PERSONAS_AND_ROLES.md)), the **problem** it solves, and
   **evidence of demand** (a GitHub issue, a user request, or a demo need).
2. **Strategic link (Tier 1):** it maps to a tracked **epic or roadmap Key Result**,
   or carries a one-line justification for why it is worthwhile opportunistic work.
3. **Working demo + example (mandatory, Tier 1+):** a runnable demonstration of the
   feature delivering its value — a demo script, an example agent/tool, or a
   documented reproducible walkthrough (e.g. under `docs/demos/` or `examples/`). It
   **must run in the required baseline environment** (local Kind + laptop), which
   ties this pillar to Pillar 4. For Tier 2, the demo covers the primary
   end-to-end use-case, not just a happy-path snippet.
4. **Scorecard (Tier 2):** score **Impact · Reach · Effort · Strategic fit** (1–5
   each). Used when the feature is large or when maintainers disagree on whether it
   earns its keep. The score is a discussion aid, not an automatic accept/reject
   threshold.

### Pillar 4 — Environment portability *(Tier 1+)*

- **Required baseline (MUST pass):** the local Kind + laptop developer loop
  (`./.github/scripts/local-setup/kind-full-test.sh`).
- **Declared best-effort:** for HyperShift, OpenShift, cloud, and sandbox, mark each
  as **Supported / Not-supported / Untested** with a one-line rationale.
- A feature legitimately scoped to a single environment is acceptable, provided the
  PR **declares** that scope rather than silently under-claiming.

## Future hardening

Selected items above may later become required CI checks (for example, a
demo-runs-in-Kind job or a feature-flag-present linter). Until then this standard is
applied by maintainers at review.
```

- [ ] **Step 2: Verify required content is present**

Run:
```bash
grep -c -E "Tier 0|Tier 1|Tier 2|Pillar 1|Pillar 2|Pillar 3|Pillar 4|Working demo|kind-full-test" FEATURE_ACCEPTANCE.md
```
Expected: a count of `9` or higher (each anchor phrase present at least once).

- [ ] **Step 3: Verify internal links resolve to real files**

Run:
```bash
for f in CONTRIBUTING.md GOVERNANCE.md PERSONAS_AND_ROLES.md; do test -f "$f" && echo "OK $f" || echo "MISSING $f"; done
```
Expected: three `OK` lines. (These are the files the doc links to.)

- [ ] **Step 4: Commit**

```bash
git add FEATURE_ACCEPTANCE.md
git commit -s -m "docs: add Feature Acceptance Standard

Defines the tiered (Tier 0/1/2) acceptance bar and four pillars
(code quality, documentation, real value, environment portability)
for accepting features into a release.

Assisted-By: Claude Code"
```

---

## Task 2: Link the standard from CONTRIBUTING.md

**Files:**
- Modify: `CONTRIBUTING.md` (Pull Requests section, after the existing template paragraph)

- [ ] **Step 1: Add the pointer**

In `CONTRIBUTING.md`, find this existing line in the "Pull Requests" section:

```markdown
See the [making PR](./docs/dev-guide.md#making-a-pr) document for detailed instructions.
```

Immediately after that line, add a blank line and this paragraph:

```markdown
Before a feature is accepted into a release it must meet the project's
[Feature Acceptance Standard](./FEATURE_ACCEPTANCE.md) — a tiered bar covering code
quality, documentation, demonstrated value, and environment portability. The pull
request template walks you through the applicable checklist.
```

- [ ] **Step 2: Verify the link was added and points at the new file**

Run:
```bash
grep -n "FEATURE_ACCEPTANCE.md" CONTRIBUTING.md && test -f FEATURE_ACCEPTANCE.md && echo "TARGET OK"
```
Expected: one matching line in `CONTRIBUTING.md` plus `TARGET OK`.

- [ ] **Step 3: Commit**

```bash
git add CONTRIBUTING.md
git commit -s -m "docs: link Feature Acceptance Standard from CONTRIBUTING

Assisted-By: Claude Code"
```

---

## Task 3: Create the PR template with the tiered checklist

**Files:**
- Create: `.github/pull_request_template.md`

- [ ] **Step 1: Write the PR template**

Create `.github/pull_request_template.md` with exactly this content:

```markdown
## What & why

<!-- Describe the problem and your solution. Link related issues. -->

Closes #

## Acceptance tier

<!-- Pick one. When in doubt, go up a tier. See FEATURE_ACCEPTANCE.md. -->

- [ ] Tier 0 — Maintenance (bugfix / docs / dependency bump / no-behavior refactor)
- [ ] Tier 1 — Standard feature (net-new user-facing behavior)
- [ ] Tier 2 — Large / contested feature (new subsystem, cross-repo, high-risk, or disputed value)

## Checklist

Complete the items for your tier. See [FEATURE_ACCEPTANCE.md](../FEATURE_ACCEPTANCE.md).

### Pillar 1 — Code quality (all tiers)

- [ ] `make lint` and pre-commit pass
- [ ] Tests added/updated and passing
- [ ] Follows repo conventions
- [ ] DCO sign-off on all commits (`git commit -s`)
- [ ] (Tier 1+) Behind a feature flag, off by default

### Pillar 2 — Documentation (all tiers; scope scales)

- [ ] Docs affected by this change are updated
- [ ] (Tier 1+) User docs, config/dev docs, and feature-flag docs updated
- [ ] (Tier 2) Linked design doc / spec

### Pillar 3 — Real value (Tier 1+)

- [ ] Names a persona/use-case, the problem, and evidence of demand
- [ ] Maps to an epic / roadmap Key Result (or justifies opportunistic value)
- [ ] **Working demo + example provided, runs in local Kind** (mandatory)
- [ ] (Tier 2) Value scorecard: Impact __/5 · Reach __/5 · Effort __/5 · Fit __/5

### Pillar 4 — Environment portability (Tier 1+)

- [ ] Passes the baseline local Kind + laptop loop (`kind-full-test.sh`)
- [ ] Declares status for other environments below

| Environment | Supported / Not-supported / Untested | Note |
|-------------|--------------------------------------|------|
| HyperShift  |                                      |      |
| OpenShift   |                                      |      |
| Cloud       |                                      |      |
| Sandbox     |                                      |      |
```

- [ ] **Step 2: Verify the template covers all tiers and pillars**

Run:
```bash
grep -c -E "Tier 0|Tier 1|Tier 2|Pillar 1|Pillar 2|Pillar 3|Pillar 4|Working demo|kind-full-test" .github/pull_request_template.md
```
Expected: a count of `9` or higher.

- [ ] **Step 3: Verify the relative link back to the standard is correct**

The template is at `.github/pull_request_template.md`, so `../FEATURE_ACCEPTANCE.md` must resolve to the repo-root file. Run:
```bash
test -f .github/../FEATURE_ACCEPTANCE.md && echo "REL LINK OK"
```
Expected: `REL LINK OK`.

- [ ] **Step 4: Commit**

```bash
git add .github/pull_request_template.md
git commit -s -m "docs: add PR template mirroring the Feature Acceptance Standard

Contributors declare an acceptance tier and complete the pillar
checklist (code quality, documentation, value, environment matrix).

Assisted-By: Claude Code"
```

---

## Task 4: Final review pass

**Files:** none (verification only)

- [ ] **Step 1: Confirm all three deliverables exist and cross-reference**

Run:
```bash
test -f FEATURE_ACCEPTANCE.md && test -f .github/pull_request_template.md \
  && grep -q FEATURE_ACCEPTANCE.md CONTRIBUTING.md \
  && grep -q FEATURE_ACCEPTANCE.md .github/pull_request_template.md \
  && echo "ALL WIRED"
```
Expected: `ALL WIRED`.

- [ ] **Step 2: Confirm no accidental duplication of the feature-flag mechanism**

The standard should *point at* the feature-flag rules, not restate the config mechanism. Run:
```bash
grep -c "rossoctl_feature_flag_" FEATURE_ACCEPTANCE.md
```
Expected: `0` (the standard references the flag concept and `config.py`, but does not copy the flag list or the naming mechanism — that lives in the dev guide / CLAUDE.md).

- [ ] **Step 3: Open the PR**

Push the branch and open a PR. The new PR template will auto-populate; fill it in for *this* PR as a Tier 0 (docs-only) change — a live dogfood of the template. Do not submit any review-approval; that is the user's decision.

---

## Self-Review (completed by plan author)

- **Spec coverage:** Artifact + location (Task 1, Task 2 link). Teeth/human-judged (Task 1 preamble). Three tiers (Task 1 table, Task 3 checklist). Four pillars incl. layered value + mandatory demo + tiered env matrix (Task 1 pillars, Task 3 checklist). Future-hardening deferral (Task 1 final section). All covered.
- **Placeholder scan:** No TBD/TODO/"add error handling"-style placeholders. All Markdown content is given verbatim.
- **Consistency:** Anchor phrases (`Tier 0/1/2`, `Pillar 1–4`, `Working demo`, `kind-full-test`) are identical across the standard, the PR template, and the verification greps. The `../FEATURE_ACCEPTANCE.md` relative path from `.github/` is verified in Task 3 Step 3.
