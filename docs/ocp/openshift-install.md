# Kagenti Installation on OpenShift

**This document is work in progress**

## Current limitations 

These limitations will be addressed in successive PRs.

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
   helm upgrade --install kagenti ./charts/kagenti/ -n kagenti-system --create-namespace -f ./charts/kagenti/.secrets.yaml --set ui.tag=${LATEST_TAG}
   ```

## Authentication Configuration

Kagenti UI now supports Keycloak authentication by default.

### Prerequisites

**IMPORTANT**: Before accessing the UI, you must create a Kubernetes secret named `kagenti-ui-oauth-secret` in the `kagenti-system` namespace with the following keys:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kagenti-ui-oauth-secret
  namespace: kagenti-system
type: Opaque
stringData:
  ENABLE_AUTH: "true"
  CLIENT_ID: "kagenti"
  CLIENT_SECRET: "<your-keycloak-client-secret>"
  AUTH_ENDPOINT: "https://<keycloak-route>/realms/master/protocol/openid-connect/auth"
  TOKEN_ENDPOINT: "https://<keycloak-route>/realms/master/protocol/openid-connect/token"
  REDIRECT_URI: "https://<ui-route>/oauth2/callback"
  SCOPE: "openid profile email"
  SSL_CERT_FILE: "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
```

Replace the placeholders:

**1. Get Keycloak client secret:**

First, find the Keycloak admin username and password in the `keycloak` namespace.

Then, log in to the Keycloak admin console:
1. Navigate to the Keycloak route URL
2. Log in with admin credentials
3. Go to **Clients** in the left sidebar
4. Click on the `kagenti` client
5. Go to the **Credentials** tab
6. Copy the **Client Secret** value

**2. Get route hostnames:**
```shell
# Get Keycloak route
KEYCLOAK_ROUTE=$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}')

# Get UI route  
UI_ROUTE=$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}')

echo "Keycloak route: $KEYCLOAK_ROUTE"
echo "UI route: $UI_ROUTE"
```

**3. Update the secret:**

Replace in the YAML above:
- `<your-keycloak-client-secret>`: The client secret from Keycloak (step 1)
- `<keycloak-route>`: Value of `$KEYCLOAK_ROUTE`
- `<ui-route>`: Value of `$UI_ROUTE`

### Authentication Features

- **Keycloak Integration**: Uses the deployed Keycloak instance for authentication
- **Automatic Token Management**: Handles token refresh and session management
- **User Session Management**: Supports login/logout functionality
- **SSL Certificate Handling**: Automatically handles OpenShift self-signed certificates

## Access the UI

After the chart is installed, follow the instructions in the release notes to access the UI. To print the UI URL, run:

```shell
echo "https://$(kubectl get route kagenti-ui -n kagenti-system -o jsonpath='{.status.ingress[0].host}')"
```

### Login Process

1. Navigate to the UI URL
2. Click "Click to login" button
3. You will be redirected to Keycloak authentication page
4. Authenticate with your Keycloak credentials
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

