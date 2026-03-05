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
                    for key in ("title", "owner", "visibility"):
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
            "SELECT history, artifacts FROM tasks WHERE context_id = $1"
            " ORDER BY COALESCE((status::json->>'timestamp')::text, '') ASC",
            context_id,
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Session not found")

    # Merge history from all task records (ordered by task creation time)
    raw_history: list = []
    seen_user_msgs: set = set()  # Deduplicate user messages across tasks

    # Collect artifacts from all tasks (each task may have a final answer)
    all_artifact_texts: List[str] = []

    for row in rows:
        task_history = _parse_json_field(row["history"]) or []
        for msg in task_history:
            # Deduplicate: skip user messages we've already seen
            if msg.get("role") == "user":
                text = "".join(p.get("text", "") for p in (msg.get("parts") or []))
                key = text[:200]
                if key in seen_user_msgs:
                    continue
                seen_user_msgs.add(key)
            raw_history.append(msg)

        # Accumulate artifacts from ALL task records
        task_artifacts = _parse_json_field(row.get("artifacts")) or []
        if isinstance(task_artifacts, list):
            for art in task_artifacts:
                for part in art.get("parts") or []:
                    if part.get("text"):
                        all_artifact_texts.append(part["text"])

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
        text = "".join(p.get("text", "") for p in (msg.get("parts") or []) if p.get("text"))
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

    return HistoryPage(messages=page, total=total, has_more=has_more)


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
                "metadata": {"username": user.username},
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
                changed = False
                if not meta.get("title"):
                    meta["title"] = request.message[:80].replace("\n", " ")
                    changed = True
                if not meta.get("owner"):
                    meta["owner"] = user.username
                    meta["visibility"] = "private"
                    changed = True
                if not meta.get("agent_name") and request.agent_name:
                    meta["agent_name"] = request.agent_name
                    changed = True
                if changed:
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
    session_has_loops = False  # Session-level flag: once loop_id seen, suppress flat events

    async def _set_owner_metadata():
        """Set owner on session metadata after task is created."""
        nonlocal owner_set
        if owner_set or not owner or not namespace:
            return
        owner_set = True
        try:
            pool = await get_session_pool(namespace)
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT metadata FROM tasks WHERE context_id = $1 ORDER BY id DESC LIMIT 1",
                    session_id,
                )
                if row:
                    meta = _parse_json_field(row["metadata"]) or {}
                    changed = False
                    if not meta.get("owner"):
                        meta["owner"] = owner
                        meta["visibility"] = "private"
                        changed = True
                    if not meta.get("title"):
                        meta["title"] = message[:80].replace("\n", " ")
                        changed = True
                    if agent_name and not meta.get("agent_name"):
                        meta["agent_name"] = agent_name
                        changed = True
                    if changed:
                        # Update ALL task records for this context_id so
                        # the title/owner/agent_name are consistent regardless
                        # of which task record the sidebar query picks up.
                        await conn.execute(
                            "UPDATE tasks SET metadata = $1::json"
                            " WHERE context_id = $2 AND ("
                            "  metadata IS NULL OR"
                            "  metadata::json->>'title' IS NULL"
                            ")",
                            json.dumps(meta),
                            session_id,
                        )
        except Exception:
            logger.debug("Failed to set owner on session %s", session_id)

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

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                agent_url,
                json=a2a_msg,
                headers=headers,
            ) as response:
                response.raise_for_status()
                logger.info("Connected to agent, status=%d", response.status_code)

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    logger.debug("Agent SSE line: %s", line[:300])

                    if line.startswith("data: "):
                        data = line[6:]

                        if data == "[DONE]":
                            logger.info("Received [DONE] from agent")
                            await _set_owner_metadata()
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

                        if "result" not in chunk:
                            continue

                        result = chunk["result"]
                        payload: dict = {"session_id": session_id}
                        if owner:
                            payload["username"] = owner

                        # Set owner after first event (task exists in DB)
                        if not owner_set:
                            await _set_owner_metadata()

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
                            has_loop_events = False
                            if status_message:
                                for msg_line in status_message.split("\n"):
                                    msg_line = msg_line.strip()
                                    if not msg_line:
                                        continue
                                    try:
                                        parsed = json.loads(msg_line)
                                        if isinstance(parsed, dict) and "loop_id" in parsed:
                                            loop_payload = dict(payload)
                                            loop_payload["loop_id"] = parsed["loop_id"]
                                            loop_payload["loop_event"] = parsed
                                            yield f"data: {json.dumps(loop_payload)}\n\n"
                                            has_loop_events = True
                                            session_has_loops = True
                                            continue
                                    except (json.JSONDecodeError, TypeError):
                                        pass

                            # Skip ALL flat events once loop mode is active
                            # (prevents duplicate flat blocks alongside AgentLoopCards)
                            if has_loop_events or session_has_loops:
                                continue

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

    except httpx.HTTPStatusError as e:
        error_msg = f"Agent error: {e.response.status_code}"
        logger.error("%s: %s", error_msg, e.response.text[:500])
        yield f"data: {json.dumps({'error': error_msg, 'session_id': session_id})}\n\n"
    except httpx.RequestError as e:
        error_msg = f"Connection error: {str(e)}"
        logger.error(error_msg)
        yield f"data: {json.dumps({'error': error_msg, 'session_id': session_id})}\n\n"
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        yield f"data: {json.dumps({'error': error_msg, 'session_id': session_id})}\n\n"


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
    agent_url = f"http://{request.agent_name}.{namespace}.svc.cluster.local:8000"
    session_id = request.session_id or uuid4().hex[:36]

    return StreamingResponse(
        _stream_sandbox_response(
            agent_url,
            request.message,
            session_id,
            owner=user.username,
            namespace=namespace,
            agent_name=request.agent_name,
            skill=request.skill,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
