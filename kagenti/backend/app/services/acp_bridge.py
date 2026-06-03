"""
ACP-to-A2A Bridge Service.

Translates between ACP (Agent Client Protocol) JSON-RPC 2.0 messages
and the existing A2A protocol endpoints in chat.py.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import uuid4

import httpx

from app.utils.routes import resolve_agent_url
from app.services.kubernetes import get_kubernetes_service
from app.services.openshell.gateway import get_openshell_client

logger = logging.getLogger(__name__)


ACP_PROTOCOL_VERSION = 1
A2A_STREAM_TIMEOUT = 120.0
SANDBOX_EXEC_TIMEOUT = 120

SANDBOX_AGENTS = {"openshell-claude", "openshell-opencode", "nemoclaw-hermes"}
NEMOCLAW_AGENTS = {"nemoclaw-openclaw"}

_SANDBOX_CLI: dict[str, list[str]] = {
    "nemoclaw-hermes": ["hermes", "chat", "-q"],
    "openshell-claude": ["claude", "--print", "--bare", "--model", "claude-sonnet-4-20250514"],
    "openshell-opencode": ["opencode", "run"],
}

_K8S_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass
class ACPSession:
    session_id: str
    agent_name: str
    namespace: str
    context_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    closed: bool = False


class ACPBridge:
    """Bridges ACP WebSocket sessions to A2A HTTP agents."""

    def __init__(self):
        self._sessions: dict[str, ACPSession] = {}
        self._lock = asyncio.Lock()

    def server_capabilities(self) -> dict:
        return {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "agentCapabilities": {
                "streaming": True,
                "tools": False,
                "loadSession": True,
            },
        }

    async def create_session(self, namespace: str, agent_name: str, cwd: str = "") -> ACPSession:
        session = ACPSession(
            session_id=uuid4().hex,
            agent_name=agent_name,
            namespace=namespace,
        )
        async with self._lock:
            self._sessions[session.session_id] = session
        logger.info("ACP session %s created", session.session_id)
        return session

    async def get_session(self, session_id: str) -> ACPSession | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def close_session(self, session_id: str) -> bool:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.closed = True
                return True
        return False

    async def cleanup_sessions(self, namespace: str, agent_name: str) -> int:
        """Remove all sessions for a namespace/agent pair (called on WebSocket disconnect)."""
        async with self._lock:
            to_remove = [
                sid
                for sid, s in self._sessions.items()
                if s.namespace == namespace and s.agent_name == agent_name and s.closed
            ]
            for sid in to_remove:
                del self._sessions[sid]
        return len(to_remove)

    async def list_sessions(self, namespace: str = "", agent_name: str = "") -> list[ACPSession]:
        async with self._lock:
            results = []
            for s in self._sessions.values():
                if s.closed:
                    continue
                if namespace and s.namespace != namespace:
                    continue
                if agent_name and s.agent_name != agent_name:
                    continue
                results.append(s)
        return results

    async def prompt(
        self,
        session_id: str,
        text: str,
    ) -> AsyncIterator[dict]:
        """Route prompt to the correct agent protocol and yield ACP updates."""
        async with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            yield _acp_error("Session not found", session_id=session_id)
            return

        if session.agent_name in SANDBOX_AGENTS:
            async for update in self._prompt_sandbox(session, text):
                yield update
        elif session.agent_name in NEMOCLAW_AGENTS:
            async for update in self._prompt_nemoclaw(session, text):
                yield update
        else:
            async for update in self._prompt_a2a(session, text):
                yield update

    async def _prompt_a2a(self, session: ACPSession, text: str) -> AsyncIterator[dict]:
        """Send prompt via A2A message/send to standard agents."""
        kube = get_kubernetes_service()
        agent_url = resolve_agent_url(session.agent_name, session.namespace, kube)

        params: dict = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
                "messageId": uuid4().hex,
            },
        }
        if session.context_id:
            params["contextId"] = session.context_id

        payload = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": "message/send",
            "params": params,
        }

        try:
            async with httpx.AsyncClient(timeout=A2A_STREAM_TIMEOUT) as client:
                response = await client.post(
                    agent_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                result = response.json()

                context_id = result.get("result", {}).get("contextId", "")
                if context_id and not session.context_id:
                    session.context_id = context_id

                resp_text = _extract_text_from_a2a(result)
                if resp_text:
                    yield {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": session.session_id,
                            "sessionUpdate": "agent_message_chunk",
                            "content": [{"type": "text", "text": resp_text}],
                        },
                    }

        except httpx.HTTPStatusError as e:
            logger.error("A2A HTTP error: %s", e)
            yield _acp_error("Agent request failed", session_id=session.session_id)
        except httpx.RequestError as e:
            logger.error("A2A connection error: %s", e)
            yield _acp_error("Cannot reach agent", session_id=session.session_id)

    async def _prompt_sandbox(self, session: ACPSession, text: str) -> AsyncIterator[dict]:
        """Send prompt to sandbox agent via OpenShell gateway ExecSandbox gRPC."""
        if not _K8S_NAME_RE.match(session.namespace) or not _K8S_NAME_RE.match(session.agent_name):
            yield _acp_error("Invalid namespace or agent_name", session_id=session.session_id)
            return

        cli_args = _SANDBOX_CLI.get(session.agent_name, ["echo", "unsupported agent"])
        cmd = ["timeout", "90", *cli_args, text]

        gateway = get_openshell_client()
        stdout_parts: list[str] = []

        logger.info(
            "Sandbox prompt via ExecSandbox",
            extra={
                "session_id": session.session_id,
                "agent_name": session.agent_name,
                "namespace": session.namespace,
                "cli": cli_args[0],
                "prompt_length": len(text),
            },
        )

        try:
            async for event_type, data in gateway.exec_sandbox(
                sandbox_id=session.agent_name,
                namespace=session.namespace,
                command=cmd,
                timeout_seconds=SANDBOX_EXEC_TIMEOUT,
            ):
                if event_type == "stdout":
                    stdout_parts.append(data.decode("utf-8", errors="replace"))
                elif event_type == "stderr":
                    logger.warning(
                        "Sandbox stderr",
                        extra={
                            "session_id": session.session_id,
                            "stderr": data.decode("utf-8", errors="replace")[:200],
                        },
                    )
                elif event_type == "exit":
                    if data != 0:
                        logger.warning(
                            "Sandbox non-zero exit",
                            extra={
                                "session_id": session.session_id,
                                "exit_code": data,
                            },
                        )

            output = "".join(stdout_parts).strip()
            if output:
                logger.info(
                    "Sandbox prompt completed",
                    extra={
                        "session_id": session.session_id,
                        "response_length": len(output),
                    },
                )
                yield {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": session.session_id,
                        "sessionUpdate": "agent_message_chunk",
                        "content": [{"type": "text", "text": output}],
                    },
                }
            else:
                logger.warning(
                    "Sandbox returned empty output",
                    extra={"session_id": session.session_id},
                )
                yield _acp_error(
                    "Sandbox exec returned empty output", session_id=session.session_id
                )
        except Exception as e:
            logger.error(
                "ExecSandbox failed",
                extra={
                    "session_id": session.session_id,
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            yield _acp_error("Sandbox execution failed", session_id=session.session_id)

    async def _prompt_nemoclaw(self, session: ACPSession, text: str) -> AsyncIterator[dict]:
        """Send prompt to NemoClaw agent via LiteLLM OpenAI-compat format."""
        litellm_url = f"http://litellm-model-proxy.{session.namespace}.svc.cluster.local:4000"

        try:
            async with httpx.AsyncClient(timeout=A2A_STREAM_TIMEOUT) as client:
                response = await client.post(
                    f"{litellm_url}/v1/chat/completions",
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": text}],
                        "max_tokens": 2048,
                    },
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                result = response.json()

                choices = result.get("choices", [])
                if choices:
                    resp_text = choices[0].get("message", {}).get("content", "")
                    if resp_text:
                        yield {
                            "jsonrpc": "2.0",
                            "method": "session/update",
                            "params": {
                                "sessionId": session.session_id,
                                "sessionUpdate": "agent_message_chunk",
                                "content": [{"type": "text", "text": resp_text}],
                            },
                        }

        except httpx.HTTPStatusError as e:
            logger.error("NemoClaw HTTP error: %s", e)
            yield _acp_error("Agent request failed", session_id=session.session_id)
        except httpx.RequestError as e:
            logger.error("NemoClaw connection error: %s", e)
            yield _acp_error("Cannot reach agent", session_id=session.session_id)

        yield {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": session.session_id,
                "sessionUpdate": "turn_complete",
                "stopReason": "end_turn",
            },
        }


def _sse_to_acp_update(event_text: str, session: ACPSession) -> dict | None:
    """Convert an SSE event into an ACP session/update notification."""
    import json

    data_line = ""
    for line in event_text.split("\n"):
        if line.startswith("data:"):
            data_line = line[5:].strip()

    if not data_line:
        return None

    try:
        event = json.loads(data_line)
    except json.JSONDecodeError:
        return {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": session.session_id,
                "sessionUpdate": "agent_message_chunk",
                "content": [{"type": "text", "text": data_line}],
            },
        }

    # Extract context_id from A2A response for session continuity
    context_id = event.get("result", {}).get("contextId", "")
    if context_id and not session.context_id:
        session.context_id = context_id

    text = _extract_text_from_a2a(event)
    if text:
        return {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": session.session_id,
                "sessionUpdate": "agent_message_chunk",
                "content": [{"type": "text", "text": text}],
            },
        }
    return None


def _extract_text_from_a2a(event: dict) -> str:
    """Extract text content from various A2A response shapes."""
    result = event.get("result", {})

    # Task-based response
    status = result.get("status", {})
    msg = status.get("message", {})
    parts = msg.get("parts", [])
    for part in parts:
        if isinstance(part, dict):
            if "text" in part:
                return part["text"]
            if "data" in part and isinstance(part["data"], str):
                return part["data"]

    # Artifact-based response
    artifacts = result.get("artifacts", [])
    for artifact in artifacts:
        for part in artifact.get("parts", []):
            if isinstance(part, dict) and "text" in part:
                return part["text"]

    return ""


def _acp_error(message: str, session_id: str = "") -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "sessionUpdate": "error",
            "error": {"message": message},
        },
    }
