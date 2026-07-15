# Why SPIFFE-Based Keycloak Authentication

This document explains why Kagenti uses SPIFFE JWT-SVIDs for Keycloak authentication rather than
the alternatives that were considered along the way — in particular Dynamic Client Registration
(DCR), which had a strong early case.

---

## The Problem

From the beginning, Kagenti required two classes of long-lived credentials:

**Admin credentials** — Keycloak admin username and password, stored as Kubernetes Secrets in
agent namespaces so the client-registration sidecar (and later the operator) could register new
OAuth clients on behalf of each deployed agent. Full realm-admin access: create/delete users,
clients, realms, and roles. A single compromised agent namespace meant full Keycloak compromise.

**Client secrets** — Per-agent OAuth2 client secrets, provisioned at deploy time and stored as
Kubernetes Secrets mounted into each agent pod. Long-lived, required manual rotation, and present
in every namespace that ran an agent.

Issues [#159](https://github.com/kagenti/kagenti/issues/159) and
[#1426](https://github.com/kagenti/kagenti/issues/1426) tracked the credential-sprawl problem
as it evolved. By mid-2026 it was described as a productization blocker on OpenShift:

> *"A single compromised namespace could mean full realm compromise and the long-lived secrets
> demand manual rotation."* — #1426

The goal, stated in [#2174](https://github.com/kagenti/kagenti/issues/2174), became eliminating
**all** provisioned credentials in favor of workload identity.

---

## What Was Considered

### Option 1: Dynamic Client Registration (DCR)

[Issue #1421](https://github.com/kagenti/kagenti/issues/1421) proposed using Keycloak's
Dynamic Client Registration endpoint
(`POST /realms/{realm}/clients-registrations/default`) with the operator's SPIFFE JWT-SVID as
a bearer token. The operator would present its workload identity to self-register agent OAuth
clients, eliminating the need for admin credentials.

**Why it was attractive:**
- Standard OAuth 2.0 protocol (RFC 7591) — not Keycloak-specific
- DCR endpoints can be scoped with initial access tokens, limiting blast radius
- No permanent admin credentials in the cluster

**Why it was dropped:**

The critical unknown was whether Keycloak's DCR endpoint would accept a SPIFFE JWT-SVID as the
bearer token at all — this required validation. But the bigger problem was that **DCR still
returns a client secret**. Using DCR to register agents would eliminate admin credentials from
the operator but leave per-agent client secrets in every pod. It solves half the problem.

The other half — eliminating client secrets — requires the agent to authenticate to Keycloak
using its own SPIFFE identity as a client credential (not a client secret). Once you need that
capability, the operator can use the same mechanism to authenticate to the Admin API directly,
making the DCR endpoint redundant. DCR became a middle step that added complexity without
reaching the goal.

**The token refresh problem:** DCR-issued registrations carry short-lived registration access
tokens. To keep a DCR-registered client alive, the operator would need to refresh these tokens
on a schedule. That requires building and operating a new component — a token refresh daemon
or a periodic reconcile loop with state management — purely to support the DCR path. The
SPIFFE approach avoids this entirely: JWT-SVIDs are short-lived by design and renewed
automatically by SPIRE; no separate refresh component is needed.

**Resolution:** Issue #1421 was closed in July 2026:
> *"This has been solved via kagenti/kagenti#2141 and kagenti/kagenti-operator#473 with
> SPIFFE-based auth instead of SPIFFE-based DCR."*

---

### Option 2: mTLS for Agent-to-Agent Traffic

[Issue #1568](https://github.com/kagenti/kagenti/issues/1568) proposed using mutual TLS with
SPIFFE SVIDs (X.509) for agent-to-agent calls, with a shared JWT audience for user-to-agent
traffic. Under this model the inbound `jwt-validation` plugin would verify the caller's mTLS
certificate rather than a bearer token, removing the per-agent Keycloak audience requirement.

**Why it is complementary, not a replacement:** mTLS covers transport-level authentication
between workloads but does not address how the operator authenticates to Keycloak to register
clients, or how agents exchange tokens for outbound A2A calls. The two approaches can coexist:
mTLS for agent-to-agent, SPIFFE JWT-SVID exchange for operator-to-Keycloak and agent-to-external.

**Status:** The IdP portability work in #1568 is ongoing. mTLS as the primary
agent-to-agent mechanism remains an open design question.

---

### Option 3: RFC 8693 Token Exchange

Issue #1568 explicitly ruled out RFC 8693 token exchange as the primary portability story:

> *"It reintroduces per-agent client registration."*

Token exchange (trading one token for a scoped token for a specific audience) still requires
every target service to be registered as a Keycloak client with an audience scope. This is
what Kagenti already does, and it is the registration burden that we are trying to reduce, not
the token exchange step itself.

---

### Option 4: Vault for Static Secrets

[Issue #1478](https://github.com/kagenti/kagenti/issues/1478) proposed a complementary
`vault-fetcher` init container pattern for applications that cannot use OAuth token exchange
(legacy applications needing static API keys, database passwords, etc.). This pattern also
uses SPIFFE JWT-SVIDs to authenticate to Vault — the same identity root as the rest of the
stack.

This is not an alternative to SPIFFE-based Keycloak auth; it is a parallel solution for a
different class of credentials. The two coexist.

---

## The Chosen Approach: SPIFFE JWT-SVID Authentication

The implementation that landed uses SPIFFE JWT-SVIDs as client assertions in the OAuth 2.0
client credentials grant (RFC 7523). The JWT-SVID is presented as:

```
grant_type=client_credentials
client_id=spiffe://trust-domain/ns/namespace/sa/service-account
client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-spiffe
client_assertion=<JWT-SVID>
```

Keycloak validates the assertion using the SPIRE OIDC Discovery Provider's JWKS endpoint.

**What it eliminates:**

| Credential | Old approach | SPIFFE approach |
|---|---|---|
| Operator → Keycloak | Admin username + password | JWT-SVID (5-min TTL, auto-renewed) |
| Agent → Keycloak | Per-agent `client_secret` | JWT-SVID (5-min TTL, auto-renewed) |
| Admin secret in cluster | `keycloak-admin-secret` in `kagenti-system` | Only needed for bootstrap Job |
| Per-agent credential Secrets | One Secret per agent namespace | Secret contains only `client-id.txt` |

**Why it wins over DCR:**

1. **Eliminates both credential classes.** DCR eliminates admin credentials but preserves client
   secrets. SPIFFE auth eliminates both.

2. **No refresh component needed.** SPIRE renews JWT-SVIDs automatically. The operator and
   agents always have a fresh, valid identity — zero operational overhead.

3. **Least-privilege by construction.** The operator's SPIFFE ID is granted only
   `manage-clients` on the Keycloak realm (via the bootstrap Job), not full admin. No
   credential grants more access than the task requires.

4. **Scoped to workload identity.** Each agent's SPIFFE ID encodes its namespace and service
   account. Keycloak validates the JWT-SVID signature against SPIRE's JWKS. A compromised pod
   can only authenticate as itself.

5. **No secret material in the cluster.** There is nothing to rotate, sync, or leak. The only
   persistent artifact is the Keycloak client registration (a public record) and `client-id.txt`
   (the SPIFFE ID itself, not a secret).

---

## Remaining Work

**SPIFFE auth is not yet the default.** It is currently opt-in (`--enable-spiffe-auth`) because
making it the default requires SPIRE to be present, and not all deployments run SPIRE.

**`client-id.txt` still exists** in the mounted credential Secret. In SPIFFE mode its value is
the agent's SPIFFE ID (non-sensitive), written so the AuthBridge inbound `jwt-validation` plugin
has the expected audience for validating incoming bearer tokens. `client-secret.txt` is written
as an empty file. Neither contains secret material.

**Phase 4 of #1426** — using federated SPIFFE client auth as the formal OAuth client authenticator
type at the Keycloak protocol level — is blocked on RHBK shipping Keycloak 26.6.x. The current
implementation achieves the same security outcome through the custom `jwt-spiffe` client
authenticator in the kagenti-extensions Keycloak SPI, which is already deployed.

**IdP portability (#1568)** — the agent-to-agent inbound validation model is Keycloak-specific
today. Replacing it with mTLS or an IdP-agnostic JWT check is a separate workstream.

---

## References

| Issue | Title |
|---|---|
| [#159](https://github.com/kagenti/kagenti/issues/159) | Duplicated Keycloak credentials across namespaces |
| [#1337](https://github.com/kagenti/kagenti/issues/1337) | Stale keycloak-admin-secret after RHBK upgrade |
| [#1421](https://github.com/kagenti/kagenti/issues/1421) | Eliminate admin credentials using SPIFFE-based DCR |
| [#1426](https://github.com/kagenti/kagenti/issues/1426) | Epic: Eliminate Keycloak admin credentials and client secrets |
| [#1478](https://github.com/kagenti/kagenti/issues/1478) | Epic: Identity-secured secret store for legacy applications |
| [#1568](https://github.com/kagenti/kagenti/issues/1568) | Epic: IdP portability and split trust model |
| [#2174](https://github.com/kagenti/kagenti/issues/2174) | Make SPIFFE-based auth the default |
