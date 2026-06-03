# Kagenti Installation Guide

This guide covers installation on both local Kind clusters and OpenShift environments.

## Table of Contents

- [Prerequisites](#prerequisites)
  - [macOS Quick Start (New Machine)](#macos-quick-start-new-machine)
- [Kind Installation (Local Development)](#kind-installation-local-development)
- [OpenShift Installation](#openshift-installation)
- [Accessing the UI](#accessing-the-ui)
- [Verifying the Installation](#verifying-the-installation)

---

## Prerequisites

### Common Requirements

| Tool | Version | Purpose |
|------|---------|---------|
| kubectl | ≥1.32.1 | Kubernetes CLI |
| [Helm](https://helm.sh/docs/intro/install/) | ≥3.18.0, <4 | Package manager for Kubernetes |
| git | ≥2.48.0 | Cloning repositories |

### macOS Quick Start (New Machine)

If you're setting up a brand-new Mac, install all prerequisites at once with [Homebrew](https://brew.sh):

```bash
# Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install required tools
brew install git kind kubectl helm@3

# Verify Helm version meets the ≥3.18.0 requirement above
helm version

# Container runtime — pick one:
brew install podman    # recommended for macOS
# or: brew install --cask docker   # Docker Desktop

# If using Podman, create and start a machine with sufficient resources:
podman machine init --memory 18432 --cpus 4
podman machine start
```

### Kind-Specific Requirements

| Tool | Purpose |
|------|---------|
| Docker Desktop / Rancher Desktop / Podman | Container runtime (16GB RAM, 4 cores recommended) |
| [Kind](https://kind.sigs.k8s.io) | Local Kubernetes cluster |
| [Ollama](https://ollama.com/download) | Local LLM inference |
| [GitHub Token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic) | **(Optional)** Only needed to deploy agents/tools from private GitHub repos or pull from private registries. Recommended scopes: `repo` for private repositories and `read:packages` for private registries (e.g., GHCR). |

### OpenShift-Specific Requirements

| Tool | Purpose |
|------|---------|
| oc | ≥4.16.0 (OpenShift CLI) |
| OpenShift cluster | Admin access required (tested with OpenShift 4.19) |

---

## Kind Installation (Local Development)

### Quick Start

```bash
# Clone the repository
git clone https://github.com/kagenti/kagenti.git
cd kagenti
```

#### Bash Installer (Recommended)

The bash installer (`scripts/kind/setup-kagenti.sh`) is a composable, single-file
script that creates a Kind cluster and deploys Kagenti. Core components are always
installed; optional layers are enabled with `--with-*` flags.

**Core (always installed):** cert-manager, Gateway API CRDs, Istio Gateway controller (istio-base + istiod), Keycloak, kagenti-operator, kagenti-webhook

**Install everything:**

```bash
scripts/kind/setup-kagenti.sh --with-all
```

**Install only what you need:**

```bash
# Core + Istio ambient + UI
scripts/kind/setup-kagenti.sh --with-istio --with-ui

# Core + full service mesh + builds
scripts/kind/setup-kagenti.sh --with-istio --with-spire --with-builds
```

**Available `--with-*` flags:**

| Flag | Components |
|------|------------|
| `--with-istio` | Full Istio ambient mesh (mTLS, waypoints); Gateway API controller always installed as core |
| `--with-spire` | SPIRE + SPIFFE IdP setup |
| `--with-backend` | Kagenti backend API |
| `--with-ui` | Kagenti UI (auto-enables backend) |
| `--with-mcp-gateway` | MCP Gateway |
| `--with-kuadrant` | Kuadrant operator (auto-enables MCP Gateway) |
| `--with-otel` | OpenTelemetry collector |
| `--with-mlflow` | MLflow trace backend (auto-enables OTel + Istio ambient) |
| `--with-builds` | Tekton + Shipwright (build agents from source) |
| `--with-kiali` | Kiali + Prometheus (auto-enables Istio ambient) |
| `--with-all` | All of the above |

**Other options:**

| Flag | Description |
|------|-------------|
| `--skip-cluster` | Reuse an existing Kind cluster |
| `--build-images` | Build platform images from source and load into Kind (backend, ui-v2, agent-oauth-secret, mlflow-oauth-secret) |
| `--preload-images` | Pre-pull third-party images on the host and load them into the Kind node for faster pod startup (see [Preloading Images](#preloading-images)) |
| `--secrets-file FILE` | YAML file with secrets (see below) |
| `--cluster-name NAME` | Kind cluster name (default: `kagenti`) |
| `--domain DOMAIN` | Domain for services (default: `localtest.me`) |
| `--kagenti-values FILE` | Helm override file applied to the `kagenti` chart |
| `--kagenti-deps-values FILE` | Helm override file applied to the `kagenti-deps` chart |
| `--dry-run` | Show commands without executing |

#### Preloading Images

The `--preload-images` flag pulls third-party container images onto the host
ahead of time and side-loads them into the Kind control-plane node. This avoids
Docker Hub anonymous-pull rate limits (which can stall a fresh install when
Istio, Phoenix, OTel collector, and other images are pulled in parallel) and
shortens overall startup time on slow links by reusing the host's image cache.

> **Why this exists:** the original motivation is shared-NAT environments such
> as office buildings, conference Wi-Fi, or VPNs, where many users appear to
> Docker Hub as a single IP and quickly trip the anonymous pull-rate limit.
> A fresh install pulls dozens of `docker.io/*` images in parallel and is
> especially likely to hit the cap. Preloading from the host's authenticated
> daemon cache sidesteps the limit entirely.

The list of images lives in
[`scripts/kind/preload-images.txt`](../scripts/kind/preload-images.txt) — one
image per line, comments with `#`. The file is intentionally focused on
`docker.io/*` images; `ghcr.io` and `quay.io` are not rate-limited and pull
fine on demand.

```bash
# Use during a full install
scripts/kind/setup-kagenti.sh --with-all --preload-images
```

How it works:

1. Pulls every image in `preload-images.txt` to the host (in parallel for
   Docker, sequential for Podman).
2. Bundles them into a single tar via `docker save` / `podman save`.
3. Copies the tar into the Kind control-plane container and imports it with
   `ctr --namespace=k8s.io images import`. The load runs in the background so
   it overlaps with the rest of the install.

Failures during pull are non-fatal — the installer logs a warning and lets
pods fall back to pulling on demand.

When updating image versions, keep `preload-images.txt` in sync with the
versions referenced in `scripts/kind/setup-kagenti.sh` and the
`charts/kagenti-deps/templates/` manifests, otherwise pods will still pull
the un-preloaded versions at runtime.

#### Providing Secrets

Create a secrets file from the template:

```bash
cp charts/kagenti/.secrets_template.yaml charts/kagenti/.secrets.yaml
# Edit .secrets.yaml with your values
```

Pass it to the installer:

```bash
scripts/kind/setup-kagenti.sh --with-all --secrets-file charts/kagenti/.secrets.yaml
```

If `--secrets-file` is not specified, the installer automatically uses
`charts/kagenti/.secrets.yaml` when it exists.

#### Cleanup

To uninstall Kagenti from a Kind cluster:

```bash
# Uninstall platform, keep cluster
scripts/kind/cleanup-kagenti.sh

# Uninstall platform and destroy cluster
scripts/kind/cleanup-kagenti.sh --destroy-cluster
```

### Using an Existing Kubernetes Cluster

If you have an existing Kind cluster:

```bash
scripts/kind/setup-kagenti.sh --skip-cluster --with-all
```

For non-Kind clusters, see the [OpenShift installation](#openshift-installation) instructions.

---

## OpenShift Installation

Both Ollama (local models) and OpenAI are supported as LLM backends. See the [Local Models Guide](local-models.md) for setup details.

### Option A: Bash Installer (Recommended)

The `scripts/ocp/setup-kagenti.sh` script is the recommended way to install Kagenti on OpenShift.
It installs SPIRE, cert-manager, Keycloak, the operator, MCP Gateway, and the UI/backend in a
single command. Run it from the repository root after logging in with `oc`.

> **Note**: If your cluster already has a cert-manager installation (e.g. installed via the
> Red Hat OpenShift cert-manager Operator), remove it before running the script, as Kagenti
> installs its own.

```bash
# Clone repository
git clone https://github.com/kagenti/kagenti.git
cd kagenti

# Log in to your cluster
oc login https://api.your-cluster.example.com:6443 -u kubeadmin -p <password>

# Install Kagenti platform
./scripts/ocp/setup-kagenti.sh
```

Common options:

| Flag | Description |
|------|-------------|
| `--kagenti-repo PATH\|URL` | Local path or GitHub URL to the repo (default: clones `main` to `~/.cache/kagenti`) |
| `--realm REALM` | Keycloak realm (default: `kagenti`) |
| `--skip-ovn-patch` | Skip OVN gateway routing patch |
| `--skip-mcp-gateway` | Skip MCP Gateway installation |
| `--skip-ui` | Skip Kagenti UI and backend installation |
| `--skip-mlflow` | Skip MLflow integration |
| `--operator-image IMG:TAG` | Custom operator image (e.g. `quay.io/user/kagenti-operator:dev`) |
| `--dry-run` | Show commands without executing |

### Option B: Install from OCI Charts

```bash
# Get latest version
LATEST_TAG=$(git ls-remote --tags --sort="v:refname" https://github.com/kagenti/kagenti.git | tail -n1 | sed 's|.*refs/tags/v||; s/\^{}//')

# Prepare secrets
# Download .secrets_template.yaml from https://github.com/kagenti/kagenti/blob/main/charts/kagenti/.secrets_template.yaml
# Save as .secrets.yaml and fill in required values

# Install dependencies
helm install --create-namespace -n kagenti-system kagenti-deps \
  oci://ghcr.io/kagenti/kagenti/kagenti-deps \
  --version $LATEST_TAG \
  --set spire.trustDomain=${DOMAIN}

# Install MCP Gateway
LATEST_GATEWAY_TAG=$(skopeo list-tags docker://ghcr.io/kagenti/charts/mcp-gateway | jq -r '.Tags[-1]')
helm install mcp-gateway oci://ghcr.io/kagenti/charts/mcp-gateway \
  --create-namespace --namespace mcp-system \
  --version $LATEST_GATEWAY_TAG

# Install Kagenti (with OpenShift CA workaround)
helm upgrade --install --create-namespace -n kagenti-system \
  -f .secrets.yaml kagenti oci://ghcr.io/kagenti/kagenti/kagenti \
  --version $LATEST_TAG \
  --set agentOAuthSecret.spiffePrefix=spiffe://${DOMAIN}/sa \
  --set uiOAuthSecret.useServiceAccountCA=false \
  --set agentOAuthSecret.useServiceAccountCA=false
```

### Option C: Install from Repository

```bash
# Clone repository
git clone https://github.com/kagenti/kagenti.git
cd kagenti

# Prepare secrets
cp charts/kagenti/.secrets_template.yaml charts/kagenti/.secrets.yaml
# Edit .secrets.yaml with your values

# Update chart dependencies
helm dependency update ./charts/kagenti-deps/
helm dependency update ./charts/kagenti/

# Install dependencies
helm install kagenti-deps ./charts/kagenti-deps/ \
  -n kagenti-system --create-namespace \
  --set spire.trustDomain=${DOMAIN} --wait

# Install MCP Gateway
helm install mcp-gateway oci://ghcr.io/kagenti/charts/mcp-gateway \
  --create-namespace --namespace mcp-system --version 0.4.0

# Get latest UI tag
LATEST_TAG=$(git ls-remote --tags --sort="v:refname" https://github.com/kagenti/kagenti.git | tail -n1 | sed 's|.*refs/tags/||; s/\^{}//')

# Install Kagenti (with OpenShift CA workaround)
helm upgrade --install kagenti ./charts/kagenti/ \
  -n kagenti-system --create-namespace \
  -f ./charts/kagenti/.secrets.yaml \
  --set ui.tag=${LATEST_TAG} \
  --set agentOAuthSecret.spiffePrefix=spiffe://${DOMAIN}/sa \
  --set uiOAuthSecret.useServiceAccountCA=false \
  --set agentOAuthSecret.useServiceAccountCA=false
```

### Verify SPIRE Daemonsets

```bash
kubectl get daemonsets -n zero-trust-workload-identity-manager
```

If `Current` or `Ready` is `0`, see [Troubleshooting](#spire-daemonset-issues).

---

## Accessing the UI

### Kind Cluster

```bash
open http://kagenti-ui.localtest.me:8080
```

### OpenShift

```bash
echo "https://$(kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.status.ingress[0].host}')"
```

If using self-signed certificates, accept the certificate in your browser.

For MCP Inspector, also accept the proxy certificate:

```bash
echo "https://$(kubectl get route mcp-proxy -n kagenti-system -o jsonpath='{.status.ingress[0].host}')"
```

### Default Credentials

Run the following script to display all service URLs and credentials:

```bash
./.github/scripts/local-setup/show-services.sh
```

For OpenShift, Keycloak admin credentials can also be retrieved directly:

```bash
kubectl get secret keycloak-initial-admin -n keycloak \
  -o go-template='Username: {{.data.username | base64decode}}  Password: {{.data.password | base64decode}}{{"\n"}}'
```

---

## Keycloak Admin Credentials for Agent Namespaces

The [AuthBridge](https://github.com/kagenti/kagenti-extensions/tree/main/authbridge) stack (separate sidecars or a single [combined `authbridge` container](authbridge-combined-sidecar.md)) needs Keycloak admin credentials for automatic OAuth2 client registration. These credentials are stored in a Kubernetes Secret called `keycloak-admin-secret` in each agent namespace.

### Automatic Provisioning

The installer automatically creates `keycloak-admin-secret` in every agent namespace (e.g., `team1`, `team2`). By default it uses `admin`/`admin`, matching the default Keycloak admin account.

### Customizing Credentials

If your Keycloak admin credentials differ from the defaults, override them using a values file (preferred over `--set` to avoid exposing passwords in shell history and process listings):

**Secrets file** (via `.secrets.yaml`):

Add to your `charts/kagenti/.secrets.yaml`:

```yaml
keycloak:
  adminUsername: myadmin
  adminPassword: mypassword
```

**Helm install** (via values file):

```bash
helm upgrade --install kagenti ./charts/kagenti/ \
  -n kagenti-system --create-namespace \
  -f my-secret-values.yaml
```

### Using an Existing Secret

If you already manage Keycloak admin credentials in a Secret (e.g., via an external secrets operator), you can skip the automatic secret creation entirely by setting `keycloak.adminExistingSecret` to the name of that secret. The referenced secret must contain `KEYCLOAK_ADMIN_USERNAME` and `KEYCLOAK_ADMIN_PASSWORD` keys:

```bash
helm upgrade --install kagenti ./charts/kagenti/ \
  -n kagenti-system --create-namespace \
  --set keycloak.adminExistingSecret=my-keycloak-admin-secret
```

### Manual Creation

If you need to create or update the secret manually in an agent namespace:

```bash
kubectl create secret generic keycloak-admin-secret -n <agent-namespace> \
  --from-literal=KEYCLOAK_ADMIN_USERNAME=admin \
  --from-literal=KEYCLOAK_ADMIN_PASSWORD=admin \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Verifying

```bash
kubectl get secret keycloak-admin-secret -n team1
```

> **Security note:** For production deployments, use a dedicated Keycloak service account with limited permissions instead of the admin account. See the [Identity Guide](./identity-guide.md) for details.

---

## Verifying the Installation

### Identity Services

```bash
# SPIRE OIDC (Kind)
curl http://spire-oidc.localtest.me:8080/keys
curl http://spire.localtest.me:8080/.well-known/openid-configuration

# Tornjak API
curl http://spire-tornjak-api.localtest.me:8080/
# Expected: "Welcome to the Tornjak Backend!"

# Tornjak UI
open http://spire-tornjak-ui.localtest.me:8080/
```

### Keycloak (Kind)

```bash
open http://keycloak.localtest.me:8080/
# Login: see .github/scripts/local-setup/show-services.sh output for credentials
```

### UI Functionality

From the UI you can:
- Import and deploy A2A agents from any framework
- Deploy MCP tools directly from source
- Test agents interactively
- Monitor traces and network traffic

---

## Troubleshooting

### SPIRE Daemonset Issues

If daemonsets show `Current=0` or `Ready=0`:

```bash
kubectl describe daemonsets -n zero-trust-workload-identity-manager spire-agent
kubectl describe daemonsets -n zero-trust-workload-identity-manager spire-spiffe-csi-driver
```

If you see SCC (Security Context Constraint) errors:

```bash
oc adm policy add-scc-to-user privileged -z spire-agent -n zero-trust-workload-identity-manager
kubectl rollout restart daemonsets -n zero-trust-workload-identity-manager spire-agent

oc adm policy add-scc-to-user privileged -z spire-spiffe-csi-driver -n zero-trust-workload-identity-manager
kubectl rollout restart daemonsets -n zero-trust-workload-identity-manager spire-spiffe-csi-driver
```

### OpenShift Upgrade (4.18 → 4.19)

<details>
<summary>Red Hat OpenShift Container Platform (AWS)</summary>

```bash
# Update channel
oc patch clusterversion version --type merge -p '{"spec":{"channel":"fast-4.19"}}'

# Acknowledge changes
oc -n openshift-config patch cm admin-acks --patch '{"data":{"ack-4.18-kube-1.32-api-removals-in-4.19":"true"}}' --type=merge
oc -n openshift-config patch cm admin-acks --patch '{"data":{"ack-4.18-boot-image-opt-out-in-4.19":"true"}}' --type=merge

# Upgrade
oc adm upgrade --to-latest=true --allow-not-recommended=true

# Monitor
oc get clusterversion
```

</details>

For more troubleshooting tips, see [Troubleshooting Guide](./troubleshooting.md).

