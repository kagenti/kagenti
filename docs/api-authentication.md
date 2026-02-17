# API Authentication

This guide covers how to authenticate with the Kagenti API using OAuth2 bearer tokens.

## Overview

The Kagenti API uses JWT bearer tokens for authentication. Tokens are issued by Keycloak and must be included in the `Authorization` header of API requests.

**Authentication flow options:**

| Flow | Use Case | Client Type |
|------|----------|-------------|
| Authorization Code + PKCE | Interactive users (UI) | Public |
| Client Credentials Grant | Scripts, services, automation | Confidential |

This guide focuses on **Client Credentials Grant** for programmatic API access.

## Quick Start

> **Prerequisite:** The `kagenti-api-oauth-secret` must exist before running these commands.
> Enable it in your Helm values with `apiOAuthSecret.enabled: true` (see
> [Using the Default Service Account](#using-the-default-service-account)), or
> create your own Keycloak client and Kubernetes secret manually.

```bash
# 1. Get credentials from the Kubernetes secret
export CLIENT_ID=$(kubectl get secret kagenti-api-oauth-secret -n kagenti-system -o jsonpath='{.data.CLIENT_ID}' | base64 -d)
export CLIENT_SECRET=$(kubectl get secret kagenti-api-oauth-secret -n kagenti-system -o jsonpath='{.data.CLIENT_SECRET}' | base64 -d)
export TOKEN_ENDPOINT=$(kubectl get secret kagenti-api-oauth-secret -n kagenti-system -o jsonpath='{.data.TOKEN_ENDPOINT}' | base64 -d)
export KEYCLOAK_URL=$(kubectl get secret kagenti-api-oauth-secret -n kagenti-system -o jsonpath='{.data.KEYCLOAK_URL}' | base64 -d)
export KEYCLOAK_REALM=$(kubectl get secret kagenti-api-oauth-secret -n kagenti-system -o jsonpath='{.data.KEYCLOAK_REALM}' | base64 -d)

# 2. Obtain an access token
TOKEN=$(curl -s -X POST "$TOKEN_ENDPOINT" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET" | jq -r '.access_token')

# 3. Call the API
curl -H "Authorization: Bearer $TOKEN" \
  https://kagenti-api.example.com/api/v1/agents
```

> **Note:** The default `kagenti-api` client is automatically assigned the
> `kagenti-operator` realm role (configurable via `apiOAuthSecret.serviceAccountRole`).
> Tokens obtained with this client's credentials already include this role, so no
> additional user-role mapping is needed for programmatic access.

## Roles and Permissions

Kagenti uses Role-Based Access Control (RBAC) with three roles:

| Role | Permissions | Typical Use |
|------|-------------|-------------|
| `kagenti-viewer` | Read-only access to all resources | Monitoring, dashboards |
| `kagenti-operator` | Read + write access (create, update, delete) | CI/CD, automation |
| `kagenti-admin` | Full access including admin operations | Platform administrators |

**Role hierarchy:** Higher roles inherit permissions from lower roles.
- `kagenti-admin` includes all `kagenti-operator` permissions
- `kagenti-operator` includes all `kagenti-viewer` permissions

### Endpoint Permissions

| Endpoint Pattern | Method | Required Role |
|-----------------|--------|---------------|
| `/api/v1/agents` | GET | `kagenti-viewer` |
| `/api/v1/agents` | POST | `kagenti-operator` |
| `/api/v1/agents/{namespace}/{name}` | DELETE | `kagenti-operator` |
| `/api/v1/tools` | GET | `kagenti-viewer` |
| `/api/v1/tools` | POST | `kagenti-operator` |
| `/api/v1/tools/{namespace}/{name}` | DELETE | `kagenti-operator` |
| `/api/v1/chat/*` | GET | `kagenti-viewer` |
| `/api/v1/chat/*` | POST | `kagenti-operator` |
| `/api/v1/namespaces` | GET | `kagenti-viewer` |
| `/api/v1/config/dashboards` | GET | `kagenti-viewer` |
| `/api/v1/auth/userinfo` | GET | `kagenti-viewer` |

**Public endpoints** (no authentication required):
- `/api/v1/auth/config` - Auth configuration for frontend
- `/api/v1/auth/status` - Auth status check

## Obtaining Tokens

### Using the Default Service Account

Kagenti can provision a default `kagenti-api` service account for testing and development.
This feature is disabled by default; set `enabled: true` to activate it:

```yaml
# charts/kagenti/values.yaml (override)
apiOAuthSecret:
  enabled: true  # default: false
  clientId: kagenti-api
  secretName: kagenti-api-oauth-secret
  serviceAccountRole: kagenti-operator  # role assigned to the client's service account
```

The provisioning job automatically assigns the `serviceAccountRole` (default:
`kagenti-operator`) to the client's service account in Keycloak. Because Client
Credentials Grant tokens are **not tied to an end-user**, the token's roles come
entirely from the client's service account. This means tokens obtained with
these credentials will already carry `kagenti-operator` permissions without any
additional user-role mapping.

**Retrieve credentials:**

```bash
kubectl get secret kagenti-api-oauth-secret -n kagenti-system -o yaml
```

The secret contains:
- `CLIENT_ID` - OAuth2 client ID
- `CLIENT_SECRET` - OAuth2 client secret
- `TOKEN_ENDPOINT` - Keycloak token endpoint URL
- `KEYCLOAK_URL` - Keycloak server URL
- `KEYCLOAK_REALM` - Keycloak realm name

### Token Request

```bash
curl -X POST "$TOKEN_ENDPOINT" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET"
```

**Response:**

```json
{
  "access_token": "<JWT_TOKEN>",
  "expires_in": 300,
  "token_type": "Bearer",
  "scope": "openid profile email"
}
```

### Token Lifetime

Tokens expire after a configurable period. The lifetime is controlled by the
Keycloak realm and client settings (see **Realm Settings > Tokens** in the
Keycloak Admin Console). Your client should:

1. Check the `expires_in` field in the token response
2. Cache tokens and request a new one before expiration
3. Handle 401 responses by refreshing the token

## Using Tokens

Include the token in the `Authorization` header:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://kagenti-api.example.com/api/v1/agents
```

### Python Example

```python
import os
import requests

# Read credentials from environment variables (set via Quick Start above)
TOKEN_ENDPOINT = os.environ["TOKEN_ENDPOINT"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

def get_token(token_endpoint, client_id, client_secret):
    response = requests.post(
        token_endpoint,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    response.raise_for_status()
    return response.json()["access_token"]

def call_api(base_url, token, endpoint):
    response = requests.get(
        f"{base_url}{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()

# Usage
token = get_token(TOKEN_ENDPOINT, CLIENT_ID, CLIENT_SECRET)
agents = call_api("https://kagenti-api.example.com", token, "/api/v1/agents")
```

## Error Responses

### 401 Unauthorized

Returned when authentication fails:

```json
{
  "detail": "Authentication required"
}
```

**Common causes:**
- Missing `Authorization` header
- Expired token
- Invalid token signature
- Token issued by wrong Keycloak realm

### 403 Forbidden

Returned when authenticated but lacking required role:

```json
{
  "detail": "Required role(s): kagenti-operator"
}
```

**Solution:** Request a token with a client that has the required role assigned.

## Creating Additional Service Accounts

For production, create dedicated service accounts per client instead of sharing credentials.

### Via Keycloak Admin Console

1. Navigate to **Clients** > **Create client**
2. Configure:
   - **Client ID:** Your unique client name (e.g., `my-ci-pipeline`)
   - **Client authentication:** ON (confidential)
   - **Service accounts roles:** ON
   - **Standard flow:** OFF
   - **Direct access grants:** OFF
3. Save and go to **Credentials** tab to get the client secret
4. Go to **Service account roles** tab and assign `kagenti-operator` or `kagenti-viewer`

### Via Keycloak Admin API

```bash
# Create the client
curl -X POST "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "my-ci-pipeline",
    "enabled": true,
    "publicClient": false,
    "serviceAccountsEnabled": true,
    "standardFlowEnabled": false,
    "directAccessGrantsEnabled": false
  }'

# Get the internal client ID
CLIENT_UUID=$(curl -s "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients?clientId=my-ci-pipeline" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.[0].id')

# Assign the kagenti-operator role
ROLE=$(curl -s "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/roles/kagenti-operator" \
  -H "Authorization: Bearer $ADMIN_TOKEN")

SERVICE_ACCOUNT_ID=$(curl -s "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients/$CLIENT_UUID/service-account-user" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.id')

curl -X POST "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/users/$SERVICE_ACCOUNT_ID/role-mappings/realm" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "[$ROLE]"
```

## Security Considerations

### Shared Credentials Warning

The default `kagenti-api` client is a **shared credential** intended for testing and development only.

**Production anti-patterns to avoid:**
- Multiple services sharing the same client credentials
- Hardcoding shared credentials in source code
- Using shared credentials across environments

**Production best practices:**
- Create dedicated service accounts per client/service
- Use Kubernetes secrets or a secrets manager
- Rotate credentials regularly
- Audit API access via Keycloak logs

### Credential Storage

- Store credentials in Kubernetes secrets (encrypted at rest)
- Never commit credentials to source control
- Use environment variables or mounted secrets in containers
- Consider external secrets operators for production

### Network Security

- Always use HTTPS for API and token endpoints
- Configure Istio mTLS for service-to-service communication
- Restrict network access to the API using NetworkPolicies

## Troubleshooting

### Token Request Fails

```bash
# Check Keycloak is accessible
curl -s "$KEYCLOAK_URL/realms/$KEYCLOAK_REALM/.well-known/openid-configuration"

# Verify client exists
curl -s "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients?clientId=$CLIENT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### API Returns 401

```bash
# Decode and inspect the token (adds base64url padding before decoding)
echo "$TOKEN" | cut -d. -f2 | tr '_-' '/+' | awk '{while(length%4)$0=$0"=";print}' | base64 -d 2>/dev/null | jq .

# Or use Python (stdlib only, no extra dependencies)
python3 -c "import base64,json,sys; p=sys.argv[1].split('.')[1]; print(json.dumps(json.loads(base64.urlsafe_b64decode(p+'==')),indent=2))" "$TOKEN"

# Or paste the token into https://jwt.io for visual inspection
```

### API Returns 403

```bash
# Check roles in token
echo "$TOKEN" | cut -d. -f2 | tr '_-' '/+' | awk '{while(length%4)$0=$0"=";print}' | base64 -d 2>/dev/null | jq '.realm_access.roles'

# Verify role assignment in Keycloak
curl -s "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/clients/$CLIENT_UUID/service-account-user" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.id' | \
  xargs -I {} curl -s "$KEYCLOAK_URL/admin/realms/$KEYCLOAK_REALM/users/{}/role-mappings/realm" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

## Related Documentation

- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [OAuth 2.0 Client Credentials Grant](https://oauth.net/2/grant-types/client-credentials/)
- [JWT.io](https://jwt.io/) - Token decoder and debugger
