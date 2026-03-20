# Session Delta Passover — Infrastructure

> **Date:** 2026-03-12
> **From:** Session Gamma
> **Cluster:** sbox42
> **Worktrees:** `.worktrees/sandbox-agent` (kagenti), `.worktrees/agent-examples` (agent code)
> **Branch:** `feat/sandbox-agent` (both repos)

## Prerequisites

Beta and Gamma should be complete before starting Delta:
- Beta: LLM budget proxy deployed, DB schema isolation working
- Gamma: UI polish (step naming, reflector prompt, event ordering, page load)

## What Session Delta Should Do

### Priority 0: Kiali Ambient Mesh (#23)

LiteLLM and Squid egress proxy need Istio ambient mesh labels to get mTLS:

```yaml
metadata:
  labels:
    istio.io/dataplane-mode: ambient
```

- Add label to LiteLLM Deployment in `kagenti-system`
- Add label to egress proxy Deployments in agent namespaces
- Verify in Kiali that traffic between agent -> LiteLLM shows mTLS
- Verify in Kiali that traffic between agent -> egress proxy shows mTLS

### Priority 1: OTEL/Phoenix Traces (#26)

Phoenix trace export is broken. Fix the OTEL pipeline:

1. Verify OTEL Collector is receiving GenAI spans from agents
2. Check Phoenix exporter configuration in OTEL Collector config
3. Fix broken trace export — traces should appear in Phoenix UI
4. Verify per-session trace correlation (session context_id in span attributes)

### Priority 2: DB Metadata Race Condition (#31)

A2A SDK's `save()` overwrites the full metadata JSON, causing race conditions
when multiple writers update the same task record concurrently.

- `MergingDatabaseTaskStore` was a partial fix — verify it works
- If not sufficient, implement row-level locking or JSON merge patch
- Test with concurrent budget_update + loop_event writes

### Priority 3: Ghost Sessions (#33)

Recovery tasks survive pod rollouts, creating phantom sessions:

- Investigate: are these leftover `working` state tasks from before rollout?
- Add cleanup logic: on agent startup, mark stale `working` tasks as `failed`
- Or: add a TTL-based reaper that marks tasks older than N minutes as failed

### Priority 4: Agent Crash Recovery (#38)

LangGraph supports resuming from checkpoint via `ainvoke(None, config)`:

1. Design the recovery flow (on agent restart, detect interrupted tasks)
2. Implement checkpoint resume for tasks in `working` state
3. Test: kill agent pod mid-task, verify it resumes after restart
4. Coordinate with ghost sessions fix (P3) — recovery vs cleanup decision

## Items from Master Tracking

| # | Item | Origin | Notes |
|---|------|--------|-------|
| 23 | Kiali ambient mesh labels | Y | LiteLLM + Squid need ambient label |
| 26 | LLM usage panel (OTEL) | Y | Phoenix trace export broken |
| 31 | DB metadata race condition | Y | A2A SDK save() overwrites metadata |
| 33 | Ghost sessions after cleanup | Y | Recovery tasks survive pod rollout |
| 38 | Agent crash recovery | Alpha | LangGraph `ainvoke(None, config)` |
