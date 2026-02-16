# CVE Gate — Superpowers Integration Notes

## finishing-a-development-branch

The superpowers `finishing-a-development-branch` skill presents 4 options:
1. Merge locally
2. Push and create PR
3. Keep as-is
4. Discard

**CVE gate insertion point: between Step 1 (Verify Tests) and Step 3 (Present Options).**

When this skill is invoked:
1. After tests pass (Step 1), invoke `cve:scan` on the branch diff
2. If CVEs found, invoke `cve:brainstorm` — block Option 2 (Push and Create PR)
3. Options 1, 3, 4 remain available (local operations)
4. Option 2 unblocks when CVE hold is resolved

**NOTE:** This integration requires changes to the superpowers plugin.
Until the plugin is updated, the CVE gate in `tdd:ci` Phase 3.5 and
`git:commit` CVE ID check provide coverage for the same scenarios.
