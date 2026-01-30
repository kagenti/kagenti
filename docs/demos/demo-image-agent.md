# Image Agent Demo

This document provides detailed steps for running the **Image Agent** proof-of-concept (PoC) demo.

In this demo, we will use the Kagenti UI to import and deploy both the **Image Service Agent** and the **Image Tool**.
During deployment, we'll configure the **A2A protocol** for managing agent calls and **MCP** for enabling communication between the agent and the image tool.

Once deployed, we will query the agent using a natural language prompt. The agent will then invoke the tool and return the image data as a response.

This demo illustrates how Kagenti manages the lifecycle of all required components: agents, tools, protocols, and runtime infrastructure.

Here's a breakdown of the sections:
- In [**Set Up**](#set-up), you'll run a script to rebuild and roll out the UI image 
- In [**Import New Agent**](#import-new-agent), you'll build and deploy the [`image_service`](https://github.com/kagenti/agent-examples/tree/main/a2a/image_service) agent.
- In [**Import New Tool**](#import-new-tool), you'll build and deploy the [`image_tool`](https://github.com/kagenti/agent-examples/tree/main/mcp/image_tool) tool.
- In [**Validate the Deployment**](#validate-the-deployment), you'll verify that all components are running and operational.
- In [**Chat with the Image Agent**](#chat-with-the-image-agent), you'll interact with the agent and confirm it responds correctly with randomly generated images.

> **Prerequisites:**
> Ensure you've completed the Kagenti platform setup as described in the [Installation](./demos.md#installation) section.

You should also open the Agent Platform Demo Dashboard as instructed in the [Connect to the Kagenti UI](./demos.md#connect-to-the-kagenti-ui) section.

---

## Import New Agent

To deploy the Image Agent:

1. Navigate to [Import New Agent](http://kagenti-ui.localtest.me:8080/Import_New_Agent#import-new-agent) in the Kagenti UI.
2. In the **Select Namespace to Deploy Agent** drop-down, choose the `<namespace>` where you'd like to deploy the agent. (These namespaces are defined in your `.env` file.)
3. Under [**Select Environment Variable Sets**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#select-environment-variable-sets), select:
   - `mcp-image`
   - `ollama` or `openai`
4. In the **Agent Source Repository URL** field, use the default:
   <https://github.com/kagenti/agent-examples>
   Or use a custom repository accessible using the GitHub ID specified in your `.env` file.
5. For **Git Branch or Tag**, use the default `main` branch (or select another as needed).
6. Set **Protocol** to `a2a`.
7. Under [**Specify Source Subfolder**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#specify-source-subfolder):
   - Click `Select from examples`
   - Choose: `a2a/image_service`
8. Click **Build & Deploy New Agent** to deploy.

**Note:** The `ollama` environmental variable set specifies `llama3.2:3b-instruct-fp16` as the default model. To download the model, run `ollama pull llama3.2:3b-instruct-fp16`. Please ensure an Ollama server is running in a separate terminal via `ollama serve`. 

---

## Import New Tool

To deploy the Image Tool using Shipwright:

1. Navigate to [Import New Tool](http://kagenti-ui.localtest.me:8080/Import_New_Tool#import-new-tool) in the UI.
1. Select the same `<namespace>` as used for the agent.
1. Select "Build from source" as the deployment method.
1. Use the same source repository:
   <https://github.com/kagenti/agent-examples>
1. Choose the `main` branch or your preferred branch.
1. Set **Select Protocol** to `streamable_http`.
1. Under **Specify Source Subfolder**:
   - Select: `mcp/image_tool`
1. Click **Build & Deploy New Tool** to deploy.

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
   image-service-8bb4644fc-4d65d       1/1     Running   0          1m
   image-tool-5bb675dd7c-ccmlp         1/1     Running   0          1m
   ```

3. Tail the logs to ensure both services have started successfully.
   For the agent:

   ```console
   installer$ kubectl logs -f deployment/image-service -n <your-ns>
   Defaulted container "image-service" out of: image-service, kagenti-client-registration (init)
   INFO:     Started server process [18]
   INFO:     Waiting for application startup.
   INFO:     Application startup complete.
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   ```

   For the tool:
   ```console
   installer$ kubectl logs -f deployment/image-tool -n <your-ns>
   Defaulted container "image-tool" out of: image-tool, kagenti-client-registration (init)
   INFO:     Started server process [19]
   INFO:     Waiting for application startup.
   INFO:     Application startup complete.
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   ```

4. Once you see the logs indicating that both services are up and running, you're ready to proceed to [Chat with the Image Agent](#chat-with-the-image-agent).

---

## Chat with the Image Agent

Once the deployment is complete, you can run the demo:

1. Navigate to the **Agent Catalog** in the Kagenti UI.
2. Select the same `<namespace>` used during the agent deployment.
3. Under [**Available Agents in <namespace>**](http://kagenti-ui.localtest.me:8080/Agent_Catalog#available-agents-in-kagenti-system), select `image-service` and click **View Details**.
4. Scroll to the bottom of the page. In the input field labeled *Say something to the agent...*, enter:

   ```console
   Give me a 200x200 image
   ```

5. You will see the *Agent Thinking...* message. Depending on the speed of your hosting environment, the agent will return a image response. 

6. You can tail the log files (as shown in the [Validate the Deployment section](#validate-the-deployment)) to observe the interaction between the agent and the tool in real time.

If you encounter any errors, check the [Troubleshooting section](./demos.md#troubleshooting).

## Cleanup

To cleanup the agents and tools in the UI, go to the `Agent Catalog` and `Tool Catalog`
respectively and click the `Delete` button next to each.

You can also manually remove them by deleting their Custom Resources (CRs) from the cluster.

### Step 1: List Custom Resource Definitions (CRDs)

   ```console
   installer$ kubectl get crds | grep kagenti
   components.kagenti.operator.dev             2025-07-23T23:11:59Z
   platforms.kagenti.operator.dev              2025-07-23T23:11:59Z
   ```

### Step 2: List deployed components in your namespace

   ```console
   installer$ kubectl get components.kagenti.operator.dev -n <your-ns>
   NAME                  SUSPEND
   image-service       false
   image-tool          false
   ```

### Step 3: Delete the Agent and the Tool

   ```console
   installer$ kubectl delete components.kagenti.operator.dev image-service image-tool -n <your-ns>
   ```

The Kagenti Operator will automatically clean up all related Kubernetes resources.
