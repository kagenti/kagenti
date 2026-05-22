# Release Management SOP

Standard Operating Procedure for releasing Kagenti, aligned with CNCF project
conventions (Kubernetes, Helm, ArgoCD).

> **Related:** [docs/releasing.md](releasing.md) contains the procedural step-by-step
> instructions. This document covers policy and governance.

---

## 1. Branching Strategy

| Branch | Purpose | Lifetime |
|--------|---------|----------|
| `main` | Active development; all features merge here | Permanent |
| `release-X.Y` | Stabilization and patches for a minor series | Permanent once created |

### Rules

- **`main` is always releasable.** CI must pass; broken builds are P0.
- **Release branches are cut at RC time**, not before. Alpha releases tag directly from `main`.
- **No direct commits to release branches.** All fixes land on `main` first and are cherry-picked back (exceptions: release-only metadata changes like version bumps).
- **One active release branch per minor version.** Example: `release-0.6` covers `v0.6.0-rc.1` through all `v0.6.Z` patches.

### When to Create a Release Branch

```
main ─────●────●────●────●────●────●─── (development continues)
                              │
                              └─── release-0.6 ─── rc.1 ─── rc.2 ─── v0.6.0 ─── v0.6.1
```

Create `release-X.Y` when cutting the **first RC**:

```bash
git checkout -b release-X.Y main
git push origin release-X.Y
```

---

## 2. Pre-release Lifecycle

### 2.1 Alpha Releases

**Purpose:** Milestone snapshots for early testing. May break between releases.

**Naming:** `vX.Y.0-alpha.N` (e.g., `v0.7.0-alpha.1`, `v0.7.0-alpha.2`)

**Criteria to tag:**
- CI passes on `main`
- No known data-loss or security issues in the tagged commit
- All image tags in `values.yaml` pinned (no `latest`)

**Cadence:** As needed during active development (typically every 1-2 weeks during a cycle).

**Process:**

```bash
# Determine next alpha number
git tag --list 'vX.Y.0-alpha.*' --sort=-v:refname | head -1

# Tag (follow multi-repo dependency order - see Section 6)
git tag -s vX.Y.0-alpha.N -m "vX.Y.0-alpha.N"
git push origin vX.Y.0-alpha.N
```

### 2.2 Release Candidates

**Purpose:** Feature-complete builds for validation. Code freeze in effect.

**Naming:** `vX.Y.0-rc.N` (e.g., `v0.7.0-rc.1`, `v0.7.0-rc.2`)

**Code freeze rules:**
- Only bug fixes, test fixes, and documentation changes are allowed.
- No new features, refactors, or dependency upgrades (unless fixing a security issue).
- All changes go through the normal PR process targeting the release branch.

**Entry criteria:**
- [ ] All planned features for the milestone are merged to `main`
- [ ] No open P0/P1 bugs against the milestone
- [ ] Feature freeze declared on Slack/mailing list
- [ ] Release branch created from `main`
- [ ] All image tags pinned to RC version

**Progression:**
- If bugs are found during RC testing, fix on `main`, cherry-pick to release branch, bump to `rc.N+1`.
- Maximum 3 RCs recommended. If more are needed, re-evaluate scope.

---

## 3. Stable (GA) Releases

**Naming:** `vX.Y.0` (first GA of a minor series), `vX.Y.Z` (patches)

**Promotion criteria:**
- [ ] At least 1 RC validated with no release-blocking issues
- [ ] Minimum 1-week soak since last RC (recommended)
- [ ] At least one maintainer sign-off (not the person who tagged the RC)
- [ ] E2E tests pass on Kind and OpenShift
- [ ] Upgrade path from previous GA tested
- [ ] Release notes written and reviewed

**Process:**

```bash
# On the release branch
git checkout release-X.Y

# Verify the RC tag is the HEAD (or contains only release metadata commits)
git log --oneline release-X.Y...vX.Y.0-rc.N  # should be empty or trivial

# Tag GA
git tag -s vX.Y.0 -m "vX.Y.0"
git push origin vX.Y.0
```

**Post-release:**
- Mark GitHub Release as "Latest"
- Announce on Slack and mailing list
- Update installation docs with new version

---

## 4. Maintenance and Patching

### 4.1 Cherry-Pick Workflow

All fixes land on `main` first. To backport to a release branch:

```bash
# 1. Identify the commit(s) to cherry-pick
git log --oneline main | grep "<fix description>"

# 2. Cherry-pick onto release branch
git checkout release-X.Y
git cherry-pick -x <commit-sha>  # -x adds "cherry picked from" reference

# 3. Resolve conflicts if any, then push
git push origin release-X.Y

# 4. Tag the patch
git tag -s vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

The `-x` flag is mandatory — it creates traceability between main and the backport.

### 4.2 Security Patches vs. Bug Fixes

| Aspect | Security Patch | Bug Fix |
|--------|---------------|---------|
| Timeline | ASAP (24-72h target) | Next patch window |
| Disclosure | Private fix, coordinated disclosure | Public PR on main |
| RC required? | No (direct to patch tag) | Recommended for non-trivial fixes |
| Backport scope | All supported release branches | Latest release branch only (unless critical) |
| Communication | Security advisory + CVE | Release notes |

**Security patch process:**
1. Fix developed in a private fork or restricted branch
2. Patch applied to all supported release branches simultaneously
3. Tags pushed for all affected versions
4. GitHub Security Advisory published
5. Announce on mailing list with CVE reference

### 4.3 Support Window

| Policy | Scope |
|--------|-------|
| Active support | Current GA (N) — bug fixes and security patches |
| Security-only | Previous GA (N-1) — security patches only |
| End of life | N-2 and older — no further releases |

---

## 5. Multi-Repo Dependency Order

Kagenti spans multiple repositories. Tags must be created in dependency order:

```
1. kagenti/kagenti-operator      →  tag, wait for CI
2. kagenti/kagenti-extensions    →  tag, wait for CI
3. kagenti/kagenti               →  update Chart.yaml + values.yaml, tag
```

**Between each step:** Verify container images and Helm charts are published before proceeding to the next repository.

---

## 6. Automation Goals

### Currently Automated (via existing `build.yaml` workflows)

| Step | Trigger | Output |
|------|---------|--------|
| Container image build + push | Tag push (`v*`) | Images on `ghcr.io/kagenti/` |
| Helm chart package + push | Tag push (`v*`) | OCI charts on `ghcr.io/kagenti/` |
| GitHub Release creation | Tag push (`v*`) | Release with auto-generated changelog |
| Pre-release flag | GoReleaser `prerelease: auto` | `-alpha`/`-rc` tags marked as pre-release |

### Recommended Additions

| Automation | Trigger | Purpose | Priority |
|-----------|---------|---------|----------|
| **Release branch protection** | Branch creation matching `release-*` | Enforce PR reviews, required CI, no force push | P0 |
| **Changelog generation** | Tag push | Generate structured changelog from conventional commits (e.g., `git-cliff`) | P1 |
| **Image tag lint** | PR to `release-*` branches | Fail if `values.yaml` contains `tag: latest` | P1 |
| **Version bump PR** | Manual workflow dispatch | Create PR bumping Chart.yaml + values.yaml to target version | P2 |
| **Cross-repo orchestration** | Manual workflow dispatch | Trigger dependency-ordered release across repos | P2 |
| **Cosign image signing** | After image push | Sign images with Sigstore keyless signing | P2 |
| **SBOM generation** | Tag push | Produce CycloneDX SBOM per image | P3 |
| **Release readiness check** | Manual or pre-tag hook | Validate all criteria before allowing a tag | P3 |

### Suggested GitHub Action: `release-lint.yaml`

```yaml
name: Release Lint
on:
  pull_request:
    branches: ['release-*']
    paths: ['charts/kagenti/values.yaml', 'charts/kagenti/Chart.yaml']

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: No 'latest' tags allowed
        run: |
          if grep -q 'tag: latest' charts/kagenti/values.yaml; then
            echo "::error::values.yaml contains 'tag: latest' — pin all images before release"
            exit 1
          fi
      - name: Chart.yaml versions are not -alpha on release branches
        env:
          BASE_REF: ${{ github.base_ref }}
        run: |
          if echo "$BASE_REF" | grep -q 'release-' && \
             grep -q 'alpha' charts/kagenti/Chart.yaml; then
            echo "::warning::Chart.yaml references alpha dependencies on a release branch"
          fi
```

---

## 7. Release Checklist (Quick Reference)

### Alpha

- [ ] CI green on `main`
- [ ] Tag dependency repos in order (operator → extensions)
- [ ] Verify images/charts published for each
- [ ] Update `Chart.yaml` + `values.yaml` in `kagenti/kagenti`
- [ ] Pin all image tags (no `latest`)
- [ ] Run `helm dependency update charts/kagenti/`
- [ ] Tag `kagenti/kagenti`
- [ ] Verify GitHub Release is Pre-release

### RC

- [ ] Feature freeze announced
- [ ] All alpha checklist items
- [ ] Release branch `release-X.Y` created
- [ ] E2E tests pass
- [ ] Testing checklist added to release notes

### GA

- [ ] All RC checklist items
- [ ] 1-week soak since last RC
- [ ] Maintainer sign-off
- [ ] Upgrade from previous GA tested
- [ ] Full release notes with component version table
- [ ] Announcement drafted

### Patch

- [ ] Fix merged to `main` with tests
- [ ] Cherry-picked to `release-X.Y` with `-x` flag
- [ ] CI passes on release branch
- [ ] Tag `vX.Y.Z`
- [ ] Release notes describe the fix

---

## 8. Tooling

| Tool | Role |
|------|------|
| `/release` skill | Interactive AI-assisted release workflow |
| `gh` CLI | Tag management, release creation, CI status |
| GoReleaser | Builds binaries, manages GitHub Releases |
| Helm | Chart packaging and OCI registry push |
| `git-cliff` (proposed) | Conventional-commit changelog generation |
| Cosign (proposed) | Image signature verification |
