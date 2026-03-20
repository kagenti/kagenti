# HashiCorp Vault on OpenShift for Kagenti — Research (2026-02-26)

## 1. Deployment Options on OpenShift

### 1.1 Vault Helm Chart (Official) vs Vault Secrets Operator

There are two distinct components to consider:

| Component | Purpose | Install Method | Recommendation |
|-----------|---------|---------------|----------------|
| **Vault Server** | Secret storage, policy engine, dynamic secrets | Helm chart (`hashicorp/vault`) | Helm chart with `global.openshift=true` |
| **Vault Secrets Operator (VSO)** | Syncs Vault secrets to K8s Secrets | OperatorHub (certified) or Helm | OperatorHub on OpenShift (Red Hat certified) |

**Vault Server** must be deployed via the Helm chart. There is no "Vault Operator" that replaces the server itself. The VSO is a _client-side_ operator that reads secrets from an already-running Vault and creates Kubernetes Secret objects.

**Key decision:** You need both. The Helm chart deploys the Vault server; the VSO (or Agent Injector) is how workloads consume secrets.

### 1.2 Minimum Resources

#### Vault Server (Kubernetes Deployment)

| Tier | CPU Request | CPU Limit | Memory Request | Memory Limit | Storage (PVC) | Nodes |
|------|-------------|-----------|----------------|--------------|---------------|-------|
| **Dev/Test (single-node)** | 250m | 500m | 256Mi | 512Mi | 1Gi (Raft) | 1 |
| **Small production (HA)** | 2000m | 2000m | 8Gi | 16Gi | 25Gi (Raft) | 3-5 |
| **Large production (HA)** | 4000m+ | 8000m+ | 16Gi | 32Gi | 100Gi+ (Raft) | 5 |

HashiCorp's reference architecture recommends 2 vCPUs / 8 GB RAM as a minimum for production with Raft integrated storage, plus 3000+ IOPS on the storage volume.

For Kagenti dev/test with 2-3 agents, the **dev/test tier** is sufficient. A single Vault pod with 256Mi-512Mi memory and 1Gi PVC will handle the secret load of a small agent cluster.

#### Vault Secrets Operator (VSO)

| Resource | Request | Limit |
|----------|---------|-------|
| CPU | 50m | 100m |
| Memory | 128Mi | 256Mi |

VSO runs as a single controller per cluster (not per-pod), so overhead is minimal. Note: a known issue in VSO 0.3.x causes CPU to spike to its limit after ~1 hour of operation; this is fixed in later versions.

#### Vault Agent Sidecar (per-pod overhead)

| Resource | Default | Tuned (recommended) | Observed real usage |
|----------|---------|---------------------|---------------------|
| CPU Request | 250m | 25m | 1-5m |
| CPU Limit | 500m | 50m | <15m |
| Memory Request | 64Mi | 16Mi | Low |
| Memory Limit | 128Mi | 32Mi | Low |

The defaults are very conservative. In practice, the agent sidecar uses 1-15m CPU. For Kagenti, where agents only need a handful of secrets, tune the requests down to 25m CPU / 16Mi memory to minimize scheduling overhead.

**Recommendation for Kagenti:** Prefer VSO over Agent Injector sidecars. VSO runs one controller per cluster rather than one sidecar per pod, reducing total resource consumption significantly.

### 1.3 HA vs Single-Node

| Mode | When to Use | Vault Pods | Storage |
|------|------------|------------|---------|
| **Dev mode** (`server.dev.enabled: true`) | Local testing, demos | 1 | In-memory (data lost on restart) |
| **Standalone** (`server.standalone.enabled: true`) | Dev/test clusters, CI | 1 | 1Gi PVC (Raft or file) |
| **HA Raft** (`server.ha.enabled: true, server.ha.raft.enabled: true`) | Production | 3-5 | 25Gi+ PVC per node |

For Kagenti dev/test on HyperShift clusters, **standalone mode** is the right choice. It persists data across restarts but avoids the overhead of a 3-5 node Raft cluster.

### 1.4 Raft Integrated Storage vs Consul Backend

| Feature | Integrated Storage (Raft) | Consul Backend |
|---------|--------------------------|----------------|
| **Status** | **Recommended** (current default) | Supported (legacy) |
| **Data persistence** | On-disk (disk I/O bound) | In-memory (RAM bound) |
| **Infrastructure** | Self-contained (Vault only) | Requires separate Consul cluster |
| **Total pods (HA)** | 3-5 Vault pods | 3 Vault + 5 Consul pods (8 total) |
| **Operational complexity** | Lower | Higher (two clusters to manage) |
| **Backup frequency** | Less frequent (data on disk) | Frequent (data in memory) |

**Verdict:** Use Raft integrated storage. It eliminates the need for a Consul cluster and is HashiCorp's current recommendation. For Kagenti, this means deploying only the Vault Helm chart, not Consul.

---

## 2. Integration with Kagenti

### 2.1 Replace Kubernetes Secrets with Vault Dynamic Secrets

Currently, Kagenti stores credentials (GitHub PATs, LLM API keys, OAuth client secrets) as Kubernetes Secrets in agent namespaces. Vault replaces this with:

| Current Pattern | Vault Pattern |
|----------------|---------------|
| `kubectl create secret generic openai-key --from-literal=key=sk-...` | Vault KV or dynamic secrets engine |
| Secret mounted as env var or file in agent pod | VSO syncs to K8s Secret, or Agent Injector writes to `/vault/secrets/` |
| Manual rotation (delete + recreate secret) | Automatic rotation via TTL or `rotation_period` |
| Visible in `kubectl get secrets` (base64 encoded) | Encrypted at rest in Vault, audit-logged |

**Migration path for Kagenti:**

1. Deploy Vault in `vault` namespace (standalone, Raft storage)
2. Install VSO from OperatorHub
3. Store existing secrets in Vault KV v2 (`secret/kagenti/team1/openai-key`)
4. Create `VaultStaticSecret` CRs in agent namespaces to sync secrets
5. Gradually move to dynamic secrets engines for credentials that support it

Example `VaultStaticSecret` for an agent namespace:
```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultStaticSecret
metadata:
  name: openai-key
  namespace: team1
spec:
  vaultAuthRef: vault-auth
  mount: secret
  path: kagenti/team1/openai-key
  type: kv-v2
  refreshAfter: 60s
  destination:
    name: openai-key          # K8s Secret name
    create: true
```

### 2.2 Agent Credential Rotation

#### GitHub PATs / Installation Tokens

**Problem:** Sandbox agents need GitHub access for cloning repos, creating branches, and opening PRs. Long-lived PATs are a security risk.

**Solution: vault-plugin-secrets-github** (community plugin by Martin Baillie)

This plugin uses a GitHub App to generate ephemeral, scoped installation tokens:

1. Register a GitHub App with the required permissions (contents:write, pull_requests:write)
2. Configure the plugin with the App's private key
3. Agents request tokens scoped to specific repos
4. Tokens expire after 1 hour (GitHub's maximum for installation tokens)

```bash
# Configure the GitHub secrets engine
vault write github/config \
  app_id=123456 \
  prv_key=@github-app-private-key.pem

# Agent requests a scoped token
vault read github/token \
  installation_id=789 \
  repositories=org/repo1,org/repo2 \
  permissions=contents:write,pull_requests:write
```

**Integration with AuthBridge:** AuthBridge's `ext_proc` can request tokens from Vault instead of directly from GitHub, using Vault's Kubernetes auth to authenticate.

#### LLM API Keys (OpenAI, Anthropic)

**Option A: Vault KV with Auto-Rotation (simple)**
- Store API keys in Vault KV v2
- Use VSO to sync to K8s Secrets with `refreshAfter: 60s`
- Manual rotation: update in Vault, VSO propagates to all agent pods

**Option B: Vault OpenAI Dynamic Secrets Plugin (advanced)**
- Community plugin: `vault-plugin-secrets-openai`
- Generates ephemeral OpenAI API keys with TTL (e.g., 1 hour)
- Keys auto-expire; no manual cleanup
- Currently supports OpenAI only; Anthropic would need a custom plugin or KV approach

```bash
# Configure OpenAI secrets engine
vault write openai/config \
  admin_api_key="sk-admin-..." \
  organization_id="org-123456" \
  rotation_period=604800

# Create a role with 1h TTL
vault write openai/roles/sandbox-agent \
  ttl=1h max_ttl=24h

# Agent requests credentials
vault read openai/creds/sandbox-agent
# Returns: api_key, lease_id, lease_duration
```

#### Slack / Webhook Tokens

Store in Vault KV v2 with periodic rotation. Use VSO `VaultStaticSecret` to sync.

### 2.3 Integration with SPIRE (Vault Auth via SPIFFE SVIDs)

Kagenti already runs SPIRE for workload identity. Vault supports SPIFFE as a native auth method (Vault Enterprise 1.21+) or via OIDC federation (open source).

#### Option A: Native SPIFFE Auth (Vault Enterprise 1.21+)

```bash
# Enable SPIFFE auth
vault auth enable spiffe

# Configure trust domain from SPIRE
vault write auth/spiffe/config \
  trust_domain="kagenti" \
  trust_bundle_url="https://spire-server.spire-system.svc:8443/bundle"

# Create a role mapping SPIFFE IDs to Vault policies
vault write auth/spiffe/roles/sandbox-agent \
  workload_id_patterns="ns/team1/sa/*,ns/team2/sa/*" \
  token_policies="sandbox-agent-policy"
```

Agent pods authenticate to Vault using their SPIFFE SVID (X.509 or JWT) -- no service account tokens or app-role credentials needed.

#### Option B: SPIRE OIDC Federation with Vault JWT Auth (Open Source)

For Vault open-source / community edition:

1. Configure SPIRE to expose an OIDC Discovery endpoint
2. Configure Vault's JWT auth method to trust SPIRE as an OIDC provider
3. Agents present their JWT-SVID to Vault and receive a Vault token

```bash
# Enable JWT auth
vault auth enable jwt

# Configure SPIRE as OIDC provider
vault write auth/jwt/config \
  oidc_discovery_url="https://spire-oidc.spire-system.svc" \
  default_role="sandbox-agent"

# Create role
vault write auth/jwt/role/sandbox-agent \
  role_type="jwt" \
  bound_audiences="vault" \
  user_claim="sub" \
  bound_subject="spiffe://kagenti/ns/team1/sa/sandbox-agent" \
  token_policies="sandbox-agent-policy" \
  token_ttl=1h
```

#### Option C: Kubernetes Auth (Simplest, No SPIRE Dependency)

If SPIRE integration is not required for Vault auth specifically:

```bash
vault auth enable kubernetes

vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc"

vault write auth/kubernetes/role/sandbox-agent \
  bound_service_account_names="sandbox-agent,sandbox-legion" \
  bound_service_account_namespaces="team1,team2" \
  policies="sandbox-agent-policy" \
  ttl=1h
```

**Recommendation for Kagenti:** Start with Kubernetes auth (Option C) for simplicity. Add SPIRE OIDC federation (Option B) when you want zero-secret auth. Option A requires Vault Enterprise.

### 2.4 Integration with AuthBridge (Vault as Credential Backend)

Currently, AuthBridge reads credentials from Kubernetes Secrets. With Vault:

```
Agent pod ──SPIFFE SVID──> AuthBridge ext_proc ──Vault API──> Dynamic Credential
                                    │
                                    ├── Vault Kubernetes auth (SA token)
                                    ├── vault read github/token (scoped GitHub token)
                                    ├── vault read openai/creds/role (dynamic LLM key)
                                    └── Injects credential into outbound request
```

**Changes needed in AuthBridge:**
1. Add a Vault client (e.g., `hvac` Python library or Vault HTTP API)
2. On startup, authenticate to Vault using Kubernetes SA token
3. For each outbound request, look up the `SandboxTokenPolicy` CRD
4. Request the appropriate credential from Vault (GitHub token, LLM key, etc.)
5. Inject the credential into the Authorization header
6. Vault handles TTL, rotation, and audit logging

This replaces the current pattern where AuthBridge reads from Kubernetes Secrets and manually manages credential lifecycles.

---

## 3. Resource Requirements Summary

### Total Overhead for Kagenti Dev/Test (2-3 Agents)

| Component | Pods | CPU (request) | Memory (request) | Storage |
|-----------|------|---------------|-------------------|---------|
| Vault Server (standalone) | 1 | 250m | 256Mi | 1Gi PVC |
| Vault Agent Injector | 1 | 50m | 64Mi | -- |
| Vault Secrets Operator | 1 | 50m | 128Mi | -- |
| **Total platform overhead** | **3** | **350m** | **448Mi** | **1Gi** |

Per-agent overhead (if using Agent Injector sidecar instead of VSO):

| Component | Per Pod | CPU (request) | Memory (request) |
|-----------|---------|---------------|-------------------|
| Vault Agent sidecar | 1 container | 25m (tuned) | 16Mi (tuned) |

**With VSO (recommended):** No per-pod overhead. VSO syncs secrets to K8s Secrets centrally.

**With Agent Injector:** 25m CPU + 16Mi memory per agent pod (tuned from defaults).

### Comparison with Current Kagenti Stack

| Component | CPU | Memory | Notes |
|-----------|-----|--------|-------|
| Vault (standalone) | 250m | 256Mi | New addition |
| VSO | 50m | 128Mi | New addition |
| Keycloak | 500m | 512Mi | Already deployed |
| SPIRE Server | 200m | 256Mi | Already deployed |
| PostgreSQL | 250m | 256Mi | Already deployed |

Vault adds roughly 300m CPU and 384Mi memory to the platform, which is modest compared to Keycloak (the heaviest current component).

---

## 4. Quick Deploy Recipe

### 4.1 Helm Values for OpenShift (Minimum Viable Config)

Create `vault-values.yaml`:

```yaml
# vault-values.yaml - Kagenti dev/test on OpenShift
global:
  openshift: true

server:
  image:
    repository: "registry.connect.redhat.com/hashicorp/vault"
    tag: "1.21.2-ubi"

  standalone:
    enabled: true
    config: |
      ui = true
      listener "tcp" {
        tls_disable = 1
        address = "[::]:8200"
        cluster_address = "[::]:8201"
      }
      storage "raft" {
        path = "/vault/data"
      }
      service_registration "kubernetes" {}

  # Service-CA operator handles TLS on the Route
  serviceCA:
    enabled: true

  # Resource limits for dev/test
  resources:
    requests:
      memory: 256Mi
      cpu: 250m
    limits:
      memory: 512Mi
      cpu: 500m

  dataStorage:
    enabled: true
    size: 1Gi
    storageClass: null    # Use cluster default

  # OpenShift Route
  route:
    enabled: true
    host: vault.apps.example.com   # Replace with your cluster domain
    tls:
      termination: edge

  readinessProbe:
    path: "/v1/sys/health?uninitcode=204"

injector:
  enabled: true
  image:
    repository: "registry.connect.redhat.com/hashicorp/vault-k8s"
    tag: "1.7.2-ubi"
  agentImage:
    repository: "registry.connect.redhat.com/hashicorp/vault"
    tag: "1.21.2-ubi"
  resources:
    requests:
      memory: 64Mi
      cpu: 50m
    limits:
      memory: 128Mi
      cpu: 100m

ui:
  enabled: true

csi:
  enabled: false         # Not needed if using VSO or Agent Injector
```

### 4.2 HA Config (Production)

For production deployments, replace the `server` section:

```yaml
server:
  ha:
    enabled: true
    replicas: 3
    raft:
      enabled: true
      config: |
        ui = true
        listener "tcp" {
          tls_disable = 1
          address = "[::]:8200"
          cluster_address = "[::]:8201"
        }
        storage "raft" {
          path = "/vault/data"
          retry_join {
            leader_api_addr = "http://vault-0.vault-internal:8200"
          }
          retry_join {
            leader_api_addr = "http://vault-1.vault-internal:8200"
          }
          retry_join {
            leader_api_addr = "http://vault-2.vault-internal:8200"
          }
        }
        service_registration "kubernetes" {}

  resources:
    requests:
      memory: 8Gi
      cpu: 2000m
    limits:
      memory: 16Gi
      cpu: 2000m

  dataStorage:
    size: 25Gi
```

### 4.3 Deploy Commands

```bash
# 1. Add Helm repo
helm repo add hashicorp https://helm.releases.hashicorp.com
helm repo update

# 2. Create namespace
oc new-project vault

# 3. Install Vault server
helm install vault hashicorp/vault \
  --namespace vault \
  -f vault-values.yaml

# 4. Wait for pod to be running
oc wait --for=condition=Ready pod/vault-0 -n vault --timeout=120s

# 5. Initialize Vault (first time only)
oc exec -n vault vault-0 -- vault operator init \
  -key-shares=1 \
  -key-threshold=1 \
  -format=json > /tmp/vault-init.json

# IMPORTANT: Save the unseal key and root token securely
# In production, use key-shares=5 key-threshold=3

# 6. Unseal Vault
UNSEAL_KEY=$(jq -r '.unseal_keys_b64[0]' /tmp/vault-init.json)
oc exec -n vault vault-0 -- vault operator unseal "$UNSEAL_KEY"

# 7. Verify Vault is running
oc exec -n vault vault-0 -- vault status

# 8. Install VSO from OperatorHub (OpenShift web console)
#    Operators > OperatorHub > search "Vault Secrets Operator" > Install
#    Or via CLI:
cat <<EOF | oc apply -f -
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: vault-secrets-operator
  namespace: openshift-operators
spec:
  channel: stable
  name: vault-secrets-operator
  source: certified-operators
  sourceNamespace: openshift-marketplace
EOF

# 9. Configure Kubernetes auth in Vault
ROOT_TOKEN=$(jq -r '.root_token' /tmp/vault-init.json)
oc exec -n vault vault-0 -- sh -c "
  export VAULT_TOKEN=$ROOT_TOKEN
  vault auth enable kubernetes
  vault write auth/kubernetes/config \
    kubernetes_host=https://kubernetes.default.svc
"

# 10. Create a policy for sandbox agents
oc exec -n vault vault-0 -- sh -c "
  export VAULT_TOKEN=$ROOT_TOKEN
  vault policy write sandbox-agent - <<POLICY
path \"secret/data/kagenti/*\" {
  capabilities = [\"read\", \"list\"]
}
path \"github/token\" {
  capabilities = [\"read\"]
}
path \"openai/creds/*\" {
  capabilities = [\"read\"]
}
POLICY
"

# 11. Create a Kubernetes auth role for sandbox agents
oc exec -n vault vault-0 -- sh -c "
  export VAULT_TOKEN=$ROOT_TOKEN
  vault write auth/kubernetes/role/sandbox-agent \
    bound_service_account_names=sandbox-agent,sandbox-legion \
    bound_service_account_namespaces=team1,team2 \
    policies=sandbox-agent-policy \
    ttl=1h
"
```

### 4.4 Auto-Unseal (Recommended for Non-Dev)

For OpenShift, consider using Vault auto-unseal with a cloud KMS:

```hcl
# Add to server config
seal "awskms" {
  region     = "us-east-1"
  kms_key_id = "alias/vault-unseal"
}
# Or for Azure:
seal "azurekeyvault" {
  tenant_id  = "..."
  vault_name = "..."
  key_name   = "vault-unseal"
}
```

This eliminates the manual unseal step after pod restarts.

---

## 5. Secret Rotation Patterns

### 5.1 Dynamic GitHub Tokens via Vault GitHub Secrets Engine

**Plugin:** `vault-plugin-secrets-github` (community)

```bash
# Register and enable plugin
vault plugin register -sha256=<sha> secret vault-plugin-secrets-github
vault secrets enable -path=github vault-plugin-secrets-github

# Configure with GitHub App credentials
vault write github/config \
  app_id=123456 \
  prv_key=@/path/to/private-key.pem

# Read a token (scoped to specific repos + permissions)
vault read github/token \
  installation_id=789 \
  repositories=kagenti/agent-examples \
  permissions=contents:write,pull_requests:write

# Token is valid for 1 hour (GitHub's maximum for installation tokens)
# Vault automatically revokes expired tokens
```

**Kagenti integration:**
- AuthBridge requests tokens from Vault on behalf of agents
- Each agent's `SandboxTokenPolicy` CRD maps to Vault roles
- Tokens are never stored long-term; generated on-demand per request

### 5.2 Auto-Rotating Database Credentials (PostgreSQL)

For agents that need direct database access (e.g., the sandbox session store):

```bash
# Enable database secrets engine
vault secrets enable database

# Configure PostgreSQL connection
vault write database/config/kagenti-postgres \
  plugin_name=postgresql-database-plugin \
  allowed_roles="sandbox-readonly,sandbox-readwrite" \
  connection_url="postgresql://{{username}}:{{password}}@postgresql.kagenti-system.svc:5432/kagenti" \
  username="vault_admin" \
  password="initial-password"

# Rotate root credentials (only Vault knows the new password)
vault write -force database/rotate-root/kagenti-postgres

# Create a dynamic role with 1h TTL
vault write database/roles/sandbox-readonly \
  db_name=kagenti-postgres \
  creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; \
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
  default_ttl=1h \
  max_ttl=24h

# Agent requests credentials
vault read database/creds/sandbox-readonly
# Returns: username, password, lease_id, lease_duration
```

**Benefits:**
- Each agent pod gets unique database credentials
- Credentials auto-expire after TTL (1 hour)
- Compromised credentials have limited blast radius
- Full audit trail of who accessed the database and when

### 5.3 Short-Lived LLM API Keys

#### OpenAI (via community plugin)

```bash
# Enable OpenAI secrets engine
vault secrets enable -path=openai vault-plugin-secrets-openai

# Configure with admin API key
vault write openai/config \
  admin_api_key="sk-admin-..." \
  organization_id="org-..." \
  rotation_period=604800   # Rotate admin key weekly

# Create role for sandbox agents
vault write openai/roles/sandbox-agent \
  ttl=1h \
  max_ttl=24h

# Agent requests a dynamic API key
vault read openai/creds/sandbox-agent
# Returns: api_key (valid for 1 hour), lease_id
```

#### Anthropic / Other Providers (KV + Manual Rotation)

No dynamic secrets plugin exists for Anthropic yet. Use Vault KV v2 with periodic manual or scripted rotation:

```bash
# Store API key in KV v2
vault kv put secret/kagenti/team1/anthropic-key \
  api_key="sk-ant-..."

# VSO syncs this to a K8s Secret in the agent namespace
# When the key is rotated in Vault, VSO propagates within refreshAfter interval

# Automated rotation script (run as CronJob)
#!/bin/bash
# 1. Generate new API key via provider's API
# 2. Update Vault:
vault kv put secret/kagenti/team1/anthropic-key api_key="$NEW_KEY"
# 3. VSO automatically propagates to K8s Secrets
```

### 5.4 Rotation Summary

| Credential Type | Engine | TTL | Rotation Method |
|----------------|--------|-----|-----------------|
| GitHub installation tokens | `vault-plugin-secrets-github` | 1h (GitHub max) | On-demand dynamic generation |
| OpenAI API keys | `vault-plugin-secrets-openai` | 1h (configurable) | Dynamic; admin key rotated weekly |
| Anthropic API keys | KV v2 | N/A (static) | Manual or scripted; VSO propagates |
| PostgreSQL credentials | Database secrets engine | 1h | Dynamic; root auto-rotated |
| Keycloak client secrets | KV v2 | N/A (static) | Rotated via Keycloak API + Vault update |
| Slack/webhook tokens | KV v2 | N/A (static) | Manual or scripted |

---

## 6. Kagenti-Specific Architecture

### 6.1 Proposed Namespace Layout

```
vault                    # Vault server + injector
openshift-operators      # VSO (installed via OperatorHub)
kagenti-system           # VaultAuth CR, platform secrets
team1                    # VaultStaticSecret / VaultDynamicSecret CRs
team2                    # VaultStaticSecret / VaultDynamicSecret CRs
```

### 6.2 Secret Flow with VSO

```
┌─── Vault Server (vault namespace) ──────────────────────────────┐
│  KV v2:  secret/kagenti/team1/openai-key                         │
│  GitHub: github/token (dynamic)                                  │
│  DB:     database/creds/sandbox-readonly (dynamic)               │
│  Auth:   Kubernetes auth (SA tokens from agent namespaces)       │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
┌─── VSO (openshift-operators) ────▼──────────────────────────────┐
│  Watches VaultStaticSecret / VaultDynamicSecret CRs             │
│  Authenticates to Vault via Kubernetes auth                     │
│  Creates/updates K8s Secrets in agent namespaces                │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
┌─── Agent Namespace (team1) ──────▼──────────────────────────────┐
│  K8s Secret: openai-key (synced by VSO, refreshed every 60s)   │
│  Agent pod mounts secret as env var or volume                   │
│  AuthBridge can also read from Vault directly for dynamic creds │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 Integration with SandboxTokenPolicy CRD

The existing `SandboxTokenPolicy` CRD design (from the sandbox-legion status doc) maps cleanly to Vault:

```yaml
apiVersion: kagenti.io/v1alpha1
kind: SandboxTokenPolicy
metadata:
  name: my-sandbox-agent
  namespace: team1
spec:
  spiffeId: spiffe://kagenti/ns/team1/sa/my-sandbox-agent
  github:
    vaultRole: github-team1-agent    # Maps to Vault GitHub secrets engine role
    repos: ["org/repo1", "org/repo2"]
    permissions: ["contents:write", "pull_requests:write"]
  llm:
    vaultPath: secret/kagenti/team1/openai-key   # KV path in Vault
    models: ["gpt-4o-mini", "gpt-4o"]
  database:
    vaultRole: sandbox-readonly       # Maps to Vault database secrets engine role
```

AuthBridge reads this CRD and calls Vault to obtain the appropriate credential for each outbound request.

---

## 7. Risks and Considerations

| Risk | Mitigation |
|------|-----------|
| **Vault Enterprise features needed** (SPIFFE auth, namespaces) | Start with open-source; use Kubernetes auth + OIDC federation for SPIRE |
| **Unseal ceremony on pod restart** | Use auto-unseal with cloud KMS or transit unseal |
| **Community plugins not officially supported** | Review plugin code; pin versions; wrap in internal chart |
| **Adds operational complexity** | Start with standalone + KV v2; add dynamic engines incrementally |
| **Vault becomes single point of failure** | HA Raft for production; K8s Secret fallback for critical paths |
| **License changes** (HashiCorp BSL) | Vault 1.14+ is BSL; evaluate OpenBao fork if licensing is a concern |

### OpenBao Alternative

OpenBao is the open-source fork of Vault (maintained by the Linux Foundation) created after HashiCorp's BSL license change. It is API-compatible with Vault 1.14. If licensing is a concern, OpenBao can be used as a drop-in replacement. The Helm chart and configuration are nearly identical.

---

## 8. Recommended Phased Rollout

| Phase | Scope | Effort | Dependencies |
|-------|-------|--------|-------------|
| **Phase 1** | Deploy Vault standalone + KV v2; store existing secrets | 1 day | Helm chart, `oc` access |
| **Phase 2** | Install VSO; sync KV secrets to K8s Secrets in agent namespaces | 1 day | Phase 1 |
| **Phase 3** | Enable Kubernetes auth; agents authenticate to Vault | 0.5 day | Phase 1 |
| **Phase 4** | Add GitHub secrets engine plugin for dynamic tokens | 1 day | Phase 3, GitHub App setup |
| **Phase 5** | Add database secrets engine for PostgreSQL | 0.5 day | Phase 3 |
| **Phase 6** | Integrate AuthBridge with Vault API | 2-3 days | Phase 3-4 |
| **Phase 7** | Add SPIRE OIDC federation for zero-secret auth | 1 day | Phase 3, SPIRE OIDC endpoint |

**Total estimated effort:** 7-8 days for full integration, starting from a working Kagenti deployment.

---

## Sources

- [Run Vault on OpenShift](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/helm/openshift)
- [Vault Helm Chart Configuration](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/helm/configuration)
- [vault-helm/values.openshift.yaml](https://github.com/hashicorp/vault-helm/blob/main/values.openshift.yaml)
- [VSO on OpenShift](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/vso/openshift)
- [Vault Integrated Storage Reference Architecture](https://developer.hashicorp.com/vault/tutorials/day-one-raft/raft-reference-architecture)
- [Vault SPIFFE Auth Method](https://developer.hashicorp.com/vault/docs/auth/spiffe)
- [SPIRE + OIDC + Vault](https://spiffe.io/docs/latest/keyless/vault/readme/)
- [Vault Enterprise 1.21 SPIFFE Auth](https://www.hashicorp.com/en/blog/vault-enterprise-1-21-spiffe-auth-fips-140-3-level-1-compliance-granular-secret-recovery)
- [Vault OpenAI Dynamic Secrets Plugin](https://www.hashicorp.com/en/blog/managing-openai-api-keys-with-hashicorp-vault-s-dynamic-secrets-plugin)
- [vault-plugin-secrets-github](https://github.com/martinbaillie/vault-plugin-secrets-github)
- [Vault Database Secrets Engine](https://developer.hashicorp.com/vault/docs/secrets/databases)
- [Vault Agent Injector Annotations](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/injector/annotations)
- [Kubernetes Vault Integration Comparison](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/comparisons)
- [Secure AI Agent Auth with Vault](https://developer.hashicorp.com/validated-patterns/vault/ai-agent-identity-with-hashicorp-vault)
- [SPIFFE for Agentic AI](https://www.hashicorp.com/en/blog/spiffe-securing-the-identity-of-agentic-ai-and-non-human-actors)
- [Vault Agent Sidecar Defaults Issue](https://github.com/hashicorp/vault-k8s/issues/216)
