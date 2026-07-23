---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Rossoctl Repository Tiers — Proposal

**Status:** Draft for review
**Date:** 2026-06-03
**Audience:** Rossoctl maintainers (TL;DR + decisions); broader contributor community (full rationale)

---

## TL;DR

The Rossoctl GitHub org has ~20 repos today with no visible distinction between
production-ready projects and experiments. This proposal introduces a **two-tier
model** — **Core** and **Incubator** — signaled through three reinforcing surfaces:

1. **GitHub Custom Properties** (`tier=core|incubator`) — admin-controlled source of truth.
2. **Topics** (`rossoctl-core`, `rossoctl-incubator`) — public, filterable from any repo page.
3. **Curated index** in `rossoctl/.github/profile/README.md` and
   `rossoctl/rossoctl/docs/governance/repositories.md` — human-readable, kept in sync by automation.

Tier changes are governed by a **lightweight checklist + maintainer vote** (7-day
lazy consensus, simple majority of Core repo maintainers).

CI for any repo is owned by **that repo's own maintainers**. Org-wide CI
enforcement applies only to Core repos. Incubator repos can opt into a shared
CI workflow library to easily run the same checks Core uses, on their own
schedule.

The proposal stays within a **single GitHub org** — no sub-orgs, no repo moves,
no renames as part of this proposal. Renames may be considered as a separate
future step.

### Decisions requested from maintainers

1. Approve the two-tier model (Core / Incubator).
2. Approve the criteria and the maintainer-vote process.
3. Approve the first-pass classification of the 17 public repos.
4. Approve the phased rollout (Phases 0–4 below).

---

## Goals

This proposal addresses three goals together:

- **Discoverability** — outside users can tell at a glance which repos are
  production-ready vs. experimental.
- **Governance** — tier is a real commitment with clear criteria, a documented
  process for promotion/demotion, and automation hooks.
- **Day-to-day hygiene** — maintainers have an obvious place to put new work
  and a shared vocabulary for "is this Core?".

## Non-goals

- Splitting the Rossoctl org into sub-orgs (e.g., `rossoctl-labs`).
- Renaming existing repositories (a separate, future decision).
- Moving repository contents between repos.
- Introducing a third tier (e.g., "sandbox") — kept to two for simplicity;
  revisitable later if pain emerges.
- Tiering private repositories until/if they are made public.
- Per-component tiering within a single repository.
- Org-wide enforcement of CI on Incubator repos. CI for Incubator repos
  remains the responsibility of those repos' own maintainers; the proposal
  provides shared, **opt-in** CI workflows but does not mandate them.

---

## Background

GitHub provides no folder concept for repos within an org. Common patterns
across mature open-source orgs are:

| Pattern | Used by | Strength | Weakness |
|---|---|---|---|
| Naming prefixes (`core-*`, `lab-*`) | Many smaller orgs | Visual grouping for free | One-time rename disruption |
| Topics + curated index | CNCF, kubernetes-sigs, Istio | Filterable, no rename cost | Topics are uncontrolled; index decays |
| Custom Properties + rulesets | Newer GitHub feature, growing adoption | Admin-controlled, governance-grade | Invisible to outside users |
| Teams + CODEOWNERS | Most mature orgs | Clean ownership separation | Doesn't visually group repos |
| Sub-orgs | Very large orgs (rare) | Hardest possible isolation | Splits membership/billing/SSO |

This proposal combines the middle three (Topics + Custom Properties + Teams &
CODEOWNERS via index), explicitly **not** sub-orgs and **not** renames.

---

## The Tier Model

Tier is defined by **the commitment a repo makes to its users**, not by effort,
activity level, or perceived importance.

### Core

| Aspect | Commitment |
|---|---|
| API stability | Breaking changes follow a deprecation policy (≥1 minor release of notice). |
| Security | Vulnerabilities handled per documented SLA in `SECURITY.md`. |
| Maintainership | ≥2 active maintainers (commits in last 90 days). |
| CI | Green on `main`. CI is owned and operated by the repo's own maintainers. |
| Releases | Tagged releases, on a documented cadence. |
| Discoverability | Listed prominently in the index; recommended for production. |

### Incubator

| Aspect | Commitment |
|---|---|
| API stability | None. May change shape, may be abandoned. |
| Security | Best-effort; clearly disclaimed in README. |
| Maintainership | At least one identifiable maintainer; otherwise eligible for archival. |
| CI | Owned by the **repo's own maintainers**. Not enforced org-wide. Encouraged but not required. Shared CI workflows are available to opt into (see [Shared CI](#shared-ci-for-incubator-repos)). |
| Releases | Optional. |
| Discoverability | Listed in a separate "Incubator" section; README banner labels as experimental. |

### CI ownership

CI for any repo — Core or Incubator — is owned and operated by **that repo's
own maintainers**. Core repo maintainers are not on the hook for keeping
Incubator repos green, and vice versa. Org-level CI enforcement (Phase 4
rulesets) applies only to Core repos.

### Shared CI for Incubator repos

To make it easy for Incubator maintainers to test their repo against the same
CI pipeline Core uses, the proposal includes a **shared, opt-in CI workflow
library** maintained alongside the platform:

- A set of reusable GitHub Actions workflows (e.g., lint, security scan,
  container build, e2e against a Kind cluster) lives in
  `rossoctl/.github/.github/workflows/`, exposed as `workflow_call` reusables.
  This is the org's special `.github` repo, and GitHub's tooling — reusable-
  workflow resolution and (where supported) org-level *required workflows* /
  rulesets — recognizes workflows under that path, which a `rossoctl/rossoctl/.github/workflows/`
  or standalone `rossoctl/ci-workflows` location would not get for free.
  (Per @rubambiza on the PR thread.)
- Incubator repos opt in by adding a one-line `uses:` reference in their own
  workflow file. They control which checks run and on what triggers.
- The shared workflows are versioned (tagged) so an Incubator repo can pin to
  a known-good version and isn't broken by changes in Core's CI.
- Documentation in `docs/ci/shared-workflows.md` (added in Phase 2 alongside
  the index) describes how to opt in.

This keeps the boundary clean: Core defines and maintains the CI it cares
about; Incubator repos pick up whichever pieces are useful, on their own
schedule, without org-wide enforcement.

### Archival

Archival is **orthogonal to tier**. A repo from either tier can be archived
when work has stopped. Archival uses GitHub's built-in archive flag (which
locks the repo and visually strikes it through). The Custom Property is set
to `archived` (or removed) at archive time.

---

## Signaling: Three Layers

The same fact (a repo's tier) is expressed on three reinforcing surfaces.
Each layer covers gaps the others leave.

### Layer 1 — GitHub Custom Properties (source of truth)

The org defines a Custom Property:

```
name: tier
allowed values: core | incubator | archived
required: true (enforced after Phase 1 stamping completes)
```

Set once via org settings or `gh api`. Org-admin-controlled, so a repo
maintainer cannot unilaterally re-tier their repo — which is what makes the
maintainer-vote process load-bearing.

**API access (verified against the GitHub REST docs):**

- **Reading** property values is available to any org member:
  `GET /orgs/rossoctl/properties/values` returns every repo with its `tier`.
  So read-only automation (the reconciliation script below) needs only an
  org-member token — no admin rights.
- **Writing** values (`PATCH /orgs/rossoctl/properties/values`, ≤30 repos per
  call) and **defining the schema** require an **org admin** or a token with the
  fine-grained `custom_properties_org_values_editor` permission. Re-tiering is
  therefore admin-gated by construction, which is exactly the property we want.

This split is what keeps the model honest: anyone can *observe* the source of
truth; only an org owner (acting on a passed vote) can *change* it.

Queryable: `gh search repos --owner rossoctl props:"tier:core"`.

Custom Properties feed into **org-level rulesets** (Phase 4), which is how the
tier becomes more than a label.

### Layer 2 — Topics (public-facing filter)

Each repo gets one of:

- `rossoctl-core`
- `rossoctl-incubator`

Topics carry the tier and nothing else. We deliberately **do not** add maturity
hints (`stable`, `alpha`) on top of the tier: an Incubator repo commits to *no*
API stability, so a `stable` hint on an Incubator repo would contradict the
tier rather than refine it. (`archived` is conveyed by GitHub's built-in archive
flag and the `tier=archived` Custom Property, not by a topic.)

Topics are **publicly visible and filterable** (e.g.,
`https://github.com/orgs/rossoctl/repositories?q=topic:rossoctl-core`).
They are uncontrolled (any maintainer can edit them on their repo), so they
act as a public mirror of the source-of-truth Custom Property, not as the
source of truth itself.

### Layer 3 — Curated index

Two locations, kept in sync:

- `rossoctl/.github/profile/README.md` — what shows on the org landing page at
  `github.com/rossoctl`. Two sections: "Core projects" and "Incubator projects."
- `rossoctl/rossoctl/docs/governance/repositories.md` — same content, linked from
  main repo docs, where contributors look.

Each entry lists: repo name, one-line description, key topics, and link.

A reconciliation script in `rossoctl/automation` reads Custom Properties via the
GitHub API, regenerates both index pages, and opens a PR if drift is detected.
Runs weekly on a schedule and on the `repository.edited` webhook.

The script is **read-only** against the org: it calls
`GET /orgs/rossoctl/properties/values` and opens a normal PR with the
regenerated index. Reading property values needs only an org-member token, so
the script can run as a GitHub Action with a standard token — it does **not**
need org-owner rights or an owner PAT. Writing/re-tiering stays a manual,
admin-gated step (see Layer 1); the script never mutates the source of truth,
only mirrors it into the index.

### Why three layers and not one

| Layer alone | Gap it leaves |
|---|---|
| Custom Properties only | Invisible to outside users browsing the org. |
| Topics only | Uncontrolled — any maintainer can flip a tier. |
| Index README only | Decays without automation; no governance hook. |

The three together: governance comes from Custom Properties, public visibility
from topics, human-readable navigation from the index. The reconciliation
script binds them.

---

## First-Pass Classification

The 17 public repos in the Rossoctl org as of 2026-06-03:

### Core (6)

| Repo | Rationale |
|---|---|
| `rossoctl` | Main installer, UI, docs. The flagship; broad user surface. |
| `rossoctl-operator` | Lifecycle controller — production deployments depend on it. |
| `agent-examples` | Reference samples users copy from; examples are an API. |
| `adk` | Agent Development Kit; explicitly a "Kit" with a contract to downstream developers. |
| `cortex` | Houses AuthBridge and related stable extensions. *(May be renamed to `rossoctl-authbridge` in a future update — separate decision.)* |
| `.github` | Org profile and landing surface; Core by definition. |

### Incubator (9)

| Repo | Rationale |
|---|---|
| `plugins-adapter` | Single-purpose component, no release cadence. |
| `workload-harness` | Test/benchmarking tool, internal-feeling. |
| `adk-starter` | Template/scaffold; by nature a starter, not a stable surface. |
| `ecosystem-guide` | Reference content; could be promoted later if positioned as authoritative. |
| `OpenShell` | New, low star count, "private runtime" — fits experimental. |
| `openshell-driver-openshift` | OpenShell satellite; tier follows OpenShell. |
| `openshell-credentials-keycloak` | OpenShell satellite; tier follows OpenShell. |
| `automation` | Org-internal tooling. |
| `agent-skills` | Org-internal automation skills today; a subset is being built for broader adoption, so this is a likely promotion candidate once that surface stabilizes. |

### Archived (2)

These are no longer active and should get the GitHub archive flag and
`tier=archived` rather than an active tier.

| Repo | Rationale |
|---|---|
| `agentic-control-plane` | No longer active (per @kellyaa). |
| `capture-the-flag` | Demo / security-test scenarios that have served their purpose (per @rubambiza). |

### Out of scope

- Private repos (`rossoctl-bundle-service`, `token-broket-service`) — to be tiered
  when/if made public.

---

## Promotion, Demotion, and Archival Process

### Promotion (Incubator → Core)

Initiated by a repo maintainer via PR to a tracking issue in `rossoctl/rossoctl`.
The PR must demonstrate the following checklist:

- [ ] README clearly states scope and audience.
- [ ] CI green on `main` for the last 30 days.
- [ ] Test suite exists and runs in CI.
- [ ] At least one tagged release.
- [ ] ≥2 active maintainers (commits in last 90 days), listed in `CODEOWNERS`.
      We standardize on `CODEOWNERS` (rather than `MAINTAINERS.md`) so GitHub
      routes review requests only to the relevant repo's owners — keeping
      maintainers off notifications for repos they don't own.
- [ ] `SECURITY.md` present, documenting disclosure policy.
- [ ] Documented deprecation policy for breaking changes.
- [ ] No critical (priority/severity = high) open issues older than 90 days.

**Who votes:** the **voting body** is the maintainers (per `CODEOWNERS`) of all
`tier=core` repos, one voice per person regardless of how many repos they
maintain.

> **Bootstrap exception.** This definition is circular for the *first*
> classification — before Phase 1 runs, no repo carries `tier=core` yet, so
> there are no Core repo maintainers to vote. For that initial round only, the
> voting body is the **org's existing maintainer/owner set** (the people listed
> as org owners plus current repo maintainers). Once Phase 1 stamps the initial
> tiers, every subsequent promotion/demotion uses the Core-repo-maintainer
> definition above.

**Vote:** 7-day comment period on the tracking issue, open to that voting body.
Lazy consensus applies: the change passes unless a voting member raises an
objection during the comment period. Objections are resolved on the issue; if
unresolved at the end of the period, a simple-majority vote of the voting body
is called. The outcome is recorded in the issue.

On approval, an org admin updates the Custom Property and topics; the
reconciliation script picks up the change on its next run (or sooner if
triggered manually).

### Demotion (Core → Incubator)

Same process, triggered when **any** of:

- A Core criterion has been unmet for >90 days.
- Active maintainer count drops below 2 for >60 days.
- Maintainers themselves request it.

Demotion is not punitive — it signals to users that the previous commitment no
longer holds. A demoted repo can be re-promoted later through the standard
promotion process.

### Archival

Either tier can be archived when work has stopped. Same maintainer vote.
Archival applies GitHub's built-in archive flag and updates the Custom Property
to `archived`. Archived repos remain visible in the org but locked.

---

## Phased Rollout

Each phase is a separate decision. Nothing kicks off until Phase 0 (this
proposal) is approved. Phases are sequential; later phases assume earlier ones
are in place.

### Phase 0 — Approve the proposal and verify feature availability

Maintainer review and merge of this document, plus a **feature-availability
check** against the rossoctl org's current GitHub plan before any later phase
commits to a mechanism:

- **Custom Properties** — confirm the org can define a schema and set values
  (admin or `custom_properties_org_values_editor`).
- **Topic filtering** — confirm `topic:` org search works (it does for public
  repos on all plans, but verify our setup).
- **Org rulesets (Phase 4)** — confirm org-level rulesets can target the org's
  **public** repos on the current plan. We hit a wall here before — rulesets on
  some repos were blocked, plausibly a plan limitation — so this is verified
  *now*, not assumed. If rulesets turn out to require a paid plan we don't have,
  Phase 4 falls back to per-repo branch-protection settings on Core repos and
  the rest of the model is unaffected.

**Output:** tier model, criteria, and process are written down, and we know
which of the three signaling layers are actually available to us.

### Phase 1 — Stamp existing repos

Apply Custom Property `tier` and the matching topic to all 17 public repos per
the classification table. No renames, no content changes.
**Output:** every repo is labeled; labels are queryable.

### Phase 2 — Stand up the index and shared CI workflows

Update `rossoctl/.github/profile/README.md` and create
`rossoctl/rossoctl/docs/governance/repositories.md` with Core and Incubator
sections. First edit done manually.

In the same phase, publish the **shared CI workflow library** (lint, security
scan, container build, e2e against Kind) as `workflow_call` reusables under
`rossoctl/.github/.github/workflows/`, with `docs/ci/shared-workflows.md`
describing how Incubator repos opt in. **Output:** the org landing page and main docs reflect the tier
model; Incubator maintainers have a clear, optional on-ramp to the same CI
that Core uses.

### Phase 3 — Automate the index

Add a reconciliation script to `rossoctl/automation` that:

1. Reads Custom Properties via the GitHub API.
2. Regenerates both index pages.
3. Opens a PR if the regenerated content differs from the committed content.

Triggered weekly on schedule and on the `repository.edited` org webhook.
**Output:** indexes self-heal; manual edits are no longer required for
tier-driven content.

### Phase 4 — Apply governance (Core repos only)

Use Custom Properties as inputs to GitHub org rulesets. **Rulesets in this
phase apply only to `tier=core` repos.** Incubator repos are explicitly
excluded — their CI, branch protection, and security setup remain the
responsibility of their own maintainers.

This phase depends on the Phase 0 confirmation that org rulesets are available
on our plan. If they are not, the same starting set below is applied as
per-repo branch-protection rules on the (small) set of Core repos instead — more
manual, but the Core/Incubator boundary and the rest of the model still hold.

Likely starting set for `tier=core`:

- Require signed commits.
- Require branch protection on `main` (≥1 review, status checks must pass).
- Require `CODEOWNERS`.
- Require `SECURITY.md`.

Each rule rolled out one at a time, with maintainer notice before each.
**Output:** tier becomes load-bearing — the label correlates with enforced
behavior on Core repos, while Incubator repos retain full autonomy over their
own CI and policies.

### Phase 5 (future, optional) — Renames

Separate proposal. Candidates discussed informally:

- `cortex` → `rossoctl-authbridge`.
- Prefixing incubator repos (e.g., `lab-`).

Not part of this proposal. Listed here only to acknowledge it as a known
follow-up.

---

## Considered Alternatives

### A — Lightweight: topics + index only

Topics + a curated README, no Custom Properties, no automation.

**Rejected because:** topics alone are uncontrolled (any maintainer can flip a
tier), and the index decays without automation. The governance commitments in
this proposal would not be enforceable.

### C — Sub-org split (`rossoctl` + `rossoctl-labs`)

Move incubator repos to a separate organization.

**Rejected because:** splits membership, billing, and SSO; breaks cross-repo
references; way oversized for ~20 repos. The user-facing benefits can be
achieved within one org via the chosen approach.

---

## Open Questions

These are not blockers for approval but should be tracked:

1. **`ecosystem-guide`.** Currently classified as Incubator; could be Core if
   positioned as authoritative reference content. Defer to maintainer judgment.
2. **Reconciliation script ownership.** Lives in `rossoctl/automation`. @rubambiza
   has offered to own it and would like a co-owner; the script's `CODEOWNERS`
   entry should name both. Defaulting otherwise to the Core repo maintainer pool.

---

## Appendix — Glossary

- **Tier**: a repo's commitment level (Core or Incubator).
- **Custom Property**: GitHub org-level metadata, admin-controlled, queryable
  via API and rulesets.
- **Topic**: GitHub repo-level public tag, maintainer-editable, used for
  external filtering.
- **Index**: the human-readable list of repos by tier, in `.github/profile/README.md`
  and `docs/governance/repositories.md`.
- **Reconciliation script**: automation that keeps the index in sync with
  Custom Properties.
- **Lazy consensus**: a vote where silence over the comment period counts as
  approval.
- **Voting body**: the maintainers of all `tier=core` repos (one voice per
  person). For the first classification only, the org's existing
  maintainer/owner set stands in, since no Core repos exist yet.
