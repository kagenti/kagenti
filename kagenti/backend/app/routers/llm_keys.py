# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
LLM virtual key management API.

Manages LiteLLM teams (per namespace) and virtual keys (per agent)
through the LiteLLM admin API. The backend holds the master key and
proxies admin operations.

Key hierarchy:
  Master Key (kagenti-system) → Team (namespace) → Agent Key (per-agent)
"""

import logging
import os
import re
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_roles, ROLE_ADMIN, ROLE_VIEWER
from app.services.kubernetes import KubernetesService, get_kubernetes_service

logger = logging.getLogger(__name__)

_K8S_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _safe_log(value: object) -> str:
    """Sanitize user input for logging (CWE-117 log injection prevention)."""
    s = str(value) if not isinstance(value, str) else value
    return s.replace("\n", "\\n").replace("\r", "\\r").replace("\x00", "")


router = APIRouter(prefix="/llm", tags=["llm-keys"])

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://litellm-proxy.kagenti-system.svc:4000")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "")


def _master_headers() -> dict[str, str]:
    if not LITELLM_MASTER_KEY:
        raise HTTPException(
            status_code=503,
            detail="LiteLLM master key not configured (LITELLM_MASTER_KEY env var)",
        )
    return {
        "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TeamCreateRequest(BaseModel):
    namespace: str
    max_budget: float = 500.0
    budget_duration: str = "30d"
    models: Optional[list[str]] = None


class TeamResponse(BaseModel):
    team_id: str
    namespace: str
    max_budget: float = 0.0
    budget_used: float = 0.0
    models: list[str] = []


class KeyCreateRequest(BaseModel):
    namespace: str
    agent_name: str
    max_budget: float = 100.0
    budget_duration: str = "30d"
    models: Optional[list[str]] = None


class KeyResponse(BaseModel):
    key_alias: str
    secret_name: str
    namespace: str


class KeyInfo(BaseModel):
    key_alias: str
    agent_name: str
    max_budget: float = 0.0
    budget_used: float = 0.0
    models: list[str] = []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _litellm_request(
    method: str, path: str, json: dict | None = None, *, allow_conflict: bool = False
) -> dict:
    """Make an authenticated request to LiteLLM admin API."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.request(
            method,
            f"{LITELLM_BASE_URL}{path}",
            headers=_master_headers(),
            json=json,
        )
        if resp.status_code >= 400:
            if allow_conflict and resp.status_code == 400 and "already exists" in resp.text:
                logger.info("LiteLLM %s %s: resource already exists (idempotent)", method, path)
                return {"_already_exists": True}
            logger.warning(
                "LiteLLM %s %s returned %s: %s",
                method,
                path,
                resp.status_code,
                resp.text[:300],
            )
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"LiteLLM error: {resp.text[:300]}",
            )
        return resp.json()


def _extract_keys(data: dict | list) -> list[dict]:
    """Extract key list from litellm /key/list response.

    LiteLLM returns {"keys": [...], "total_count": ...} — NOT {"data": [...]}.
    """
    if isinstance(data, list):
        return [k for k in data if isinstance(k, dict)]
    raw = data.get("keys", data.get("data", []))
    return [k for k in raw if isinstance(k, dict)]


async def _get_team_id(namespace: str) -> str | None:
    """Look up litellm team_id for a namespace by alias."""
    try:
        data = await _litellm_request("GET", "/team/list")
        teams = data if isinstance(data, list) else data.get("data", data.get("teams", []))
        for team in teams:
            if team.get("team_alias") == namespace:
                return team.get("team_id")
    except HTTPException:
        pass
    return None


async def _ensure_team(
    namespace: str, max_budget: float = 500.0, budget_duration: str = "30d"
) -> str:
    """Get or create a litellm team for a namespace. Returns team_id."""
    existing = await _get_team_id(namespace)
    if existing:
        return existing

    data = await _litellm_request(
        "POST",
        "/team/new",
        json={
            "team_alias": namespace,
            "max_budget": max_budget,
            "budget_duration": budget_duration,
        },
    )
    team_id = data.get("team_id", "")
    if not team_id:
        raise HTTPException(status_code=500, detail="LiteLLM did not return team_id")
    logger.info(
        "Created litellm team %s for namespace %s", _safe_log(team_id), _safe_log(namespace)
    )
    return team_id


async def _create_virtual_key(
    team_id: str,
    key_alias: str,
    namespace: str,
    max_budget: float = 100.0,
    budget_duration: str = "30d",
    models: list[str] | None = None,
) -> str:
    """Generate a litellm virtual key under a team. Returns the key token."""
    body: dict = {
        "team_id": team_id,
        "key_alias": key_alias,
        "max_budget": max_budget,
        "budget_duration": budget_duration,
        "metadata": {"namespace": namespace, "agent": key_alias},
    }
    if models:
        body["models"] = models

    data = await _litellm_request("POST", "/key/generate", json=body, allow_conflict=True)
    if data.get("_already_exists"):
        return ""  # Key exists — caller should handle empty return
    key = data.get("token") or data.get("key", "")
    if not key:
        raise HTTPException(status_code=500, detail="LiteLLM did not return a key")
    return key


# ---------------------------------------------------------------------------
# Team endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/teams",
    response_model=TeamResponse,
    dependencies=[Depends(require_roles(ROLE_ADMIN))],
)
async def create_team(
    req: TeamCreateRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Create a litellm team for a namespace and store a default virtual key."""
    team_id = await _ensure_team(req.namespace, req.max_budget, req.budget_duration)

    # Create default namespace key (idempotent — may already exist)
    key = await _create_virtual_key(
        team_id=team_id,
        key_alias=f"{req.namespace}-default",
        namespace=req.namespace,
        max_budget=req.max_budget,
        budget_duration=req.budget_duration,
        models=req.models,
    )

    # Store in k8s secret (only if new key was created)
    if key:
        kube.create_secret(
            namespace=req.namespace,
            name="litellm-virtual-keys",
            string_data={"api-key": key},
            labels={
                "app.kubernetes.io/managed-by": "kagenti",
                "kagenti.io/litellm-team-id": team_id,
            },
        )
    logger.info(
        "Created team %s + default key for namespace %s",
        _safe_log(team_id),
        _safe_log(req.namespace),
    )

    return TeamResponse(
        team_id=team_id,
        namespace=req.namespace,
        max_budget=req.max_budget,
    )


@router.get(
    "/teams",
    response_model=list[TeamResponse],
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_teams():
    """List all litellm teams."""
    try:
        data = await _litellm_request("GET", "/team/list")
    except HTTPException as exc:
        if exc.status_code == 503:
            return []
        raise

    teams_raw = data if isinstance(data, list) else data.get("data", data.get("teams", []))
    return [
        TeamResponse(
            team_id=t.get("team_id", ""),
            namespace=t.get("team_alias", ""),
            max_budget=t.get("max_budget") or 0.0,
            budget_used=t.get("spend") or 0.0,
            models=t.get("models") or [],
        )
        for t in teams_raw
    ]


@router.get(
    "/teams/{namespace}",
    response_model=TeamResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_team(namespace: str):
    """Get team details for a namespace."""
    team_id = await _get_team_id(namespace)
    if not team_id:
        raise HTTPException(status_code=404, detail=f"No team for namespace {namespace}")

    data = await _litellm_request("GET", "/team/list")
    teams_raw = data if isinstance(data, list) else data.get("data", data.get("teams", []))
    for t in teams_raw:
        if t.get("team_id") == team_id:
            return TeamResponse(
                team_id=team_id,
                namespace=namespace,
                max_budget=t.get("max_budget") or 0.0,
                budget_used=t.get("spend") or 0.0,
                models=t.get("models") or [],
            )
    raise HTTPException(status_code=404, detail=f"Team {team_id} not found")


# ---------------------------------------------------------------------------
# Key endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/keys",
    response_model=KeyResponse,
    dependencies=[Depends(require_roles(ROLE_ADMIN))],
)
async def create_agent_key(
    req: KeyCreateRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Create a per-agent virtual key under the namespace's team."""
    team_id = await _ensure_team(req.namespace)

    key = await _create_virtual_key(
        team_id=team_id,
        key_alias=req.agent_name,
        namespace=req.namespace,
        max_budget=req.max_budget,
        budget_duration=req.budget_duration,
        models=req.models,
    )

    secret_name = f"{req.agent_name}-llm-key"
    if key:
        kube.create_secret(
            namespace=req.namespace,
            name=secret_name,
            string_data={"apikey": key},
            labels={
                "app.kubernetes.io/managed-by": "kagenti",
                "kagenti.io/agent": req.agent_name,
                "kagenti.io/litellm-team-id": team_id,
            },
        )
        logger.info(
            "Created agent key for agent %s in %s/%s",
            _safe_log(req.agent_name),
            _safe_log(req.namespace),
            _safe_log(secret_name),
        )
    else:
        logger.info("Agent key for %s already exists (idempotent)", _safe_log(req.agent_name))

    return KeyResponse(
        key_alias=req.agent_name,
        secret_name=secret_name,
        namespace=req.namespace,
    )


@router.get(
    "/keys",
    response_model=list[KeyInfo],
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_keys(namespace: str | None = None):
    """List virtual keys, optionally filtered by namespace."""
    try:
        data = await _litellm_request("GET", "/key/list")
    except HTTPException as exc:
        if exc.status_code == 503:
            return []
        raise

    keys_raw = _extract_keys(data)
    result = []
    for k in keys_raw:
        meta = k.get("metadata") or {}
        ns = meta.get("namespace", "")
        if namespace and ns != namespace:
            continue
        result.append(
            KeyInfo(
                key_alias=k.get("key_alias") or k.get("key_name", ""),
                agent_name=meta.get("agent", k.get("key_alias", "")),
                max_budget=k.get("max_budget") or 0.0,
                budget_used=k.get("spend") or 0.0,
                models=k.get("models") or [],
            )
        )
    return result


@router.delete(
    "/keys/{namespace}/{agent_name}",
    dependencies=[Depends(require_roles(ROLE_ADMIN))],
)
async def delete_agent_key(
    namespace: str,
    agent_name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Revoke an agent's virtual key and delete the k8s secret."""
    # Find the key by alias
    try:
        data = await _litellm_request("GET", "/key/list")
        keys_raw = _extract_keys(data)
        for k in keys_raw:
            if k.get("key_alias") == agent_name:
                token = k.get("token", k.get("key", ""))
                if token:
                    await _litellm_request("POST", "/key/delete", json={"keys": [token]})
                    logger.info("Revoked litellm key for %s", _safe_log(agent_name))
                break
    except HTTPException:
        logger.warning(
            "Could not revoke litellm key for %s (litellm may be down)", _safe_log(agent_name)
        )

    # Delete k8s secret
    secret_name = f"{agent_name}-llm-key"
    try:
        kube.core_api.delete_namespaced_secret(secret_name, namespace)
        logger.info("Deleted secret %s/%s", _safe_log(namespace), _safe_log(secret_name))
    except Exception:
        logger.warning(
            "Could not delete secret %s/%s", _safe_log(namespace), _safe_log(secret_name)
        )

    return {"status": "deleted", "agent_name": agent_name, "namespace": namespace}


# ---------------------------------------------------------------------------
# Agent model access endpoint (for chat model selector)
# ---------------------------------------------------------------------------


@router.get(
    "/agent-models/{namespace}/{agent_name}",
    response_model=list[dict],
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_agent_models(namespace: str, agent_name: str):
    """Get models accessible by a specific agent's virtual key.

    If the agent has a scoped key with model restrictions, returns only
    those models. Otherwise falls back to all models available on litellm.
    """
    # Try to find agent-specific key with model restrictions
    try:
        data = await _litellm_request("GET", "/key/list")
        keys_raw = _extract_keys(data)
        for k in keys_raw:
            if k.get("key_alias") == agent_name:
                agent_models = k.get("models") or []
                if agent_models:
                    return [{"id": m} for m in agent_models]
                break
    except HTTPException:
        pass

    # Fallback: return all models from litellm
    try:
        data = await _litellm_request("GET", "/models")
        raw = data.get("data", [])
        return [{"id": item["id"]} for item in raw if isinstance(item, dict) and "id" in item]
    except HTTPException:
        return []
