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
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from kubernetes.client import ApiException
from pydantic import BaseModel, field_validator

from app.core.auth import ROLE_OPERATOR, require_roles
from app.core.config import settings
from app.core.constants import DEFAULT_IN_CLUSTER_PORT
from app.services.kubernetes import KubernetesService, get_kubernetes_service
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
