# Renaming Kagenti → Rossoctl: Migration Playbook

> **Status:** Proposal for review · Tracking issue: [kagenti/kagenti#1972](https://github.com/kagenti/kagenti/issues/1972)
> **This file is temporary.** It lives in `kagenti/kagenti` only so the team can review it and add detail in one place. Delete it once the rename lands and #1972 closes.
> **Audience:** humans. The machine-readable execution steps live in the companion **`rossoctl-rename-prompt.md`** (same folder), which Claude Code reads to do the per-repo work — see §8.
> **How to give feedback:** comment inline on the PR, or edit the relevant section. Every item marked *"Open — needs a call"* is a decision we still owe an answer to; every *"Owner: assign in review"* needs a name.

---

## 1. What this is

We're renaming the project from **Kagenti** to **Rossoctl** — the brand, the GitHub org, the repositories, the code, the container images, the Kubernetes API surface, the docs, and every external place the name shows up.

This document is the source of truth for that work:

- The **naming decisions** — what every flavor of "kagenti" becomes.
- The **scope and order** — which repos, in what sequence, and why.
- The **rename mechanics** — what changes in code, on GitHub, in the cluster, and out in the community.
- The **verification** each repo must pass before its PR merges.
- The **rollout, owners, risks, and rollback.**

We rename **one repo at a time**, in dependency order, each behind its own tested PR. "Full cutover" (§14) describes *what* we rename, not *how fast* — the sequencing is deliberately incremental.

---

## 2. The naming decisions

**Brand:** every human-facing "Kagenti" becomes "Rossoctl" (and "kagenti" → "rossoctl").

**Repositories** (the GitHub org itself renames `kagenti` → `rossoctl`):

| Today | Becomes | Notes |
|---|---|---|
| `kagenti/kagenti` | `rossoctl/rossoctl` | Flagship: installer, backend, UI, TUI, docs |
| `kagenti/kagenti-operator` | `rossoctl/operator` | Kubernetes operator |
| `kagenti/kagenti-extensions` | `rossoctl/rossocortex` | AuthBridge + security extensions |
| `kagenti/agent-examples` | `rossoctl/examples` | Sample agents & tools — **our pilot** |
| every other **public, active** repo | keep name, sweep content | See §3 |

### The full string map

This is the contract. When in doubt, this table wins.

| Category | Old | New |
|---|---|---|
| Brand (prose, UI, comments) | `Kagenti` / `kagenti` | `Rossoctl` / `rossoctl` |
| GitHub org | `github.com/kagenti` | `github.com/rossoctl` |
| Go module — operator | `github.com/kagenti/operator` | `github.com/rossoctl/operator` |
| Go module — token-broker | `github.com/kagenti/token-broker` | `github.com/rossoctl/token-broker` |
| Go module — extensions (7 modules) | `github.com/kagenti/kagenti-extensions/…` | `github.com/rossoctl/rossocortex/…` |
| Go module — TUI | `github.com/kagenti/kagenti/kagenti/tui` | `github.com/rossoctl/rossoctl/rossoctl/tui` |
| Go module — examples MITM | `github.com/kagenti/mcp-mitm` | `github.com/rossoctl/mcp-mitm` |
| Python import root | `kagenti/` (`import kagenti…`) | `rossoctl/` (`import rossoctl…`) |
| Python dist names | `kagenti-project`, `kagenti-backend` | `rossoctl-project`, `rossoctl-backend` |
| Python console script | `kagenti-sparc-service` | `rossoctl-sparc-service` |
| npm package | `@kagenti/ui` | `@rossoctl/ui` |
| Java Maven groupId / package | `io.kagenti.keycloak(.authenticator)` | `io.rossoctl.keycloak(.authenticator)` |
| Container image namespace | `ghcr.io/kagenti/*` | `ghcr.io/rossoctl/*` |
| Helm charts | `kagenti`, `kagenti-deps`, `kagenti-operator-chart`, `kagenti-webhook-chart` | `rossoctl`, `rossoctl-deps`, `operator-chart`, `rossocortex-webhook-chart` |
| **CRD group — agents** | `agent.kagenti.dev` | `agent.rossoctl.dev` |
| **CRD group — mcp** | `mcp.kagenti.com` | `mcp.rossoctl.com` |
| **Label / annotation domains** | `kagenti.io/*`, `protocol.kagenti.io/*`, `inject.kagenti.io`, `integrations.kagenti.io`, `openshell.kagenti.io` | `rossoctl.io/*`, `protocol.rossoctl.io/*`, `inject.rossoctl.io`, `integrations.rossoctl.io`, `openshell.rossoctl.io` |
| **API version** | `kagenti.io/v1alpha1` | `rossoctl.io/v1alpha1` |
| **Namespaces** | `kagenti-system`, `kagenti-webhook-system`, `kagenti-traces` (operator) | `rossoctl-system`, `rossoctl-webhook-system`, `rossoctl-traces` |
| Controller / release names | `kagenti-operator`, `kagenti-controller-manager` | `rossoctl-operator`, `rossoctl-controller-manager` |
| **Keycloak realm + OAuth client** | realm `kagenti`, `client_id`/`azp` = `kagenti` | realm `rossoctl`, client `rossoctl` |
| **SPIFFE trust domain** | `kagenti.local`, `kagenti.example.com` | `rossoctl.local`, `rossoctl.example.com` |
| **Env var prefix** | `KAGENTI_*` (`KAGENTI_NS`, `KAGENTI_REPO`, `KAGENTI_CONFIG_FILE`, …) | `ROSSOCTL_*` |
| Kind cluster names (dev) | `kagenti`, `kagenti-dev` | `rossoctl`, `rossoctl-dev` |
| Dev hostnames | `kagenti-ui.localtest.me` | `rossoctl-ui.localtest.me` |

**The bold rows are runtime contracts** — live clusters, issued identities, and existing installs depend on them. They do **not** ride on GitHub redirects, and they can't be safely find-and-replaced. They get the migration treatment in **§5.3 and §5.4**.

> **Open — needs a call:** we assume the org owns (or can register) `rossoctl.dev`, `rossoctl.io`, and `rossoctl.com` for the CRD groups and label domains. **Confirm domain ownership before touching any CRD group** — otherwise the suffixes change and this table changes with them.

---

## 3. Scope and order

The GitHub **org rename** (`kagenti` → `rossoctl`) happens first (§12). Then, before any core repo:

**Step 0 — `.github` / org automation.** Rename/update the org's `.github` repo and any automation that gates other repos: reusable workflow refs, the `ALLOWED_REPOS` allowlists and `/run-e2e --build kagenti/<repo>` targets, org-profile README, and workflow display names. **This must go first** — otherwise the moment `agent-examples` becomes `examples`, an allowlist still naming the old repo will reject the pilot's CI for a reason unrelated to its own content.

**Core four — renamed and swept, in this order (a repo renames only after everything it depends on has):**

1. `agent-examples` → `examples` — **pilot.** A leaf: nothing imports it, and its CI derives image names from `github.repository`, so it's the cheapest place to shake out the mechanics.
2. `kagenti-extensions` → `rossocortex` — publishes the AuthBridge library the operator's `token-broker` imports. Before the operator.
3. `kagenti-operator` → `operator` — owns the CRDs and the mutating webhook. Everything downstream reacts to it.
4. `kagenti` → `rossoctl` — the flagship; consumes all three above (charts, images, CRDs). Last, so it lands on already-renamed dependencies.

**Long-tail content sweep (public, active; no name change; no dependency edges — any order):**
`serverless-harness` · `workload-harness` · `ecosystem-guide` · `automation` · `agent-skills` · `openshell-credentials-keycloak`

**`context-guru` — sweep with a dependency edge.** It's a published Go module imported by `rossocortex` (`github.com/kagenti/context-guru`). If we change its module path, do it in the `rossocortex` wave and update the importer in lockstep. If we leave the path for now, say so in the `rossocortex` PR.

### Explicitly out of scope — do not touch

- **Private repos — hands off entirely.** `context-operator`, `kagenti-bundle-service`, `token-broket-service`, `lab-clear`, `lab-data-governance`, `lab-runtime-simulation`. Their owners rename them separately if they choose. `kagenti-bundle-service`'s name carries the brand, but it's private, so it's still out of this effort. *(Open — needs a call: if the team wants private repos included, that's a separate, explicitly-authorized pass.)*
- **Archived repos — hands off entirely.** `plugins-adapter`, `agentic-control-plane`, `adk`, `adk-starter` are archived on GitHub today. No PRs. *(Open — needs a call: `docs/design-proposals/repository-tiers-proposal.md` proposes re-activating some of these. Reconcile that before finalizing scope; if one is un-archived, it joins the sweep then, not now.)*
- **Forks** (`OpenShell`, `openshell-driver-openshift`): upstream owns the name — only touch our references to them, never the fork contents.
- **`pi`**: looks empty — **propose archiving** rather than renaming.
- **`capture-the-flag`**: public and active — light content sweep only (low footprint).

---

## 4. Ground rules

Read these before running anything.

- **Never touch private or archived repos.** This effort covers **public, active** repos only. The exclusions in §3 are hard boundaries — for humans and for Claude Code. Any tool or run must confirm a repo is public and unarchived before making a single change.
- **Rename the GitHub repo first, then open the content PR.** Per repo: rename it on GitHub (the org is already `rossoctl` by now), then branch off the renamed repo and open the PR that updates its contents.
- **One repo, one PR.** No cross-repo PRs. Each rename is independently reviewable, testable, and revertable.
- **Know exactly what redirects cover — and what they don't.**
  - ✅ **Covered:** git clone/remote URLs, GHCR package URLs, and cross-repo web links, *for as long as the old name stays parked (see below)*.
  - ⚠️ **Not covered — Go module paths.** A redirect satisfies `git`, not Go's module-path check. Once a `go.mod` declares `github.com/rossoctl/rossocortex/…`, `go get github.com/kagenti/kagenti-extensions/…` on new commits fails with a path mismatch, and `proxy.golang.org` / `sum.golang.org` entries for the old path are immutable. External importers keep building only against already-cached old versions until they edit their imports. **Treat every path-changing module as a breaking change for downstream importers** (§14).
  - ❌ **Not covered at all:** CRD groups, label selectors, namespaces, the Keycloak realm, SPIFFE trust domains. Those move only when we deliberately migrate them (§5.3, §5.4).
- **Park the old names — do not let them be reclaimed.** The instant we rename the org, the login `kagenti` (and each old repo name) becomes registerable by anyone. A squatter could then serve malicious code or images through the very redirects we rely on. **Immediately after the org rename, register and hold a placeholder org/account named `kagenti`, kept empty and owned by us, past the deprecation window.** Same for old repo names we care about, via holding repos. Owner: GitHub org admin.
- **Never blind-replace a runtime contract.** The bold rows in §2 need the migration steps in §5.3/§5.4, not a `sed`. Flag them, then migrate them.
- **Verify before you merge.** The §9 checklist and §10 tests are the merge gate.
- **Preserve a baseline.** We cut a final `kagenti` alpha release before this starts (issue Phase 1) as our known-good rollback point for source. Note that some steps are *not* revertable this way — see §14.

---

## 5. The rename, category by category

Grouped by risk.

### 5.1 Safe — find/replace + redirects

- **Brand & prose.** READMEs, docs, UI strings, comments, log messages. Docs are by far the largest bucket of references (thousands in the flagship) — and the lowest-risk part.
- **Go modules & imports.** Update `module` in every `go.mod`, all imports, and any `replace` directives (extensions has an internal `replace` pointing at `authlib`). Run `go mod tidy && go build ./...`. The operator's module is *already* `github.com/kagenti/operator`, so only the org segment moves; extensions modules carry the repo name and become `…/rossocortex/…`. Remember the go.mod caveat in §4 for external importers.
- **Python & npm.** Rename the `kagenti/` package dir to `rossoctl/`, update `pyproject.toml` dist names and `[project.scripts]`, fix every `import kagenti…`; `@kagenti/ui` → `@rossoctl/ui`. None of these are published to a public index today, so there's no external install to break — confirm that's still true at rename time.
- **CI / workflows.** Update reusable-workflow refs (`kagenti/.github/...` → `rossoctl/.github/...`), `ALLOWED_REPOS`, `/run-e2e --build kagenti/<repo>` commands, and display names. Workflows that push images via `${{ github.repository }}` auto-follow the rename — leave those alone. **Watch job/check names** — see §6.
- **Cross-repo links.** Update sibling-repo URLs and image refs to the new names even though redirects cover them, so nothing depends on a redirect long-term.

### 5.2 Coordinated — published artifacts

- **Container images.** Everything moves `ghcr.io/kagenti/*` → `ghcr.io/rossoctl/*`. GHCR follows the org rename, and most CI derives the namespace from `github.repository`. The risk is **pinned references** — in sibling manifests, Helm `values.yaml` defaults, and users' deployments. Update every in-repo reference; keep old tags resolving through the deprecation window (don't delete old packages on day one).
- **Image signing & provenance.** *(Open — confirm this applies.)* Our security posture (Scorecard, etc.) suggests images may be keyless-cosign-signed and/or ship SBOM/provenance. Keyless signatures bind to the OIDC identity `https://github.com/kagenti/<repo>/...`; after the rename, new images sign under `rossoctl/...`. **Any consumer whose admission policy pins `--certificate-identity(-regexp)` to the `kagenti` subject will fail verification — a hard deploy break.** If we sign: update the signing workflow identity, publish the new identity regexp, notify pinned consumers *before* cutover, and add signature/attestation verification against the new identity to the §10 gate.
- **Helm charts.** Chart names and OCI publish locations change (`oci://ghcr.io/kagenti/kagenti-operator` → `…/rossoctl/operator`). The flagship's `Chart.yaml` depends on the operator chart by OCI URL — that dependency moves in lockstep with the operator repo's publish step. Chart *release names* (`kagenti-operator`) are baked into existing installs; renaming them means a fresh `helm install`, not an `upgrade`.

### 5.3 Breaking — Kubernetes runtime contracts

These identifiers are contracts between the operator, the UI, and every workload in a cluster. Renaming them is a **cluster migration**, not a code change.

**Affected:** CRD groups `agent.kagenti.dev` (kinds `AgentRuntime`, `AgentCard`, `AuthorizationPolicy`), `mcp.kagenti.com`, plus `kagenti.io` / `openshell.kagenti.io`; the label/annotation domains `kagenti.io/*` and `protocol.kagenti.io/*` (~490 refs in the operator, ~208 of them `kagenti.io/type`, and **end users set these on their own Deployments**); namespaces `kagenti-system`, `kagenti-webhook-system`, `kagenti-traces`.

**Why a grep-replace is wrong:** renaming a CRD group is not a version bump — `agent.rossoctl.dev` is a *different* CRD from `agent.kagenti.dev`, and conversion webhooks convert versions *within* a group, not across groups. Flip `kagenti.io/type` → `rossoctl.io/type` in the operator's selectors and every already-labeled agent silently stops matching.

**Migration approach — Owner: operator team. Runbook drafted before the operator PR.**
1. Ship new-group CRDs (`agent.rossoctl.dev`, …) **alongside** the old ones — don't remove the old group yet.
2. Teach the operator to **read both** label domains during the transition (accept `kagenti.io/*` and `rossoctl.io/*`, write new).
3. Run a **migration job**: read existing CRs under the old group, re-create under the new; re-label existing workloads.
4. Cut the operator's reconcile and the UI's selectors over to the new group + domain.
5. Mark old CRDs/labels **deprecated**, keep them served for an agreed window, then remove in a later release.

### 5.4 Breaking — identity contracts (the least reversible)

A changed trust domain or realm invalidates live credentials, not just code. Give this the same rigor as §5.3.

**Keycloak realm & OAuth client — Owner: assign in review (auth/platform).** Realm `kagenti` and client id/`azp` `kagenti` are embedded in the JWT issuer, JWKS URL, and token-exchange URLs at runtime. **Cutover:** stand up the `rossoctl` realm/client alongside the old one, migrate config, move consumers over, then deprecate the old realm. Don't rename the live realm out from under running tokens.

**SPIFFE trust domain — Owner: assign in review (auth/platform).** `kagenti.local` (and `kagenti.example.com` in examples) is the identity namespace for issued SVIDs. **Changing it invalidates every issued SVID** and every ACL that references it. This is a coordinated SPIRE-server change plus a re-issue — stage the new trust domain, dual-issue where possible, cut over, then retire the old. Not a string edit.

**Env vars.** `KAGENTI_*` (`KAGENTI_NS`, `KAGENTI_REPO`, `KAGENTI_CONFIG_FILE`, …) are the installer's public interface — users set them in shells and CI. (`KAGENTI_DIR` is an *extensions* dev build knob, not part of the installer interface.) Rename to `ROSSOCTL_*`, and for a window have the installer **accept both** — read `ROSSOCTL_*`, fall back to `KAGENTI_*` with a deprecation warning — so no one's pipeline breaks on day one.

Both identity cutovers get a **rehearsal gate** in §10, same as the §5.3 operator migration.

---

## 6. GitHub platform mechanics (what the rename touches beyond code)

Redirects don't cover these; each is a real break mode.

- **Old-name retention** — park `kagenti` and old repo names (see §4). *Blocker.*
- **Branch-protection required checks.** Protection rules match by check/job **name**. Renaming a workflow or job display name orphans the rule: PRs stall forever on "waiting for status," or a required check silently never runs. You also can't merge the PR that renames a check the branch rule still requires. **Prefer keeping job names stable during the rename;** where a name must change, an org/repo admin updates the protection rule in lockstep. Add to the §9 checklist.
- **CODEOWNERS team slugs.** Org rename changes `@kagenti/<team>` → `@rossoctl/<team>`. Stale owners silently stop assigning reviewers and can void "require review from code owners." Update CODEOWNERS in every repo's PR and confirm assignment still fires. (Org rename usually preserves teams — re-validate the slugs.)
- **GitHub Apps & webhooks.** Confirm the DCO app, bots, and any webhook targets/allowlists survive the org rename and still reference the org correctly.
- **Pages / DNS / badges.** If docs or the landing page are served from GitHub Pages, the org rename changes `kagenti.github.io` → `rossoctl.github.io`; a custom domain relies on a repo `CNAME` file + external DNS that GitHub does **not** manage, and Pages custom-domain verification is org-scoped and must be re-established. Refresh README badges and path-keyed services (Scorecard badge, Go Report Card, pkg.go.dev).
- **Dependabot.** Sweep `.github/dependabot.yml` and any GHCR registry/auth config for old-org references. **SHA-pinned actions and reusable workflows are rename-safe** — immutable objects resolve — so their digests need no change.

---

## 7. Beyond GitHub: external & community touchpoints

Everything above lives in Git. The brand also lives in a dozen places Git can't reach — and these behave differently: **most can't be reverted like a PR, some can't be "renamed" at all (you create a new handle and redirect), and each needs a named owner.** Handle these as part of the Phase 3 launch (§12), not per-repo.

Rules of thumb:
- **Rename in place where the platform allows it** (Slack workspace name, YouTube channel name, Medium publication title). The URL/handle often lags the display name — check both.
- **Where a handle is permanent** (Reddit subreddit names, some usernames), stand up the new one, cross-link from the old, and pin a "we've moved" notice. Don't delete the old — it's a redirect and a squatting guard, same logic as §4.
- **Reserve the new names early**, before launch, so no one else takes `rossoctl` on a platform we care about.
- **Swap brand assets in one pass** (logo, avatar, banner, favicon) so we never ship a half-rebranded look.

| Touchpoint | What changes | Rename in place? | Owner |
|---|---|---|---|
| **Slack** | Workspace name, display name, channel names, bot/app names, join/invite URL, `kagenti.slack.com` refs in docs | Name yes; workspace URL may need a new workspace | assign in review |
| **Discord** | Server name, channel names, bot names, invite links, vanity URL | Yes (server rename + new invite/vanity) | assign in review |
| **YouTube** | Channel name & handle (`@kagenti`), banner/avatar, playlist titles, pinned & existing video titles/descriptions linking old URLs | Channel name yes; handle change may break old `@kagenti` links | assign in review |
| **Reddit** | Subreddit (e.g. `r/kagenti`), sidebar, pinned posts | **No** — subreddit names are permanent. Create `r/rossoctl`, cross-link, pin a move notice | assign in review |
| **Medium** | Publication name & URL, author bylines, post canonical links, in-post brand mentions | Publication name yes; custom-domain/URL may change | assign in review |
| **X / Twitter, LinkedIn, Bluesky, Mastodon** | Handle, display name, bio, banner, pinned post | Handle change usually keeps followers but breaks old `@` links | assign in review |
| **Website & docs site** | Landing-page copy, docs site, custom domain + DNS/CNAME, Pages settings, old-URL redirects | Cross-ref §6 (Pages/DNS) | assign in review |
| **Registry & package listings** | Docker Hub / Artifact Hub / PyPI / npm org pages, Homebrew tap, Krew index (if any) | Overlaps §5.2 — coordinate | assign in review |
| **Directory & third-party listings** | CNCF landscape, awesome-lists, integration marketplaces, conference/talk pages, partner pages | Mostly requests/PRs to external maintainers | assign in review |
| **Email & mailing lists** | `*@kagenti.*` addresses, mailing lists, calendar invites, support aliases | Depends on domain ownership | assign in review |
| **Brand assets** | Logos, avatars, banners, favicons, slide templates, social cards | One coordinated swap | assign in review |

> **Open — needs a call:** which of these we actually own today (some may not exist yet), and which new handles to reserve now. Build the real inventory before Phase 3; the table above is the starting checklist, not a claim that all of these exist.

---

## 8. How we execute this with Claude Code

The per-repo mechanical work is driven by Claude Code, using the companion prompt in **`rossoctl-rename-prompt.md`** (same folder). That file is the machine-readable instructions; this playbook is the source of truth it reads from.

The flow is **plan first, then execute** — Claude Code never edits blind:

1. **Point it at one repo** (already renamed on GitHub, public, not archived).
2. **It produces a plan** — an inventory of every `kagenti` reference grouped by category, the exact substitutions, the runtime-contract items it will *not* touch without sign-off, the verification it will run, and the PR it will open. It stops here.
3. **A human confirms the plan** (or edits it). Nothing changes until you approve.
4. **It executes** — applies the safe substitutions, pauses at each runtime-contract item for explicit sign-off, regenerates generated files, and runs the build/test/lint gate.
5. **It verifies and opens the PR** per §9–§11, then reports what passed, what it skipped, and why.

One repo per run, in the §3 order. The dangerous migrations (§5.3, §5.4) are confirmed and driven by their owners — never auto-applied. External touchpoints (§7) are people-work, not Claude Code's job.

---

## 9. Per-repo checklist

Copy into each repo's PR description.

```
Repo: kagenti/<old>  →  rossoctl/<new>

Preflight
- [ ] Repo is PUBLIC and NOT archived (else STOP — out of scope)
- [ ] Open PRs merged or closed (PR freeze)
- [ ] GitHub repo renamed; redirect confirmed; old name parked if it matters
- [ ] Branch created off the renamed repo

Rename
- [ ] Inventory run; DANGER-list occurrences listed in this PR
- [ ] Safe substitutions applied (brand, org, modules, packages, CI, links)
- [ ] Images repointed to ghcr.io/rossoctl/*
- [ ] Helm charts renamed / OCI locations updated
- [ ] Runtime-contract migration plan linked, or explicitly N/A for this repo
- [ ] CODEOWNERS @kagenti/* → @rossoctl/* updated; review assignment verified
- [ ] Branch-protection required-check names updated (or names kept stable)
- [ ] Generated files regenerated (not hand-edited)
- [ ] Cross-repo references updated to new names

Verify (see §10)
- [ ] Build passes
- [ ] Unit tests pass
- [ ] Lint / format clean
- [ ] Chart/manifest validation passes (helm unittest, kubeconform)
- [ ] E2E passes (or explicitly deferred with reason)
- [ ] Image signatures/attestations verify under the new identity (if signed)
- [ ] Links checked; no dead kagenti/* links except intentional redirects
- [ ] Grep clean: no stray "kagenti" except deliberately-retained contracts

Ship
- [ ] Commits signed off (DCO, -s)
- [ ] PR title uses the emoji convention (§11)
- [ ] "Related to #1972" in the body
- [ ] CI green
- [ ] Merged
- [ ] Release artifacts / distribution channels re-published (if this repo ships them)
```

---

## 10. Verification & testing

A repo doesn't merge until it passes the gate. Match depth to the repo.

**Every repo:**
- **Build.** `go build ./...` / `uv build` / `npm run build` — must compile under the new names.
- **Unit tests.** Full suite. Watch for fixtures hardcoding old strings (`realms/kagenti`, `kagenti-system`, self-import paths — there are many).
- **Lint & format.** Flagship runs `ruff` + `pre-commit` (gitleaks, commit-msg trailer hook); Go repos run `go vet`. Reproduce locally with `uv run pre-commit run --all-files` where it applies.
- **Grep sweep.** `grep -rIn -i kagenti .` returns only the identifiers we *deliberately* kept (documented in the PR). Anything else is a miss.
- **Link check.** No broken `github.com/kagenti/*` links except intentional redirects.

**Repos with charts/manifests (flagship, operator, rossocortex):**
- `helm unittest` + `kubeconform`; render charts and confirm image refs, namespaces, and labels resolve to the intended values.

**Cluster-touching repos (operator, rossocortex, flagship):**
- **E2E on a kind cluster.** Stand up the renamed stack end to end: operator reconciles, webhook injects, an example agent comes up, the UI discovers it, auth works.
- **Migration rehearsal — the real gate for the dangerous part.** Before merging the operator PR, rehearse §5.3 on a cluster seeded with *old*-group resources: install new CRDs alongside, run the migration job, cut over, confirm existing workloads still reconcile. Do the same for §5.4 — bring up the new Keycloak realm and SPIFFE trust domain, cut a consumer over, confirm tokens/SVIDs validate. Capture both runbooks in the PR.

**Pilot scope — be honest about what it proves.** `examples` validates the **rename mechanics, CI wiring, and safe substitutions** on the cheapest repo. Its `kagenti.io` labels and SPIFFE/Keycloak strings are *sample config*, not live contracts — so the pilot does **not** exercise the §5.3/§5.4 migration. That's first proven on the operator via the rehearsal gate above. The pilot has to go fully green before we touch the operator or flagship.

---

## 11. The PR workflow

Standard for every rename PR, including the one that adds *this* document.

- **Branch** off the renamed repo. No enforced naming; use something legible like `rename/kagenti-to-rossoctl` or `docs/rossoctl-rename-playbook`.
- **Sign off every commit** — DCO is mandatory, enforced by the `DCO` check on every PR:
  ```
  git commit -s -m "📖 <message>"
  ```
  `-s` adds the `Signed-off-by` trailer. If you have commit signing configured, add `-S` too — welcome, but **not** required (CI enforces DCO, not GPG). Fix a branch after the fact with `git rebase --signoff main`.
- **PR title** uses the emoji type prefix: `✨` feature · `🐛` fix · `📖` docs · `📝` proposal · `⚠️` breaking change · `🌱` other/misc (tests, tooling, CI, refactor) · `❓` needs review. A PR that changes runtime contracts is `⚠️`; a docs/content sweep is `📖`. This doc's PR is `📝`.
- **PR body:** a `## Summary` with key changes, and `## Related issue(s)` with `Related to #1972`. Don't `Fixes #1972` — the rename spans many PRs; the issue closes at the end.
- **AI attribution:** include `Co-authored-by:` if applicable — a pre-commit hook rewrites AI co-author trailers to `Assisted-By`. Don't add the "Generated with" line; the hook strips it.
- **Merge** only when CI is green: lint, tests, chart tests, DCO, PR-title verifier, and the security suite (CodeQL, Trivy, Bandit, Scorecard, …).

---

## 12. Rollout sequence

Steps only — open decisions and blockers live in §14, owners in §13.

```
Phase 1 — Prepare
  • PR freeze: merge/close everything in flight
  • Cut the final `kagenti` alpha release (rollback baseline)
  • Reserve new external handles (Slack/Discord/YouTube/Reddit/social) — §7
  • Land this playbook; validate it on the pilot (examples)

Phase 2 — Execute
  • Rename the GitHub org: kagenti → rossoctl; verify redirects
  • Park the old `kagenti` org name (and old repo names) — hold, don't release
  • Update `.github` / org automation FIRST (allowlists, reusable workflows, teams)
  • Then, one repo at a time in dependency order:
       1. agent-examples    → examples      (pilot)
       2. kagenti-extensions → rossocortex
       3. kagenti-operator  → operator       (+ §5.3 CRD/label migration)
       4. kagenti           → rossoctl        (+ §5.4 identity cutover)
     For each: rename repo → Claude Code plan+execute (§8) → §9 checklist →
               §10 tests → merge → re-publish artifacts
  • Long-tail content sweep of the remaining public active repos (§3)

Phase 3 — Launch
  • Publish the Rossoctl landing page (handle Pages/DNS/CNAME cutover — §6)
  • Rename external & community touchpoints (§7); publish MIGRATION.md (§14)
  • Keep docs gated until v0.7 docs are ready (target Jul 31)
  • Announce across community channels; update external references we control

Phase 4 — Retire (after the deprecation window)
  • Remove old CRDs, labels, image tags, env-var fallbacks, old realm/trust domain
  • Keep the parked `kagenti` name held — do NOT release it
```

---

## 13. Ownership

Rename efforts stall when steps are unowned. Fill these in during review; flagged privileges matter.

| Step | Owner | Privilege |
|---|---|---|
| Org rename `kagenti → rossoctl` | assign in review | GitHub **org owner** |
| Park old org + repo names | assign in review | GitHub org owner |
| `.github` / org-automation update | assign in review | repo maintainer |
| Branch protection + CODEOWNERS updates | assign in review | repo/org admin |
| Per-repo rename + content PR | per-repo owner | repo maintainer |
| Operator CRD/label migration (§5.3) | **operator team** | cluster admin |
| Keycloak realm + SPIFFE cutover (§5.4) | assign in review (auth/platform) | cluster + IdP admin |
| Image signing identity (§5.2) | assign in review | CI/release owner |
| Release + distribution channels | assign in review | release owner |
| DNS / Pages / landing page | assign in review | infra/web owner |
| External & community touchpoints (§7) | assign in review | DevRel/community |
| Downstream comms + MIGRATION.md | assign in review | DevRel/maintainers |
| Retire old names/tags (Phase 4) | assign in review | org owner |

---

## 14. Risks & open decisions

Bring these to review. Bolded ones block work.

- **⚠️ Full cutover is the recommended default, pending sign-off.** We propose renaming the runtime contracts too (CRD groups, labels, namespaces, Keycloak realm, SPIFFE) — the most complete outcome, and the highest risk. This is a *scope* choice, independent of the incremental *timing* (still one repo at a time). Mitigation is the dual-serve → migrate → deprecate approach in §5.3/§5.4, which **needs owners and rehearsed runbooks before the operator PR.** If review judges the migration cost too high now, the fallback is to keep the bold rows stable this pass and schedule them as a later coordinated release.
- **Rollback is not symmetric.** Source changes revert via the baseline release and per-PR reverts. **These do not:** the org/repo rename (redirects + parked names), a live CRD-group + label migration once the job has run, a SPIFFE re-issue, a Keycloak realm cutover. Write a per-repo back-out runbook for the breaking repos, mark the point-of-no-return checkpoints explicitly, and gate them behind a go/no-go.
- **Downstream migration guide.** Ship a `MIGRATION.md` for external users: one table of *old identifier → new identifier → action → deadline*, covering CRDs/labels/namespaces, the Keycloak realm, the SPIFFE trust domain, image namespace, and `KAGENTI_* → ROSSOCTL_*`. Reference it in the announcement, tied to the deprecation-window date.
- **Open — domain ownership.** CRD groups/label domains need `rossoctl.dev` / `.io` / `.com`. Confirm before renaming any group (blocks §5.3).
- **Open — Red Hat stability commitments** (issue Phase 1). Which repos/APIs/packages must stay stable, and for how long? Answers can pull specific rows out of the cutover set.
- **Open — image signing.** Confirm whether images are cosign-signed / ship attestations (§5.2); if so, the consumer-notification and re-verification steps become mandatory.
- **Open — deprecation window.** How long we keep old image tags, `KAGENTI_*` fallbacks, old CRDs, and the old realm alive. Pick a date; it drives Phase 4.
- **Open — repository tiers.** Reconcile scope with `docs/design-proposals/repository-tiers-proposal.md`, which may re-activate some currently-archived repos.
- **Open — private repos.** `kagenti-bundle-service` and other private repos are out of scope by rule (§3/§4). Decide separately whether/when their owners rename them.

---

## 15. Appendix — the footprint (from the repo audit)

Sizing so reviewers know the size of each job. Counts are case-insensitive "kagenti" occurrences at audit time.

| Repo | ~refs | The parts that hurt |
|---|---|---|
| `kagenti` → `rossoctl` | ~7,700 | 4 CRD groups, ~30 `kagenti.io/*` label keys, `kagenti-system` / `-webhook-system`, Keycloak realm, `@kagenti/ui`, `io.kagenti.keycloak` Java SPI, `KAGENTI_*` installer env, 10+ image repos |
| `kagenti-operator` → `operator` | ~1,927 (558 in tests) | `agent.kagenti.dev` group (~141), `kagenti.io/*` (~490, incl. `kagenti.io/type` ×208), `kagenti-traces`, module `github.com/kagenti/operator`, imports `kagenti-extensions/authbridge/authlib` |
| `kagenti-extensions` → `rossocortex` | ~1,427 | 7 Go modules + internal `replace`, `agent.kagenti.dev` consumer, `kagenti.io/*` labels, Keycloak realm `kagenti`, SPIFFE `kagenti.local`, dist/console-script `kagenti-sparc-service`, imports `github.com/kagenti/context-guru` |
| `agent-examples` → `examples` | ~253 | `kagenti.io/*` discovery labels, SPIFFE `kagenti.example.com`, Keycloak realm/client `kagenti`, module `github.com/kagenti/mcp-mitm`, `@kagenti` CODEOWNERS teams |

Long-tail sweep (content only, no name change): `ecosystem-guide` (~145) · `automation` (~139) · `agent-skills` (~115) · `serverless-harness` (~79) · `context-guru` (~58, + module path — §3) · `openshell-credentials-keycloak` (~36) · `workload-harness` (~19) · `capture-the-flag` (~11).

---

*Delete this file once the rename lands and #1972 closes.*
