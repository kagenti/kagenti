---
draft: true       # excluded from https://www.rossoctl.dev/
---

# API Bearer Token Authentication Design

**Date:** 2025-02-05
**Status:** Draft

## Overview

Protect the Rossoctl backend API with JWT bearer token authentication using Keycloak as the identity provider. Enable external clients (scripts, services) to authenticate via Client Credentials Grant.

### Goals

- Secure all `/api/v1/*` endpoints with JWT bearer token validation, except explicitly public endpoints (`/api/v1/auth/config`, `/api/v1/auth/status`) needed for auth bootstrapping
- Support Role-Based Access Control (RBAC) with three roles: `rossoctl-viewer`, `rossoctl-operator`, `rossoctl-admin`
- Enable external clients to authenticate via Client Credentials Grant
- Automatically provision a default service account in Keycloak
- Maintain dev-friendly experience with mock auth when `ENABLE_AUTH=false`

### Out of Scope

- CLI tooling (users use curl/HTTP clients)
- Namespace-scoped access control
- Device Authorization Grant flow

### Authentication Flows

- **UI (existing):** Authorization Code + PKCE - unchanged
- **External clients (new):** Client Credentials Grant

## Role Definitions & Permissions

### Roles

Defined in Keycloak, embedded in JWT `realm_access.roles`:

| Role | Description |
|------|-------------|
| `rossoctl-viewer` | Read-only access to resources |
| `rossoctl-operator` | Full CRUD on agents and tools |
| `rossoctl-admin` | All permissions including admin operations |

**Role Hierarchy:** `rossoctl-admin` inherits `rossoctl-operator` inherits `rossoctl-viewer`

### Endpoint Permissions Matrix

| Endpoint Pattern | `rossoctl-viewer` | `rossoctl-operator` | `rossoctl-admin` |
|-----------------|------------------|--------------------|-----------------|
| `GET /api/v1/agents` | ✓ | ✓ | ✓ |
| `GET /api/v1/agents/{namespace}/{name}` | ✓ | ✓ | ✓ |
| `GET /api/v1/agents/{namespace}/{name}/route-status` | ✓ | ✓ | ✓ |
| `GET /api/v1/agents/{namespace}/{name}/shipwright-build` | ✓ | ✓ | ✓ |
| `GET /api/v1/agents/build-strategies` | ✓ | ✓ | ✓ |
| `POST /api/v1/agents` | | ✓ | ✓ |
| `POST /api/v1/agents/{namespace}/{name}/shipwright-buildrun` | | ✓ | ✓ |
| `POST /api/v1/agents/{namespace}/{name}/finalize-shipwright-build` | | ✓ | ✓ |
| `DELETE /api/v1/agents/{namespace}/{name}` | | ✓ | ✓ |
| `GET /api/v1/tools` | ✓ | ✓ | ✓ |
| `GET /api/v1/tools/{namespace}/{name}` | ✓ | ✓ | ✓ |
| `GET /api/v1/tools/{namespace}/{name}/route-status` | ✓ | ✓ | ✓ |
| `POST /api/v1/tools` | | ✓ | ✓ |
| `POST /api/v1/tools/{namespace}/{name}/shipwright-buildrun` | | ✓ | ✓ |
| `POST /api/v1/tools/{namespace}/{name}/finalize-shipwright-build` | | ✓ | ✓ |
| `POST /api/v1/tools/{namespace}/{name}/connect` | | ✓ | ✓ |
| `POST /api/v1/tools/{namespace}/{name}/invoke` | | ✓ | ✓ |
| `DELETE /api/v1/tools/{namespace}/{name}` | | ✓ | ✓ |
| `GET /api/v1/namespaces` | ✓ | ✓ | ✓ |
| `GET /api/v1/chat/{namespace}/{name}/agent-card` | ✓ | ✓ | ✓ |
| `POST /api/v1/chat/{namespace}/{name}/send` | | ✓ | ✓ |
| `POST /api/v1/chat/{namespace}/{name}/stream` | | ✓ | ✓ |
| `GET /api/v1/config/dashboards` | ✓ | ✓ | ✓ |
| `GET /api/v1/auth/config` | public | public | public |
| `GET /api/v1/auth/status` | public | public | public |
| `GET /api/v1/auth/userinfo` | ✓ | ✓ | ✓ |
| `GET /api/v1/auth/me` | optional | optional | optional |

**Notes:**
- **public**: No authentication required
- **optional**: Works with or without authentication (returns guest info if unauthenticated)

## Backend Implementation

### Changes to `rossoctl/backend/app/core/auth.py`

1. **Define role constants:**

```python
ROLE_VIEWER = "rossoctl-viewer"
ROLE_OPERATOR = "rossoctl-operator"
ROLE_ADMIN = "rossoctl-admin"

ROLE_HIERARCHY = {
    ROLE_ADMIN: [ROLE_OPERATOR, ROLE_VIEWER],
    ROLE_OPERATOR: [ROLE_VIEWER],
    ROLE_VIEWER: [],
}
```

2. **Update `require_roles()` dependency** to support role hierarchy - if user has `admin`, they automatically satisfy `operator` or `viewer` requirements.

3. **Mock user in dev mode** gets `rossoctl-admin` role.

### Changes to Route Files

Each router file gets auth dependencies added:

- **`routers/agents.py`:**
  - GET endpoints → `require_roles(ROLE_VIEWER)`
  - POST/DELETE → `require_roles(ROLE_OPERATOR)`

- **`routers/tools.py`:** Same pattern as agents

- **`routers/chat.py`:** All endpoints → `require_roles(ROLE_OPERATOR)`

- **`routers/namespaces.py`:** GET → `require_roles(ROLE_VIEWER)`

- **`routers/config.py`:** GET → `require_roles(ROLE_VIEWER)`

- **`routers/auth.py`:** `/auth/config` stays public, others require `ROLE_VIEWER`

## Keycloak Configuration

### New Kubernetes Job: `rossoctl-api-oauth-secret`

Creates a confidential client for API access:

**Client Configuration:**

- **Client ID:** `rossoctl-api`
- **Client Type:** Confidential (has a secret)
- **Authentication Flow:** Client Credentials Grant enabled
- **Service Account:** Enabled (required for Client Credentials)
- **Default Role:** `rossoctl-operator` assigned to the service account

### Secret Created

`rossoctl-api-oauth-secret` in `rossoctl-system` namespace:

| Key | Value |
|-----|-------|
| `CLIENT_ID` | `rossoctl-api` |
| `CLIENT_SECRET` | Generated by Keycloak |
| `TOKEN_ENDPOINT` | `http://keycloak-service.keycloak:8080/realms/{realm}/protocol/openid-connect/token` |

### Keycloak Realm Roles

The job ensures these roles exist in the realm:

- `rossoctl-viewer`
- `rossoctl-operator`
- `rossoctl-admin`

### Helm Values Addition

Following the existing pattern of top-level OAuth secret configuration (like `uiOAuthSecret` and `agentOAuthSecret`):

```yaml
# ------------------------------------------------------------------
#  API OAuth Secret Creator Configuration
# ------------------------------------------------------------------
apiOAuthSecret:
  enabled: true
  image: ghcr.io/rossoctl/rossoctl/api-oauth-secret
  tag: latest
  clientId: rossoctl-api
  defaultRole: rossoctl-operator
  # When true, mount the in-cluster serviceaccount CA
  useServiceAccountCA: true
```

## Token Usage for External Clients

### Default Service Account (`rossoctl-api`)

The auto-provisioned `rossoctl-api` client is a shared credential intended for **testing and development only**.

> **Warning:** Using a shared credential in production is an anti-pattern. It prevents audit traceability (you cannot identify which client made a request), complicates credential rotation, and violates least-privilege principles. For production deployments, each external client (service, script, automation) should have its own Keycloak service account client with appropriate roles. See documentation for creating additional service account clients in Keycloak.

### Getting a Token

External clients obtain tokens by POSTing to the Keycloak token endpoint:

```bash
# Using the default test credential (development/testing only)
curl -X POST "http://keycloak.localtest.me:8080/realms/rossoctl/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=rossoctl-api" \
  -d "client_secret=<secret-from-k8s-secret>"
```

**Response:**

```json
{
  "access_token": "<JWT_ACCESS_TOKEN>",
  "expires_in": 300,
  "token_type": "Bearer"
}
```

### Using the Token

```bash
curl "http://rossoctl-ui.localtest.me:8080/api/v1/agents" \
  -H "Authorization: Bearer <JWT_ACCESS_TOKEN>"
```

### Token Lifetime

- Default: 5 minutes (Keycloak default)
- Clients should refresh before expiry or request a new token

### Retrieving Credentials from Kubernetes

```bash
kubectl get secret rossoctl-api-oauth-secret -n rossoctl-system \
  -o jsonpath='{.data.CLIENT_SECRET}' | base64 -d
```

## File Changes Summary

### Files to Modify

| File | Changes |
|------|---------|
| `rossoctl/backend/app/core/auth.py` | Add role constants, role hierarchy, update `require_roles()` |
| `rossoctl/backend/app/routers/agents.py` | Add auth dependencies to all endpoints |
| `rossoctl/backend/app/routers/tools.py` | Add auth dependencies to all endpoints |
| `rossoctl/backend/app/routers/chat.py` | Add auth dependencies to all endpoints |
| `rossoctl/backend/app/routers/namespaces.py` | Add auth dependencies to all endpoints |
| `rossoctl/backend/app/routers/config.py` | Add auth dependencies to all endpoints |
| `rossoctl/backend/app/routers/auth.py` | Ensure `/auth/config` stays public |

### Files to Create

| File | Purpose |
|------|---------|
| `rossoctl/auth/api-oauth-secret/register_api_client.py` | Script to register API client in Keycloak |
| `rossoctl/auth/api-oauth-secret/Dockerfile` | Container for the registration job |
| `charts/rossoctl/templates/api-oauth-secret-job.yaml` | Kubernetes Job for client registration |
| `docs/api-authentication.md` | Documentation for external API access |

### Files to Update

| File | Changes |
|------|---------|
| `charts/rossoctl/values.yaml` | Add top-level `apiOAuthSecret` config section |
| `charts/rossoctl/templates/keycloak-realm-roles.yaml` | Ensure realm roles are created (or add to existing job) |

## Error Responses

### Standard Error Format

All auth errors return JSON with consistent structure:

```json
{
  "detail": "Error message here"
}
```

### Error Scenarios (Current Backend Implementation)

These are the actual error responses from `rossoctl/backend/app/core/auth.py`:

| Scenario | HTTP Status | Detail Message | Headers |
|----------|-------------|----------------|---------|
| No Authorization header | 401 | `Authentication required` | `WWW-Authenticate: Bearer` |
| Token missing key ID | 401 | `Token missing key ID` | |
| Token signing key not found | 401 | `Token signing key not found` | |
| JWT validation error (expired, malformed, etc.) | 401 | `Invalid token: <error details>` | |
| Token key error | 401 | `Token key error` | |
| Token missing required role | 403 | `Required role(s): rossoctl-operator` | |

**Note:** Keycloak connectivity errors during JWKS fetch will raise an unhandled exception. Consider adding explicit 503 handling in the implementation if graceful degradation is desired.
