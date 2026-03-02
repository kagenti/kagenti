# SPIFFE Identity Provider Setup

This directory contains the automated setup script for configuring SPIFFE Identity Provider in Keycloak.

## Purpose

When using JWT-SVID authentication (`authBridge.clientAuthType: "federated-jwt"`), Keycloak needs to know how to validate JWT-SVIDs from SPIRE. This script automatically:

1. Waits for SPIRE to be ready
2. Validates SPIRE JWKS has the required "use" field
3. Creates the SPIFFE Identity Provider in Keycloak
4. Configures it to trust the SPIRE trust domain

## Files

- `setup_spiffe_idp.py` - Main setup script
- `requirements.txt` - Python dependencies
- `Dockerfile` - Container image for Kubernetes Job
- `README.md` - This file

## Usage

### Automatic (via Helm)

The setup runs automatically as a Kubernetes Job during `helm install` or `helm upgrade` when SPIRE is enabled:

```bash
helm install kagenti charts/kagenti -f deployments/envs/dev_values.yaml
```

The Job:
- Runs as a Helm hook (`post-install`, `post-upgrade`)
- Waits for SPIRE to be ready before running
- Only runs when `spire.enabled: true`
- Is idempotent (safe to run multiple times)

### Manual (for development/testing)

```bash
cd kagenti/auth/spiffe-idp-setup

# Build the container image
docker build -t spiffe-idp-setup:dev .

# Run locally (requires kubectl access and environment variables)
export KEYCLOAK_BASE_URL="http://keycloak.localtest.me:8080"
export KEYCLOAK_REALM="demo"
export KEYCLOAK_ADMIN_USERNAME="admin"
export KEYCLOAK_ADMIN_PASSWORD="admin"
export SPIFFE_TRUST_DOMAIN="spiffe://localtest.me"
export SPIFFE_BUNDLE_ENDPOINT="http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys"
export SPIFFE_IDP_ALIAS="spire-spiffe"

python3 setup_spiffe_idp.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KEYCLOAK_BASE_URL` | `http://keycloak-service.keycloak.svc:8080` | Keycloak server URL |
| `KEYCLOAK_REALM` | `demo` | Target realm name |
| `KEYCLOAK_ADMIN_USERNAME` | `admin` | Keycloak admin username |
| `KEYCLOAK_ADMIN_PASSWORD` | `admin` | Keycloak admin password |
| `SPIFFE_TRUST_DOMAIN` | `spiffe://localtest.me` | SPIFFE trust domain |
| `SPIFFE_BUNDLE_ENDPOINT` | `http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys` | JWKS URL |
| `SPIFFE_IDP_ALIAS` | `spire-spiffe` | Identity Provider alias in Keycloak |
| `SPIRE_NAMESPACE` | `spire-server` | Namespace where SPIRE is deployed |

## Verification

After the Job runs, verify the SPIFFE Identity Provider was created:

1. Port-forward to Keycloak:
   ```bash
   kubectl port-forward -n keycloak svc/keycloak-service 8080:8080
   ```

2. Open Keycloak Admin Console: http://keycloak.localtest.me:8080/admin

3. Navigate to: `demo` realm → `Identity Providers`

4. Should see: `spire-spiffe` provider with Type: `SPIFFE`

## Troubleshooting

### Job fails with "SPIRE not accessible"

**Cause:** SPIRE OIDC discovery provider is not running or not accessible.

**Solution:**
```bash
# Check SPIRE pods
kubectl get pods -n spire-server

# Should see:
# spire-server-0                                  2/2     Running
# spire-spiffe-oidc-discovery-provider-xxx        1/1     Running

# Check SPIRE logs
kubectl logs -n spire-server deployment/spire-spiffe-oidc-discovery-provider
```

### Job fails with "JWKS keys missing 'use' field"

**Cause:** SPIRE OIDC discovery provider not configured with `set_key_use: true`.

**Solution:**
```bash
# From kagenti-extensions repo:
./spiffe-keycloak/patch_spire_config.sh
```

### "Identity Provider already exists" error

This is normal and expected - the script is idempotent and will update the existing IdP if needed.

## Related Documentation

- [SPIFFE_KEYCLOAK_SETUP.md](../../../../../../../kagenti-extensions/SPIFFE_KEYCLOAK_SETUP.md) - Full setup and testing guide
- [CONFIGURATION_CHANGES.md](../../../../../../../kagenti-extensions/spiffe-keycloak/CONFIGURATION_CHANGES.md) - Configuration changes summary
- [keycloak_federated_client.py](../../../../../../../kagenti-extensions/spiffe-keycloak/keycloak_federated_client.py) - Reference implementation
