---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Rossoctl Sandbox Guide (OpenShell)

This guide covers installing and using the Rossoctl sandboxing feature powered by
[OpenShell](https://github.com/NVIDIA/OpenShell). Rossoctl maintains a
[distribution fork](https://github.com/rossoctl/OpenShell) (`mvp-v2` branch) with
Rossoctl-specific multitenancy patches. The upstream CLI works as-is — no
fork-specific build is needed. Sandboxes provide kernel-level isolation for
autonomous AI agents with credential protection and network policy enforcement.

## Prerequisites

- `kubectl` (or `oc` for OpenShift) configured for your cluster
- Helm 3.x
- Docker (for Kind) or access to an OpenShift 4.16+ cluster
- An LLM API key (e.g., Anthropic)

## Install the OpenShell CLI

Install the upstream OpenShell CLI (fully compatible with the Rossoctl gateway):

```bash
# Via the official install script
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
```

Or via PyPI:

```bash
uv tool install openshell
```

Verify the installation:

```bash
openshell --version
```

## Step 1: Deploy Rossoctl (Platform-Specific)

Choose the command that matches your target environment:

### Kind (Local Development)

```bash
scripts/kind/setup-rossoctl.sh --with-ui --with-agent-sandbox --with-spire
```

This deploys: Kind cluster, Istio ambient mesh, cert-manager, Keycloak, SPIRE,
and the Rossoctl platform.

### OpenShift

```bash
scripts/ocp/setup-rossoctl.sh --with-agent-sandbox --with-spire
```

Refer to [docs/ocp/openshift-install.md](ocp/openshift-install.md) for full
installation instructions including SPIRE setup (ZTWIM operator on OCP 4.19+,
Helm charts on 4.16–4.18).

> **Note:** If your OpenShift cluster uses a self-signed or private CA, see
> [OpenShift with Self-Signed Certificates](#openshift-with-self-signed-certificates)
> at the end of this guide before configuring the CLI.

## Step 2: Deploy OpenShell Shared Infrastructure

```bash
scripts/openshell/deploy-shared.sh
```

This creates:

- Sandbox controller CRDs
- Gateway API experimental CRDs (TLSRoute support)
- cert-manager CA chain (`ClusterIssuer: openshell-ca`)
- Keycloak realm `openshell` with PKCE client, roles, users, and groups

## Step 3: Deploy Tenant Gateways

Each tenant gets an isolated namespace, gateway, and TLS certificates:

```bash
# Deploy one or both tenants
scripts/openshell/deploy-tenant.sh team1
scripts/openshell/deploy-tenant.sh team2
```

Each deployment creates an OpenShell gateway StatefulSet (gateway +
compute-driver + credentials-driver), mTLS certificates, RBAC, and an Istio
TLSRoute (Kind) or OpenShift Route for external access.

Tenant endpoints:

| Platform | Tenant | Endpoint |
|----------|--------|----------|
| Kind | team1 | `https://openshell-team1.localtest.me:30443` |
| Kind | team2 | `https://openshell-team2.localtest.me:30443` |
| OpenShift | team1 | `https://openshell-team1.<apps-domain>` |
| OpenShift | team2 | `https://openshell-team2.<apps-domain>` |

## Step 4: Configure the CLI

Point the CLI at your tenant gateway:

```bash
scripts/openshell/configure-cli.sh team1
```

The script auto-detects the platform (Kind or OpenShift), registers the gateway
with the correct endpoint and OIDC issuer, extracts mTLS certificates from the
cluster, and authenticates via OIDC.

> **Important:** Do not run `configure-cli.sh` if you have already registered
> the gateway in the same CLI session (e.g., from a previous
> `configure-cli.sh` run). If you need to re-register, first remove the
> existing gateway:
>
> ```bash
> openshell gateway remove openshell-team1
> scripts/openshell/configure-cli.sh team1
> ```

## Step 5: Log In

If you are not already authenticated (the configure-cli script opens a browser
automatically), log in manually:

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

## Step 6: Create a Provider

Providers define how the sandbox connects to an LLM. You must be logged in as an
admin user. The guide works with any OpenAI-compatible or Anthropic-compatible
endpoint — you just supply your own base URL and API key.

```bash
export ANTHROPIC_AUTH_TOKEN="your-api-key-here"

openshell provider create --name claude --type anthropic \
  --credential ANTHROPIC_AUTH_TOKEN \
  --config ANTHROPIC_BASE_URL=<your llm provider URL>
```

The `ANTHROPIC_BASE_URL` should point to whatever inference endpoint you use.
Examples for common providers:

| Provider | Base URL |
|----------|----------|
| Anthropic (direct) | `https://api.anthropic.com` |
| LiteLLM proxy | `https://your-litellm-instance.example.com` |
| Azure OpenAI | `https://<resource>.openai.azure.com` |

For instance, if you run a LiteLLM proxy internally:

```bash
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
- Any OpenAI-compatible or Anthropic-compatible endpoint works — the sandbox
  routes to whatever URL you configure

## Step 7: Configure Inference Routing

```bash
openshell inference set --provider claude --model claude-sonnet-4-6 --no-verify
```

This tells the gateway how to route `inference.local` requests from inside the
sandbox to the upstream LLM endpoint.

## Step 8: Create a Sandbox

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

## Per-User Sandbox Ownership

When OIDC is enabled on the gateway (the default), each sandbox is owned by the
user who created it. The gateway stamps an `openshell.ai/owner` label with the
caller's JWT `sub` claim — this is server-enforced and cannot be spoofed by
clients.

### How it works

| Operation | Behavior |
|-----------|----------|
| **Create** | Owner label set from verified OIDC identity. Client-supplied `openshell.ai/` labels are stripped. |
| **List** | Returns only the caller's sandboxes (filtered by owner label). |
| **Get / Delete / Connect / Exec** | Returns `PermissionDenied` if caller is not the owner. |
| **Admin** | Users with the `openshell-admin` role bypass ownership checks and can manage all sandboxes. |

### Shared gateway, multiple users

A single gateway instance serves all team members. Each user sees only their own
sandboxes:

```bash
# Alice creates her sandbox
openshell sandbox create --provider claude -- claude
# Alice's list shows only her sandboxes
openshell sandbox list

# Bob (on the same gateway) creates his sandbox
openshell sandbox create --provider claude -- claude
# Bob's list shows only his sandboxes — Alice's are not visible
openshell sandbox list
```

No configuration is needed — ownership enforcement is automatic when OIDC is
enabled.

### Admin access

Users with the `openshell-admin` Keycloak role can list and manage all sandboxes
regardless of owner:

```bash
# Admin sees all sandboxes across all users
openshell sandbox list

# Admin can delete another user's sandbox
openshell sandbox delete <sandbox-name>
```

The preconfigured Keycloak users in the `openshell` realm have admin access by
default. To grant admin to a new user, assign the `openshell-admin` role in
Keycloak.

### Requirements

- Gateway image `v0.0.56-rc.2` or later (provider ownership requires `v0.0.56-rc.3`+)
- OIDC enabled on the gateway (`oidc.enabled: true` in Helm values — the default)
- Keycloak `sub` claim must be a UUID (the default for Keycloak realms)

When OIDC is disabled (local development without authentication), ownership is
skipped and all users share all sandboxes (backward-compatible behavior).

## Per-User Provider Ownership

When OIDC is enabled, providers are also scoped by ownership — the same pattern
as sandboxes. Each user can create providers with any name, and those providers
are isolated from other users. Admin-created providers remain shared and
accessible to everyone.

### Provider types

| Provider type | Owner label | Visible to | Created by |
|---------------|-------------|------------|------------|
| Shared (team) | none | All users | Admin |
| User-owned | `openshell.ai/owner=<sub>` | Owner + admin | User |

### Resolution order (who wins)

When a sandbox references a provider by name, the gateway resolves it in this
order:

1. **User's own provider** — if the caller owns a provider with that name, it wins
2. **Shared provider** — fallback to an admin-created provider with the same name

This means if an admin created a shared `openai` provider and Bob also creates
his own `openai` provider, Bob's sandbox will always bind to Bob's provider.
The shared one is only used when the user doesn't have their own with that name.

### Example: per-user credentials on a shared gateway

```bash
# Bob creates his own GitHub provider with his personal PAT
export GH_TOKEN="ghp_bob_xxx"
openshell provider create --name gh --type custom \
  --credential GH_TOKEN \
  --config BASE_URL=https://api.github.com

# Alice creates her own — no conflict, scoped by owner
export GH_TOKEN="ghp_alice_yyy"
openshell provider create --name gh --type custom \
  --credential GH_TOKEN \
  --config BASE_URL=https://api.github.com

# Bob's sandbox uses Bob's key automatically
openshell sandbox create --provider gh -- bash

# Alice's sandbox uses Alice's key — no cross-contamination
openshell sandbox create --provider gh -- bash

# Neither user can see or bind to the other's provider
openshell provider list   # Shows only own + shared providers
```

### Cross-user isolation guarantees

- Users see only their own providers plus shared (admin-created) providers
- A sandbox cannot bind to another user's provider — the gateway rejects it
- Provider name uniqueness is scoped to `(owner, name)` — alice and bob can
  both have a provider named `gh`
- Admin users bypass ownership and can list/manage all providers

### Requirements

- Gateway image `v0.0.56-rc.3` or later
- OIDC enabled on the gateway (`oidc.enabled: true` — the default)

When OIDC is disabled, provider ownership is skipped and all providers are
shared (backward-compatible behavior).

## Network Egress Policies

By default, sandboxes have no outbound network access except to
`inference.local` (the LLM proxy). To allow a sandbox to reach external
services (e.g., GitHub for `git clone`, package registries, APIs), declare
a network policy.

### Create a sandbox with an egress policy

Write a policy YAML that lists allowed endpoints:

```yaml
# github-egress.yaml
version: 1
filesystem_policy:
  include_workdir: true
  read_only:
    - /usr
    - /lib
    - /lib64
    - /etc
    - /bin
    - /sbin
  read_write:
    - /tmp
    - /sandbox
    - /dev/null
    - /dev/urandom
network_policies:
  github:
    name: "Allow GitHub"
    endpoints:
      - host: "github.com"
        port: 443
      - host: "api.github.com"
        port: 443
```

Create the sandbox with `--policy` and a command (the entrypoint process is
required for the network proxy to function):

```bash
# With an interactive tool
openshell sandbox create --policy github-egress.yaml -- claude

# Or as a persistent sandbox for exec sessions
openshell sandbox create --policy github-egress.yaml -- sleep infinity
```

No binary restrictions are needed — `git`, `curl`, `python`, and any other
tool in the sandbox can use the allowed endpoints. The endpoint declaration
is the access gate.

Verify egress inside the sandbox:

```bash
openshell sandbox exec -- curl -sS -o /dev/null -w "%{http_code}" https://github.com
# 200

# git clone works with just github.com:443 in the policy
openshell sandbox exec -- git clone https://github.com/rossoctl/rossoctl.git /tmp/repo
```

Unlisted endpoints remain blocked:

```bash
openshell sandbox exec -- curl -sS https://example.com
# curl: (56) CONNECT tunnel failed, response 403
```

### Dynamically update the policy on a running sandbox

You don't need to recreate a sandbox to change its network policy.
Updates take effect within seconds.

**Add an endpoint:**

```bash
openshell policy update <sandbox-name> --add-endpoint pypi.org:443 --wait
```

**Add multiple endpoints at once:**

```bash
openshell policy update <sandbox-name> \
  --add-endpoint registry.npmjs.org:443 \
  --add-endpoint api.github.com:443 \
  --wait
```

**Remove an endpoint:**

```bash
openshell policy update <sandbox-name> --remove-endpoint pypi.org:443 --wait
```

**Replace the entire policy from a file:**

```bash
openshell policy set <sandbox-name> --policy new-policy.yaml --wait
```

**View the current effective policy:**

```bash
openshell policy get <sandbox-name> --full
```

### Policy format reference

The `network_policies` section maps rule names to endpoint lists:

```yaml
network_policies:
  <rule-name>:
    name: "<human-readable description>"
    endpoints:
      - host: "<hostname>"
        port: <port>
      - host: "*.example.com"   # glob patterns supported
        port: 443
```

| Field | Required | Description |
|-------|----------|-------------|
| `host` | yes | Exact hostname or glob pattern (`*` = single label, `**` = across labels) |
| `port` | yes | TCP port (usually 443 for HTTPS) |
| `binaries` | no | If omitted, any process in the sandbox can use this endpoint. If specified, only listed binary paths are allowed. |

When no `binaries` are specified (the common case for egress policies), any
process in the sandbox can access the endpoint — the endpoint declaration
itself is the access gate.

## OpenShift with Self-Signed Certificates

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

## Uninstall

To remove OpenShell resources from your cluster, use the cleanup scripts in
`scripts/openshell/`.

### Remove everything

```bash
scripts/openshell/cleanup-all.sh
```

This discovers all deployed tenants and removes them, then removes the shared
infrastructure. Add `--delete-namespaces` to also delete tenant namespaces.

### Remove a single tenant

```bash
scripts/openshell/cleanup-tenant.sh team1
scripts/openshell/cleanup-tenant.sh team1 --delete-namespace
```

### Remove shared infrastructure only

```bash
scripts/openshell/cleanup-shared.sh
```

Skip specific components with `--skip-*` flags (mirrors `deploy-shared.sh`):

```bash
scripts/openshell/cleanup-shared.sh --skip-keycloak  # Keep the Keycloak realm
scripts/openshell/cleanup-shared.sh --skip-backend   # Keep rossoctl-backend + DB
```

### Dry run

All cleanup scripts support `--dry-run` to preview what would be deleted:

```bash
scripts/openshell/cleanup-all.sh --dry-run
```

### Ordering

Tenants must be cleaned up before shared infrastructure. `cleanup-all.sh`
handles this automatically. If running scripts manually, always run
`cleanup-tenant.sh` for each tenant first, then `cleanup-shared.sh`.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `deploy-tenant.sh` hangs at Helm `--wait` | `openshell` Keycloak realm does not exist (gateway OIDC init fails in a crash loop) | Run `deploy-shared.sh` first; verify realm with `kubectl exec keycloak-0 -n keycloak -- /opt/keycloak/bin/kcadm.sh get realms` |
| `deploy-shared.sh` hangs at "Logging in to Keycloak" | `keycloak-initial-admin` secret password doesn't match the DB (common after Keycloak pod recreation on RHBK) | See [Keycloak credential mismatch](#keycloak-credential-mismatch) below |
| `invalid peer certificate: UnknownIssuer` | CLI missing CA/client certs | Re-run `configure-cli.sh` or place `ca.crt`, `tls.crt`, `tls.key` in `~/.config/openshell/gateways/<name>/mtls/` |
| `Gateway already exists` on re-registration | CLI gateway not removed before re-running `configure-cli.sh` | Run `openshell gateway remove <name>` first, then re-run the script |
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
