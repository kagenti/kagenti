# Feature Acceptance Standard

This document defines what makes a new feature good enough to be accepted into a
Rossoctl release. It complements, and does not replace, [CONTRIBUTING.md](./CONTRIBUTING.md)
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
| **Tier 0 — Maintenance** | Bugfix, docs-only change, dependency bump, or refactor with no behavior change | Pillar 1 (Code quality) only. No Pillar 3 value requirement, no Pillar 4 environment declaration, no feature flag. |
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
   feature delivering its value: a demo script, an example agent/tool, or a
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
