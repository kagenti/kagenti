# Importing a New MCP Tool into the Platform

## Overview

MCP (Model Context Protocol) tools extend the capabilities of AI agents by providing access to external services, APIs, and resources. Kagenti allows you to deploy MCP tools either from source code or from pre-existing container images.

> **💡 New to Kagenti?** This guide is designed for **Tool Developers**. If you're unsure about your role or want to understand the broader ecosystem, check out our **[Personas and Roles Documentation](../PERSONAS_AND_ROLES.md)**.

## Pre-requisites

### Deploying from Source

Before importing a new tool from source, ensure that:

1. The tool code is hosted on GitHub and is accessible using the GitHub credentials provided [during the Kagenti installation](./install.md).
2. The tool code is organized within a sub-directory of the Git repository (not in the root directory).
3. The root of the subdirectory contains a Dockerfile.
4. [Shipwright](https://shipwright.io) is installed in your cluster (included in the standard Kagenti installation).

### Deploying from an Image

Before importing a new tool from an existing Docker image, ensure that the Docker image is available in an accessible container registry.

## Tool Examples

See the [Kagenti agent examples repo](https://github.com/kagenti/agent-examples/tree/main/mcp) for a variety of MCP tool examples, including:

| Tool | Description |
|------|-------------|
| `weather_tool` | Weather information lookup |
| `slack_tool` | Slack messaging integration |
| `github_tool` | GitHub repository operations |
| `flight_tool` | Flight information service |
| `movie_tool` | Movie database lookup |
| `image_tool` | Image processing capabilities |

## Steps to Import a New Tool

### Step 1: Access the Import New Tool Section

- Log in to the Kagenti UI.
- Navigate to the "Import New Tool" section from the left menu.

### Step 2: Select the Namespace

- Choose the namespace where you want to deploy the tool.
- This should typically be the same namespace where your agents are deployed.

### Step 3: Configure Environment Variables

- Manually add environment variables required by your tool.
- Alternatively, import environment variables from a `.env` file hosted on GitHub.

> **Note:** Environment variables work the same way for tools as they do for agents. See [Using Secrets / ConfigMaps from .env files](./new-agent.md#using-secrets--configmaps-from-env-files) for details on referencing Kubernetes Secrets.

### Step 4: Select Deployment Method

#### Deploy from an existing Docker image

1. Select "Deploy from existing image" as the deployment method.
2. Provide the address of the image in a remote container registry.
3. Optionally specify an image pull secret if the registry requires authentication.

#### Deploy from source code (Shipwright Build)

1. Select "Build from source" as the deployment method.
2. In "Tool Source Repository URL", enter the root of your GitHub repository.
3. In "Git Branch or Tag", specify the branch or tag (default: `main`).
4. Under "Select Protocol", choose the MCP transport protocol:
   - `streamable_http` - HTTP-based streaming (recommended)
   - `stdio` - Standard I/O based communication
5. Under "Specify Source Subfolder", type the path to your tool code within the repository.

### Step 5: Configure Build Options (Source Builds Only)

When building from source, Kagenti uses [Shipwright](https://shipwright.io) to build container images.

#### Build Strategy

The build strategy is automatically selected based on your target registry:

| Registry Type | Strategy | Description |
|--------------|----------|-------------|
| Internal (Kind cluster) | `buildah-insecure-push` | For registries without TLS |
| External (quay.io, ghcr.io, docker.io) | `buildah` | For registries with TLS |

You can override the strategy in the "Build Configuration" section if needed.

#### Registry Configuration

- **Registry URL**: Where to push the built image (e.g., `registry.cr-system.svc.cluster.local:5000` for internal, `quay.io/myorg` for external)
- **Registry Secret**: Name of the Kubernetes Secret containing registry credentials (required for external registries)
- **Image Tag**: Version tag for the image (default: `v0.0.1`)

#### Advanced Build Options

Expand "Advanced Build Options" to configure:
- **Dockerfile path** - Default is `Dockerfile` in the context directory
- **Build timeout** - Default is 15 minutes
- **Build arguments** - Optional build-time variables (KEY=VALUE format)

### Step 6: Build and Deploy

Press the "Build & Deploy New Tool" button. 

For source builds, you will be redirected to a **Build Progress** page that shows:
- Build phase (Pending → Running → Succeeded/Failed)
- Build duration and timing
- Source configuration details
- Tool configuration that will be applied

Once the build succeeds, Kagenti automatically:
1. Creates the MCPServer CR with the built image
2. Creates an HTTPRoute for gateway access (if enabled)
3. Redirects you to the Tool detail page

For image deployments, the MCPServer is created immediately.

## Verifying the Deployment

To verify that your tool is running:

1. Open a terminal and connect to your Kubernetes cluster.
2. Check the status of the tool pods:

   ```bash
   kubectl get pods -n <namespace> -l kagenti.io/type=tool
   ```

3. Check the MCPServer status:

   ```bash
   kubectl get mcpservers -n <namespace>
   ```

4. Tail the logs to ensure the service has started:

   ```bash
   kubectl logs -f deployment/<tool-name> -n <namespace>
   ```

## Troubleshooting

### Build Issues (Source Builds)

When building from source, Kagenti creates Shipwright resources:

```bash
# Check Shipwright Build status
kubectl get builds -n <namespace>
kubectl describe build <tool-name> -n <namespace>

# Check BuildRun status and logs
kubectl get buildruns -n <namespace>
kubectl describe buildrun -l kagenti.io/build-name=<tool-name> -n <namespace>

# View build pod logs
kubectl logs -n <namespace> -l build.shipwright.io/name=<tool-name>
```

Common build issues:

| Issue | Solution |
|-------|----------|
| **Registry authentication** | Ensure registry secrets are configured correctly |
| **Dockerfile not found** | Check the Dockerfile path matches your repository structure |
| **Build timeout** | Increase timeout in Advanced Build Options for large images |
| **Git clone failed** | Verify GitHub credentials and repository access |

### Deployment Issues

```bash
# Check MCPServer status
kubectl get mcpservers -n <namespace>
kubectl describe mcpserver <tool-name> -n <namespace>

# Check pod status and logs
kubectl get pods -n <namespace> -l app=<tool-name>
kubectl logs -n <namespace> -l app=<tool-name>
```

### Gateway Registration Issues

If your tool is not accessible through the MCP Gateway:

```bash
# Check HTTPRoute status
kubectl get httproutes -n <namespace>

# Verify gateway configuration
kubectl get gateways -n gateway-system
```

## Using Tools with Agents

Once deployed, tools can be used by agents through direct connection or via the MCP Gateway. Agents invoke tools using the MCP protocol.

### Configuring MCP_URL / MCP_URLS

Agents connect to tools using environment variables:
- `MCP_URL` (singular) - For agents that use a single tool or connect via the MCP Gateway
- `MCP_URLS` (plural) - For agents that connect directly to multiple tools (comma-separated list)

The example agents in the [agent-examples repository](https://github.com/kagenti/agent-examples) include `.env.openai` or `.env.ollama` files with default values that assume the tool is deployed in the **same namespace** as the agent.

#### Same Namespace (Default)

If you deploy the agent and tool(s) in the same namespace, the default `.env` file provided with the agent works as-is. The URL format uses the service name directly:

**Single tool:**
```
MCP_URL=http://weather-tool:8000/mcp
```

**Multiple tools:**
```
MCP_URLS=http://movie-tool:8000/mcp, http://flight-tool:8000/mcp
```

No changes are required in this case.

#### Different Namespaces

If the agent and tool(s) are deployed in **different namespaces**, you must update the environment variable from the default value. You have several options:

**Option 1: Use a namespace-qualified service name**

After importing the agent, edit the environment variable to use the fully qualified service name that includes the namespace:

**Single tool:**
```
MCP_URL=http://<tool-name>.<tool-namespace>.svc.cluster.local:8000/mcp
```

For example, if your tool is named `weather-tool` and deployed in the `tools` namespace:

```
MCP_URL=http://weather-tool.tools.svc.cluster.local:8000/mcp
```

**Multiple tools:**
```
MCP_URLS=http://movie-tool.tools.svc.cluster.local:8000/mcp, http://flight-tool.tools.svc.cluster.local:8000/mcp
```

**Option 2: Copy the namespace-qualified URL from the Tool Detail Page**

1. Navigate to the Tool Catalog in the Kagenti UI
2. Click on your tool to open its detail page
3. Copy the MCP server URL displayed on the page (which includes the namespace)
4. Update your agent's `MCP_URL` (or `MCP_URLS` for multiple tools) environment variable with this value

**Option 3: Use the MCP Gateway (no namespace qualification needed)**

Register your tool(s) with the MCP Gateway and configure the agent to use the gateway URL instead:

```
MCP_URL=http://mcp-gateway-istio.gateway-system.svc.cluster.local:8080/mcp
```

This approach allows agents to access multiple tools through a single endpoint, eliminating the need for namespace qualification or the `MCP_URLS` variable. For details on registering tools with the gateway, see the [MCP Gateway documentation](./gateway.md).

## Related Documentation

- [Importing a New Agent](./new-agent.md)
- [MCP Gateway Instructions](./gateway.md)
- [Components Overview](./components.md)
- [Demo: Weather Agent and Tool](./demos/demo-weather-agent.md)
