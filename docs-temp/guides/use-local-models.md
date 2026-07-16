---
sidebar_label: Use Local Models
sidebar_position: 5
---

# Use Local Models

Agents need a model backend, and you don't have to send data to a hosted provider to use Rossoctl. This guide points agents at a local or self-hosted model through any OpenAI-compatible endpoint — [Ollama](https://ollama.com/) is the common choice for local development.

## Run a model with Ollama

```bash
ollama pull llama3.1
ollama serve
```

In-cluster, Rossoctl can run Ollama for you as part of the platform so agents reach it at a stable Service address.

## Point an agent at it

Agents read the standard OpenAI-compatible environment variables:

```yaml
apiVersion: rossoctl.dev/v1
kind: AgentRuntime
metadata:
  name: local-agent
  namespace: team1
spec:
  image: ghcr.io/my-org/local-agent:1.0.0
  env:
    - name: LLM_API_BASE
      value: http://ollama.rossoctl-system.svc:11434/v1
    - name: LLM_MODEL
      value: llama3.1
```

For a hosted provider, set the same variables to the provider's endpoint and reference the key from a `Secret`:

```yaml
    - name: LLM_API_BASE
      value: https://api.openai.com/v1
    - name: LLM_API_KEY
      valueFrom:
        secretKeyRef:
          name: llm-credentials
          key: api-key
```

:::tip Keep data in your network
Running the model locally means prompts and completions never leave your infrastructure — the same
reason many teams run agents on Rossoctl in the first place.
:::

:::note For contributors
Confirm the env var names (`LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL`) and the in-cluster Ollama
Service address against `kagenti/docs/local-models.md`.
:::
