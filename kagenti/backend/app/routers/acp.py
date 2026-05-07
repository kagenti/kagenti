"""
ACP (Agent Client Protocol) WebSocket endpoint.

Implements JSON-RPC 2.0 over WebSocket for ACP clients (IDEs, DAM/Humr,
CLI tools). Bridges to A2A agents via the ACPBridge service.
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.acp_bridge import ACPBridge

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/acp", tags=["acp"])

_bridge = ACPBridge()

JSON_RPC_INVALID_REQUEST = -32600
JSON_RPC_METHOD_NOT_FOUND = -32601
JSON_RPC_INTERNAL_ERROR = -32603
JSON_RPC_PARSE_ERROR = -32700


@router.websocket("/ws/{namespace}/{agent_name}")
async def acp_websocket(websocket: WebSocket, namespace: str, agent_name: str):
    await websocket.accept()
    logger.info("ACP WebSocket connected: %s/%s", namespace, agent_name)

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
            except Exception as e:
                logger.exception("ACP dispatch error: %s", e)
                await _send_error(websocket, rpc_id, JSON_RPC_INTERNAL_ERROR, str(e))

    except WebSocketDisconnect:
        logger.info("ACP WebSocket disconnected: %s/%s", namespace, agent_name)


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
        session = _bridge.create_session(namespace, agent_name, cwd=cwd)
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

        async for update in _bridge.prompt(session_id, text):
            await ws.send_text(json.dumps(update))

        await _send_result(ws, rpc_id, {"stopReason": "end_turn"})

    elif method == "session/close":
        session_id = params.get("sessionId", "")
        ok = _bridge.close_session(session_id)
        await _send_result(ws, rpc_id, {"closed": ok})

    elif method == "session/list":
        sessions = _bridge.list_sessions(namespace, agent_name)
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
        session = _bridge.get_session(session_id)
        if session and not session.closed:
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
