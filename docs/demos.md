# Cloud Native Proofs-Of-Concept

The following proof on concepts apply Cloud Native technologies to manage agentic workloads.
A diagram and description of the demo architecture is provided on [technical details](./tech-details.md#cloud-native-agent-platform-demo) page.

Detailed overview of the identity concepts are covered in the [Kagenti Identity PDF document](./2025-10.Kagenti-Identity.pdf).

## Demo List

Check the details for running various demos.

- Simplest Demo - [Weather Service](./demo-weather-agent.md)
- Identity & Auth Demo - [Slack Authentication](./demo-slack-research-agent.md)
- Github issue demo - [Github Issue Agent](./demo-github-issue.md)

## Installation

For installing on OpenShift, please refer to [these installation instructions](./ocp/openshift-install.md).

**Note: OpenShift support is currently a work in progress. Be sure to review the limitations detailed in the instructions.**

### Prerequisites

Before running the demo setup script, ensure you have the following prerequisites in place:

- **Python:** Python version >=3.9
- **uv:** [uv](https://docs.astral.sh/uv/getting-started/installation) must be installed (e.g. `pip install uv`)
- **Docker:** Docker Desktop, Rancher Desktop or Podman Machine. You must alias it to `docker` (e.g. `sudo ln -s /opt/homebrew/bin/podman /usr/local/bin/docker`). On MacOS, you will need also to do `brew install docker-credential-helper`. *Not required if using `--use-existing-cluster`*.
  - On Rancher or Podman Desktop, configure VM size to at least 12 GB of memory and 4 cores
  - On Podman Desktop, make sure you use a machine with [rootful connection](https://podman-desktop.io/docs/podman/setting-podman-machine-default-connection)
  - Make sure to increase your resource limits (for [rancher](https://docs.rancherdesktop.io/how-to-guides/increasing-open-file-limit/), for podman you may need to edit inside the machine the file `/etc/security/limits.conf` and restart the machine)
- **Kind:** A [tool](https://kind.sigs.k8s.io) to run a Kubernetes cluster in docker (e.g. `brew install kind`). *Not required if using `--use-existing-cluster`*.
- **kubectl:** The Kubernetes command-line tool (installs with **kind**).
- **Helm:** A package manager for Kubernetes (e.g. `brew install helm`).
- **[ollama](https://ollama.com/download)** to run LLMs locally (e.g. `brew install ollama`). Then start the **ollama* service in the background (e.g.`ollama serve`).
- **GitHub Token:** Your [GitHub token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic) to allow fetching source and then to push docker image to ghcr.io repository. Make sure to grant: `repo(all), read/write packages`. Make sure to choose the "classic" token instead of the "fine-grained" token.
- **OpenAI API Key:** The [OpenAI API Key](https://platform.openai.com/api-keys) for accessing A2A agents. Select `read only`.

At this time the demo has only been tested on MacOS and RHEL.

When you encounter any problems, review our [Troubleshooting](#troubleshooting) section.

#### Setup

Clone this project:

```shell
git clone https://github.com/kagenti/kagenti.git
cd kagenti
```

Setup your env variables:

```shell
cp kagenti/installer/app/.env_template kagenti/installer/app/.env
```

Edit the file `kagenti/installer/app/.env` to fill in the following:

```shell
GITHUB_USER=<Your public Github User ID>
GITHUB_TOKEN=<Your GitHub Token, as explained above>
OPENAI_API_KEY=<This is required only for A2A agents using OpenAI. Not needed when using ollama>
AGENT_NAMESPACES=<comma separated list of Kubernetes namespaces to set up in Kind for agents deployment e.g., `team1,team2`>
SLACK_BOT_TOKEN=<This is required only if you wish to use the Slack tool example.>
```

Run the installer.

```shell
cd kagenti/installer
uv run kagenti-installer
```

The installer creates a kind cluster named `agent-platform` and then deploys all platform components.

Using `--silent` flag removes the interactive install mode.

```shell
uv run kagenti-installer --silent
```

### Using an Existing Kubernetes Cluster

If you already have a Kubernetes cluster configured and want to skip the kind cluster creation, you can use the `--use-existing-cluster` flag:

```shell
uv run kagenti-installer --use-existing-cluster
```

This option will:
- Skip the kind and Docker dependency checks
- Use the cluster defined in your `KUBECONFIG` environment variable
- Skip kind-specific operations like image preloading
- Deploy all platform components to your existing cluster

Make sure your `KUBECONFIG` is properly set and points to a cluster where you have admin privileges before using this option.

**Note:** When using an existing cluster, the registry component is automatically skipped as it's primarily designed for kind clusters that have been initialized with a specific configuration.

To skip installation of the specific component e.g. keycloak and SPIRE, issue:

```shell
uv run kagenti-installer --skip-install keycloak --skip-install spire --skip-install mcp_gateway
```

To get a full list of components and available install parameters issue:

```shell
uv run kagenti-installer --help
```

## Connect to the Kagenti UI

Open the Kagenti UI in your browser:

```shell
open http://kagenti-ui.localtest.me:8080
```

You will be required to login using Kagenti userid.

*Important: Please note that Kagenti user is managed by Keycloak, so if you have Keycloak session open in another tab of your browser, Kagenti will be using the same Keycloak userid. To change the user, logout on Keycloak session first.*

### Default Kagenti Userid

Login with the default Kagenti userid:

```console
userid: admin
password: admin
```

From the UI, you can:

- Login and Logout with the Kagenti user id managed by Keycloak
- Import agents written in any framework, wrapped with the A2A protocol.
- Import and deploy MCP Server tools directly from source.
- Test agents interactively and inspect their behavior.
- Monitor traces, logs, and network traffic between agents and tools.

## Detailed Instructions for Running the Weather Demo

For step-by-step instructions for importing and running agents and tools, see

- [How to Build, Deploy, and Run the Weather Agent Demo](./demo-weather-agent.md)

## Importing Your Own Agent to Kagenti

See the document: [Importing Your Own Agent to Kagenti](new-agent.md)

## Identity

### SPIRE Setup

Spire configuration is defined in [spire-helm-values.yaml](../kagenti/installer/app/resources/spire-helm-values.yaml). SPIRE is deployed by default unless `--skip-install spire` is used.

To verify if OIDC service for SPIRE is properly setup execute the following:

```shell
curl http://spire-oidc.localtest.me:8080/keys
curl http://spire.localtest.me:8080/.well-known/openid-configuration
```

Test the Tornjak API access:

```shell
curl http://spire-tornjak-api.localtest.me:8080/
```

This should return something like:

```console
"Welcome to the Tornjak Backend!"
```

Now test the Tornjak UI access with browser:

```shell
open http://spire-tornjak-ui.localtest.me:8080/
```

### Keycloak

[Keycloak](https://www.keycloak.org/) is an Open Source Identity and Access Management tool used for managing access to various Kagenti components.

To access Keycloak:

```shell
open http://keycloak.localtest.me:8080/
```

The default Keyclaok admin credentials are:

```console
userid: admin
password: admin
```

---

## Troubleshooting

### kagenti-installer reports "exceeded its progress deadline"

Sometimes it can take a long time to pull container images.  Try re-running the installer.  Use `kubectl get deployments --all-namespaces` to identify failing deployments.

### Service stops responding through gateway

It may happens with Keycloak or even the UI.

Restart the following:

```shell
kubectl rollout restart daemonset -n istio-system  ztunnel
kubectl rollout restart -n kagenti-system deployment http-istio
```
### Blank UI page on macOS after installation
On macOS, if **Privacy and Content Restrictions** are enabled (under  
System Settings → Screen Time → Content & Privacy Restrictions),  
then after the Kagenti installation completes, opening the UI may display a blank loading page.

To fix, disable these restrictions and restart the UI.

### kagenti-installer complains "Please start the Docker daemon." when using Colima instead of Docker Desktop

```shell
export DOCKER_HOST="unix://$HOME/.colima/docker.sock"
```

### Need to change ENV values

If you need to update the values in `.env` file, e.g., `GITHUB_TOKEN`
delete the secret in all your auto-created namespaces, then re-run the install

```shell
kubectl get secret --all-namespaces
kubectl -n my-namespace delete github-token-secret
uv run kagenti-installer
```

### Pull Image errors while deploying components

If you see `Init:ErrImagePull` or `Init:ImagePullBackOff` errors while deploying components,
most likely your Github token expired. 

Error text:

```console
 failed to authorize: failed to fetch oauth token: unexpected status from GET request to https://ghcr.io/token?scope=repository%3Akagenti%2Fkagenti-client-registration%3Apull&service=ghcr.io: 403 Forbidden
```

Check your [personal access token (classic)](https://github.com/settings/personal-access-tokens/).
Make sure to grant scopes `all:repo`, `write:packages`, and `read:packages`.

You may also get "ghcr.io: 403 Forbidden" errors installing Helm charts during Kagenti installation.  You may have cached credentials that are no longer valid.  The fix is `docker logout ghcr.io`.

### Agent log shows communication errors

Kagenti UI shows Connection errors:

```console
An unexpected error occurred during A2A chat streaming: HTTP Error 503: Network communication error: peer closed connection without sending complete message body (incomplete chunked read)
```

Agent log shows errors:

```console
kagenti$ kubectl -n teams logs -f weather-service-7f984f478d-4jzv9
.
.
ERROR:    Exception in ASGI application
  + Exception Group Traceback (most recent call last):
  |   File "/app/.venv/lib/python3.11/site-packages/uvicorn/protocols/http/h11_impl.py", line 403, in run_asgi
  |     result = await app(  # type: ignore[func-returns-value]
  |              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  | ..
  +-+---------------- 1 ----------------
    | urllib3.exceptions.ProtocolError: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))
```

Most likely the A2A protocol is failing because *ollama* service is not installed or running.

Start *ollama* service in the terminal and keep it running:

```console
ollama serve
```

Then try the prompt again.

### Using Podman instead of Docker

The install script expects `docker` to be in your runtime path.

A few problem fixes might include:

- create `/usr/local/bin/docker` link to podman:

  ```console
   sudo ln -s /opt/podman/bin/podman /usr/local/bin/docker
   ```

- install `docker-credential-helper`:

   ```console
   brew install docker-credential-helper
   ```

- fix an issue with `insufficient memory to start keycloak`:

   ```console
   podman machine stop
   podman machine set --memory=8192
   podman machine start
   ```

- clean, fresh Podman start:

   ```console
   podman machine rm -f
   podman machine init
   podman machine set --memory=8192
   podman machine start
   ```

- clean the cluster, keep the Podman VM as is:

  ```console
  kind delete cluster --name agent-platform
  ```

### Keycloak stops working

Keycloak stops working and logs show [connection errors](https://github.com/kagenti/kagenti/issues/115).

At this time there is no reliable sequence of bringing down and up again
postgres and keycloak. The only reliable approach found so far is either to destroy and re-install
the cluster or delete and re-install keycloak as follows:

Make sure you are in `<kagenti-project-root>/kagenti/installer`, then:

```shell
kubectl delete -n keycloak -f app/resources/keycloak.yaml
kubectl apply -n keycloak -f app/resources/keycloak.yaml
kubectl rollout restart daemonset -n istio-system  ztunnel
kubectl rollout restart -n kagenti-system deployment http-istio
uv run kagenti-installer --skip-install registry --skip-install tekton --skip-install addons --skip-install gateway --skip-install spire --skip-install mcp_gateway --skip-install metrics_server --skip-install inspector --skip-install cert_manager
kubectl rollout restart -n kagenti-system deployment kagenti-ui
```

Deployed agents may need to be restarted to update the Keycloak client.

```shell
kubectl rollout restart -n <agent-namespace> deployment <agent-deployment e.g. weather-service>
```
