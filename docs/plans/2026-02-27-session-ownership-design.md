# Session Ownership & Role-Based Access Design

## Problem

Sessions have no user ownership. All sessions in a namespace are visible to all users.
No way to distinguish private from shared sessions, or to prevent users from modifying
each other's sessions.

## Design

### Role-Based Access Matrix

| Role | Sees | Can modify (kill/delete/rename) |
|------|------|--------------------------------|
| `kagenti-admin` | All sessions across all namespaces | All sessions |
| `kagenti-operator` | Own sessions + sessions marked "shared" in their namespace | Only sessions they own |
| `kagenti-viewer` | Only sessions they own | None (read-only) |

### Session Metadata Extension

Add `owner` and `visibility` fields to the existing JSON `metadata` column in the `tasks`
table. No schema migration needed.

```json
{
  "agent_name": "sandbox-legion",
  "owner": "admin",
  "visibility": "private",
  "title": "Weather query session"
}
```

- `owner`: The `preferred_username` from the Keycloak JWT of the user who created the session.
- `visibility`: `"private"` (default) or `"namespace"`. Operators can toggle this per
  session. Private sessions are only visible to the owner and admins. Namespace-shared
  sessions are visible to all operators in the same namespace.

### Backend Changes

**`sandbox.py` — Session list endpoint**:
- Add `user: TokenData = Depends(get_required_user)` dependency.
- Admin: return all sessions (no filter).
- Operator: `WHERE metadata->>'owner' = :username OR metadata->>'visibility' = 'namespace'`.
- Viewer: `WHERE metadata->>'owner' = :username`.

**`sandbox.py` — Session visibility toggle endpoint** (new):
- `PUT /{namespace}/sessions/{context_id}/visibility` — body: `{"visibility": "private"|"namespace"}`.
- Only the session owner or admin can change visibility.
- Operator role required.

**`sandbox.py` — Session mutation endpoints** (kill, delete, rename):
- Admin: allowed on all sessions.
- Operator: only if `metadata.owner == user.username`.
- Viewer: rejected (403).

**`sandbox.py` — Chat endpoints** (send/stream):
- On new session creation (no existing `session_id`), inject `owner: user.username` into
  the A2A message metadata passed to the agent.
- Agent's `DatabaseTaskStore` persists this in the `metadata` column.

**`sandbox.py` — Auth protection**:
- Add `Depends(require_roles(ROLE_VIEWER))` to all GET endpoints.
- Add `Depends(require_roles(ROLE_OPERATOR))` to chat and mutation endpoints.

### Frontend Changes

**`SessionsTablePage.tsx`**:
- Add "Owner" column showing session creator username.
- Disable Kill/Delete/Rename buttons when user doesn't own the session (unless admin).
- Add visibility badge: label showing "Private" or "Shared (team1)".
- Add visibility toggle button (lock/globe icon) for session owner to switch private/shared.

**`SessionSidebar.tsx`**:
- Show owner name next to session title.
- Show lock icon for private sessions, globe icon for shared.
- Grey out actions on sessions owned by others.

**`SandboxPage.tsx` chat area**:
- Show "admin (you)" style label on messages (already implemented in AgentChat).

### Testing

1. **Unit test**: Verify session list filtering per role.
2. **Playwright test**: Login as operator, create session, verify ownership label visible.
3. **Playwright test**: Login as viewer, verify only own sessions visible.
4. **Playwright test**: Operator cannot kill another operator's session (button disabled).

### Non-Goals (YAGNI)

- No per-session sharing controls (invite specific users).
- No real-time session presence (who's currently viewing).
- No session transfer (change owner).
