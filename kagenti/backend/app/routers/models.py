# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Available LLM models endpoint.

Proxies the LiteLLM /models list and caches for 5 minutes.
"""

import logging
import os
import time
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends

from app.core.auth import require_roles, ROLE_VIEWER

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

# ---------------------------------------------------------------------------
# Configuration (same env vars as token_usage.py)
# ---------------------------------------------------------------------------

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://litellm-proxy.kagenti-system.svc:4000")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")

# ---------------------------------------------------------------------------
# In-memory cache (5 minutes)
# ---------------------------------------------------------------------------

_cache: Dict[str, Any] = {"models": [], "expires_at": 0.0}
CACHE_TTL_SECONDS = 300


async def _fetch_models() -> List[Dict[str, str]]:
    """Fetch model list from LiteLLM /models, with 5-minute cache."""
    now = time.monotonic()
    if _cache["models"] and now < _cache["expires_at"]:
        return _cache["models"]

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{LITELLM_BASE_URL}/models", headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "LiteLLM /models returned %s: %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return _cache["models"]  # return stale cache on error
    except httpx.RequestError as exc:
        logger.warning("LiteLLM /models request failed: %s", exc)
        return _cache["models"]

    # LiteLLM returns OpenAI-compatible {"data": [{"id": "model-name", ...}]}
    raw = payload.get("data", [])
    models = [{"id": item["id"]} for item in raw if isinstance(item, dict) and "id" in item]

    _cache["models"] = models
    _cache["expires_at"] = now + CACHE_TTL_SECONDS
    return models


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=List[Dict[str, str]],
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_models():
    """Return available LLM models from LiteLLM."""
    return await _fetch_models()
