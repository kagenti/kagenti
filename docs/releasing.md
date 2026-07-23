---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Releasing Rossoctl

Practical guide for release managers. Covers the full lifecycle from alpha
through GA, including the stabilization loop between RCs.

> **AI-assisted:** Use `/release` in Claude Code for interactive guidance
> through any step below. See [Using the Release Skill](#using-the-release-skill).

## Versioning Scheme

Rossoctl follows [Semantic Versioning 2.0](https://semver.org/) with three
pre-release stages:

```
vX.Y.0-alpha.N   →   vX.Y.0-rc.N   →   vX.Y.0   →   vX.Y.Z (patches)
```

| Tag pattern | Stage | GitHub Release type |
|-------------|-------|---------------------|
| `vX.Y.0-alpha.N` | **Alpha** — active development, may break | Pre-release |
| `vX.Y.0-rc.N` | **Release Candidate** — feature-complete, stabilization only | Pre-release |
| `vX.Y.0` | **General Availability (GA)** — stable, production-ready | Latest |
| `vX.Y.Z` | **Patch** — critical fixes against a GA release | Latest |

GoReleaser's `prerelease: auto` setting automatically marks tags containing
`-alpha` or `-rc` as pre-releases on GitHub. No manual intervention is needed.

## Release Governance

Any Rossoctl maintainer (member of the
[rossoctl-maintainers](mailto:rossoctl-maintainers@googlegroups.com) team) can
cut a release. For GA releases, at least one other maintainer must sign off
before tagging.

## Version Compatibility

Each `rossoctl/rossoctl` release tag represents a tested set of component versions
across the organization. The Helm chart (`charts/rossoctl/Chart.yaml`) pins the
exact sub-chart versions, and `charts/rossoctl/values.yaml` pins the container
image tags.

GA release notes should include a compatibility table:

```markdown
## Component Versions

| Component | Version |
|-----------|---------|
| rossoctl (platform) | v0.6.0 |
| cortex (webhook) | v0.5.0 |
| rossoctl-operator | v0.3.0 |
| agent-examples | v0.2.0 |
```

Users who install via Helm charts do not need to manage
version compatibility manually — checking out a Rossoctl release tag gives a
consistent, tested set of components.

## Repositories and Artifacts

The Rossoctl platform spans multiple repositories. Each produces different
artifacts when a tag is pushed:

| Repository | Artifacts on tag push | CI workflow(s) |
|------------|----------------------|----------------|
| [rossoctl/rossoctl](https://github.com/rossoctl/rossoctl) | Container images (ui-v2, backend, oauth-secrets), Helm charts (rossoctl, rossoctl-deps) | `build.yaml` |
| [rossoctl/cortex](https://github.com/rossoctl/cortex) | Container images (envoy-with-processor, proxy-init, client-registration), webhook binary + ko image, Helm chart (cortex-webhook-chart) | `build.yaml`, `goreleaser.yml` |
| [rossoctl/operator](https://github.com/rossoctl/operator) | Operator image, Helm chart (operator-chart) | repo-specific |
| [rossoctl/examples](https://github.com/rossoctl/examples) | Sample agent/tool images | repo-specific |

## Release Order

The `rossoctl/rossoctl` Helm chart depends on sub-charts from other repos
(defined in `charts/rossoctl/Chart.yaml`). Dependency repos must be tagged
**before** the main repo:

```
1. rossoctl/operator     →  tag & wait for CI
2. rossoctl/cortex   →  tag & wait for CI
3. rossoctl/examples       →  tag (if applicable)
4. rossoctl/rossoctl              →  update Chart.yaml, tag
```

## Cutting an Alpha Release

Alpha releases are tagged from `main` during active development.

### Steps (repeat for each repo)

1. Ensure CI passes on `main`.

2. Determine the next alpha number:

   ```bash
   git tag --list 'vX.Y.0-alpha.*' --sort=-v:refname | head -1
   ```

3. Create and push the tag:

   ```bash
   git tag -s vX.Y.0-alpha.N -m "vX.Y.0-alpha.N"
   git push origin vX.Y.0-alpha.N
   ```

4. Verify CI completes:
   - [ ] Container images pushed to `ghcr.io`
   - [ ] GitHub Release created and marked as **Pre-release**
   - [ ] Helm charts published (if applicable)

5. Release notes are auto-generated from the changelog. If there are known
   breaking changes or significant issues since the previous alpha, add a brief
   note to the GitHub Release body (even for alphas, this helps early testers).

### Updating rossoctl/rossoctl after dependency alphas

After tagging `cortex` and `rossoctl-operator`, update the sub-chart
versions in `charts/rossoctl/Chart.yaml`:

```yaml
dependencies:
- name: cortex-webhook-chart
  version: X.Y.0-alpha.N    # <-- new version
  repository: oci://ghcr.io/rossoctl/cortex
- name: operator-chart
  version: X.Y.0-alpha.N    # <-- new version
  repository: oci://ghcr.io/rossoctl/operator
```

Run `helm dependency update charts/rossoctl/` to regenerate `Chart.lock`, commit,
merge, then tag `rossoctl/rossoctl`.

## Pinning Image Tags Before Release

The `charts/rossoctl/values.yaml` file references internal container images.
Some of these currently use `tag: latest`, which must be pinned to the release
version before cutting an RC or GA tag.

### Images that require pinning

Check `charts/rossoctl/values.yaml` for any `tag: latest` entries. As of v0.5.0,
these include:

| Image | values.yaml key | Purpose |
|-------|----------------|---------|
| `ghcr.io/rossoctl/rossoctl/ui-oauth-secret` | `uiOAuthSecret.tag` | UI Keycloak client registration |
| `ghcr.io/rossoctl/rossoctl/agent-oauth-secret` | `agentOAuthSecret.tag` | Agent Keycloak client registration |
| `ghcr.io/rossoctl/rossoctl/api-oauth-secret` | `apiOAuthSecret.tag` | API Keycloak client registration |
| `ghcr.io/rossoctl/rossoctl/phoenix-oauth-secret` | `phoenixOAuthSecret.tag` | Phoenix observability auth |
| `quay.io/ladas/mlflow-oauth-secret` | `mlflowOAuthSecret.tag` | MLflow auth (move to `ghcr.io/rossoctl/rossoctl/mlflow-oauth-secret` once published) |

Additionally, some Helm templates hardcode `:latest` for utility images
(`bitnami/kubectl:latest`, `ose-cli:latest`). These should be pinned to
specific versions over time.

### What to do

Before tagging an RC or GA release, update `charts/rossoctl/values.yaml`:

```yaml
uiOAuthSecret:
  image: ghcr.io/rossoctl/rossoctl/ui-oauth-secret
  tag: vX.Y.0       # <-- pin to release tag, not "latest"

agentOAuthSecret:
  image: ghcr.io/rossoctl/rossoctl/agent-oauth-secret
  tag: vX.Y.0       # <-- pin to release tag

# ... repeat for all oauth-secret images
```

The `ui.tag` and `backend.tag` fields are already pinned to specific versions
(e.g., `v0.5.0-alpha.11`). Ensure these are also updated to the release tag.

**Why this matters:** Using `latest` means different installs at different times
get different image versions, making it impossible to reproduce issues or
guarantee a tested set of components. Every image referenced in `values.yaml`
should resolve to a specific, immutable tag for any RC or GA release.

## Cutting a Release Candidate

Release candidates signal feature-complete code ready for broader testing.

### Prerequisites

- All planned features for `vX.Y.0` are merged.
- No known critical or blocking bugs.
- Feature freeze declared by maintainers.

### Steps

1. **Tag dependency repos first** with their RC tags (following the
   [release order](#release-order)).

2. **Update `charts/rossoctl/Chart.yaml`** in `rossoctl/rossoctl` to reference
   the new sub-chart RC versions. Run `helm dependency update charts/rossoctl/`
   to regenerate `Chart.lock`.

3. **Pin all image tags** in `charts/rossoctl/values.yaml` to the RC tag.
   Replace any `tag: latest` entries with the RC version (see
   [Pinning Image Tags Before Release](#pinning-image-tags-before-release)).

4. **Create a release branch** for stabilization:

   ```bash
   git checkout -b release-X.Y main
   git push origin release-X.Y
   ```

   Release branches are the target for cherry-picks and patch releases. If no
   parallel work is planned, you may tag directly from `main`, but the release
   branch will still be needed for any future patches.

5. **Tag the RC:**

   ```bash
   git tag -s vX.Y.0-rc.1 -m "vX.Y.0-rc.1"
   git push origin vX.Y.0-rc.1
   ```

6. **Verify all artifacts:**
   - [ ] Container images pushed with the RC tag
   - [ ] Helm charts pushed to OCI registry
   - [ ] GitHub Release created as **Pre-release**
   - [ ] No `tag: latest` remains in `charts/rossoctl/values.yaml`

7. **Run RC validation CI** (see
   [Validating an RC with CI](#validating-an-rc-with-ci) below):

   ```bash
   gh workflow run release-validation.yaml -f ref=vX.Y.0-rc.N
   ```

   This runs Kind and HyperShift E2E tests in parallel. Both must pass.

   - [ ] RC Validation workflow passes (Kind + HyperShift)
   - [ ] Upgrade from previous GA version works (manual)
   - [ ] Documentation reviewed and updated for new features

8. **If bugs are found:** Fix on the release branch (or `main`), cherry-pick as
   needed, bump to `rc.2`, and repeat from step 5.

## Cutting a GA Release

A GA release is the final, stable, production-ready version.

### Prerequisites

- At least one RC has been validated with no open release-blocking issues.
- Minimum soak period of 1 week since the last RC (recommended).
- At least one maintainer sign-off.

### Steps

1. **Tag dependency repos first** with their GA tags (following the
   [release order](#release-order)).

2. **Update `charts/rossoctl/Chart.yaml`** to pin sub-chart versions to their
   GA versions. Run `helm dependency update charts/rossoctl/` to regenerate
   `Chart.lock`.

3. **Pin all image tags** in `charts/rossoctl/values.yaml` to the GA tag.
   Verify no `tag: latest` entries remain (see
   [Pinning Image Tags Before Release](#pinning-image-tags-before-release)).

4. **Tag the GA release:**

   ```bash
   git tag -s vX.Y.0 -m "vX.Y.0"
   git push origin vX.Y.0
   ```

5. **Write release notes** using the following template:

   ```markdown
   ## Highlights
   - <key feature or improvement>
   - <key feature or improvement>

   ## Breaking Changes
   - <any breaking changes, or "None">

   ## Component Versions

   | Component | Version |
   |-----------|---------|
   | rossoctl (platform) | vX.Y.0 |
   | cortex (webhook) | vA.B.0 |
   | rossoctl-operator | vC.D.0 |
   | agent-examples | vE.F.0 |

   ## Upgrade Notes
   - <any special steps for upgrading from the previous GA>

   ## Full Changelog
   <auto-generated by GitHub>
   ```

   Use GitHub's auto-generated changelog as the base and prepend the sections
   above.

6. **Verify:**
   - [ ] GitHub Release is marked as **Latest** (not Pre-release)
   - [ ] All container images tagged and pushed
   - [ ] Helm charts published to OCI registry
   - [ ] No `tag: latest` remains in `charts/rossoctl/values.yaml`
   - [ ] Installation guide version references are up to date

7. **Announce** the release:
   - [Slack](https://ibm.biz/rossoctl-slack)
   - [Mailing list](mailto:rossoctl-maintainers@googlegroups.com)
   - Consider a blog post for major releases

## Cutting a Patch Release

Patch releases deliver critical fixes against an existing GA version.

1. Cherry-pick the fix(es) into the `release-X.Y` branch.
2. Tag as `vX.Y.Z` (e.g., `v0.5.1`).
3. Follow the same verification steps as a GA release.
4. For non-trivial fixes, consider cutting a patch RC (`vX.Y.Z-rc.1`) first.

## Validating an RC with CI

The `release-validation.yaml` workflow runs the full E2E test suite on both Kind
and HyperShift clusters in parallel. Use it to validate an RC before promoting
to GA.

### Running the validation

```bash
# Validate an RC tag (most common usage)
gh workflow run release-validation.yaml -f ref=v0.6.0-rc.9

# Validate with a specific extensions dependency
gh workflow run release-validation.yaml -f ref=v0.6.0-rc.9 \
  -f dep_builds='[{"repo":"rossoctl/cortex","ref":"v0.6.0-rc.1"}]'

# Quick iteration: HyperShift only, keep cluster alive for debugging
gh workflow run release-validation.yaml -f ref=v0.6.0-rc.9 \
  -f skip_kind=true -f skip_destroy=true

# Kind only (faster feedback, no AWS resources consumed)
gh workflow run release-validation.yaml -f ref=v0.6.0-rc.9 \
  -f skip_hypershift=true
```

### Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `ref` | Yes | — | Git ref to validate (tag, branch, or SHA) |
| `ocp_version` | No | `4.20.21` | OpenShift version for HyperShift cluster |
| `skip_kind` | No | `false` | Skip Kind E2E tests |
| `skip_hypershift` | No | `false` | Skip HyperShift E2E tests |
| `skip_destroy` | No | `false` | Keep HyperShift cluster alive after tests |
| `dep_builds` | No | `[]` | JSON array of dependency builds to test with |

### What it runs

| Platform | Tests included | Duration |
|----------|---------------|----------|
| Kind (K8s 1.35.0) | Backend E2E, token exchange, UI E2E | ~90 min |
| HyperShift (OCP) | Backend E2E, token exchange (community + RHBK), UI E2E, Trivy scan | ~120 min |

Both platforms run in parallel. The workflow reports a combined pass/fail — both
must succeed for the RC to be considered validated.

### Checking results

```bash
# Watch the run
gh run watch

# Check the summary after completion
gh run view <run-id>
```

The workflow produces a step summary with a clear go/no-go verdict. Test
artifacts (Playwright reports, E2E results) are uploaded and retained for 30
days.

### When to run

- After tagging every RC (mandatory for GA promotion)
- After cherry-picking a fix to the release branch
- Before signing off on a GA release

## Troubleshooting

### Stale `Chart.lock`

After updating dependency versions in `Chart.yaml`, always run
`helm dependency update` before committing:

```bash
helm dependency update charts/rossoctl/
helm dependency update charts/rossoctl-deps/
```

Forgetting this step causes Helm install failures because `Chart.lock` still
references the old versions.

### Pre-release detection

GoReleaser's `prerelease: auto` detects pre-release tags by the presence of a
hyphen after the version (e.g., `-alpha.1`, `-rc.2`). Tags like `v0.5.0` are
treated as stable. No workflow changes are needed to support new pre-release
stages.

### Helm chart version vs. app version

The `version` field in `Chart.yaml` should match the release tag (minus the `v`
prefix). The `appVersion` field may differ if it tracks a different cadence.

### `tag: latest` in values.yaml

If a GA release ships with `tag: latest` in `values.yaml`, users installing at
different times will get different image versions, making issues unreproducible.
Search for remaining `latest` references:

```bash
grep -n 'tag: latest' charts/rossoctl/values.yaml
grep -rn ':latest' charts/rossoctl/templates/
```

Fix any found before tagging.

## Using the Release Skill

The `.claude/skills/release/SKILL.md` skill (see [PR #1021](https://github.com/rossoctl/rossoctl/pull/1021))
provides an interactive, AI-assisted workflow that automates the steps in this
guide. It handles multi-repo coordination, artifact verification, and release
notes generation.

### Quick examples

**Check the current release state across all repos:**

```
/release status
```

This shows the latest tags for each repo, the current `Chart.yaml` dependency
versions, and flags any `tag: latest` entries in `values.yaml` that need
pinning.

**Cut an alpha release:**

```
/release alpha v0.6.0-alpha.1
```

The skill will:
1. Check CI status on `main` for each repo
2. Guide you through tagging dependency repos first (operator, extensions)
3. Prompt you to update `Chart.yaml` and tag `rossoctl/rossoctl` last
4. Verify all GitHub Releases and container images were produced

**Cut a release candidate:**

```
/release rc v0.6.0-rc.1
```

In addition to the alpha steps, the skill will:
1. Verify feature freeze prerequisites
2. Help pin all `tag: latest` entries in `values.yaml`
3. Create the `release-0.6` branch
4. Run the full verification suite (images, Helm charts, pre-release flags)
5. Generate an RC release notes template with a testing checklist

**Cut a GA release:**

```
/release ga v0.6.0
```

The skill will:
1. Verify an RC was validated and a maintainer has signed off
2. Pin all image and chart versions to GA tags
3. Tag all repos in order and verify artifacts
4. Generate full release notes with a component compatibility table
5. Draft an announcement for Slack and the mailing list

**Cut a patch release:**

```
/release patch v0.5.1
```

The skill guides cherry-picking fixes into the `release-0.5` branch and follows
the same verification and release notes flow.

---

## Overview

```
vX.Y.0-alpha.N   →   vX.Y.0-rc.1   →   rc.2 → ... → rc.N   →   vX.Y.0   →   vX.Y.Z
     (main)            (release-X.Y created)                       (GA)        (patch)
```

| Stage | Branch | Image tags pinned? | GitHub Release |
|-------|--------|-------------------|----------------|
| Alpha | `main` | Yes | Pre-release |
| RC | `release-X.Y` | Yes | Pre-release |
| GA | `release-X.Y` | Yes | Latest |
| Patch | `release-X.Y` | Yes | Latest |

### Repos and dependency order

Tag repos in this order. Wait for CI between each:

```
1. rossoctl/operator     →  tag, wait for CI + images
2. rossoctl/cortex   →  tag, wait for CI + images
3. rossoctl/examples       →  tag (if applicable)
4. rossoctl/rossoctl              →  update Chart.yaml + values.yaml, tag
```

### Governance

- Any maintainer can cut alpha/RC releases
- GA requires sign-off from at least one other maintainer
- Mailing list: `rossoctl-maintainers@googlegroups.com`

---

## Rules

1. **`main` is always releasable.** Broken builds are P0.
2. **Release branches are created at RC1 time**, not before.
3. **No direct commits to release branches.** Fixes land on `main` first,
   then cherry-pick with `-x`.
4. **Pin all image tags** before any release — no `tag: latest` ever.
5. **One release branch per minor** — `release-0.6` covers rc.1 through all
   v0.6.Z patches.

---

## The Release Lifecycle

### 1. Alpha (from `main`)

```bash
# 1. Verify CI passes on main for each repo
gh run list --branch main --limit 3 --repo rossoctl/<repo>

# 2. Pin images
bash scripts/pin-release-tags.sh v0.7.0-alpha.1
bash scripts/check-release-pins.sh

# 3. Tag dependency repos in order (operator → extensions → examples)
git tag -s v0.3.0-alpha.1 -m "v0.3.0-alpha.1"
git push origin v0.3.0-alpha.1

# 4. Update Chart.yaml + helm dependency update, commit, tag rossoctl/rossoctl
git tag -s v0.7.0-alpha.1 -m "v0.7.0-alpha.1"
git push origin v0.7.0-alpha.1
```

### 2. First RC (creates release branches)

Prerequisites:
- All planned features merged to `main`
- No open P0/P1 bugs
- Feature freeze declared

```bash
# 1. Create release branches in ALL repos (dependency order)
# For each repo:
git checkout -b release-X.Y main
git push origin release-X.Y
git tag -s vA.B.0-rc.1 -m "vA.B.0-rc.1"
git push origin vA.B.0-rc.1

# 2. In rossoctl/rossoctl: update Chart.yaml with RC sub-chart versions
# 3. Pin image tags
bash scripts/pin-release-tags.sh v0.6.0-rc.1
bash scripts/check-release-pins.sh

# 4. Create release branch and tag
git checkout -b release-0.6 main
git push upstream release-0.6
git tag -s v0.6.0-rc.1 -m "v0.6.0-rc.1"
git push upstream v0.6.0-rc.1
```

### 3. Stabilization Loop (between RCs)

This is where most release work happens. Repeat until stable:

```
Test RC → find bugs → fix on main (PRs) → cherry-pick to release branch → tag next RC
```

#### 3a. Find candidate fixes

```bash
# PRs merged to main since last RC
LAST_RC_DATE=$(gh release view v0.6.0-rc.6 --repo rossoctl/rossoctl --json publishedAt --jq '.publishedAt')

gh pr list --repo rossoctl/rossoctl --state merged --base main \
  --search "merged:>$LAST_RC_DATE" --json number,title,mergeCommit \
  --jq '.[] | "#\(.number) \(.title) [\(.mergeCommit.oid[:12])]"'

# Check dependency repos too
gh pr list --repo rossoctl/cortex --state merged --base main \
  --search "merged:>$LAST_RC_DATE" --json number,title,mergeCommit \
  --jq '.[] | "#\(.number) \(.title) [\(.mergeCommit.oid[:12])]"'
```

#### 3b. Cherry-pick to release branch

```bash
# Sync local release branch
git fetch upstream release-0.6
git checkout release-0.6 2>/dev/null || git checkout -b release-0.6 upstream/release-0.6
git reset --hard upstream/release-0.6

# Cherry-pick with -x (MANDATORY for traceability)
git cherry-pick -x <sha1>
git cherry-pick -x <sha2>

# Push to upstream
git push upstream release-0.6
```

If dependency repos have fixes, cherry-pick and tag those first (dependency
order), then update `Chart.yaml` in the rossoctl release branch.

#### 3c. Tag next RC

```bash
# Pin images for the new RC
bash scripts/pin-release-tags.sh v0.6.0-rc.7
bash scripts/check-release-pins.sh
git add charts/
git commit -s -m "chore(release): pin image tags for v0.6.0-rc.7"
git push upstream release-0.6

# Tag
git tag -s v0.6.0-rc.7 -m "v0.6.0-rc.7"
git push upstream v0.6.0-rc.7
```

→ Verify artifacts, then repeat from 3a if more issues are found.

### 4. GA Release

Prerequisites:
- At least 1 RC validated with no blocking issues
- Minimum 1-week soak since last RC (recommended)
- Maintainer sign-off from someone other than the tagger

```bash
# 1. Tag dependency repos with GA (in order)
git tag -s vA.B.0 -m "vA.B.0"
git push origin vA.B.0

# 2. Update Chart.yaml with GA sub-chart versions
# 3. Pin images to GA tag
bash scripts/pin-release-tags.sh v0.6.0
bash scripts/check-release-pins.sh
git commit -s -m "chore(release): pin image tags for v0.6.0"
git push upstream release-0.6

# 4. Tag
git tag -s v0.6.0 -m "v0.6.0"
git push upstream v0.6.0

# 5. Mark as latest
gh release edit v0.6.0 --repo rossoctl/rossoctl --latest
```

### 5. Patch Release

Same as the stabilization loop, but against an existing GA:

```bash
# Fix lands on main first, then:
git checkout release-0.6
git cherry-pick -x <sha>
git push upstream release-0.6

# Pin and tag
bash scripts/pin-release-tags.sh v0.6.1
git tag -s v0.6.1 -m "v0.6.1"
git push upstream v0.6.1
```

For non-trivial patches, consider a patch RC (`v0.6.1-rc.1`) first.

---

## Release Branch Git Workflow

### Approach A: Direct push (maintainers with write access)

```bash
git fetch upstream release-X.Y
git checkout release-X.Y 2>/dev/null || git checkout -b release-X.Y upstream/release-X.Y
git reset --hard upstream/release-X.Y
git cherry-pick -x <sha>
git push upstream release-X.Y
```

### Approach B: PR to release branch

```bash
git fetch upstream release-X.Y
git checkout -b cherry-pick-<desc> upstream/release-X.Y
git cherry-pick -x <sha>
git push origin cherry-pick-<desc>
gh pr create --base release-X.Y --repo rossoctl/rossoctl \
  --title "fix: cherry-pick <description> for rc.N"
```

### When to use which

| Scenario | Use |
|----------|-----|
| Clean cherry-picks, you have push access | A (direct) |
| Conflicts needing review | B (PR) |
| No upstream write access | B (PR) |
| Large/risky backport | B (PR) |

---

## Image Tag Pinning

Both charts (`charts/rossoctl/` and `charts/rossoctl-deps/`) must have all
image tags pinned before any release.

```bash
# Pin all images to target version
bash scripts/pin-release-tags.sh <version>

# Preview without modifying
bash scripts/pin-release-tags.sh <version> --dry-run

# Verify images exist in ghcr.io
bash scripts/pin-release-tags.sh <version> --verify-images

# Validate (must pass before tagging)
bash scripts/check-release-pins.sh
```

Images pinned by the script:

| Chart | Image | Key |
|-------|-------|-----|
| rossoctl | ui-v2 | `ui.frontend.tag` |
| rossoctl | backend | `ui.backend.tag` |
| rossoctl | ui-oauth-secret | `uiOAuthSecret.tag` |
| rossoctl | agent-oauth-secret | `agentOAuthSecret.tag` |
| rossoctl | api-oauth-secret | `apiOAuthSecret.tag` |
| rossoctl | mlflow-oauth-secret | `mlflowOAuthSecret.tag` |
| rossoctl-deps | spiffe-idp-setup | `spiffeIdp.image.tag` |

---

## Verification

After every tag, verify:

```bash
# GitHub Releases
gh release view <version> --repo rossoctl/rossoctl

# Container images
for img in ui-v2 backend ui-oauth-secret agent-oauth-secret api-oauth-secret; do
  docker manifest inspect ghcr.io/rossoctl/rossoctl/$img:<version> >/dev/null 2>&1 \
    && echo "$img OK" || echo "$img MISSING"
done

# Helm charts
helm show chart oci://ghcr.io/rossoctl/cortex/cortex-webhook-chart --version <version>
helm show chart oci://ghcr.io/rossoctl/operator/operator-chart --version <version>

# Pre-release flag (should be true for alpha/RC, false for GA)
gh release view <version> --repo rossoctl/rossoctl --json isPrerelease --jq '.isPrerelease'
```

E2E validation (mandatory for GA, recommended for RCs):

```bash
gh workflow run e2e-release-validation.yaml -f version=<version> --repo rossoctl/rossoctl
```

---

## Release Notes

### Alpha
Auto-generated changelog is sufficient.

### RC
```markdown
Release candidate for vX.Y.0.

## Testing needed
- [ ] Clean Kind install
- [ ] OpenShift install
- [ ] Upgrade from previous GA
- [ ] E2E tests

## Changes since rc.N-1
- PR #NNN - description
- PR #NNN - description
```

### GA
```markdown
## Highlights
- Feature 1
- Feature 2

## Breaking Changes
- (list or "None")

## Component Versions
| Component | Version |
|-----------|---------|
| rossoctl (platform) | vX.Y.0 |
| cortex | vA.B.0 |
| rossoctl-operator | vC.D.0 |

## Upgrade Notes
- (steps from previous GA)
```

### Announce (GA only)
- Slack: https://ibm.biz/rossoctl-slack
- Mailing list: rossoctl-maintainers@googlegroups.com

---

## Support Window

| Policy | Scope |
|--------|-------|
| Active support (N) | Bug fixes + security patches |
| Security-only (N-1) | Security patches only |
| End of life (N-2+) | No further releases |

---

## Security Patches

| Aspect | Security | Regular bug fix |
|--------|----------|-----------------|
| Timeline | 24-72h | Next patch window |
| Disclosure | Private fix, coordinated | Public PR |
| RC required? | No | Recommended |
| Backport scope | All supported branches | Latest only |

Process: private fix → apply to all supported release branches → tag all →
publish GitHub Security Advisory with CVE.

---

## Automation

These happen automatically on tag push (via `build.yaml`):

- Container images built and pushed to `ghcr.io/rossoctl/`
- Helm charts packaged and pushed to OCI registry
- GitHub Release created (pre-release flag auto-detected from tag)

### Interactive guidance

The skill asks questions at every decision point:
- Which PRs to include in the next RC
- Whether dependency repos need release branches
- How to handle cherry-pick conflicts
- Whether the RC is ready to tag
- GA readiness criteria
