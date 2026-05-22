# File Organizer Agent Demo (with Cloud Storage Tool)

This document provides detailed steps for running the **File Organizer Agent** proof-of-concept (PoC) demo.

In this demo, we will use the Kagenti UI to import and deploy the **File Organizer Agent** and the **Cloud Storage Tool**.
During deployment, we'll configure the **A2A protocol** for managing agent calls and **MCP** for enabling communication between the agent and tools.

Once deployed, we will query the agent using a natural language prompt. The agent will then invoke the tools to organize files in the bucket specified and return file organization data as a response.

Here's a breakdown of the sections:

- In [**Import New Agent**](#import-new-agent), you'll build and deploy the [`file_organizer_agent`](https://github.com/kagenti/agent-examples/tree/main/a2a/file_organizer_agent) agent.
- In [**Import New Tool**](#import-new-tool), you'll build and deploy [`cloud_storage_tool`](https://github.com/kagenti/agent-examples/tree/main/mcp/cloud_storage_tool) tool.
- In [**Validate the Deployment**](#validate-the-deployment), you'll verify that all components are running and operational.
- In [**Chat with the Generic Agent**](#chat-with-the-generic-agent), you'll interact with the agent and confirm it correctly organizes files in the specified cloud storage bucket.

> **Prerequisites:**
> Ensure you've completed the Kagenti platform setup as described in the [Installation Guide](../install.md).

You should also open the Agent Platform Demo Dashboard as instructed in the [Accessing the UI](../install.md#accessing-the-ui) section.

---

## Import New Agent

To deploy the File Organizer Agent:

1. Navigate to [Import New Agent](http://kagenti-ui.localtest.me:8080/Import_New_Agent#import-new-agent) in the Kagenti UI.
2. In the **Select Namespace to Deploy Agent** drop-down, choose the `<namespace>` where you'd like to deploy the agent. (These namespaces are defined in your `.env` file.)
3. Under **Environment Variables**, configure LLM settings using one of these methods:
   - Click **Import .env File** and import `.env.openai` or `.env.ollama` from the agent examples repo, **or**
   - Manually add env vars: `LLM_API_BASE`, `LLM_API_KEY`, and `LLM_MODEL` (see [Using Local Models](../local-models.md) for values)
4. Under **Environment Variables**, also add:
   - Click `Add Environment Variable`
   - Under `Name` put `BUCKET_URI` and under `Value` put the URI of your cloud storage bucket (e.g., `s3://my-bucket-name/` for AWS S3)
5. In the **Agent Source Repository URL** field, use the default:
   <https://github.com/kagenti/agent-examples>
   Or use a custom repository accessible using the GitHub ID specified in your `.env` file.
6. For **Git Branch or Tag**, use the default `main` branch (or select another as needed).
7. Set **Protocol** to `a2a`.
8. Under [**Specify Source Subfolder**](http://kagenti-ui.localtest.me:8080/Import_New_Agent#specify-source-subfolder):
   - Click `Select from examples`
   - Choose: `a2a/file_organizer`
9. Click **Build & Deploy New Agent** to deploy.

**Note:** The `ollama` environmental variable set specifies `llama3.2:3b-instruct-fp16` as the default model. To download the model, run `ollama pull llama3.2:3b-instruct-fp16`. Please ensure an Ollama server is running in a separate terminal via `ollama serve`. 

---

## Import New Tool

To deploy the Cloud Storage Tool:

1. Get your cloud storage service access credentials (e.g. AWS Access Key and Secret Key for S3, service account JSON for GCS, etc.)
1. Navigate to [Import New Tool](http://kagenti-ui.localtest.me:8080/Import_New_Tool#import-new-tool) in Kagenti's UI.
1. Select the same `<namespace>` as used for the agent.
1. In the **Select Environment Variable Sets** section, select `Import .env File` button, then provide:
   - GitHub Repository URL: `https://github.com/kagenti/agent-examples/`
   - Path to .env file: `mcp/cloud_storage_tool/.env.template`
   - Populate the appropriate environment variables with your cloud storage service access credentials. Note for GCS, it expects the entire service account JSON in a single environment variable with quotes ('') around it. Leave unused variables blank or delete them.
    - Press "Import", this will populate environment variables for this tool.
1. Use the same source repository:
   <https://github.com/kagenti/agent-examples>
1. Choose the `main` branch or your preferred branch.
1. Set **Select Protocol** to `streamable_http`.
1. Under **Specify Source Subfolder**:
   - Select: `mcp/cloud_storage_tool`
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
   cloud-storage-tool-cb7566fdf-z7j8n      3/3     Running       0          29d
   file-organizer-7cc769d86c-fkwmv   3/3     Running       0          25s
   ```

3. Tail the logs to ensure both services have started successfully.
   For the agent:

   ```console
   installer$ kubectl logs -f deployment/file-organizer -n <your-ns>
   Defaulted container "file-organizer" out of: file-organizer, spiffe-helper, kagenti-client-registration, fix-permissions (init)
   INFO:     Started server process [14]
   INFO:     Waiting for application startup.
   INFO:     Application startup complete.
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)

   ```

   For the cloud storage tool:
   ```console
   installer$ kubectl logs -f deployment/cloud-storage-tool -n <your-ns>
   Defaulted container "cloud-storage-tool" out of: cloud-storage-tool, spiffe-helper, kagenti-client-registration, fix-permissions (init)                        
   INFO:     Started server process [14]
   INFO:     Waiting for application startup.
   INFO: StreamableHTTP session manager started
   INFO:     Application startup complete.
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   ```

4. Once you see the logs indicating that both services are up and running, you're ready to proceed to [Chat with the File Organizer Agent](#chat-with-the-file-organizer-agent).

---

## Chat with the File Organizer Agent

Once the deployment is complete, you can run the demo:

1. Navigate to the **Agent Catalog** in the Kagenti UI.
2. Select the same `<namespace>` used during the agent deployment.
3. Under [**Available Agents in <namespace>**](http://kagenti-ui.localtest.me:8080/Agent_Catalog#available-agents-in-kagenti-system), select `file-organizer` and click **View Details**.
4. Scroll to the bottom of the page. In the input field labeled *Say something to the agent...*, enter:

   ```console
   Please organize the objects in the bucket. Use the tools provided to first list the objects, then organize them by file type.
   ```

5. You will see the *Agent Thinking...* message. Depending on the speed of your hosting environment, the agent will return a summary response of its actions. For example:

   ```console
    Sure! I've organized the files in the bucket as follows:
    - Images: image1.jpg, image2.png
    - Documents: doc1.pdf, doc2.docx
    - Videos: video1.mp4, video2.avi
    The files have been moved into their respective folders based on file type.
   ```

6. Sometimes the agent can hallucinate (especially with ollama). Making the prompt more specific and explicit can help with this.

7. Each time new objects are added to the bucket, you should prompt the agent again. It should ignore the already organized files (inside folders), and only target files at the root of the bucket

8. You can tail the log files (as shown in the [Validate the Deployment section](#validate-the-deployment)) to observe the interaction between the agent and the tool in real time.

If you encounter any errors, check the [Troubleshooting Guide](../troubleshooting.md).

## Cleanup

To cleanup the agents and tools in the UI, go to the `Agent Catalog` and `Tool Catalog`
respectively and click the `Delete` button next to each.

You can also manually remove them from the cluster:

```console
installer$ kubectl delete deployment file-organizer cloud-storage-tool -n <your-ns>
installer$ kubectl delete service file-organizer cloud-storage-tool -n <your-ns>
```