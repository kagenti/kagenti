# GenAI Skills

Skills for OpenTelemetry GenAI observability and LLM tracing.

## Available Skills

| Skill | Description |
|-------|-------------|
| [semantic-conventions](semantic-conventions/SKILL.md) | GenAI semantic conventions reference for agent instrumentation |

## Overview

The GenAI skills provide patterns for instrumenting AI agents with OpenTelemetry GenAI semantic conventions. This enables:

- **Session tracking** via `gen_ai.conversation.id`
- **Token usage** via `gen_ai.usage.*`
- **Model tracing** via `gen_ai.request.model`

## Architecture

```
Agent (gen_ai.* only) → OTEL Collector → Transform → Phoenix + MLflow
```

Agents emit pure GenAI attributes. The OTEL Collector transforms to target formats.
