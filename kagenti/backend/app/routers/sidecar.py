# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Sidecar Agents API — manage sidecar lifecycle and observations.

Provides REST endpoints for enabling/disabling sidecars, updating config,
listing observations, and HITL approval/denial. Also provides an SSE
endpoint for streaming sidecar observations in real-time.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.auth import ROLE_VIEWER, require_roles
from app.services.sidecar_manager import (
    SidecarManager,
    SidecarType,
    get_sidecar_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sandbox",
    tags=["sidecars"],
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)


# ── Request/Response Models ──────────────────────────────────────────────────


class EnableRequest(BaseModel):
    auto_approve: bool = False
    config: Optional[dict] = None
    agent_name: str = "sandbox-legion"


class ConfigUpdateRequest(BaseModel):
    interval_seconds: Optional[int] = None
    counter_limit: Optional[int] = None
    warn_threshold_pct: Optional[int] = None
    critical_threshold_pct: Optional[int] = None
    auto_approve: Optional[bool] = None


class SidecarResponse(BaseModel):
    context_id: str
    sidecar_type: str
    parent_context_id: str
    enabled: bool
    auto_approve: bool
    config: dict
    observation_count: int
    pending_count: int


class ObservationResponse(BaseModel):
    id: str
    sidecar_type: str
    timestamp: float
    message: str
    severity: str
    requires_approval: bool


# ── Helper ───────────────────────────────────────────────────────────────────


def _parse_sidecar_type(type_str: str) -> SidecarType:
    try:
        return SidecarType(type_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sidecar type: {type_str}. "
            f"Valid types: {[t.value for t in SidecarType]}",
        )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "/{namespace}/sessions/{context_id}/sidecars",
    response_model=list[SidecarResponse],
    summary="List all sidecars for a session",
)
async def list_sidecars(
    namespace: str,
    context_id: str,
    manager: SidecarManager = Depends(get_sidecar_manager),
):
    # Restore persisted state on first access after restart
    await manager._restore_sidecars_for_session(context_id, namespace)
    return manager.list_sidecars(context_id)


@router.post(
    "/{namespace}/sessions/{context_id}/sidecars/{sidecar_type}/enable",
    response_model=SidecarResponse,
    summary="Enable a sidecar for a session",
)
async def enable_sidecar(
    namespace: str,
    context_id: str,
    sidecar_type: str,
    body: Optional[EnableRequest] = None,
    manager: SidecarManager = Depends(get_sidecar_manager),
):
    st = _parse_sidecar_type(sidecar_type)
    handle = await manager.enable(
        parent_context_id=context_id,
        sidecar_type=st,
        auto_approve=body.auto_approve if body else False,
        config=body.config if body else None,
        namespace=namespace,
        agent_name=body.agent_name if body else "sandbox-legion",
    )
    return handle.to_dict()


@router.post(
    "/{namespace}/sessions/{context_id}/sidecars/{sidecar_type}/disable",
    summary="Disable a sidecar",
)
async def disable_sidecar(
    namespace: str,
    context_id: str,
    sidecar_type: str,
    manager: SidecarManager = Depends(get_sidecar_manager),
):
    st = _parse_sidecar_type(sidecar_type)
    await manager.disable(context_id, st)
    return {"status": "disabled", "sidecar_type": sidecar_type}


@router.put(
    "/{namespace}/sessions/{context_id}/sidecars/{sidecar_type}/config",
    response_model=SidecarResponse,
    summary="Update sidecar config (hot-reload)",
)
async def update_config(
    namespace: str,
    context_id: str,
    sidecar_type: str,
    body: ConfigUpdateRequest,
    manager: SidecarManager = Depends(get_sidecar_manager),
):
    st = _parse_sidecar_type(sidecar_type)
    config = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        handle = await manager.update_config(context_id, st, config)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return handle.to_dict()


@router.post(
    "/{namespace}/sessions/{context_id}/sidecars/{sidecar_type}/reset",
    summary="Reset sidecar state (e.g., Looper counter)",
)
async def reset_sidecar(
    namespace: str,
    context_id: str,
    sidecar_type: str,
    manager: SidecarManager = Depends(get_sidecar_manager),
):
    st = _parse_sidecar_type(sidecar_type)
    # Restore persisted state on first access after restart
    await manager._restore_sidecars_for_session(context_id, namespace)
    handle = manager.get_handle(context_id, st)
    if handle is None:
        raise HTTPException(status_code=404, detail="Sidecar not found")

    # Reset by disabling and re-enabling with same config (fresh analyzer)
    old_config = handle.config.copy()
    old_auto = handle.auto_approve
    ns = handle.namespace
    agent = handle.agent_name
    await manager.disable(context_id, st)
    await manager.enable(
        context_id,
        st,
        auto_approve=old_auto,
        config=old_config,
        namespace=ns,
        agent_name=agent,
    )

    return {"status": "reset", "sidecar_type": sidecar_type}


@router.get(
    "/{namespace}/sessions/{context_id}/sidecars/{sidecar_type}/observations",
    summary="Stream sidecar observations via SSE",
)
async def stream_observations(
    namespace: str,
    context_id: str,
    sidecar_type: str,
    manager: SidecarManager = Depends(get_sidecar_manager),
):
    st = _parse_sidecar_type(sidecar_type)
    # Restore persisted state on first access after restart
    await manager._restore_sidecars_for_session(context_id, namespace)

    async def event_generator():
        last_count = 0
        while True:
            observations = manager.get_observations(context_id, st)
            if len(observations) > last_count:
                for obs in observations[last_count:]:
                    data = json.dumps(
                        {
                            "id": obs.id,
                            "sidecar_type": obs.sidecar_type,
                            "timestamp": obs.timestamp,
                            "message": obs.message,
                            "severity": obs.severity,
                            "requires_approval": obs.requires_approval,
                        }
                    )
                    yield f"data: {data}\n\n"
                last_count = len(observations)
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post(
    "/{namespace}/sessions/{context_id}/sidecars/{sidecar_type}/approve/{msg_id}",
    summary="Approve a pending HITL intervention",
)
async def approve_intervention(
    namespace: str,
    context_id: str,
    sidecar_type: str,
    msg_id: str,
    manager: SidecarManager = Depends(get_sidecar_manager),
):
    st = _parse_sidecar_type(sidecar_type)
    result = await manager.approve_intervention(context_id, st, msg_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Intervention not found")
    return {"status": "approved", "id": msg_id}


@router.post(
    "/{namespace}/sessions/{context_id}/sidecars/{sidecar_type}/deny/{msg_id}",
    summary="Deny a pending HITL intervention",
)
async def deny_intervention(
    namespace: str,
    context_id: str,
    sidecar_type: str,
    msg_id: str,
    manager: SidecarManager = Depends(get_sidecar_manager),
):
    st = _parse_sidecar_type(sidecar_type)
    result = await manager.deny_intervention(context_id, st, msg_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Intervention not found")
    return {"status": "denied", "id": msg_id}
