# Kagenti Installation on OpenShift

**This document is work in progress**

## SPIRE Installation Methods by OpenShift Version

### OpenShift Version Compatibility

| OCP Version | SPIRE Installation Method | Notes |
|-------------|--------------------------|-------|
| **4.19.0+** | ZTWIM Operator (OLM) | Full OLM-managed SPIRE via Zero Trust Workload Identity Manager |
| **4.16.0 - 4.18.x** | Helm Charts | Upstream SPIRE Helm charts (same as Kubernetes) |
| **< 4.16.0** | Not supported | Kagenti requires OCP 4.16.0 or higher |

The Kagenti installer automatically detects your OpenShift version and selects the appropriate SPIRE installation method:

- **OCP 4.19+**: Uses the ZTWIM (Zero Trust Workload Identity Manager) operator, which is the Red Hat-supported OLM-managed approach for SPIRE on OpenShift.
- **OCP < 4.19**: Falls back to upstream SPIRE Helm charts, providing the same SPIRE functionality used on standard Kubernetes clusters.

### Version Check

Before installation, verify your OpenShift version:

```shell
oc version
# Look for: Server Version: 4.x.x
```

Or check the cluster version resource:

```shell
kubectl get clusterversion version -o jsonpath='{.status.desired.version}'
```

### SPIRE on OCP < 4.19 (Helm Chart Installation)

If your cluster is running OpenShift 4.16 - 4.18, the installer will automatically use SPIRE Helm charts:

- **No manual configuration required** - The Ansible installer detects the version and configures everything automatically
- **Full SPIRE functionality** - All SPIRE features work the same as on Kubernetes
- **Transparent fallback** - You'll see a message during installation indicating Helm charts are being used

If you prefer to upgrade to get OLM-managed SPIRE:
- See [Upgrade from OCP 4.18 to 4.19](#upgrade-from-ocp-418-to-419) section below
- After upgrade, re-run the installer to switch to ZTWIM operator

To explicitly disable SPIRE (not recommended):
```yaml
# In your values file
components:
  spire:
    enabled: false
```

### Automated Version Detection

The Kagenti installer includes automatic version detection:

- **Ansible Installer**: Automatically detects OCP version and selects the appropriate SPIRE installation method (ZTWIM operator for 4.19+, Helm charts for older versions)
- **Helm Charts**: When installing manually, pass `ocpVersion` and `useSpireHelmChart` values to control behavior
- **Pre-flight Checks**: Run validation before installation to understand what will be installed

## Current limitations

These limitations will be addressed in successive PRs.

- Only [quay.io](https://quay.io) registry has been tested in build from source

Both Ollama (local models) and OpenAI are supported as LLM backends. See the [Local Models Guide](../local-models.md) for OpenShift-specific setup instructions including deploying Ollama as a pod.

## Requirements

- helm ≥3.18.0, <4
- kubectl >= v1.32.1 or oc >= 4.16.0
- git >= 2.48.0
- **Access to OpenShift cluster with admin authority**
  - **Minimum Version: 4.16.0** (for base Kagenti functionality with SPIRE via Helm charts)
  - **Recommended Version: 4.19.0+** (for OLM-managed SPIRE via ZTWIM operator)
  - See [SPIRE installation methods](#spire-installation-methods-by-openshift-version) above
- If using manual Helm chart installation, see [Cert Manager Configuration](#cert-manager-configuration) for handling existing cert-manager installations

## Pre-flight Validation (Recommended)

Before starting the installation, run the pre-flight check script to validate your environment:

```shell
./deployments/scripts/preflight-check.sh
```

This script will:
- ✓ Verify required tools (oc/kubectl, helm, jq)
- ✓ Check cluster connectivity and admin permissions
- ✓ Detect OpenShift version and validate SPIRE/ZTWIM compatibility
- ✓ Check network configuration for Istio Ambient mode
- ✓ Provide clear recommendations for any issues found

**Example output (OCP 4.18):**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OpenShift Version Compatibility
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ℹ Detected OpenShift version: 4.18.5
✓ OpenShift version >= 4.16.0 (Kagenti compatible)
ℹ OpenShift version < 4.19.0 (ZTWIM operator not available)
  → SPIRE will be installed via Helm charts (same as Kubernetes)
  → For OLM-managed SPIRE, upgrade to OpenShift 4.19.0 or higher
```

**Example output (OCP 4.19+):**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OpenShift Version Compatibility
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ℹ Detected OpenShift version: 4.20.8
✓ OpenShift version >= 4.16.0 (Kagenti compatible)
✓ OpenShift version >= 4.19.0 (ZTWIM operator supported)
  → SPIRE will be installed via ZTWIM operator (OLM-managed)
```

If the pre-flight check fails, resolve the issues before proceeding with installation.

## Check Cluster Network Type and Configure for OVN in Ambient Mode

When enabling Istio Ambient mode on OpenShift clusters, readiness probes may fail for pods in namespaces with Ambient enabled if the cluster uses the OVNKubernetes network type.
This behavior is documented in this [issue](https://github.com/kagenti/kagenti/issues/329).

### Why This Happens

`OVNKubernetes` defaults to shared gateway mode, which routes kubelet health probe traffic outside the host network stack. As a result, the Ztunnel proxy cannot intercept the probes, causing them to fail incorrectly.

**Verify Network Type**
To confirm your cluster's network type, run:

```shell
kubectl describe network.config/cluster
```

Look for Network Type: OVNKubernetes in the output.

**Required Configuration**
If your cluster uses OVNKubernetes, you must enable local gateway mode by setting `routingViaHost: true`. This ensures traffic flows through the host network stack, allowing Ztunnel to handle probes correctly.

Apply the configuration with:

```shell
kubectl patch network.operator.openshift.io cluster --type=merge -p '{"spec":{"defaultNetwork":{"ovnKubernetesConfig":{"gatewayConfig":{"routingViaHost":true}}}}}'
```

**Important**: This configuration is a temporary workaround and should only be used until OpenShift provides native support for Istio Ambient mode. Future releases are expected to eliminate the need for this manual adjustment.

## Configure Trust Domain

Zero Trust Workload Identity Manager (ZTWIM) utilizes the OpenShift "apps" subdomain as its Trust Domain by default.

### Using the Ansible Installer (Automatic)

The Ansible installer **automatically detects** the trust domain from the OpenShift DNS cluster configuration. No manual configuration is required - the installer will:

1. Query the DNS cluster resource for the base domain
2. Construct the trust domain as `apps.<baseDomain>`
3. Pass it to both kagenti-deps (`spire.trustDomain`) and kagenti (`agentOAuthSecret.spiffePrefix`) charts

### Manual Helm Chart Installation

If installing manually with Helm charts, set the `DOMAIN` environment variable:

```shell
export DOMAIN=apps.$(kubectl get dns cluster -o jsonpath='{ .spec.baseDomain }')
```

Then pass it to the helm commands as shown in the installation sections below.

## Installing the Helm Chart

To start, ensure your `kubectl` or `oc` is configured to point to your OpenShift cluster. You might want to modify `charts/kagenti/values.yaml` to specify the namespaces where agents and tools should be deployed under `agentNamespaces:` and toggle components for installation under `components:`.

### Installing OCI Chart Release Package

1. **Determine Latest Version:**
   - Identify the [latest tagged version](https://github.com/kagenti/kagenti/pkgs/container/kagenti%2Fkagenti/versions) of the chart.
   - Set this version in the `LATEST_TAG` environment variable.

2. **Prepare Secrets:**
   - Copy the [.secrets_template.yaml](https://github.com/kagenti/kagenti/blob/main/charts/kagenti/.secrets_template.yaml) to a local `.secrets.yaml` file.
   - Edit the `.secrets.yaml` to provide the necessary keys as per the comments within the file.

3. **Kagenti Dependencies Helm Chart Installation:**
   - If you have git installed you may determine the latest tag with the command:

      ```shell
      LATEST_TAG=$(git ls-remote --tags --sort="v:refname" https://github.com/kagenti/kagenti.git | tail -n1 | sed 's|.*refs/tags/v||; s/\^{}//')
      ```

      if this command fails, visit [this page](https://github.com/kagenti/kagenti/pkgs/container/kagenti%2Fkagenti/versions) to determine the latest version to use.

   This chart includes all the OpenShift software components required by Kagenti.

      ```shell
      helm install --create-namespace -n kagenti-system kagenti-deps oci://ghcr.io/kagenti/kagenti/kagenti-deps --version $LATEST_TAG --set spire.trustDomain=${DOMAIN}
      ```

4. **Install MCP Gateway Chart:**

   - If you have [skopeo](https://www.redhat.com/en/topics/containers/what-is-skopeo) installed you may determine the latest tag with the command:

      ```shell
      LATEST_GATEWAY_TAG=$(skopeo list-tags docker://ghcr.io/kagenti/charts/mcp-gateway | jq -r '.Tags[-1]')
      ```

      if this command fails, visit [this page](https://github.com/kagenti/mcp-gateway/pkgs/container/charts%2Fmcp-gateway) to determine the latest version to use.

   ```shell
   helm install mcp-gateway oci://ghcr.io/kagenti/charts/mcp-gateway --create-namespace --namespace mcp-system --version $LATEST_GATEWAY_TAG
   ```

5. **Kagenti Helm Chart Installation:**
   This chart includes Kagenti software components and configurations.

   ```shell
   helm upgrade --install --create-namespace -n kagenti-system -f .secrets.yaml kagenti oci://ghcr.io/kagenti/kagenti/kagenti --version $LATEST_TAG --set agentOAuthSecret.spiffePrefix=spiffe://${DOMAIN}/sa --set ui.frontend.tag=$LATEST_TAG --set ui.backend.tag=$LATEST_TAG
   ```
   **Important**: When using OpenShift CA, we have to disable it as trusted cert:

   ```shell
   helm upgrade --install --create-namespace -n kagenti-system -f .secrets.yaml kagenti oci://ghcr.io/kagenti/kagenti/kagenti --version $LATEST_TAG --set agentOAuthSecret.spiffePrefix=spiffe://${DOMAIN}/sa --set ui.frontend.tag=$LATEST_TAG --set ui.backend.tag=$LATEST_TAG --set uiOAuthSecret.useServiceAccountCA=false --set agentOAuthSecret.useServiceAccountCA=false
   ```

### Installing from Repo

1. **Clone Repository:**

   ```shell
   git clone https://github.com/kagenti/kagenti.git
   cd kagenti
   ```

2. **Prepare Helm Secrets:**
   - Copy and edit the secrets template:

     ```shell
     cp charts/kagenti/.secrets_template.yaml charts/kagenti/.secrets.yaml
     ```

   - Ensure the required keys are filled as per the comments in the file.

3. **Update Helm Charts dependencies:**

   These commands need to be run only the first time you clone
   the repository or when there are updates to the charts.

   ```shell
   helm dependency update ./charts/kagenti-deps/
   helm dependency update ./charts/kagenti/
   ```

4. **Install Dependencies:**

   ```shell
   helm install kagenti-deps ./charts/kagenti-deps/ -n kagenti-system --create-namespace --set spire.trustDomain=${DOMAIN} --wait
   ```

5. **Install MCP Gateway Chart:**

   ```shell
   helm install mcp-gateway oci://ghcr.io/kagenti/charts/mcp-gateway --create-namespace --namespace mcp-system --version 0.4.0
   ```

6. **Install the Kagenti Chart:**

   - Open [kagenti-platform-operator-chart](https://github.com/kagenti/kagenti-operator/pkgs/container/kagenti-operator%2Fkagenti-platform-operator-chart) to find the latest available version (e.g., 0.2.0-alpha.12).
   - Open charts/kagenti/Chart.yaml and set the version field for kagenti-platform-operator-chart to match the latest tag.
   - If you updated the version tag, run the following command to update the chart dependencies:

     ```shell
      helm dependency update ./charts/kagenti/
      ```

   - Determine the latest ui tag with the command:

      ```shell
      LATEST_TAG=$(git ls-remote --tags --sort="v:refname" https://github.com/kagenti/kagenti.git | tail -n1 | sed 's|.*refs/tags/||; s/\^{}//')
      ```

      if this command fails, visit [this page](https://github.com/kagenti/kagenti/pkgs/container/kagenti%2Fkagenti/versions) to determine the latest version to use.

   Install the kagenti chart as follows:

   ```shell
   helm upgrade --install kagenti ./charts/kagenti/ -n kagenti-system --create-namespace -f ./charts/kagenti/.secrets.yaml --set ui.frontend.tag=${LATEST_TAG} --set ui.backend.tag=${LATEST_TAG} --set agentOAuthSecret.spiffePrefix=spiffe://${DOMAIN}/sa
   ```
   **Important**: When using OpenShift CA, we have to disable it as trusted cert:

   ```shell
   helm upgrade --install kagenti ./charts/kagenti/ -n kagenti-system --create-namespace -f ./charts/kagenti/.secrets.yaml --set ui.frontend.tag=${LATEST_TAG} --set ui.backend.tag=${LATEST_TAG} --set agentOAuthSecret.spiffePrefix=spiffe://${DOMAIN}/sa --set uiOAuthSecret.useServiceAccountCA=false --set agentOAuthSecret.useServiceAccountCA=false
   ```

## Using the new ansible-based installer

You may also use the new ansible based installer to install the helm charts.

1. Copy example secrets file: `deployments/envs/secret_values.yaml.example` to `deployments/envs/.secret_values.yaml` and fill in the values in that file.

2. Run the installer as:

```bash
deployments/ansible/run-install.sh --env ocp
```

Check [Ansible README](../../deployments/ansible/README.md) for more details on the new installer.

To override existing environments, you may create a [customized override file](../../deployments/ansible/README.md#using-override-files).

## Checking the Spire daemonsets

After installation, check if the SPIRE daemonsets are correctly started with the command:

```shell
kubectl get daemonsets -n zero-trust-workload-identity-manager
```

If `Current` and/or `Ready` status is `0`, follow the steps in the [troubleshooting](#spire-daemonset-does-not-start) section.

## Authentication Configuration

Kagenti UI now supports Keycloak authentication by default. The `kagenti` helm chart creates automatically the required
`kagenti-ui-oauth-secret`in the `kagenti-system` namespace required by the UI.

```shell
  kubectl get secret keycloak-initial-admin -n keycloak -o go-template='Username: {{.data.username | base64decode}}  password: {{.data.password | base64decode}}{{"\n"}}'
```

## Access the UI

After the chart is installed, follow the instructions in the release notes to access the UI. To print the UI URL, run:

```shell
echo "https://$(kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.status.ingress[0].host}')"
```

### Login Process

1. Navigate to the UI URL
2. Click "Click to login" button
3. You will be redirected to Keycloak authentication page
4. Authenticate with your [Keycloak credentials](#authentication-configuration)
5. You will be redirected back to the Kagenti UI
6. You should see a welcome message confirming successful login

### Logout Process

1. Click the "Logout" button in the UI
2. Your session will be cleared
3. You will need to re-authenticate to access the UI again

If your OpenShift cluster uses self-signed route certificates, open that URL in your browser and accept the certificate.

You also need to retrieve and open the MCP Inspector proxy address so the MCP Inspector can establish a trusted connection to the MCP server and avoid failing silently. Print the proxy URL with:

```shell
echo "https://$(kubectl get route mcp-proxy -n kagenti-system -o jsonpath='{.status.ingress[0].host}')"
```

Open the printed address in your browser and accept the certificate. It is normal to see a `Cannot GET /` message — this indicates the proxy is reachable but not serving an HTML page; you can safely close the tab.

## Running the demo

You may use the pre-built images available at [https://github.com/orgs/kagenti/packages?repo_name=agent-examples](https://github.com/orgs/kagenti/packages?repo_name=agent-examples) or build from source. Agents support both Ollama and OpenAI backends — select the appropriate environment variable set when importing an agent. See the [Local Models Guide](../local-models.md) for details.

Building from source has been tested only with `quay.io`, and requires setting up a robot account on [quay.io](https://quay.io), creating empty repos in your organization for the repos to build (e.g.`a2a-contact-extractor` and `a2a-currency-converter`) and granting the robot account write access to those repos.

Finally, you may get the Kubernetes secret from the robot account you created, and apply the secret to the namespaces
you enabled for agents and tools (e.g. `team1` and `team2`).

You should now be able to use the UI to:

- Import an agent
- List the agent
- Interact with the agent from the agent details page
- Import a MCP tool
- List the tool
- Interact with the tool from the tool details page

# Running the Demo

There are two ways to get the agent images for the demo: using pre-built images (recommended for a quick start) or building them from source. Both Ollama and OpenAI backends are supported — see the [Local Models Guide](../local-models.md) for details.

---

## Option 1: Use Pre-built Images (Recommended)

This is the fastest way to get started. The required images are already built and hosted on the GitHub Container Registry.

1. You can find all the necessary images here: **[kagenti/agent-examples Packages](https://github.com/orgs/kagenti/packages?repo_name=agent-examples)**
2. No image building or secret configuration is required. You can proceed directly to the **"Verifying in the UI"** section.

---

## Option 2: Build from Source

Follow this path if you want to build the agent container images yourself.

### Prerequisites

- A user or organization account on **[quay.io](https://quay.io)**.
- Namespaces created in your Kubernetes cluster where you will run agents and tools (e.g., `team1` and `team2`).

### Steps

1. **Configure Quay.io**
    - [Create a robot account](https://docs.redhat.com/en/documentation/red_hat_quay/3/html/user_guide/managing_robot_accounts) for your organization.
    - Create empty repositories for the images you need to build (e.g., `a2a-content-extractor` and `a2a-currency-converter`).
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

3. **Build and Push the Images**
    - Follow the project's build instructions to build the agent images and push them to your Quay.io repositories.

---

## Verifying in the UI

After completing either of the setup options above, you should be able to use the UI to:

- **Agents**
    1. Import a new agent.
    2. List the imported agent.
    3. Interact with the agent from its details page.
- **Tools**
    1. Import a new MCP tool.
    2. List the imported tool.
    3. Interact with the tool from its details page.

## Accessing Keycloak

You may access Keycloak from the Admin page. The initial credentials for Keycloak can be found
running the command:

```shell
kubectl get secret keycloak-initial-admin -n keycloak -o go-template='Username: {{.data.username | base64decode}}  password: {{.data.password | base64decode}}{{"\n"}}'
```

## Troubleshooting

### Spire daemonset does not start

Run the following command:

```shell
kubectl get daemonsets -n zero-trust-workload-identity-manager
```

If the daemonsets are not correctly started ('Current' and/or 'Ready' status is '0') the agent client registration will not work.

Run the following commands:

```shell
kubectl describe daemonsets -n zero-trust-workload-identity-manager spire-agent
kubectl describe daemonsets -n zero-trust-workload-identity-manager spire-spiffe-csi-driver
```

If any of them shows `Events` including messages such as `Error creating: pods <pod-name-prefix> is forbidden: unable to validate against any security context constraint`, run the following commands:

```shell
oc adm policy add-scc-to-user privileged -z spire-agent -n zero-trust-workload-identity-manager
kubectl rollout restart daemonsets -n zero-trust-workload-identity-manager spire-agent

oc adm policy add-scc-to-user privileged -z spire-spiffe-csi-driver -n zero-trust-workload-identity-manager
kubectl rollout restart daemonsets -n zero-trust-workload-identity-manager spire-spiffe-csi-driver
```

Wait a few seconds and verify that the daemonsets are correctly started:

```shell
kubectl get daemonsets -n zero-trust-workload-identity-manager
```

### Upgrade from OCP 4.18 to 4.19

If the only available option is OpenShift 4.18, you can always upgrade the cluster.

We tested upgrades with two OCP Platforms:
<details>
  <summary><strong>Red Hat OpenShift Container Platform Cluster (AWS)</strong></summary>

Steps:

1. First Update the channel

```shell
oc patch clusterversion version --type merge -p '{"spec":{"channel":"fast-4.19"}}'
```

2. Then apply the acks to acknowledge you understand the changes that are associated with the 4.19 upgrade

```shell
oc -n openshift-config patch cm admin-acks --patch '{"data":{"ack-4.18-kube-1.32-api-removals-in-4.19":"true"}}' --type=merge
oc -n openshift-config patch cm admin-acks --patch '{"data":{"ack-4.18-boot-image-opt-out-in-4.19":"true"}}' --type=merge
```

3. Upgrade to the latest version

```shell
oc adm upgrade --to-latest=true --allow-not-recommended=true
```

You can ignore the warnings, the upgrade should be happening.

4. Monitor the upgrade status:

```shell
oc get clusterversion
```

</details>

Another option, that just stopped working recently:
<details>
  <summary><strong>Single Node</strong></summary>

If you use a `Single Node`, make sure you have a reasonably large instance (at least 24 cores, 64 Gi).

Steps:

1. First Update the channel

```shell
oc patch clusterversion version --type merge -p '{"spec":{"channel":"stable-4.19"}}'
```

2. Then apply the acks to acknowledge you understand the changes that are associated with the 4.19 upgrade

```shell
oc -n openshift-config patch cm admin-acks --patch '{"data":{"ack-4.18-kube-1.32-api-removals-in-4.19":"true"}}' --type=merge
```

3. Upgrade to the latest version

```shell
oc adm upgrade --to-latest=true --allow-not-recommended=true
```

You can ignore the warnings, the upgrade should be happening.

4. Monitor the upgrade status:

```shell
oc get clusterversion
```
</details>

### SPIRE Configuration

Kagenti uses SPIRE for workload identity management. The installation method varies by OpenShift version.

#### Using the Ansible Installer (Recommended)

The ansible-based installer automatically detects your OpenShift version and selects the appropriate SPIRE installation method:

| OCP Version | What Happens |
|-------------|--------------|
| 4.19.0+ | Installs ZTWIM operator via OLM |
| 4.16.0 - 4.18.x | Installs SPIRE via upstream Helm charts |

No manual intervention is required - the installer handles everything automatically.

#### Manual Helm Chart Installation

When installing Kagenti manually with Helm charts on OCP < 4.19, you need to:

1. **Tell kagenti-deps to skip ZTWIM operator** and indicate Helm charts will be used:

```shell
# Install kagenti-deps with useSpireHelmChart=true
helm install kagenti-deps ./charts/kagenti-deps/ -n kagenti-system --create-namespace \
  --set spire.trustDomain=${DOMAIN} \
  --set openshift=true \
  --set useSpireHelmChart=true \
  --wait
```

2. **Install SPIRE Helm charts separately**:

```shell
# Add SPIFFE Helm repo
helm repo add spiffe https://spiffe.github.io/helm-charts-hardened/
helm repo update

# Install SPIRE CRDs
helm install spire-crds spiffe/spire-crds -n spire-system --create-namespace

# Install SPIRE
helm install spire spiffe/spire -n spire-system \
  --set global.spire.trustDomain=${DOMAIN}
```

For OCP 4.19+, you can let kagenti-deps install the ZTWIM operator automatically (default behavior).

### Cert Manager Configuration

Kagenti requires cert-manager for TLS certificate management. On OpenShift, cert-manager may already be installed by other operators such as OpenShift Pipelines (Tekton).

#### Using the Ansible Installer (Recommended)

The ansible-based installer automatically detects existing cert-manager installations, including:
- Cert-manager installed via OLM (Operator Lifecycle Manager)
- Cert-manager installed by OpenShift Pipelines/Tekton operator

When an existing cert-manager is detected, the installer will:
1. Skip the cert-manager operator installation
2. Use the existing cert-manager installation
3. Wait for the CRDs and webhook to be ready before proceeding

No manual intervention is required when using the ansible installer.

#### Manual Helm Chart Installation

When installing Kagenti manually with Helm charts, you need to handle cert-manager appropriately.

**Check if cert-manager is already installed:**

```shell
# Check for cert-manager CRDs
kubectl get crd certificates.cert-manager.io

# Check for running cert-manager pods
kubectl get pods -n cert-manager
```

**Option 1: Use existing cert-manager (Recommended)**

If cert-manager is already running (e.g., installed by OpenShift Pipelines), you can skip installing it via kagenti-deps:

```shell
# Install kagenti-deps with cert-manager disabled
helm install kagenti-deps ./charts/kagenti-deps/ -n kagenti-system --create-namespace \
  --set spire.trustDomain=${DOMAIN} \
  --set components.certManager.enabled=false \
  --wait
```

Or when using OCI charts:

```shell
helm install --create-namespace -n kagenti-system kagenti-deps \
  oci://ghcr.io/kagenti/kagenti/kagenti-deps --version $LATEST_TAG \
  --set spire.trustDomain=${DOMAIN} \
  --set components.certManager.enabled=false
```

**Option 2: Remove existing cert-manager and let Kagenti install it**

If you prefer Kagenti to manage cert-manager, remove the existing installation first:

Using the OpenShift Container Platform web console:

1. Log in to the OpenShift Container Platform web console.
2. Go to Operators > Installed Operators.
3. Locate the cert-manager Operator for Red Hat OpenShift in the list.
4. Click the Options menu (three vertical dots) next to the operator.
5. Select Uninstall Operator.

Then from the console:

```shell
kubectl delete deploy cert-manager cert-manager-cainjector cert-manager-webhook -n cert-manager
kubectl delete service cert-manager cert-manager-cainjector cert-manager-webhook -n cert-manager
kubectl delete ns cert-manager-operator cert-manager
```

After removal, install kagenti-deps with cert-manager enabled (the default):

```shell
helm install kagenti-deps ./charts/kagenti-deps/ -n kagenti-system --create-namespace \
  --set spire.trustDomain=${DOMAIN} \
  --set components.certManager.enabled=true \
  --wait
```

#### Resolving Conflicts with OpenShift Pipelines Operator

OpenShift Pipelines (Tekton) can install its own internal cert-manager, which may conflict with a cluster-wide cert-manager installation. This can cause CRD conflicts where two cert-managers fight over the same Custom Resource Definitions.

**Symptoms of conflict:**
- cert-manager pods repeatedly restarting
- Certificate resources not being reconciled properly
- Errors in cert-manager logs about CRD ownership

**Solution: Configure TektonConfig to use external cert-manager**

OpenShift Pipelines 1.12+ can be configured to use an existing cluster-wide cert-manager. The ansible installer automatically patches the TektonConfig when it detects this scenario.

For manual installations, apply this configuration:

```shell
kubectl patch tektonconfig config --type=merge -p '
spec:
  params:
    - name: createRbacResource
      value: "true"
  targetNamespace: openshift-pipelines
'
```

This configuration:
- Ensures proper RBAC resource creation for Tekton components
- Sets the correct target namespace for OpenShift Pipelines
- Prevents conflicts with external cert-manager installations

**Note:** When using the ansible installer (`deployments/ansible/run-install.sh --env ocp`), this patch is applied automatically.

**Alternative: Disable Tekton Results**

If you don't need Tekton Results or Pipelines as Code features, you can disable them to avoid cert-manager dependencies:

```yaml
spec:
  platforms:
    openshift:
      pipelinesAsCode:
        enable: false
```

**Alternative: Use specific Pipelines Operator channel**

Check the Subscription of the Pipelines Operator for channels that don't bundle cert-manager:

```shell
oc get subscription openshift-pipelines-operator-rh -n openshift-operators -o yaml
```

Look for alternative channels in the PackageManifest that may have different dependency configurations:

```shell
oc get packagemanifest openshift-pipelines-operator-rh -o jsonpath='{.status.channels[*].name}'
```

**Recommended installation order:**

1. Install cert-manager Operator for Red Hat OpenShift (or let Kagenti install it)
2. Ensure cert-manager is fully healthy
3. Install OpenShift Pipelines, configuring it to use the existing cert-manager
4. Install Kagenti

If conflicts persist after installation:

```shell
# Check which cert-manager is running
kubectl get pods -n cert-manager -o wide

# Check for CRD conflicts
kubectl get crd certificates.cert-manager.io -o yaml | grep -A5 'ownerReferences'
```
