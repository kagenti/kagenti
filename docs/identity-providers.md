# Identity Providers

Kagenti supports multiple workload identity providers through a pluggable abstraction layer. This allows deployment on platforms with different identity infrastructure capabilities.

## Supported Providers

### SPIRE/SPIFFE
- **Provider Name:** `spire`
- **Description:** Production-grade workload identity using SPIFFE/SPIRE
- **Features:**
  - Cross-cluster identity support
  - Cryptographic attestation
  - Short-lived, automatically rotated tokens
  - Industry-standard SPIFFE ID format
- **Requirements:** SPIRE server and agent must be installed
- **Token Location:** `/opt/jwt_svid.token`

#### SPIRE Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SPIRE INFRASTRUCTURE                             │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  SPIRE Server                                                             │
│  ────────────                                                            │
│  • Central authority for identity issuance                               │
│  • Validates workload attestation                                        │
│  • Issues SPIFFE IDs and JWT-SVID tokens                                 │
│  • Manages trust domain                                                  │
│                                                                          │
│  Trust Domain: example.org                                               │
└─────────────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                              │ communicates via
                              │ SPIRE Agent API
                              │
┌─────────────────────────────┴───────────────────────────────────────────┐
│  SPIRE Agent (DaemonSet)                                                  │
│  ────────────────────────                                                 │
│  • Runs on each node                                                     │
│  • Attests workloads running on the node                                │
│  • Requests SVIDs from SPIRE Server                                      │
│  • Provides Workload API via CSI driver                                  │
│                                                                          │
│  CSI Driver: csi.spiffe.io                                               │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              │ mounts volumes via
                              │ CSI Workload API
                              │
┌─────────────────────────────┴───────────────────────────────────────────┐
│                         POD WITH SPIRE IDENTITY                           │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  Pod                                                                      │
│  ───                                                                     │
│  spec:                                                                    │
│    volumes:                                                               │
│      - name: spiffe-workload-api                                          │
│        csi:                                                               │
│          driver: csi.spiffe.io                                           │
│                                                                          │
│    containers:                                                            │
│      - volumeMounts:                                                     │
│          - name: spiffe-workload-api                                     │
│            mountPath: /spiffe-workload-api                               │
│                                                                          │
│  SPIRE Agent provides:                                                   │
│  • JWT-SVID token at: /opt/jwt_svid.token                               │
│  • SPIFFE ID: spiffe://example.org/ns/kagenti-system/sa/kagenti-ui      │
│  • Short-lived, automatically rotated tokens                            │
│  • Cryptographic attestation                                              │
└─────────────────────────────────────────────────────────────────────────┘
```

#### SPIRE Identity Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│  1. POD STARTS                                                           │
│     ──────────                                                          │
│     Pod scheduled on node with SPIRE Agent                              │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  2. SPIRE AGENT ATTESTATION                                             │
│     ────────────────────────                                            │
│     • SPIRE Agent detects new pod                                       │
│     • Verifies pod identity (ServiceAccount, labels, etc.)             │
│     • Attests workload to SPIRE Server                                  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  3. SPIRE SERVER VALIDATION                                             │
│     ────────────────────────                                            │
│     • Validates attestation evidence                                     │
│     • Checks registration entries                                        │
│     • Issues SPIFFE ID based on workload attributes                      │
│     • Generates JWT-SVID token                                           │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  4. TOKEN DELIVERY                                                       │
│     ──────────────                                                      │
│     • SPIRE Agent receives JWT-SVID from Server                          │
│     • Token delivered via CSI Workload API                              │
│     • Token mounted in pod at: /opt/jwt_svid.token                      │
│     • Token automatically rotated (short-lived)                         │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  5. WORKLOAD USES IDENTITY                                              │
│     ──────────────────────                                             │
│     • Pod reads token from /opt/jwt_svid.token                          │
│     • Token contains SPIFFE ID in 'sub' claim:                          │
│       spiffe://example.org/ns/kagenti-system/sa/kagenti-ui              │
│     • Used for:                                                          │
│       - Keycloak client registration                                     │
│       - OAuth token exchange                                            │
│       - Cross-cluster authentication                                     │
│       - Service-to-service authentication                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### Kubernetes ServiceAccount
- **Provider Name:** `serviceaccount`
- **Description:** Basic workload identity using Kubernetes ServiceAccount tokens
- **Features:**
  - No additional infrastructure required
  - Works on any Kubernetes cluster
  - Standard Kubernetes token format
- **Limitations:**
  - **Cluster-local only** (no cross-cluster identity)
  - Less secure than SPIRE (no cryptographic attestation)
  - Tokens managed by Kubernetes API server
- **Token Location:** `/var/run/secrets/kubernetes.io/serviceaccount/token`

## Configuration

The identity provider must be explicitly configured. There is no auto-detection.

### Environment Variable
```bash
export KAGENTI_IDENTITY_PROVIDER=spire  # spire or serviceaccount (required)
```

### Values.yaml
```yaml
identity:
  provider: "spire"  # spire or serviceaccount (required)
components:
  spire:
    enabled: true  # Set to false if using ServiceAccount provider
```

### Identity Provider Selection

The provider is determined solely by the `KAGENTI_IDENTITY_PROVIDER` environment variable or `identity.provider` Helm value:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Identity Provider Selection                                            │
│  ────────────────────────────                                           │
│                                                                          │
│  Check KAGENTI_IDENTITY_PROVIDER environment variable or                │
│  identity.provider Helm value                                           │
│     │                                                                    │
│     ├─> "spire" ──────────────> Use SPIRE Provider                    │
│     │                            (requires SPIRE infrastructure)         │
│     │                                                                    │
│     ├─> "serviceaccount" ──────> Use ServiceAccount Provider            │
│     │                            (uses Kubernetes native tokens)         │
│     │                                                                    │
│     └─> Not set or invalid ────> Error: Identity provider required     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Usage Examples

### Using SPIRE (Production)
```yaml
identity:
  provider: "spire"
components:
  spire: true
```

#### SPIRE Pod Configuration Example

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Deployment with SPIRE Identity                                          │
│  ──────────────────────────────                                         │
│                                                                          │
│  apiVersion: apps/v1                                                    │
│  kind: Deployment                                                        │
│  metadata:                                                               │
│    name: kagenti-ui                                                      │
│  spec:                                                                   │
│    template:                                                             │
│      spec:                                                               │
│        serviceAccountName: kagenti-ui-service-account                   │
│        volumes:                                                          │
│          - name: spiffe-workload-api                                     │
│            csi:                                                           │
│              driver: csi.spiffe.io                                       │
│              readOnly: true                                              │
│        containers:                                                       │
│          - name: kagenti-ui                                              │
│            volumeMounts:                                                 │
│              - name: spiffe-workload-api                                 │
│                mountPath: /spiffe-workload-api                           │
│                readOnly: true                                            │
│                                                                          │
│  SPIRE Agent automatically:                                              │
│  • Detects pod via CSI mount                                             │
│  • Attests workload                                                      │
│  • Delivers JWT-SVID to: /opt/jwt_svid.token                             │
│  • Rotates token automatically                                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Using ServiceAccount (Compatibility)
```yaml
identity:
  provider: "serviceaccount"
components:
  spire: false
```

### Explicit Configuration (Required)
```yaml
identity:
  provider: "spire"  # Explicitly use SPIRE provider
components:
  spire:
    enabled: true  # Install SPIRE infrastructure
```

## Migration Guide

### Migrating from SPIRE-only to Abstraction

**Explicit configuration required!** Existing SPIRE deployments must be updated:
- Set `identity.provider: "spire"` explicitly in values.yaml
- Set `KAGENTI_IDENTITY_PROVIDER=spire` environment variable
- All existing functionality preserved

### Enabling ServiceAccount Provider

1. Set environment variable or values.yaml:
   ```yaml
   identity:
     provider: "serviceaccount"
   components:
     spire:
       enabled: false
   ```

2. Ensure pods have ServiceAccounts configured
3. Deploy as normal

## Provider Comparison

| Feature | SPIRE | ServiceAccount |
|---------|-------|----------------|
| Cross-cluster identity | ✅ Yes | ❌ No |
| Cryptographic attestation | ✅ Yes | ❌ No |
| Automatic token rotation | ✅ Yes | ⚠️ Managed by K8s |
| Additional infrastructure | ✅ Required | ❌ None |
| Production readiness | ✅ Recommended | ⚠️ Basic |
| OpenShift compatibility | ⚠️ Version dependent | ✅ All versions |

### Detailed Identity Comparison

```
┌─────────────────────────────────────────────────────────────────────────┐
│              SERVICEACCOUNT IDENTITY (Kubernetes Native)                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Identity Source:                                                       │
│    Kubernetes API Server                                                │
│                                                                          │
│  Token Location:                                                        │
│    /var/run/secrets/kubernetes.io/serviceaccount/token                  │
│                                                                          │
│  Identity Format:                                                        │
│    system:serviceaccount:<namespace>:<name>                             │
│    Example: system:serviceaccount:kagenti-system:kagenti-ui-sa          │
│                                                                          │
│  Token Management:                                                       │
│    • Managed by Kubernetes API server                                   │
│    • Long-lived tokens                                                  │
│    • Manual rotation                                                    │
│                                                                          │
│  Scope:                                                                  │
│    • Cluster-local only                                                 │
│    • Cannot be used across clusters                                     │
│                                                                          │
│  Security:                                                               │
│    • Basic Kubernetes authentication                                    │
│    • No cryptographic attestation                                       │
│                                                                          │
│  Infrastructure:                                                         │
│    • Built into Kubernetes                                              │
│    • No additional components required                                  │
│                                                                          │
│  Use Case:                                                              │
│    • Simple, cluster-local workloads                                    │
│    • Development/testing environments                                   │
│    • OpenShift compatibility                                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                    SPIRE IDENTITY (SPIFFE/SPIRE)                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Identity Source:                                                       │
│    SPIRE Server (via SPIRE Agent)                                       │
│                                                                          │
│  Token Location:                                                        │
│    /opt/jwt_svid.token                                                  │
│    (delivered via CSI Workload API)                                     │
│                                                                          │
│  Identity Format:                                                        │
│    SPIFFE ID: spiffe://<trust-domain>/<path>                            │
│    Example: spiffe://example.org/ns/kagenti-system/sa/kagenti-ui       │
│                                                                          │
│  Token Management:                                                      │
│    • Managed by SPIRE Server                                             │
│    • Short-lived tokens (auto-rotated)                                  │
│    • Automatic rotation                                                 │
│                                                                          │
│  Scope:                                                                  │
│    • Cross-cluster support                                              │
│    • Can be used across multiple clusters                               │
│    • Works with federated trust domains                                  │
│                                                                          │
│  Security:                                                               │
│    • Cryptographic attestation                                           │
│    • Zero-trust principles                                              │
│    • Workload verification                                               │
│                                                                          │
│  Infrastructure:                                                         │
│    • Requires SPIRE Server                                              │
│    • Requires SPIRE Agent (DaemonSet)                                   │
│    • Requires CSI driver (csi.spiffe.io)                                │
│                                                                          │
│  Use Case:                                                              │
│    • Production workloads                                                │
│    • Multi-cluster deployments                                          │
│    • Zero-trust architectures                                           │
│    • High-security requirements                                         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Implementation Details

### Client Registration
The client registration process (`kagenti/auth/client-registration`) automatically uses the configured identity provider to extract the workload identity for Keycloak client registration.

### Agent/Tool Deployment
Agents and tools receive identity volumes based on the selected provider:
- **SPIRE:** CSI volumes with `csi.spiffe.io` driver
- **ServiceAccount:** Projected token volumes

#### SPIRE Identity Usage in Kagenti

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Pod (Kagenti Component)                                                 │
│  ───────────────────────                                                │
│                                                                          │
│  1. Reads SPIRE token from: /opt/jwt_svid.token                         │
│                                                                          │
│  2. Extracts SPIFFE ID from token 'sub' claim:                          │
│     spiffe://example.org/ns/kagenti-system/sa/my-component              │
│                                                                          │
│  3. Uses identity for:                                                   │
│     ┌─────────────────────────────────────────────────────────────┐     │
│     │ Keycloak Client Registration                                │     │
│     │ • Registers OAuth client using SPIFFE ID as client_id       │     │
│     │ • Enables secure, workload-specific authentication          │     │
│     └─────────────────────────────────────────────────────────────┘     │
│                                                                          │
│     ┌─────────────────────────────────────────────────────────────┐     │
│     │ OAuth Token Exchange                                         │     │
│     │ • Exchanges user token for workload token                   │     │
│     │ • Uses SPIFFE ID to identify workload                       │     │
│     └─────────────────────────────────────────────────────────────┘     │
│                                                                          │
│     ┌─────────────────────────────────────────────────────────────┐     │
│     │ Cross-Cluster Authentication                                 │     │
│     │ • Authenticate to services in other clusters                │     │
│     │ • Federated trust domains                                    │     │
│     └─────────────────────────────────────────────────────────────┘     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Identity vs RBAC Permissions

```
┌─────────────────────────────────────────────────────────────────────────┐
│  WORKLOAD IDENTITY vs RBAC PERMISSIONS                                   │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  SPIRE Identity                                                          │
│  ─────────────                                                          │
│  Purpose: WHO the workload is                                           │
│  • Provides SPIFFE ID                                                   │
│  • Used for authentication to external services                         │
│  • Used for Keycloak client registration                                │
│  • Used for OAuth token exchange                                        │
│  • Cross-cluster identity                                                │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              │ separate from
                              │
┌─────────────────────────────┴───────────────────────────────────────────┐
│  RBAC Permissions                                                        │
│  ────────────────                                                      │
│  Purpose: WHAT the workload can do                                      │
│  • ClusterRole defines permissions                                      │
│  • ClusterRoleBinding grants to ServiceAccount                          │
│  • Used for Kubernetes API access                                      │
│  • Cluster-local permissions                                            │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              │ both used by
                              │
┌─────────────────────────────┴───────────────────────────────────────────┐
│  Pod                                                                     │
│  ───                                                                    │
│                                                                          │
│  Uses SPIRE Identity for:                                               │
│  • External service authentication                                       │
│  • Keycloak integration                                                  │
│  • Cross-cluster communication                                          │
│                                                                          │
│  Uses RBAC (ServiceAccount) for:                                       │
│  • Kubernetes API access                                                 │
│  • Reading/writing cluster resources                                    │
│  • Managing Kagenti components                                          │
│                                                                          │
│  Note: A pod can use BOTH simultaneously:                              │
│  • SPIRE token: /opt/jwt_svid.token (for external auth)                 │
│  • ServiceAccount token: /var/run/secrets/kubernetes.io/... (for K8s)  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Installer Integration
The installer (`kagenti/installer`) conditionally:
- Installs SPIRE only if provider is `spire`
- Applies SPIRE helper configs only when using SPIRE
- Skips SPIRE installation when using ServiceAccount provider

## Troubleshooting

### "Identity provider must be explicitly specified"
- Set `KAGENTI_IDENTITY_PROVIDER` environment variable to `spire` or `serviceaccount`
- Or set `identity.provider` in Helm values.yaml to `spire` or `serviceaccount`

### "SPIRE provider requested but token not found"
- Ensure SPIRE is installed and configured
- Check that SPIRE agent is running
- Verify token path is correct

### "ServiceAccount provider requested but token not found"
- Ensure pod has a ServiceAccount configured
- Check that ServiceAccount token projection is enabled
- Verify token path is correct

## Future Enhancements

Potential future identity providers:
- Cert-manager based identities
- External identity providers (e.g., Vault)
- Custom provider plugins

