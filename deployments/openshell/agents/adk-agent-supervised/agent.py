"""Minimal Google ADK agent with PR review skill for OpenShell PoC.

Uses LiteLlm wrapper so the agent talks to the Budget Proxy (OpenAI-compatible)
instead of requiring a direct Gemini API key.  Falls back to gemini-flash if
no LLM_MODEL is set and the LiteLlm import fails.

A2A exposure via ``to_a2a()`` auto-generates the agent card at
``/.well-known/agent-card.json``.
"""

import os

from google.adk.agents import LlmAgent
from google.adk.a2a.utils.agent_to_a2a import to_a2a

# ---------------------------------------------------------------------------
# LiteLlm integration — routes requests through the Budget Proxy
# ---------------------------------------------------------------------------
try:
    from google.adk.models.lite_llm import LiteLlm

    _model = LiteLlm(model=os.environ.get("LLM_MODEL", "openai/llama-4-scout"))
except Exception:
    # Graceful fallback: use Gemini directly (requires GOOGLE_API_KEY).
    _model = os.environ.get("LLM_MODEL", "gemini-2.0-flash")  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Tool: review_pr
# ---------------------------------------------------------------------------
def review_pr(diff: str) -> str:
    """Review a pull-request diff and return structured feedback.

    Args:
        diff: The unified diff text of the pull request.

    Returns:
        A short review summary with actionable comments.
    """
    lines = diff.strip().splitlines()
    additions = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))

    return (
        f"PR Review Summary\n"
        f"-----------------\n"
        f"Lines added  : {additions}\n"
        f"Lines removed: {deletions}\n"
        f"Total diff   : {len(diff)} characters\n\n"
        f"Observations:\n"
        f"- Verify new code has adequate test coverage.\n"
        f"- Check error handling in changed paths.\n"
        f"- Confirm no secrets or credentials are included.\n"
        f"- Review naming conventions for consistency.\n"
    )


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------
root_agent = LlmAgent(
    name="pr_reviewer",
    model=_model,
    description="Reviews pull request diffs and provides constructive feedback.",
    instruction=(
        "You are a thorough, constructive code reviewer. "
        "When a user provides a diff, call the review_pr tool and then "
        "augment its output with specific, actionable suggestions. "
        "Be concise and focus on correctness, security, and readability."
    ),
    tools=[review_pr],
)

# ---------------------------------------------------------------------------
# A2A server — ``to_a2a()`` auto-generates the agent card and wraps the
# agent in a Starlette ASGI app compatible with the A2A protocol.
# ---------------------------------------------------------------------------
_port = int(os.environ.get("PORT", "8080"))
app = to_a2a(root_agent, port=_port)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=_port)
