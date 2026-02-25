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

from fastapi import APIRouter, HTTPException, Query
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
            f" ORDER BY id DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *args,
            limit,
            offset,
        )

    items = [_row_to_summary(r) for r in rows]
    return TaskListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{namespace}/sessions/{context_id}", response_model=TaskDetail)
async def get_session(namespace: str, context_id: str):
    """Get a task/session by context_id with full history and artifacts."""
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tasks WHERE context_id = $1", context_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

    return _row_to_detail(row)


@router.delete("/{namespace}/sessions/{context_id}", status_code=204)
async def delete_session(namespace: str, context_id: str):
    """Delete a task/session by context_id."""
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM tasks WHERE context_id = $1", context_id)

    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Session not found")

    return None


@router.post(
    "/{namespace}/sessions/{context_id}/kill",
    response_model=TaskDetail,
)
async def kill_session(namespace: str, context_id: str):
    """Mark a task as canceled by updating its status JSON."""
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tasks WHERE context_id = $1", context_id)
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
        row = await conn.fetchrow("SELECT * FROM tasks WHERE context_id = $1", context_id)

    return _row_to_detail(row)
