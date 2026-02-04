# OpenShift Certificate Bundles for Pod TLS Verification

## Overview

OpenShift has multiple CA certificate bundles for different purposes. This skill
documents when to use each bundle and how to properly configure TLS verification
for pods that need to communicate with HTTPS endpoints.

**Note:** The OpenShift Router handles both Routes and Gateway API. The ingress CA
documented here applies regardless of which API you use - it's about the router's
TLS certificates for `*.apps.cluster...` URLs, not about any specific API.

## Certificate Bundles

### 1. Trusted CA Bundle (`config-trusted-cabundle`)

**Purpose:** Mozilla/system CA bundle for public internet CAs.

**Use when:** Connecting to public HTTPS endpoints (e.g., api.openai.com, pypi.org).

**How to use:**
1. Create empty ConfigMap with label `config.openshift.io/inject-trusted-cabundle: "true"`
2. OpenShift auto-populates with system CA bundle
3. Mount and reference `ca-bundle.crt`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: config-trusted-cabundle
  labels:
    config.openshift.io/inject-trusted-cabundle: "true"
data: {}  # Auto-populated by OpenShift
```

**Mount path:** `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`

### 2. Service CA Bundle (`config-service-cabundle`)

**Purpose:** OpenShift internal service CA for pod-to-pod communication.

**Use when:** Connecting to internal services with OpenShift-generated TLS certs.

**How to use:**
1. Create ConfigMap with annotation `service.beta.openshift.io/inject-cabundle: "true"`
2. OpenShift auto-populates with service CA

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: config-service-cabundle
  annotations:
    service.beta.openshift.io/inject-cabundle: "true"
data: {}  # Auto-populated by OpenShift
```

**Mount path:** `/etc/pki/service-ca/service-ca.crt`

### 3. Ingress CA Bundle (`otel-ingress-ca` - custom)

**Purpose:** OpenShift ingress controller CA for external routes (*.apps.cluster...).

**Use when:** Connecting to HTTPS endpoints via OpenShift routes from inside the cluster.

**Why needed:** The ingress CA is NOT included in either trusted-cabundle or service-cabundle.
Pods connecting to external URLs (like `https://keycloak.apps.cluster.example.com`)
will get "certificate signed by unknown authority" errors without this CA.

**How to use:**
The ingress CA is stored in `openshift-config-managed/default-ingress-cert`.
Since cross-namespace ConfigMap mounting isn't possible, copy it to your namespace:

```yaml
# Pre-install Job to copy ingress CA (see otel-ingress-ca-job.yaml)
apiVersion: batch/v1
kind: Job
metadata:
  name: ingress-ca-copier
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
spec:
  template:
    spec:
      containers:
        - name: copier
          image: registry.redhat.io/openshift4/ose-cli:v4.16
          command:
            - /bin/bash
            - -c
            - |
              INGRESS_CA=$(oc get configmap default-ingress-cert \
                -n openshift-config-managed \
                -o jsonpath='{.data.ca-bundle\.crt}')
              oc create configmap otel-ingress-ca \
                --from-literal=ca-bundle.crt="$INGRESS_CA" \
                -n $NAMESPACE --dry-run=client -o yaml | oc apply -f -
```

**Mount path:** `/etc/pki/ingress-ca/ingress-ca.pem`

## Decision Tree

```
Need to verify TLS certificate?
│
├─> Connecting to public internet (api.openai.com, pypi.org, etc.)
│   └─> Use: config-trusted-cabundle
│
├─> Connecting to internal service (http://service.namespace.svc)
│   └─> No CA needed (use http) OR use service-cabundle for HTTPS
│
├─> Connecting to external route (https://*.apps.cluster...)
│   └─> Use: Ingress CA (copy from openshift-config-managed/default-ingress-cert)
│
└─> Connecting to Keycloak for OAuth tokens
    ├─> Internal URL (http://keycloak-service.keycloak.svc:8080)
    │   └─> No CA needed (internal HTTP)
    │   └─> WARNING: JWT issuer will be internal URL - may cause validation issues
    │
    └─> External URL (https://keycloak.apps.cluster...)
        └─> Use: Ingress CA
```

## Common Mistakes

### Using trusted-cabundle for OpenShift routes

**Problem:** `x509: certificate signed by unknown authority` when connecting to
`*.apps.cluster.example.com` URLs.

**Cause:** OpenShift ingress uses a cluster-specific CA, not a public CA.

**Fix:** Use the ingress CA from `openshift-config-managed/default-ingress-cert`.

### Using insecure_skip_verify

**Problem:** Bypasses TLS verification, security risk.

**Fix:** Always configure proper CA certificates instead.

### JWT issuer mismatch with internal URLs

**Problem:** OAuth token obtained from internal Keycloak URL has internal issuer.
Applications validating against external OIDC discovery URL reject the token.

**Cause:** Keycloak sets JWT `iss` claim based on the URL used to obtain the token.

**Fix:** Use external Keycloak URL for token endpoint, with proper ingress CA.

## Implementation in Kagenti

The OTEL collector uses OAuth2 client credentials to authenticate with MLflow.
The token endpoint is the external Keycloak URL (via OpenShift route).

**Files:**
- `charts/kagenti-deps/templates/otel-ingress-ca-job.yaml` - Pre-install Job
- `charts/kagenti-deps/templates/otel-collector.yaml` - Mounts ingress CA

**Configuration:**
```yaml
oauth2client/mlflow:
  client_id: ${env:MLFLOW_CLIENT_ID}
  client_secret: ${env:MLFLOW_CLIENT_SECRET}
  token_url: ${env:KEYCLOAK_TOKEN_URL}
  tls:
    ca_file: /etc/pki/ingress-ca/ingress-ca.pem  # Ingress CA
```

## Testing

Verify certificate verification works:

```bash
# Check ingress CA was copied
kubectl get configmap otel-ingress-ca -n kagenti-system

# Check OTEL collector logs for OAuth errors
kubectl logs -n kagenti-system -l app=otel-collector | grep -i oauth

# Test token endpoint from pod with ingress CA mounted
kubectl exec -it <pod> -- curl --cacert /etc/pki/ingress-ca/ingress-ca.pem \
  https://keycloak.apps.cluster.example.com/realms/master/.well-known/openid-configuration
```
