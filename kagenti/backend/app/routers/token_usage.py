# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Token usage analytics endpoints.

Proxies LiteLLM spend data and aggregates per-model token usage
for individual sessions and session trees (parent + children).
"""

import json
import logging
import os
import re
from collections import defaultdict
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import require_roles, ROLE_VIEWER
from app.services.session_db import get_session_pool

logger = logging.getLogger(__name__)


def _safe_log(value: object) -> str:
    """Sanitize user input for logging (CWE-117 log injection prevention)."""
    s = str(value) if not isinstance(value, str) else value
    return s.replace("\n", "\\n").replace("\r", "\\r").replace("\x00", "")


# Kubernetes-style name validation (RFC 1123 DNS label)
_K8S_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

router = APIRouter(prefix="/token-usage", tags=["token-usage"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://litellm-proxy.kagenti-system.svc:4000")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
LLM_BUDGET_PROXY_URL = os.getenv("LLM_BUDGET_PROXY_URL", "http://llm-budget-proxy.team1.svc:8080")

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ModelUsage(BaseModel):  # pylint: disable=too-few-public-methods
    """Per-model token usage breakdown."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    num_calls: int
    cost: float


class SessionTokenUsage(BaseModel):  # pylint: disable=too-few-public-methods
    """Aggregated token usage for a session."""

    context_id: str
    models: List[ModelUsage]
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_calls: int
    total_cost: float


class SessionTreeUsage(BaseModel):  # pylint: disable=too-few-public-methods
    """Token usage for a session tree (parent + children)."""

    context_id: str
    own_usage: SessionTokenUsage
    children: List[SessionTokenUsage]
    aggregate: SessionTokenUsage


# ---------------------------------------------------------------------------
# LiteLLM helpers
# ---------------------------------------------------------------------------


async def _fetch_spend_by_request_id(request_id: str) -> List[Dict[str, Any]]:
    """Fetch spend logs from LiteLLM for a single request_id."""
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(
                f"{LITELLM_BASE_URL}/spend/logs",
                headers=headers,
                params={"request_id": request_id},
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "LiteLLM /spend/logs returned %s for request_id=%s: %s",
                exc.response.status_code,
                request_id,
                exc.response.text[:200],
            )
            return []
        except httpx.RequestError as exc:
            logger.warning("LiteLLM request failed for request_id=%s: %s", request_id, exc)
            return []

    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) and data else []


def _aggregate_by_model(logs: List[Dict[str, Any]], context_id: str) -> SessionTokenUsage:
    """Group spend logs by model and sum tokens/cost."""
    by_model: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "num_calls": 0,
            "cost": 0.0,
        }
    )

    for log in logs:
        model = log.get("model") or "unknown"
        prompt = log.get("prompt_tokens") or 0
        completion = log.get("completion_tokens") or 0
        total = log.get("total_tokens") or (prompt + completion)
        cost = log.get("spend") or 0.0

        entry = by_model[model]
        entry["prompt_tokens"] += prompt
        entry["completion_tokens"] += completion
        entry["total_tokens"] += total
        entry["num_calls"] += 1
        entry["cost"] += cost

    models = [ModelUsage(model=model, **stats) for model, stats in sorted(by_model.items())]

    return SessionTokenUsage(
        context_id=context_id,
        models=models,
        total_prompt_tokens=sum(m.prompt_tokens for m in models),
        total_completion_tokens=sum(m.completion_tokens for m in models),
        total_tokens=sum(m.total_tokens for m in models),
        total_calls=sum(m.num_calls for m in models),
        total_cost=sum(m.cost for m in models),
    )


def _merge_usages(context_id: str, usages: List[SessionTokenUsage]) -> SessionTokenUsage:
    """Merge multiple SessionTokenUsage objects into a single aggregate."""
    by_model: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "num_calls": 0,
            "cost": 0.0,
        }
    )
    for usage in usages:
        for m in usage.models:
            entry = by_model[m.model]
            entry["prompt_tokens"] += m.prompt_tokens
            entry["completion_tokens"] += m.completion_tokens
            entry["total_tokens"] += m.total_tokens
            entry["num_calls"] += m.num_calls
            entry["cost"] += m.cost

    models = [ModelUsage(model=model, **stats) for model, stats in sorted(by_model.items())]
    return SessionTokenUsage(
        context_id=context_id,
        models=models,
        total_prompt_tokens=sum(m.prompt_tokens for m in models),
        total_completion_tokens=sum(m.completion_tokens for m in models),
        total_tokens=sum(m.total_tokens for m in models),
        total_calls=sum(m.num_calls for m in models),
        total_cost=sum(m.cost for m in models),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


async def _get_request_ids_from_metadata(context_id: str, namespace: str) -> List[str]:
    """Read llm_request_ids from the session's task metadata."""
    try:
        pool = await get_session_pool(namespace)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT metadata FROM tasks WHERE context_id = $1 LIMIT 1",
                context_id,
            )
        if row and row["metadata"]:
            meta = (
                json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
            )
            return meta.get("llm_request_ids", [])
    except Exception as exc:
        logger.warning(
            "Failed to query task metadata for context_id=%s: %s", _safe_log(context_id), exc
        )
    return []


async def _fetch_from_budget_proxy(context_id: str) -> SessionTokenUsage | None:
    """Try to fetch session usage from the LLM Budget Proxy."""
    # Validate context_id to prevent SSRF via path traversal (CWE-918)
    if not _K8S_NAME_RE.match(context_id) and not re.match(r"^[a-zA-Z0-9_-]+$", context_id):
        logger.warning("Invalid context_id rejected for budget proxy: %s", _safe_log(context_id))
        return None

    # Defense-in-depth: re-validate right before URL construction (CWE-918)
    safe_id = context_id
    if not re.match(r"^[a-zA-Z0-9_-]+$", safe_id):
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{LLM_BUDGET_PROXY_URL}/internal/usage/{safe_id}")
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("Budget proxy unavailable for %s: %s", _safe_log(context_id), exc)
            return None

    if not data.get("call_count"):
        return None

    models = [
        ModelUsage(
            model=m.get("model", "unknown"),
            prompt_tokens=m.get("prompt_tokens", 0),
            completion_tokens=m.get("completion_tokens", 0),
            total_tokens=m.get("total_tokens", 0),
            num_calls=m.get("num_calls", 0),
            cost=m.get("cost", 0.0),
        )
        for m in data.get("models", [])
    ]
    return SessionTokenUsage(
        context_id=context_id,
        models=models,
        total_prompt_tokens=data.get("prompt_tokens", 0),
        total_completion_tokens=data.get("completion_tokens", 0),
        total_tokens=data.get("total_tokens", 0),
        total_calls=data.get("call_count", 0),
        total_cost=sum(m.cost for m in models),
    )


@router.get(
    "/sessions/{context_id}",
    response_model=SessionTokenUsage,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_session_token_usage(context_id: str, namespace: str = "team1"):
    """Per-model token usage for a single session.

    Queries the LLM Budget Proxy first (authoritative, persists across
    restarts). Falls back to LiteLLM spend logs if the proxy is unavailable.
    """
    # Try budget proxy first
    proxy_result = await _fetch_from_budget_proxy(context_id)
    if proxy_result:
        return proxy_result

    # Fallback: LiteLLM spend logs
    request_ids = await _get_request_ids_from_metadata(context_id, namespace)
    logs: List[Dict[str, Any]] = []
    for rid in request_ids:
        spend = await _fetch_spend_by_request_id(rid)
        if spend:
            logs.extend(spend)
    return _aggregate_by_model(logs, context_id)


@router.get(
    "/sessions/{context_id}/tree",
    response_model=SessionTreeUsage,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_session_tree_usage(context_id: str, namespace: str = "team1"):
    """Token usage for a session including all child sessions."""
    # 1. Get own usage
    own_request_ids = await _get_request_ids_from_metadata(context_id, namespace)
    own_logs: List[Dict[str, Any]] = []
    for rid in own_request_ids:
        spend = await _fetch_spend_by_request_id(rid)
        if spend:
            own_logs.extend(spend)
    own_usage = _aggregate_by_model(own_logs, context_id)

    # 2. Find child sessions from the tasks table
    children_usage: List[SessionTokenUsage] = []
    try:
        pool = await get_session_pool(namespace)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT context_id FROM tasks"
                " WHERE metadata::json->>'parent_context_id' = $1",
                context_id,
            )
        child_ids = [row["context_id"] for row in rows]
    except Exception as exc:
        logger.warning("Failed to query child sessions: %s", exc)
        child_ids = []

    # 3. Fetch usage for each child
    for child_id in child_ids:
        child_request_ids = await _get_request_ids_from_metadata(child_id, namespace)
        child_logs: List[Dict[str, Any]] = []
        for rid in child_request_ids:
            spend = await _fetch_spend_by_request_id(rid)
            if spend:
                child_logs.extend(spend)
        children_usage.append(_aggregate_by_model(child_logs, child_id))

    # 4. Build aggregate
    all_usages = [own_usage] + children_usage
    aggregate = _merge_usages(context_id, all_usages)

    return SessionTreeUsage(
        context_id=context_id,
        own_usage=own_usage,
        children=children_usage,
        aggregate=aggregate,
    )
