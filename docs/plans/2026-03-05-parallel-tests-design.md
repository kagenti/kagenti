# Parallel E2E Tests Design

**Date**: 2026-03-05
**Status**: Approved
**Session**: L

## Goal

Make all E2E tests run in parallel with `npx playwright test e2e/ --workers=auto`. No serial dependencies between tests. Every test is self-contained.

## Changes

### 1. Collapse `sandbox-sessions.spec.ts` (6 serial → 2 independent)

**Test A: "session isolation across contexts"** (~5 min)
- Login, navigate to sandbox
- Create Session A with unique marker, send 4 turns
- Create Session B with unique marker, send 4 turns
- Verify Session B workspace doesn't contain Session A's files
- Switch back to Session A, verify history intact
- Verify sidebar shows session titles (not raw IDs)

**Test B: "session persists across page reload"** (~2 min)
- Login, create new session with unique marker
- Send message, verify response
- Reload page, verify session content preserved

Remove: `test.describe.serial()`, shared `sessionAId`/`sessionBId` variables.

### 2. Collapse `agent-rca-workflow.spec.ts` (6 serial → 1 test)

**Single test: "RCA agent end-to-end"** (~5 min)
- Deploy rca-agent via wizard, patch security context
- Verify agent card has correct capabilities
- Send RCA request, wait for response
- Reload page, verify session persists
- Navigate away and back, verify session persists
- Check response quality (Root Cause, Impact, Fix keywords)

Remove: `test.describe.configure({ mode: 'serial' })`, shared `sessionUrl`.

### 3. Clean up `test:ui-sandbox` skill

Replace parallelism classification table with simple rules:
- All tests run in parallel
- Every test is self-contained
- Use unique markers
- One command: `cd kagenti/ui-v2 && npx playwright test e2e/`

## Files to Change

| File | Change |
|------|--------|
| `e2e/sandbox-sessions.spec.ts` | Merge 6 tests → 2 independent tests |
| `e2e/agent-rca-workflow.spec.ts` | Merge 6 tests → 1 test |
| `.claude/skills/test:ui-sandbox/SKILL.md` | Simplify parallelism section |
