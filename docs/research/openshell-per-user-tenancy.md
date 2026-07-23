---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Per-User Sandbox Ownership on a Shared OpenShell Gateway

**Status:** Implemented (v0.0.56-rc.2)
**Issue:** [#1976](https://github.com/rossoctl/rossoctl/issues/1976)
**Relates to:** `docs/research/openshell-mvp.md` §5.2, §10

## Problem

The MVP (`openshell-mvp.md`) achieves isolation with namespace-per-team gateways.
Within a team, all `openshell-user` members share every sandbox (§5.2). Pushing
that model to per-user isolation would require a namespace (or gateway stack) per
user, which doesn't scale:

- Namespace churn, RBAC/quota fragmentation, controller load
- Gateway-per-user multiplies pods, certs, and DBs
- K8s namespaces are a coarse blast-radius/quota boundary, not a per-user partition

## Solution: Owner-Label Approach

A single shared gateway enforces ownership at the application layer via a reserved,
server-set label: `openshell.ai/owner = <identity.subject>`.

### How it works

| Operation | Behavior |
|-----------|----------|
| **Create** | Server reads `Principal::User` from request extensions, stamps `openshell.ai/owner = identity.subject`. Client-supplied `openshell.ai/` keys are stripped. |
| **List** | Server ANDs `openshell.ai/owner=<caller>` into the label selector before querying the store. |
| **Get/Delete/Connect/Exec** | After fetching by name/ID, returns `PermissionDenied` if owner != caller. |
| **Admin bypass** | Callers with role `openshell-admin` skip the owner filter and operate on all sandboxes. |
| **OIDC disabled** | Ownership skipped for `Anonymous` principal (backward-compatible local dev). |

### Why labels (not a dedicated column)

- Reuses `validate_label_selector`, Postgres JSONB `@>` filter, and SQLite in-memory filter
- Zero proto changes, zero DB migrations for v1
- A dedicated indexed `owner` column is the tidy long-term option (see Scaling below)

### Security properties

- **Server-set, never client input.** The `openshell.ai/` prefix is reserved; any
  client-supplied keys under it are stripped on CreateSandbox.
- **Verified identity.** Owner is extracted from the `Principal` inserted by OIDC
  middleware after JWT validation — not from any request field.
- **Defense-in-depth, not a substitute.** Owner filtering is a control-plane
  visibility/authz control. Pod-level isolation (separate SA, NetworkPolicy,
  SPIFFE, supervisor Landlock/seccomp/netns) remains the data-plane boundary.

### Label-value charset

The gateway validates label values per K8s rules (alnum, `-`, `_`, `.`, <=63 chars).
Keycloak's `sub` is a UUID and satisfies this. Deployments with email-style subjects
(`alice@corp`) will fail validation — the Rossoctl Keycloak realm must use UUID `sub`
(the default). A sanitization helper exists in `auth/ownership.rs` for future
non-UUID deployments.

## Deployment model

```
┌─────────────────────────────────────────────────────┐
│  Namespace: team1  (team boundary / quota scope)    │
│                                                     │
│  ┌───────────────────────────────────────────────┐  │
│  │  Shared Gateway (OIDC audience = team1)       │  │
│  │  - Accepts tokens from alice, bob, ...        │  │
│  │  - Stamps openshell.ai/owner per sandbox      │  │
│  │  - Filters list/get/delete by owner           │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │ alice's  │  │ alice's  │  │  bob's   │         │
│  │ sandbox1 │  │ sandbox2 │  │ sandbox1 │         │
│  │ owner=   │  │ owner=   │  │ owner=   │         │
│  │ <alice>  │  │ <alice>  │  │  <bob>   │         │
│  └──────────┘  └──────────┘  └──────────┘         │
└─────────────────────────────────────────────────────┘
```

The namespace remains a **team/quota** boundary. Ownership within the namespace
is enforced by the gateway's application logic.

## E2E validation

Test file: `rossoctl/tests/e2e/openshell/test_T4_4_per_user_isolation.py`

Covers:
- Create stamps owner from verified identity
- Client-supplied owner stripped (anti-spoofing)
- List filtered to caller's sandboxes
- Cross-user get/delete → PermissionDenied
- Admin bypass (openshell-admin role)

## Scaling follow-ups (not blocking v1)

1. **Shared Postgres store** — enables server-side owner filtering at scale and
   gateway HA. Add a JSONB index on `(object_type, labels->>'openshell.ai/owner')`.
2. **Dedicated owner column** — promote from label to indexed proto field + migration
   once the label approach is proven at scale.
3. **Provider/credential ownership** — out of scope for this issue (sandboxes only).

## References

- [openshell-mvp.md](openshell-mvp.md) — §5.2 (no per-user ownership), §10 (deferred)
- [openshell-fork-analysis.md](openshell-fork-analysis.md) — fork branches, store architecture
- Gateway source: `rossoctl/openshell` `crates/openshell-server/src/auth/ownership.rs`
