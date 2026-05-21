# Backend API

> **Test file:** `kagenti/tests/e2e/openshell/test_T5_1_backend_api.py`
> **Tests:** 11

## What This Tests

Validates kagenti-backend as the production A2A proxy path. Instead of per-agent port-forwards, all A2A requests route through a single backend endpoint at `/api/v1/chat/{namespace}/{agent}/send|stream`. Tests cover backend health, agent card proxying, non-streaming send with session tracking, SSE streaming, multi-turn context preservation, agent listing, error handling for invalid agents/namespaces, and concurrent parallel requests across agents.

## Test Functions

- `test_T5_connectivity__backend_health` -- `GET /health` returns 200 with `status: healthy`.
- `test_T5_connectivity__agent_card[agent]` -- Backend proxies the agent card for each A2A agent and returns a response with a `name` field.
- `test_T5_send__responds[agent]` -- `POST /chat/{ns}/{agent}/send` returns a response with non-empty `content`.
- `test_T5_send__has_session_id[agent]` -- Send response includes a non-empty `session_id` for conversation tracking.
- `test_T5_stream__delivers_events[agent]` -- `POST /chat/{ns}/{agent}/stream` delivers SSE `data:` events.
- `test_T5_multiturn__preserves_context[agent]` -- Two sequential sends with the same `session_id` preserve conversation context.
- `test_T5_agent_list__shows_deployed` -- `GET /api/v1/agents?namespace={ns}` lists at least 2 deployed agents.
- `test_T5_agent_list__has_metadata` -- Each agent in the list has a `name` field.
- `test_T5_error__nonexistent_agent` -- Request to an unknown agent returns 404 or 503.
- `test_T5_error__invalid_namespace` -- Request to an unknown namespace returns 404 or 503.
- `test_T5_concurrent__parallel_requests` -- Multiple agents queried in parallel return at least one successful response.
