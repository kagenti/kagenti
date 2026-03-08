# LiteLLM Session Analytics - Design Document

**Date:** 2026-03-08
**Status:** Draft
**Branch:** `next_phase_agents`

## Problem

Kagenti agents make LLM calls through LiteLLM proxy, but there is no visibility into per-session token usage, cost, or per-model breakdown. Operators cannot answer basic questions like "how many tokens did session X consume?" or "which model drove the most cost?" without manually querying LiteLLM's spend APIs and correlating by hand.

This design adds end-to-end session-level LLM analytics by tagging every LLM call with session metadata at the agent layer, exposing aggregation endpoints in the backend, and rendering usage data in the UI.

## Architecture

Four layers, each building on the previous:

```
+------------------+     +------------------+     +------------------+     +------------------+
| Layer 1          |     | Layer 2          |     | Layer 3          |     | Layer 4          |
| Agent Metadata   | --> | Backend Endpoint | --> | UI API Client    | --> | UI Component     |
| Tagging          |     | (token_usage.py) |     | (api.ts)         |     | (SessionStats    |
|                  |     |                  |     |                  |     |  Panel.tsx)       |
+------------------+     +------------------+     +------------------+     +------------------+
```

### Layer 1: Agent Metadata Tagging

Every LLM call made by an agent must carry session metadata so LiteLLM can associate spend records with the originating session, agent, and namespace.

**Mechanism:** Pass metadata through `ChatOpenAI`'s `model_kwargs` using LiteLLM's `extra_body` extension:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4o",
    model_kwargs={
        "extra_body": {
            "metadata": {
                "tags": [
                    f"session_id:{context_id}",
                    f"agent_name:{agent_name}",
                    f"namespace:{namespace}",
                ],
                "spend_logs_metadata": {
                    "session_id": context_id,
                    "agent_name": agent_name,
                    "namespace": namespace,
                },
            }
        }
    },
)
```

**Key points:**

- `tags` enables filtering via LiteLLM's `/spend/tags` API
- `spend_logs_metadata` enables filtering via LiteLLM's `/spend/logs` API with arbitrary key-value queries
- Both are set so either query path works
- The tagging must be applied at agent initialization time, before any LLM calls are made
- `context_id` is the session/context identifier already tracked by the platform

### Layer 2: Backend Endpoint

New FastAPI router `token_usage.py` that proxies and aggregates LiteLLM spend data.

**File:** `kagenti/backend/routers/token_usage.py`

#### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/token-usage/sessions/{context_id}` | Per-model token usage for a single session |
| `GET` | `/api/v1/token-usage/sessions/{context_id}/tree` | Rollup including child sessions |

#### Per-Session Endpoint

`GET /api/v1/token-usage/sessions/{context_id}`

Queries LiteLLM's `/spend/logs` API filtered by `session_id` metadata tag, then aggregates by model.

**Response model:**

```python
class ModelUsage(BaseModel):
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    num_calls: int
    cost: float

class SessionTokenUsage(BaseModel):
    context_id: str
    models: list[ModelUsage]
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_calls: int
    total_cost: float
```

**Logic:**

1. Call LiteLLM `/spend/logs` with filter `{"spend_logs_metadata.session_id": context_id}`
2. Group returned spend records by `model`
3. Sum `prompt_tokens`, `completion_tokens`, `total_tokens`, and `spend` per model
4. Count records per model as `num_calls`
5. Return `SessionTokenUsage`

#### Tree Endpoint

`GET /api/v1/token-usage/sessions/{context_id}/tree`

Same as per-session, but also includes child sessions (e.g., sub-agent sessions spawned from a parent).

**Response model:**

```python
class SessionTreeUsage(BaseModel):
    context_id: str
    own_usage: SessionTokenUsage
    children: list[SessionTokenUsage]
    aggregate: SessionTokenUsage  # rolled-up totals across own + children
```

**Logic:**

1. Query the session store for child sessions of `context_id`
2. Fetch `SessionTokenUsage` for the parent and each child
3. Merge all `ModelUsage` records into the `aggregate` field

#### LiteLLM API Proxying

The backend proxies two LiteLLM APIs:

| LiteLLM API | Used for |
|-------------|----------|
| `GET /spend/logs` | Fetching raw spend records filtered by metadata |
| `GET /spend/tags/{tag}/info` | Alternative: fetching spend by tag value |

The backend holds the LiteLLM API key and base URL in its configuration. The UI never calls LiteLLM directly.

### Layer 3: UI API Client

TypeScript types and fetch methods added to the existing API client.

**File:** `kagenti/ui-v2/src/api.ts` (or equivalent API module)

#### Types

```typescript
interface ModelUsage {
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  num_calls: number;
  cost: number;
}

interface SessionTokenUsage {
  context_id: string;
  models: ModelUsage[];
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_calls: number;
  total_cost: number;
}

interface SessionTreeUsage {
  context_id: string;
  own_usage: SessionTokenUsage;
  children: SessionTokenUsage[];
  aggregate: SessionTokenUsage;
}
```

#### Fetch Methods

```typescript
async function getSessionTokenUsage(contextId: string): Promise<SessionTokenUsage> {
  const response = await fetch(`/api/v1/token-usage/sessions/${contextId}`);
  return response.json();
}

async function getSessionTreeUsage(contextId: string): Promise<SessionTreeUsage> {
  const response = await fetch(`/api/v1/token-usage/sessions/${contextId}/tree`);
  return response.json();
}
```

### Layer 4: UI Component

**File:** `kagenti/ui-v2/src/components/SessionStatsPanel.tsx`

An "LLM Usage" card rendered within the session detail view. Displays a per-model breakdown table.

#### Table Columns

| Column | Source Field | Format |
|--------|-------------|--------|
| Model | `model` | String |
| Prompt Tokens | `prompt_tokens` | Number with comma separators |
| Completion Tokens | `completion_tokens` | Number with comma separators |
| Total Tokens | `total_tokens` | Number with comma separators |
| Calls | `num_calls` | Integer |
| Cost | `cost` | `$X.XXXX` |

#### Behavior

- Fetches data on mount using `getSessionTokenUsage(contextId)`
- Shows a loading skeleton while fetching
- Shows "No LLM usage data" if the response has zero models
- Includes a totals row at the bottom summing all models
- Optionally toggles between "This session" and "Including children" (tree view)

## Implementation Sequence

| Step | Layer | Description | Dependencies |
|------|-------|-------------|-------------|
| 1 | Agent Metadata Tagging | Add `extra_body.metadata` to `ChatOpenAI` initialization in agent code | LiteLLM proxy configured with spend tracking enabled |
| 2 | Backend Endpoint | Create `token_usage.py` router with both endpoints, register in FastAPI app | Step 1 (spend data must exist in LiteLLM) |
| 3 | UI API Client | Add TypeScript types and fetch methods to `api.ts` | Step 2 (endpoints must exist) |
| 4 | UI Component | Build `SessionStatsPanel.tsx` with per-model breakdown table | Step 3 (API client must exist) |
| 5 | E2E Test | Test that runs an agent session, then verifies token usage appears in API and UI | Steps 1-4 |

### Step 1: Agent Metadata Tagging

- Identify all places where `ChatOpenAI` (or equivalent LLM client) is instantiated
- Add the `model_kwargs` with `extra_body` metadata
- Ensure `context_id`, `agent_name`, and `namespace` are available at initialization time
- Verify spend records appear in LiteLLM's `/spend/logs` with correct metadata

### Step 2: Backend Endpoint

- Create `kagenti/backend/routers/token_usage.py`
- Add Pydantic response models: `ModelUsage`, `SessionTokenUsage`, `SessionTreeUsage`
- Implement LiteLLM `/spend/logs` proxying with metadata filtering
- Implement aggregation logic (group by model, sum tokens/cost)
- Register router in the FastAPI app
- Add unit tests with mocked LiteLLM responses

### Step 3: UI API Client

- Add TypeScript interfaces matching the backend response models
- Add fetch functions with proper error handling
- Ensure authentication headers are forwarded

### Step 4: UI Component

- Create `SessionStatsPanel.tsx` with the per-model table
- Integrate into the session detail view
- Handle loading, empty, and error states
- Format numbers with locale-aware comma separators
- Format cost as USD with 4 decimal places

### Step 5: E2E Test

- Run an agent session that makes at least one LLM call with metadata tagging
- Query `GET /api/v1/token-usage/sessions/{context_id}` and assert non-zero usage
- Verify the UI renders the LLM Usage card with correct data
- Test the tree endpoint with a parent/child session pair

## Configuration

| Config Key | Description | Default |
|------------|-------------|---------|
| `LITELLM_BASE_URL` | LiteLLM proxy base URL | `http://litellm:4000` |
| `LITELLM_API_KEY` | LiteLLM master key for spend APIs | (required) |
| `LITELLM_SPEND_TRACKING` | Must be enabled on the LiteLLM proxy | `true` |

## Future Considerations

- **Time-range filtering**: Add `?from=` and `?to=` query params to scope usage by time window
- **Namespace-level aggregation**: Aggregate usage across all sessions in a namespace for team-level billing
- **Cost alerts**: Threshold-based notifications when session or namespace cost exceeds a limit
- **Export**: CSV/JSON export of usage data for external reporting
- **Dashboard**: Aggregate dashboard showing usage trends across sessions over time
