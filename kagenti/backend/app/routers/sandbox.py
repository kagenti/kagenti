# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Sandbox sessions API endpoints.

Provides CRUD operations for sandbox agent sessions stored in per-namespace
PostgreSQL databases.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.session_db import ensure_schema, get_session_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SessionMessage(BaseModel):
    """A single message within a session."""

    id: int
    context_id: str
    role: str
    content: str
    actor_user: Optional[str] = None
    created_at: datetime


class SessionSummary(BaseModel):
    """Lightweight session representation for list views."""

    context_id: str
    parent_id: Optional[str] = None
    owner_user: str
    owner_group: str
    title: Optional[str] = None
    status: str
    agent_name: str
    config: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class SessionDetail(SessionSummary):
    """Full session with children and messages."""

    children: List[SessionSummary] = []
    messages: List[SessionMessage] = []


class SessionListResponse(BaseModel):
    """Paginated list of sessions."""

    items: List[SessionSummary]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_summary(row: dict) -> SessionSummary:
    """Convert an asyncpg Record (as dict) to a SessionSummary."""
    data = dict(row)
    # config is stored as JSONB; asyncpg returns it as a str or dict
    if isinstance(data.get("config"), str):
        data["config"] = json.loads(data["config"])
    return SessionSummary(**data)


def _row_to_message(row: dict) -> SessionMessage:
    return SessionMessage(**dict(row))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{namespace}/sessions", response_model=SessionListResponse)
async def list_sessions(
    namespace: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = Query(default=None, description="Filter by session status"),
    search: Optional[str] = Query(default=None, description="Search title or context_id"),
):
    """List sessions with pagination, optional status filter, and text search."""
    await ensure_schema(namespace)
    pool = await get_session_pool(namespace)

    # Build dynamic WHERE clause
    conditions: List[str] = []
    args: List[Any] = []
    idx = 1

    if status:
        conditions.append(f"status = ${idx}")
        args.append(status)
        idx += 1

    if search:
        conditions.append(f"(title ILIKE ${idx} OR context_id ILIKE ${idx})")
        args.append(f"%{search}%")
        idx += 1

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM sessions {where}", *args)

        rows = await conn.fetch(
            f"SELECT * FROM sessions {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *args,
            limit,
            offset,
        )

    items = [_row_to_summary(r) for r in rows]
    return SessionListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{namespace}/sessions/{context_id}", response_model=SessionDetail)
async def get_session(namespace: str, context_id: str):
    """Get a session with its children and messages."""
    await ensure_schema(namespace)
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM sessions WHERE context_id = $1", context_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

        children_rows = await conn.fetch(
            "SELECT * FROM sessions WHERE parent_id = $1 ORDER BY created_at", context_id
        )

        message_rows = await conn.fetch(
            "SELECT * FROM session_messages WHERE context_id = $1 ORDER BY created_at",
            context_id,
        )

    detail = SessionDetail(
        **_row_to_summary(row).model_dump(),
        children=[_row_to_summary(r) for r in children_rows],
        messages=[_row_to_message(r) for r in message_rows],
    )
    return detail


@router.delete("/{namespace}/sessions/{context_id}", status_code=204)
async def delete_session(namespace: str, context_id: str):
    """Delete a session and cascade-delete its messages."""
    await ensure_schema(namespace)
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM sessions WHERE context_id = $1", context_id)

    # result is e.g. "DELETE 1" or "DELETE 0"
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Session not found")

    return None


@router.post("/{namespace}/sessions/{context_id}/kill", response_model=SessionSummary)
async def kill_session(namespace: str, context_id: str):
    """Mark a session as killed (set status='killed', completed_at=NOW())."""
    await ensure_schema(namespace)
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE sessions SET status = 'killed', completed_at = NOW(), updated_at = NOW() "
            "WHERE context_id = $1 RETURNING *",
            context_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return _row_to_summary(row)
