---
sidebar_label: State & Sessions
sidebar_position: 3
---

:::danger Placeholder content
This content is placeholder and should be replaced, edited, or deleted by the content owners.
:::

# State & Sessions

Agents that hold a conversation or work over long periods need memory that survives a restart. Rossoctl provides persistent state and session management so an agent can be rescheduled, upgraded, or resumed without losing its context.

## Why it matters

A stateless restart is fine for a request/response tool. It's a problem for an agent mid-task: lose the session and you lose the conversation, the plan, and any partial work. Persistent state lets you treat agents as durable, resumable workloads.

## What Rossoctl persists

- **Conversation history** — so a user can pick up where they left off.
- **Session context** — the working state an agent accumulates during a task.
- **Continuity across restarts** — reschedules and upgrades resume rather than reset.

## Operating with state

- Back up the stateful components (see the [production checklist](../deployment/production-checklist.md)).
- Understand your retention policy — how long sessions live and when they're reclaimed.
- Watch storage growth as long-running agents accumulate context.

:::tip Design agents to resume
Agents that checkpoint their progress recover gracefully from a restart. Treat "can this agent be
killed and resumed?" as a design requirement, not an afterthought.
:::

:::note For contributors
Ground this in the State Management workstream and `agentic-runtime/*` (session persistence, multiturn
resume). Add the concrete storage backend and retention settings once confirmed.
:::
