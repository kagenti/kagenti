"""Claude SDK agent with code review skill for OpenShell PoC.

Uses the Anthropic Python SDK to call Claude.  The ``ANTHROPIC_BASE_URL``
environment variable can point to LiteLLM's Anthropic pass-through endpoint
so the agent routes through the Budget Proxy instead of calling Anthropic
directly.

A2A exposure is implemented manually via Starlette since the Anthropic SDK
does not include a built-in A2A wrapper (unlike Google ADK's ``to_a2a()``).
"""

import json
import os
import uuid

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# ---------------------------------------------------------------------------
# LLM client — supports both Anthropic SDK and OpenAI-compatible endpoints.
# When ANTHROPIC_BASE_URL points to a non-Anthropic endpoint (e.g., LiteMaaS),
# we use httpx directly with OpenAI chat/completions format.
# ---------------------------------------------------------------------------
_base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
_use_openai_format = "anthropic.com" not in _base_url and _base_url != ""

if _use_openai_format:
    import httpx
    _llm_client = httpx.Client(timeout=120.0)
else:
    import anthropic
    _llm_client = anthropic.Anthropic(
        api_key=_api_key,
        base_url=_base_url if _base_url else anthropic.NOT_GIVEN,
    )
_port = int(os.environ.get("PORT", "8080"))

# ---------------------------------------------------------------------------
# A2A Agent Card
# ---------------------------------------------------------------------------
AGENT_CARD = {
    "name": "claude-code-reviewer",
    "description": "Reviews code using Claude and provides constructive feedback.",
    "url": "http://claude-sdk-agent.team1.svc:8080",
    "version": "0.1.0",
    "capabilities": {"streaming": False},
    "skills": [
        {
            "id": "code_review",
            "name": "Code Review",
            "description": (
                "Review code for quality, security, and best practices. "
                "Provide constructive, actionable feedback."
            ),
        },
    ],
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
async def agent_card(request: Request) -> JSONResponse:
    """Serve the A2A agent card."""
    return JSONResponse(AGENT_CARD)


async def handle_jsonrpc(request: Request) -> JSONResponse:
    """Handle A2A JSON-RPC 2.0 requests (``message/send``)."""
    body = await request.json()
    req_id = body.get("id")
    method = body.get("method")

    if method != "message/send":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Method not found"},
            }
        )

    # Extract user message text from A2A parts
    params = body.get("params", {})
    message = params.get("message", {})
    parts = message.get("parts", [])
    text = " ".join(
        p.get("text", "") for p in parts if p.get("type") == "text"
    )

    # Call LLM — Anthropic SDK or OpenAI-compatible format
    system_prompt = (
        "You are a thorough, constructive code reviewer. "
        "Provide specific, actionable feedback on code quality, "
        "security, performance, and best practices. "
        "Be concise and focus on the most impactful observations."
    )
    import time

    reply_text = None
    for attempt in range(3):
        try:
            if _use_openai_format:
                resp = _llm_client.post(
                    f"{_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {_api_key}"},
                    json={
                        "model": _model,
                        "max_tokens": 1024,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text},
                        ],
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                reply_text = data["choices"][0]["message"]["content"]
            else:
                response = _llm_client.messages.create(
                    model=_model,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": text}],
                )
                reply_text = response.content[0].text
            break
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                "LLM call failed (attempt %d/3): %s", attempt + 1, e
            )
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    if reply_text is None:
        reply_text = "Error: LLM service temporarily unavailable. Please try again."

    task_id = str(uuid.uuid4())
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "id": task_id,
                "status": {"state": "completed"},
                "artifacts": [
                    {"parts": [{"type": "text", "text": reply_text}]},
                ],
            },
        }
    )


# ---------------------------------------------------------------------------
# ASGI application
# ---------------------------------------------------------------------------
app = Starlette(
    routes=[
        Route("/.well-known/agent-card.json", agent_card),
        Route("/", handle_jsonrpc, methods=["POST"]),
    ],
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=_port)
