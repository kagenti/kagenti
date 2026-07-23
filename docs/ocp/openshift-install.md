---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Rossoctl Installation on OpenShift

## Requirements

- OpenShift 4.16.0+ (4.19.0+ recommended for OLM-managed SPIRE)
- `oc` >= 4.16.0 or `kubectl` >= 1.32
- `helm` >= 3.18.0, < 4
- Cluster-admin access

## Quick Start

Clone the repository, check out a release, and run the installer:

```shell
git clone https://github.com/rossoctl/rossoctl.git
cd rossoctl
git checkout v0.6.0   # replace with desired version

./scripts/ocp/setup-rossoctl.sh --rossoctl-repo . --with-all
```

This installs the full Rossoctl stack (SPIRE, cert-manager, Keycloak, Istio, operator, UI, MCP Gateway, Kiali, Builds, Kuadrant) and prints access information at the end.

### Access the UI

```shell
echo "https://$(kubectl get route rossoctl-ui -n rossoctl-system -o jsonpath='{.status.ingress[0].host}')"
```

Keycloak credentials:

```shell
kubectl get secret keycloak-initial-admin -n keycloak \
  -o go-template='User: {{.data.username | base64decode}}  Pass: {{.data.password | base64decode}}{{"\n"}}'
```

## Installation Examples

### Auto-clone (no local repo)

The installer auto-clones `main` to `~/.cache/rossoctl` when `--rossoctl-repo` is omitted:

```shell
./scripts/ocp/setup-rossoctl.sh --with-all
```

### Core only (no optional components)

Installs SPIRE, cert-manager, Keycloak, Istio, operator, UI, and MCP Gateway:

```shell
./scripts/ocp/setup-rossoctl.sh --rossoctl-repo .
```

### Skip MLflow

```shell
./scripts/ocp/setup-rossoctl.sh --rossoctl-repo . --skip-mlflow
```

### Selective optional components

```shell
# Only Kiali + Prometheus
./scripts/ocp/setup-rossoctl.sh --rossoctl-repo . --with-kiali

# Only Tekton/OpenShift Builds
./scripts/ocp/setup-rossoctl.sh --rossoctl-repo . --with-builds
```

### Custom operator image (development)

```shell
./scripts/ocp/setup-rossoctl.sh --rossoctl-repo . \
  --operator-image quay.io/myuser/operator:dev
```

### Dry run

Preview what commands would execute without running them:

```shell
./scripts/ocp/setup-rossoctl.sh --rossoctl-repo . --with-all --dry-run
```

### Flag Reference

| Flag | Description |
|------|-------------|
| `--rossoctl-repo PATH\|URL` | Local path or GitHub URL (default: auto-clone `main`) |
| `--realm REALM` | Keycloak realm (default: `rossoctl`) |
| `--keycloak-namespace NS` | Keycloak namespace (default: `keycloak`) |
| `--skip-ovn-patch` | Skip OVN gateway routing patch (operator logs a warning at startup if not applied) |
| `--skip-mcp-gateway` | Skip MCP Gateway |
| `--skip-ui` | Skip UI and backend |
| `--skip-mlflow` | Skip MLflow integration |
| `--with-kiali` | Enable Kiali + Prometheus |
| `--with-builds` | Enable Tekton + OpenShift Builds |
| `--with-kuadrant` | Enable Kuadrant (auto-enables MCP Gateway) |
| `--with-all` | Enable all optional components |
| `--with-agent-sandbox` | Install agent-sandbox controller |
| `--operator-repo PATH` | Local path to rossoctl-operator repo |
| `--operator-image IMG:TAG` | Custom operator image |
| `--mcp-gateway-version VER` | MCP Gateway chart version (default: `0.5.1`) |
| `--show-secrets` | Print Keycloak credentials to stdout |
| `--dry-run` | Show commands without executing |

## Running the Demo

There are three ways to get agent images for the demo: using pre-built images (recommended for a quick start), building from source using the OpenShift internal registry, or building from source with an external registry. Both Ollama and OpenAI backends are supported — see the [Local Models Guide](../local-models.md) for details.

---

### Option 1: Use Pre-built Images (Recommended)

This is the fastest way to get started. The required images are already built and hosted on the GitHub Container Registry.

1. You can find all the necessary images here: **[rossoctl/examples Packages](https://github.com/orgs/rossoctl/packages?repo_name=agent-examples)**
2. No image building or secret configuration is required. You can proceed directly to the **"Verifying in the UI"** section.

---

### Option 2: Build from Source (Internal Registry)

When the installer is run with the `--with-builds` flag, the OpenShift internal image registry is automatically configured as the build target. No external registry account or push secrets are needed.

#### Prerequisites

- OpenShift cluster with the internal image registry enabled (default on most OCP installations)
- Installer run with the `--with-builds` flag:

  ```bash
  ./scripts/ocp/setup-rossoctl.sh --with-builds
  ```

#### How it works

The `--with-builds` flag automatically:

1. Installs the **OpenShift Builds operator** (Shipwright) and **Tekton Pipelines**
2. Configures the backend to use the internal registry (`image-registry.openshift-image-registry.svc:5000`)
3. Sets the build strategy to `buildah` (TLS-enabled, matching the internal registry)
4. Grants the `pipeline` ServiceAccount `system:image-builder` permissions in each agent namespace (standard OpenShift RBAC)

#### Using Build from Source in the UI

Once installed with `--with-builds`:

1. Navigate to **Agents** or **Tools** in the Rossoctl UI
2. Click **Import** and select **Build from Source**
3. Provide the git repository URL (and branch/path if needed)
4. The build runs in-cluster using Shipwright, pushing the image to the internal registry
5. Once the build completes, the agent/tool is deployed automatically

No registry URL or push secret configuration is needed in the UI — the internal registry is used by default.

---

### Option 3: Build from Source (External Registry)

Use this path if you prefer to push built images to an external registry like Quay.io.

#### Prerequisites

- A user or organization account on **[quay.io](https://quay.io)**
- Installer run with the `--with-builds` flag
- Namespaces created for agents and tools (e.g., `team1` and `team2`)

#### Steps

1. **Configure Quay.io**
    - [Create a robot account](https://docs.redhat.com/en/documentation/red_hat_quay/3/html/user_guide/managing_robot_accounts) for your organization.
    - Create empty repositories for the images you need to build (e.g., `a2a-contact-extractor` and `a2a-currency-converter`).
    - Grant your robot account **write access** to these new repositories.

2. **Create Kubernetes Image Pull Secret**
    - Navigate to your robot account settings in the Quay.io UI.
    - Select the **Kubernetes Secret** tab and copy the generated secret manifest.
    - Apply the secret to each namespace where agents will run.

      ```bash
      # Save the secret to a file named quay-secret.yaml, then run:
      kubectl apply -f quay-secret.yaml -n team1
      kubectl apply -f quay-secret.yaml -n team2
      ```

3. **Build from Source in the UI**
    - When importing an agent/tool, select **Build from Source**
    - Enter the external registry URL (e.g., `quay.io/myorg`)
    - Select the push secret you created above
    - The build uses the `buildah` strategy with TLS for external registries

---

### Verifying in the UI

After completing any of the setup options above, you should be able to use the UI to:

- **Agents**
    1. Import a new agent.
    2. List the imported agent.
    3. Interact with the agent from its details page.
- **Tools**
    1. Import a new MCP tool.
    2. List the imported tool.
    3. Interact with the tool from its details page.

## Manual Installation (Helm)

For fine-grained control, install each chart individually.

### Prerequisites

```shell
export DOMAIN=apps.$(kubectl get dns cluster -o jsonpath='{.spec.baseDomain}')
```

### Option A: OCI Chart Releases

```shell
# Determine latest version
LATEST_TAG=$(git ls-remote --tags --sort="v:refname" \
  https://github.com/rossoctl/rossoctl.git | tail -n1 | sed 's|.*refs/tags/v||; s/\^{}//')

# 1. Dependencies (SPIRE, cert-manager, Keycloak, Istio)
helm install rossoctl-deps oci://ghcr.io/rossoctl/rossoctl/rossoctl-deps \
  --version $LATEST_TAG \
  -n rossoctl-system --create-namespace \
  --set spire.trustDomain=${DOMAIN}

# 2. MCP Gateway
helm install mcp-gateway oci://ghcr.io/rossoctl/charts/mcp-gateway \
  --namespace mcp-system --create-namespace \
  --version 0.5.1

# 3. Rossoctl platform
helm install rossoctl oci://ghcr.io/rossoctl/rossoctl/rossoctl \
  --version $LATEST_TAG \
  -n rossoctl-system \
  -f .secrets.yaml \
  --set agentOAuthSecret.spiffePrefix=spiffe://${DOMAIN}/sa \
  --set uiOAuthSecret.useServiceAccountCA=false \
  --set agentOAuthSecret.useServiceAccountCA=false \
  --set ui.frontend.tag=$LATEST_TAG \
  --set ui.backend.tag=$LATEST_TAG
```

### Option B: From Local Repository

```shell
git clone https://github.com/rossoctl/rossoctl.git && cd rossoctl

# Prepare secrets
cp charts/rossoctl/.secrets_template.yaml charts/rossoctl/.secrets.yaml
# Edit .secrets.yaml with your API keys

# Update chart dependencies
helm dependency update ./charts/rossoctl-deps/
helm dependency update ./charts/rossoctl/

# 1. Dependencies
helm install rossoctl-deps ./charts/rossoctl-deps/ \
  -n rossoctl-system --create-namespace \
  --set spire.trustDomain=${DOMAIN} --wait

# 2. MCP Gateway
helm install mcp-gateway oci://ghcr.io/rossoctl/charts/mcp-gateway \
  --namespace mcp-system --create-namespace \
  --version 0.5.1

# 3. Rossoctl platform
helm upgrade --install rossoctl ./charts/rossoctl/ \
  -n rossoctl-system \
  -f ./charts/rossoctl/.secrets.yaml \
  --set agentOAuthSecret.spiffePrefix=spiffe://${DOMAIN}/sa \
  --set uiOAuthSecret.useServiceAccountCA=false \
  --set agentOAuthSecret.useServiceAccountCA=false
```

### Key Helm Values for OpenShift

| Value | Purpose |
|-------|---------|
| `spire.trustDomain` | SPIFFE trust domain (set to cluster apps domain) |
| `uiOAuthSecret.useServiceAccountCA=false` | Required when using OpenShift self-signed route certs |
| `agentOAuthSecret.useServiceAccountCA=false` | Same as above for agent OAuth |
| `components.certManager.enabled=false` | Skip cert-manager if already installed (e.g. by OpenShift Pipelines) |
| `useSpireHelmChart=true` | Force SPIRE via Helm charts on OCP < 4.19 |

## Cleanup

Remove all Rossoctl components from the cluster:

```shell
./scripts/ocp/cleanup-rossoctl.sh
```

Add `--yes` or `-y` to skip the confirmation prompt (useful for CI):

```shell
./scripts/ocp/cleanup-rossoctl.sh --yes
```

The cleanup script removes:

- Helm releases: `rossoctl`, `mcp-gateway`, `rossoctl-deps`
- Namespaces: `rossoctl-system`, `mcp-system`, `gateway-system`, `keycloak`, `istio-cni`, `istio-system`, `istio-ztunnel`, `openshift-builds`, `zero-trust-workload-identity-manager`, `cert-manager-operator`, `cert-manager`, `team1`, `team2`
- Istio shared-trust ClusterIssuers and Certificates

## RHOAI MLflow Integration

When Red Hat OpenShift AI (RHOAI) is installed, Rossoctl can use RHOAI's managed
MLflow instance for LLM trace collection instead of deploying its own.

### Enabling RHOAI MLflow

Enable the integration by passing these values to `setup-rossoctl.sh` (or the
equivalent Helm overrides):

```yaml
components:
  mlflow:
    enabled: false        # do NOT deploy standalone MLflow
  rhoai:
    enabled: true         # install RHOAI operator + DSC

otel:
  mlflow:
    enabled: true         # wire OTEL collector → RHOAI MLflow
    workspace: "team1"    # RHOAI workspace namespace
    experimentId: "1"     # target experiment (created automatically)
```

The installer (`scripts/ocp/setup-rossoctl.sh`) automatically:

1. Waits for the RHOAI MLflow CR to become ready
2. Grants the OTEL collector ServiceAccount `mlflow-edit` in the workspace namespace
3. Creates the target experiment via the MLflow REST API
4. Deploys an OAuth proxy with browser SSO for the MLflow dashboard
5. Adds a "MLflow" link to the Rossoctl UI sidebar

### Authentication

The OTEL collector authenticates to RHOAI MLflow using its projected
ServiceAccount token (`/var/run/secrets/kubernetes.io/serviceaccount/token`).
MLflow's `kubernetes-auth` plugin validates this token via Kubernetes
SubjectAccessReview against the workspace namespace.

TLS is verified using the OpenShift service-ca certificate
(`/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt`), which is
automatically available in every pod.

### RHOAI Version Requirements

RHOAI **3.4.0+** (channel `stable-3.4`) is required for full trace rendering.
It ships MLflow 3.10.1 which includes the fix for OTEL-ingested trace display.

Earlier versions (RHOAI 3.3.x on channel `fast-3.x`) ship MLflow 3.6.x which
has a client-side JavaScript bug where clicking a trace shows "Trace failed to
render" due to a `num_spans` metadata mismatch. The fix landed in upstream
[MLflow PR #20596](https://github.com/mlflow/mlflow/pull/20596) (v3.10.0).

If you are on RHOAI 3.3.x, switch to the `stable-3.4` channel:

```shell
oc patch subscription rhods-operator -n redhat-ods-operator --type=merge \
  -p '{"spec":{"channel":"stable-3.4"}}'
```

After the operator upgrades, the MLflow deployment will be updated automatically.

### OTEL Collector Configuration

The RHOAI MLflow pipeline differs from the standalone MLflow pipeline:

| Setting | Standalone | RHOAI |
|---------|-----------|-------|
| Authentication | OAuth2 client credentials | ServiceAccount bearer token |
| TLS CA | System CAs / ingress-ca | service-ca.crt (projected volume) |
| Compression | gzip (default) | none (RHOAI incompatibility) |
| Retry | enabled (5s→30s backoff) | disabled (response parsing bug) |
| Endpoint | `http://mlflow:5000/v1/traces` | `https://mlflow.<ns>.svc:8443/v1/traces` |

The retry is disabled because RHOAI MLflow returns a JSON body with
`Content-Type: application/x-protobuf`, which the OTEL collector cannot parse,
triggering infinite retries even though traces are successfully ingested.

## Troubleshooting

### Pre-flight Validation

Run before installation to check your environment:

```shell
./scripts/ocp/preflight-check.sh
```

Validates: required tools, cluster connectivity, OCP version, network configuration for Istio Ambient mode.

### SPIRE Daemonset Not Starting

Check status:

```shell
kubectl get daemonsets -n zero-trust-workload-identity-manager
```

If `Ready` is `0`, the pods likely lack SCC privileges:

```shell
oc adm policy add-scc-to-user privileged -z spire-agent -n zero-trust-workload-identity-manager
kubectl rollout restart daemonset spire-agent -n zero-trust-workload-identity-manager

oc adm policy add-scc-to-user privileged -z spire-spiffe-csi-driver -n zero-trust-workload-identity-manager
kubectl rollout restart daemonset spire-spiffe-csi-driver -n zero-trust-workload-identity-manager
```

### Cert-Manager Already Installed

If another operator (e.g. OpenShift Pipelines) manages cert-manager, skip it:

```shell
# With the installer
./scripts/ocp/setup-rossoctl.sh --rossoctl-repo .  # installer auto-detects

# With Helm (manual)
helm install rossoctl-deps ... --set components.certManager.enabled=false
```
