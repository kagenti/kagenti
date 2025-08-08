# Slack Research Agent Demo

### NOTE: This demo is currently under ACTIVE development! 

Todos:
 - create a2a agent example and add pointers/flavor text
   - probably remove all references to acp in favor of a2a
   - remove all references to weather
 - add documentation to get slack bot token

-----
This document provides detailed steps for running the **Slack Research Agent** proof-of-concept (PoC) demo.

In this demo, we will use the Kagenti UI to import and deploy both the **Slack Research Agent** and the **Slack Tool**.  
During deployment, we'll configure the **A2A protocol** for managing agent calls and **MCP** for enabling communication between the agent and the slack tool.

Once deployed, we will query the agent using a natural language prompt. The agent will then invoke the tool and return the slack data as a response.

This demo illustrates how Kagenti manages the lifecycle of all required components: agents, tools, protocols, and runtime infrastructure.

Here's a breakdown of the sections:

- In [**Import New Agent**](#import-new-agent), you'll build and deploy the [`acp_weather_service`](https://github.com/kagenti/agent-examples/tree/main/acp/acp_weather_service) agent.
- In [**Import New Tool**](#import-new-tool), you'll build and deploy the [`slack_tool`](https://github.com/kagenti/agent-examples/tree/main/mcp/slack_tool) tool.
- In [**Validate the Deployment**](#validate-the-deployment), you'll verify that all components are running and operational.
- In [**Run the Weather Agent Demo**](#run-the-weather-agent-demo), you'll interact with the agent and confirm it responds correctly using real-time slack data.

> **Prerequisites:**  
> Ensure you've completed the Kagenti platform setup as described in the [Installation](../demos.md#installation) section. This demo uses `SLACK_BOT_TOKEN` so please include this. 

You should also open the Agent Platform Demo Dashboard as instructed in the [Connect to the Kagenti UI](../demos.md#connect-to-the-kagenti-ui) section.

---

## Import New Agent

To deploy the Weather Agent:

1. Navigate to [Import New Agent](http://kagenti-ui.localtest.me:8080/Import_New_Agent#import-new-agent) in the Kagenti UI.
2. In the **Select Namespace to Deploy Agent** drop-down, choose the `<namespace>` where you'd like to deploy the agent. (These namespaces are defined in your `.env` file.)
3. Under [**Select Environment Variable Sets**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#select-environment-variable-sets), select:
   - `mcp-slack`
   - `ollama`
4. In the **Agent Source Repository URL** field, use the default:
   <https://github.com/kagenti/agent-examples>
   Or use a custom repository accessible using the GitHub ID specified in your `.env` file.
5. For **Git Branch or Tag**, use the default `main` branch (or select another as needed).
6. Set **Protocol** to `acp`.
7. Under [**Specify Source Subfolder**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#specify-source-subfolder):
   - Click `Select from examples`
   - Choose: `acp/acp_weather_service`
8. Click **Build New Agent** to deploy.

---

## Import New Tool

To deploy the slack Tool:

1. Navigate to [Import New Tool](http://kagenti-ui.localtest.me:8080/Import_New_Tool#import-new-tool) in the UI.
2. Select the same `<namespace>` as used for the agent.
3. In the **Select Environment Variable Sets** section, select:
   - `mcp-slack-config`
4. Use the same source repository:
   <https://github.com/kagenti/agent-examples>
5. Choose the `main` branch or your preferred branch.
6. Set **Select Protocol** to `MCP`.
7. Under **Specify Source Subfolder**:
   - Select: `mcp/slack_tool`
8. Click **Build New Tool** to deploy.

---

## Validate The Deployment

Depending on your hosting environment, it may take some time for the agent and tool deployments to complete.

To verify that both the agent and tool are running:

1. Open a terminal and connect to your Kubernetes cluster.
2. Use the namespace you selected during deployment to check the status of the pods:

   ```console
   installer$ kubectl -n <namespace> get po
   NAME                                  READY   STATUS    RESTARTS   AGE
   acp-weather-service-8bb4644fc-4d65d   1/1     Running   0          1m
   slack-tool-5bb675dd7c-ccmlp         1/1     Running   0          1m
   ```

3. Tail the logs to ensure both services have started successfully.
   For the agent:

   ```console
    installer$ kubectl -n <namespace> logs -f acp-weather-service-8bb4644fc-4d65d
    Defaulted container "acp-weather-service" out of: acp-weather-service, kagenti-client-registration (init)
    INFO:     Started server process [18]
    INFO:     Waiting for application startup.
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
    ```

    For the tool:
    ```console
    installer$ kubectl -n <namespace> logs -f slack-tool-5bb675dd7c-ccmlp
    Defaulted container "slack-tool" out of: slack-tool, kagenti-client-registration (init)
    INFO:     Started server process [19]
    INFO:     Waiting for application startup.
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
    ```

4. Once you see the logs indicating that both services are up and running, you're ready to proceed to [Chat with the Agent](#chat-with-the-agent).

---

## Chat with the Agent

Once the deployment is complete, you can run the demo:

1. Navigate to the **Agent Catalog** in the Kagenti UI.
2. Select the same `<namespace>` used during the agent deployment.
3. Under [**Available Agents in <namespace>**](http://kagenti-ui.localtest.me:8080/Agent_Catalog#available-agents-in-kagenti-system), select `acp-weather-service` and click **View Details**.
4. Scroll to the bottom of the page. In the input field labeled *Say something to the agent...*, enter:

   ```console
   What are the channels in the slack? 
   ```

5. You will see the *Agent Thinking...* message. Depending on the speed of your hosting environment, the agent will return a slack response. For example:

   ```console
     The current weather in NY is mostly sunny with a temperature of 22.6 degrees Celsius (73.07 degrees Fahrenheit). There is a gentle breeze blowing at 6.8 km/h (4.2 mph) from the northwest. It's currently daytime, and the weather code indicates fair weather with no precipitation.
    ```

6. You can tail the log files (as shown in the [Validate the Deployment section](#validate-the-deployment)) to observe the interaction between the agent and the tool in real time.

If you encounter any errors, check the [Troubleshooting section](./demos.md#troubleshooting).

## Cleanup

Currently, the Kagenti UI does not provide built-in cleanup capabilities for agents or tools.
However, you can manually remove them by deleting their Custom Resources (CRs) from the cluster.

### Step 1: List Custom Resource Definitions (CRDs)

```console
    installer$ kubectl get crds | grep kagenti
    components.kagenti.operator.dev             2025-07-23T23:11:59Z
    platforms.kagenti.operator.dev              2025-07-23T23:11:59Z
```

### Step 2: List deployed components in your namespace

```console
    installer$ kubectl get components.kagenti.operator.dev -n <namespace>
    NAME                  SUSPEND
    acp-weather-service   false
    slack-tool          false
```

### Step 3: Delete the Agent and the Tool

```console
   installer$ kubectl delete components.kagenti.operator.dev acp-weather-service slack-tool -n <namespace>
```

The Kagenti Operator will automatically clean up all related Kubernetes resources.
