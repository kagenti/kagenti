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
