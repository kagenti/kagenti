# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Shipwright API endpoints (cluster-wide listing for CLI and tooling).
"""

import logging
from typing import Literal, List

from fastapi import APIRouter, Depends, HTTPException, Query
from kubernetes.client import ApiException

from app.core.auth import ROLE_VIEWER, require_roles
from app.core.constants import (
    RESOURCE_TYPE_AGENT,
    RESOURCE_TYPE_TOOL,
    SHIPWRIGHT_BUILDS_LIST_SCOPE_ALL,
)
from app.models.shipwright import ShipwrightBuildListResponse
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.services.shipwright_builds import collect_kagenti_shipwright_builds

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shipwright", tags=["shipwright"])

# Query param ``for=agents|tools|all`` → values expected by collect_kagenti_shipwright_builds
_SHIPWRIGHT_BUILDS_FOR_QUERY = {
    "agents": RESOURCE_TYPE_AGENT,
    "tools": RESOURCE_TYPE_TOOL,
    "all": SHIPWRIGHT_BUILDS_LIST_SCOPE_ALL,
}


@router.get(
    "/builds",
    response_model=ShipwrightBuildListResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_shipwright_builds(
    namespace: str = Query(
        default="",
        description="Kubernetes namespace (required unless allNamespaces=true)",
    ),
    all_namespaces: bool = Query(
        default=False,
        alias="allNamespaces",
        description="If true, list builds in all kagenti-enabled namespaces",
    ),
    builds_for: Literal["agents", "tools", "all"] = Query(
        default="all",
        alias="for",
        description="List builds for agents only, tools only, or both (agents | tools | all)",
    ),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ShipwrightBuildListResponse:
    """
    List Shipwright Build CRs created for Kagenti agents and/or tools.

    Uses the `kagenti.io/type` label (agent | tool). Intended for CLI and automation.
    """
    namespaces_to_scan: List[str] = []
    if all_namespaces:
        namespaces_to_scan = kube.list_enabled_namespaces()
    else:
        if not namespace or not namespace.strip():
            raise HTTPException(
                status_code=400,
                detail="namespace query parameter is required (or use allNamespaces=true)",
            )
        namespaces_to_scan = [namespace.strip()]

    try:
        items = collect_kagenti_shipwright_builds(
            kube, namespaces_to_scan, _SHIPWRIGHT_BUILDS_FOR_QUERY[builds_for], logger
        )
    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=str(e.reason))

    return ShipwrightBuildListResponse(items=items)
