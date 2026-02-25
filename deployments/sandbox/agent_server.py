"""
Kagenti Sandbox Agent Server — litellm-powered agent with skills (Phase 4, C10+C11)

A simple agent server that:
1. Loads CLAUDE.md + .claude/skills/ from /workspace via SkillsLoader
2. Uses litellm for model-agnostic LLM access (any model via LLM_MODEL env var)
3. Exposes an HTTP endpoint for agent interaction

Environment variables:
  LLM_MODEL     - litellm model string (default: openai/gpt-4o-mini)
  LLM_API_KEY   - API key for the LLM provider
  LLM_BASE_URL  - Custom base URL (for self-hosted models)
  WORKSPACE_DIR - Repo workspace path (default: /workspace)
  PORT          - Server port (default: 8080)

Usage:
  LLM_MODEL=anthropic/claude-sonnet-4-20250514 python3 agent_server.py
  LLM_MODEL=openai/gpt-4o python3 agent_server.py
  LLM_MODEL=ollama/llama3 LLM_BASE_URL=http://ollama:11434 python3 agent_server.py
"""

import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

# Add /tmp/pip-packages to path for sandbox-installed packages
sys.path.insert(0, "/tmp/pip-packages")

from skills_loader import SkillsLoader


class AgentHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for agent interaction."""

    loader: SkillsLoader = None  # Set by server setup
    model: str = "openai/gpt-4o-mini"

    def do_POST(self):
        """Handle agent query."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
            user_message = data.get("message", "")
            skill_name = data.get("skill")
        except json.JSONDecodeError:
            user_message = body
            skill_name = None

        # Build system prompt
        if skill_name:
            system_prompt = self.loader.build_full_prompt_with_skill(skill_name)
        else:
            system_prompt = self.loader.build_system_prompt()

        # Call LLM via litellm
        try:
            import litellm

            response = litellm.completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                timeout=120,
            )
            reply = response.choices[0].message.content

            result = {
                "reply": reply,
                "model": self.model,
                "skills_loaded": len(self.loader.skills),
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                },
            }
            self._send_json(200, result)

        except ImportError:
            self._send_json(
                500, {"error": "litellm not installed. Run: pip install litellm"}
            )
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_GET(self):
        """Health check and info endpoint."""
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        elif self.path == "/info":
            self._send_json(
                200,
                {
                    "model": self.model,
                    "workspace": str(self.loader.workspace),
                    "claude_md": self.loader.claude_md is not None,
                    "skills": self.loader.list_skills(),
                    "skills_count": len(self.loader.skills),
                },
            )
        else:
            self._send_json(404, {"error": "Not found. Use /health, /info, or POST /"})

    def _send_json(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress default logging to stderr."""
        pass


def main():
    workspace = os.environ.get("WORKSPACE_DIR", "/workspace")
    model = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")
    port = int(os.environ.get("PORT", "8080"))

    # Load skills
    loader = SkillsLoader(workspace)
    print(f"Workspace: {workspace}")
    print(f"CLAUDE.md: {'loaded' if loader.claude_md else 'not found'}")
    print(
        f"Skills: {len(loader.skills)} loaded ({', '.join(loader.list_skills()[:5])}{'...' if len(loader.skills) > 5 else ''})"
    )
    print(f"Model: {model}")

    # Configure handler
    AgentHandler.loader = loader
    AgentHandler.model = model

    # Start server
    server = HTTPServer(("0.0.0.0", port), AgentHandler)
    print(f"Agent server listening on :{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
