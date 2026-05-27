"""
ACP (Agent Client Protocol) WebSocket endpoint.

Implements JSON-RPC 2.0 over WebSocket for ACP clients (IDEs, DAM/Humr,
CLI tools). Bridges to A2A agents via the ACPBridge service.

Auth: When ENABLE_AUTH is true, the WebSocket upgrade requires a valid JWT
token passed as the `token` query parameter. The token is validated using
the same Keycloak JWKS as the REST endpoints.
"""

import json
import logging
import re
from uuid import uuid4

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.services.acp_bridge import ACPBridge

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/acp", tags=["acp"])

_bridge = ACPBridge()

JSON_RPC_INVALID_REQUEST = -32600
JSON_RPC_METHOD_NOT_FOUND = -32601
JSON_RPC_INTERNAL_ERROR = -32603
JSON_RPC_PARSE_ERROR = -32700

_K8S_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


@router.websocket("/ws/{namespace}/{agent_name}")
async def acp_websocket(
    websocket: WebSocket,
    namespace: str,
    agent_name: str,
    token: str = Query(default=""),
):
    if (
        not _K8S_NAME.match(namespace)
        or not _K8S_NAME.match(agent_name)
        or len(namespace) > 63
        or len(agent_name) > 63
    ):
        logger.warning(
            "ACP rejected invalid K8s name: ns_len=%d agent_len=%d", len(namespace), len(agent_name)
        )
        await websocket.close(code=4400, reason="Invalid namespace or agent_name")
        return

    if settings.enable_auth:
        if not token:
            await websocket.close(code=4001, reason="Authentication required: pass ?token=<jwt>")
            return
        try:
            from app.core.auth import validate_token

            token_data = await validate_token(token)
            # Verify the token's audience includes this namespace (tenant)
            aud = token_data.raw_token.get("aud", [])
            if isinstance(aud, str):
                aud = [aud]
            azp = token_data.raw_token.get("azp", "")
            allowed = {*aud, azp} if azp else set(aud)
            if allowed and namespace not in allowed and "account" not in allowed:
                logger.warning(
                    "ACP namespace mismatch: user=%s requested=%s allowed=%s",
                    token_data.username,
                    namespace,
                    sorted(allowed),
                )
                await websocket.close(code=4003, reason="Access denied for this namespace")
                return
        except Exception:
            await websocket.close(code=4003, reason="Invalid or expired token")
            return

    conn_id = uuid4().hex[:8]
    await websocket.accept()
    logger.info("ACP WebSocket connected (conn=%s)", conn_id)

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, None, JSON_RPC_PARSE_ERROR, "Parse error")
                continue

            rpc_id = msg.get("id")
            method = msg.get("method", "")
            params = msg.get("params", {})

            if not method:
                await _send_error(websocket, rpc_id, JSON_RPC_INVALID_REQUEST, "Missing method")
                continue

            try:
                await _dispatch(websocket, rpc_id, method, params, namespace, agent_name)
            except Exception:
                logger.exception("ACP dispatch error (conn=%s)", conn_id)
                await _send_error(websocket, rpc_id, JSON_RPC_INTERNAL_ERROR, "Internal error")

    except WebSocketDisconnect:
        logger.info("ACP WebSocket disconnected (conn=%s)", conn_id)
    finally:
        cleaned = await _bridge.cleanup_sessions(namespace, agent_name)
        if cleaned:
            logger.info("Cleaned up %d sessions (conn=%s)", cleaned, conn_id)


async def _dispatch(
    ws: WebSocket,
    rpc_id: str | None,
    method: str,
    params: dict,
    namespace: str,
    agent_name: str,
):
    if method == "initialize":
        caps = _bridge.server_capabilities()
        await _send_result(ws, rpc_id, caps)

    elif method == "authenticate":
        await _send_result(ws, rpc_id, {"authenticated": True})

    elif method == "session/new":
        cwd = params.get("cwd", "")
        session = await _bridge.create_session(namespace, agent_name, cwd=cwd)
        await _send_result(ws, rpc_id, {"sessionId": session.session_id})

    elif method == "session/prompt":
        session_id = params.get("sessionId", "")
        prompt_parts = params.get("prompt", [])
        text = ""
        for part in prompt_parts:
            if isinstance(part, dict) and part.get("type") == "text":
                text += part.get("text", "")
        if not text:
            text = params.get("text", "")

        if not session_id or not text:
            await _send_error(ws, rpc_id, JSON_RPC_INVALID_REQUEST, "sessionId and text required")
            return

        session = await _bridge.get_session(session_id)
        if not session or session.namespace != namespace:
            await _send_error(ws, rpc_id, JSON_RPC_INVALID_REQUEST, "Session not found")
            return

        async for update in _bridge.prompt(session_id, text):
            await ws.send_text(json.dumps(update))

        await _send_result(ws, rpc_id, {"stopReason": "end_turn"})

    elif method == "session/close":
        session_id = params.get("sessionId", "")
        session = await _bridge.get_session(session_id)
        if not session or session.namespace != namespace:
            await _send_result(ws, rpc_id, {"closed": False})
            return
        ok = await _bridge.close_session(session_id)
        await _send_result(ws, rpc_id, {"closed": ok})

    elif method == "session/list":
        sessions = await _bridge.list_sessions(namespace, agent_name)
        await _send_result(
            ws,
            rpc_id,
            {
                "sessions": [
                    {
                        "sessionId": s.session_id,
                        "agentName": s.agent_name,
                        "createdAt": s.created_at,
                    }
                    for s in sessions
                ]
            },
        )

    elif method == "session/resume":
        session_id = params.get("sessionId", "")
        session = await _bridge.get_session(session_id)
        if session and not session.closed and session.namespace == namespace:
            await _send_result(ws, rpc_id, {"sessionId": session.session_id, "resumed": True})
        else:
            await _send_error(ws, rpc_id, JSON_RPC_INVALID_REQUEST, "Session not found or closed")

    elif method == "session/request_permission":
        # PoC: auto-approve all permission requests
        await _send_result(
            ws,
            rpc_id,
            {
                "outcome": "selected",
                "selectedOptionId": "allow_once",
            },
        )

    else:
        await _send_error(ws, rpc_id, JSON_RPC_METHOD_NOT_FOUND, f"Unknown method: {method}")


async def _send_result(ws: WebSocket, rpc_id: str | None, result: dict):
    await ws.send_text(json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result}))


async def _send_error(ws: WebSocket, rpc_id: str | None, code: int, message: str):
    await ws.send_text(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": code, "message": message},
            }
        )
    )
