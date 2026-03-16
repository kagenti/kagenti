# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Paginated event retrieval API endpoints.

Provides read access to per-event records stored in the events table.
Events are persisted during SSE streaming (one row per loop event) and
retrieved here for paginated history loading.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import (
    get_required_user,
    require_roles,
    TokenData,
    ROLE_VIEWER,
)
from app.services.session_db import get_session_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["events"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class EventRecord(BaseModel):
    """Single persisted event."""

    id: int
    context_id: str
    task_id: str
    event_index: int
    event_type: str
    event_category: Optional[str] = None
    langgraph_node: Optional[str] = None
    payload: Dict[str, Any]
    created_at: Optional[str] = None


class PaginatedEvents(BaseModel):
    """Paginated list of events."""

    events: List[EventRecord]
    has_more: bool
    next_index: int


class TaskEventSummary(BaseModel):
    """Summary of a task for paginated task listing."""

    task_id: str
    user_message: str
    status: str
    step_count: int
    created_at: Optional[str] = None
    agent_name: str


class PaginatedTasks(BaseModel):
    """Paginated list of task summaries."""

    tasks: List[TaskEventSummary]
    has_more: bool


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse_json_field(value: Any) -> Any:
    """Parse a JSON field that may be a string or already a dict/list."""
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{namespace}/events",
    response_model=PaginatedEvents,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_events(
    namespace: str,
    context_id: str = Query(..., description="Session context ID"),
    task_id: Optional[str] = Query(default=None, description="Filter by task ID"),
    from_index: int = Query(default=0, ge=0, description="Start from event_index"),
    limit: int = Query(default=100, ge=1, le=500, description="Max events to return"),
    user: TokenData = Depends(get_required_user),
):
    """Get paginated events for a session/task.

    Returns events ordered by event_index ascending, starting from from_index.
    """
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        if task_id:
            rows = await conn.fetch(
                "SELECT id, context_id, task_id, event_index, event_type,"
                "       event_category, langgraph_node, payload, created_at"
                " FROM events"
                " WHERE context_id = $1 AND task_id = $2 AND event_index >= $3"
                " ORDER BY event_index ASC"
                " LIMIT $4",
                context_id,
                task_id,
                from_index,
                limit + 1,  # fetch one extra to detect has_more
            )
        else:
            rows = await conn.fetch(
                "SELECT id, context_id, task_id, event_index, event_type,"
                "       event_category, langgraph_node, payload, created_at"
                " FROM events"
                " WHERE context_id = $1 AND event_index >= $2"
                " ORDER BY event_index ASC"
                " LIMIT $3",
                context_id,
                from_index,
                limit + 1,
            )

    has_more = len(rows) > limit
    result_rows = rows[:limit]

    events = []
    for r in result_rows:
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        events.append(
            EventRecord(
                id=r["id"],
                context_id=r["context_id"],
                task_id=r["task_id"],
                event_index=r["event_index"],
                event_type=r["event_type"],
                event_category=r["event_category"],
                langgraph_node=r["langgraph_node"],
                payload=payload,
                created_at=str(r["created_at"]) if r["created_at"] else None,
            )
        )

    next_index = result_rows[-1]["event_index"] + 1 if result_rows else from_index

    return PaginatedEvents(events=events, has_more=has_more, next_index=next_index)


@router.get(
    "/{namespace}/tasks/paginated",
    response_model=PaginatedTasks,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_paginated_tasks(
    namespace: str,
    context_id: str = Query(..., description="Session context ID"),
    limit: int = Query(default=5, ge=1, le=50, description="Max tasks to return"),
    before_id: Optional[str] = Query(
        default=None, description="Return tasks created before this task_id"
    ),
    user: TokenData = Depends(get_required_user),
):
    """Get paginated task summaries for a session.

    Returns tasks ordered by creation time descending (newest first).
    Each task includes the user message, status, step count, and agent name.
    """
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        # Build query based on whether before_id is provided
        if before_id:
            # Get the created_at of the before_id task for cursor pagination
            before_row = await conn.fetchrow(
                "SELECT id FROM tasks WHERE id = $1 AND context_id = $2",
                before_id,
                context_id,
            )
            if not before_row:
                raise HTTPException(404, f"Task {before_id} not found")

            rows = await conn.fetch(
                "SELECT id, context_id, status, metadata, history"
                " FROM tasks"
                " WHERE context_id = $1 AND id < $2"
                " ORDER BY id DESC"
                " LIMIT $3",
                context_id,
                before_id,
                limit + 1,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, context_id, status, metadata, history"
                " FROM tasks"
                " WHERE context_id = $1"
                " ORDER BY id DESC"
                " LIMIT $2",
                context_id,
                limit + 1,
            )

        has_more = len(rows) > limit
        result_rows = rows[:limit]

        tasks = []
        for r in result_rows:
            meta = _parse_json_field(r["metadata"]) or {}
            status = _parse_json_field(r["status"]) or {}
            history = _parse_json_field(r["history"]) or []

            # Extract user message from history
            user_message = ""
            for h in history:
                if isinstance(h, dict) and h.get("role") == "user":
                    parts = h.get("parts", [])
                    for p in parts:
                        if isinstance(p, dict) and p.get("text"):
                            user_message = p["text"]
                            break
                    if user_message:
                        break
            if not user_message:
                user_message = meta.get("title", "")

            # Count events (steps) from events table or loop_events in metadata
            loop_events = meta.get("loop_events", [])
            step_count = len(loop_events)

            # If events table has data, use that count instead
            try:
                evt_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM events WHERE task_id = $1",
                    r["id"],
                )
                if evt_count and evt_count > 0:
                    step_count = evt_count
            except Exception:
                pass  # events table may not exist yet

            tasks.append(
                TaskEventSummary(
                    task_id=r["id"],
                    user_message=user_message[:200],
                    status=status.get("state", "unknown"),
                    step_count=step_count,
                    created_at=None,  # tasks table doesn't have created_at column
                    agent_name=meta.get("agent_name", ""),
                )
            )

    return PaginatedTasks(tasks=tasks, has_more=has_more)
