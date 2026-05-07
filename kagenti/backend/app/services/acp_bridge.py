"""
ACP-to-A2A Bridge Service.

Translates between ACP (Agent Client Protocol) JSON-RPC 2.0 messages
and the existing A2A protocol endpoints in chat.py.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import uuid4

import httpx

from app.utils.routes import resolve_agent_url
from app.services.kubernetes import get_kubernetes_service

logger = logging.getLogger(__name__)


ACP_PROTOCOL_VERSION = 1


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

    def server_capabilities(self) -> dict:
        return {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "agentCapabilities": {
                "streaming": True,
                "tools": False,
                "loadSession": True,
            },
        }

    def create_session(self, namespace: str, agent_name: str, cwd: str = "") -> ACPSession:
        session = ACPSession(
            session_id=uuid4().hex,
            agent_name=agent_name,
            namespace=namespace,
        )
        self._sessions[session.session_id] = session
        logger.info("ACP session %s created for %s/%s", session.session_id, namespace, agent_name)
        return session

    def get_session(self, session_id: str) -> ACPSession | None:
        return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session:
            session.closed = True
            return True
        return False

    def list_sessions(self, namespace: str = "", agent_name: str = "") -> list[ACPSession]:
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
        """Send a prompt via A2A message/stream and yield ACP update notifications."""
        session = self._sessions.get(session_id)
        if not session:
            yield _acp_error("Session not found", session_id=session_id)
            return

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
            "method": "message/stream",
            "params": params,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    agent_url,
                    json=payload,
                    headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
                ) as response:
                    response.raise_for_status()
                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while "\n\n" in buffer:
                            event_text, buffer = buffer.split("\n\n", 1)
                            acp_update = _sse_to_acp_update(event_text, session)
                            if acp_update:
                                yield acp_update

                    if buffer.strip():
                        acp_update = _sse_to_acp_update(buffer, session)
                        if acp_update:
                            yield acp_update

        except httpx.HTTPStatusError as e:
            logger.error("A2A HTTP error: %s", e)
            yield _acp_error(f"Agent returned {e.response.status_code}", session_id=session_id)
        except httpx.RequestError as e:
            logger.error("A2A connection error: %s", e)
            yield _acp_error(f"Cannot reach agent: {e}", session_id=session_id)

        yield {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": session_id,
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
