# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Simulated MCP tools API endpoints (epic #2151).

Mounted only when ``kagenti_feature_flag_simulated_tools`` is enabled
(see ``app/main.py``). This module owns the create path that provisions a
simulated tool's workload (StatefulSet + per-tool PVC + Service), the
generation-trigger task that posts the spec to the harness, and the
generation-status endpoint that surfaces Generating/Ready/Failed/Error.
Lifecycle and database re-seed attach in later issues.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from kubernetes.client import ApiException
from pydantic import BaseModel, field_validator

from app.core.auth import ROLE_OPERATOR, ROLE_VIEWER, require_roles
from app.core.config import settings
from app.core.constants import (
    APP_KUBERNETES_IO_NAME,
    DEFAULT_IN_CLUSTER_PORT,
    KAGENTI_SIMULATED_LABEL,
    TOOL_SERVICE_SUFFIX,
)
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.services.simulation_harness_client import (
    HarnessNotFound,
    HarnessUnreachable,
    get_simulation,
    post_simulation,
    reset_simulation,
)
from app.services.simulation_manifests import (
    MAX_SIMULATION_NAME_LEN,
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

# Outstanding generation-trigger tasks, tracked so lifespan shutdown can cancel
# them (mirrors main.py's reconciliation_task handling). Fire-and-forget per tool.
_generation_tasks: set = set()


# Full-string DNS-1123 label matcher, kept local so the sanitizing guard below
# lives in the same frame as the URL sink. CodeQL recognizes an re.fullmatch
# guard as an SSRF barrier only when it directly gates the tainted value at the
# point of interpolation; the cross-frame boolean helpers in simulation_manifests
# validate identically but are not seen through by the taint tracker.
_DNS1123_LABEL_RE = re.compile(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?")


def _harness_base_url(name: str, namespace: str, port: int) -> str:
    """In-cluster URL of a simulated tool's harness Service ({name}-mcp).

    Both identifiers are re-validated as DNS-1123 labels here so no untrusted
    value can ever be interpolated into the request URL. This is the single
    chokepoint that closes SSRF via the status endpoint's path parameters
    (CWE-918); the create path's names are already valid, so this never rejects
    a legitimate request.
    """
    if not (_DNS1123_LABEL_RE.fullmatch(name) and len(name) <= MAX_SIMULATION_NAME_LEN):
        raise ValueError("name must be a DNS-1123 label")
    if not _DNS1123_LABEL_RE.fullmatch(namespace):
        raise ValueError("namespace must be a DNS-1123 label")
    return f"http://{name}{TOOL_SERVICE_SUFFIX}.{namespace}.svc.cluster.local:{port}"


async def _run_generation_trigger(namespace: str, name: str, spec: dict, port: int) -> None:
    """Wait for the harness pod to accept connections, then POST the spec once.

    The harness generates in the background after a 202; this task's only job is
    to deliver the spec, retrying while the pod is still starting (connection
    failures) or briefly warming up (5xx). A 202/409 is terminal success; any
    other 4xx is a terminal rejection. Bounded by ``simulation_generation_timeout``
    so it never loops forever; a give-up is later surfaced by the status
    endpoint's watchdog as Failed/generation_stalled.

    Runs fire-and-forget via ``asyncio.create_task``, so it must never let an
    exception escape (an unretrieved task exception would only surface as log
    noise); any unexpected error is logged and ends the task.
    """
    base_url = _harness_base_url(name, namespace, port)
    deadline = time.monotonic() + settings.simulation_generation_timeout
    interval = settings.simulation_trigger_poll_interval
    try:
        while True:
            try:
                code = await post_simulation(base_url, spec, name)
            except HarnessUnreachable:
                if time.monotonic() >= deadline:
                    logger.warning(
                        "Gave up posting spec to harness for '%s' (unreachable past timeout)",
                        sanitize_log(name),
                    )
                    return
                await asyncio.sleep(interval)
                continue
            if code in (202, 409):
                logger.info(
                    "Generation triggered for simulated tool '%s' (HTTP %d)",
                    sanitize_log(name),
                    code,
                )
                return
            if code >= 500:
                # Transient server error while the harness warms up — retry until
                # the deadline rather than giving up on the first hiccup.
                if time.monotonic() >= deadline:
                    logger.warning(
                        "Gave up posting spec to harness for '%s' (HTTP %d past timeout)",
                        sanitize_log(name),
                        code,
                    )
                    return
                await asyncio.sleep(interval)
                continue
            # Terminal 4xx rejection (e.g. 413 too large, 422 invalid spec).
            logger.warning(
                "Harness rejected spec for simulated tool '%s' (HTTP %d)",
                sanitize_log(name),
                code,
            )
            return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "Unexpected error in generation trigger for simulated tool '%s'",
            sanitize_log(name),
            exc_info=True,
        )


async def cancel_generation_tasks() -> None:
    """Cancel any outstanding generation-trigger tasks (called on shutdown)."""
    for task in list(_generation_tasks):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


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


class SimulationLifecycleResponse(BaseModel):
    """Response after a start/stop action on a simulated tool."""

    success: bool
    name: str
    namespace: str
    status: str
    message: str


class SimulationResetResponse(BaseModel):
    """Response after resetting a simulated tool's session."""

    success: bool
    name: str
    namespace: str
    message: str


class SimulationDeleteResponse(BaseModel):
    """Response after deleting a simulated tool and its backing resources."""

    success: bool
    name: str
    namespace: str
    deletedResources: List[str]
    message: str


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
            # The harness buries the underlying cause (e.g. a timed-out
            # generation stage rewrapped as a generic RuntimeError) in
            # error.details.cause_type. Fold it into the reason so the UI shows
            # *why* it failed instead of just the coarse code.
            cause_type = (err.get("details") or {}).get("cause_type")
            label = f"{code} ({cause_type})" if cause_type else code
            reason = f"{label}: {message}" if message else label
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


def _read_simulated_statefulset(kube: KubernetesService, namespace: str, name: str):
    """Read a simulated tool's StatefulSet, or raise HTTPException.

    404 if the StatefulSet is absent or does not carry kagenti.io/simulated=true
    (these lifecycle endpoints act only on simulated tools). 502 on any other
    read failure.
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
    labels = sts.metadata.labels or {}
    if labels.get(KAGENTI_SIMULATED_LABEL) != "true":
        raise HTTPException(
            status_code=404,
            detail=f"Simulated tool '{name}' not found in namespace '{namespace}'",
        )
    return sts


def _validate_path_params(namespace: str, name: str) -> None:
    """Reject path params that cannot name a real tool (SSRF guard, CWE-918)."""
    try:
        validate_namespace(namespace)
        validate_custom_name(name)
    except ValueError:
        raise HTTPException(status_code=404, detail="Simulated tool not found")


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
    trigger = asyncio.create_task(_run_generation_trigger(request.namespace, name, spec, port))
    _generation_tasks.add(trigger)
    trigger.add_done_callback(_generation_tasks.discard)
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
    # Reject path parameters that cannot name a real tool before they reach any
    # backend call (k8s API or the harness URL) — an invalid identifier is
    # definitionally "not found" and must not be interpolated into a request
    # target (SSRF guard, CWE-918).
    try:
        validate_namespace(namespace)
        validate_custom_name(name)
    except ValueError:
        raise HTTPException(status_code=404, detail="Simulated tool not found")

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

    # Build the harness URL from the StatefulSet's server-returned identity, not
    # the raw path parameters: these come from the k8s API (not a remote-flow
    # source) and name a resource we just confirmed exists (extra SSRF defense).
    base_url = _harness_base_url(sts.metadata.name, sts.metadata.namespace, DEFAULT_IN_CLUSTER_PORT)
    harness = None
    try:
        harness = await get_simulation(base_url)
    except HarnessNotFound:
        # No simulation active yet — routine before the spec is posted.
        harness = None
    except HarnessUnreachable as e:
        # Routine while the harness pod is still starting; maps to Generating.
        logger.debug(
            "Harness not reachable yet for '%s': %s", sanitize_log(name), sanitize_log(str(e))
        )
        harness = None
    except httpx.HTTPError as e:
        # An unexpected harness HTTP failure (e.g. 5xx) — degrade to pod state
        # rather than 500, but surface it: this is not the routine not-started case.
        logger.warning("Harness read error for '%s': %s", sanitize_log(name), sanitize_log(str(e)))
        harness = None

    pod = kube.get_workload_pod_status(namespace, f"{APP_KUBERNETES_IO_NAME}={name}")
    return map_generation_status(
        harness=harness,
        pod_waiting_reason=pod["waiting_reason"],
        pod_waiting_message=pod["waiting_message"],
        elapsed_seconds=elapsed,
        timeout_seconds=settings.simulation_generation_timeout,
    )


def _scale_simulated_tool(
    kube: KubernetesService, namespace: str, name: str, replicas: int, status_label: str
) -> SimulationLifecycleResponse:
    _validate_path_params(namespace, name)
    _read_simulated_statefulset(kube, namespace, name)
    try:
        kube.patch_statefulset(namespace, name, {"spec": {"replicas": replicas}})
    except ApiException as e:
        logger.error(
            "Failed to scale simulated tool '%s' to %d: %s",
            sanitize_log(name),
            replicas,
            sanitize_log(str(e)),
        )
        raise HTTPException(status_code=502, detail="Failed to scale simulated-tool workload")
    return SimulationLifecycleResponse(
        success=True,
        name=name,
        namespace=namespace,
        status=status_label,
        message=f"Simulated tool '{name}' {status_label.lower()}.",
    )


@router.post(
    "/tools/{namespace}/{name}/stop",
    response_model=SimulationLifecycleResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def stop_simulated_tool(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SimulationLifecycleResponse:
    """Scale a simulated tool's StatefulSet to 0 (bundle retained on the PVC)."""
    return _scale_simulated_tool(kube, namespace, name, replicas=0, status_label="Stopped")


@router.post(
    "/tools/{namespace}/{name}/start",
    response_model=SimulationLifecycleResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def start_simulated_tool(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SimulationLifecycleResponse:
    """Scale a simulated tool's StatefulSet back to 1 (harness autostarts from bundle)."""
    return _scale_simulated_tool(kube, namespace, name, replicas=1, status_label="Starting")


@router.post(
    "/tools/{namespace}/{name}/reset",
    response_model=SimulationResetResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def reset_simulated_tool(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SimulationResetResponse:
    """Reset a simulated tool's session (fresh session, same bundle; no teardown)."""
    _validate_path_params(namespace, name)
    sts = _read_simulated_statefulset(kube, namespace, name)
    base_url = _harness_base_url(sts.metadata.name, sts.metadata.namespace, DEFAULT_IN_CLUSTER_PORT)
    try:
        code = await reset_simulation(base_url)
    except HarnessUnreachable as e:
        logger.warning(
            "Harness unreachable resetting '%s': %s", sanitize_log(name), sanitize_log(str(e))
        )
        raise HTTPException(
            status_code=502, detail="Simulated tool is not reachable (it may be stopped)"
        )
    if code == 200:
        return SimulationResetResponse(
            success=True,
            name=name,
            namespace=namespace,
            message=f"Simulated tool '{name}' session reset.",
        )
    if code in (404, 503):
        raise HTTPException(
            status_code=409,
            detail="Simulated tool has no active, ready simulation to reset",
        )
    logger.warning("Unexpected harness reset status %d for '%s'", code, sanitize_log(name))
    raise HTTPException(status_code=502, detail="Failed to reset simulated-tool session")


@router.delete(
    "/tools/{namespace}/{name}",
    response_model=SimulationDeleteResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def delete_simulated_tool(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SimulationDeleteResponse:
    """Delete a simulated tool: StatefulSet + Service + PVC(s), no leaked resources."""
    _validate_path_params(namespace, name)
    _read_simulated_statefulset(kube, namespace, name)

    # Enumerate the tool's PVCs before deleting the StatefulSet (its
    # volumeClaimTemplates are needed to find them). Fail cleanly if we cannot
    # enumerate, rather than deleting the workload and leaking the volume.
    try:
        pvc_names = kube.list_statefulset_pvcs(namespace, name)
    except ApiException as e:
        logger.error(
            "Failed to list PVCs for simulated tool '%s' in '%s': %s",
            sanitize_log(name),
            sanitize_log(namespace),
            sanitize_log(str(e)),
        )
        raise HTTPException(status_code=502, detail="Failed to enumerate simulated-tool volumes")
    deleted: List[str] = []

    def _try(delete_call, resource_label: str) -> None:
        try:
            delete_call()
            deleted.append(resource_label)
        except ApiException as e:
            if e.status != 404:
                logger.warning(
                    "Failed to delete %s for '%s': %s",
                    resource_label,
                    sanitize_log(name),
                    sanitize_log(str(e)),
                )

    _try(lambda: kube.delete_statefulset(namespace, name), f"StatefulSet/{name}")
    service_name = f"{name}{TOOL_SERVICE_SUFFIX}"
    _try(lambda: kube.delete_service(namespace, service_name), f"Service/{service_name}")
    for pvc in pvc_names:
        _try(
            lambda pvc=pvc: kube.delete_persistent_volume_claim(namespace, pvc),
            f"PersistentVolumeClaim/{pvc}",
        )

    logger.info(
        "Deleted simulated tool '%s' in '%s' (%d resources)",
        sanitize_log(name),
        sanitize_log(namespace),
        len(deleted),
    )
    return SimulationDeleteResponse(
        success=True,
        name=name,
        namespace=namespace,
        deletedResources=deleted,
        message=f"Simulated tool '{name}' deleted.",
    )
