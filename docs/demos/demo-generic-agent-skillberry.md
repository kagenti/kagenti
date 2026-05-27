# Generic Agent + Summarizer Skill via Skillberry Store

This guide explains how to use Kagenti's external skill registry support to:

1. publish the example [`summarizer`](../agent-examples/skills/summarizer) skill to a running [skillberry-store](https://github.ibm.com/skillberry/skillberry-store) instance,
2. register the skill in Kagenti as an **external skill reference** pointing to that registry,
3. import the example [`generic_agent`](../agent-examples/a2a/generic_agent) and link the external skill,
4. and verify in chat that the skill is fetched from the registry at agent startup and used correctly.

This flow differs from the [local skill demo](./demo-generic-agent-skill.md): the skill files are never uploaded into Kagenti. Instead, Kagenti stores only a pointer (URL + metadata) to the skillberry-store instance. When the agent pod starts, an init container fetches the skill archive from the registry and mounts it at the same path that a local skill would occupy. The agent runtime is unaware of the difference.

## What this demo shows

- The skill content lives in an external skillberry-store registry, not in a Kagenti ConfigMap.
- Kagenti holds a lightweight **external skill reference** (a ConfigMap with `kagenti.io/source=external`) instead of the full skill content.
- At agent pod startup, an `alpine:3` init container fetches the skill from the registry and mounts it under `/app/skills/`.
- The agent's `SKILL_FOLDERS` env var is populated automatically, as in the local flow.
- From the agent's perspective the skill is identical to a locally imported skill.

## Prerequisites

### Kagenti

- Kagenti is installed and the UI is reachable, as described in [`docs/install.md`](../install.md).
- You have access to a Kagenti-enabled namespace, for example `team1`.
- The cluster can build example agents from GitHub.
- You have LLM credentials ready for the generic agent (`LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY`).
- **Both** of the following feature flags must be enabled:

  ```bash
  KAGENTI_FEATURE_FLAG_SKILLS=true
  KAGENTI_FEATURE_FLAG_EXTERNAL_SKILLS=true
  ```

  When using the setup script:

  ```bash
  export KAGENTI_FEATURE_FLAG_SKILLS=true
  export KAGENTI_FEATURE_FLAG_EXTERNAL_SKILLS=true
  ./scripts/kind/setup-kagenti.sh --with-backend --with-ui
  ```

  When using the Ansible installer, add to your values file:

  ```yaml
  charts:
    kagenti:
      values:
        featureFlags:
          skills: true
          externalSkills: true
  ```

### Skillberry store

- A running instance of [skillberry-store](https://github.ibm.com/skillberry/skillberry-store) that is **network-reachable from the Kagenti cluster**. The agent init container must be able to reach the registry URL at pod startup time.
- You have credentials or access to publish a skill to that instance (follow skillberry-store's own onboarding documentation).
- Note the base URL of your instance, for example `https://skillberry.example.com`. This is used throughout as `SKILLBERRY_URL`.

## Repositories and paths used in this demo

| Resource | Value |
|---|---|
| Example agent repository | `https://github.com/kagenti/agent-examples` |
| Skill source path | `skills/summarizer` |
| Agent source path | `a2a/generic_agent` |
| Skillberry base URL | `https://skillberry.example.com` *(replace with your instance)* |
| Skill name in registry | `summarizer` |
| Skill version | `1.0.0` |

## Step 1: Publish the summarizer skill to skillberry-store

Clone the agent-examples repository and locate the summarizer skill:

```bash
git clone https://github.com/kagenti/agent-examples
cd agent-examples/skills/summarizer
ls
# SKILL.md  (and any additional files)
```

Use the skillberry-store CLI or API to publish the skill. The exact command depends on your skillberry-store version — refer to the [skillberry-store documentation](https://github.ibm.com/skillberry/skillberry-store) for the authoritative publishing steps. A typical publish looks like:

```bash
skillberry publish \
  --name summarizer \
  --version 1.0.0 \
  --source . \
  --registry "${SKILLBERRY_URL}"
```

After publishing, verify the skill is accessible. The skillberry-store REST API should return a `tar.gz` archive when you request:

```
GET ${SKILLBERRY_URL}/api/v1/skills/summarizer/1.0.0/archive
```

You can confirm this with curl:

```bash
curl -fsSL "${SKILLBERRY_URL}/api/v1/skills/summarizer/1.0.0/archive" -o /tmp/test-summarizer.tar.gz
tar -tzf /tmp/test-summarizer.tar.gz
# Expected: SKILL.md listed in archive contents
```

## Step 2: Register the external skill reference in the Kagenti UI

The Kagenti UI "From Registry" tab creates a lightweight ConfigMap that points to your skillberry-store instance. **No skill content is uploaded.**

1. Open the Kagenti UI.
2. Navigate to **Skills**.
3. Click **Import Skill**.
4. Select the **From Registry** tab.

   > This tab is visible only when the `externalSkills` feature flag is enabled.

5. In **Namespace**, select the namespace you will also use for the agent, for example `team1`.
6. In **Registry Type**, select `skillberry`.
7. In **Registry URL**, enter your skillberry-store base URL:

   `https://skillberry.example.com`

8. In **Skill Name in Registry**, enter:

   `summarizer`

9. In **Version**, enter:

   `1.0.0`

   Leave blank to use `latest`.

10. In **Display Name**, enter:

    `summarizer`

11. In **Description**, enter:

    `Summarization skill for converting long source text into concise structured summaries.`

12. In **Category**, enter `summarization` (optional).
13. Click **Register External Skill**.

After the reference is created, the skill appears in the skill catalog with an **External** badge. If you open the skill detail page, you will see a **Registry Information** card rather than a file tree — the file content is not stored locally.

### Alternative: register via API

If you prefer the API:

```bash
curl -s -X POST "${KAGENTI_URL}/api/v1/skills/external" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "name": "summarizer",
    "namespace": "team1",
    "description": "Summarization skill for converting long source text into concise structured summaries.",
    "category": "summarization",
    "registryType": "skillberry",
    "registryUrl": "https://skillberry.example.com",
    "registrySkillName": "summarizer",
    "registrySkillVersion": "1.0.0"
  }'
```

## Step 3: Import the generic agent in the UI

1. Navigate to **Agents**.
2. Click **Import New Agent**.
3. In **Namespace**, select the same namespace where you registered the skill.
4. Leave **Deployment Method** as **Build from Source**.
5. In **Git Repository URL**, use:

   `https://github.com/kagenti/agent-examples`

6. In **Git Branch or Tag**, use `main`.
7. In **Select Agent**, choose **Generic Agent**.
   This fills the source path with:

   `a2a/generic_agent`

8. Confirm the agent name. For this demo, `generic-agent` is a good choice.
9. Set **Protocol** to `a2a`.
10. Set **Framework** to `LangGraph`.

## Step 4: Configure the generic agent environment variables

In the **Environment Variables** section, provide the LLM configuration:

- `LLM_MODEL`
- `LLM_API_BASE`
- `LLM_API_KEY`

Do not set `SKILL_FOLDERS` manually. Kagenti sets it automatically based on the linked skills, regardless of whether they are local or external registry references.

## Step 5: Link the external summarizer skill to the agent

In the **Linked Skills** section of the import form:

1. Find the `summarizer` skill (marked **External**) in the list.
2. Enable the checkbox for `summarizer`.

Kagenti records the skill linkage. At agent pod startup, an `alpine:3` init container will:

1. fetch `${SKILLBERRY_URL}/api/v1/skills/summarizer/1.0.0/archive`,
2. extract the archive to `/app/skills/summarizer/`,
3. and allow the main agent container to mount the result read-only.

The agent receives `SKILL_FOLDERS=/app/skills/summarizer` automatically.

## Step 6: Build and deploy the agent

1. Review the remaining defaults.
2. Click **Create** / **Build & Deploy**.
3. Wait for the Shipwright build to complete.
4. Open the agent details page when the deployment finishes.

## Step 7: Verify that the skill was fetched at startup

On the agent details page:

1. Confirm the agent status is healthy.
2. Verify that `summarizer` appears in the agent's listed skills.

To confirm the init container fetched the skill successfully, inspect the pod:

```bash
kubectl logs <agent-pod-name> -n team1 -c fetch-skill-0
# Expected output includes:
# Fetching summarizer@1.0.0 from https://skillberry.example.com/api/v1/skills/summarizer/1.0.0/archive
# OK: summarizer@1.0.0 -> /app/skills/summarizer
```

You can also verify the mounted files and environment variable:

```bash
kubectl exec <agent-pod-name> -n team1 -- ls /app/skills/summarizer/
# Expected: SKILL.md (and any other published files)

kubectl exec <agent-pod-name> -n team1 -- env | grep SKILL_FOLDERS
# Expected: SKILL_FOLDERS=/app/skills/summarizer
```

This confirms the skill was fetched from the external registry and wired identically to a local skill.

## Step 8: Open the chat and test the summarizer skill

From the agent details page, open the chat UI.

Paste the following demo prompt:

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

A successful response should be a structured summary, not a free-form essay.

```text
Executive summary:
The team successfully connected the Kagenti UI, the generic agent, and the summarizer skill, and now needs to complete validation and documentation before using the flow in a stakeholder demo.

Key points:
- The team completed an end-to-end integration between the Kagenti UI and the generic agent.
- The summarizer skill was registered from the skillberry-store and linked during agent import.
- Initial testing showed the agent can summarize long-form text into a concise structure.
- Documentation and fresh-namespace validation are still pending.
- Missing LLM environment variables remain a usability risk during startup.

Risks:
- Users may omit required LLM configuration.
- The skillberry-store instance must be reachable from the cluster at pod startup.
- Fresh-environment validation may reveal deployment issues.

Action items:
1. Finalize the step-by-step documentation.
2. Validate the full flow in a new namespace.
3. Confirm agent-card skill visibility before the stakeholder demo.
```

The wording does not need to match exactly. The structure and behavior should clearly reflect summarization rather than general chat.

## How to tell that the skill is working

The skill is working if all of the following are true:

- the `summarizer` skill is visible with an **External** badge in the skill catalog,
- the `fetch-skill-0` init container log shows a successful fetch from skillberry-store,
- `/app/skills/summarizer/SKILL.md` exists in the agent pod,
- `SKILL_FOLDERS` is set to `/app/skills/summarizer` without manual configuration,
- and the agent responds to the long-form prompt with a structured summary.

## Recommended demo narrative

For a live demo:

1. Show the skillberry-store UI or API confirming the `summarizer` skill is published.
2. Show the **Import Skill → From Registry** tab and register the external reference.
3. Point out the **External** badge in the skill catalog and open the detail page to show the Registry Information card instead of a file tree.
4. Show the **Import New Agent** page, select `a2a/generic_agent`, and check `summarizer` in **Linked Skills**.
5. After deployment, show the `kubectl logs ... -c fetch-skill-0` output confirming the fetch.
6. Open chat and paste the long project-update prompt.
7. Point out that the response is structured exactly as a summary, which demonstrates the external registry skill flow.

## Troubleshooting

### The "From Registry" tab is not visible

Check that `KAGENTI_FEATURE_FLAG_EXTERNAL_SKILLS=true` is set. The tab is hidden when the feature flag is disabled. If you enabled it after the UI started, refresh the page.

### The skill reference was created but the agent pod fails to start

The init container (`fetch-skill-0`) could not reach the registry. Check:

```bash
kubectl logs <agent-pod-name> -n team1 -c fetch-skill-0
```

Common causes:

- The skillberry-store URL is not reachable from inside the cluster. Verify network connectivity from a test pod in the same namespace.
- The skill name or version does not exist in the registry. Verify with `curl "${SKILLBERRY_URL}/api/v1/skills/summarizer/1.0.0/archive"` from inside the cluster.
- The archive format is not a valid `tar.gz`. Check the skillberry-store publish step.

### The external skill does not appear in the Linked Skills list

Check that:

- the feature flags `KAGENTI_FEATURE_FLAG_SKILLS` and `KAGENTI_FEATURE_FLAG_EXTERNAL_SKILLS` are both true,
- the external skill reference was created in the same namespace as the agent,
- and the skill appears in the skill catalog before opening the agent import form.

### The agent deploys but responses are poor or fail

Check that `LLM_MODEL`, `LLM_API_BASE`, and `LLM_API_KEY` are set correctly and the model endpoint is reachable from the agent pod.

### The skill appears to be linked but is not used

Check that:

- the init container completed successfully (see logs above),
- `SKILL_FOLDERS` is set in the agent pod (`kubectl exec ... env | grep SKILL_FOLDERS`),
- and the files under `/app/skills/summarizer/` include `SKILL.md`.

## Cleanup

1. Go to **Agents** and delete the generic agent.
2. Go to **Skills** and delete the `summarizer` external skill reference.
3. Optionally remove the skill from the skillberry-store registry if no longer needed.

## Difference from the local skill demo

| | [Local skill demo](./demo-generic-agent-skill.md) | This demo |
|---|---|---|
| Skill content stored in | Kagenti ConfigMap (`data:` field) | skillberry-store archive |
| Kagenti ConfigMap type | `kagenti.io/source` absent (local) | `kagenti.io/source=external` |
| Skill content visible in UI | File tree on skill detail page | Registry information card |
| Skill catalog badge | None | **External** |
| Pod skill delivery | ConfigMap volume mount | `alpine:3` init container fetch |
| Registry reachability required | No | Yes, at pod startup |
| Feature flags required | `KAGENTI_FEATURE_FLAG_SKILLS` | Both skills and `KAGENTI_FEATURE_FLAG_EXTERNAL_SKILLS` |

## Related references

- [`docs/demos/demo-generic-agent-skill.md`](./demo-generic-agent-skill.md) — local skill variant of this demo
- [`docs/demos/demo-generic-agent.md`](./demo-generic-agent.md)
- [`docs/skills.md`](../skills.md) — skills feature overview and feature flag configuration
- [`docs/superpowers/specs/2026-05-27-external-skill-registries-design.md`](../superpowers/specs/2026-05-27-external-skill-registries-design.md) — design spec for the external skill registry feature
- [skillberry-store](https://github.ibm.com/skillberry/skillberry-store) — the external skill registry used in this demo
- [`docs/install.md`](../install.md)
- [`docs/local-models.md`](../local-models.md)
