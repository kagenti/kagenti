# Authentication Guide

Kagenti supports two modes for how the operator and agent/tool workloads authenticate to Keycloak:

| Mode | Operator authenticates as | Agents/tools authenticate as | Requires |
|---|---|---|---|
| **Client secrets** (default) | Admin credentials (`keycloak-admin-secret`) | Per-workload OAuth2 client secret | Nothing extra |
| **SPIFFE auth** (recommended) | Its own SPIFFE identity (JWT-SVID) | Their own SPIFFE identity (JWT-SVID) | SPIRE deployed |

The two modes are independent and can be mixed — you can enable SPIFFE auth for the operator while agents still use client secrets, or vice versa.

---

## How SPIFFE Authentication Works

### Background: JWT-SVID and Keycloak

SPIRE issues each workload a **JWT-SVID** — a short-lived, cryptographically signed JWT containing the workload's SPIFFE identity. When a component wants to authenticate to Keycloak, it presents this JWT-SVID as a client assertion (RFC 7523). Keycloak validates the signature via the SPIFFE Identity Provider (backed by SPIRE's OIDC Discovery Provider) and issues an access token.

The JWT's `aud` (audience) claim must equal Keycloak's realm issuer URL — the URL Keycloak advertises in its OIDC discovery document:

```bash
curl http://keycloak.your-domain.com/realms/kagenti/.well-known/openid-configuration | jq .issuer
```

This is always `keycloak.publicUrl/realms/<realm>` and is derived automatically from your Helm values — no separate configuration needed.

> **Important:** The audience must be the **external/public URL**, not the in-cluster service address. `http://keycloak-service.keycloak.svc:8080` causes a silent mismatch because Keycloak's issuer is configured with the external URL.

### Operator SPIFFE Auth Flow

**At install time** — a Helm post-install/upgrade Job (`operator-client-bootstrap`) runs once:
1. Creates a SPIFFE Identity Provider in Keycloak pointing at SPIRE's OIDC Discovery Provider
2. Creates a Keycloak client for the operator with `clientAuthenticatorType: federated-jwt` and the operator's SPIFFE ID as subject
3. Assigns the `manage-clients` role (scoped — not full admin)

After this job completes, the operator never needs admin credentials again.

**On every reconcile** — when the operator registers an agent client:
1. The spiffe-helper sidecar fetches the operator's JWT-SVID from the SPIRE workload API socket and writes it to `/opt/jwt_svid.token`
2. The operator reads the JWT-SVID and exchanges it for a Keycloak access token using the `jwt-spiffe` assertion type
3. The operator uses that token to call the Keycloak Admin API

```
Operator pod
├─ spiffe-helper sidecar ──→ SPIRE workload API
│   writes JWT-SVID to /opt/jwt_svid.token
└─ manager binary
    reads JWT-SVID → exchanges with Keycloak → access token → Admin API
```

### Agent/Tool SPIFFE Auth Flow

**Per workload at registration time** — when the operator detects a new agent/tool Deployment with `CLIENT_AUTH_TYPE=federated-jwt`:
1. Creates a Keycloak client with `clientAuthenticatorType: federated-jwt` and the workload's SPIFFE ID as subject
2. Does **not** create a credential Secret — AuthBridge reads JWT-SVIDs directly

**On every outbound request** — AuthBridge in the agent pod:
1. Fetches the workload's JWT-SVID from the SPIRE workload API socket (via the go-spiffe SDK, no separate binary)
2. Exchanges it for a Keycloak access token
3. Attaches the token to the outbound request

```
Agent pod
└─ authbridge-proxy sidecar
    fetches JWT-SVID from SPIRE workload API → exchanges with Keycloak → attaches token to requests
```

---

## Enabling SPIFFE Authentication

### Prerequisites

- SPIRE deployed (`--with-spire`)
- `keycloak.publicUrl` set in your Helm values (e.g. `http://keycloak.localtest.me:8080`)
- `kagenti-operator-chart:0.3.0-alpha.7` or later

### Using setup-kagenti.sh

```bash
# Operator SPIFFE auth only
# Operator → Keycloak uses JWT-SVID; agents still use client secrets
scripts/kind/setup-kagenti.sh --with-spire --enable-operator-spiffe-auth

# Agent/tool SPIFFE auth only
# Agents → Keycloak uses JWT-SVID; operator still uses admin credentials
scripts/kind/setup-kagenti.sh --with-spire --enable-agent-spiffe-auth

# Both — no provisioned credentials needed at all
scripts/kind/setup-kagenti.sh --with-spire --enable-spiffe-auth
```

Both flags require `--with-spire` and will fail immediately with a clear error if SPIRE is not enabled.

### Manual Helm values

```yaml
keycloak:
  publicUrl: "http://keycloak.your-domain.com"   # required

kagenti-operator-chart:
  spiffe:
    enabled: true
    operatorAuth:
      enabled: true
      bootstrapImage: "ghcr.io/kagenti/kagenti/operator-spiffe-bootstrap:latest"

authBridge:
  clientAuthType: "federated-jwt"
  spiffeIdpAlias: "spire-spiffe"

spire:
  enabled: true
```

---

## Using the Default (Client Secrets) Mode

When SPIFFE auth is not enabled, Kagenti uses provisioned OAuth2 credentials:

- **`keycloak-admin-secret`** in `kagenti-system` — admin credentials for the operator to register agent clients. Created automatically by the installer from `keycloak-initial-admin`.
- **Per-agent client secrets** — created by the operator's `ClientRegistrationReconciler` and stored as `kagenti-keycloak-client-credentials-*` Secrets in agent namespaces.

This mode requires no SPIRE and works out of the box on any install.

### Turning off SPIFFE auth

If SPIFFE auth is currently enabled and you want to revert to client secrets:

```bash
scripts/kind/setup-kagenti.sh ... \
  --kagenti-values <(cat <<'EOF'
kagenti-operator-chart:
  spiffe:
    enabled: false
    operatorAuth:
      enabled: false
authBridge:
  clientAuthType: "client-secret"
EOF
)
```

### Manual sync (break-glass)

If `keycloak-admin-secret` goes out of sync after a Keycloak credential rotation:

```bash
KC_USER=$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.username}' | base64 -d)
KC_PASS=$(kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath='{.data.password}' | base64 -d)

kubectl create secret generic keycloak-admin-secret -n kagenti-system \
  --from-literal=KEYCLOAK_ADMIN_USERNAME="$KC_USER" \
  --from-literal=KEYCLOAK_ADMIN_PASSWORD="$KC_PASS" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Then re-run `helm upgrade` to trigger a new `kagenti-agent-oauth-secret-job` run.

---

## Verifying Authentication

### Operator SPIFFE auth active

```bash
POD=$(kubectl get pod -n kagenti-system -l control-plane=controller-manager \
  -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n kagenti-system $POD -c manager | grep "SPIFFE ID authentication enabled"
# Expected: {"msg":"SPIFFE ID authentication enabled: using JWT-SVID for client registration",...}
```

### Agent registered with SPIFFE identity

```bash
kubectl get secret -n team1 | grep kagenti-keycloak-client-credentials
# In client-secret mode: expect a Secret per agent
# In federated-jwt mode: expect nothing (no Secrets created)

# Check client ID in the Secret (client-secret mode)
kubectl get secret <secret-name> -n team1 \
  -o jsonpath='{.data.client-id\.txt}' | base64 -d
# Expected in federated-jwt mode: spiffe://localtest.me/ns/team1/sa/<workload>
# Expected in client-secret mode: team1/<workload>
```

### Direct JWT-SVID token exchange (agent)

```bash
AGENT_POD=$(kubectl get pod -n team1 -l app.kubernetes.io/name=<agent> \
  -o jsonpath='{.items[0].metadata.name}')
JWT_SVID=$(kubectl exec -n team1 $AGENT_POD -c authbridge-proxy -- cat /opt/jwt_svid.token)
CLIENT_ID="spiffe://localtest.me/ns/team1/sa/<agent-sa>"

kubectl run --rm -i --restart=Never verify --image=curlimages/curl -n kagenti-system \
  --env="JWT=$JWT_SVID" --env="CID=$CLIENT_ID" -- \
  sh -c 'curl -s -w "\nHTTP:%{http_code}" -X POST \
    "http://keycloak-service.keycloak.svc:8080/realms/kagenti/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials&client_id=${CID}&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-spiffe&client_assertion=${JWT}"' \
  | grep -E "HTTP:|access_token|error"
# Expected: HTTP:200 with access_token
```

---

## Troubleshooting

### Operator not using SPIFFE auth

Check whether both flags are set:
```bash
helm get values kagenti -n kagenti-system | grep -A 5 "spiffe:"
# spiffe.enabled and spiffe.operatorAuth.enabled must both be true
```

### Pods stuck in Init:0/1 (federated-jwt mode)

The agent pod is waiting for a credential Secret that doesn't exist (correct behavior in `federated-jwt` mode, but older operator versions still injected the annotation). Requires `kagenti-operator-chart:0.3.0-alpha.7` or later.

### Bootstrap job failed

```bash
kubectl logs -n keycloak job/kagenti-operator-client-bootstrap --tail=50
```

Common cause: `keycloak.publicUrl` not set, causing an empty JWT audience and Keycloak rejecting the SPIFFE IdP configuration.

### JWT validation fails (invalid_client)

Verify that `keycloak.publicUrl` matches Keycloak's actual issuer:
```bash
curl -s http://keycloak.localtest.me:8080/realms/kagenti/.well-known/openid-configuration | jq .issuer
```

The value must exactly match what was passed as `keycloak.publicUrl`. A mismatch between the external URL and the in-cluster service address is the most common cause.
