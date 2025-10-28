# Kagenti Installation on OpenShift

**This document is work in progress**

## Current limitations 

These limitations will be addressed in successive PRs.

- UI Auth and token management is disabled
- Only [quay.io](https://quay.io) registry has been tested in build from source
- Ollama models not tested - OpenAI key required for now

## Requirements 

- helm >= v3.18.0
- kubectl >= v1.32.1 or oc >= 4.16.0
- git >= 2.48.0
- Access to OpenShift cluster with admin authority (We tested with OpenShift 4.18.21)

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
      LATEST_TAG=$(git ls-remote --tags --sort="v:refname" https://github.com/kagenti/kagenti.git | tail -n1 | sed 's|.*refs/tags/||; s/\^{}//')
      ``` 
      if this command fails, visit [this page](https://github.com/kagenti/kagenti/pkgs/container/kagenti%2Fkagenti/versions) to determine the latest version to use.


   This chart includes all the OpenShift software components required by Kagenti.
   ```shell

   helm install --create-namespace -n kagenti-system kagenti-deps oci://ghcr.io/kagenti/kagenti/kagenti-deps --version $LATEST_TAG
   ```
4.  **Kagenti Helm Chart Installation:**
   This chart includes Kagenti software components and configurations.
   ```shell
   helm upgrade --install --create-namespace -n kagenti-system -f .secrets.yaml kagenti oci://ghcr.io/kagenti/kagenti/kagenti --version $LATEST_TAG
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
   helm install kagenti-deps ./charts/kagenti-deps/ -n kagenti-system --create-namespace 
   ```

5. **Install the Kagenti Chart:**
 
   - Open [kagenti-platform-operator-chart](https://github.com/kagenti/kagenti-operator/pkgs/container/kagenti-operator%2Fkagenti-platform-operator-chart) to find the latest available version (e.g., 0.2.0-alpha.12).
   - Open charts/kagenti/Chart.yaml and set the version field for kagenti-platform-operator-chart to match the latest tag.
   - If you updated the version tag, run the following command to update the chart dependencies:
     ```shell
      helm dependency update ./charts/kagenti/
      ```
   - Determine the latest tag with the command:
      ```shell
      LATEST_TAG=$(git ls-remote --tags --sort="v:refname" https://github.com/kagenti/kagenti.git | tail -n1 | sed 's|.*refs/tags/||; s/\^{}//')
      ```
      if this command fails, visit [this page](https://github.com/kagenti/kagenti/pkgs/container/kagenti%2Fkagenti/versions) to determine the latest version to use.

   Install the kagenti chart as follows:

   ```shell
   helm upgrade --install kagenti ./charts/kagenti/ -n kagenti-system --create-namespace -f ./charts/kagenti/.secrets.yaml
   ```

## Access the UI

After the chart is installed, follow the instructions in the release notes to access the UI. To print the UI URL, run:

```shell
echo "https://$(kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.status.ingress[0].host}')"
```

If your OpenShift cluster uses self-signed route certificates, open that URL in your browser and accept the certificate.

You also need to retrieve and open the MCP Inspector proxy address so the MCP Inspector can establish a trusted connection to the MCP server and avoid failing silently. Print the proxy URL with:

```shell
echo "https://$(kubectl get route mcp-proxy -n kagenti-system -o jsonpath='{.status.ingress[0].host}')"
```

Open the printed address in your browser and accept the certificate. It is normal to see a `Cannot GET /` message — this indicates the proxy is reachable but not serving an HTML page; you can safely close the tab.

## Running the demo

At this time, only the OpenAI API-backed agents have been tested (`a2a-content-extractor` and `a2a-currency-converter`).
You may use the pre-built images available at https://github.com/orgs/kagenti/packages?repo_name=agent-examples
or build from source. Building from source has been tested only with `quay.io`, and requires setting up a robot account on [quay.io](https://quay.io), creating empty repos in your organization for the repos to build (e.g.`a2a-contact-extractor` and `a2a-currency-converter`) and granting the robot account write access to those repos.

Finally, you may get the Kubernetes secret from the robot account you created, and apply the secret to the namespaces
you enabled for agents and tools (e.g. `team1` and `team2`). 

You should now be able to use the UI to:

- Import an agent
- List the agent
- Interact with the agent from the agent details page
- Import a MCP tool 
- List the tool 
- Interact with the tool from the tool details page


# 🚀 Running the Demo

> **Note**
> At this time, only the OpenAI API-backed agents have been tested: `a2a-content-extractor` and `a2a-currency-converter`.

There are two ways to get the agent images for the demo: using pre-built images (recommended for a quick start) or building them from source.

---

## Option 1: Use Pre-built Images (Recommended)

This is the fastest way to get started. The required images are already built and hosted on the GitHub Container Registry.

1.  You can find all the necessary images here: **[kagenti/agent-examples Packages](https://github.com/orgs/kagenti/packages?repo_name=agent-examples)**
2.  No image building or secret configuration is required. You can proceed directly to the **"Verifying in the UI"** section.

---

## Option 2: Build from Source

Follow this path if you want to build the agent container images yourself.

### Prerequisites

* A user or organization account on **[quay.io](https://quay.io)**.
* Namespaces created in your Kubernetes cluster where you will run agents and tools (e.g., `team1` and `team2`).

### Steps

1.  **Configure Quay.io**
    * [Create a robot account](https://docs.redhat.com/en/documentation/red_hat_quay/3/html/user_guide/managing_robot_accounts) for your organization.
    * Create empty repositories for the images you need to build (e.g., `a2a-content-extractor` and `a2a-currency-converter`).
    * Grant your robot account **write access** to these new repositories.

2.  **Create Kubernetes Image Pull Secret**
    * Navigate to your robot account settings in the Quay.io UI.
    * Select the **Kubernetes Secret** tab and copy the generated secret manifest.
    * Apply the secret to each namespace where agents will run.
      ```bash
      # Save the secret to a file named quay-secret.yaml, then run:
      kubectl apply -f quay-secret.yaml -n team1
      kubectl apply -f quay-secret.yaml -n team2
      ```

3.  **Build and Push the Images**
    * Follow the project's build instructions to build the agent images and push them to your Quay.io repositories.

---

## ✅ Verifying in the UI

After completing either of the setup options above, you should be able to use the UI to:

* **Agents**
    1.  Import a new agent.
    2.  List the imported agent.
    3.  Interact with the agent from its details page.
* **Tools**
    1.  Import a new MCP tool.
    2.  List the imported tool.
    3.  Interact with the tool from its details page.

## Accessing Keycloak

You may access Keycloak from the Admin page. The initial credentials for Keycloak can be found
running the command:

```shell
kubectl get secret keycloak-initial-admin -n keycloak -o go-template='Username: {{.data.username | base64decode}}  password: {{.data.password | base64decode}}{{"\n"}}'
```

## Troubleshooting

### Readiness checks fail for pods in namespaces with istio ambient enabled 

This is a specific [issue](https://github.com/kagenti/kagenti/issues/329) for 
OpenShift with Network Type `OVNKubernetes`. 

This occurs because OVNKubernetes' default "shared gateway mode" causes 
health probe traffic from the kubelet to bypass the host network stack. This 
prevents the Ztunnel proxy from intercepting the traffic and incorrectly fails the probes.

To inspect the Network Type you can run the command:

```shell
kubectl describe network.config/cluster
```

**Workaround**

To fix this, you must set `routingViaHost: true` in your gatewayConfig when 
deploying ambient mode. This forces OVNKubernetes to use "local gateway mode," 
which correctly routes traffic through the host and allows the probes to function properly.

```shell
kubectl patch network.operator.openshift.io cluster --type=merge -p '{"spec":{"defaultNetwork":{"ovnKubernetesConfig":{"gatewayConfig":{"routingViaHost":true}}}}}'
```

