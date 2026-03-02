# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Sandbox Trigger API — create sandboxes from cron, webhook, and alert events.

Creates kubernetes-sigs SandboxClaim resources via the SandboxTrigger module.
Requires ROLE_OPERATOR for all operations (creates K8s resources).
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_roles, ROLE_OPERATOR

# Add deployments/sandbox to path for trigger module
# Walk up to find repo root (works at any depth, including containers)
_this_dir = Path(__file__).resolve().parent
_sandbox_dir = None
for _parent in _this_dir.parents:
    _candidate = _parent / "deployments" / "sandbox"
    if _candidate.is_dir():
        _sandbox_dir = _candidate
        break
if _sandbox_dir and str(_sandbox_dir) not in sys.path:
    sys.path.insert(0, str(_sandbox_dir))

from triggers import SandboxTrigger  # noqa: E402  # pylint: disable=wrong-import-position,wrong-import-order

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["sandbox-triggers"])


class TriggerRequest(BaseModel):
    """Request body for creating a sandbox trigger."""

    type: str  # "cron", "webhook", "alert"
    # Cron fields
    skill: Optional[str] = None
    schedule: Optional[str] = ""
    # Webhook fields
    event: Optional[str] = None
    repo: Optional[str] = None
    branch: Optional[str] = "main"
    pr_number: Optional[int] = 0
    # Alert fields
    alert: Optional[str] = None
    cluster: Optional[str] = ""
    severity: Optional[str] = "warning"
    # Common
    namespace: Optional[str] = "team1"
    ttl_hours: Optional[int] = 2


class TriggerResponse(BaseModel):
    """Response from sandbox trigger creation."""

    sandbox_claim: str
    namespace: str


@router.post(
    "/trigger",
    response_model=TriggerResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def create_sandbox_trigger(request: TriggerRequest) -> TriggerResponse:
    """Create a sandbox from a trigger event.

    Requires ROLE_OPERATOR — creates SandboxClaim K8s resources.
    """
    trigger = SandboxTrigger(
        namespace=request.namespace,
        ttl_hours=request.ttl_hours,
    )

    try:
        if request.type == "cron":
            if not request.skill:
                raise HTTPException(422, "skill is required for cron triggers")
            name = trigger.create_from_cron(
                skill=request.skill,
                schedule=request.schedule or "",
            )
        elif request.type == "webhook":
            if not request.event or not request.repo:
                raise HTTPException(422, "event and repo are required for webhook triggers")
            name = trigger.create_from_webhook(
                event_type=request.event,
                repo=request.repo,
                branch=request.branch or "main",
                pr_number=request.pr_number or 0,
            )
        elif request.type == "alert":
            if not request.alert:
                raise HTTPException(422, "alert is required for alert triggers")
            name = trigger.create_from_alert(
                alert_name=request.alert,
                cluster=request.cluster or "",
                severity=request.severity or "warning",
            )
        else:
            raise HTTPException(400, f"Unknown trigger type: {request.type}")
    except RuntimeError as e:
        logger.error("Failed to create sandbox trigger: %s", e)
        raise HTTPException(500, str(e))

    return TriggerResponse(sandbox_claim=name, namespace=trigger.namespace)
