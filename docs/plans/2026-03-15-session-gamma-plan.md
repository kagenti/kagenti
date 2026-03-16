# Session Gamma — Graph Feedback + File Browser Plan

> **Status:** Planned
> **Depends On:** Beta-2 (unified turn rendering, graph view polish)

## Graph View Feedback

### Two Subtabs in Graph Mode
1. **All Messages** — accumulated edge counts across all messages in session
2. **Selected Message** — single message graph with that message's traversal

### Session List Integration
- Collapsible sidebar on left shows all messages
- Each message: user prompt summary, status, step progress
- Click to filter graph to that message
- "All" button shows accumulated view

### Inline Mode Improvements
- Messages with summary card + link to fullscreen
- Fullscreen: detailed graph with all events visible
- Per-message [Graph] [Detail] toggle

## File Browser Fixes

### Scroll Reset Bug
- File browser reloads on parent state change (polling)
- Fix: React.memo or useMemo to stabilize FileBrowser props
- Scroll position should persist during background polls

### File Browser Integration with Agent Loop
- Plan files (plan.json, plan.md) should be highlighted
- Agent output files linked from the final answer
- Workspace file changes tracked per session

## Related
- `docs/plans/2026-03-15-agent-graph-card-design.md` — Section 7 (rendering modes)
- `GraphLoopView.tsx` — enhanced in Beta with topology DAG
