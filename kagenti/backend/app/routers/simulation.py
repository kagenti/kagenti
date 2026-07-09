# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Simulated MCP tools API endpoints (epic #2151).

Mounted only when ``kagenti_feature_flag_simulated_tools`` is enabled
(see ``app/main.py``). This module owns the create path that provisions a
simulated tool's workload (StatefulSet + per-tool PVC + Service). Generation
orchestration, lifecycle, and database re-seed attach in later issues.
"""

import logging
from datetime import datetime, timezone
from typing import List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from kubernetes.client import ApiException
from pydantic import BaseModel, field_validator

from app.core.auth import ROLE_OPERATOR, ROLE_VIEWER, require_roles
from app.core.config import settings
from app.core.constants import APP_KUBERNETES_IO_NAME, DEFAULT_IN_CLUSTER_PORT
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.services.simulation_harness_client import (
    HarnessNotFound,
    HarnessUnreachable,
    get_simulation,
)
from app.services.simulation_manifests import (
    EnvVar,
    build_simulation_env_vars,
    build_simulation_service,
    build_simulation_statefulset,
    derive_simulation_name,
    validate_custom_name,
    validate_namespace,
    validate_openapi_spec,
    validate_storage_size,
)
from app.utils.routes import sanitize_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulation", tags=["simulation"])


class SimulationHealthResponse(BaseModel):
    """Health response confirming the simulation router is mounted."""

    status: str


class SimulationCreateRequest(BaseModel):
    """Request to create a simulated tool from an OpenAPI spec."""

    namespace: str
    openapiSpec: str
    name: Optional[str] = None
    envVars: Optional[List[EnvVar]] = None
    storageSize: str = "1Gi"
    spireEnabled: bool = False
    authBridgeEnabled: bool = False
    authBridgeMode: Optional[Literal["proxy-sidecar", "envoy-sidecar", "lite", "waypoint"]] = None

    @field_validator("namespace")
    @classmethod
    def _check_namespace(cls, v: str) -> str:
        return validate_namespace(v)

    @field_validator("storageSize")
    @classmethod
    def _check_storage_size(cls, v: str) -> str:
        return validate_storage_size(v)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: Optional[str]) -> Optional[str]:
        return v if v is None else validate_custom_name(v)


class SimulationCreateResponse(BaseModel):
    """Response after starting a simulated-tool creation."""

    success: bool
    name: str
    namespace: str
    status: str
    message: str


class GenerationStatusResponse(BaseModel):
    """UI-pollable generation status for a simulated tool (issue #2162)."""

    status: str  # Generating | Ready | Failed | Error
    reason: Optional[str] = None
    mcpUrl: Optional[str] = None


# Container waiting reasons that indicate a runtime/pod-level Error (not a
# harness generation failure): missing LLM secret, bad image, crash loop.
POD_ERROR_REASONS = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
}


def map_generation_status(
    harness: Optional[dict],
    pod_ready: bool,
    pod_waiting_reason: Optional[str],
    pod_waiting_message: Optional[str],
    elapsed_seconds: float,
    timeout_seconds: int,
) -> GenerationStatusResponse:
    """Map live harness + pod state to a stable UI phase.

    `harness` is the parsed GET /api/v1/simulation body, or None when the harness
    is unreachable or reports 404 (no simulation active yet). Pure — the caller
    supplies elapsed time so this is fully unit-testable.
    """
    if harness is not None:
        status = harness.get("status")
        if status == "ready":
            return GenerationStatusResponse(
                status="Ready", reason=None, mcpUrl=harness.get("mcp_url")
            )
        if status == "failed":
            err = harness.get("error") or {}
            code = err.get("code") or "unknown"
            message = err.get("message") or ""
            reason = f"{code}: {message}" if message else code
            return GenerationStatusResponse(status="Failed", reason=reason, mcpUrl=None)
        # pending / generating_skill / initializing / generated
        return GenerationStatusResponse(status="Generating", reason=None, mcpUrl=None)

    # Harness unreachable or no simulation yet — distinguish "still starting"
    # from "crash-looping" via pod state, and cap the wait with the watchdog.
    if pod_waiting_reason in POD_ERROR_REASONS:
        reason = pod_waiting_reason
        if pod_waiting_message:
            reason = f"{pod_waiting_reason}: {pod_waiting_message}"
        return GenerationStatusResponse(status="Error", reason=reason, mcpUrl=None)
    if elapsed_seconds > timeout_seconds:
        return GenerationStatusResponse(status="Failed", reason="generation_stalled", mcpUrl=None)
    return GenerationStatusResponse(status="Generating", reason=None, mcpUrl=None)


@router.get("/health", response_model=SimulationHealthResponse)
async def simulation_health() -> SimulationHealthResponse:
    """Return OK when the flag-gated simulation router is mounted."""
    logger.debug("simulation router health check")
    return SimulationHealthResponse(status="ok")


@router.post(
    "/tools",
    status_code=202,
    response_model=SimulationCreateResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def create_simulated_tool(
    request: SimulationCreateRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SimulationCreateResponse:
    """Provision a simulated tool's workload (StatefulSet + PVC + Service).

    Validates the spec synchronously (422 on invalid, no workload created), then
    creates the workload and returns 202 with a Generating status. Posting the
    spec to the harness and polling generation status is handled in issue #2162.
    """
    try:
        spec = validate_openapi_spec(request.openapiSpec)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    name = derive_simulation_name(spec, request.name)
    port = DEFAULT_IN_CLUSTER_PORT

    kube.ensure_service_account(namespace=request.namespace, name=name)
    env_vars = build_simulation_env_vars(request.envVars, port=port)
    statefulset = build_simulation_statefulset(
        name=name,
        namespace=request.namespace,
        image=settings.simulation_harness_image,
        env_vars=env_vars,
        port=port,
        storage_size=request.storageSize,
        spire_enabled=request.spireEnabled,
        auth_bridge_enabled=request.authBridgeEnabled,
        auth_bridge_mode=request.authBridgeMode,
        image_pull_secret=settings.simulation_image_pull_secret or None,
        image_pull_policy=settings.simulation_image_pull_policy,
    )
    service = build_simulation_service(name, request.namespace, port=port)

    try:
        kube.create_statefulset(request.namespace, statefulset)
        kube.create_service(request.namespace, service)
    except ApiException as e:
        if e.status == 409:
            raise HTTPException(
                status_code=409,
                detail=f"Simulated tool '{name}' already exists in namespace '{request.namespace}'",
            )
        logger.error(
            "Failed to provision simulated tool '%s': %s",
            sanitize_log(name),
            sanitize_log(str(e)),
        )
        raise HTTPException(status_code=502, detail="Failed to create simulated-tool resources")

    logger.info(
        "Provisioned simulated tool '%s' in namespace '%s'",
        sanitize_log(name),
        sanitize_log(request.namespace),
    )
    return SimulationCreateResponse(
        success=True,
        name=name,
        namespace=request.namespace,
        status="Generating",
        message=f"Simulated tool '{name}' provisioning started.",
    )


@router.get(
    "/tools/{namespace}/{name}/generation-status",
    response_model=GenerationStatusResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def generation_status(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> GenerationStatusResponse:
    """Return the live, UI-pollable generation status of a simulated tool.

    Reads harness `GET /api/v1/simulation` plus pod state on every call and maps
    to Generating / Ready / Failed / Error. A watchdog derived from the
    StatefulSet's creationTimestamp turns a never-started generation into Failed
    rather than hanging (issue #2162).
    """
    try:
        sts = kube.apps_api.read_namespaced_stateful_set(name=name, namespace=namespace)
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Simulated tool '{name}' not found in namespace '{namespace}'",
            )
        logger.error(
            "Failed to read simulated tool '%s' in '%s': %s",
            sanitize_log(name),
            sanitize_log(namespace),
            sanitize_log(str(e)),
        )
        raise HTTPException(status_code=502, detail="Failed to read simulated-tool workload")

    created = sts.metadata.creation_timestamp
    elapsed = (datetime.now(timezone.utc) - created).total_seconds() if created else 0.0

    base_url = f"http://{name}.{namespace}.svc.cluster.local:{DEFAULT_IN_CLUSTER_PORT}"
    harness = None
    try:
        harness = await get_simulation(base_url)
    except HarnessNotFound:
        harness = None
    except (HarnessUnreachable, httpx.HTTPError) as e:
        logger.debug("Harness read failed for '%s': %s", sanitize_log(name), sanitize_log(str(e)))
        harness = None

    pod = kube.get_workload_pod_status(namespace, f"{APP_KUBERNETES_IO_NAME}={name}")
    return map_generation_status(
        harness=harness,
        pod_ready=pod["ready"],
        pod_waiting_reason=pod["waiting_reason"],
        pod_waiting_message=pod["waiting_message"],
        elapsed_seconds=elapsed,
        timeout_seconds=settings.simulation_generation_timeout,
    )
