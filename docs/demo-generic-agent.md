# Generic Agent Demo (with Movie Tool and Flight Tool)

This document provides detailed steps for running the **Generic Agent** proof-of-concept (PoC) demo.

In this demo, we will use the Kagenti UI to import and deploy the **Generic Agent**, the **Movie Tool**, and the **Flight Tool**.
During deployment, we'll configure the **A2A protocol** for managing agent calls and **MCP** for enabling communication between the agent and tools.

Once deployed, we will query the agent using a natural language prompt. The agent will then invoke the tool and return movie or flight data as a response.

This demo illustrates how Kagenti manages the lifecycle of all required components: agents, tools, protocols, and runtime infrastructure.

Here's a breakdown of the sections:

- In [**Import New Agent**](#import-new-agent), you'll build and deploy the [`generic_agent`](https://github.com/kagenti/agent-examples/tree/main/a2a/generic_agent) agent.
- In [**Import New Tool**](#import-new-tool), you'll build and deploy [`flight_tool`](https://github.com/kagenti/agent-examples/tree/main/mcp/flight_tool) tool and [`movie_tool`](https://github.com/kagenti/agent-examples/tree/main/mcp/movie_tool) tool.
- In [**Validate the Deployment**](#validate-the-deployment), you'll verify that all components are running and operational.
- In [**Chat with the Generic Agent**](#chat-with-the-generic-agent), you'll interact with the agent and confirm it responds correctly using movie and flight data.

> **Prerequisites:**
> Ensure you've completed the Kagenti platform setup as described in the [Installation](./demos.md#installation) section.

You should also open the Agent Platform Demo Dashboard as instructed in the [Connect to the Kagenti UI](./demos.md#connect-to-the-kagenti-ui) section.

---

## Import New Agent

To deploy the Generic Agent:

1. Navigate to [Import New Agent](http://kagenti-ui.localtest.me:8080/Import_New_Agent#import-new-agent) in the Kagenti UI.
2. In the **Select Namespace to Deploy Agent** drop-down, choose the `<namespace>` where you'd like to deploy the agent. (These namespaces are defined in your `.env` file.)
3. Under [**Select Environment Variable Sets**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#select-environment-variable-sets):
   - `ollama` or `openai`
4. Under [**Environment Variable**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#select-environment-variable-sets), select:
   - Click `Add Environment Variable`
   - Under `Name` put `MCP_URLS` and under `Value` put `http://movie-tool:8000/mcp, http://flight-tool:8000/mcp`
5. In the **Agent Source Repository URL** field, use the default:
   <https://github.com/kagenti/agent-examples>
   Or use a custom repository accessible using the GitHub ID specified in your `.env` file.
6. For **Git Branch or Tag**, use the default `main` branch (or select another as needed).
7. Set **Protocol** to `a2a`.
8. Under [**Specify Source Subfolder**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#specify-source-subfolder):
   - Click `Select from examples`
   - Choose: `a2a/geneic_agent`
9. Click **Build & Deploy New Agent** to deploy.

**Note:** The `ollama` environmental variable set specifies `llama3.2:3b-instruct-fp16` as the default model. To download the model, run `ollama pull llama3.2:3b-instruct-fp16`. Please ensure an Ollama server is running in a separate terminal via `ollama serve`. 

---

## Import New Tool

To deploy the Movie Tool:

1. Go to [OMDB's website](https://www.omdbapi.com/) and apply for a free API key
1. Navigate to [Import New Tool](http://kagenti-ui.localtest.me:8080/Import_New_Tool#import-new-tool) in Kagenti's UI.
1. Select the same `<namespace>` as used for the agent.
1. Under [**Environment Variable**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#select-environment-variable-sets), select:
   - Click `Add Environment Variable`
   - Under `Name` put `OMDB_API_KEY` and under `Value` put your OMDB API key
1. Use the same source repository:
   <https://github.com/kagenti/agent-examples>
1. Choose the `main` branch or your preferred branch.
1. Set **Select Protocol** to `streamable_http`.
1. Under **Specify Source Subfolder**:
   - Select: `mcp/movie_tool`
1. Click **Build & Deploy New Tool** to deploy.

To deploy the Flight Tool:

1. Navigate to [Import New Tool](http://kagenti-ui.localtest.me:8080/Import_New_Tool#import-new-tool) in the UI.
1. Select the same `<namespace>` as used for the agent.
1. Use the same source repository:
   <https://github.com/kagenti/agent-examples>
1. Choose the `main` branch or your preferred branch.
1. Set **Select Protocol** to `streamable_http`.
1. Under **Specify Source Subfolder**:
   - Select: `mcp/flight_tool`
1. Click **Build & Deploy New Tool** to deploy.

---

## Validate The Deployment

Depending on your hosting environment, it may take some time for the agent and tool deployments to complete.

To verify that both the agent and tool are running:

1. Open a terminal and connect to your Kubernetes cluster.
2. Use the namespace you selected during deployment to check the status of the pods:

   ```console
   installer$ kubectl get po -n <your-ns>
   NAME                             READY   STATUS        RESTARTS   AGE
   flight-tool-cb7566fdf-z7j8n      3/3     Running       0          29d
   generic-agent-7cc769d86c-fkwmv   3/3     Running       0          25s
   movie-tool-74dd484b6c-958rv      3/3     Running       0          3m38s
   ```

3. Tail the logs to ensure both services have started successfully.
   For the agent:

   ```console
   installer$ kubectl logs -f deployment/generic-agent -n <your-ns>
   Defaulted container "generic-agent" out of: generic-agent, spiffe-helper, kagenti-client-registration, fix-permissions (init)
   INFO:     Started server process [14]
   INFO:     Waiting for application startup.
   INFO:     Application startup complete.
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)

   ```

   For the movie tool:
   ```console
   installer$ kubectl logs -f deployment/movie-tool -n <your-ns>
   Defaulted container "movie-tool" out of: movie-tool, spiffe-helper, kagenti-client-registration, fix-permissions (init)                        
   INFO:     Started server process [14]
   INFO:     Waiting for application startup.
   INFO: StreamableHTTP session manager started
   INFO:     Application startup complete.
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   ```

   For the flight tool:
   ```console
   installer$ kubectl logs -f deployment/flight-tool -n <your-ns>
   Defaulted container "flight-tool" out of: flight-tool, spiffe-helper, kagenti-client-registration, fix-permissions (init)   INFO:     Started server process [14]
   INFO:     Waiting for application startup.
   INFO: StreamableHTTP session manager started
   INFO:     Application startup complete.
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   ```

4. Once you see the logs indicating that both services are up and running, you're ready to proceed to [Chat with the Generic Agent](#chat-with-the-generic-agent).

---

## Chat with the Generic Agent

Once the deployment is complete, you can run the demo:

1. Navigate to the **Agent Catalog** in the Kagenti UI.
2. Select the same `<namespace>` used during the agent deployment.
3. Under [**Available Agents in <namespace>**](http://kagenti-ui.localtest.me:8080/Agent_Catalog#available-agents-in-kagenti-system), select `generic_agent` and click **View Details**.
4. Scroll to the bottom of the page. In the input field labeled *Say something to the agent...*, enter:

   ```console
   Show me flights for one adult from Taipei to San Francisco on November 22nd, 2025. 
   ```
   Please note, that you will need to use a date that is in the future. 

   To use the movie tool, use a prompt like this:
   ```console
   Tell me the plot of Wicked: For Good
   ```

5. You will see the *Agent Thinking...* message. Depending on the speed of your hosting environment, the agent will return a flight response. For example:

   ```console
   Here is a list of flights from Taipei to San Fancisco on November 22nd, 2025: 
   1. United - Departure: 1:35 PM, Arrival: 7:50 PM
   1. STARLUX Airlines - Departure: 11:10 PM, Arrival: 5:15 AM (next day)
   1. EVA Air - Departure: 12:00 PM, Arrival: 6:00 PM
   ```

   ```console
   Wicked: For Good is the second part of the Wicked movie adaptation, where Elphaba is in exile as the "Wicked Witch of the West" and Glinda is the public figure of "Glinda the Good". The plot follows their estranged friendship as Elphaba fights the Wizard's regime and Glinda becomes the Wizard's spokesperson, creating a final, powerful conflict that forces them to confront their past and make crucial decisions. The story culminates in Elphaba's apparent death by water, a final reconciliation with Glinda, and the resolution of the conflict with the Wizard
   ```

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
   generic-agent         false
   flight-tool           false
   movie-tool           false
   ```

### Step 3: Delete the Agent and the Tool

   ```console
   installer$ kubectl delete components.kagenti.operator.dev generic-agent flight-tool movie-tool -n <your-ns>
   ```

The Kagenti Operator will automatically clean up all related Kubernetes resources.
