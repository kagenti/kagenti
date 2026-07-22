# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Skill "dreaming" API (feature flag: rossoctl_feature_flag_dreaming).

POST /api/v1/dream/{namespace}/{agent}        trigger a dream run (operator)
GET  /api/v1/dream/{namespace}/{agent}        dream state / watermark (viewer)
PUT  /api/v1/dream/{namespace}/{agent}/thresholds   set auto-trigger thresholds

Requires the skillberry-store (installed with the ask-runspace plugin) to be
reachable; its URL comes from the skill auto-sync ConfigMap.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import require_roles, ROLE_OPERATOR, ROLE_VIEWER
from app.core.config import settings
from app.core.constants import SKILL_AUTOSYNC_CONFIG_CM
from app.services import dream_state, dreaming
from app.services.kubernetes import KubernetesService, get_kubernetes_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dream", tags=["dreaming"])

_ROSSOCTL_SYSTEM = "rossoctl-system"


def _scrub(value: str) -> str:
    """Strip CR/LF from a user-supplied value before logging (log-injection)."""
    return str(value).replace("\r", " ").replace("\n", " ")


class DreamStatus(BaseModel):
    """Current dream state for an agent."""

    namespace: str
    agent: str
    lastDreamedTs: str | None = None
    lastDreamedAt: str | None = None
    lastRunId: str = ""
    dreamedCount: int = 0
    minNewTrajectories: int = 0
    minIntervalSeconds: int = 0
    # Weekly schedule: days (e.g. ["sun","mon"]) at scheduleTime ("HH:MM", 24h, local).
    scheduleDays: list[str] = Field(default_factory=list)
    scheduleTime: str = ""
    # New (un-dreamed) trajectories currently available to dream on, from Phoenix.
    newTrajectories: int = 0


class ThresholdRequest(BaseModel):
    """Auto-trigger thresholds (persisted; not evaluated automatically in v1).

    Two complementary triggers: a count/interval trigger and/or a weekly
    schedule (dream on the given weekdays at ``scheduleTime``).
    """

    minNewTrajectories: int = Field(0, ge=0)
    minIntervalSeconds: int = Field(0, ge=0)
    scheduleDays: list[str] = Field(default_factory=list)
    scheduleTime: str = Field("", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")


def _require_flag() -> None:
    if not settings.rossoctl_feature_flag_dreaming:
        raise HTTPException(status_code=404, detail="Not Found")


def _resolve_store_url(kube: KubernetesService) -> str:
    """The skillberry-store URL from the skill auto-sync ConfigMap's registry-url."""
    registry_url = None
    try:
        cm = kube.core_api.read_namespaced_config_map(
            name=SKILL_AUTOSYNC_CONFIG_CM, namespace=_ROSSOCTL_SYSTEM
        )
        registry_url = (cm.data or {}).get("registry-url")
    except Exception:  # pylint: disable=broad-except
        registry_url = None
    try:
        return dreaming.resolve_store_url(registry_url)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/{namespace}/{agent}", response_model=DreamStatus)
async def get_dream_status(
    namespace: str,
    agent: str,
    _=Depends(require_roles(ROLE_VIEWER)),
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Return dream watermark/state for an agent."""
    _require_flag()
    state = dream_state.get_state(kube, namespace, agent) or {}
    cursor = state.get("last_dreamed_ts")

    # Best-effort: how many new (un-dreamed) trajectories are waiting in Phoenix.
    new_trajectories = 0
    try:
        project = settings.dreaming_phoenix_project or agent
        spans = await dreaming.fetch_new_spans(
            dreaming.resolve_phoenix_url(), project, cursor, settings.dreaming_max_events
        )
        new_trajectories = dreaming.count_trajectories(spans)
    except Exception:  # pylint: disable=broad-except
        new_trajectories = 0

    return DreamStatus(
        namespace=namespace,
        agent=agent,
        lastDreamedTs=state.get("last_dreamed_ts"),
        lastDreamedAt=state.get("last_dreamed_at"),
        lastRunId=state.get("last_run_id") or "",
        dreamedCount=int(state.get("dreamed_count", 0)),
        minNewTrajectories=int(state.get("min_new_trajectories", 0)),
        minIntervalSeconds=int(state.get("min_interval_seconds", 0)),
        scheduleDays=list(state.get("schedule_days", []) or []),
        scheduleTime=state.get("schedule_time", "") or "",
        newTrajectories=new_trajectories,
    )


@router.post("/{namespace}/{agent}", dependencies=[Depends(require_roles(ROLE_OPERATOR))])
async def trigger_dream(
    namespace: str,
    agent: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Trigger a dream run: read NEW Phoenix trajectories → RunSpace optimization.

    Requires the skillberry-store installed with the ask-runspace plugin (hosts
    the /run endpoint) and Phoenix tracing (the trajectory source).
    """
    _require_flag()
    store_url = _resolve_store_url(kube)
    phoenix_url = dreaming.resolve_phoenix_url()
    try:
        return await dreaming.run_dream(kube, namespace, agent, store_url, phoenix_url)
    except Exception as exc:  # pylint: disable=broad-except
        # namespace/agent are user-supplied path params; strip CR/LF so they
        # can't forge log lines (CodeQL log-injection).
        logger.exception("Dream run failed for %s/%s", _scrub(namespace), _scrub(agent))
        raise HTTPException(status_code=502, detail=f"Dream run failed: {exc}")


class DreamRunStatus(BaseModel):
    """Status + result of a submitted dream (RunSpace) run."""

    runId: str
    status: str | None = None  # pending | ready | failed
    summaryMd: str | None = None  # RunSpace summary.md (what it optimized), when ready


@router.get("/{namespace}/{agent}/runs/{run_id}", response_model=DreamRunStatus)
async def get_dream_run(
    namespace: str,
    agent: str,
    run_id: str,
    _=Depends(require_roles(ROLE_VIEWER)),
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Poll a dream run's progress + result (RunSpace summary) via the store."""
    _require_flag()
    store_url = _resolve_store_url(kube)
    try:
        s = await dreaming.get_run_status(store_url, run_id)
    except ValueError as exc:  # invalid run id
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail=f"Failed to fetch run status: {exc}")

    # Commit the watermark only once the run has actually succeeded; drop it on
    # failure so the trajectories are re-dreamed rather than lost.
    status = s.get("status")
    if status == "ready":
        dream_state.commit_pending_cursor(kube, namespace, agent, run_id)
    elif status == "failed":
        dream_state.clear_pending_cursor(kube, namespace, agent, run_id)
    return DreamRunStatus(runId=run_id, status=status, summaryMd=s.get("summary_md"))


@router.put(
    "/{namespace}/{agent}/thresholds",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def set_thresholds(
    namespace: str,
    agent: str,
    req: ThresholdRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Persist auto-trigger thresholds (stored for a future iteration)."""
    _require_flag()
    dream_state.set_thresholds(
        kube,
        namespace,
        agent,
        req.minNewTrajectories,
        req.minIntervalSeconds,
        schedule_days=req.scheduleDays,
        schedule_time=req.scheduleTime,
    )
    return {"status": "ok", "namespace": namespace, "agent": agent}
