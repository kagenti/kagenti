# Session Beta-3 — Per-Session Landlock Isolation

> **Status:** Planned (brainstorm in Beta-2)
> **Depends On:** Beta-2 (unified turn rendering)

## Goal

Implement per-session file access isolation using Linux Landlock LSM
and Kubernetes securityContext, so each agent session can only access
its own workspace subdirectory.

## Design Areas

### 1. Landlock LSM Integration
- Agent sandbox already has `landlock: bool` wizard field
- Need to implement the actual Landlock ruleset in the agent container
- Rules: allow read/write only to `/workspace/{session_id}/`
- Deny access to other sessions' workspace directories

### 2. Per-Session UID/GID
- Each session gets a unique UID within the agent pod
- `securityContext.fsGroup` per session subdirectory
- For PVC: subdirectory permissions set on session creation
- For emptyDir: same approach, no persistence concern

### 3. Workspace Layout
```
/workspace/
  {session_id_1}/    # UID 1001, GID 1001
    repos/
    output/
  {session_id_2}/    # UID 1002, GID 1001
    repos/
    output/
```

## Related
- `docs/plans/2026-03-15-agent-graph-card-design.md`
- `docs/plans/2026-03-15-session-theta-squid-proxy-counters.md`
