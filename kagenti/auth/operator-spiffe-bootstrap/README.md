# Operator SPIFFE Bootstrap

Python-based bootstrap job that configures Keycloak to enable operator SPIFFE authentication via JWT-SVID.

## Purpose

This bootstrap job runs as a Helm post-install/post-upgrade hook to automatically configure Keycloak for operator JWT-SVID authentication, eliminating the need for admin credentials.

## What It Does

1. **Creates SPIFFE Identity Provider** in Keycloak if not exists
   - Alias: `spire-spiffe`
   - JWKS URL: SPIRE OIDC Discovery Provider
   - Validates JWT-SVID signatures

2. **Creates Operator Client** with federated-jwt authentication
   - Client ID: Operator's SPIFFE ID (e.g., `spiffe://localtest.me/ns/kagenti-operator-system/sa/controller-manager`)
   - Client Authenticator: `federated-jwt`
   - Links to SPIFFE IdP for JWT validation

3. **Assigns manage-clients Role**
   - Scoped permission (not full admin)
   - Allows operator to register agent clients

## Usage

Automatically deployed when `kagentiOperator.spiffeAuth.enabled=true` in Helm values:

```bash
ENABLE_OPERATOR_SPIFFE_AUTH=true ./.github/scripts/local-setup/kind-full-test.sh
```

## Configuration

Environment variables (set by Helm template):

| Variable | Default | Description |
|----------|---------|-------------|
| `KEYCLOAK_URL` | `http://keycloak-service.keycloak.svc:8080` | Keycloak server URL |
| `KEYCLOAK_REALM` | `kagenti` | Target realm |
| `KEYCLOAK_ADMIN_SECRET_NAME` | `keycloak-initial-admin` | Secret with admin credentials |
| `KEYCLOAK_ADMIN_SECRET_NAMESPACE` | `keycloak` | Namespace containing secret |
| `SPIFFE_IDP_ALIAS` | `spire-spiffe` | SPIFFE IdP alias |
| `SPIRE_OIDC_URL` | `http://spire-spiffe-oidc-discovery-provider...` | SPIRE OIDC Discovery URL |
| `OPERATOR_CLIENT_ID` | (auto-generated) | Operator's SPIFFE ID |
| `OPERATOR_NAMESPACE` | `kagenti-operator-system` | Operator namespace |

## Dependencies

- `requests==2.32.3` - HTTP client for Keycloak Admin API
- `kubernetes==32.0.0` - Kubernetes API for reading secrets
- `urllib3==2.3.0` - HTTP library (transitive)

## Image

Built and published to:
```
ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:v0.1.0
```

## Verification

Check bootstrap job logs:
```bash
kubectl logs -n kagenti-operator-system job/kagenti-operator-client-bootstrap
```

Expected output:
```
============================================================
Operator SPIFFE Authentication Bootstrap
============================================================
1. Authenticating to Keycloak...
   ✓ Authenticated successfully
2. Ensuring SPIFFE Identity Provider exists...
   ✓ SPIFFE Identity Provider 'spire-spiffe' already exists
3. Ensuring operator client exists...
   ✓ Operator client already exists (UUID: ...)
4. Assigning manage-clients role to operator service account...
   ✓ manage-clients role assigned
============================================================
✓ Bootstrap completed successfully
============================================================
```

## Security

- Runs as non-root user (UID 1001)
- Read-only root filesystem
- Drops all capabilities
- Uses Kubernetes RBAC to read admin secret
- Admin credentials only used during bootstrap (not stored)
- Resulting operator client uses JWT-SVID (no secrets)

## Related

- **kagenti-operator#349**: Core operator SPIFFE authentication implementation
- **kagenti/kagenti#1837**: Platform integration and automation
- **kagenti-operator#410**: Epic issue
