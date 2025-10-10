# Authorized Slack Research Agent Demo

## NOTE: This demo is currently under ACTIVE development

---
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
> Ensure you've completed the Kagenti platform setup as described in the [Installation](./demos.md#installation) section.
>
> This demo uses `SLACK_BOT_TOKEN` and `ADMIN_SLACK_BOT_TOKEN` env. variables. See the section
[Slack Tokens](#slack-tokens) below for more details.

You should also open the Agent Platform Demo Dashboard as instructed in the [Connect to the Kagenti UI](./demos.md#connect-to-the-kagenti-ui) section.

#### Slack Tokens

In this demo, the Slack MCP Server will access the Slack API using Slack bot tokens. We will be using two bot tokens: a general `SLACK_BOT_TOKEN` that is used by default and an `ADMIN_SLACK_BOT_TOKEN` that is used when the access token has the `slack-full-access` scope.

For this demo, prior to installing Kagenti, you need to add two variables to the `kagenti/installer/app/.env` file. Visit
[Slack Bot Token](https://docs.slack.dev/quickstart) page and follow instructions to generate the bot token:

1. Create a pre-configured app
1. Select the Slack workspace (e.g. [kagenti-dev](https://kagenti-dev.slack.com) reach out to us to be added.)
1. Edit Configurations
    * Change the name, by replacing `my-powerful-app` with a custom name
    * Modify Slack scopes according to what are required. [See note below]
1. Create
1. Select `Install App` under Settings. This should take you to a page where you can copy `Bot User OAuth Token`. This will be the value you add as `ADMIN_SLACK_BOT_TOKEN` or `SLACK_BOT_TOKEN`

> **Note on required scopes**
> To demonstrate finer-grained authorization, each of the tokens must have different scopes. This demo has been tested where:
> - `ADMIN_SLACK_BOT_TOKEN` has at least `channels:history` and `channels:read`
> - `SLACK_BOT_TOKEN` has only `channels:read`
> This way, a user that can access Slack will be able to list channels, but not read the conversations, and a user with "admin" access will be able to read channels as well.

Repeat the above for another app with a new name. This time limit the scope to `connections:write` only. This will be your `SLACK_BOT_TOKEN`.

Add both variables into `kagenti/installer/app/.env` before executing Kagenti install.

---

## Import New Agent

### Pre-requisite: Pick an LLM provider

The Slack Researcher agent supports any OpenAI-compatible backend. The following models have been tested:

*Ollama*

- granite3.3:8b
This has been tested with an Apple M3 processor and 64 GB of RAM. You will likely need at least 32GB of RAM to run this example locally.

*OpenAI*
The agent will work with a variety of OpenAI models. The following have been tested:

- gpt-4.1-nano
- gpt-4.1-mini
- gpt-4.1
- gpt-4o
- gpt-4o-mini

To log in and import agents you can use [default Kagenti userid](../demos.md#default-kagenti-userid). Log in to the Kagenti UI.

### To deploy the Slack Research Agent

1. Navigate to [Import New Agent](http://kagenti-ui.localtest.me:8080/Import_New_Agent#import-new-agent) in the Kagenti UI.
2. In the **Select Namespace to Deploy Agent** drop-down, choose the `<namespace>` where you'd like to deploy the agent. (These namespaces are defined in your `.env` file.)
3. Under [**Select Environment Variable Sets**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#select-environment-variable-sets), select:

   - `mcp-slack`
   - `slack-researcher-config`
   - `slack-researcher-auth-config`
   - `ollama` or `openai`

4. Depending on the LLM provider you need to do a following:

   - If using `ollama`, note that it uses `granite3.3:8b`, so you may need to run locally:

     ```console
     ollama serve
     ```

     ```console
     ollama pull granite3.3:8b
     ```

     **IMPORTANT**: The default context length in Ollama is 4k; However we need a 128k context length. Go to Ollama -> Settings and adjust the context length to 128k.

   - If using `openai`, you will need to specify a different `TASK_MODEL_ID`, and can do so in the `Custom Environment Variables` section. i.e. `TASK_MODEL_ID=gpt-4.1-nano`

5. In the **Agent Source Repository URL** field, use the default:
   <https://github.com/kagenti/agent-examples>
   Or use a custom repository accessible using the GitHub ID specified in your `.env` file.
6. For **Git Branch or Tag**, use the default `main` branch (or select another as needed).
7. Set **Protocol** to `a2a`.
8. Under [**Specify Source Subfolder**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#specify-source-subfolder):
   - Click `Select from examples`
   - Choose: `a2a/slack_researcher`
9. Click **Build & Deploy New Agent** button.

---

## Import New Tool

To import tools you can use [default Kagenti userid](../demos.md#default-kagenti-userid)

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
8. Click **Build & Deploy New Tool** button.

---

## Configure Keycloak

Now that the agent and tool have been deployed, the Keycloak Administrator must configure the policies to give the UI delegated access to the tool. We have automated these steps in a script.

### Set up Python environment

```console
cd kagenti/auth/auth_demo/
python -m venv venv
```

To run the Keycloak configuration script, you must have Python Keycloak library installed.

```console
pip install -r requirements.txt
```

Define environment variables for accessing Keycloak:

```console
export KEYCLOAK_URL="http://keycloak.localtest.me:8080"
export KEYCLOAK_REALM=master
export KEYCLOAK_ADMIN_USERNAME=admin
export KEYCLOAK_ADMIN_PASSWORD=admin
export NAMESPACE=<namespace>
```

Now run the configuration script:

```console
python set_up_demo.py
```

For more information about the configuration script check the [detailed README.md](../../kagenti/auth/auth_demo/README.md) file.

### Enable Token exchange for the agent

Finally, to enable the agent to perform token exchange, we must [go to Keycloak](http://keycloak.localtest.me:8080/) in the browser. Log in with the admin credentials `admin` and `admin`. 

Click on `Clients` in the left sidebar, and select `spiffe://localtest.me/sa/slack-researcher`. 

Under the `Settings` tab, scroll down to Capability config. Double check that `Client authentication` is enabled. Then enable `Standard Token Exchange` under `Authentication flow`. Then click `Save`. 

Now Keycloak has been fully configured for our example!

---

## Validate The Deployment

Depending on your hosting environment, it may take some time for the agent and tool deployments to complete.

To verify that both the agent and tool are running:

1. Open a terminal and connect to your Kubernetes cluster.
2. Use the namespace you selected during deployment to check the status of the pods:

   ```console
   installer$ kubectl get pods -n <namespace>
   NAME                                READY   STATUS    RESTARTS   AGE
   slack-researcher-8bb4644fc-4d65d    1/1     Running   0          1m
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

## Chat with the Agent

Once the deployment is complete and the Keycloak configured, you can run the demo.

This example demonstrates different results based on the user access control.
The Keycloak was pre-configured with two Kagenti demo users:

- **slack-full-access-user** - Kagenti user that is tied to Slack token `ADMIN_SLACK_BOT_TOKEN`. This user has a full access to all the Slack channels and capabilities.
- **slack-partial-access-user** - Kagenti user that is tied to Slack token `SLACK_BOT_TOKEN`. This user has a limited access to all the Slack channels and limited capabilities. E.g., it can list channels but not read them.

Both users use `password` as password.

Try each userid for the following interactions with the Slack agent:

1. Login with the Kagenti userid.
1. Navigate to the **Agent Catalog** in the Kagenti UI.
1. Select the same `<namespace>` used during the agent deployment.
1. Under [**Available Agents**](http://kagenti-ui.localtest.me:8080/Agent_Catalog) in your namespace, select `slack-researcher` and click **View Details**.
1. Scroll to the bottom of the page. In the input field labeled *Say something to the agent...*, enter:

   ```console
   What are the channels in the Slack?
   ```

1. You will see the *Agent Thinking...* message and a series of `Task Status Update`. Depending on the speed of your hosting environment, and the userid Slack access level, the agent will return a Slack response. For example:

   ```console
    The bot has access to two channels:
        1. general: This channel is for team-wide announcements and conversations. Everyone is included here.
        2. random: This channel is for everything else, including team jokes, spur-of-the-moment ideas, and funny GIFs.
    Please let me know if you need more information about a specific channel.
   ```

1. You can tail the log files (as shown in the [Validate the Deployment section](#validate-the-deployment)) to observe the interaction between the agent and the tool in real time.
1. To demonstrate finer-grained access, another query to try is `What's going on in the general slack channel?`. This query should result in more detail for the `slack-full-access-user` but should result in less detail for the `slack-partial-access-user`.

If you encounter any errors, check the [Troubleshooting section](./demos.md#troubleshooting).

## Cleanup

### Delete the Agent and the Tool

You may navigate to the **Agent Catalog** and **Tool Catalog** in the UI and delete the agent and tool respectively. Else, you may do this in the console:

```console
   installer$ kubectl delete components.kagenti.operator.dev slack-researcher slack-tool -n <namespace>
```

The Kagenti Operator will automatically clean up all related Kubernetes resources.
