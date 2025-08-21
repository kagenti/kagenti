# Cloud Native Proofs-Of-Concept

The following proof on concepts apply Cloud Native technologies to manage agentic workloads.
A diagram and description of the demo architecture is provided [here](./tech-details.md#cloud-native-agent-platform-demo)

## Installation

### Prerequisites

Before running the demo setup script, ensure you have the following prerequisites in place:

* **Python:** Python versionn >=3.9
* **uv:** [uv](https://docs.astral.sh/uv/getting-started/installation) must be installed (e.g. `pip install uv`)
* **Docker:** Docker Desktop, Rancher Desktop or Podman Machine. You must alias it to `docker` (e.g. `sudo ln -s /opt/homebrew/bin/podman /usr/local/bin/docker`). On MacOS, you will need also to do `brew install docker-credential-helper`. *Not required if using `--use-existing-cluster`*.
  * In Rancher Decktop, configure VM size to at least 8GB of memory and 4 cores
* **Kind:** A [tool](https://kind.sigs.k8s.io) to run a Kubernetes cluster in docker (e.g. `brew install kind`). *Not required if using `--use-existing-cluster`*.
* **kubectl:** The Kubernetes command-line tool (installs with **kind**).
* **Helm:** A package manager for Kubernetes (e.g. `brew install helm`).
* **[ollama](https://ollama.com/download)** to run LLMs locally (e.g. `brew install ollama`). Then start the **ollama* service in the background (e.g.`ollama serve`).
* **GitHub Token:** Your [GitHub token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic) to allow fetching source and then to push docker image to ghcr.io repository. Make sure to grant: `repo(all), read/write packages`. Make sure to choose the "classic" token instead of the "fine-grained" token.
* **OpenAI API Key:** The [OpenAI API Key](https://platform.openai.com/api-keys) for accessing A2A agents. Select `read only`.

At this time the demo has only been tested on MacOS with M1 processor.

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
OPENAI_API_KEY=<This is required only for A2A agents, if only using the ACP agents can just put a placeholder>
AGENT_NAMESPACES=<comma separated list of Kubernetes namespaces to set up in Kind for agents deployment e.g., `team1,team2`>
```

Run the installer.

```shell
cd kagenti/installer
uv run kagenti-installer
```

The installer creates a kind cluster named `agent-platform` and then deploys all platform components.

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

**Note:** When using an existing cluster, you may want to skip the registry component as it's primarily designed for kind clusters:

```shell
uv run kagenti-installer --use-existing-cluster --skip-install registry
```

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

From the UI, you can:

* Import agents written in any framework, wrapped with either the A2A or ACP protocol.
* Import and deploy MCP Server tools directly from source.
* Test agents interactively and inspect their behavior.
* Monitor traces, logs, and network traffic between agents and tools.

## Detailed Instructions for Running the Weather Demo

For step-by-step instructions for importing and running agents and tools, see

* [How to Build, Deploy, and Run the Weather Agent Demo](./demo-weather-agent.md)

## Importing Your Own Agent to Kagenti

See the document: [Importing Your Own Agent to Kagenti](new-agent.md)

## Troubleshooting

### kagenti-installer reports "exceeded its progress deadline"

Sometimes it can take a long time to pull container images.  Try re-running the installer.

### Agent stops responding through gateway

Restart the following daemonset

```shell
kubectl rollout restart daemonset -n istio-system  ztunnel
```

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

### Agent log shows communication errors

Kagenti UI shows Connection errors:

```console
Error: Failed to process weather request. Connection error.
```

Agent log shows errors:

```console
kagenti$ kubectl -n teams logs -f acp-weather-service-7f984f478d-4jzv9
.
.
ERROR:    Graph execution error: Connection error.
ERROR:acp:Run failed
Traceback (most recent call last):
  File "/app/.venv/lib/python3.11/site-packages/acp_sdk/server/bundle.py", line 151, in _execute
    generic = AnyModel.model_validate(next)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.11/site-packages/pydantic/main.py", line 703, in model_validate
    return cls.__pydantic_validator__.validate_python(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
pydantic_core._pydantic_core.ValidationError: 1 validation error for AnyModel
  Input should be a valid dictionary or instance of AnyModel [type=model_type, input_value=ACPError(), input_type=ACPError]
```

Most likely the ACP protocol is failing because *ollama* service is not installed or running.

Start *ollama* service in the terminal and keep it running:

```console
ollama serve
```

Then try the prompt again.

### Using Podman instead of Docker

The install script expects `docker` to be in your runtime path.

A few problem fixes might include:

* create `/usr/local/bin/docker` link to podman:

  ```console
   sudo ln -s /opt/podman/bin/podman /usr/local/bin/docker
   ```

* install `docker-credential-helper`:

   ```console
   brew install docker-credential-helper
   ```

* fix an issue with `insufficient memory to start keycloak`:

   ```console
   podman machine stop
   podman machine set --memory=8192
   podman machine start
   ```

* clean, fresh Podman start:

   ```console
   podman machine rm -f 
   podman machine init
   podman machine set --memory=8192
   podman machine start
   ```

* clean the cluster, keep the Podman VM as is:

  ```console
  kind delete cluster --name agent-platform
  ```
