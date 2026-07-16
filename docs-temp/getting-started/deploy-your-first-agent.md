---
sidebar_label: Deploy Your First Agent
sidebar_position: 4
---

# Deploy Your First Agent

The quickstart used a sample. Here you deploy *your own* agent — from a container image or straight from source. Rossoctl is framework-neutral, so whatever built your agent (LangGraph, CrewAI, AG2, AutoGen, or any A2A-compatible framework) is fine as long as it speaks A2A.

## Option A — from an image

If you already publish an image, point Rossoctl at it with an `AgentRuntime`:

```yaml
apiVersion: rossoctl.dev/v1
kind: AgentRuntime
metadata:
  name: my-agent
  namespace: team1
spec:
  image: ghcr.io/my-org/my-agent:1.0.0
  env:
    - name: LLM_API_BASE
      value: http://ollama.rossoctl-system.svc:11434/v1
```

```bash
rossoctl apply -f my-agent.yaml
rossoctl agent list --namespace team1
```

## Option B — from source

Let Rossoctl build the image in-cluster from a Git repo (via Shipwright — no local Docker build):

```bash
rossoctl agent deploy my-agent \
  --source https://github.com/my-org/my-agent \
  --namespace team1
```

## Provide configuration and secrets

Reference a `Secret` or env file rather than inlining credentials:

```bash
rossoctl agent deploy my-agent \
  --source https://github.com/my-org/my-agent \
  --env-from-file ./my-agent.env \
  --namespace team1
```

:::warning Never inline credentials
Keep API keys and tokens in a `Secret`. Rossoctl injects identity and short-lived tokens at runtime — see
[Security & Identity](../security/overview.md) — so agents rarely need long-lived secrets at all.
:::

## Verify it registered

```bash
rossoctl agent describe my-agent --namespace team1
```

Look for a `Ready` status and a published agent card. Then connect a tool ([Add your first tool](add-your-first-tool.md)) and start a conversation.

:::note For contributors
Align the CR fields and `rossoctl` flags with `kagenti/docs/new-agent.md`. Confirm the real API group
and kind (`AgentRuntime` on `agent.kagenti.dev/v1alpha1` today) and update once the `rossoctl.dev`
group is live.
:::
