# Weather Agent Demo

This document provides detailed steps for running the **Weather Agent** proof-of-concept (PoC) demo.

In this demo, we will use the Kagenti UI to import and deploy both the **Weather Service Agent** and the **Weather Service Tool**.
During deployment, we'll configure the **A2A protocol** for managing agent calls and **MCP** for enabling communication between the agent and the weather tool.

Once deployed, we will query the agent using a natural language prompt. The agent will then invoke the tool and return the weather data as a response.

This demo illustrates how Kagenti manages the lifecycle of all required components: agents, tools, protocols, and runtime infrastructure.

Here's a breakdown of the sections:

- In [**Import New Agent**](#import-new-agent), you'll build and deploy the [`weather_service`](https://github.com/kagenti/agent-examples/tree/main/a2a/weather_service) agent.
- In [**Import New Tool**](#import-new-tool), you'll build and deploy the [`weather_tool`](https://github.com/kagenti/agent-examples/tree/main/mcp/weather_tool) tool.
- In [**Validate the Deployment**](#validate-the-deployment), you'll verify that all components are running and operational.
- In [**Chat with the Weather Agent**](#chat-with-the-weather-agent), you'll interact with the agent and confirm it responds correctly using real-time weather data.

> **Prerequisites:**
> Ensure you've completed the Kagenti platform setup as described in the [Installation Guide](../install.md).

You should also open the Agent Platform Demo Dashboard as instructed in the [Accessing the UI](../install.md#accessing-the-ui) section.

> **🎭 User Roles**: This demo involves multiple personas including **Agent Developers**, **Tool Developers**, **Security Specialists**, and **End Users**. See our [Personas Documentation](../../PERSONAS_AND_ROLES.md#overview) to understand which parts are relevant to your role.

---

## Import New Agent

To deploy the Weather Agent:

1. Click on [Import New Agent](http://kagenti-ui.localtest.me:8080/agents/import) in the Kagenti UI.
1. In the **Agent Configuration** section's **Namespace** drop-down, choose the `<namespace>` where you'd like to deploy the agent. (These namespaces can be defined or overwritten in [value files](https://github.com/kagenti/kagenti/tree/main/deployments/ansible#how-variables-and-value-files-are-resolved).)
1. Provide a new **Agent Name** if wanted, or this will get populated later automatically as `weather-service`.
1. Keep the **Deployment Method** as **Build from Source** to deploy from a source repository.
1. In the **Source Repository** section's **Git Repository URL** field, use the default:
   <https://github.com/kagenti/agent-examples>.
   Or use a custom repository accessible using the GitHub ID specified in your `.secret_values` file.
1. For **Git Branch**, use the default `main` branch (or select another as needed).
1. For **Select Example**, choose `Weather Service Agent`. The **Source Path** will populate as `a2a/weather_service` (or provide another path).
1. Keep the **Container Registry Configuration** section's **Container Registry** and **Override Start Command** as default.
1. Expand the **Environment Variables** dropdown and click **Import from File/URL** to add environment variables including agent LLM information. Use the default `https://raw.githubusercontent.com/kagenti/agent-examples/refs/heads/main/a2a/weather_service/.env.openai` URL or select another file or URL, then click **Fetch & Parse**. Make sure the LLM variables are for a model accessible to you. Variables can be updated in the UI as wanted.
1. Click **Build & Deploy New Agent** to deploy.

**Note:** To use `ollama`:
- update the `LLM_API_BASE` to `http://host.docker.internal:11434/v1` (or wherever the model is being served.)
- update `LLM_MODEL` to `gpt-oss:latest` (or your preferred model that ollama supports)
- To download an `ollama` model, run `ollama pull <model-name>`. Please ensure an Ollama server is running in a separate terminal via `ollama serve`.

---

## Import New Tool

To deploy the Weather Tool using Shipwright:

1. Navigate to [Import New Tool](http://kagenti-ui.localtest.me:8080/tools/import) in the UI.
1. Select the same `<namespace>` as used for the agent for the **Namespace** under **Tool Configuration**.
1. Provide a new **Tool Name** if wanted, or this will get populated later automatically as `weather-tool`.
1. Keep the **Deployment Method** as **Deploy From Image** to deploy from an image. It can also be switched to **Build from Source** to build, where an example `Weather Tool` can be chosen.
1. For **Container Image**, use `ghcr.io/kagenti/agent-examples/weather_tool` or any other full image path with the weather tool. These examples are available [here on the Github Container Registry](https://github.com/kagenti/agent-examples/pkgs/container/agent-examples%2Fweather_tool).
1. Pick a corresponding tag under **Image Tag** or keep the default `latest`.
1. Keep the **MCP Transport Portocol** as "Streamable HTTP".
1. Click **Deploy New Tool** to deploy.

You will be redirected to a **Build Progress** page where you can monitor the Shipwright build. Once the build succeeds, the Deployment and Service for the tool will be created automatically.

---

## Validate The Deployment

Depending on your hosting environment, it may take some time for the agent and tool deployments to complete.

To verify that both the agent and tool are running:

1. Open a terminal and connect to your Kubernetes cluster.
2. Use the namespace you selected during deployment to check the status of the pods:

   ```console
   installer$ kubectl get po -n <your-ns>
   NAME                                  READY   STATUS    RESTARTS   AGE
   weather-service-8bb4644fc-4d65d       3/3     Running   0          1m
   weather-tool-0                        3/3     Running   0          1m
   weather-tool-5bb675dd7c-ccmlp         1/1     Running   0          1m
   ```

3. Tail the logs to ensure both services have started successfully.
   For the agent:

   ```console
   installer$ kubectl logs -f deployment/weather-service -n <your-ns>
   Defaulted container "agent" out of: agent, spiffe-helper, kagenti-client-registration
   INFO:     Started server process [17]
   INFO:     Waiting for application startup.
   INFO:     Application startup complete.
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   ```

   For the tool:
   ```console
   installer$ kubectl logs -f deployment/weather-tool -n <your-ns>
   ...
   {"level":"info","ts":1769024819.3249917,"caller":"logger/logger.go:39","msg":"Server was initialized successfully for http://mcp-weather-tool-headless:8000"}
   {"level":"info","ts":1769024819.3251433,"caller":"logger/logger.go:39","msg":"MCP server is ready after 3.122989251s (attempt 6)"}
   ...
   {"level":"info","ts":1769024819.3265529,"caller":"logger/logger.go:34","msg":"Press Ctrl+C to stop or wait for container to exit"}
   ```

4. Once you see the logs indicating that both services are up and running, you're ready to proceed to [Chat with the Weather Agent](#chat-with-the-weather-agent).

---

## Chat with the Weather Agent

Once the deployment is complete, you can run the demo:

1. Navigate to the **Agent Catalog** in the Kagenti UI by clicking on **Agents** on the left sidebar.
1. Select the agent name chosen earlier (`weather-service` by default).
1. Click on the **Chat** tab. You can see agent details under the **Agent Details** dropdown.
1. Scroll to the bottom of the page. In the input field labeled *Type your message...*, enter:

   ```console
   What is the weather in NY?
   ```

1. You will see *Events* flowing and a *Processing...* message. Depending on the speed of your hosting environment, the agent will return a weather response. For example:

   ```console
   The current weather in NY is mostly sunny with a temperature of 22.6 degrees Celsius (73.07 degrees Fahrenheit). There is a gentle breeze blowing at 6.8 km/h (4.2 mph) from the northwest. It's currently daytime, and the weather code indicates fair weather with no precipitation.
   ```

1. You can tail the log files (as shown in the [Validate the Deployment section](#validate-the-deployment)) to observe the interaction between the agent and the tool in real time.

If you encounter any errors, check the [Troubleshooting Guide](../troubleshooting.md).

## Cleanup

To cleanup the agents and tools in the UI, go to the `Agent Catalog` and `Tool Catalog` respectively. These are accessible via "Agents" and "Tools" on the left sidebar. Click on each agent or tool you want to delete. On the right side there is an `Action` dropdown that will show `Delete agent` or `Delete tool`. Confirmation will be required to ensure deletion is intentional.

You can also manually remove them by deleting their Custom Resources (CRs) from the cluster. The Kagenti Operator will automatically clean up all related Kubernetes resources.

<!---
Once CRDs are finalized as part of https://github.com/kagenti/kagenti/issues/523,
instructions for manual removal can be updated here.
-->
