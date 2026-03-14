# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Sandbox sessions API endpoints.

Provides read-only access to sandbox agent sessions stored in per-namespace
PostgreSQL databases. Session data is managed by the A2A SDK's DatabaseTaskStore
(table: 'tasks') — the backend only reads from it for UI purposes.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from app.core.auth import (
    get_required_user,
    require_roles,
    TokenData,
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
)
from app.services.session_db import get_session_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["sandbox"])

# Kubernetes name validation: lowercase alphanumeric + dashes, max 63 chars
_K8S_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


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
    loop_events: Optional[List[Dict[str, Any]]] = None
    task_state: Optional[str] = None
    last_updated: Optional[str] = None


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

    # Fix stale "working" status for sessions that completed but the
    # A2A SDK didn't update (e.g. client disconnect during streaming).
    status = data.get("status") or {}
    meta = data.get("metadata") or {}
    if isinstance(status, dict) and status.get("state") == "working":
        loop_events = meta.get("loop_events", []) if isinstance(meta, dict) else []
        has_reporter = any(
            e.get("type") == "reporter_output" for e in loop_events if isinstance(e, dict)
        )
        if has_reporter:
            status["state"] = "completed"

    return TaskSummary(**data)


def _row_to_detail(row: dict) -> TaskDetail:
    """Convert an asyncpg Record (as dict) to a TaskDetail."""
    data = dict(row)
    data["status"] = _parse_json_field(data.get("status"))
    data["metadata"] = _parse_json_field(data.get("metadata"))
    data["artifacts"] = _parse_json_field(data.get("artifacts"))
    data["history"] = _parse_json_field(data.get("history"))
    return TaskDetail(**data)


def _check_session_ownership(meta: Optional[Dict[str, Any]], user: TokenData, action: str) -> None:
    """Raise 403 if user is not the session owner (unless admin)."""
    if user.has_role(ROLE_ADMIN):
        return
    owner = (meta or {}).get("owner")
    if owner and owner != user.username:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot {action}: session owned by '{owner}'",
        )


class VisibilityRequest(BaseModel):
    visibility: str  # "private" or "namespace"


# ---------------------------------------------------------------------------
# Endpoints — reading from A2A SDK's 'tasks' table
# ---------------------------------------------------------------------------


@router.get(
    "/{namespace}/sessions",
    response_model=TaskListResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_sessions(
    namespace: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None, description="Search by context_id"),
    agent_name: Optional[str] = Query(default=None, description="Filter by agent name"),
    user: TokenData = Depends(get_required_user),
):
    """List sessions (tasks) with pagination and optional search.

    Visibility is role-based:
    - Admin: all sessions across all namespaces.
    - Operator: own sessions + sessions with visibility='namespace'.
    - Viewer: only own sessions.
    """
    pool = await get_session_pool(namespace)

    conditions: List[str] = []
    args: List[Any] = []
    idx = 1

    if search:
        conditions.append(f"context_id ILIKE ${idx}")
        args.append(f"%{search}%")
        idx += 1

    if agent_name:
        conditions.append(f"metadata::json->>'agent_name' = ${idx}")
        args.append(agent_name)
        idx += 1

    # Role-based visibility filtering
    if not user.has_role(ROLE_ADMIN):
        if user.has_role(ROLE_OPERATOR):
            # Operators see own sessions + namespace-shared sessions
            conditions.append(
                f"(metadata::json->>'owner' = ${idx}"
                f" OR metadata::json->>'visibility' = 'namespace'"
                f" OR metadata::json->>'owner' IS NULL)"
            )
            args.append(user.username)
            idx += 1
        else:
            # Viewers see only their own sessions
            conditions.append(
                f"(metadata::json->>'owner' = ${idx} OR metadata::json->>'owner' IS NULL)"
            )
            args.append(user.username)
            idx += 1

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        # Deduplicate: A2A SDK creates a new immutable task per message exchange.
        # Multiple tasks share the same context_id. For the session list, pick
        # the latest task (most recent status) for each context_id.
        dedup_cte = (
            "WITH latest AS ("
            "  SELECT DISTINCT ON (context_id) id, context_id, kind, status, metadata"
            "  FROM tasks ORDER BY context_id, id DESC"
            ")"
        )

        total = await conn.fetchval(f"{dedup_cte} SELECT COUNT(*) FROM latest {where}", *args)

        rows = await conn.fetch(
            f"{dedup_cte} SELECT id, context_id, kind, status, metadata"
            f" FROM latest {where}"
            f" ORDER BY COALESCE((status::json->>'timestamp')::text, id::text) DESC"
            f" LIMIT ${idx} OFFSET ${idx + 1}",
            *args,
            limit,
            offset,
        )

        # Merge metadata across rows: _set_owner_metadata() sets title/owner
        # on the first task row, but the agent creates later rows without it.
        # For each session where the latest row lacks title/owner, look for
        # it in sibling rows.
        items = [_row_to_summary(r) for r in rows]
        missing_meta = [s for s in items if not (s.metadata or {}).get("title")]
        if missing_meta:
            ctx_ids = [s.context_id for s in missing_meta]
            meta_rows = await conn.fetch(
                "SELECT DISTINCT ON (context_id) context_id, metadata"
                " FROM tasks"
                " WHERE context_id = ANY($1)"
                "   AND metadata::json->>'title' IS NOT NULL"
                " ORDER BY context_id, id DESC",
                ctx_ids,
            )
            meta_map = {}
            for mr in meta_rows:
                parsed = _parse_json_field(mr["metadata"])
                if parsed:
                    meta_map[mr["context_id"]] = parsed
            for s in missing_meta:
                donor = meta_map.get(s.context_id)
                if donor:
                    if s.metadata is None:
                        s.metadata = {}
                    for key in ("title", "owner", "visibility", "agent_name"):
                        if key not in s.metadata and key in donor:
                            s.metadata[key] = donor[key]

    return TaskListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/{namespace}/sessions/{context_id}",
    response_model=TaskDetail,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_session(namespace: str, context_id: str):
    """Get a task/session by context_id with full history and artifacts.

    If multiple tasks share the same context_id (e.g. retries), returns
    the latest one (highest id).
    """
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        # Pick the record with the longest history (most complete conversation)
        row = await conn.fetchrow(
            "SELECT * FROM tasks WHERE context_id = $1"
            " ORDER BY COALESCE(json_array_length(history::json), 0) DESC, id DESC"
            " LIMIT 1",
            context_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

    return _row_to_detail(row)


class SessionChainEntry(BaseModel):
    """One node in a session lineage chain."""

    context_id: str
    type: str  # "root", "child", "passover"
    status: Optional[str] = None
    parent: Optional[str] = None
    passover_from: Optional[str] = None
    title: Optional[str] = None


class SessionChainResponse(BaseModel):
    """Full session lineage: root + ordered chain of children/passovers."""

    root: str
    chain: List[SessionChainEntry]


@router.get(
    "/{namespace}/sessions/{context_id}/chain",
    response_model=SessionChainResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_session_chain(namespace: str, context_id: str):
    """Return the full lineage chain for a session.

    Walks parent_context_id upward to find the root, then collects all
    children (via parent_context_id) and passovers (via passover_from/to).
    Returns an ordered list starting from the root.
    """
    _validate_namespace(namespace)
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        # Fetch all sessions with their metadata (deduplicated by context_id)
        rows = await conn.fetch(
            "SELECT DISTINCT ON (context_id) context_id, status, metadata"
            " FROM tasks ORDER BY context_id, id DESC"
        )

    # Build lookup maps
    meta_map: Dict[str, Dict] = {}
    for r in rows:
        meta = _parse_json_field(r["metadata"]) or {}
        status = _parse_json_field(r["status"]) or {}
        meta_map[r["context_id"]] = {
            "meta": meta if isinstance(meta, dict) else {},
            "status": status if isinstance(status, dict) else {},
        }

    if context_id not in meta_map:
        raise HTTPException(status_code=404, detail="Session not found")

    # Walk upward to find root
    root_id = context_id
    visited = {root_id}
    while True:
        entry = meta_map.get(root_id, {})
        parent = entry.get("meta", {}).get("parent_context_id")
        pf = entry.get("meta", {}).get("passover_from")
        ancestor = parent or pf
        if not ancestor or ancestor in visited or ancestor not in meta_map:
            break
        visited.add(ancestor)
        root_id = ancestor

    # Collect chain: BFS from root following children + passovers
    chain: List[SessionChainEntry] = []
    queue = [root_id]
    seen = set()

    while queue:
        cid = queue.pop(0)
        if cid in seen:
            continue
        seen.add(cid)

        entry = meta_map.get(cid, {})
        meta = entry.get("meta", {})
        status = entry.get("status", {})
        state = status.get("state") if isinstance(status, dict) else None

        # Determine type
        if cid == root_id:
            node_type = "root"
        elif meta.get("parent_context_id"):
            node_type = "child"
        elif meta.get("passover_from"):
            node_type = "passover"
        else:
            node_type = "related"

        chain.append(
            SessionChainEntry(
                context_id=cid,
                type=node_type,
                status=state,
                parent=meta.get("parent_context_id"),
                passover_from=meta.get("passover_from"),
                title=meta.get("title"),
            )
        )

        # Find children and passovers pointing FROM this node
        for other_cid, other in meta_map.items():
            om = other.get("meta", {})
            if om.get("parent_context_id") == cid and other_cid not in seen:
                queue.append(other_cid)
            if om.get("passover_from") == cid and other_cid not in seen:
                queue.append(other_cid)

    return SessionChainResponse(root=root_id, chain=chain)


@router.get(
    "/{namespace}/sessions/{context_id}/history",
    response_model=HistoryPage,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
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
    skip_events: bool = Query(
        default=False,
        description="Skip loop_events extraction (for lightweight polling).",
    ),
    events_since: Optional[int] = Query(
        default=None,
        description="Only return loop_events after this count (incremental polling).",
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
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        # Aggregate history + artifacts across ALL task records for this context_id.
        # The A2A SDK creates a new immutable task per message exchange, so a
        # multi-turn session has N task records. Each record's history contains
        # the messages for that specific exchange. We merge them chronologically.
        rows = await conn.fetch(
            "SELECT id, history, artifacts, metadata, status FROM tasks WHERE context_id = $1"
            " ORDER BY COALESCE((status::json->>'timestamp')::text, '') ASC",
            context_id,
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Session not found")

    # Extract task_state and last_updated from the most recent task row.
    # The A2A SDK stores state transitions in the status JSON column.
    _last_status = _parse_json_field(rows[-1].get("status")) or {}
    _task_state = (
        _last_status.get("state")
        if isinstance(_last_status.get("state"), str)
        else (
            _last_status.get("state", {}).get("state")
            if isinstance(_last_status.get("state"), dict)
            else None
        )
    )
    _last_updated = _last_status.get("timestamp")

    # Merge history from all task records (ordered by task creation time)
    raw_history: list = []

    # Collect artifacts from all tasks (each task may have a final answer)
    all_artifact_texts: List[str] = []

    # Extract persisted loop events from ALL task rows.
    # Skip entirely when skip_events=True (lightweight polling for messages only).
    persisted_loop_events: Optional[List[Dict[str, Any]]] = None
    all_loop_events: List[Dict[str, Any]] = []
    seen_event_json: set = set()
    total_raw_count = 0
    _skip_event_extraction = skip_events
    for row in rows:
        meta = _parse_json_field(row.get("metadata"))
        if not _skip_event_extraction and isinstance(meta, dict) and meta.get("loop_events"):
            for evt in meta["loop_events"]:
                total_raw_count += 1
                # Dedup by full JSON to handle exact duplicates from old metadata merge
                evt_json = json.dumps(evt, sort_keys=True)
                if evt_json not in seen_event_json:
                    seen_event_json.add(evt_json)
                    all_loop_events.append(evt)
    for row in rows:
        task_history = _parse_json_field(row["history"]) or []

        # If this task has no persisted loop_events but its history contains
        # JSON lines with loop_id (agent messages from a cut-short stream),
        # extract them so the UI can show an incomplete loop card.
        row_meta = _parse_json_field(row.get("metadata"))
        has_persisted = isinstance(row_meta, dict) and bool(row_meta.get("loop_events"))
        if not _skip_event_extraction and not has_persisted:
            # Extract events server-side via SQL to avoid loading full history
            # into Python memory (can be 500KB+). Query uses jsonb functions
            # to parse event JSON lines from agent message parts.
            task_id = row.get("id") or (row["id"] if "id" in row.keys() else None)
            if task_id:
                try:
                    extract_pool = await get_session_pool(namespace)
                    async with extract_pool.acquire() as extract_conn:
                        db_events = await extract_conn.fetch(
                            """
                            SELECT DISTINCT ON (evt_json)
                                line::jsonb AS evt,
                                line AS evt_json
                            FROM tasks,
                                jsonb_array_elements(history::jsonb) AS msg,
                                jsonb_array_elements(msg->'parts') AS part,
                                unnest(string_to_array(part->>'text', E'\\n')) AS line
                            WHERE tasks.id = $1
                                AND msg->>'role' = 'agent'
                                AND part->>'text' IS NOT NULL
                                AND line ~ '^\\s*\\{.*"loop_id"'
                                AND line::jsonb->>'type' IS NOT NULL
                                AND line::jsonb->>'type' NOT IN ('plan', 'plan_step', 'reflection', 'llm_response')
                            """,
                            task_id,
                        )
                        for db_evt in db_events:
                            evt = json.loads(db_evt["evt_json"])
                            evt_json = json.dumps(evt, sort_keys=True)
                            if evt_json not in seen_event_json:
                                seen_event_json.add(evt_json)
                                all_loop_events.append(evt)
                except Exception as e:
                    logger.warning(
                        "SQL event extraction failed for task %s: %s — falling back to Python",
                        task_id,
                        e,
                    )
                    # Fallback: Python extraction (loads full history)
                    for msg in task_history:
                        if msg.get("role") != "agent":
                            continue
                        for part in msg.get("parts") or []:
                            text = part.get("text", "") if isinstance(part, dict) else ""
                            for line in text.split("\n"):
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    parsed = json.loads(line)
                                    if isinstance(parsed, dict) and "loop_id" in parsed:
                                        evt_type = parsed.get("type", "")
                                        _LEGACY = {
                                            "plan",
                                            "plan_step",
                                            "reflection",
                                            "llm_response",
                                        }
                                        if evt_type not in _LEGACY:
                                            evt_json = json.dumps(parsed, sort_keys=True)
                                            if evt_json not in seen_event_json:
                                                seen_event_json.add(evt_json)
                                                all_loop_events.append(parsed)
                                except (json.JSONDecodeError, TypeError):
                                    pass

        for msg in task_history:
            raw_history.append(msg)

        # Accumulate artifacts from ALL task records
        task_artifacts = _parse_json_field(row.get("artifacts")) or []
        if isinstance(task_artifacts, list):
            for art in task_artifacts:
                if not isinstance(art, dict):
                    continue
                for part in art.get("parts") or []:
                    if isinstance(part, dict) and part.get("text"):
                        all_artifact_texts.append(part["text"])

    # Set persisted_loop_events AFTER both extraction passes (metadata + history text)
    # Apply events_since filter — only return new events the client hasn't seen
    if events_since is not None and len(all_loop_events) > events_since:
        all_loop_events = all_loop_events[events_since:]
    elif events_since is not None and len(all_loop_events) <= events_since:
        all_loop_events = []  # Client already has everything

    if all_loop_events:
        persisted_loop_events = all_loop_events
        logger.info(
            "HISTORY session=%s tasks=%d total_events=%d unique=%d types=%s",
            context_id,
            len(rows),
            total_raw_count,
            len(all_loop_events),
            [e.get("type") for e in all_loop_events[:10]],
        )
        # Write-back: if events were extracted from history text but not in
        # metadata, persist them so future loads don't need re-extraction.
        if total_raw_count == 0 and len(all_loop_events) > 0 and rows:

            async def _writeback():
                try:
                    wb_pool = await get_session_pool(namespace)
                    async with wb_pool.acquire() as conn:
                        task_id = rows[-1]["id"]
                        row = await conn.fetchrow(
                            "SELECT metadata FROM tasks WHERE id = $1", task_id
                        )
                        if row:
                            meta = _parse_json_field(row["metadata"]) or {}
                            meta["loop_events"] = all_loop_events
                            await conn.execute(
                                "UPDATE tasks SET metadata = $1::jsonb WHERE id = $2",
                                json.dumps(meta),
                                task_id,
                            )
                            logger.info(
                                "HISTORY write-back: saved %d events to metadata for session %s",
                                len(all_loop_events),
                                context_id,
                            )
                except Exception as e:
                    logger.warning("HISTORY write-back failed for session %s: %s", context_id, e)

            asyncio.create_task(_writeback())

    # Parse graph event dumps into structured tool call data.
    # Raw history contains: user messages + graph events like:
    #   "assistant: {'messages': [AIMessage(content='...', tool_calls=[...])]}"
    #   "tools: {'messages': [ToolMessage(content='output', name='shell')]}"
    # We parse these into a richer conversation view.
    def _parse_graph_event(text: str) -> Optional[Dict[str, Any]]:
        """Parse a graph event — JSON first, improved regex for old format."""
        stripped = text.strip()

        # New format: structured JSON
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "type" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            pass

        # Old format: Python repr — improved regex for robustness
        if stripped.startswith("assistant:"):
            # Try to extract tool calls (may be truncated)
            if "tool_calls=" in stripped or ("'name':" in stripped and "'args':" in stripped):
                calls = re.findall(r"'name':\s*'([^']+)'.*?'args':\s*(\{[^}]*\}?)", stripped)
                if calls:
                    return {
                        "type": "tool_call",
                        "tools": [{"name": c[0], "args": c[1]} for c in calls],
                    }
            # Extract content — try single quotes then double quotes
            for pattern in [
                r"content='((?:[^'\\]|\\.){1,2000})'",
                r'content="((?:[^"\\]|\\.){1,2000})"',
                r"content='([^']{1,500})",  # truncated (no closing quote)
            ]:
                match = re.search(pattern, stripped)
                if match and match.group(1).strip():
                    return {"type": "llm_response", "content": match.group(1)[:2000]}

        elif stripped.startswith("tools:"):
            # Extract tool result — try single then double quotes
            for pattern in [
                r"content='((?:[^'\\]|\\.)*?)'\s*,\s*name='([^']*)'",
                r'content="((?:[^"\\]|\\.)*?)"\s*,\s*name=\'([^\']*)\'',
                r"content='((?:[^'\\]|\\.)*?)'\s*,\s*name=\"([^\"]*)\"",
                r'content="((?:[^"\\]|\\.)*?)"\s*,\s*name="([^"]*)"',
            ]:
                match = re.search(pattern, stripped)
                if match:
                    output = match.group(1)[:2000].replace("\\n", "\n")
                    return {
                        "type": "tool_result",
                        "name": match.group(2),
                        "output": output,
                    }

        return None

    filtered: List[Dict[str, Any]] = []
    for msg in raw_history:
        if msg.get("role") == "user":
            # Propagate username from A2A message metadata to top level
            username = msg.get("metadata", {}).get("username")
            entry: Dict[str, Any] = {
                "role": "user",
                "parts": msg.get("parts", []),
            }
            if username:
                entry["username"] = username
            filtered.append(entry)
            continue

        # Try to parse graph event dumps
        text = "".join(
            p.get("text", "")
            for p in (msg.get("parts") or [])
            if isinstance(p, dict) and p.get("text")
        )
        if not text:
            continue

        # Text may contain multiple JSON events on separate lines
        # (agent emits "\n".join(serializer.serialize(...) for ...))
        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = _parse_graph_event(line)
            if parsed:
                filtered.append(
                    {
                        "role": "agent",
                        "parts": [{"kind": "data", **parsed}],
                    }
                )

    # Append final responses from artifacts, but deduplicate against
    # llm_response entries already parsed from graph events.  Without this
    # guard the same final answer appears twice: once from the graph event
    # dump (kind=data, type=llm_response) and once from the artifact.
    seen_llm_texts: set = set()
    for msg in filtered:
        parts = msg.get("parts") or []
        for p in parts:
            if not isinstance(p, dict):
                continue
            if p.get("kind") == "data" and p.get("type") == "llm_response":
                content = (p.get("content") or "").strip()
                if content:
                    # Store a normalised prefix for fuzzy dedup
                    seen_llm_texts.add(content[:200])

    for art_text in all_artifact_texts:
        normalised = art_text.strip()[:200]
        if normalised and normalised in seen_llm_texts:
            continue  # already present as an llm_response
        filtered.append(
            {
                "role": "agent",
                "parts": [{"kind": "text", "text": art_text}],
            }
        )

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

    return HistoryPage(
        messages=page,
        total=total,
        has_more=has_more,
        loop_events=persisted_loop_events,
        task_state=_task_state,
        last_updated=_last_updated,
    )


@router.delete(
    "/{namespace}/sessions/{context_id}",
    status_code=204,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def delete_session(
    namespace: str,
    context_id: str,
    user: TokenData = Depends(get_required_user),
):
    """Delete a task/session by context_id. Only owner or admin can delete."""
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT metadata FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
            context_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

        meta = _parse_json_field(row["metadata"])
        _check_session_ownership(meta, user, "delete")

        await conn.execute("DELETE FROM tasks WHERE context_id = $1", context_id)

    return None


class RenameRequest(BaseModel):
    title: str


@router.put(
    "/{namespace}/sessions/{context_id}/rename",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def rename_session(
    namespace: str,
    context_id: str,
    request: RenameRequest,
    user: TokenData = Depends(get_required_user),
):
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
        _check_session_ownership(meta, user, "rename")

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
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def kill_session(
    namespace: str,
    context_id: str,
    user: TokenData = Depends(get_required_user),
):
    """Mark a task as canceled by updating its status JSON. Only owner or admin."""
    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1", context_id
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

        meta = _parse_json_field(row["metadata"])
        _check_session_ownership(meta, user, "kill")

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


@router.post(
    "/{namespace}/sessions/{context_id}/approve",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def approve_session(
    namespace: str,
    context_id: str,
    user: TokenData = Depends(get_required_user),
):
    """Approve a pending HITL request — resumes the agent graph via A2A.

    No ownership check: any ROLE_OPERATOR can approve any session's HITL request.
    This is intentional — HITL approval is a team-level action, not owner-only.
    """
    _validate_namespace(namespace)
    logger.info(
        "User %s approved HITL request for session %s in namespace %s",
        user.username,
        context_id,
        namespace,
    )
    return await _resume_agent_graph(namespace, context_id, user, approved=True)


@router.post(
    "/{namespace}/sessions/{context_id}/deny",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def deny_session(
    namespace: str,
    context_id: str,
    user: TokenData = Depends(get_required_user),
):
    """Deny a pending HITL request — resumes the agent graph with denial.

    No ownership check: same rationale as approve — team-level action.
    """
    _validate_namespace(namespace)
    logger.info(
        "User %s denied HITL request for session %s in namespace %s",
        user.username,
        context_id,
        namespace,
    )
    return await _resume_agent_graph(namespace, context_id, user, approved=False)


async def _resume_agent_graph(
    namespace: str,
    context_id: str,
    user: TokenData,
    approved: bool,
) -> dict:
    """Resume an agent's LangGraph graph by sending an A2A message.

    When an agent enters INPUT_REQUIRED state, it pauses and waits for
    the next user message on the same contextId.  Sending a message/send
    with the approval/denial text resumes the graph via LangGraph's
    Command(resume=...) pattern handled inside the agent.
    """
    # 1. Look up agent_name from session metadata
    pool = await get_session_pool(namespace)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT metadata FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
            context_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    meta = _parse_json_field(row["metadata"]) or {}
    agent_name = meta.get("agent_name")
    if not agent_name:
        raise HTTPException(
            status_code=400,
            detail="Session has no agent_name in metadata — cannot determine target agent",
        )
    # Defense-in-depth: agent_name comes from DB, not user input, but validate
    # against K8s naming rules to prevent SSRF if metadata is ever corrupted.
    if not _K8S_NAME_RE.match(agent_name):
        raise HTTPException(400, f"Invalid agent_name in session metadata: {agent_name}")

    # 2. Build the A2A message to resume the graph
    decision = "approved" if approved else "denied"
    agent_url = f"http://{agent_name}.{namespace}.svc.cluster.local:8000"
    a2a_msg = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": uuid4().hex,
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": decision}],
                "messageId": uuid4().hex,
                "contextId": context_id,
                "metadata": {
                    "username": user.username,
                    "hitl_decision": decision,
                },
            }
        },
    }

    # 3. POST to the agent — this resumes the LangGraph graph
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(f"{agent_url}/", json=a2a_msg)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.error("Failed to resume agent %s: %s", agent_name, e)
        raise HTTPException(502, f"Failed to resume agent: {e}")

    if "error" in data:
        raise HTTPException(502, f"A2A error: {data['error']}")

    result = data.get("result", {})
    return {
        "status": decision,
        "context_id": context_id,
        "agent_name": agent_name,
        "task_status": result.get("status", {}),
    }


@router.put(
    "/{namespace}/sessions/{context_id}/visibility",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def set_session_visibility(
    namespace: str,
    context_id: str,
    request: VisibilityRequest,
    user: TokenData = Depends(get_required_user),
):
    """Toggle session visibility between 'private' and 'namespace'.

    Only the session owner or admin can change visibility.
    """
    if request.visibility not in ("private", "namespace"):
        raise HTTPException(400, "visibility must be 'private' or 'namespace'")

    pool = await get_session_pool(namespace)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT metadata FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
            context_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

        meta = _parse_json_field(row["metadata"]) or {}
        _check_session_ownership(meta, user, "change visibility")

        meta["visibility"] = request.visibility
        await conn.execute(
            "UPDATE tasks SET metadata = $1::json WHERE context_id = $2",
            json.dumps(meta),
            context_id,
        )

    return {"visibility": request.visibility}


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
# Sandbox agent visibility — list agent deployments with session counts
# ---------------------------------------------------------------------------


class SandboxAgentInfo(BaseModel):
    """Summary of a sandbox agent deployment."""

    name: str
    namespace: str
    status: str  # "ready", "pending", "error"
    replicas: str  # "1/1"
    session_count: int
    active_sessions: int
    image: str
    created: Optional[str] = None


def _get_apps_api():
    """Return an AppsV1Api client, or None if K8s is unavailable."""
    try:
        import kubernetes.client
        import kubernetes.config
        from kubernetes.config import ConfigException

        try:
            if os.getenv("KUBERNETES_SERVICE_HOST"):
                kubernetes.config.load_incluster_config()
            else:
                kubernetes.config.load_kube_config()
        except ConfigException:
            return None
        return kubernetes.client.AppsV1Api()
    except ImportError:
        return None


def _get_core_api():
    """Return a CoreV1Api client, or None if K8s is unavailable."""
    try:
        import kubernetes.client
        import kubernetes.config
        from kubernetes.config import ConfigException

        try:
            if os.getenv("KUBERNETES_SERVICE_HOST"):
                kubernetes.config.load_incluster_config()
            else:
                kubernetes.config.load_kube_config()
        except ConfigException:
            return None
        return kubernetes.client.CoreV1Api()
    except ImportError:
        return None


@router.get("/{namespace}/agents", response_model=List[SandboxAgentInfo])
async def list_sandbox_agents(namespace: str):
    """List sandbox agent deployments in the namespace with session counts."""
    apps_api = _get_apps_api()
    if apps_api is None:
        return []

    try:
        deployments = apps_api.list_namespaced_deployment(
            namespace=namespace,
            label_selector="kagenti.io/type=agent",
        )
    except Exception as exc:
        logger.warning("Failed to list deployments in %s: %s", namespace, exc)
        return []

    # Query session counts from DB (best effort)
    session_counts: Dict[str, int] = {}
    active_counts: Dict[str, int] = {}
    try:
        pool = await get_session_pool(namespace)
        async with pool.acquire() as conn:
            # Total sessions per agent_name
            rows = await conn.fetch(
                "SELECT COALESCE(metadata::json->>'agent_name', 'sandbox-legion') AS agent,"
                " COUNT(*) AS cnt"
                " FROM tasks GROUP BY agent"
            )
            for row in rows:
                session_counts[row["agent"]] = row["cnt"]

            # Active sessions (working or submitted)
            rows = await conn.fetch(
                "SELECT COALESCE(metadata::json->>'agent_name', 'sandbox-legion') AS agent,"
                " COUNT(*) AS cnt"
                " FROM tasks"
                " WHERE status::text ILIKE '%working%' OR status::text ILIKE '%submitted%'"
                " GROUP BY agent"
            )
            for row in rows:
                active_counts[row["agent"]] = row["cnt"]
    except Exception as exc:
        logger.debug("Could not query session counts for %s: %s", namespace, exc)

    result: List[SandboxAgentInfo] = []
    for dep in deployments.items:
        name = dep.metadata.name
        ready = dep.status.ready_replicas or 0
        desired = dep.spec.replicas or 1

        if ready >= desired:
            status = "ready"
        elif ready > 0:
            status = "pending"
        else:
            # Check if there are unavailable replicas with error conditions
            if dep.status.conditions:
                has_error = any(
                    c.type == "Available" and c.status == "False" for c in dep.status.conditions
                )
                status = "error" if has_error else "pending"
            else:
                status = "pending"

        # Extract container image from the first container
        image = ""
        if dep.spec.template.spec.containers:
            image = dep.spec.template.spec.containers[0].image or ""

        created = None
        if dep.metadata.creation_timestamp:
            created = dep.metadata.creation_timestamp.isoformat()

        result.append(
            SandboxAgentInfo(
                name=name,
                namespace=namespace,
                status=status,
                replicas=f"{ready}/{desired}",
                session_count=session_counts.get(name, 0),
                active_sessions=active_counts.get(name, 0),
                image=image,
                created=created,
            )
        )

    return result


@router.get("/{namespace}/agent-card/{agent_name}")
async def get_sandbox_agent_card(namespace: str, agent_name: str):
    """Proxy the A2A agent card from a sandbox agent pod (port 8000)."""
    if not _K8S_NAME_RE.match(agent_name):
        raise HTTPException(400, "Invalid agent name")
    if not _K8S_NAME_RE.match(namespace):
        raise HTTPException(400, "Invalid namespace")

    agent_url = f"http://{agent_name}.{namespace}.svc.cluster.local:8000"
    card_url = f"{agent_url}/.well-known/agent-card.json"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(card_url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Agent returned {e.response.status_code}")
    except httpx.RequestError as e:
        logger.warning("Failed to fetch agent card from %s: %s", card_url, e)
        raise HTTPException(503, f"Cannot reach agent {agent_name}")


@router.get("/{namespace}/agents/{agent_name}/pod-status")
async def get_agent_pod_status(namespace: str, agent_name: str):
    """Return pod status, events, and resources for all pods related to an agent deployment.

    Checks three deployments: the agent itself, its egress proxy, and the
    shared llm-budget-proxy.
    """
    if not _K8S_NAME_RE.match(agent_name):
        raise HTTPException(400, "Invalid agent name")
    if not _K8S_NAME_RE.match(namespace):
        raise HTTPException(400, "Invalid namespace")

    apps_api = _get_apps_api()
    core_api = _get_core_api()
    if apps_api is None or core_api is None:
        raise HTTPException(503, "Kubernetes API unavailable")

    from kubernetes.client import ApiException

    component_deployments = [
        ("agent", agent_name),
        ("egress-proxy", f"{agent_name}-egress-proxy"),
        ("llm-budget-proxy", "llm-budget-proxy"),
    ]

    pods_result: List[Dict[str, Any]] = []

    for component, deploy_name in component_deployments:
        # --- Fetch the Deployment -------------------------------------------
        try:
            deployment = apps_api.read_namespaced_deployment(name=deploy_name, namespace=namespace)
        except ApiException as e:
            if e.status == 404:
                continue  # deployment doesn't exist, skip
            logger.warning("Error reading deployment %s/%s: %s", namespace, deploy_name, e)
            continue

        replicas = deployment.spec.replicas or 1
        ready_replicas = deployment.status.ready_replicas or 0

        # --- Find pods for this deployment ----------------------------------
        match_labels = deployment.spec.selector.match_labels or {}
        label_selector = ",".join(f"{k}={v}" for k, v in match_labels.items())

        try:
            pod_list = core_api.list_namespaced_pod(
                namespace=namespace, label_selector=label_selector
            )
        except ApiException as e:
            logger.warning("Error listing pods for %s/%s: %s", namespace, deploy_name, e)
            pods_result.append(
                {
                    "component": component,
                    "deployment": deploy_name,
                    "replicas": replicas,
                    "ready_replicas": ready_replicas,
                    "pod_name": None,
                    "status": "Unknown",
                    "restarts": 0,
                    "last_restart_reason": None,
                    "resources": {
                        "requests": {"cpu": "", "memory": ""},
                        "limits": {"cpu": "", "memory": ""},
                    },
                    "events": [],
                }
            )
            continue

        if not pod_list.items:
            pods_result.append(
                {
                    "component": component,
                    "deployment": deploy_name,
                    "replicas": replicas,
                    "ready_replicas": ready_replicas,
                    "pod_name": None,
                    "status": "No pods",
                    "restarts": 0,
                    "last_restart_reason": None,
                    "resources": {
                        "requests": {"cpu": "", "memory": ""},
                        "limits": {"cpu": "", "memory": ""},
                    },
                    "events": [],
                }
            )
            continue

        for pod in pod_list.items:
            pod_name = pod.metadata.name

            # --- Container status -------------------------------------------
            status = "Unknown"
            restarts = 0
            last_restart_reason = None

            container_statuses = pod.status.container_statuses or []
            if container_statuses:
                cs = container_statuses[0]
                restarts = cs.restart_count or 0

                if cs.state:
                    if cs.state.running:
                        status = "Running"
                    elif cs.state.waiting:
                        status = cs.state.waiting.reason or "Waiting"
                    elif cs.state.terminated:
                        status = cs.state.terminated.reason or "Terminated"

                if cs.last_state and cs.last_state.terminated:
                    last_restart_reason = cs.last_state.terminated.reason
            elif pod.status.phase:
                status = pod.status.phase

            # --- Resources from pod spec ------------------------------------
            resources: Dict[str, Dict[str, str]] = {
                "requests": {"cpu": "", "memory": ""},
                "limits": {"cpu": "", "memory": ""},
            }
            containers = pod.spec.containers or []
            if containers:
                res = containers[0].resources
                if res:
                    if res.requests:
                        resources["requests"] = {
                            "cpu": res.requests.get("cpu", ""),
                            "memory": res.requests.get("memory", ""),
                        }
                    if res.limits:
                        resources["limits"] = {
                            "cpu": res.limits.get("cpu", ""),
                            "memory": res.limits.get("memory", ""),
                        }

            # --- Events for this pod ----------------------------------------
            events: List[Dict[str, Any]] = []
            try:
                event_list = core_api.list_namespaced_event(
                    namespace=namespace,
                    field_selector=f"involvedObject.name={pod_name}",
                )
                for evt in event_list.items:
                    timestamp = None
                    if evt.last_timestamp:
                        timestamp = evt.last_timestamp.isoformat()
                    elif evt.event_time:
                        timestamp = evt.event_time.isoformat()
                    events.append(
                        {
                            "type": evt.type or "",
                            "reason": evt.reason or "",
                            "message": evt.message or "",
                            "timestamp": timestamp or "",
                            "count": evt.count or 1,
                        }
                    )
            except ApiException as e:
                logger.warning("Error listing events for pod %s/%s: %s", namespace, pod_name, e)

            pods_result.append(
                {
                    "component": component,
                    "deployment": deploy_name,
                    "replicas": replicas,
                    "ready_replicas": ready_replicas,
                    "pod_name": pod_name,
                    "status": status,
                    "restarts": restarts,
                    "last_restart_reason": last_restart_reason,
                    "resources": resources,
                    "events": events,
                }
            )

    return {"pods": pods_result}


# ---------------------------------------------------------------------------
# Chat proxy — forwards A2A messages to sandbox agents on port 8000
# ---------------------------------------------------------------------------


class SandboxChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    agent_name: str = "sandbox-legion"
    skill: Optional[str] = None

    @field_validator("agent_name")
    @classmethod
    def validate_agent_name(cls, v: str) -> str:
        if not _K8S_NAME_RE.match(v):
            raise ValueError("Invalid agent name — must be a valid Kubernetes name")
        return v


def _validate_namespace(namespace: str) -> str:
    """Validate namespace matches Kubernetes naming rules (prevent SSRF)."""
    if not _K8S_NAME_RE.match(namespace):
        raise HTTPException(400, "Invalid namespace name")
    return namespace


async def _resolve_agent_name(
    namespace: str,
    session_id: str | None,
    request_agent: str,
) -> str:
    """Resolve the authoritative agent name for a request.

    Agent Name Resolution Architecture
    -----------------------------------
    1. ``_resolve_agent_name()`` is the **single source of truth** for
       determining which agent owns a session.
    2. For **new sessions** (no ``session_id``): uses ``request_agent``
       supplied by the frontend.
    3. For **existing sessions**: reads ``agent_name`` from the DB
       metadata, which is authoritative.  The frontend's
       ``selectedAgent`` state is unreliable due to race conditions.
    4. ``_set_owner_metadata()`` (streaming path) and ``chat_send()``
       (non-streaming path) both call this function and **always
       overwrite** the metadata ``agent_name`` with the resolved value
       so every task record stays consistent.
    5. ``list_sessions()`` merges ``agent_name`` across task records for
       the sidebar, ensuring the correct name appears even when some
       records lack metadata.
    """
    if not session_id:
        return request_agent or "sandbox-legion"

    try:
        pool = await get_session_pool(namespace)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT metadata FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
                session_id,
            )
            if row and row["metadata"]:
                meta = _parse_json_field(row["metadata"]) or {}
                bound_agent = meta.get("agent_name")
                if bound_agent:
                    if bound_agent != request_agent:
                        logger.info(
                            "Resolved agent from DB: %s (request had %s) for session %s",
                            bound_agent,
                            request_agent,
                            session_id[:12],
                        )
                    return bound_agent
    except Exception as e:
        logger.warning("Failed to resolve agent from DB: %s", e)

    # Never return empty — fall back to default agent
    return request_agent or "sandbox-legion"


@router.post(
    "/{namespace}/chat",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def chat_send(
    namespace: str,
    request: SandboxChatRequest,
    user: TokenData = Depends(get_required_user),
):
    """Send a message to a sandbox agent via A2A JSON-RPC (non-streaming).

    Proxies the message to the agent's in-cluster service on port 8000.
    Returns the complete response (no SSE streaming).
    """
    _validate_namespace(namespace)
    context_id = request.session_id or uuid4().hex[:36]

    # Resolve agent name: for existing sessions, use DB-bound agent
    agent_name = await _resolve_agent_name(namespace, request.session_id, request.agent_name)
    agent_url = f"http://{agent_name}.{namespace}.svc.cluster.local:8000"

    metadata: dict = {"username": user.username}
    if request.skill:
        metadata["skill"] = request.skill

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
                "metadata": metadata,
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
    if text.startswith("[{") and "'type': 'text'" in text and len(text) < 100_000:
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

    # Auto-set session title from first message (truncated to 80 chars).
    # Merge metadata across ALL task rows so agent-written fields
    # (e.g. llm_request_ids) and backend fields (owner, title, agent_name)
    # coexist on every row.
    final_context_id = result.get("contextId", context_id)
    try:
        pool = await get_session_pool(namespace)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT metadata FROM tasks WHERE context_id = $1",
                final_context_id,
            )
            if rows:
                merged: dict = {}
                for row in rows:
                    m = _parse_json_field(row["metadata"]) or {}
                    merged.update({k: v for k, v in m.items() if v is not None})
                changed = False
                if not merged.get("title"):
                    merged["title"] = request.message[:80].replace("\n", " ")
                    changed = True
                if not merged.get("owner"):
                    merged["owner"] = user.username
                    merged["visibility"] = "private"
                    changed = True
                resolved = await _resolve_agent_name(
                    namespace, final_context_id, request.agent_name
                )
                if resolved and merged.get("agent_name") != resolved:
                    merged["agent_name"] = resolved
                    changed = True
                if changed:
                    await conn.execute(
                        "UPDATE tasks SET metadata = $1::json WHERE context_id = $2",
                        json.dumps(merged),
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


# ---------------------------------------------------------------------------
# SSE streaming endpoint
# ---------------------------------------------------------------------------


def _extract_text_from_parts(parts: list) -> str:
    """Extract text content from A2A message parts."""
    content = ""
    for part in parts:
        if isinstance(part, dict):
            if "text" in part:
                content += part["text"]
            elif part.get("kind") == "text":
                content += part.get("text", "")
            elif "data" in part:
                data = part["data"]
                if isinstance(data, dict):
                    if "content_type" in data and "content" in data:
                        content_type = data.get("content_type", "")
                        content_value = data.get("content", "")
                        if content_type == "application/json" and content_value:
                            try:
                                json_data = json.loads(content_value)
                                formatted = json.dumps(json_data, indent=2)
                                content += f"\n```json\n{formatted}\n```\n"
                            except json.JSONDecodeError:
                                content += f"\n{content_value}\n"
                        elif not content_type.startswith("image/"):
                            content += f"\n{content_value}\n"
                    else:
                        formatted = json.dumps(data, indent=2)
                        content += f"\n```json\n{formatted}\n```\n"
                elif isinstance(data, str):
                    try:
                        json_data = json.loads(data)
                        formatted = json.dumps(json_data, indent=2)
                        content += f"\n```json\n{formatted}\n```\n"
                    except (json.JSONDecodeError, TypeError):
                        content += f"\n{data}\n"
                elif isinstance(data, (list, int, float, bool)):
                    formatted = json.dumps(data, indent=2)
                    content += f"\n```json\n{formatted}\n```\n"
    return content


# ---------------------------------------------------------------------------
# Incremental loop-event persistence
# ---------------------------------------------------------------------------
_INCREMENTAL_PERSIST_THRESHOLD = 1  # persist every event — no batching, no loss on disconnect
_INCREMENTAL_TRIGGER_TYPES = frozenset(
    {
        "planner_output",
        "replanner_output",
        "executor_step",
        "tool_call",
        "tool_result",
        "micro_reasoning",
        "reflector_decision",
        "reporter_output",
        "step_selector",
        "budget_update",
    }
)


async def _persist_loop_events_incremental(
    task_id: str,
    loop_events: list[dict],
    namespace: str,
) -> None:
    """Write the current loop_events list to the task metadata (fire-and-forget).

    Uses ``jsonb_set`` so only the ``loop_events`` key is touched — other
    metadata fields are left intact.  This is safe to call concurrently with
    the final writeback because the final writeback overwrites the same key
    with the complete list.
    """
    try:
        pool = await get_session_pool(namespace)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tasks SET metadata = jsonb_set("
                "  COALESCE(metadata::jsonb, '{}'),"
                "  '{loop_events}',"
                "  $1::jsonb"
                ") WHERE id = $2",
                json.dumps(loop_events),
                task_id,
            )
        logger.debug(
            "Incremental persist: %d loop events for task %s",
            len(loop_events),
            task_id,
        )
    except Exception as exc:
        logger.warning(
            "Incremental loop-event persist failed for task %s: %s",
            task_id,
            exc,
        )


def _should_persist_incrementally(
    loop_events: list[dict],
    last_persisted_count: int,
    latest_event: dict,
) -> bool:
    """Decide whether to fire an incremental DB write."""
    # Always persist on high-value event types
    if latest_event.get("type") in _INCREMENTAL_TRIGGER_TYPES:
        return True
    # Persist every N events
    if len(loop_events) - last_persisted_count >= _INCREMENTAL_PERSIST_THRESHOLD:
        return True
    return False


async def _stream_sandbox_response(
    agent_url: str,
    message: str,
    session_id: str,
    owner: Optional[str] = None,
    namespace: Optional[str] = None,
    agent_name: Optional[str] = None,
    skill: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Async generator that proxies A2A SSE events from the agent."""
    owner_set = False
    loop_events_persisted = False  # Guard against double-write of loop events
    session_has_loops = False  # Session-level flag: once loop_id seen, suppress flat events
    loop_events: list[dict] = []  # Accumulated loop events for persistence
    stream_task_id: Optional[str] = None  # DB id of the task row created by THIS stream
    _last_persisted_count: int = 0  # count at last incremental persist
    # Hold strong references to fire-and-forget persist tasks so the event loop
    # doesn't garbage-collect them before completion (Python asyncio only keeps
    # weak refs to tasks).
    _persist_bg_tasks: set[asyncio.Task] = set()

    async def _set_owner_metadata():
        """Set owner on THIS stream's task row only.

        Reads only the current task row's metadata (identified by
        ``stream_task_id``) and writes backend-managed fields (owner,
        title, agent_name) to that single row. Does NOT merge metadata
        across task rows — each task keeps its own metadata to prevent
        cross-pollination of loop_events and other per-turn data.

        Called on every SSE event batch (not just the first) to handle
        task rows created after the initial call. Retries on transient
        DB errors.
        """
        nonlocal stream_task_id
        logger.info(
            "_set_owner_metadata: agent_name=%s, owner=%s, namespace=%s, session=%s, task_id=%s",
            agent_name,
            owner,
            namespace,
            session_id,
            stream_task_id,
        )
        if not namespace:
            logger.warning(
                "_set_owner_metadata skipped: namespace is empty for session %s",
                session_id,
            )
            return
        for attempt in range(3):
            try:
                pool = await get_session_pool(namespace)
                async with pool.acquire() as conn:
                    # Use stream_task_id captured from A2A event — no fallback
                    if stream_task_id is None:
                        if attempt < 2:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        logger.warning(
                            "_set_owner_metadata: stream_task_id still None after retries for session %s",
                            session_id,
                        )
                        return

                    row = await conn.fetchrow(
                        "SELECT metadata FROM tasks WHERE id = $1",
                        stream_task_id,
                    )
                    if row is None:
                        if attempt < 2:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        return
                    meta = _parse_json_field(row["metadata"]) or {}

                    # Set/overwrite backend-managed fields on this row only
                    if owner and not meta.get("owner"):
                        meta["owner"] = owner
                        meta["visibility"] = "private"
                    if not meta.get("title"):
                        meta["title"] = message[:80].replace("\n", " ")
                    if agent_name:
                        meta["agent_name"] = agent_name
                    else:
                        logger.warning(
                            "_set_owner_metadata called with empty agent_name for session %s",
                            session_id,
                        )
                    # Update only THIS task row
                    result = await conn.execute(
                        "UPDATE tasks SET metadata = $1::json WHERE id = $2",
                        json.dumps(meta),
                        stream_task_id,
                    )
                    affected = int(str(result).split()[-1]) if result else 0
                    if affected == 0:
                        logger.warning(
                            "Metadata update matched 0 rows for task %s session %s",
                            stream_task_id,
                            session_id,
                        )
                break  # Success
            except Exception:
                logger.warning(
                    "Failed to set owner on session %s (attempt %d/3)",
                    session_id,
                    attempt + 1,
                    exc_info=True,
                )
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))

    metadata: dict = {"username": owner}
    if skill:
        metadata["skill"] = skill

    a2a_msg = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "message/stream",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
                "messageId": uuid4().hex,
                "contextId": session_id,
                "metadata": metadata,
            },
        },
    }

    logger.info("Starting sandbox SSE stream to %s (session=%s)", agent_url, session_id)

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    # SSE keepalive interval (seconds). Prevents nginx proxy_read_timeout
    # (default 300s) from killing long-running agent connections.
    _KEEPALIVE_INTERVAL = 15

    _MAX_RESUBSCRIBE = 5  # Max reconnection attempts via tasks/resubscribe
    _done_received = False

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            # --- Initial stream: message/stream ---
            async with client.stream(
                "POST",
                agent_url,
                json=a2a_msg,
                headers=headers,
            ) as response:
                response.raise_for_status()
                logger.info("Connected to agent, status=%d", response.status_code)

                line_count = 0
                line_iter = response.aiter_lines().__aiter__()
                stream_exhausted = False

                while not stream_exhausted:
                    try:
                        line = await asyncio.wait_for(
                            line_iter.__anext__(),
                            timeout=_KEEPALIVE_INTERVAL,
                        )
                    except asyncio.TimeoutError:
                        yield f"data: {json.dumps({'ping': True})}\n\n"
                        continue
                    except StopAsyncIteration:
                        stream_exhausted = True
                        break

                    if not line:
                        continue
                    line_count += 1
                    # Log all SSE lines for pipeline debugging
                    logger.info("Agent SSE [%d]: %s", line_count, line[:300])

                    if line.startswith("data: "):
                        data = line[6:]

                        if data == "[DONE]":
                            _done_received = True
                            logger.info("Received [DONE] from agent")
                            # Fan out done signal to sidecar manager so
                            # the looper detects stream completion
                            try:
                                from app.services.sidecar_manager import get_sidecar_manager

                                get_sidecar_manager().fan_out_event(
                                    session_id,
                                    {"done": True, "session_id": session_id},
                                )
                            except Exception:
                                pass  # best-effort

                            await _set_owner_metadata()
                            # Persist accumulated loop events to THIS task row only
                            if loop_events and namespace and not loop_events_persisted:
                                try:
                                    pool = await get_session_pool(namespace)
                                    async with pool.acquire() as conn:
                                        # Use stream_task_id to target this stream's row
                                        task_db_id = stream_task_id
                                        if task_db_id is None:
                                            task_db_id = await conn.fetchval(
                                                "SELECT id FROM tasks WHERE context_id = $1"
                                                " ORDER BY id DESC LIMIT 1",
                                                session_id,
                                            )
                                        if task_db_id is not None:
                                            row = await conn.fetchrow(
                                                "SELECT metadata FROM tasks WHERE id = $1",
                                                task_db_id,
                                            )
                                            if row:
                                                meta = (
                                                    json.loads(row["metadata"])
                                                    if row["metadata"]
                                                    else {}
                                                )
                                                meta["loop_events"] = loop_events
                                                await conn.execute(
                                                    "UPDATE tasks SET metadata = $1::json WHERE id = $2",
                                                    json.dumps(meta),
                                                    task_db_id,
                                                )
                                    loop_events_persisted = True
                                except Exception as e:
                                    logger.warning(
                                        "Failed to persist loop events for %s: %s",
                                        session_id,
                                        e,
                                    )
                            yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
                            break

                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError as e:
                            logger.warning(
                                "Failed to parse SSE data: %s, error: %s",
                                data[:200],
                                e,
                            )
                            continue

                        # Fan out event to sidecar manager
                        try:
                            from app.services.sidecar_manager import get_sidecar_manager

                            get_sidecar_manager().fan_out_event(session_id, chunk)
                        except Exception:
                            pass  # Sidecar fan-out is best-effort

                        if "result" not in chunk:
                            continue

                        result = chunk["result"]

                        # Capture stream_task_id from ANY A2A event as early as possible.
                        # TaskStatusUpdateEvent has "taskId", initial Task has "id".
                        if stream_task_id is None:
                            a2a_task_id = (
                                result.get("taskId") or result.get("task_id") or result.get("id")
                            )
                            if a2a_task_id and a2a_task_id != chunk.get("id"):
                                # Exclude JSON-RPC request id (chunk["id"])
                                stream_task_id = a2a_task_id
                                logger.info(
                                    "Captured stream_task_id=%s for session %s (kind=%s)",
                                    stream_task_id,
                                    session_id,
                                    result.get("kind", "?"),
                                )
                                # Flush any events buffered before task_id was known
                                if loop_events and namespace:
                                    _last_persisted_count = len(loop_events)
                                    _t = asyncio.create_task(
                                        _persist_loop_events_incremental(
                                            stream_task_id,
                                            list(loop_events),
                                            namespace,
                                        )
                                    )
                                    _persist_bg_tasks.add(_t)
                                    _t.add_done_callback(_persist_bg_tasks.discard)

                        payload: dict = {"session_id": session_id}
                        if owner:
                            payload["username"] = owner

                        # Set owner after first event (task exists in DB).
                        # Runs once per stream; the [DONE] handler runs it again
                        # to catch task rows created mid-stream.
                        if not owner_set:
                            await _set_owner_metadata()
                            owner_set = True

                        # --- TaskArtifactUpdateEvent ---
                        if "artifact" in result:
                            # Suppress artifact events in loop mode
                            # (loop cards handle all content display)
                            if session_has_loops:
                                continue

                            artifact = result["artifact"]
                            parts = artifact.get("parts", [])
                            content = _extract_text_from_parts(parts)

                            payload["event"] = {
                                "type": "artifact",
                                "taskId": result.get("taskId", ""),
                                "name": artifact.get("name"),
                                "index": artifact.get("index"),
                            }
                            if content:
                                payload["content"] = content

                            yield f"data: {json.dumps(payload)}\n\n"

                        # --- TaskStatusUpdateEvent ---
                        elif "status" in result and "taskId" in result:
                            status = result["status"]
                            is_final = result.get("final", False)
                            state = status.get("state", "UNKNOWN")

                            status_message = ""
                            if "message" in status and status["message"]:
                                parts = status["message"].get("parts", [])
                                status_message = _extract_text_from_parts(parts)

                            # Detect HITL (Human-in-the-Loop) requests
                            event_type = "status"
                            if state == "INPUT_REQUIRED":
                                event_type = "hitl_request"

                            # Forward structured loop events (loop_id)
                            # The agent serializer puts JSON lines in the message text.
                            # Parse each line and forward loop_id at top level so the
                            # UI can group events into AgentLoopCards.
                            _LEGACY = {"plan", "plan_step", "reflection", "llm_response"}
                            has_loop_events = False
                            if status_message:
                                msg_lines = [
                                    l.strip() for l in status_message.split("\n") if l.strip()
                                ]
                                logger.info(
                                    "SSE_PARSE session=%s lines=%d preview=%s",
                                    session_id,
                                    len(msg_lines),
                                    msg_lines[0][:120] if msg_lines else "(empty)",
                                )
                                for msg_line in msg_lines:
                                    try:
                                        parsed = json.loads(msg_line)
                                        if isinstance(parsed, dict) and "loop_id" in parsed:
                                            evt_type = parsed.get("type", "")

                                            # Skip legacy types entirely — don't forward, don't persist
                                            if evt_type in _LEGACY:
                                                logger.debug(
                                                    "LEGACY_SKIP session=%s type=%s",
                                                    session_id,
                                                    evt_type,
                                                )
                                                continue

                                            # Forward to frontend
                                            loop_payload = dict(payload)
                                            loop_payload["loop_id"] = parsed["loop_id"]
                                            loop_payload["loop_event"] = parsed
                                            yield f"data: {json.dumps(loop_payload)}\n\n"

                                            # Log forwarding
                                            logger.info(
                                                "LOOP_FWD session=%s loop=%s type=%s step=%s",
                                                session_id,
                                                parsed["loop_id"][:8],
                                                evt_type,
                                                parsed.get("step", ""),
                                            )

                                            has_loop_events = True
                                            session_has_loops = True
                                            loop_events.append(parsed)

                                            # -- Incremental persist --
                                            should_persist = _should_persist_incrementally(
                                                loop_events, _last_persisted_count, parsed
                                            )
                                            if stream_task_id and namespace and should_persist:
                                                logger.info(
                                                    "INCR_PERSIST session=%s task=%s events=%d type=%s",
                                                    session_id,
                                                    stream_task_id[:12],
                                                    len(loop_events),
                                                    evt_type,
                                                )
                                                _last_persisted_count = len(loop_events)
                                                _t = asyncio.create_task(
                                                    _persist_loop_events_incremental(
                                                        stream_task_id,
                                                        list(loop_events),  # snapshot
                                                        namespace,
                                                    )
                                                )
                                                _persist_bg_tasks.add(_t)
                                                _t.add_done_callback(_persist_bg_tasks.discard)
                                            elif not stream_task_id:
                                                logger.warning(
                                                    "INCR_PERSIST_SKIP session=%s no stream_task_id events=%d",
                                                    session_id,
                                                    len(loop_events),
                                                )

                                            continue
                                    except (json.JSONDecodeError, TypeError):
                                        pass

                            # Skip ALL flat events once loop mode is active
                            # (prevents duplicate flat blocks alongside AgentLoopCards)
                            if has_loop_events or session_has_loops:
                                continue

                            # Log flat event forwarding (no loop_id detected)
                            if status_message:
                                logger.info(
                                    "FLAT_FWD session=%s content_len=%d first_80=%s",
                                    session_id,
                                    len(status_message),
                                    status_message[:80].replace("\n", "\\n"),
                                )

                            payload["event"] = {
                                "type": event_type,
                                "taskId": result.get("taskId", ""),
                                "state": state,
                                "final": is_final,
                                "message": status_message or None,
                            }

                            if is_final or state in ("COMPLETED", "FAILED"):
                                if status_message:
                                    payload["content"] = status_message

                            yield f"data: {json.dumps(payload)}\n\n"

                        # --- Task object (initial response) ---
                        elif "id" in result and "status" in result:
                            task_status = result["status"]
                            state = task_status.get("state", "UNKNOWN")

                            payload["event"] = {
                                "type": "status",
                                "taskId": result.get("id", ""),
                                "state": state,
                                "final": state in ("COMPLETED", "FAILED"),
                            }

                            if state in ("COMPLETED", "FAILED"):
                                if "message" in task_status and task_status["message"]:
                                    parts = task_status["message"].get("parts", [])
                                    content = _extract_text_from_parts(parts)
                                    if content:
                                        payload["content"] = content

                            yield f"data: {json.dumps(payload)}\n\n"

                        # --- Direct message (A2AMessage) ---
                        elif "parts" in result:
                            content = _extract_text_from_parts(result["parts"])
                            message_id = result.get("messageId", "")

                            payload["event"] = {
                                "type": "status",
                                "taskId": message_id,
                                "state": "WORKING",
                                "final": False,
                                "message": content or None,
                            }
                            if content:
                                payload["content"] = content

                            yield f"data: {json.dumps(payload)}\n\n"

                        else:
                            logger.warning(
                                "Unknown result structure: keys=%s",
                                list(result.keys()),
                            )

            # --- Resubscribe loop: reconnect if stream closed without [DONE] ---
            if not _done_received and stream_task_id:
                for resub_attempt in range(1, _MAX_RESUBSCRIBE + 1):
                    logger.info(
                        "Resubscribe attempt %d/%d: task=%s session=%s",
                        resub_attempt,
                        _MAX_RESUBSCRIBE,
                        stream_task_id,
                        session_id,
                    )
                    resub_msg = {
                        "jsonrpc": "2.0",
                        "id": str(uuid4()),
                        "method": "tasks/resubscribe",
                        "params": {"id": stream_task_id},
                    }
                    try:
                        # First try a non-streaming POST to check if the task
                        # is still running. If it's terminal, resubscribe will
                        # fail, so we skip to recovery polling.
                        check_resp = await client.post(
                            agent_url,
                            json={
                                "jsonrpc": "2.0",
                                "id": str(uuid4()),
                                "method": "tasks/get",
                                "params": {"id": stream_task_id},
                            },
                        )
                        if check_resp.status_code == 200:
                            check_data = check_resp.json()
                            check_state = (
                                check_data.get("result", {})
                                .get("status", {})
                                .get("state", "")
                                .lower()
                            )
                            if check_state in ("completed", "failed", "canceled"):
                                logger.info(
                                    "Task already %s — skipping resubscribe, using recovery",
                                    check_state,
                                )
                                break

                        async with client.stream(
                            "POST",
                            agent_url,
                            json=resub_msg,
                            headers=headers,
                        ) as resub_response:
                            if resub_response.status_code != 200:
                                logger.info(
                                    "Resubscribe returned %d — falling back to recovery",
                                    resub_response.status_code,
                                )
                                break

                            logger.info(
                                "Resubscribed to agent stream, status=%d",
                                resub_response.status_code,
                            )
                            resub_iter = resub_response.aiter_lines().__aiter__()
                            resub_exhausted = False

                            while not resub_exhausted:
                                try:
                                    line = await asyncio.wait_for(
                                        resub_iter.__anext__(),
                                        timeout=_KEEPALIVE_INTERVAL,
                                    )
                                except asyncio.TimeoutError:
                                    yield f"data: {json.dumps({'ping': True})}\n\n"
                                    continue
                                except StopAsyncIteration:
                                    resub_exhausted = True
                                    break

                                if not line:
                                    continue
                                line_count += 1
                                logger.info("Agent SSE [%d] (resub): %s", line_count, line[:300])

                                if line.startswith("data: "):
                                    data = line[6:]

                                    if data == "[DONE]":
                                        _done_received = True
                                        logger.info("Received [DONE] from agent (via resubscribe)")
                                        await _set_owner_metadata()
                                        if loop_events and namespace and not loop_events_persisted:
                                            try:
                                                pool = await get_session_pool(namespace)
                                                async with pool.acquire() as conn:
                                                    task_db_id = stream_task_id
                                                    if task_db_id is not None:
                                                        row = await conn.fetchrow(
                                                            "SELECT metadata FROM tasks WHERE id = $1",
                                                            task_db_id,
                                                        )
                                                        if row:
                                                            meta = (
                                                                json.loads(row["metadata"])
                                                                if row["metadata"]
                                                                else {}
                                                            )
                                                            meta["loop_events"] = loop_events
                                                            await conn.execute(
                                                                "UPDATE tasks SET metadata = $1::json WHERE id = $2",
                                                                json.dumps(meta),
                                                                task_db_id,
                                                            )
                                                    loop_events_persisted = True
                                            except Exception as e:
                                                logger.warning(
                                                    "Failed to persist loop events on resubscribe: %s",
                                                    e,
                                                )
                                        yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
                                        break

                                    try:
                                        chunk = json.loads(data)
                                    except json.JSONDecodeError:
                                        continue

                                    if "result" not in chunk:
                                        continue

                                    result = chunk["result"]
                                    payload: dict = {"session_id": session_id}
                                    if owner:
                                        payload["username"] = owner

                                    # Process status updates (same logic as initial stream)
                                    if "status" in result and "message" in result.get("status", {}):
                                        state = result["status"].get("state", "UNKNOWN")
                                        parts = result["status"].get("message", {}).get("parts", [])
                                        status_message = _extract_text_from_parts(parts)
                                        is_final = result.get("final", False)

                                        _LEGACY = {
                                            "plan",
                                            "plan_step",
                                            "reflection",
                                            "llm_response",
                                        }
                                        has_loop_events = False
                                        if status_message:
                                            msg_lines = [
                                                l.strip()
                                                for l in status_message.split("\n")
                                                if l.strip()
                                            ]
                                            for msg_line in msg_lines:
                                                try:
                                                    parsed = json.loads(msg_line)
                                                    if (
                                                        isinstance(parsed, dict)
                                                        and "loop_id" in parsed
                                                    ):
                                                        evt_type = parsed.get("type", "")
                                                        if evt_type in _LEGACY:
                                                            continue
                                                        loop_payload = dict(payload)
                                                        loop_payload["loop_id"] = parsed["loop_id"]
                                                        loop_payload["loop_event"] = parsed
                                                        yield f"data: {json.dumps(loop_payload)}\n\n"
                                                        logger.info(
                                                            "LOOP_FWD session=%s loop=%s type=%s step=%s (resub)",
                                                            session_id,
                                                            parsed["loop_id"][:8],
                                                            evt_type,
                                                            parsed.get("step", ""),
                                                        )
                                                        has_loop_events = True
                                                        session_has_loops = True
                                                        loop_events.append(parsed)

                                                        # -- Incremental persist (resub) --
                                                        if (
                                                            stream_task_id
                                                            and namespace
                                                            and _should_persist_incrementally(
                                                                loop_events,
                                                                _last_persisted_count,
                                                                parsed,
                                                            )
                                                        ):
                                                            _last_persisted_count = len(loop_events)
                                                            _t = asyncio.create_task(
                                                                _persist_loop_events_incremental(
                                                                    stream_task_id,
                                                                    list(loop_events),  # snapshot
                                                                    namespace,
                                                                )
                                                            )
                                                            _persist_bg_tasks.add(_t)
                                                            _t.add_done_callback(
                                                                _persist_bg_tasks.discard
                                                            )

                                                except (json.JSONDecodeError, TypeError):
                                                    pass

                                            if not has_loop_events and not session_has_loops:
                                                payload["event"] = {
                                                    "type": "status",
                                                    "taskId": result.get("taskId", ""),
                                                    "state": state,
                                                    "final": is_final,
                                                    "message": status_message or None,
                                                }
                                                yield f"data: {json.dumps(payload)}\n\n"

                    except (httpx.RequestError, httpx.ReadError, httpx.RemoteProtocolError) as e:
                        logger.warning(
                            "Resubscribe connection error (attempt %d): %s", resub_attempt, e
                        )
                        await asyncio.sleep(2)
                        continue
                    except Exception as e:
                        logger.warning("Resubscribe error (attempt %d): %s", resub_attempt, e)
                        break

                    if _done_received:
                        break

    except httpx.HTTPStatusError as e:
        error_msg = f"Agent error: {e.response.status_code}"
        logger.error("%s: %s", error_msg, e.response.text[:500])
        yield f"data: {json.dumps({'error': error_msg, 'session_id': session_id})}\n\n"
    except (httpx.RequestError, httpx.ReadError, httpx.RemoteProtocolError) as e:
        error_msg = f"Connection error: {str(e)}"
        logger.warning("%s — will poll for completion in finally block", error_msg)
        yield f"data: {json.dumps({'error': error_msg, 'retry': True, 'session_id': session_id})}\n\n"
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        yield f"data: {json.dumps({'error': error_msg, 'session_id': session_id})}\n\n"
    finally:
        logger.info(
            "Stream finally block for session %s: %d loop events, persisted=%s, task_id=%s",
            session_id,
            len(loop_events),
            loop_events_persisted,
            stream_task_id,
        )
        # IMPORTANT: All DB writes and recovery MUST run as background tasks.
        # This finally block runs in an async generator that can be interrupted
        # by GeneratorExit (a BaseException) when the client disconnects.
        # GeneratorExit kills any `await` in progress and is NOT caught by
        # `except Exception`. Background tasks are immune to this.
        if namespace:
            has_reporter = any(e.get("type") == "reporter_output" for e in loop_events)
            logger.info(
                "Spawning background persist+recovery: session=%s task=%s "
                "events=%d has_reporter=%s session_has_loops=%s",
                session_id,
                stream_task_id,
                len(loop_events),
                has_reporter,
                session_has_loops,
            )
            asyncio.create_task(
                _persist_and_recover(
                    namespace=namespace,
                    session_id=session_id,
                    task_db_id=stream_task_id,
                    loop_events=list(loop_events),  # snapshot
                    loop_events_already_persisted=loop_events_persisted,
                    owner=owner,
                    message=message,
                    agent_name=agent_name,
                    session_has_loops=session_has_loops,
                    has_reporter=has_reporter,
                    agent_url=agent_url,
                )
            )


async def _persist_and_recover(
    namespace: str,
    session_id: str,
    task_db_id: Optional[str],
    loop_events: list[dict],
    loop_events_already_persisted: bool = False,
    owner: Optional[str] = None,
    message: Optional[str] = None,
    agent_name: Optional[str] = None,
    session_has_loops: bool = False,
    has_reporter: bool = False,
    agent_url: str = "",
) -> None:
    """Background task: persist metadata + loop events, then recover if needed.

    Runs as a standalone coroutine (not a generator), so it is immune to
    GeneratorExit that would kill the finally block of the SSE generator.

    Always writes metadata (owner, title, agent_name). Only writes loop_events
    if they weren't already persisted by the inline [DONE] handler.
    """
    try:
        if task_db_id is None:
            logger.warning(
                "stream_task_id is None for session %s — cannot persist metadata",
                session_id,
            )
            return

        pool = await get_session_pool(namespace)
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT metadata FROM tasks WHERE id = $1", task_db_id)
            logger.info(
                "BG persist: task %s row_found=%s loop_events=%d already_persisted=%s",
                task_db_id[:12] if task_db_id else "?",
                row is not None,
                len(loop_events),
                loop_events_already_persisted,
            )
            if row:
                meta = _parse_json_field(row["metadata"]) or {}
                logger.info(
                    "BG persist: DB meta BEFORE update session=%s keys=%s agent=%s owner=%s",
                    session_id,
                    list(meta.keys()),
                    meta.get("agent_name", "(none)"),
                    meta.get("owner", "(none)"),
                )
                # Always set metadata fields — the inline _set_owner_metadata
                # may have been killed by GeneratorExit before committing
                if owner:
                    meta["owner"] = owner
                    meta["visibility"] = meta.get("visibility", "private")
                if message:
                    meta["title"] = meta.get("title") or message[:80].replace("\n", " ")
                if agent_name:
                    meta["agent_name"] = agent_name
                if loop_events and not loop_events_already_persisted:
                    meta["loop_events"] = loop_events
                meta_json = json.dumps(meta)
                logger.info(
                    "BG persist: WRITING session=%s agent=%s owner=%s events=%d json_len=%d",
                    session_id,
                    meta.get("agent_name", "(none)"),
                    meta.get("owner", "(none)"),
                    len(meta.get("loop_events", [])),
                    len(meta_json),
                )
                result = await conn.execute(
                    "UPDATE tasks SET metadata = $1::json WHERE id = $2",
                    meta_json,
                    task_db_id,
                )
                logger.info(
                    "BG persist: UPDATE result=%s session=%s task=%s",
                    result,
                    session_id,
                    task_db_id,
                )

        # Recovery: if loop didn't complete, poll agent for remaining events
        if session_has_loops and not has_reporter:
            logger.info("BG persist: triggering recovery for session %s", session_id)
            await _recover_loop_events_from_agent(agent_url, session_id, namespace, task_db_id)
    except Exception:
        logger.warning(
            "BG persist+recover failed for session %s",
            session_id,
            exc_info=True,
        )


async def _recover_loop_events_from_agent(
    agent_url: str,
    session_id: str,
    namespace: str,
    task_db_id: Optional[int],
    max_retries: int = 10,
) -> None:
    """Fallback: poll the agent's A2A task store until the task completes,
    then extract loop_events from the task history.

    This handles the case where nginx dropped the SSE connection (e.g.
    proxy_read_timeout) before the agent finished, causing loop events
    to be lost from the SSE stream. The agent's task store still has the
    complete history.

    Polls with exponential backoff (5s, 10s, 20s, ...) up to max_retries
    attempts, waiting for the task to reach COMPLETED or FAILED state.
    """
    try:
        _TERMINAL_STATES = {"completed", "failed", "canceled"}

        # Use task_db_id (the A2A task ID captured from the stream) to query
        # the agent. The agent stores tasks by their own UUID (task.id), NOT
        # by context_id (session_id). Using session_id here was why recovery
        # always returned "Task not found".
        if not task_db_id:
            logger.warning(
                "Recovery: no A2A task ID available for session %s — cannot query agent",
                session_id,
            )
            return
        logger.info(
            "Recovery: querying agent with a2a_task_id=%s (session=%s)",
            task_db_id,
            session_id,
        )
        a2a_request = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "tasks/get",
            "params": {"id": task_db_id},
        }

        recovered_events: list[dict] = []
        delay = 5.0  # start with 5 seconds

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(1, max_retries + 1):
                resp = await client.post(agent_url, json=a2a_request)
                if resp.status_code != 200:
                    logger.debug(
                        "Recovery attempt %d/%d: tasks/get returned %d for %s",
                        attempt,
                        max_retries,
                        resp.status_code,
                        session_id,
                    )
                    break

                data = resp.json()
                result = data.get("result", {})
                task_state = result.get("status", {}).get("state", "").lower()
                history = result.get("history", [])

                logger.info(
                    "Recovery attempt %d/%d: session=%s state=%s history_msgs=%d",
                    attempt,
                    max_retries,
                    session_id,
                    task_state,
                    len(history),
                )

                if task_state in _TERMINAL_STATES:
                    # Task finished — extract events from history
                    for msg in history:
                        for part in msg.get("parts", []):
                            text = part.get("text", "")
                            for line in text.split("\n"):
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    parsed = json.loads(line)
                                    if isinstance(parsed, dict) and "loop_id" in parsed:
                                        recovered_events.append(parsed)
                                except (json.JSONDecodeError, TypeError):
                                    pass
                    break

                # Task still running — wait with exponential backoff
                if attempt < max_retries:
                    logger.info(
                        "Recovery: agent still processing, waiting %.0fs (attempt %d/%d)",
                        delay,
                        attempt,
                        max_retries,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60.0)  # cap at 60s

        if not recovered_events:
            logger.info("No loop events recovered from agent for %s", session_id)
            return

        logger.info(
            "Recovered %d loop events from agent task store for session %s",
            len(recovered_events),
            session_id,
        )

        # Write recovered events to this stream's task row, replacing any
        # partial set (e.g. just the router event persisted by the finally block)
        pool = await get_session_pool(namespace)
        async with pool.acquire() as conn:
            if task_db_id is None:
                task_db_id = await conn.fetchval(
                    "SELECT id FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
                    session_id,
                )
            if task_db_id is not None:
                row = await conn.fetchrow("SELECT metadata FROM tasks WHERE id = $1", task_db_id)
                if row:
                    meta = _parse_json_field(row["metadata"]) or {}
                    existing = meta.get("loop_events", [])
                    # MERGE: keep SSE-captured events (have prompt data)
                    # and add only NEW events from recovery.
                    # Dedup by (type, step, micro_step) or full JSON.
                    existing_sigs = set()
                    for evt in existing:
                        sig = json.dumps(
                            {
                                k: evt.get(k)
                                for k in ("type", "loop_id", "step", "micro_step", "name")
                            },
                            sort_keys=True,
                        )
                        existing_sigs.add(sig)

                    merged = list(existing)
                    added = 0
                    for evt in recovered_events:
                        sig = json.dumps(
                            {
                                k: evt.get(k)
                                for k in ("type", "loop_id", "step", "micro_step", "name")
                            },
                            sort_keys=True,
                        )
                        if sig not in existing_sigs:
                            merged.append(evt)
                            existing_sigs.add(sig)
                            added += 1

                    if added > 0:
                        meta["loop_events"] = merged
                        await conn.execute(
                            "UPDATE tasks SET metadata = $1::json WHERE id = $2",
                            json.dumps(meta),
                            task_db_id,
                        )
                        logger.info(
                            "Recovery: merged %d existing + %d new events for session %s (total %d)",
                            len(existing),
                            added,
                            session_id,
                            len(merged),
                        )
    except Exception:
        logger.warning(
            "Recovery failed for session %s",
            session_id,
            exc_info=True,
        )


@router.post(
    "/{namespace}/chat/stream",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def chat_stream(
    namespace: str,
    request: SandboxChatRequest,
    user: TokenData = Depends(get_required_user),
):
    """Stream agent responses via Server-Sent Events (SSE).

    Sends the user message to the A2A agent using ``message/stream`` and
    proxies the resulting SSE events back to the browser in real-time,
    so the UI can display intermediate status (thinking, tool execution)
    as well as partial results.

    The connection is kept alive for up to 5 minutes.  If the agent
    disconnects or errors, a final error event is emitted so the client
    can surface the failure gracefully.
    """
    _validate_namespace(namespace)
    session_id = request.session_id or uuid4().hex[:36]

    # Resolve agent name: for existing sessions, use the DB-bound agent
    # (authoritative). For new sessions, trust the request.
    agent_name = await _resolve_agent_name(namespace, request.session_id, request.agent_name)
    agent_url = f"http://{agent_name}.{namespace}.svc.cluster.local:8000"

    return StreamingResponse(
        _stream_sandbox_response(
            agent_url,
            request.message,
            session_id,
            owner=user.username,
            namespace=namespace,
            agent_name=agent_name,
            skill=request.skill,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{namespace}/sessions/{session_id}/subscribe",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def subscribe_session(
    namespace: str,
    session_id: str,
    user: TokenData = Depends(get_required_user),
):
    """Subscribe to a running session's event stream via tasks/resubscribe.

    Used when the UI opens a session that's still in 'working' state.
    Returns an SSE stream of events from the agent without resending
    the original message.
    """
    _validate_namespace(namespace)

    # Look up the A2A task ID and agent name for this session
    pool = await get_session_pool(namespace)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status::json->>'state' as state FROM tasks "
            "WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
            session_id,
        )
    if not row:
        raise HTTPException(404, "Session not found")

    task_id = row["id"]
    state = (row["state"] or "").lower()
    logger.info("Subscribe: session=%s task=%s state=%s", session_id, task_id, state)
    if state in ("completed", "failed", "canceled"):
        # Task already finished — nothing to subscribe to
        logger.info("Subscribe: session=%s already %s — sending done", session_id, state)
        return StreamingResponse(
            _done_stream(session_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    agent_name = await _resolve_agent_name(namespace, session_id, None)
    agent_url = f"http://{agent_name}.{namespace}.svc.cluster.local:8000"

    return StreamingResponse(
        _subscribe_stream(agent_url, task_id, session_id, namespace),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _done_stream(session_id: str):
    """Emit a single done event for already-completed sessions."""
    yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"


async def _subscribe_stream(
    agent_url: str,
    task_id: str,
    session_id: str,
    namespace: str,
):
    """Proxy A2A tasks/resubscribe events to the browser."""
    _KEEPALIVE_INTERVAL = 15
    resub_msg = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "tasks/resubscribe",
        "params": {"id": task_id},
    }

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                agent_url,
                json=resub_msg,
            ) as response:
                if response.status_code != 200:
                    logger.warning("Subscribe: resubscribe returned %d", response.status_code)
                    yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
                    return

                logger.info("Subscribe: connected to agent stream for session %s", session_id)
                line_iter = response.aiter_lines().__aiter__()

                while True:
                    try:
                        line = await asyncio.wait_for(
                            line_iter.__anext__(),
                            timeout=_KEEPALIVE_INTERVAL,
                        )
                    except asyncio.TimeoutError:
                        yield f"data: {json.dumps({'ping': True})}\n\n"
                        continue
                    except StopAsyncIteration:
                        break

                    if not line or not line.startswith("data: "):
                        continue

                    data = line[6:]
                    if data == "[DONE]":
                        logger.info("Subscribe: received [DONE] for session %s", session_id)
                        yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
                        return

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    if "result" not in chunk:
                        continue

                    result = chunk["result"]
                    payload: dict = {"session_id": session_id}

                    # Forward loop events
                    if "status" in result and "message" in result.get("status", {}):
                        parts = result["status"].get("message", {}).get("parts", [])
                        status_message = _extract_text_from_parts(parts)
                        if status_message:
                            _LEGACY = {"plan", "plan_step", "reflection", "llm_response"}
                            for msg_line in [
                                l.strip() for l in status_message.split("\n") if l.strip()
                            ]:
                                try:
                                    parsed = json.loads(msg_line)
                                    if isinstance(parsed, dict) and "loop_id" in parsed:
                                        evt_type = parsed.get("type", "")
                                        if evt_type not in _LEGACY:
                                            loop_payload = dict(payload)
                                            loop_payload["loop_id"] = parsed["loop_id"]
                                            loop_payload["loop_event"] = parsed
                                            yield f"data: {json.dumps(loop_payload)}\n\n"
                                except (json.JSONDecodeError, TypeError):
                                    pass

    except Exception as e:
        logger.warning("Subscribe stream error: %s", e)
        yield f"data: {json.dumps({'error': str(e), 'session_id': session_id})}\n\n"
