---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Generic Agent + Summarizer Skill via Skillberry Store

This guide explains how to use Rossoctl's external skill registry support to:

1. publish the example [`summarizer`](../agent-examples/skills/summarizer) skill to a running [skillberry-store](https://github.ibm.com/skillberry/skillberry-store) instance,
2. register the skill in Rossoctl as an **external skill reference** pointing to that registry,
3. import the example [`generic_agent`](../agent-examples/a2a/generic_agent) and link the external skill,
4. and verify in chat that the skill is fetched from the registry at agent startup and used correctly.

This flow differs from the [local skill demo](./demo-generic-agent-skill.md): the skill files are never uploaded into Rossoctl. Instead, Rossoctl stores only a pointer (URL + metadata) to the skillberry-store instance. When the agent pod starts, an init container fetches the skill archive from the registry and mounts it at the same path that a local skill would occupy. The agent runtime is unaware of the difference.

## Two ways to provide the registry

You can point Rossoctl at the skillberry-store in one of two ways:

1. **In-cluster store (simplest).** `--with-skills` deploys a skillberry-store
   pod inside the cluster and **auto-enables autosync against it** — no external
   instance and **no `--skill-registry-allowed-hosts` needed** (the in-cluster
   `*.svc` URL is trusted by the autosync loop). The store UI is browsable at
   `http://skillberry-store.<domain>:8080`. Override the image with the
   `SKILLBERRY_STORE_IMAGE` / `SKILLBERRY_STORE_TAG` env vars (default tag `0.2.0`).
   With this path, skip the external-instance prerequisites below and publish your
   skill to the in-cluster store (its API is reachable in-cluster at
   `http://skillberry-store.rossoctl-system.svc.cluster.local:8000`).
   skillberry-store's plugins — which **manage** the skills in the store
   (creating, evaluating, optimizing, deduplicating, and security-scanning them)
   — call an LLM and read their configuration from environment variables on the
   store pod. To enable those plugins, inject the LLM provider/model and API keys
   via `skillberryStore.extraEnv` — see
   [Configuring skillberry-store Environment Variables](../skills.md#configuring-skillberry-store-environment-variables).

2. **External instance (this guide's main flow).** Run skillberry-store yourself
   somewhere reachable, register it as an external skill reference, and (for
   private/LAN addresses) allow-list it via `--skill-registry-allowed-hosts`. The
   rest of this guide walks through this path.

## What this demo shows

- The skill content lives in an external skillberry-store registry, not in a Rossoctl ConfigMap.
- Rossoctl holds a lightweight **external skill reference** (a ConfigMap with `rossoctl.io/source=external`) instead of the full skill content.
- At agent pod startup, an `alpine:3` init container fetches the skill from the registry and mounts it under `/app/skills/`.
- The agent's `SKILL_FOLDERS` env var is populated automatically, as in the local flow.
- From the agent's perspective the skill is identical to a locally imported skill.

## Prerequisites

### Rossoctl

- Rossoctl is installed and the UI is reachable, as described in [`docs/install.md`](../install.md).
- You have access to a Rossoctl-enabled namespace, for example `team1`.
- The cluster can build example agents from GitHub.
- You have LLM credentials ready for the generic agent (`LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY`).
- **Both** `featureFlags.skills` and `featureFlags.externalSkills` must be enabled.

  When using the Kind setup script, use `--with-skills` (enables both flags and auto-enables backend and UI):

  ```bash
  scripts/kind/setup-rossoctl.sh --with-skills --with-builds
  ```

  To also build images from source:

  ```bash
  scripts/kind/setup-rossoctl.sh --with-skills --with-builds --build-images --skip-cluster
  ```

  When using the Ansible installer, add to your values file:

  ```yaml
  charts:
    rossoctl:
      values:
        featureFlags:
          skills: true
          externalSkills: true
  ```

  When enabling on an already-running cluster with Helm:

  ```bash
  helm upgrade rossoctl ./charts/rossoctl/ \
    --reuse-values \
    --set featureFlags.skills=true \
    --set featureFlags.externalSkills=true \
    -n rossoctl-system
  ```

### Skillberry store

- A running instance of [skillberry-store](https://github.ibm.com/skillberry/skillberry-store) accessible at:
  - **UI**: `http://localhost:8002/`
  - **FastAPI / REST API**: `http://localhost:8000/`
- You have credentials or access to publish a skill to that instance (follow skillberry-store's own [onboarding documentation](https://github.com/skillberry-ai/skillberry-store/blob/main/README.md) and [CLI guide](https://github.com/skillberry-ai/skillberry-store/blob/main/docs/cli.md)).
- **Kind cluster note**: the `sbs` CLI and `curl` commands in this guide run from your workstation and use `http://localhost:8000`. However, the registry URL you register in Rossoctl (Step 2) is fetched by an init container running **inside** the Kind cluster — it cannot reach `localhost` on the host. Use `http://host.docker.internal:8000` (Docker Desktop / WSL2) or your host's LAN IP (e.g. `http://192.168.1.10:8000`) for that field.
- **Private/LAN registry note (SSRF allow-list)**: the backend validates registry URLs and rejects ones that resolve to private/internal addresses (RFC-1918, loopback, link-local) to prevent SSRF. A LAN IP like `192.168.1.10` or an in-cluster `*.svc` name is private, so you must explicitly allow it via the `SKILL_REGISTRY_ALLOWED_HOSTS` setting (comma-separated hostnames, IPs, or CIDRs). Empty by default — public registries need no configuration. Set it one of these ways:
  - **Kind installer**: pass `--skill-registry-allowed-hosts "192.168.1.10"` (accepts a comma-separated list / CIDRs) to `scripts/kind/setup-rossoctl.sh`.
  - **Helm**: set `ui.backend.skillRegistryAllowedHosts` (e.g. `"192.168.1.10"` or `"192.168.0.0/16"`).
  - **Existing deployment**: set the `SKILL_REGISTRY_ALLOWED_HOSTS` env var on the backend and restart, e.g. `kubectl set env deploy/rossoctl-backend -n rossoctl-system SKILL_REGISTRY_ALLOWED_HOSTS=192.168.1.10`.

## Repositories and paths used in this demo

| Resource | Value |
|---|---|
| Example agent repository | `https://github.com/rossoctl/examples` |
| Skill source path | `skills/summarizer` |
| Agent source path | `a2a/generic_agent` |
| Skillberry UI | `http://localhost:8002/` |
| Skillberry API (FastAPI / `sbs` CLI) | `http://localhost:8000/` |
| Registry URL for Kind init container | `http://host.docker.internal:8000` or host LAN IP |
| Skill name in registry | `summarizer` |
| Skill version | `1.0.0` |

## Step 1: Publish the summarizer skill to skillberry-store

Clone the agent-examples repository and locate the summarizer skill:

```bash
git clone https://github.com/rossoctl/examples
cd agent-examples/skills/summarizer
ls
# SKILL.md  (and any additional files)
```

Use `curl` to import the skill into skillberry-store via the `POST /skills/import-anthropic` endpoint:

```bash
curl -s -X POST "http://localhost:8000/skills/import-anthropic" \
  -F "source_type=folder" \
  -F "folder_path=/path/to/agent-examples/skills/summarizer" \
  -F "treat_all_as_documents=true"
```

Replace `/path/to/agent-examples` with the actual path where you cloned the repository. A successful response looks like:

```json
{
  "success": true,
  "message": "Successfully imported Anthropic skill 'summarizer' (created)",
  "skill_name": "summarizer",
  "tools_created": 29,
  "snippets_created": 2
}
```

Optional form fields:

| Field | Default | Description |
|-------|---------|-------------|
| `snippet_mode` | `file` | How text files are split: `file` (one snippet per file) or `paragraph` |
| `tags` | `[]` | Additional tags to attach to all imported objects |
| `treat_all_as_documents` | `false` | Treat all files as documents (set to `true` in this demo) |

After importing, verify the skill is visible in the skillberry-store UI at `http://localhost:8002/`.

You can also verify via the export endpoint, which returns a ZIP archive:

```bash
curl -fsSL "http://localhost:8000/skills/summarizer/export-anthropic" -o /tmp/test-summarizer.zip
unzip -l /tmp/test-summarizer.zip
# Expected: summarizer/SKILL.md and other skill files listed
```

## Step 2: Register the external skill reference in the Rossoctl UI

The Rossoctl UI "From Registry" tab creates a lightweight ConfigMap that points to your skillberry-store instance. **No skill content is uploaded.**

1. Open the Rossoctl UI.
2. Navigate to **Skills**.
3. Click **Import Skill**.
4. Select the **From Registry** tab.

   > This tab is visible only when the `externalSkills` feature flag is enabled.

5. In **Namespace**, select the namespace you will also use for the agent, for example `team1`.
6. In **Registry Type**, select `skillberry`.
7. In **Registry URL**, enter the skillberry-store API URL that is reachable from **inside the Kind cluster** (not from your workstation). On Docker Desktop or WSL2 use:

   `http://host.docker.internal:8000`

   If `host.docker.internal` does not resolve in your environment, use your host's LAN IP instead (e.g. `http://172.26.89.33:8000`). The init container that fetches the skill archive at pod startup must be able to reach this URL.

   > **Important:** The URL must include the `http://` prefix (e.g. `http://172.26.89.33:8000`, not `172.26.89.33:8000`). The form shows a hint as a reminder.

   Once you enter a valid URL, the **Skill Name in Registry** field automatically becomes a combobox populated with all skills available in the registry. The remaining fields stay disabled until you select a skill.

8. In **Skill Name in Registry**, open the combobox and select `summarizer` (or type to filter the list).

   As soon as you select a skill, the following fields are filled in automatically:

   | Field | Auto-filled value |
   |---|---|
   | **Version** | skill version from the registry (e.g. `1.0.0`) |
   | **Display Name** | skill name (e.g. `summarizer`) |
   | **Description** | skill description from the registry |

   You can edit any auto-filled value before registering. **Category** is not populated automatically (skillberry does not have a category field) — enter `summarization` manually if desired.

9. Review the auto-filled fields and adjust if needed.
10. Click **Register External Skill**.

After the reference is created, the skill appears in the skill catalog with an **External** badge. If you open the skill detail page, you will see a **Registry Information** card rather than a file tree — the file content is not stored locally.

### Alternative: register via API

If you prefer the API:

```bash
# Use the URL reachable from inside the Kind cluster, not localhost
curl -s -X POST "${ROSSOCTL_URL}/api/v1/skills/external" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -d '{
    "name": "summarizer",
    "namespace": "team1",
    "description": "Summarization skill for converting long source text into concise structured summaries.",
    "category": "summarization",
    "registryType": "skillberry",
    "registryUrl": "http://host.docker.internal:8000",
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

   `https://github.com/rossoctl/examples`

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

Do not set `SKILL_FOLDERS` manually. Rossoctl sets it automatically based on the linked skills, regardless of whether they are local or external registry references.

## Step 5: Link the external summarizer skill to the agent

In the **Linked Skills** section of the import form:

1. Find the `summarizer` skill (marked **External**) in the list.
2. Enable the checkbox for `summarizer`.

Rossoctl records the skill linkage. At agent pod startup, an `alpine:3` init container will:

1. fetch `<registry-url>/skills/summarizer/export-anthropic` (the URL registered in Step 2, e.g. `http://host.docker.internal:8000/skills/summarizer/export-anthropic`),
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
# Fetching summarizer from http://host.docker.internal:8000/skills/summarizer/export-anthropic
# OK: summarizer -> /app/skills/summarizer
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
During the last two sprints, the platform team completed the first end-to-end integration between the Rossoctl UI and the example generic agent. The team also imported the summarizer skill into the namespace and linked it to the agent during the UI import flow. Initial testing showed that the agent can accept long-form text and respond with a concise structured summary. However, several follow-up items remain: the team needs to improve documentation, verify the build flow in a fresh namespace, and confirm that the agent card correctly displays linked skills after deployment. There is also an open concern that users may forget to provide the required LLM environment variables, which leads to startup failures that are not always obvious from the UI alone. If the remaining validation passes, the team plans to use this demo in the next stakeholder walkthrough to show how Rossoctl can manage both reusable skills and example agents through the same UI.
```

## Expected result

A successful response should be a structured summary, not a free-form essay.

```text
Executive summary:
The team successfully connected the Rossoctl UI, the generic agent, and the summarizer skill, and now needs to complete validation and documentation before using the flow in a stakeholder demo.

Key points:
- The team completed an end-to-end integration between the Rossoctl UI and the generic agent.
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

1. Show the skillberry-store UI at `http://localhost:8002/` confirming the `summarizer` skill is published, or run `curl -o /dev/null -w "%{http_code}" http://localhost:8000/skills/summarizer/export-anthropic` to confirm `200`.
2. Show the **Import Skill → From Registry** tab. Enter the registry URL and watch the **Skill Name in Registry** field become a combobox populated from the registry. Select `summarizer` and show the other fields auto-filling.
3. Point out the **External** badge in the skill catalog, the **View ↗** link in the Registry column, and open the detail page to show the Registry Information card instead of a file tree.
4. Show the **Import New Agent** page, select `a2a/generic_agent`, and check `summarizer` in **Linked Skills**.
5. After deployment, show the `kubectl logs ... -c fetch-skill-0` output confirming the fetch.
6. Open chat and paste the long project-update prompt.
7. Point out that the response is structured exactly as a summary, which demonstrates the external registry skill flow.

## Troubleshooting

### The "From Registry" tab is not visible

The tab is hidden when `featureFlags.externalSkills` is false. Verify both flags are enabled:

```bash
kubectl get deployment rossoctl-backend -n rossoctl-system \
  -o jsonpath='{.spec.template.spec.containers[0].env}' \
  | python3 -m json.tool | grep -A1 "FEATURE_FLAG_SKILLS\|FEATURE_FLAG_EXTERNAL"
```

If either flag shows `"false"`, enable both with:

```bash
helm upgrade rossoctl ./charts/rossoctl/ \
  --reuse-values \
  --set featureFlags.skills=true \
  --set featureFlags.externalSkills=true \
  -n rossoctl-system
```

Wait for the pods to restart, then refresh the page. If you deployed with the Kind setup script, use `--with-skills` on the next run.

### The skill reference was created but the agent pod fails to start

The init container (`fetch-skill-0`) could not reach the registry. Check:

```bash
kubectl logs <agent-pod-name> -n team1 -c fetch-skill-0
```

Common causes:

- The skillberry-store URL is not reachable from inside the cluster. The registered URL must be reachable from the Kind pod, not just from your workstation. `localhost:8000` does not resolve inside a Kind pod — use `http://host.docker.internal:8000` (Docker Desktop / WSL2) or your host's LAN IP.
  Verify from a test pod in the same namespace:
  ```bash
  kubectl run -it --rm nettest --image=alpine --restart=Never -n team1 -- \
    wget -qO- http://host.docker.internal:8000/skills/summarizer/export-anthropic | wc -c
  ```
- The skill does not exist in the registry. Verify from your workstation: `curl -o /dev/null -w "%{http_code}" "http://localhost:8000/skills/summarizer/export-anthropic"` — expect `200`.
- The downloaded archive is not a valid ZIP file. Verify the export endpoint returns a ZIP: `curl -fsSL "http://localhost:8000/skills/summarizer/export-anthropic" -o /tmp/test.zip && file /tmp/test.zip` — should say `Zip archive data`.

### The external skill does not appear in the Linked Skills list

Check that:

- the feature flags `ROSSOCTL_FEATURE_FLAG_SKILLS` and `ROSSOCTL_FEATURE_FLAG_EXTERNAL_SKILLS` are both true,
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
| Skill content stored in | Rossoctl ConfigMap (`data:` field) | skillberry-store archive |
| Rossoctl ConfigMap type | `rossoctl.io/source` absent (local) | `rossoctl.io/source=external` |
| Skill content visible in UI | File tree on skill detail page | Registry information card |
| Skill catalog badge | None | **External** |
| Pod skill delivery | ConfigMap volume mount | `alpine:3` init container fetch |
| Registry reachability required | No | Yes, at pod startup |
| Feature flags required | `featureFlags.skills` | `featureFlags.skills` + `featureFlags.externalSkills` |

## Related references

- [`docs/demos/demo-generic-agent-skill.md`](./demo-generic-agent-skill.md) — local skill variant of this demo
- [`docs/demos/demo-generic-agent.md`](./demo-generic-agent.md)
- [`docs/skills.md`](../skills.md) — skills feature overview and feature flag configuration
- [`docs/superpowers/specs/2026-05-27-external-skill-registries-design.md`](../superpowers/specs/2026-05-27-external-skill-registries-design.md) — design spec for the external skill registry feature
- [skillberry-store](https://github.ibm.com/skillberry/skillberry-store) — the external skill registry used in this demo
- [`docs/install.md`](../install.md)
- [`docs/local-models.md`](../local-models.md)
