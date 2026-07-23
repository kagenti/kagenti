---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Importing a Simulated Tool

## Overview
A **simulated tool** is an MCP tool whose behavior Rossoctl generates from an OpenAPI
spec — no real backend, no hand-written MCP server. Rossoctl runs a generic harness
image that reads your spec, generates a skill with an LLM, seeds an in-memory
database, and serves the operations as MCP tools. Use it for demos, onboarding, and
developing agents against a controlled, reproducible API before a real backend exists.

> Simulated tools are gated by the `simulatedTools` feature flag (off by default).
> Enable it with `--set featureFlags.simulatedTools=true` (see [installation](install.md)).

## Prerequisites
- **LLM API key Secret** in the target namespace. The harness needs it at *both*
  generation time and serving time. Create it, e.g.:
  ```
  kubectl create secret generic llm-api-key --from-literal=apiKey=<key> -n team1
  ```
  (the env var injected into the tool is `LLM_API_KEY`).
- **Egress allow-listing** of the inference endpoint. If the namespace enforces
  egress policy, allow the LLM host so both generation and serving can reach it.
- The `simulatedTools` feature flag enabled on the platform.

## Import via the UI
Steps mirroring `docs/new-tool.md`: open **Import Tool**, choose the **Simulated
Tool** method (described as generating a tool from an OpenAPI spec), select a
namespace, paste/upload `openapi.json` (optionally set a custom name), and click
**Create**. You land on the generation
progress page; the tool moves **Generating → Ready** and then appears in the catalog
with a **SIMULATED** badge.

## Import via the seed script (demo/onboarding)
Use the worked example for one-command seeding:
```
./rossoctl/examples/simulated-tools/tasks-api/seed.sh team1
```
This creates the Tasks API simulated tool and waits until it is Ready, printing the
`mcpUrl`. No real external backend is required.

## Managing a simulated tool
From the tool detail page: **Start / Stop** (scale to 1 / 0, bundle retained),
**Reset** (fresh session, same data), **Delete** (removes StatefulSet + Service + PVC).

## Seeding / editing the database
Provide your own dataset (see `db.json` for the shape) via the **Seed database**
action. The dataset is validated against the generated schema; a schema violation
returns `422` (with the offending `json_path`), and a re-seed while calls are in
flight returns `409`.

## Troubleshooting
- **Stuck in Generating / then Failed** — a generation failure surfaces `Failed`
  with the harness reason (e.g. `skill_generation_failed`). Delete and retry.
- **Error status** — the pod cannot start (commonly a missing/invalid LLM key
  Secret; `CreateContainerConfigError` / `CrashLoopBackOff`). Fix the Secret and
  recreate.
- **Never reaches Ready** — check egress to the inference endpoint.

## Related documentation
- [Importing a tool (image / source)](new-tool.md)
- Worked example: `rossoctl/examples/simulated-tools/tasks-api/`
