# Operator SPIFFE Bootstrap

Python-based bootstrap job that configures Keycloak to enable operator SPIFFE authentication via JWT-SVID.

## Purpose

This bootstrap job runs as a Helm post-install/post-upgrade hook to configure the **operator's client** in Keycloak for JWT-SVID authentication. This allows the operator to authenticate using its SPIRE-issued identity instead of admin credentials when registering agent clients.

**Prerequisites**: SPIRE must already be installed (via platform setup). This job only configures Keycloak, not SPIRE.

## What It Does

This bootstrap job is **ONLY** responsible for configuring the **operator client** in Keycloak, not SPIRE itself. SPIRE must already be installed via the platform's SPIRE setup.

1. **Ensures SPIFFE Identity Provider exists** in Keycloak
   - Should already exist from SPIRE installation
   - Creates it if missing (fallback)
   - Alias: `spire-spiffe`
   - JWKS URL: SPIRE OIDC Discovery Provider
   - Validates JWT-SVID signatures

2. **Creates Operator Client** with federated-jwt authentication
   - Client ID is the operator's SPIFFE ID, **derived** from:
     - Trust domain (e.g., `localtest.me`)
     - Namespace (e.g., `kagenti-operator-system`)
     - ServiceAccount name (e.g., `controller-manager`)
   - Format: `spiffe://<trust-domain>/ns/<namespace>/sa/<service-account>`
   - Example: `spiffe://localtest.me/ns/kagenti-operator-system/sa/controller-manager`
   - Client Authenticator: `federated-jwt`
   - Links to SPIFFE IdP for JWT-SVID validation

3. **Assigns manage-clients Role** to operator's service account
   - Scoped permission (not full admin)
   - Allows operator to register agent clients dynamically

## Usage

Automatically deployed when `kagentiOperator.spiffeAuth.enabled=true` in Helm values.

**Via shell scripts** (sets Helm value):
```bash
# Environment variable → Helm value mapping:
# ENABLE_OPERATOR_SPIFFE_AUTH=true → kagentiOperator.spiffeAuth.enabled=true
ENABLE_OPERATOR_SPIFFE_AUTH=true ./.github/scripts/local-setup/kind-full-test.sh
```

**Directly with Helm**:
```bash
helm install kagenti charts/kagenti --set kagentiOperator.spiffeAuth.enabled=true
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
| `SPIFFE_TRUST_DOMAIN` | `localtest.me` | SPIFFE trust domain (required) |
| `OPERATOR_NAMESPACE` | `kagenti-operator-system` | Operator namespace (required) |
| `OPERATOR_SERVICE_ACCOUNT` | `controller-manager` | Operator ServiceAccount (required) |

The operator's SPIFFE ID is **derived** from these three components:
```
spiffe://<SPIFFE_TRUST_DOMAIN>/ns/<OPERATOR_NAMESPACE>/sa/<OPERATOR_SERVICE_ACCOUNT>
```
This matches the SPIFFE ID that SPIRE will issue to the operator pod.

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
