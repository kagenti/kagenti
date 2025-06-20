# Cloud Native Proof-Of-Concepts

The following proof on concepts apply Cloud Native technologies to manage agentic workloads.
A diagram and description of the demo architecture is provided [here](./tech-details.md#cloud-native-agent-platform-demo)

## Installation

### Prerequisites

Before running the demo setup script, ensure you have the following prerequisites in place:

* **Python:** Python versionn >=3.9
* **uv** [uv](https://docs.astral.sh/uv/getting-started/installation) must be installed (e.g. `pip install uv`)
* **Docker:** Docker Desktop, Rancher Desktop or Podman Machine.
* **Kind:** A [tool](https://kind.sigs.k8s.io) to run a Kubernetes cluster in docker.
* **kubectl:** The Kubernetes command-line tool.
* **Helm:** A package manager for Kubernetes.
* **GitHub Token:** Your [GitHub token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic) to allow fetching source and then to push docker image to ghcr.io repository. Make sure to grant: `repo(all), read/write packages`. Make sure to choose the "classic" token instead of the "fine-grained" token.
* **OpenAI API Key:** The [OpenAI API Key](https://platform.openai.com/api-keys) for accessing A2A agents. Select `read only`.
* **[ollama](https://ollama.com/download)** to run LLMs locally.

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
cp kagenti/installer/src/.env_template kagenti/installer/src/.env
```

Edit the file `kagenti/installer/src/.env` to fill in the following:

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

To skip installation of the specific component issue, e.g. keycloak:

```shell
uv run kagenti-installer --skip-install keycloak
```

To get a full list of components and available install parameters issue:

```shell
uv run kagenti-installer --help
```

## Run the demo

Open the Agent Platform Demo Dashboard:

```shell
open http://kagenti-ui.localtest.me:8080
```

You can import agents written in any framework and wrapped with a2a or acp from github repos, test the agents
and monitor traces and network traffic. You may also import mcp server from source and deploys them on the platform.

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
