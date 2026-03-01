# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Integration API endpoints.

Manages Integration custom resources that connect repositories
to agents via webhooks, cron schedules, and alert triggers.
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.auth import ROLE_OPERATOR, ROLE_VIEWER, require_roles
from app.services.kubernetes import KubernetesService, get_kubernetes_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])

# CRD constants
CRD_GROUP = "kagenti.io"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "integrations"


# Request/Response models
class IntegrationAgentRef(BaseModel):
    """Reference to an agent associated with an integration."""

    name: str
    namespace: str


class IntegrationWebhook(BaseModel):
    """Webhook trigger configuration for an integration."""

    name: str
    events: list[str]
    filters: Optional[dict] = None


class IntegrationSchedule(BaseModel):
    """Cron schedule trigger configuration for an integration."""

    name: str
    cron: str
    skill: str
    agent: str
    enabled: bool = True


class IntegrationAlert(BaseModel):
    """Alert trigger configuration for an integration."""

    name: str
    source: str  # prometheus | pagerduty
    matchLabels: dict[str, str]  # noqa: N815
    agent: str


class RepositorySpec(BaseModel):
    """Repository connection specification."""

    url: str
    provider: str = "github"
    branch: str = "main"
    credentialsSecret: Optional[str] = None  # noqa: N815


class CreateIntegrationRequest(BaseModel):
    """Request body for creating an Integration resource."""

    name: str
    namespace: str
    repository: RepositorySpec
    agents: list[IntegrationAgentRef]
    webhooks: list[IntegrationWebhook] = []
    schedules: list[IntegrationSchedule] = []
    alerts: list[IntegrationAlert] = []


class IntegrationSummary(BaseModel):
    """Summary representation of an Integration resource."""

    name: str
    namespace: str
    repository: dict
    agents: list[dict]
    webhooks: list[dict]
    schedules: list[dict]
    alerts: list[dict]
    status: str
    webhookUrl: Optional[str] = None  # noqa: N815
    lastWebhookEvent: Optional[str] = None  # noqa: N815
    lastScheduleRun: Optional[str] = None  # noqa: N815
    createdAt: Optional[str] = None  # noqa: N815


class IntegrationListResponse(BaseModel):
    """Response containing a list of Integration summaries."""

    items: list[IntegrationSummary]


def _crd_to_summary(obj: dict) -> IntegrationSummary:
    """Convert a K8s Integration CRD object to an IntegrationSummary."""
    metadata = obj.get("metadata", {})
    spec = obj.get("spec", {})
    obj_status = obj.get("status", {})

    # Determine status from conditions
    conditions = obj_status.get("conditions", [])
    integration_status = "Pending"
    for cond in conditions:
        if cond.get("type") == "Connected" and cond.get("status") == "True":
            integration_status = "Connected"
            break
        if cond.get("type") == "Error":
            integration_status = "Error"
            break

    return IntegrationSummary(
        name=metadata.get("name", ""),
        namespace=metadata.get("namespace", ""),
        repository=spec.get("repository", {}),
        agents=list(spec.get("agents", [])),
        webhooks=spec.get("webhooks", []),
        schedules=spec.get("schedules", []),
        alerts=spec.get("alerts", []),
        status=integration_status,
        webhookUrl=obj_status.get("webhookUrl"),
        lastWebhookEvent=obj_status.get("lastWebhookEvent"),
        lastScheduleRun=obj_status.get("lastScheduleRun"),
        createdAt=metadata.get("creationTimestamp"),
    )


@router.get(
    "",
    response_model=IntegrationListResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_integrations(
    namespace: str = Query(..., description="Namespace to list integrations from"),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> IntegrationListResponse:
    """List Integration resources in a namespace."""
    try:
        result = kube.custom_api.list_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=CRD_PLURAL,
        )
        items = [_crd_to_summary(obj) for obj in result.get("items", [])]
        return IntegrationListResponse(items=items)
    except Exception as e:
        logger.error(f"Failed to list integrations in {namespace}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list integrations: {e!s}",
        )


@router.get(
    "/{namespace}/{name}",
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_integration(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Get a specific Integration resource."""
    try:
        obj = kube.custom_api.get_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=CRD_PLURAL,
            name=name,
        )
        summary = _crd_to_summary(obj)
        # Add conditions for detail view
        obj_status = obj.get("status", {})
        return {
            **summary.model_dump(),
            "conditions": obj_status.get("conditions", []),
        }
    except Exception as e:
        if "NotFound" in str(e) or "404" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Integration {namespace}/{name} not found",
            )
        logger.error(f"Failed to get integration {namespace}/{name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get integration: {e!s}",
        )


@router.post(
    "",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def create_integration(
    request: CreateIntegrationRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Create a new Integration resource."""
    body = {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "Integration",
        "metadata": {
            "name": request.name,
            "namespace": request.namespace,
            "labels": {
                "kagenti.io/provider": request.repository.provider,
            },
        },
        "spec": {
            "repository": request.repository.model_dump(exclude_none=True),
            "agents": [a.model_dump() for a in request.agents],
            "webhooks": [w.model_dump(exclude_none=True) for w in request.webhooks],
            "schedules": [s.model_dump() for s in request.schedules],
            "alerts": [a.model_dump() for a in request.alerts],
        },
    }

    try:
        kube.custom_api.create_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=request.namespace,
            plural=CRD_PLURAL,
            body=body,
        )
        return {
            "success": True,
            "name": request.name,
            "namespace": request.namespace,
            "message": f"Integration {request.name} created",
        }
    except Exception as e:
        if "AlreadyExists" in str(e) or "409" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Integration {request.name} already exists in {request.namespace}",
            )
        logger.error(f"Failed to create integration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create integration: {e!s}",
        )


@router.put(
    "/{namespace}/{name}",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def update_integration(
    namespace: str,
    name: str,
    request: dict,
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Update an existing Integration resource (partial spec update)."""
    try:
        obj = kube.custom_api.get_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=CRD_PLURAL,
            name=name,
        )

        spec = obj.get("spec", {})
        for key in ["agents", "webhooks", "schedules", "alerts"]:
            if key in request:
                spec[key] = request[key]
        obj["spec"] = spec

        kube.custom_api.replace_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=CRD_PLURAL,
            name=name,
            body=obj,
        )
        return {"success": True, "message": f"Integration {name} updated"}
    except Exception as e:
        if "NotFound" in str(e) or "404" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Integration {namespace}/{name} not found",
            )
        logger.error(f"Failed to update integration {namespace}/{name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update integration: {e!s}",
        )


@router.delete(
    "/{namespace}/{name}",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def delete_integration(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Delete an Integration resource."""
    try:
        kube.custom_api.delete_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=CRD_PLURAL,
            name=name,
        )
        return {"success": True, "message": f"Integration {name} deleted"}
    except Exception as e:
        if "NotFound" in str(e) or "404" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Integration {namespace}/{name} not found",
            )
        logger.error(f"Failed to delete integration {namespace}/{name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete integration: {e!s}",
        )


@router.post(
    "/{namespace}/{name}/test",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def test_integration_connection(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """Test connectivity to the integration's repository."""
    try:
        obj = kube.custom_api.get_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=CRD_PLURAL,
            name=name,
        )
        repo_url = obj.get("spec", {}).get("repository", {}).get("url", "")
        async with httpx.AsyncClient() as client:
            response = await client.head(repo_url, timeout=10.0, follow_redirects=True)
            if response.status_code < 400:
                return {"success": True, "message": f"Repository {repo_url} is reachable"}
            return {
                "success": False,
                "message": f"Repository returned status {response.status_code}",
            }
    except httpx.HTTPError as e:
        return {"success": False, "message": f"Connection failed: {e!s}"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Test failed: {e!s}",
        )
