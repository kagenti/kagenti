# Generic Agent + Summarizer Skill Demo in the Kagenti UI

This guide explains how to use the Kagenti UI to:

1. import the example [`summarizer`](../agent-examples/skills/summarizer) skill,
2. import the example [`generic_agent`](../agent-examples/a2a/generic_agent) agent,
3. link the skill to the agent from the UI,
4. and verify in chat that the skill is available and being used.

This flow is intended for the Kagenti UI workflow where skills are imported into Kagenti first and then linked to an agent during agent import.

## What this demo shows

The example generic agent loads skill instructions and exposes them through its agent card in the Kagenti UI. In this demo:

- the skill content comes from the imported `summarizer` skill,
- the agent is the example `generic_agent`,
- the linkage between the two is configured in the Kagenti UI when the agent is imported,
- and the result is visible both in the agent card and in the agent chat experience.

## Prerequisites

Before starting, make sure:

- Kagenti is installed and the UI is reachable, as described in [`docs/install.md`](../install.md)
- you have access to a Kagenti-enabled namespace, for example `team1`
- the cluster can build example agents from GitHub
- you have LLM credentials ready for the generic agent

For the example generic agent, configure the LLM environment variables with values appropriate for your setup. At minimum, the generic agent needs:

- `LLM_MODEL`
- `LLM_API_BASE`
- `LLM_API_KEY`

If you use the example env file flow in the UI, you can import the matching env file from the example repository and then adjust values if needed.

## Repositories and paths used in this demo

This guide uses the example repository:

- Repository URL: `https://github.com/kagenti/agent-examples`
- Skill path: `skills/summarizer`
- Agent path: `a2a/generic_agent`

## Step 1: Import the summarizer skill in the UI

1. Open the Kagenti UI.
2. Navigate to **Skills**.
3. Click **Import Skill**.
4. In **Namespace**, select the namespace you will also use for the agent, for example `team1`.
5. In **Name**, enter `summarizer`.
6. In **Description**, enter a clear description, for example:

   `Summarization skill for converting long source text into concise structured summaries.`

7. In **URL**, paste the example skill URL:

   `https://github.com/kagenti/agent-examples/tree/main/skills/summarizer`

8. Wait for the UI to auto-import the skill content and additional files.
9. Confirm that `SKILL.md` was imported.
10. Click **Import Skill**.

After the skill is created, the skill should appear in the skill catalog for the selected namespace.

## Step 2: Import the generic agent in the UI

1. Navigate to **Agents**.
2. Click **Import New Agent**.
3. In **Namespace**, select the same namespace where you imported the skill.
4. Leave **Deployment Method** as **Build from Source**.
5. In **Git Repository URL**, use:

   `https://github.com/kagenti/agent-examples`

6. In **Git Branch or Tag**, use `main`.
7. In **Select Agent**, choose **Generic Agent**.
   This fills the source path with:

   `a2a/generic_agent`

8. Confirm the generated or entered agent name. For this demo, `generic-agent` is a good choice.
9. Set **Protocol** to `a2a`.
10. Set **Framework** to `LangGraph`.

## Step 3: Configure the generic agent environment variables

In the **Environment Variables** section, provide the LLM configuration required by the generic agent.

Add these variables with values that match your environment:

- `LLM_MODEL`
- `LLM_API_BASE`
- `LLM_API_KEY`

Notes:

- If you are using a hosted model endpoint, set these values according to that provider.
- If you are using a local model setup supported by Kagenti, use the values documented in [`docs/local-models.md`](../local-models.md).

Do not set `SKILL_FOLDERS` manually in this demo. When you select a skill in **Linked Skills**, Kagenti mounts the linked skill ConfigMaps into the agent pod under `/app/skills/...` and sets `SKILL_FOLDERS` automatically for the generic agent runtime.

## Step 4: Link the summarizer skill to the agent in the UI

In the **Linked Skills** section of the import form:

1. Find the imported `summarizer` skill in the list of namespace skills.
2. Enable the checkbox for `summarizer`.

This stores the skill linkage with the agent configuration so Kagenti can associate the imported skill with the imported generic agent, mount the skill files into the pod, and expose those mounted paths to the generic agent through `SKILL_FOLDERS`.

## Step 5: Build and deploy the agent

1. Review the remaining defaults.
2. Click **Create** / **Build & Deploy** for the agent.
3. Wait for the Shipwright build to complete.
4. Open the agent details page when the deployment finishes.

## Step 6: Verify that the skill is linked

On the agent details page:

1. Confirm the agent status is healthy.
2. Locate the agent card or skills section.
3. Verify that the `summarizer` skill appears in the agent’s listed skills.
4. If you inspect the running pod, verify Kagenti populated `SKILL_FOLDERS` automatically and mounted the skill under `/app/skills/summarizer`.

This confirms both the UI-visible skill linkage and the runtime skill wiring between the imported skill and the imported generic agent.

## Step 7: Open the chat and test the summarizer skill

From the agent details page, open the chat UI for the generic agent.

Use a prompt that strongly signals summarization. Paste the following demo text into the chat:

```text
Use your summarizer skill to summarize the following project update into:
1. a one-sentence executive summary,
2. exactly 5 bullet points,
3. a short risk list,
4. and 3 clear action items.

Project update:
During the last two sprints, the platform team completed the first end-to-end integration between the Kagenti UI and the example generic agent. The team also imported the summarizer skill into the namespace and linked it to the agent during the UI import flow. Initial testing showed that the agent can accept long-form text and respond with a concise structured summary. However, several follow-up items remain: the team needs to improve documentation, verify the build flow in a fresh namespace, and confirm that the agent card correctly displays linked skills after deployment. There is also an open concern that users may forget to provide the required LLM environment variables, which leads to startup failures that are not always obvious from the UI alone. If the remaining validation passes, the team plans to use this demo in the next stakeholder walkthrough to show how Kagenti can manage both reusable skills and example agents through the same UI.
```

## Expected result

A successful response should look like a structured summary, not a free-form essay.

You should expect the answer to include:

- one short executive-summary sentence,
- 5 bullets summarizing the update,
- a risk section,
- and 3 action items.

A representative successful output would look like this:

```text
Executive summary:
The team successfully connected the Kagenti UI, the generic agent, and the summarizer skill, and now needs to complete validation and documentation before using the flow in a stakeholder demo.

Key points:
- The team completed an end-to-end integration between the Kagenti UI and the generic agent.
- The summarizer skill was imported into the namespace and linked during agent import.
- Initial testing showed the agent can summarize long-form text into a concise structure.
- Documentation and fresh-namespace validation are still pending.
- Missing LLM environment variables remain a usability risk during startup.

Risks:
- Users may omit required LLM configuration.
- Fresh-environment validation may reveal deployment issues.
- Skill display in the agent card still needs confirmation.

Action items:
1. Finalize the step-by-step documentation.
2. Validate the full flow in a new namespace.
3. Confirm agent-card skill visibility before the stakeholder demo.
```

The wording does not need to match exactly, but the structure and behavior should clearly reflect summarization rather than general chat.

## How to tell that the skill is working

The skill is working if all of the following are true:

- the `summarizer` skill is visible in the agent card or skill list,
- the agent responds to the long-form prompt with a concise structured summary,
- the response follows the requested summary structure,
- the runtime did not require you to manually set `SKILL_FOLDERS`,
- and the response is clearly based on summarization behavior rather than a generic unconstrained answer.

## Recommended demo narrative

For a live demo, use this sequence:

1. Show the **Import Skill** page and import the summarizer skill from GitHub.
2. Show the **Import New Agent** page and select `a2a/generic_agent`.
3. Show the **Linked Skills** section and select `summarizer`.
4. Show the finished agent detail page where the skill is listed.
5. Open chat and paste the long project-update prompt.
6. Point out that the resulting response is structured as a summary, which demonstrates the linked skill flow.

## Troubleshooting

### The summarizer skill does not appear in the Linked Skills section

Check that:

- the skill was imported successfully,
- the skill was imported into the same namespace as the agent,
- and the skill appears in the skill catalog before opening the agent import page.

### The agent deploys but chat responses are poor or fail

Check that:

- `LLM_MODEL`, `LLM_API_BASE`, and `LLM_API_KEY` are set correctly,
- the model endpoint is reachable from the agent,
- and the agent pod started successfully.

### The agent does not show the linked skill on its detail page

Check that:

- the skill was selected in **Linked Skills** during agent import,
- the agent build and deployment completed successfully,
- and the agent card was generated for the deployed agent.

### The skill is listed but still does not seem to load at runtime

Check that:

- the linked skill name matches the imported skill name in the same namespace,
- the agent pod has `SKILL_FOLDERS` set,
- the agent pod has mounted skill content under `/app/skills`,
- and the imported skill includes the expected files such as `SKILL.md`.

### The answer is not obviously summarized

Use a longer prompt and explicitly ask the agent to use the summarizer skill and return a structured format. The provided demo prompt is designed for that purpose.

## Cleanup

After the demo, delete the agent and skill from the Kagenti UI:

1. Go to **Agents** and delete the generic agent.
2. Go to **Skills** and delete the summarizer skill.

## Related references

- [`docs/demos/demo-generic-agent.md`](./demo-generic-agent.md)
- [`docs/install.md`](../install.md)
- [`docs/local-models.md`](../local-models.md)
