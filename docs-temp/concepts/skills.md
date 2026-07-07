---
sidebar_label: Skills
sidebar_position: 4
---

# Skills

A **skill** is a reusable, packaged capability an agent can pick up — a documented procedure plus any assets it needs. Skills let you capture "how we do X" once and share it across agents, instead of re-teaching every agent from scratch.

## What a skill is

On Rosso, a skill is stored as a Kubernetes resource (a labeled `ConfigMap`) with a mandatory `SKILL.md` that describes what the skill does and how to use it. Because skills are first-class, versioned artifacts, they can be governed like any other supply-chain component — reviewed, signed, and rolled back.

```text
my-skill/
  SKILL.md          # what it does, when to use it, inputs/outputs
  scripts/          # optional helper scripts or assets
```

## Why skills are governed

Autonomous agents that can acquire new capabilities at runtime are powerful and risky. Treating skills as governed artifacts means you can answer: *where did this capability come from, who approved it, and what version is running?* That's the difference between a demo and something you'd run on real infrastructure.

## The Skillberry store

Skills can live in **Skillberry**, an optional in-cluster registry with curation and autosync. Teams publish skills to the store; agents pull approved skills from it. See [Manage skills](../guides/manage-skills.md).

:::info Feature-flagged
Skills and the external skill registry are behind feature flags and are off by default. Enable them in
[Configuration](../deployment/configuration.md).
:::

:::note For contributors
Expand from `kagenti/docs/skills.md`. Add a real `SKILL.md` example and the enable/publish flow, plus a
note on signing/versioning once that lands.
:::
