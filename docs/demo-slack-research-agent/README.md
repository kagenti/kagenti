# Authorized Slack Research Agent Demo

### NOTE: This demo is currently under ACTIVE development! 

-----
This document provides detailed steps for running the **Slack Research Agent** proof-of-concept (PoC) demo.

In this demo, we will use the Kagenti UI to import and deploy both the **Slack Research Agent** and the **Slack Tool**.  
During deployment, we'll configure the **A2A protocol** for managing agent calls and **MCP** for enabling communication between the agent and the Slack tool.

Once deployed, we will query the agent using a natural language prompt. The agent will then invoke the tool and return the Slack data as a response.

This demo illustrates how Kagenti manages the lifecycle of all required components: agents, tools, protocols, and runtime infrastructure.

Here's a breakdown of the sections:

- In [**Import New Agent**](#import-new-agent), you'll build and deploy the [`a2a_slack_researcher`](https://github.com/kagenti/agent-examples/tree/main/a2a/slack_researcher) agent.
- In [**Import New Tool**](#import-new-tool), you'll build and deploy the [`slack_tool`](https://github.com/kagenti/agent-examples/tree/main/mcp/slack_tool) tool.
- In [**Validate the Deployment**](#validate-the-deployment), you'll verify that all components are running and operational.
- In [**Chat with the Agent**](#chat-with-the-agent), you'll interact with the agent and confirm it responds correctly using real-time Slack data.

> **Prerequisites:**  
> Ensure you've completed the Kagenti platform setup as described in the [Installation](./demos.md#installation) section. This demo uses `SLACK_BOT_TOKEN` so please include this. 

> **Note:**
> This demo has been tested skipping the install of mcp-gateway:
> `uv run kagenti-installer --skip-install mcp_gateway`

You should also open the Agent Platform Demo Dashboard as instructed in the [Connect to the Kagenti UI](./demos.md#connect-to-the-kagenti-ui) section.

---

## Import New Agent

To deploy the Slack Research Agent:

1. Navigate to [Import New Agent](http://kagenti-ui.localtest.me:8080/Import_New_Agent#import-new-agent) in the Kagenti UI.
2. In the **Select Namespace to Deploy Agent** drop-down, choose the `<namespace>` where you'd like to deploy the agent. (These namespaces are defined in your `.env` file.)
3. Under [**Select Environment Variable Sets**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#select-environment-variable-sets), select:
  * `mcp-slack`
  * `slack-researcher-config`
  * `slack-researcher-auth-config`
  * `ollama` or `openai`
    * If using `ollama`, note that it uses `granite3.3:8b` so you may need to `ollama pull granite3.3:8b` locally
    * If using `openai`, you will need to specify a different `TASK_MODEL_ID`, and can do so in the `Custom Environment Variables` section. This demo has been tested with `openai` environment with `TASK_MODEL_ID=gpt-4o-mini-2024-07-18`
4. In the **Agent Source Repository URL** field, use the default:
   <https://github.com/kagenti/agent-examples>
   Or use a custom repository accessible using the GitHub ID specified in your `.env` file.
5. For **Git Branch or Tag**, use the default `main` branch (or select another as needed).
6. Set **Protocol** to `a2a`.
7. Under [**Specify Source Subfolder**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#specify-source-subfolder):
   - Click `Select from examples`
   - Choose: `a2a/slack_researcher`
8. Click **Build New Agent** to deploy.

---

## Import New Tool

To deploy the Slack Tool:

1. Navigate to [Import New Tool](http://kagenti-ui.localtest.me:8080/Import_New_Tool#import-new-tool) in the UI.
2. Select the same `<namespace>` as used for the agent.
3. In the **Select Environment Variable Sets** section, select:
   - `mcp-slack-config`
   - `mcp-slack-auth-config`
4. Use the same source repository:
   <https://github.com/kagenti/agent-examples>
5. Choose the `main` branch or your preferred branch.
6. Set **Select Protocol** to `streamable-http`.
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
   installer$ kubectl get pods -n <namespace>
   NAME                                  READY   STATUS    RESTARTS   AGE
   slack-researcher-8bb4644fc-4d65d   1/1     Running   0          1m
   slack-tool-5bb675dd7c-ccmlp         1/1     Running   0          1m
   ```

3. Tail the logs to ensure both services have started successfully.
   For the agent:

   ```console
    installer$ kubectl logs -f deployment/slack-researcher -n <namespace>
    Defaulted container "slack-researcher" out of: slack-researcher, kagenti-client-registration (init)
    INFO:     Started server process [18]
    INFO:     Waiting for application startup.
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
    ```

    For the tool:
    ```console
    installer$ kubectl logs -f deployment/slack-tool -n <namespace>
    Defaulted container "slack-tool" out of: slack-tool, kagenti-client-registration (init)
    INFO:     Started server process [19]
    INFO:     Waiting for application startup.
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
    ```

4. Once you see the logs indicating that both services are up and running, you're ready to proceed to [Chat with the Agent](#chat-with-the-agent).

---

## Configure Keycloak

Now that the agent and tool have been deployed, the Keycloak Administrator must configure the policies to give the UI delegated access to the tool. We have automated these steps in a script. Simply run:

```
<insert command to run keycloak automation>
```

---

## Chat with the Agent

Once the deployment is complete, you can run the demo:

1. Navigate to the **Agent Catalog** in the Kagenti UI.
2. Select the same `<namespace>` used during the agent deployment.
3. Under [**Available Agents in <namespace>**](http://kagenti-ui.localtest.me:8080/Agent_Catalog#available-agents-in-kagenti-system), select `slack-researcher` and click **View Details**.
4. Scroll to the bottom of the page. In the input field labeled *Say something to the agent...*, enter:

   ```console
   What are the channels in the Slack? 
   ```

5. You will see the *Agent Thinking...* message and a series of `Task Status Update`. Depending on the speed of your hosting environment, the agent will return a Slack response. For example:

   ```console
    The bot has access to two channels:
        1. general: This channel is for team-wide announcements and conversations. Everyone is included here.
        2. random: This channel is for everything else, including team jokes, spur-of-the-moment ideas, and funny GIFs.
    Please let me know if you need more information about a specific channel.
   ```

6. You can tail the log files (as shown in the [Validate the Deployment section](#validate-the-deployment)) to observe the interaction between the agent and the tool in real time.

If you encounter any errors, check the [Troubleshooting section](./demos.md#troubleshooting).

## Cleanup

### Delete the Agent and the Tool

You may navigate to the **Agent Catalog** and **Tool Catalog** in the UI and delete the agent and tool respectively. Else, you may do this in the console:

```console
   installer$ kubectl delete components.kagenti.operator.dev slack-researcher slack-tool -n <namespace>
```

The Kagenti Operator will automatically clean up all related Kubernetes resources.

