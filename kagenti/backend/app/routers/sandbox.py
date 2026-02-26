# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Sandbox sessions API endpoints.

Provides read-only access to sandbox agent sessions stored in per-namespace
PostgreSQL databases. Session data is managed by the A2A SDK's DatabaseTaskStore
(table: 'tasks') — the backend only reads from it for UI purposes.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.session_db import get_session_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TaskSummary(BaseModel):
    """Lightweight task/session representation for list views."""

    id: str
    context_id: str
    kind: str
    status: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None


class TaskDetail(TaskSummary):
    """Full task with artifacts and history."""

    artifacts: Optional[List[Dict[str, Any]]] = None
    history: Optional[List[Dict[str, Any]]] = None


class TaskListResponse(BaseModel):
    """Paginated list of tasks/sessions."""

    items: List[TaskSummary]
    total: int
    limit: int
    offset: int


class HistoryPage(BaseModel):
    """Paginated slice of session history messages."""

    messages: List[Dict[str, Any]]
    total: int
    has_more: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_field(value: Any) -> Any:
    """Parse a JSON field that may be a string or already a dict/list."""
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_summary(row: dict) -> TaskSummary:
    """Convert an asyncpg Record (as dict) to a TaskSummary."""
    data = dict(row)
    data["status"] = _parse_json_field(data.get("status"))
    data["metadata"] = _parse_json_field(data.get("metadata"))
    return TaskSummary(**data)


def _row_to_detail(row: dict) -> TaskDetail:
    """Convert an asyncpg Record (as dict) to a TaskDetail."""
    data = dict(row)
    data["status"] = _parse_json_field(data.get("status"))
    data["metadata"] = _parse_json_field(data.get("metadata"))
    data["artifacts"] = _parse_json_field(data.get("artifacts"))
    data["history"] = _parse_json_field(data.get("history"))
    return TaskDetail(**data)


# ---------------------------------------------------------------------------
# Endpoints — reading from A2A SDK's 'tasks' table
# ---------------------------------------------------------------------------


@router.get("/{namespace}/sessions", response_model=TaskListResponse)
async def list_sessions(
    namespace: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None, description="Search by context_id"),
):
    """List sessions (tasks) with pagination and optional search."""
    pool = await get_session_pool(namespace)

    conditions: List[str] = []
    args: List[Any] = []
    idx = 1

    if search:
        conditions.append(f"context_id ILIKE ${idx}")
        args.append(f"%{search}%")
        idx += 1

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM tasks {where}", *args)

        rows = await conn.fetch(
            f"SELECT id, context_id, kind, status, metadata"
            f" FROM tasks {where}"
            f" ORDER BY COALESCE((status::json->>'timestamp')::text, id::text) DESC"
            f" LIMIT ${idx} OFFSET ${idx + 1}",
            *args,
            limit,
            offset,
        )

    items = [_row_to_summary(r) for r in rows]
    return TaskListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{namespace}/sessions/{context_id}", response_model=TaskDetail)
async def get_session(namespace: str, context_id: str):
    """Get a task/session by context_id with full history and artifacts.

    If multiple tasks share the same context_id (e.g. retries), returns
    the latest one (highest id).
    """
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
            context_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

    return _row_to_detail(row)


@router.get(
    "/{namespace}/sessions/{context_id}/history",
    response_model=HistoryPage,
)
async def get_session_history(
    namespace: str,
    context_id: str,
    limit: int = Query(default=30, ge=1, le=200),
    before: Optional[int] = Query(
        default=None,
        description="Return messages before this index (for reverse pagination). "
        "Omit to get the most recent messages.",
    ),
):
    """Return a paginated slice of session history.

    Messages are ordered oldest-first in the DB. We serve them in reverse
    (newest-first) so the client can implement reverse infinite scroll:
    load the latest page, then fetch progressively older pages on scroll-up.

    Intermediate graph-event dumps (``assistant: {...}``, ``tools: {...}``)
    are filtered out server-side so the client receives only meaningful
    user/agent messages.
    """
    import re

    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT history, artifacts FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
            context_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

    raw_history: list = _parse_json_field(row["history"]) or []

    # The A2A agent stores graph event dumps in history (e.g. "assistant: {...}",
    # "tools: {...}") — these are not user-readable.  The actual final agent
    # responses live in the *artifacts* array.  Build a conversation view by
    # pairing each user message with the corresponding artifact text.
    artifacts: list = _parse_json_field(row.get("artifacts")) or []
    artifact_texts: List[str] = []
    for art in artifacts if isinstance(artifacts, list) else []:
        for part in art.get("parts") or []:
            if part.get("text"):
                artifact_texts.append(part["text"])

    filtered: List[Dict[str, Any]] = []
    user_idx = 0
    for msg in raw_history:
        if msg.get("role") == "user":
            filtered.append(msg)
            # Pair with the corresponding artifact (agent response)
            if user_idx < len(artifact_texts):
                filtered.append(
                    {
                        "role": "agent",
                        "parts": [{"kind": "text", "text": artifact_texts[user_idx]}],
                    }
                )
            user_idx += 1

    total = len(filtered)

    # Reverse pagination: slice from the end
    if before is not None:
        end_idx = max(before, 0)
    else:
        end_idx = total
    start_idx = max(end_idx - limit, 0)

    page = filtered[start_idx:end_idx]
    has_more = start_idx > 0

    # Add index to each message so the client can request the next page
    for i, msg in enumerate(page):
        msg["_index"] = start_idx + i

    return HistoryPage(messages=page, total=total, has_more=has_more)


@router.delete("/{namespace}/sessions/{context_id}", status_code=204)
async def delete_session(namespace: str, context_id: str):
    """Delete a task/session by context_id."""
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM tasks WHERE context_id = $1", context_id)

    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Session not found")

    return None


class RenameRequest(BaseModel):
    title: str


@router.put("/{namespace}/sessions/{context_id}/rename")
async def rename_session(namespace: str, context_id: str, request: RenameRequest):
    """Set or clear a custom session title.

    Pass an empty title to revert to the auto-generated default (first message).
    """
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT metadata, history FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
            context_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

        meta = _parse_json_field(row["metadata"]) or {}

        if request.title.strip():
            meta["title"] = request.title.strip()[:120]
        else:
            # Revert to default: first user message
            history = _parse_json_field(row["history"]) or []
            first_msg = next(
                (
                    m
                    for m in history
                    if m.get("role") == "user" and m.get("parts") and m["parts"][0].get("text")
                ),
                None,
            )
            if first_msg:
                meta["title"] = first_msg["parts"][0]["text"][:80].replace("\n", " ")
            else:
                meta.pop("title", None)

        await conn.execute(
            "UPDATE tasks SET metadata = $1::json WHERE context_id = $2",
            json.dumps(meta),
            context_id,
        )

    return {"title": meta.get("title", "")}


@router.post(
    "/{namespace}/sessions/{context_id}/kill",
    response_model=TaskDetail,
)
async def kill_session(namespace: str, context_id: str):
    """Mark a task as canceled by updating its status JSON."""
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1", context_id
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # Update the status JSON to set state to 'canceled'
        status = _parse_json_field(row["status"])
        if isinstance(status, dict):
            state = status.get("state", {})
            if isinstance(state, dict):
                state["state"] = "canceled"
            else:
                status["state"] = "canceled"
        else:
            status = {"state": "canceled"}

        await conn.execute(
            "UPDATE tasks SET status = $1::json WHERE context_id = $2",
            json.dumps(status),
            context_id,
        )

        # Re-fetch updated row
        row = await conn.fetchrow(
            "SELECT * FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1", context_id
        )

    return _row_to_detail(row)


# ---------------------------------------------------------------------------
# TTL cleanup — mark stale submitted tasks as failed
# ---------------------------------------------------------------------------


class CleanupResponse(BaseModel):
    """Result of a stale-session cleanup run."""

    cleaned: int


@router.post("/{namespace}/cleanup", response_model=CleanupResponse)
async def cleanup_stale_sessions(
    namespace: str,
    ttl_minutes: int = Query(default=5, ge=1, description="Age threshold in minutes"),
):
    """Mark stale *submitted* tasks as failed.

    Scans the ``tasks`` table for rows whose status JSON contains a state of
    ``submitted`` and whose status timestamp is older than *ttl_minutes*
    minutes ago (or has no timestamp at all).  Each matching task is updated
    to state ``failed`` with the message ``"Agent timeout"``.
    """
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        # Fetch all tasks that are still in "submitted" state.
        rows = await conn.fetch(
            "SELECT id, context_id, status FROM tasks WHERE status::text ILIKE '%submitted%'"
        )

        if not rows:
            return CleanupResponse(cleaned=0)

        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
        cleaned = 0

        for row in rows:
            status = _parse_json_field(row["status"])
            if not isinstance(status, dict):
                continue

            # Determine the current state — handle both flat and nested shapes.
            state_value = status.get("state", {})
            current_state = (
                state_value.get("state") if isinstance(state_value, dict) else state_value
            )
            if current_state != "submitted":
                continue

            # Check timestamp: if present, skip tasks that are still fresh.
            ts_str = status.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts > cutoff:
                        continue  # still within TTL
                except (ValueError, TypeError):
                    pass  # unparseable timestamp — treat as stale

            # Mark as failed.
            if isinstance(state_value, dict):
                state_value["state"] = "failed"
            else:
                status["state"] = "failed"
            status["message"] = {
                "role": "agent",
                "parts": [{"kind": "text", "text": "Agent timeout"}],
            }

            await conn.execute(
                "UPDATE tasks SET status = $1::json WHERE id = $2",
                json.dumps(status),
                row["id"],
            )
            cleaned += 1
            logger.info(
                "Cleanup: marked task %s (context_id=%s) as failed (agent timeout)",
                row["id"],
                row["context_id"],
            )

    return CleanupResponse(cleaned=cleaned)


# ---------------------------------------------------------------------------
# Chat proxy — forwards A2A messages to sandbox agents on port 8000
# ---------------------------------------------------------------------------


class SandboxChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    agent_name: str = "sandbox-legion"


@router.post("/{namespace}/chat")
async def chat_send(namespace: str, request: SandboxChatRequest):
    """Send a message to a sandbox agent via A2A JSON-RPC (non-streaming).

    Proxies the message to the agent's in-cluster service on port 8000.
    Returns the complete response (no SSE streaming).
    """
    agent_url = f"http://{request.agent_name}.{namespace}.svc.cluster.local:8000"
    context_id = request.session_id or uuid4().hex[:36]

    a2a_msg = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": uuid4().hex,
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": request.message}],
                "messageId": uuid4().hex,
                "contextId": context_id,
            }
        },
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(f"{agent_url}/", json=a2a_msg)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Agent error: {e}")

    result = data.get("result", {})
    if "error" in data:
        raise HTTPException(502, f"A2A error: {data['error']}")

    # Extract text from artifacts — only the final human-readable content
    text = ""
    artifacts = result.get("artifacts", [])
    if artifacts:
        for artifact in artifacts:
            for part in artifact.get("parts", []):
                if "text" in part:
                    text += part["text"]

    # Guard: if the agent serialized a list of content blocks (e.g. from a
    # tool-calling model), extract only the text portions.
    if text.startswith("[{") and "'type': 'text'" in text:
        try:
            import ast

            blocks = ast.literal_eval(text)
            if isinstance(blocks, list):
                text = "\n".join(
                    b.get("text", "")
                    for b in blocks
                    if isinstance(b, dict) and b.get("type") == "text"
                )
        except (ValueError, SyntaxError):
            pass  # keep original text

    # Auto-set session title from first message (truncated to 80 chars)
    final_context_id = result.get("contextId", context_id)
    try:
        pool = await get_session_pool(namespace)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT metadata FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
                final_context_id,
            )
            if row:
                meta = _parse_json_field(row["metadata"]) or {}
                if not meta.get("title"):
                    title = request.message[:80].replace("\n", " ")
                    meta["title"] = title
                    await conn.execute(
                        "UPDATE tasks SET metadata = $1::json WHERE context_id = $2",
                        json.dumps(meta),
                        final_context_id,
                    )
    except Exception:
        pass  # non-critical

    return {
        "content": text,
        "context_id": final_context_id,
        "task_id": result.get("id"),
        "status": result.get("status", {}),
    }
