# OTEL Collector Ingress CA Certificate Setup

## Problem

The OTEL collector uses OAuth2 client credentials flow to authenticate with MLflow.
The token endpoint URL is the external Keycloak URL (https://keycloak-keycloak.apps...).
This URL uses the OpenShift ingress controller's certificate, which is NOT in the
standard trusted CA bundle (`config-trusted-cabundle`).

**Error:**
```
oauth2: cannot fetch token: oauth2/oidc: failed to get token:
Post "https://keycloak-keycloak.apps.../token":
tls: failed to verify certificate: x509: certificate signed by unknown authority
```

## Root Cause

OpenShift has several CA bundles:
1. **`config-trusted-cabundle`** - Mozilla CA bundle (public CAs)
2. **`config-service-cabundle`** - OpenShift service CA (internal service-to-service)
3. **`default-ingress-cert`** (in `openshift-config-managed`) - Ingress controller CA

The ingress CA is NOT auto-injected into pods. It must be explicitly copied or mounted.

## Solution

Create a Helm pre-install Job that copies the ingress CA certificate from
`openshift-config-managed/default-ingress-cert` to `kagenti-system/ingress-ca-bundle`.

### Implementation Steps

1. **Create RBAC for cross-namespace ConfigMap access**
   - ServiceAccount, Role, RoleBinding to read from `openshift-config-managed`

2. **Create pre-install Job**
   - Runs `kubectl` to copy the ConfigMap
   - Uses Helm hook `pre-install,pre-upgrade`

3. **Mount the ingress CA in OTEL collector**
   - Add volume mount for the copied ConfigMap
   - Update oauth2client TLS config to use ingress CA

4. **Update skill documentation**
   - Document when to use which CA bundle

### Files to Create/Modify

- `charts/kagenti-deps/templates/otel-ingress-ca-job.yaml` (new)
- `charts/kagenti-deps/templates/otel-collector.yaml` (modify TLS config)
- `.claude/skills/openshift/certificates/SKILL.md` (new skill)

## Alternative Approaches Considered

### A. Use internal Keycloak URL
**Rejected**: JWT issuer would be internal URL, but MLflow's OIDC_DISCOVERY_URL
uses external URL. Token validation would fail due to issuer mismatch.

### B. Add ingress CA to trusted-cabundle
**Rejected**: Would require modifying cluster-wide config, not portable.

### C. Use insecure_skip_verify
**Rejected**: Disables TLS verification, security risk.

## Testing

1. Deploy updated Helm chart
2. Verify OTEL collector pod starts successfully
3. Verify oauth2client can obtain tokens from Keycloak
4. Verify traces flow to MLflow (run E2E tests)
