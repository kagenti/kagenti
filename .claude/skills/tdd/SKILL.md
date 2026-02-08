---
name: tdd
description: Test-driven development workflows for Kagenti - CI, HyperShift, and Kind
---

# TDD Skills

Test-driven development workflows for iterative Kagenti development.

## Auto-Select Sub-Skill

When this skill is invoked, determine the right sub-skill automatically:

### Step 1: Check for a live HyperShift cluster

```bash
ls ~/clusters/hcp/kagenti-hypershift-custom-*/auth/kubeconfig 2>/dev/null
```

### Step 2: Check for a running Kind cluster

```bash
kind get clusters 2>/dev/null
```

### Step 3: Route

```
HyperShift kubeconfig found?
    │
    ├─ YES → Use `tdd:hypershift`
    │        (full cluster access, real-time debugging)
    │
    └─ NO → Kind cluster running?
             │
             ├─ YES → Use `tdd:kind`
             │        (fast local iteration)
             │
             └─ NO → Is this a CI failure investigation?
                      │
                      ├─ YES → Use `tdd:ci`
                      │        (commit, push, wait for CI)
                      │
                      └─ NO → Ask user:
                               "No cluster available. Options:
                                1. Create Kind cluster (auto-approved)
                                2. Create HyperShift cluster (requires approval)
                                3. Use CI-only workflow (tdd:ci)"
```

## Available Skills

| Skill | Cluster | Auto-approve | Speed |
|-------|---------|--------------|-------|
| `tdd:ci` | None needed | N/A (CI runs remotely) | Slow (wait for CI) |
| `tdd:kind` | Local Kind | All ops auto-approved | Fast |
| `tdd:hypershift` | HyperShift hosted | All ops auto-approved | Medium |

## TDD Full Loop

The complete TDD loop includes test, git, and CI monitoring:

```
1. Write/fix code
2. test:write — write or update tests
3. test:review — verify test quality (no silent skips, assertive)
4. test:run-kind or test:run-hypershift — execute tests
5. Track progress — compare test results with previous run
6. git:commit — commit with proper format (repo:commit)
7. git:rebase — rebase onto upstream/main
8. Push → ci:monitoring — wait for CI results
9. CI passes? → Done. CI fails? → Back to step 1.
```

## Commit Policy

**Never revert. Never amend. Commits are permanent history.**

Only commit when:
- All tests pass, OR
- At least 1 additional test passes compared to the previous commit (forward progress)

```
Commit 1: 8 pass, 5 fail  ← baseline, acceptable
Commit 2: 10 pass, 3 fail ← good, +2 passing
Commit 3: 11 pass, 2 fail ← good, +1 passing
(no commit): 9 pass, 4 fail ← DON'T COMMIT — regression, keep iterating
```

### Rules

1. **Don't commit until tests improve** — at least 1 fewer failure than last commit
2. **Never revert** — keep the history, fix forward instead
3. **Never amend** — each commit is a checkpoint, session retrospective uses the history
4. **Don't fix too many things at once** — small focused commits are more stable
5. **If stuck for too long** — the session retrospective will catch it and improve the skill

### Before Each Commit

Run tests and compare with last commit's results:

```bash
uv run pytest kagenti/tests/e2e/ -v --tb=no -q 2>&1 | tail -5
```

If pass count didn't increase, keep iterating — don't commit yet.

## Related Skills

- `rca:ci` - Root cause analysis from CI logs
- `rca:hypershift` - Root cause analysis with live cluster
- `rca:kind` - Root cause analysis on Kind
- `ci:status` - Check CI pipeline status
- `test` - Test writing, reviewing, and running
- `test:review` - Verify test quality before committing
- `git:commit` - Commit with proper format
- `git:rebase` - Rebase before pushing
- `repo:commit` - Repository commit conventions
