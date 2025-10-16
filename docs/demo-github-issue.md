# Github Issue Demo

This document provides detailed steps for running the **Github Issue Agent** proof-of-concept (PoC) demo.

In this demo, we will use the Kagenti UI to import and deploy the **Github Issue Agent**.

During deployment, we'll configure the **A2A protocol** for managing agent calls to the LLM and the publicly accessible Github tool. To access Github, users must provide their [personal Github access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-personal-access-token-classic). Make sure this token allows reading issues from the Github repository.

Once deployed, we will query the agent using a natural language prompt. The agent will then invoke the public Github tool and return the responses related to issues.

This demo illustrates how Kagenti agent can access public tool.

Here's a breakdown of the sections:

- In [**Import New Agent**](#import-new-agent), you'll build and deploy the [`git_issue_agent`](https://github.com/kagenti/agent-examples/tree/main/a2a/git_issue_agent).
- In [**Validate the Deployment**](#validate-the-deployment), you'll verify that all components are running and operational.
- In [**Chat with the Github Issue Agent**](#chat-with-the-github-issue-agent), you'll interact with the agent and confirm it responds correctly using Github issue data from selected repository.

> **Prerequisites:**
> Ensure you've completed the Kagenti platform setup as described in the [Installation](./demos.md#installation) section.

You should also open the Agent Platform Demo Dashboard as instructed in the [Connect to the Kagenti UI](./demos.md#connect-to-the-kagenti-ui) section.

---

## Import New Agent

To deploy the Github Issue Agent:

1. Navigate to [Import New Agent](http://kagenti-ui.localtest.me:8080/Import_New_Agent#import-new-agent) in the Kagenti UI.
1. In the **Select Namespace to Deploy Agent** drop-down, choose the `<namespace>` where you'd like to deploy the agent. (These namespaces are defined in your `.env` file.)
1. Under [**Select Environment Variable Sets**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#select-environment-variable-sets), select:
   - `ollama` or `openai`
1. Next select `Import .env File` button, then provide:
   - Github Repository URL: `https://github.com/kagenti/agent-examples/`
   - Path to .env file: `a2a/git_issue_agent/.env.template`
   - Press "Import", this will populate env. variables for this agent.
1. In the newly created variable `GITHUB_TOKEN`, provide the personal Github access token value, as discussed above.
1. In the **Deployment Method** select `Build from Source` and then in **Agent Source Repository URL** field, use the default:
   <https://github.com/kagenti/agent-examples>
   Or use a custom repository accessible using the GitHub ID specified in your `.env` file.
1. For **Git Branch or Tag**, use the default `main` branch (or select another as needed).
1. In Container Registry Configuration, select the default value then, for **Protocol** set `a2a`.
1. Under [**Specify Source Subfolder**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#specify-source-subfolder):
   - Click `Select from examples`
   - Choose: `a2a/github_issue_agent`
1. Click **Build & Deploy New Agent** to deploy.

**Note:** For the `ollama` environmental make sure to use most up-to-date version and run `ollama pull ibm/granite4:latest`. Please ensure an Ollama server is running in a separate terminal via `ollama serve`.

---

## Validate The Deployment

Depending on your hosting environment, it may take some time for the agent deployment to complete.

To verify that the agent is running:

1. Open a terminal and connect to your Kubernetes cluster.
2. Use the namespace you selected during deployment to check the status of the pods:

   ```console
   installer$ kubectl get po -n <your-ns>
   NAME                                  READY   STATUS    RESTARTS   AGE
   git-issue-agent-58768bdb67-758kc      3/3     Running   0          1m

   ```

3. Tail the log to ensure the service has started successfully.
   For the agent:

   ```console
   installer$ kubectl logs -f deployment/git-issue-agent -c git-issue-agent -n <your-ns>
   DEBUG: Initializing InMemoryTaskStore
   INFO:     Started server process [17]
   INFO:     Waiting for application startup.
   INFO:     Application startup complete.
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   ```

4. Once you see the logs indicating that the service is up and running, you're ready to proceed to [Chat with the Github Issue Agent](#chat-with-the-github-issue-agent).

---

## Chat with the Github Issue Agent

Once the deployment is complete, you can run the demo:

1. Navigate to the **Agent Catalog** in the Kagenti UI.
2. Select the same `<namespace>` used during the agent deployment.
3. Under [**Available Agents in <namespace>**](http://kagenti-ui.localtest.me:8080/Agent_Catalog#available-agents-in-kagenti-system), select `github-issue-agent` and click **View Details**.
4. Scroll to the bottom of the page. In the input field labeled *Say something to the agent...*, enter:

   ```console
   List issues in kagenti/kagenti repo
   ```

5. You will see the *Agent Thinking...* message. Depending on the speed of your hosting environment, the agent will return a response, describing current issues.

6. You can tail the log files (as shown in the [Validate the Deployment section](#validate-the-deployment)) to observe the interaction between the agent and the external service in real time.

If you encounter any errors, check the [Troubleshooting section](./demos.md#troubleshooting).

## Cleanup

To cleanup the agents and tools in the UI, go to the `Agent Catalog` and `Tool Catalog`
respectively and click the `Delete` button next to each.
