# Kagenti Sandbox Guide (OpenShell)

This guide covers installing and using the Kagenti sandboxing feature powered by
[OpenShell](https://github.com/NVIDIA/OpenShell). Kagenti maintains a
[distribution fork](https://github.com/kagenti/OpenShell) with pre-built
binaries and Kagenti-specific patches. Sandboxes provide kernel-level isolation
for autonomous AI agents with credential protection and network policy
enforcement.

## Prerequisites

- `kubectl` (or `oc` for OpenShift) configured for your cluster
- Helm 3.x
- Docker (for Kind) or access to an OpenShift 4.16+ cluster
- An LLM API key (e.g., Anthropic)

## Install the OpenShell CLI

Download the latest release for your platform from
<https://github.com/kagenti/OpenShell/releases>:

```bash
# macOS (Apple Silicon)
curl -L https://github.com/kagenti/OpenShell/releases/latest/download/openshell-aarch64-apple-darwin.tar.gz | tar xz
sudo mv openshell /usr/local/bin/

# Linux (x86_64)
curl -L https://github.com/kagenti/OpenShell/releases/latest/download/openshell-x86_64-unknown-linux-musl.tar.gz | tar xz
sudo mv openshell /usr/local/bin/
```

Verify the installation:

```bash
openshell --version
```

## Platform Installation

Choose the section that matches your target environment.

---

### Kind (Local Development)

#### Step 1: Deploy Kagenti on Kind

```bash
scripts/kind/setup-kagenti.sh  --with-ui --with-agent-sandbox --with-spire
```

This deploys: Kind cluster, Istio ambient mesh, cert-manager, Keycloak, SPIRE,
and the Kagenti platform.

#### Step 2: Deploy OpenShell Shared Infrastructure

```bash
scripts/openshell/deploy-shared.sh
```

This creates:

- Sandbox controller CRDs
- Gateway API experimental CRDs (TLSRoute support)
- cert-manager CA chain (`ClusterIssuer: openshell-ca`)
- Keycloak realm `openshell` with PKCE client, roles, users, and groups

#### Step 3: Deploy Tenant Gateways

Each tenant gets an isolated namespace, gateway, and TLS certificates:

```bash
# Deploy one or both tenants
scripts/openshell/deploy-tenant.sh team1
scripts/openshell/deploy-tenant.sh team2
```

Each deployment creates an OpenShell gateway StatefulSet (gateway +
compute-driver + credentials-driver), mTLS certificates, RBAC, and an Istio
TLSRoute for external access.

Tenant endpoints on Kind:

| Tenant | Endpoint |
|--------|----------|
| team1  | `https://openshell-team1.localtest.me:30443` |
| team2  | `https://openshell-team2.localtest.me:30443` |

---

### OpenShift

First deploy the Kagenti platform on OpenShift. Refer to
[docs/ocp/openshift-install.md](ocp/openshift-install.md) for full installation
instructions including SPIRE setup (ZTWIM operator on OCP 4.19+, Helm charts on
4.16–4.18).

Once the platform is running (Keycloak, cert-manager, Istio), deploy the
OpenShell components:

#### Step 1: Deploy OpenShell Shared Infrastructure

```bash
scripts/openshell/deploy-shared.sh
```

This creates:

- Sandbox controller CRDs
- cert-manager CA chain (`ClusterIssuer: openshell-ca`)
- Keycloak realm `openshell` with PKCE client, roles, users, and groups

#### Step 2: Deploy Tenant Gateways

```bash
scripts/openshell/deploy-tenant.sh team1
scripts/openshell/deploy-tenant.sh team2
```

Each deployment creates an OpenShell gateway StatefulSet (gateway +
compute-driver + credentials-driver), mTLS certificates, RBAC, and an OpenShift
Route for external access.

Tenant endpoints follow the pattern
`https://openshell-<tenant>.<apps-domain>`.

After deployment, continue with [Configure the CLI](#configure-the-cli) below.

---

## Configure the CLI

Point the CLI at your tenant gateway:

```bash
scripts/openshell/configure-cli.sh team1
```

The script auto-detects the platform (Kind or OpenShift), registers the gateway
with the correct endpoint and OIDC issuer, and extracts mTLS certificates from
the cluster (`openshell-server-tls` and `openshell-client-tls` secrets in the
tenant namespace).

### OpenShift with Self-Signed Certificates

If your OpenShift cluster uses a self-signed or private CA (common in
disconnected or lab environments), the CLI will reject the gateway's TLS
certificate with an `UnknownIssuer` error. You need to trust the cluster's
ingress CA on your local machine.

Extract the OpenShift ingress CA:

```bash
# Get the default ingress CA bundle
oc get secret router-ca -n openshift-ingress-operator \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/ocp-ingress-ca.crt
```

Then trust it at the system level:

```bash
# macOS
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain /tmp/ocp-ingress-ca.crt

# Linux (RHEL/Fedora)
sudo cp /tmp/ocp-ingress-ca.crt /etc/pki/ca-trust/source/anchors/ocp-ingress-ca.crt
sudo update-ca-trust

# Linux (Debian/Ubuntu)
sudo cp /tmp/ocp-ingress-ca.crt /usr/local/share/ca-certificates/ocp-ingress-ca.crt
sudo update-ca-certificates
```

Alternatively, if you prefer not to modify system trust, set the
`SSL_CERT_FILE` environment variable before running CLI commands:

```bash
export SSL_CERT_FILE=/tmp/ocp-ingress-ca.crt
openshell gateway login
```

## Log In

```bash
openshell gateway login
```

This opens a browser for Keycloak OIDC PKCE authentication. Use one of the
preconfigured users:

| User  | Password | Teams        | Role  |
|-------|----------|--------------|-------|
| alice | alice123 | team1        | admin |
| bob   | bob123   | team2        | admin |
| admin | admin123 | team1, team2 | admin |

## Create a Provider

Providers define how the sandbox connects to an LLM. You must be logged in as an
admin user.

```bash
export ANTHROPIC_AUTH_TOKEN="your-api-key-here"

openshell provider create --name claude --type anthropic \
  --credential ANTHROPIC_AUTH_TOKEN \
  --config ANTHROPIC_BASE_URL=<your llm provider URL>

# for example
openshell provider create --name claude --type anthropic \
  --credential ANTHROPIC_AUTH_TOKEN \
  --config ANTHROPIC_BASE_URL=https://ete-litellm.bx.cloud9.ibm.com 
```

Key points:

- `--type` must be `anthropic`, `openai`, or `nvidia` (these are the supported
  inference routing types)
- API keys go in `--credential` (managed by SecretResolver, never exposed to the
  sandbox)
- Base URLs go in `--config` (used for inference route resolution only)

## Configure Inference Routing

```bash
openshell inference set --provider claude --model claude-sonnet-4-6 --no-verify
```

This tells the gateway how to route `inference.local` requests from inside the
sandbox to the upstream LLM endpoint.

## Create a Sandbox

```bash
openshell sandbox create --provider claude --no-auto-providers -- claude
```
**Note**: The community NVIDIA sandbox image is quite large. On first use, 
Kubernetes may take a few minutes to download the image and start the sandbox.


Flags:

| Flag | Purpose |
|------|---------|
| `--provider claude` | Bind the named provider to this sandbox |
| `--no-auto-providers` | Don't auto-create providers from local env vars |
| `-- claude` | Command to run inside the sandbox (Claude Code) |

The sandbox pod starts with:

- Network isolation (only `inference.local` allowed outbound)
- Credential protection (API keys resolved at the proxy layer, never in the
  sandbox env)
- Kernel-level enforcement (Landlock, seccomp)

## Connect to an Existing Sandbox

```bash
# Interactive session
openshell sandbox connect

# Run a one-off command
openshell sandbox exec -n <sandbox-name> -- claude --print "Hello"
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `deploy-tenant.sh` hangs at Helm `--wait` | `openshell` Keycloak realm does not exist (gateway OIDC init fails in a crash loop) | Run `deploy-shared.sh` first; verify realm with `kubectl exec keycloak-0 -n keycloak -- /opt/keycloak/bin/kcadm.sh get realms` |
| `deploy-shared.sh` hangs at "Logging in to Keycloak" | `keycloak-initial-admin` secret password doesn't match the DB (common after Keycloak pod recreation on RHBK) | See [Keycloak credential mismatch](#keycloak-credential-mismatch) below |
| `invalid peer certificate: UnknownIssuer` | CLI missing CA/client certs | Re-run `configure-cli.sh` or place `ca.crt`, `tls.crt`, `tls.key` in `~/.config/openshell/gateways/<name>/mtls/` |
| `POST openshell:80/... not permitted by policy` | URL placed in `--credential` instead of `--config` | Recreate provider with URL in `--config` |
| `Failed to connect to api.anthropic.com` | CLI auto-created a provider with wrong type | Use `--no-auto-providers` flag |
| `/v1/v1/messages` double path | `ANTHROPIC_BASE_URL` includes a trailing `/v1` | Remove `/v1` suffix — the SDK appends its own |
| `context_management: Extra inputs not permitted` | LiteLLM rejects experimental beta parameters | Set `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` in the provider config |
| `connection not allowed by policy` | Inference bundle not loaded | Run `openshell inference get` and verify route count |

### Keycloak Credential Mismatch

On RHBK (Red Hat Build of Keycloak), the `bootstrapAdmin` user is only created
on first database initialization. If Keycloak is later redeployed (operator
reconciliation, pod eviction, etc.), the `keycloak-initial-admin` secret may be
regenerated with a new password while the database retains the original
credentials. This causes `deploy-shared.sh` to hang at the kcadm login step.

To fix, reset the admin password via the database:

```bash
# Read username and password from the secret (avoids hardcoding env-specific values)
KC_USER=$(kubectl get secret keycloak-initial-admin -n keycloak \
  -o jsonpath='{.data.username}' | base64 -d)
KC_PASS=$(kubectl get secret keycloak-initial-admin -n keycloak \
  -o jsonpath='{.data.password}' | base64 -d)

# Find the admin user ID
ADMIN_ID=$(kubectl exec -n keycloak postgres-kc-0 -- psql -U postgres -d postgres -tA -c \
  "SELECT id FROM user_entity ue JOIN realm r ON ue.realm_id=r.id WHERE r.name='master' AND ue.username='${KC_USER}';")

# Read hash iterations from the existing credential (varies by Keycloak version)
ITERS=$(kubectl exec -n keycloak postgres-kc-0 -- psql -U postgres -d postgres -tA -c \
  "SELECT credential_data::json->>'hashIterations' FROM credential WHERE user_id='${ADMIN_ID}';")

# Generate a new password hash matching the secret
python3 -c "
import hashlib, base64, os, json
dk = hashlib.pbkdf2_hmac('sha256', '${KC_PASS}'.encode(), (salt := os.urandom(16)), ${ITERS})
print(json.dumps({'value': base64.b64encode(dk).decode(), 'salt': base64.b64encode(salt).decode(), 'additionalParameters': {}}))
" > /tmp/kc-secret-data.json
chmod 600 /tmp/kc-secret-data.json

# Update the credential in the database
kubectl exec -n keycloak postgres-kc-0 -- psql -U postgres -d postgres -c \
  "UPDATE credential SET secret_data='$(cat /tmp/kc-secret-data.json)',
   credential_data='{\"hashIterations\":${ITERS},\"algorithm\":\"pbkdf2-sha256\",\"additionalParameters\":{}}'
   WHERE user_id='${ADMIN_ID}';"

rm -f /tmp/kc-secret-data.json
```

After updating, re-run `deploy-shared.sh`.

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ openshell   │────▶│ OpenShell        │────▶│ Keycloak         │
│ CLI         │     │ Gateway          │     │ (OIDC PKCE)      │
└─────────────┘     └──────────────────┘     └──────────────────┘
                           │
                    ┌──────┴──────┐
                    ▼             ▼
           ┌──────────────┐  ┌───────────────────┐
           │ Compute      │  │ Sandbox Pod        │
           │ Driver       │  │ ┌───────────────┐  │
           │ (creates pod)│  │ │ Supervisor    │  │
           └──────────────┘  │ │ + HTTP Proxy  │  │
                             │ └───────┬───────┘  │
                             │         │          │
                             │         ▼          │
                             │ ┌───────────────┐  │
                             │ │ Claude Code   │  │
                             │ │ (sandboxed)   │  │
                             │ └───────────────┘  │
                             └───────────────────┘
                                       │
                                       ▼
                             ┌───────────────────┐
                             │ LLM Upstream      │
                             │ (via inference    │
                             │  proxy routing)   │
                             └───────────────────┘
```

The sandbox never sees raw API keys. Credentials are resolved at the proxy layer
inside the supervisor, which intercepts requests to `inference.local` and injects
the real API key before forwarding to the upstream LLM.
