# Releasing Kagenti

Practical guide for release managers. Covers the full lifecycle from alpha
through GA, including the stabilization loop between RCs.

> **AI-assisted:** Use `/release` in Claude Code for interactive guidance
> through any step below. See [Using the Release Skill](#using-the-release-skill).

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
1. kagenti/kagenti-operator     →  tag, wait for CI + images
2. kagenti/kagenti-extensions   →  tag, wait for CI + images
3. kagenti/agent-examples       →  tag (if applicable)
4. kagenti/kagenti              →  update Chart.yaml + values.yaml, tag
```

### Governance

- Any maintainer can cut alpha/RC releases
- GA requires sign-off from at least one other maintainer
- Mailing list: `kagenti-maintainers@googlegroups.com`

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
gh run list --branch main --limit 3 --repo kagenti/<repo>

# 2. Pin images
bash scripts/pin-release-tags.sh v0.7.0-alpha.1
bash scripts/check-release-pins.sh

# 3. Tag dependency repos in order (operator → extensions → examples)
git tag -s v0.3.0-alpha.1 -m "v0.3.0-alpha.1"
git push origin v0.3.0-alpha.1

# 4. Update Chart.yaml + helm dependency update, commit, tag kagenti/kagenti
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

# 2. In kagenti/kagenti: update Chart.yaml with RC sub-chart versions
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
LAST_RC_DATE=$(gh release view v0.6.0-rc.6 --repo kagenti/kagenti --json publishedAt --jq '.publishedAt')

gh pr list --repo kagenti/kagenti --state merged --base main \
  --search "merged:>$LAST_RC_DATE" --json number,title,mergeCommit \
  --jq '.[] | "#\(.number) \(.title) [\(.mergeCommit.oid[:12])]"'

# Check dependency repos too
gh pr list --repo kagenti/kagenti-extensions --state merged --base main \
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
order), then update `Chart.yaml` in the kagenti release branch.

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
gh release edit v0.6.0 --repo kagenti/kagenti --latest
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
gh pr create --base release-X.Y --repo kagenti/kagenti \
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

Both charts (`charts/kagenti/` and `charts/kagenti-deps/`) must have all
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
| kagenti | ui-v2 | `ui.frontend.tag` |
| kagenti | backend | `ui.backend.tag` |
| kagenti | ui-oauth-secret | `uiOAuthSecret.tag` |
| kagenti | agent-oauth-secret | `agentOAuthSecret.tag` |
| kagenti | api-oauth-secret | `apiOAuthSecret.tag` |
| kagenti | mlflow-oauth-secret | `mlflowOAuthSecret.tag` |
| kagenti-deps | spiffe-idp-setup | `spiffeIdp.image.tag` |

---

## Verification

After every tag, verify:

```bash
# GitHub Releases
gh release view <version> --repo kagenti/kagenti

# Container images
for img in ui-v2 backend ui-oauth-secret agent-oauth-secret api-oauth-secret; do
  docker manifest inspect ghcr.io/kagenti/kagenti/$img:<version> >/dev/null 2>&1 \
    && echo "$img OK" || echo "$img MISSING"
done

# Helm charts
helm show chart oci://ghcr.io/kagenti/kagenti-extensions/kagenti-webhook-chart --version <version>
helm show chart oci://ghcr.io/kagenti/kagenti-operator/kagenti-operator-chart --version <version>

# Pre-release flag (should be true for alpha/RC, false for GA)
gh release view <version> --repo kagenti/kagenti --json isPrerelease --jq '.isPrerelease'
```

E2E validation (mandatory for GA, recommended for RCs):

```bash
gh workflow run e2e-release-validation.yaml -f version=<version> --repo kagenti/kagenti
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
| kagenti (platform) | vX.Y.0 |
| kagenti-extensions | vA.B.0 |
| kagenti-operator | vC.D.0 |

## Upgrade Notes
- (steps from previous GA)
```

### Announce (GA only)
- Slack: https://ibm.biz/kagenti-slack
- Mailing list: kagenti-maintainers@googlegroups.com

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

- Container images built and pushed to `ghcr.io/kagenti/`
- Helm charts packaged and pushed to OCI registry
- GitHub Release created (pre-release flag auto-detected from tag)

---

## Troubleshooting

**Stale Chart.lock:** Always run `helm dependency update charts/kagenti/`
after changing `Chart.yaml`.

**`tag: latest` in values.yaml:** Run `bash scripts/check-release-pins.sh` —
it catches this.

**GoReleaser pre-release detection:** Tags with `-` after the version (e.g.,
`-rc.1`) are auto-marked as pre-release. No config needed.

**Chart version vs app version:** `version` in `Chart.yaml` should match the
tag (minus `v` prefix).

---

## Using the Release Skill

The `/release` skill in Claude Code provides interactive, guided assistance
for all steps above. It tracks state, discovers candidate fixes, and asks
questions at decision points.

### Commands

```
/release                    # Full assessment → asks what to do
/release status             # Current state across all repos + fix tracker
/release alpha vX.Y.0-alpha.N
/release rc vX.Y.0-rc.N    # First RC creates release branches
/release stabilize          # Find fixes, cherry-pick, tag next RC
/release cherry-pick <PR#>  # Cherry-pick a specific PR
/release ga vX.Y.0          # Promote to GA
/release patch vX.Y.Z
```

### What the skill does

| Command | Actions |
|---------|---------|
| `/release` | Checks tags, Chart.yaml, image pins across all repos. Asks what you want to do. |
| `/release rc` | Verifies prerequisites, tags dependency repos in order, creates release branches, pins images, tags RC. |
| `/release stabilize` | Finds PRs merged since last RC (all repos), asks which to include, cherry-picks in dependency order, pins images, tags next RC. |
| `/release ga` | Checks soak time and sign-off, tags dependency repos with GA, pins images, tags GA, generates release notes. |

### Fix tracking

The skill maintains a local tracker at `/tmp/kagenti/release/<version>/rc-fixes.md`
that records:
- Cherry-picked fixes (ready to tag)
- Pending fixes (merged to main, not yet cherry-picked)
- In-progress fixes (PR open, not merged yet)
- Dependency repo fixes

This persists across sessions and feeds into RC release notes.

### Interactive guidance

The skill asks questions at every decision point:
- Which PRs to include in the next RC
- Whether dependency repos need release branches
- How to handle cherry-pick conflicts
- Whether the RC is ready to tag
- GA readiness criteria
