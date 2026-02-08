---
name: rca
description: Root cause analysis workflows - systematic investigation of failures
---

# RCA Skills

Root cause analysis workflows for systematic failure investigation.

## Auto-Select Sub-Skill

When this skill is invoked, determine the right sub-skill based on context:

### Step 1: Determine what's available

Check for HyperShift cluster:

```bash
ls ~/clusters/hcp/kagenti-hypershift-custom-*/auth/kubeconfig 2>/dev/null
```

Check for Kind cluster:

```bash
kind get clusters 2>/dev/null
```

### Step 2: Route based on failure source and access

```
Where did the failure occur?
    │
    ├─ CI pipeline (GitHub Actions) ─────────────────────────┐
    │                                                         │
    │   Do you have a live cluster matching the CI env?       │
    │       │                                                 │
    │       ├─ HyperShift cluster available                   │
    │       │   → Use `rca:hypershift` (deep investigation)   │
    │       │                                                 │
    │       ├─ Kind cluster available (for Kind CI failures)  │
    │       │   → Use `rca:kind` (reproduce locally)          │
    │       │                                                 │
    │       └─ No cluster                                     │
    │           → Use `rca:ci` (logs and artifacts only)      │
    │           → If inconclusive, ask user to create cluster │
    │                                                         │
    ├─ Local Kind cluster ──────────────────────────────────┐ │
    │   → Use `rca:kind` (full local access)                │ │
    │                                                       │ │
    └─ HyperShift cluster ─────────────────────────────────┐│ │
        → Use `rca:hypershift` (full remote access)        ││ │
                                                           ││ │
After RCA is complete, switch to TDD for fix iteration: ◄──┘┘ │
    - `tdd:ci` (CI-only)                                       │
    - `tdd:hypershift` (live cluster)                          │
    - `tdd:kind` (local cluster)                               │
```

## Available Skills

| Skill | Access | Auto-approve | Best for |
|-------|--------|--------------|----------|
| `rca:ci` | CI logs/artifacts only | N/A | CI failures, no cluster |
| `rca:hypershift` | Full cluster access | All read ops | Deep investigation |
| `rca:kind` | Full local access | All ops | Kind failures, fast repro |

## Related Skills

- `tdd:ci` - Fix iteration after RCA (CI-driven)
- `tdd:hypershift` - Fix iteration with live cluster
- `tdd:kind` - Fix iteration on Kind
- `k8s:logs` - Query and analyze component logs
- `k8s:pods` - Debug pod issues
