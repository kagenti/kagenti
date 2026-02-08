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

## Incremental Progress Rule

**Each commit should reduce the number of failing tests.** This is the key metric for TDD:

```
Commit 1: 8 pass, 5 fail
Commit 2: 10 pass, 3 fail  ← good, 2 fewer failures
Commit 3: 11 pass, 2 fail  ← good, 1 fewer failure
Commit 4: 9 pass, 4 fail   ← BAD — more failures than before
```

### Rules

1. **At least 1 fewer test failure per commit** — verify before committing
2. **Don't fix too many things at once** — small focused commits are more stable
3. **If failures increase** — stop, analyze the diff, understand what change caused new failures before proceeding
4. **For complex tasks** — it's fine to take many commits, each removing 1-2 failures
5. **Track progress** — compare pass/fail counts between iterations

### Before Each Commit

Check test results against the previous run:

```bash
# Current results (save these)
uv run pytest kagenti/tests/e2e/ -v --tb=no -q 2>&1 | tail -5
```

If more tests fail than the previous run, investigate the regression before committing.

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
