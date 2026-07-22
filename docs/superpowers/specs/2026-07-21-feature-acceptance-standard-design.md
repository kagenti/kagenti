# Feature Acceptance Standard — Design

Date: 2026-07-21
Status: Draft for review
Author: mrsabath (with Claude Code assistance)

## Purpose

Define what makes a new feature good enough to be accepted into a Rossoctl
release. Today the project has contribution mechanics (CONTRIBUTING.md),
governance (GOVERNANCE.md), and a contributor ladder, but no stated bar for
"is this feature ready and worth accepting." This document designs that bar.

## What this artifact is

- **File:** `FEATURE_ACCEPTANCE.md` at the root of the `rossoctl` repo,
  alongside `CONTRIBUTING.md` and `GOVERNANCE.md`.
- **Linked from:** the "Pull Requests" section of `CONTRIBUTING.md` and the PR
  template.
- **Status / teeth:** a documented standard that maintainers apply at review
  time. It is authoritative — a maintainer may decline a feature that fails it
  — but human-judged, not machine-blocked. It can harden into enforced CI gates
  later without changing the substance.
- **Relationship to existing docs:** it does not replace CONTRIBUTING (how to
  contribute) or GOVERNANCE (who decides). It defines only *what makes a
  feature acceptable*, and cites the others where a rule already lives there
  (DCO, feature flags, review policy) rather than restating them.

## Proportionality: three tiers

Every incoming change is classified into one tier, which sets how much of the
standard applies. Reviewers assign the tier; **when in doubt, go up a tier.** A
reviewer may bump a PR's tier at any point. This prevents everything being filed
as maintenance to dodge the bar.

| Tier | What it is | What applies |
|------|-----------|--------------|
| **Tier 0 — Maintenance** | Bugfix, docs-only, dependency bump, refactor with no behavior change | Code quality pillar only (lint / tests / conventions / DCO). No value test, no env matrix, no feature flag. |
| **Tier 1 — Standard feature** | Net-new user-facing behavior or capability | All four pillars at baseline. Feature flag off by default. |
| **Tier 2 — Large / contested feature** | New subsystem, cross-repo change, or anything a maintainer flags as high-risk or disputed value | Everything in Tier 1 **plus** the value scorecard and a linked design doc/spec. |

## The four pillars

### Pillar 1 — Code quality *(all tiers)*

- Passes `make lint` and pre-commit hooks.
- Tests added or updated; existing tests pass.
- Follows repository conventions (matches surrounding code).
- **Feature-flagged, off by default** (Tier 1+), per the mandate in
  `CLAUDE.md` → "Feature Flags (REQUIRED)". Cite that section; do not restate
  the mechanism.
- DCO sign-off (`git commit -s`), per CONTRIBUTING and the `commit-msg` hook.
- Reviewed and approved per GOVERNANCE.

### Pillar 2 — Documentation *(all tiers; scope scales)*

- **Tier 0:** relevant docs updated if behavior or config changed.
- **Tier 1+:** user-facing docs (how to use it), config/dev docs (how it is
  wired), the **feature flag documented** in
  `rossoctl/backend/app/core/config.py` and the flag table, examples updated if
  applicable.
- **Tier 2:** a linked design doc / spec (in `docs/superpowers/specs/` or
  `docs/`).

### Pillar 3 — Real value *(Tier 1+)* — layered test

Value is established in layers, escalating with tier:

1. **Baseline (Tier 1):** the feature names a **persona / use-case** (from
   `PERSONAS_AND_ROLES.md`), the **problem** it solves, and **evidence of
   demand** (a GitHub issue, a user request, or a demo need).
2. **Strategic link (Tier 1):** it maps to a tracked **epic or roadmap Key
   Result** — or carries a one-line explicit justification for why it is
   worthwhile opportunistic work.
3. **Working demo + example (mandatory, Tier 1+):** a runnable demonstration of
   the feature delivering its value — a demo script, an example agent/tool, or a
   documented reproducible walkthrough (e.g. under `docs/demos/` or
   `examples/`). It **must run in the required baseline environment** (local
   Kind + laptop), which ties this pillar to Pillar 4. For Tier 2 the demo
   covers the primary end-to-end use-case, not just a happy-path snippet.
4. **Scorecard (Tier 2):** score **Impact · Reach · Effort · Strategic fit**
   (1–5 each). Used when the feature is large or when maintainers disagree on
   whether it earns its keep. The score is a discussion aid, not an automatic
   accept/reject threshold.

### Pillar 4 — Environment portability *(Tier 1+)* — tiered matrix

- **Required baseline (MUST pass):** local Kind + laptop dev loop
  (`./.github/scripts/local-setup/kind-full-test.sh`).
- **Declared best-effort:** for HyperShift, OpenShift, cloud, and sandbox, each
  is marked **Supported / Not-supported / Untested** with a one-line rationale.
- A feature legitimately scoped to a single environment is acceptable, provided
  it **declares** that scope rather than silently under-claiming. The goal is an
  honest, per-feature portability statement, not a blanket "runs everywhere"
  promise that erodes.

## How it is used in practice

1. Contributor opens a PR; the PR template asks them to state the tier and fill
   the applicable checklist.
2. Reviewer confirms or bumps the tier and checks each applicable pillar.
3. Failing an applicable pillar item is grounds to request changes or decline
   the feature; the reviewer references the specific pillar.
4. Where a pillar item already has an automated gate (lint, tests, DCO,
   feature-flag config), the reviewer relies on that gate rather than
   re-checking by hand.

## Future hardening (out of scope for this doc)

- Convert selected checklist items into required CI checks (e.g. a
  demo-runs-in-Kind job, a feature-flag-present linter).
- Add a machine-readable tier label and a PR-template parser.
- These are deferred; the standard is adopted as a human-judged doc first.

## Open questions

None outstanding — all design decisions were resolved during brainstorming
(artifact type, layered value test, tiered env matrix, four pillars with demo
folded into Pillar 3, proportionality by tier).
