# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Namespace API endpoints.
"""

from fastapi import APIRouter, Depends, Query

from app.models.responses import NamespaceListResponse
from app.services.kubernetes import KubernetesService, get_kubernetes_service

router = APIRouter(prefix="/namespaces", tags=["namespaces"])


@router.get("", response_model=NamespaceListResponse)
async def list_namespaces(
    enabled_only: bool = Query(default=True, description="Only return enabled namespaces"),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> NamespaceListResponse:
    """
    List available Kubernetes namespaces.

    If enabled_only is True, returns only namespaces with the kagenti-enabled=true label.
    """
    if enabled_only:
        namespaces = kube.list_enabled_namespaces()
    else:
        namespaces = kube.list_namespaces()

    return NamespaceListResponse(namespaces=namespaces)
