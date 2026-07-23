---
description: SPIFFE, Oauth2, and Keycloak
---

# Authentication Guide

Rossoctl supports two modes for how the operator and agent/tool workloads authenticate to Keycloak:

| Mode | How operator authenticates | How agents authenticate | Requires |
|---|---|---|---|
| **Client secrets** (default) | Admin credentials (`keycloak-admin-secret`) | Per-workload OAuth2 client secret | Nothing extra |
| **SPIFFE auth** (recommended) | SPIFFE identity (JWT-SVID) | SPIFFE identity (JWT-SVID) | SPIRE deployed |

Both modes are independent — you can enable SPIFFE auth for the operator while agents still use client secrets, or vice versa.

---

## Client Secrets (Default)

In this mode, the operator uses admin credentials to register Keycloak clients on behalf of each agent and tool workload. Each workload receives a provisioned OAuth2 client secret stored as a Kubernetes Secret in its namespace.

### How it works

1. At install time, the `rossoctl-agent-oauth-secret-job` Helm Job reads admin credentials from the `keycloak-initial-admin` Secret (managed by the RHBK operator) and creates a `rossoctl-keycloak-client-secret` in each agent namespace with the per-workload OAuth2 client credentials.
2. When the operator's `ClientRegistrationReconciler` detects a new agent/tool Deployment, it reads `keycloak-initial-admin` directly and uses those credentials to register an OAuth2 client in Keycloak.
3. The operator stores the generated `client_id` and `client_secret` in a `rossoctl-keycloak-client-credentials-*` Secret in the agent's namespace.
4. AuthBridge reads the credential files from the mounted Secret and uses them for token exchange on outbound requests.

### Setup

No extra configuration needed — this mode works out of the box on any install.

The per-agent credential Secrets are created on-demand by the operator when each workload is deployed.

### Configuring the admin secret source

By default the operator reads admin credentials from the `keycloak-initial-admin` Secret in the keycloak namespace. This is configurable:

```yaml
keycloak:
  adminSecretName: keycloak-initial-admin  # Secret in the keycloak namespace
  adminUsernameKey: username
  adminPasswordKey: password
```

### Manual sync (break-glass)

If the operator is failing to authenticate to Keycloak after a credential rotation, restart it so it re-reads `keycloak-initial-admin`:

```bash
kubectl rollout restart deployment/rossoctl-controller-manager -n rossoctl-system
```

Verify the operator is authenticating successfully:

```bash
POD=$(kubectl get pod -n rossoctl-system -l control-plane=controller-manager \
  -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n rossoctl-system $POD -c manager | grep -i "keycloak\|auth" | tail -5
```

---

## SPIFFE Authentication (Recommended)

In this mode, the operator and agents authenticate to Keycloak using their SPIFFE identities (JWT-SVIDs). No credentials are provisioned or stored.

### How it works

**JWT-SVID and Keycloak**

SPIRE issues each workload a JWT-SVID — a short-lived, cryptographically signed JWT containing the workload's SPIFFE identity (e.g. `spiffe://localtest.me/ns/team1/sa/weather-service`). When presenting this to Keycloak as a client assertion (RFC 7523), the JWT's `aud` claim must equal Keycloak's realm issuer URL.

This URL is always `keycloak.publicUrl/realms/<realm>` — derived automatically from your Helm values. **It must be the external/public URL**, not the in-cluster service address, because Keycloak's issuer is configured with the external URL and the check is a string comparison.

**Operator authentication flow**

At install time, a Helm post-install/upgrade Job (`operator-client-bootstrap`) runs once using admin credentials to configure Keycloak:
1. Creates a SPIFFE Identity Provider in Keycloak (backed by SPIRE's OIDC Discovery Provider)
2. Creates a Keycloak client for the operator with `clientAuthenticatorType: federated-jwt` and the operator's SPIFFE ID as subject
3. Assigns `manage-clients` role (scoped — not full admin)

After this, the operator authenticates on every reconcile by reading its JWT-SVID (written by the spiffe-helper sidecar to `/opt/jwt_svid.token`) and exchanging it for a Keycloak access token.

```
Operator pod
├─ spiffe-helper sidecar ──→ SPIRE workload API
│   writes JWT-SVID to /opt/jwt_svid.token (auto-rotates)
└─ manager binary
    reads JWT-SVID → exchanges with Keycloak → access token → Admin API
```

**Agent/tool authentication flow**

When the operator registers an agent with `CLIENT_AUTH_TYPE=federated-jwt`:
1. Creates a Keycloak client with `clientAuthenticatorType: federated-jwt` and the workload's SPIFFE ID as subject
2. Does **not** create a credential Secret — AuthBridge reads JWT-SVIDs directly

AuthBridge fetches the workload's JWT-SVID from the SPIRE workload API socket (via the go-spiffe SDK) and exchanges it for a Keycloak access token on every outbound request.

```
Agent pod
└─ authbridge-proxy sidecar
    fetches JWT-SVID from SPIRE workload API
    → exchanges with Keycloak
    → attaches access token to outbound requests
```

### Prerequisites

- SPIRE deployed (`--with-spire`)
- `keycloak.publicUrl` set to the URL Keycloak uses as its OIDC issuer — check with:
  ```bash
  curl http://keycloak.your-domain.com/realms/rossoctl/.well-known/openid-configuration | jq .issuer
  ```
- `operator-chart:0.3.0-alpha.7` or later

### Enabling SPIFFE auth

**Via `setup-rossoctl.sh`:**

```bash
# Operator SPIFFE auth only (agents still use client secrets)
scripts/kind/setup-rossoctl.sh --with-spire --enable-operator-spiffe-auth

# Agent/tool SPIFFE auth only (operator still uses admin credentials)
scripts/kind/setup-rossoctl.sh --with-spire --enable-agent-spiffe-auth

# Both — no provisioned credentials needed
scripts/kind/setup-rossoctl.sh --with-spire --enable-spiffe-auth
```

Both flags fail immediately with a clear error if `--with-spire` is not set.

**Via Helm values:**

```yaml
keycloak:
  publicUrl: "http://keycloak.your-domain.com"   # required

operator-chart:
  spiffe:
    enabled: true
    operatorAuth:
      enabled: true
      bootstrapImage: "ghcr.io/rossoctl/rossoctl/operator-spiffe-bootstrap:latest"

authBridge:
  clientAuthType: "federated-jwt"
  spiffeIdpAlias: "spire-spiffe"

spire:
  enabled: true
```

### Disabling SPIFFE auth (reverting to client secrets)

```bash
scripts/kind/setup-rossoctl.sh ... \
  --rossoctl-values <(cat <<'EOF'
operator-chart:
  spiffe:
    enabled: false
    operatorAuth:
      enabled: false
authBridge:
  clientAuthType: "client-secret"
EOF
)
```

---

## Verifying Authentication

### Check which mode is active

```bash
# Operator mode
POD=$(kubectl get pod -n rossoctl-system -l control-plane=controller-manager \
  -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n rossoctl-system $POD -c manager | grep -E "SPIFFE ID authentication enabled|Client registration controller enabled"

# Agent mode
kubectl get configmap authbridge-config -n team1 -o jsonpath='{.data.CLIENT_AUTH_TYPE}'
# client-secret  or  federated-jwt
```

### Check agent registration (client secrets mode)

```bash
kubectl get secret -n team1 | grep rossoctl-keycloak-client-credentials
# Expect one Secret per registered agent/tool workload
```

### Check agent registration (SPIFFE auth mode)

```bash
kubectl get secret -n team1 | grep rossoctl-keycloak-client-credentials
# Expect nothing — no credential Secrets are created

# Verify the agent's SPIFFE ID was registered
POD=$(kubectl get pod -n rossoctl-system -l control-plane=controller-manager \
  -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n rossoctl-system $POD -c manager | grep "operator client registration applied"
# The "secret" field shows what the Secret name would be — but it is not created
```

### Direct token exchange test (SPIFFE auth)

```bash
AGENT_POD=$(kubectl get pod -n team1 -l app.kubernetes.io/name=<agent> \
  -o jsonpath='{.items[0].metadata.name}')
JWT_SVID=$(kubectl exec -n team1 $AGENT_POD -c authbridge-proxy -- cat /opt/jwt_svid.token)
CLIENT_ID="spiffe://localtest.me/ns/team1/sa/<agent-serviceaccount>"

kubectl run --rm -i --restart=Never verify --image=curlimages/curl -n rossoctl-system \
  --env="JWT=$JWT_SVID" --env="CID=$CLIENT_ID" -- \
  sh -c 'curl -s -w "\nHTTP:%{http_code}" -X POST \
    "http://keycloak-service.keycloak.svc:8080/realms/rossoctl/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials&client_id=${CID}&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-spiffe&client_assertion=${JWT}"' \
  | grep -E "HTTP:|access_token|error"
# Expected: HTTP:200 with access_token
```

---

## Troubleshooting

### Client secrets mode: `keycloak-admin-secret` out of sync

Symptom: operator logs show Keycloak authentication failures.
Fix: re-run the break-glass sync in the [manual sync](#manual-sync-break-glass) section above.

### SPIFFE mode: operator not using JWT-SVID

Check both flags are set:
```bash
helm get values rossoctl -n rossoctl-system | grep -A 5 "spiffe:"
# spiffe.enabled and spiffe.operatorAuth.enabled must both be true
```

### SPIFFE mode: pods stuck in `Init:0/1`

Requires `operator-chart:0.3.0-alpha.7` or later. Earlier versions still inject a credential volume mount in `federated-jwt` mode, causing pods to wait for a Secret that is never created.

### SPIFFE mode: bootstrap job failed

```bash
kubectl logs -n keycloak job/rossoctl-operator-client-bootstrap --tail=50
```

Most common cause: `keycloak.publicUrl` not set, resulting in an empty JWT audience string.

### SPIFFE mode: `invalid_client` from Keycloak

Verify the audience matches Keycloak's issuer exactly:
```bash
curl -s http://keycloak.localtest.me:8080/realms/rossoctl/.well-known/openid-configuration | jq .issuer
```

The value must match `keycloak.publicUrl`. Using the in-cluster service address instead of the external URL is the most common cause of this error.
