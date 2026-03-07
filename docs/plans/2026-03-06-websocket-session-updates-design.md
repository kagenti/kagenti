# WebSocket / SSE Session Updates Design

**Date:** 2026-03-06
**Status:** Passover to next session
**Author:** Claude Code (Session L)

## Problem

SandboxPage does not update when another tab or user sends a message to the same session. The current architecture is request-scoped: the SSE stream from `/chat/stream` is only active while the current user's chat request is being processed. Once the response completes, the connection closes and the UI goes idle. If a second user (or the same user in another tab) sends a message to the same `contextId`, the first tab has no way of knowing about the new messages until the page is manually refreshed.

This is especially problematic for:
- Multi-user collaboration on the same session
- Delegation events that arrive after the parent request completes
- HITL (human-in-the-loop) approval requests triggered by background agent work
- Long-running agent loops where the user navigates away and returns

## Current Architecture

```
Browser ──POST /chat/stream──> Backend ──SSE──> Browser
           (request-scoped)      (closes when done)
```

- SSE is **one-directional** (server to client) and **transient** (lives only for one request/response cycle).
- No persistent connection exists between the UI and backend for a given session.
- The UI uses `loadInitialHistory()` on mount and on session selection, but never re-fetches while idle.

## Interim Solution: Polling (implemented)

As a quick, low-risk fix, the UI now polls `getHistory(namespace, contextId, { limit: 5 })` every 5 seconds when the session is idle (not streaming). New messages are appended without replacing existing ones. This is good enough for demos and light multi-user scenarios.

**Limitations:** 5-second latency, unnecessary network traffic when nothing changes, does not scale to many concurrent viewers.

## Proposed: WebSocket Endpoint

### Endpoint

```
GET /ws/sandbox/{namespace}/sessions/{contextId}
```

Upgrades to WebSocket. Authenticated via the same Bearer token (passed as query param `?token=...` or via first message).

### Server-Side Behavior

1. On connect, the backend registers the WebSocket in a per-session connection set.
2. Whenever a message is added to the session store (by any source -- direct chat, delegation callback, HITL response), the backend broadcasts a session event to all connected WebSockets for that `contextId`.
3. On disconnect, the backend removes the WebSocket from the set.

### Event Schema

```json
{
  "type": "session_event",
  "event": "new_message" | "status_change" | "delegation_update",
  "message": { ... },          // HistoryMessage, present for new_message
  "status": "working" | "completed" | "failed",  // present for status_change
  "timestamp": "2026-03-06T12:00:00Z"
}
```

### Client-Side Integration

```typescript
useEffect(() => {
  if (!contextId || isStreaming) return;
  const ws = new WebSocket(`${WS_BASE}/ws/sandbox/${namespace}/sessions/${contextId}?token=${token}`);
  ws.onmessage = (evt) => {
    const data = JSON.parse(evt.data);
    if (data.event === 'new_message') {
      setMessages(prev => {
        const exists = prev.some(m => m.id === `history-${data.message._index}`);
        return exists ? prev : [...prev, toMessage(data.message, prev.length)];
      });
    }
  };
  return () => ws.close();
}, [contextId, isStreaming, namespace, token]);
```

### Backend Implementation Notes

- Use FastAPI `WebSocket` route in `sandbox_router.py`.
- Session event bus: a simple in-memory `dict[str, set[WebSocket]]` is sufficient for single-replica deployments. For multi-replica, use Redis Pub/Sub on channel `session:{contextId}`.
- The existing `_append_to_store()` method in `sandbox_service.py` should call `await broadcast_session_event(context_id, message)` after persisting.

## Alternative: SSE Endpoint for Session Updates

A simpler alternative for read-only updates:

```
GET /sandbox/{namespace}/sessions/{contextId}/events
Accept: text/event-stream
```

Keeps a long-lived SSE connection open. The server pushes events whenever the session state changes. This is simpler than WebSocket (no upgrade negotiation, works through more proxies) but is purely server-to-client.

**Pros:** Simpler implementation, better proxy compatibility, auto-reconnect via `EventSource` API.
**Cons:** Cannot send client-to-server messages (e.g., typing indicators), one-directional only.

For the Kagenti use case (session updates are read-only notifications), SSE is likely sufficient and simpler to implement.

## Recommendation

1. **Short-term (done):** Polling with 5-second interval -- already implemented in SandboxPage.
2. **Medium-term:** SSE endpoint for session updates -- simpler, covers 90% of use cases.
3. **Long-term:** WebSocket if bidirectional communication is needed (typing indicators, collaborative editing).

## Passover Notes

- The polling mechanism is implemented in `SandboxPage.tsx` using `useEffect` with `setInterval`.
- It uses `sandboxService.getHistory(namespace, contextId, { limit: 5 })` and deduplicates by message `_index`.
- The poll only runs when `contextId` is set AND `isStreaming` is false.
- Next session should evaluate whether SSE is worth implementing given the polling baseline.
