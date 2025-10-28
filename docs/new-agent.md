# Importing a New Agent into the Platform from a Code Base

## Pre-requisites

When deploying a new agent, you may either deploy from source code or from a pre-existing container image. When deploying from source code, Kagenti will retrieve the source code from GitHub. Kagenti will build your agent by deploying the code into a container based up on the Dockerfile you provide. When deploying from an image, it is expected that the agent code already exists in the container image, so the GitHub retrieval of the code and its installation will be skipped.

### Deploying from Source
Before importing a new agent from source, ensure that:
1. The agent code is hosted on GitHub and is accessible using the GitHub credentials provided [during the Kagenti installation](https://github.com/kagenti/kagenti/blob/main/docs/demos.md). 
2. The agent code is organized within a sub-directory of the Git repository (not in the root directory).
3. The root of the subdirectory contains a Dockerfile.

### Deploying from an Image
Before importing a new agent from an existing Docker image, ensure that the Docker image is available in an accessible container registry.

## Agent Examples

See the [Kagenti agent examples repo](https://github.com/kagenti/agent-examples) for a variety of agents and MCP tool examples.

## Steps to Import a New Agent
To import a new agent into the platform, follow these steps:

### Step 1: Access the Import New Agent Section
- Log in to the Kagenti UI.
- Navigate to the "Import New Agent" section.

### Step 2: Select the Namespace
- Choose the namespace where you want to deploy the agent.

### Step 3: Configure Environment Variables
- Manually add environment variables required by your agent.
- Alternatively, import environment variables from a `.env` file hosted on GitHub.

### Using Secrets / ConfigMaps from .env files

The Kagenti UI supports importing environment variables from a `.env` file. To safely reference Kubernetes Secrets or ConfigMaps from a `.env` file (instead of embedding secret plaintext), the `.env` value may contain a JSON object which will be interpreted as a structured environment entry and mapped to Kubernetes `valueFrom` entries in the agent's manifest.

Important notes:

- JSON values must be quoted in the `.env` file so they survive shell parsing. Either single or double quotes are accepted.
- If the JSON contains a `valueFrom` object it will be used as-is. A shorthand form is also supported: supplying `secretKeyRef` or `configMapKeyRef` at the top-level will be wrapped under `valueFrom` automatically.
- The UI will NOT store secret plaintext in repository or ConfigMaps. When you reference a Secret via `secretKeyRef`, Kagenti will include a `valueFrom` reference in the generated Component but it will not create or populate the Kubernetes Secret for you — you must ensure the referenced Secret exists in the target namespace.
- Invalid JSON will be left as a plain string and the UI will show a warning during import.

Examples (in your `.env` file):

Plain value:

```ini
MCP_URL=http://weather-tool:8080/mcp
```

Secret reference (valueFrom provided explicitly):

```ini
OPENAI_API_KEY='{"valueFrom": {"secretKeyRef": {"name": "openai-secret", "key": "apikey"}}}'
```

Secret shorthand (top-level secretKeyRef will be wrapped into valueFrom):

```ini
OPENAI_API_KEY='{"secretKeyRef": {"name": "openai-secret", "key": "apikey"}}'
```

ConfigMap reference example:

```ini
WEATHER_CONFIG='{"configMapKeyRef": {"name": "weather-config", "key": "settings"}}'
```

Migration notes

- If you previously kept secrets as plaintext in your `.env` files, move them into Kubernetes Secrets and update the `.env` to reference them using the JSON examples above. Do not commit plaintext secrets to source control.
- When editing existing `.env` entries in the Kagenti UI, you can toggle a variable to "Structured" and paste the JSON; the UI will validate the JSON. If you switch back to plain mode, structured data will be removed from the in-memory representation.
- Ensure the referenced Secrets/ConfigMaps are present in the target namespace before deploying; otherwise your agent pods will fail to resolve the environment values.

**Quick Secret creation example**

Below is a minimal example showing how to create a Kubernetes Secret with an API key and then reference it from your `.env` file.

Create the Secret (replace <NAMESPACE> and <YOUR_API_KEY>):

```bash
kubectl create secret generic openai-secret \
	--from-literal=apikey='<YOUR_API_KEY>' \
	-n <NAMESPACE>
```

Then in your `.env` file reference the Secret using JSON (note the single quotes around the JSON to keep it as one value in the `.env`):

```ini
OPENAI_API_KEY='{"valueFrom": {"secretKeyRef": {"name": "openai-secret", "key": "apikey"}}}'
```

When Kagenti imports this `.env` entry it will add an env var to the generated Component manifest that uses `valueFrom.secretKeyRef` to pull the `apikey` from the `openai-secret` in the target namespace.


### Step 4: Select Deployment Method

#### Deploy from an existing Docker image.
- Select "deploy from existing image" as the deployment method, and provide the address of the image in a remote container registry

#### Deploy from source code.

1. Select "Build from source" as the deployment method
2. In "Agent Source Repository URL", enter the root of your GitHub repository where your agent project lives.
3. In "Git Branch or Tag" - If your agent project exists in a different branch than Main, specify the branch or tag
4. Under "select protocol", specify an agent-to-agent communication protocol: A2A or ACP. Note: ACP is being deprecated.
5. Under "Specify Source Subfolder" type the name of the subfolder of your Git repo where the agent code can be found.

## Step 5: Build New Agent

Press the "Build New Agent" button. There will be continual status updates in the UI as the deployment progresses and completes.

## Testing agents

1. Once the deployment is complete, click "Agent Catalog". There you will see a list of available agents. 
2. Click "View Details" under the agent you wish to test.
3. At the bottom of the screen, you may enter text in the "chat with agent" text box at the bottom of the page in order to send messages to the agent for testing.

## Troubleshooting
If you encounter issues during agent deployment, you can troubleshoot by inspecting the Kubernetes artifacts produced during the deployment process.

- The custom resource created is called a `Component`.
- The `Component` creates a `Deployment`, which in turn creates pods that belong to the deployment of the agent.
- You can tail the logs of the pods to troubleshoot any errors.
- If the agent fails to deploy, there will be artifact pods in the namespace for building and deploying the agent; you may inspect those logs.

By following these steps and troubleshooting tips, you can successfully import and deploy your new agent into the platform.
