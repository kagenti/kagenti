---
sidebar_label: Manage Skills
sidebar_position: 3
---

# Manage Skills

Skills package a reusable capability an agent can adopt. This guide enables the skills feature, authors a skill, and publishes it for agents to use. For the concept, see [Skills](../concepts/skills.md).

## Enable the feature

Skills are off by default. Turn them on in your platform configuration:

```bash
rossoctl config set features.skills=true
# For the shared store as well:
rossoctl config set features.externalSkills=true
```

## Author a skill

A skill is a folder with a required `SKILL.md` describing what it does and when to use it:

```markdown
---
name: summarize-incident
description: Turn an incident timeline into a concise executive summary.
---

# Summarize Incident

Use this skill when asked to summarize an incident for leadership.

## Inputs
- A timeline of events (timestamps + descriptions)

## Steps
1. Group events by phase (detection, mitigation, resolution).
2. Produce a 5-sentence summary with impact and follow-ups.
```

## Publish it

```bash
rossoctl skill publish ./summarize-incident --namespace team1
rossoctl skill list --namespace team1
```

Published skills land in the **Skillberry** store, where they can be curated and synced to agents.

## Attach a skill to an agent

```bash
rossoctl agent add-skill orders-agent --skill summarize-incident --namespace team1
```

:::tip Treat skills like code
Review and version skills the same way you review code. Because they change what an agent can do,
they're part of your supply chain — see [Audit & Governance](../security/audit-and-governance.md).
:::

:::note For contributors
Confirm the flag names (`skills`, `externalSkills`) and CLI verbs against `kagenti/docs/skills.md`, and
add the REST API and UI paths for teams that don't use the CLI.
:::
