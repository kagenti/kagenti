---
name: tdd:ci
description: CI-driven TDD workflow - commit, local checks, push, wait for CI, iterate on failures
---

# TDD-CI Workflow

Iterative development workflow using CI as the test environment. Commit changes, run local checks, push to PR, wait for CI results, and iterate on failures.

## tdd:ci vs tdd:hypershift

| Aspect | `tdd:ci` | `tdd:hypershift` |
|--------|----------|------------------|
| **Test environment** | CI pipeline (no direct access) | Your own HyperShift cluster |
| **Debugging** | Analyze CI logs after failure | Real-time debugging with `k8s:*` skills |
| **Feedback loop** | Slower (wait for CI) | Faster (immediate cluster access) |
| **Use when** | Final validation, no cluster | Active development, need to inspect state |

**Use `tdd:hypershift`** when you have a cluster and need real-time debugging.
**Use `tdd:ci`** when iterating on CI failures or for final PR validation.

## When to Use

- Iterating on CI failures (no cluster access needed)
- Final validation before merge
- When you don't have a HyperShift cluster running
- Simple changes that don't need live debugging

## The Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Brainstorm│───▶│  Commit  │───▶│  Local   │───▶│   Push   │  │
│  │ (if new)  │    │          │    │  Checks  │    │          │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                                                        │        │
│                                                        ▼        │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │   Fix    │◀───│  Analyze │◀───│   Wait   │◀───│    CI    │  │
│  │          │    │  Failure │    │          │    │  Runs    │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │                                                         │
│       └─────────────────────────────────────────────────────────┘
│                         (iterate until green)
└─────────────────────────────────────────────────────────────────┘
```

## Phase 1: Brainstorm (New Features)

For new features or complex changes, use the brainstorming skill first:

```
/superpowers:brainstorming
```

This helps clarify:
- What exactly needs to be done
- Edge cases and requirements
- Potential approaches

## Phase 2: Commit

Create a focused commit with your changes:

```bash
# Stage specific files (not git add -A)
git add <changed-files>

# Commit with sign-off
git commit -s -m "fix: description of change"
```

**Commit message conventions:**
- `fix:` - Bug fixes
- `feat:` - New features
- `docs:` - Documentation
- `refactor:` - Code refactoring
- `test:` - Test changes
- `chore:` - Maintenance

## Phase 3: Local Checks

Run local validation before pushing:

```bash
# Linting
make lint

# Pre-commit hooks
pre-commit run --all-files

# Unit tests (if applicable)
uv run pytest kagenti/tests/ -v --ignore=kagenti/tests/e2e
```

**Fix any failures before pushing.**

## Phase 4: Push to PR

```bash
# Push to remote (creates PR if needed)
git push -u origin <branch-name>

# Or if PR exists, just push
git push
```

If no PR exists yet:

```bash
gh pr create --title "fix: description" --body "## Summary
- What this changes

## Test plan
- CI will validate"
```

## Phase 5: Wait for CI

Monitor CI status:

```bash
# Watch PR checks
gh pr checks --watch

# Or check specific workflow
gh run list --branch <branch-name>
gh run view <run-id>
```

**Wait for CI to complete before making more changes.**

## Phase 6: Analyze Failures

When CI fails:

```bash
# View failed run
gh run view <run-id> --log-failed

# Or view in browser
gh run view <run-id> --web
```

**Identify root cause before fixing:**
1. Read the full error message
2. Check if it's a flaky test or real failure
3. Understand what the test expects
4. Use `superpowers:systematic-debugging` for complex failures

## Phase 7: Fix and Iterate

```bash
# Make fix
vim <file>

# Commit the fix (new commit, not amend)
git add <fixed-files>
git commit -s -m "fix: address CI failure - description"

# Push
git push

# Wait for CI again
gh pr checks --watch
```

**Repeat until all checks pass.**

## Escalation: Too Many Iterations?

After **3+ failed CI iterations**, consider switching to `tdd:hypershift` for real-time debugging:

### Check for Existing Cluster

```bash
# Check if cluster exists for current worktree
WORKTREE=$(basename $(git rev-parse --show-toplevel))
ls ~/clusters/hcp/kagenti-hypershift-custom-*/auth/kubeconfig 2>/dev/null
```

### Decision Tree

```
CI failed 3+ times?
    │
    ├─ YES → Check for existing cluster
    │         │
    │         ├─ Cluster exists → Switch to `tdd:hypershift`
    │         │
    │         └─ No cluster → Ask user:
    │                         "Create HyperShift cluster for debugging?"
    │                         │
    │                         ├─ YES → Use `hypershift:cluster` to create
    │                         │        Then switch to `tdd:hypershift`
    │                         │
    │                         └─ NO → Continue with tdd:ci
    │
    └─ NO → Continue iterating
```

### Escalate to HyperShift

If user approves cluster creation:

```bash
# Create cluster (max 5 char suffix)
KUBECONFIG=~/clusters/hcp/kagenti-hypershift-custom-<suffix>/auth/kubeconfig \
  ./.github/scripts/local-setup/hypershift-full-test.sh <suffix> \
  --include-cluster-create --skip-cluster-destroy
```

Then switch to `tdd:hypershift` for real-time debugging with:
- `k8s:pods` - inspect pod state
- `k8s:logs` - check logs immediately
- `k8s:live-debugging` - iterative fixes

## Quick Reference

| Step | Command |
|------|---------|
| Stage files | `git add <files>` |
| Commit | `git commit -s -m "type: message"` |
| Lint | `make lint` |
| Pre-commit | `pre-commit run --all-files` |
| Push | `git push` |
| Watch CI | `gh pr checks --watch` |
| View failure | `gh run view <id> --log-failed` |

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Push without local checks | Run `make lint` and `pre-commit` first |
| Amend after push | Create new commits |
| Push multiple times quickly | Wait for CI between pushes |
| Guess at fixes | Analyze failure logs first |
| Skip brainstorming | Use `/superpowers:brainstorming` for new features |

## Related Skills

- `superpowers:brainstorming` - Design before implementation
- `superpowers:systematic-debugging` - Debug CI failures
- `superpowers:verification-before-completion` - Verify before claiming done
- `tdd:hypershift` - TDD with HyperShift clusters
- `git:status` - Check worktree and PR status before pushing
- `test:review` - Review test quality
- `test:write` - Write new tests
- `git:commit` - Commit format
- `git:rebase` - Rebase onto upstream main
- `repo:commit` - Repository commit conventions
