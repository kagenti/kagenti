---
sidebar_label: Authentication
sidebar_position: 3
---

# Authentication

Workload identity answers *which workload*. Authentication answers *which user or client*, and what role they hold. Rosso uses [Keycloak](https://www.keycloak.org/) as its OAuth2/OIDC provider for user login, client registration, and token issuance.

## Users and single sign-on

Users authenticate through Keycloak (OIDC). That login establishes the user identity that flows through the system — into agents and, via [token exchange](token-exchange-and-authbridge.md), all the way to tools.

## Clients are registered automatically

When you deploy an agent or tool, the operator's client-registration controller registers it as a Keycloak OAuth client. You don't hand-manage client secrets for every workload.

## API access and roles

The platform API uses OAuth2 bearer tokens and a small set of roles:

| Role | Can do |
|------|--------|
| `rosso-viewer` | Read-only: list and inspect agents, tools, traces |
| `rosso-operator` | Deploy and manage agents and tools |
| `rosso-admin` | Full control, including platform configuration |

```bash
# Authenticate the CLI (opens Keycloak login)
rossoctl login

# Calls now carry your bearer token and role
rossoctl agent list --namespace team1
```

:::info End-user access levels
Beyond platform roles, end users of an agent can be granted Full, Partial, or Read-Only access to a
given agent's capabilities. Model these against your own org's needs.
:::

:::note For contributors
Confirm role names and the API auth flow against `kagenti/docs/api-authentication.md`, and the client
auto-registration behavior against `kagenti/docs/identity-guide.md`. The `auth:keycloak-confidential-client`
skill documents confidential-client setup.
:::
