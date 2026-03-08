# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Token usage analytics endpoints.

Proxies LiteLLM spend data and aggregates per-model token usage
for individual sessions and session trees (parent + children).
"""

import logging
import os
from collections import defaultdict
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import require_roles, ROLE_VIEWER
from app.services.session_db import get_session_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/token-usage", tags=["token-usage"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://litellm-proxy.kagenti-system.svc:4000")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")

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


async def _fetch_spend_logs(session_id: str) -> List[Dict[str, Any]]:
    """Fetch spend logs from LiteLLM filtered by session_id metadata."""
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"

    params = {
        "request_id": "",  # required by LiteLLM but can be empty
        "api_key": "",
        "user_id": "",
        "start_date": "",
        "end_date": "",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            # LiteLLM /spend/logs supports metadata filtering via query params
            response = await client.get(
                f"{LITELLM_BASE_URL}/spend/logs",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            logs = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "LiteLLM /spend/logs returned %s: %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return []
        except httpx.RequestError as exc:
            logger.warning("LiteLLM request failed: %s", exc)
            return []

    # Filter logs by session_id in spend_logs_metadata
    filtered: List[Dict[str, Any]] = []
    if not isinstance(logs, list):
        logs = []
    for log in logs:
        meta = log.get("metadata") or {}
        spend_meta = meta.get("spend_logs_metadata") or {}
        tags = meta.get("tags") or []

        # Match by spend_logs_metadata.session_id or tag
        if spend_meta.get("session_id") == session_id:
            filtered.append(log)
        elif f"session_id:{session_id}" in tags:
            filtered.append(log)

    return filtered


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


@router.get(
    "/sessions/{context_id}",
    response_model=SessionTokenUsage,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_session_token_usage(context_id: str):
    """Per-model token usage for a single session."""
    logs = await _fetch_spend_logs(context_id)
    return _aggregate_by_model(logs, context_id)


@router.get(
    "/sessions/{context_id}/tree",
    response_model=SessionTreeUsage,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_session_tree_usage(context_id: str, namespace: str = "team1"):
    """Token usage for a session including all child sessions."""
    # 1. Get own usage
    own_logs = await _fetch_spend_logs(context_id)
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
        child_logs = await _fetch_spend_logs(child_id)
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
