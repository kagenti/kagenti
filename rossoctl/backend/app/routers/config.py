# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Configuration API endpoints.
"""

import logging
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from kubernetes.client import ApiException
from pydantic import BaseModel, Field

from app.core.auth import require_roles, ROLE_VIEWER
from app.core.config import settings
from app.core.constants import (
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
    SHIPWRIGHT_CLUSTER_BUILD_STRATEGIES_PLURAL,
)
from app.models.responses import DashboardConfigResponse
from app.services.kubernetes import KubernetesService, get_kubernetes_service

logger = logging.getLogger(__name__)


class FeatureFlagsResponse(BaseModel):
    """Response model for feature flag status."""

    builds: bool = Field(description="Shipwright build-from-source capability available")
    sandbox: bool = Field(description="Interactive sandbox session UI (Legion)")
    integrations: bool = Field(description="Third-party integration endpoints")
    triggers: bool = Field(description="Event-driven trigger system")
    agentSandbox: bool = Field(description="agent-sandbox (k8s-sigs) as a workload type")
    skills: bool = Field(description="Skill management system (CRUD + catalog UI)")
    externalSkills: bool = Field(description="External skill registry references")
    authbridgeAPI: bool = Field(description="AuthBridge statistics (API and UI)")
    admin: bool = Field(description="Platform Status card and /platform-status endpoint")
    agentImportDefaults: bool = Field(
        description="Auto-inject MCP_URL and LLM env vars on agent import"
    )
    traceAnalysis: bool = Field(description="Trace-analysis Observability card")
    simulatedTools: bool = Field(description="Simulated MCP tools generated from an OpenAPI spec")


class ComponentStatus(BaseModel):
    """Health of a single platform component (Istio, Keycloak, SPIRE, etc.)."""

    name: str
    status: Literal[
        "Ready",  # API group or service exists and is reachable
        "Degraded",  # Workload exists but not fully ready (e.g. ready < desired for deployments/statefulsets, or a non-404 API error)
        "Missing",  # API group or service not found in the cluster
        "Unknown",  # Probe could not determine status (e.g. timeout, RBAC)
    ]


class RegistryBuildInfo(BaseModel):
    """Container registry endpoint and Shipwright ClusterBuildStrategy availability."""

    clusterBuildStrategyPresent: bool
    clusterBuildStrategies: List[str]
    registryEndpoint: str


class PlatformStatusResponse(BaseModel):
    """Aggregated platform status returned by GET /config/platform-status."""

    components: List[ComponentStatus]
    registry: RegistryBuildInfo


router = APIRouter(prefix="/config", tags=["config"])


@router.get(
    "/features",
    response_model=FeatureFlagsResponse,
)
async def get_feature_flags(
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> FeatureFlagsResponse:
    """Return enabled feature flags for UI gating (public, no auth required)."""
    return FeatureFlagsResponse(
        builds=kube.api_group_exists("shipwright.io"),
        sandbox=settings.rossoctl_feature_flag_sandbox,
        integrations=settings.rossoctl_feature_flag_integrations,
        triggers=settings.rossoctl_feature_flag_triggers,
        agentSandbox=settings.rossoctl_feature_flag_agent_sandbox,
        skills=settings.rossoctl_feature_flag_skills,
        externalSkills=settings.rossoctl_feature_flag_external_skills,
        authbridgeAPI=settings.rossoctl_feature_flag_authbridge_api,
        admin=settings.rossoctl_feature_flag_admin,
        agentImportDefaults=settings.rossoctl_feature_flag_agent_import_defaults,
        traceAnalysis=settings.rossoctl_feature_flag_trace_analysis,
        simulatedTools=settings.rossoctl_feature_flag_simulated_tools,
    )


@router.get(
    "/dashboards",
    response_model=DashboardConfigResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_dashboard_config() -> DashboardConfigResponse:
    """
    Get dashboard URLs for observability tools.

    Returns URLs for Phoenix (traces), Kiali (network), MCP Inspector/Proxy,
    and Keycloak console. URLs are read from environment variables that are
    populated from the rossoctl-ui-config ConfigMap.
    """
    domain = settings.domain_name

    return DashboardConfigResponse(
        traces=settings.traces_dashboard_url,
        network=settings.network_dashboard_url or f"http://kiali.{domain}:8080",
        mlflow=settings.mlflow_dashboard_url,
        traceAnalysis=settings.trace_analysis_dashboard_url or None,
        mcpInspector=settings.mcp_inspector_url or None,
        mcpProxy=settings.mcp_proxy_full_address or None,
        keycloakConsole=(
            settings.keycloak_console_url
            or f"{settings.effective_keycloak_url}/admin/{settings.effective_keycloak_realm}/console/"
        ),
        domainName=domain,
    )


def _check_api_group(kube: KubernetesService, group: str) -> str:
    """Return 'Ready' if the API group exists, 'Missing' otherwise."""
    try:
        return "Ready" if kube.api_group_exists(group) else "Missing"
    except Exception:
        logger.debug("Failed to check API group %s", group, exc_info=True)
        return "Missing"


def _check_service(kube: KubernetesService, namespace: str, name: str) -> str:
    """Return 'Ready' if the service exists, 'Missing' otherwise."""
    try:
        kube.core_api.read_namespaced_service(name=name, namespace=namespace)
        return "Ready"
    except ApiException as e:
        if e.status == 404:
            return "Missing"
        logger.debug("Error checking service %s/%s: %s", namespace, name, e)
        return "Degraded"
    except Exception:
        logger.debug("Failed to check service %s/%s", namespace, name, exc_info=True)
        return "Missing"


def _check_deployment_ready(kube: KubernetesService, namespace: str, name: str) -> str:
    """Return Ready/Degraded/Missing based on a Deployment's ready replica count."""
    try:
        dep = kube.apps_api.read_namespaced_deployment(name=name, namespace=namespace)
        desired = dep.spec.replicas or 1
        ready = (dep.status and dep.status.ready_replicas) or 0
        if ready >= desired:
            return "Ready"
        return "Degraded"
    except ApiException as e:
        if e.status == 404:
            return "Missing"
        logger.debug("Error checking deployment %s/%s: %s", namespace, name, e)
        return "Degraded"
    except Exception:
        logger.debug("Failed to check deployment %s/%s", namespace, name, exc_info=True)
        return "Missing"


def _check_statefulset_ready(kube: KubernetesService, namespace: str, name: str) -> str:
    """Return Ready/Degraded/Missing based on a StatefulSet's ready replica count."""
    try:
        sts = kube.apps_api.read_namespaced_stateful_set(name=name, namespace=namespace)
        desired = sts.spec.replicas or 1
        ready = (sts.status and sts.status.ready_replicas) or 0
        if ready >= desired:
            return "Ready"
        return "Degraded"
    except ApiException as e:
        if e.status == 404:
            return "Missing"
        logger.debug("Error checking statefulset %s/%s: %s", namespace, name, e)
        return "Degraded"
    except Exception:
        logger.debug("Failed to check statefulset %s/%s", namespace, name, exc_info=True)
        return "Missing"


@router.get(
    "/platform-status",
    response_model=PlatformStatusResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_platform_status(
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> PlatformStatusResponse:
    """Return health status of platform components, build strategies, and registry info."""
    if not settings.rossoctl_feature_flag_admin:
        raise HTTPException(status_code=404, detail="Admin feature disabled")

    components = [
        ComponentStatus(
            name="Istio", status=_check_deployment_ready(kube, "istio-system", "istiod")
        ),
        ComponentStatus(
            name="Keycloak", status=_check_statefulset_ready(kube, "keycloak", "keycloak")
        ),
        # SPIRE uses spire-system on Kind but zero-trust-workload-identity-manager on
        # OpenShift, so we check the API group instead of a specific workload.
        ComponentStatus(name="SPIRE", status=_check_api_group(kube, "spire.spiffe.io")),
        # Shipwright uses different namespaces on Kind (shipwright-build) vs OpenShift
        # (openshift-builds), so we check the API group instead of a specific service.
        ComponentStatus(name="Shipwright", status=_check_api_group(kube, "shipwright.io")),
        ComponentStatus(name="Phoenix", status=_check_service(kube, "rossoctl-system", "phoenix")),
        ComponentStatus(
            name="MLflow", status=_check_deployment_ready(kube, "rossoctl-system", "mlflow")
        ),
    ]

    strategy_names: List[str] = []
    try:
        response = kube.list_cluster_custom_resources(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            plural=SHIPWRIGHT_CLUSTER_BUILD_STRATEGIES_PLURAL,
            log_api_error=False,
        )
        strategy_names = [
            item.get("metadata", {}).get("name", "")
            for item in response.get("items", [])
            if item.get("metadata", {}).get("name")
        ]
    except Exception:
        logger.debug("Failed to list ClusterBuildStrategies", exc_info=True)

    registry = RegistryBuildInfo(
        clusterBuildStrategyPresent=len(strategy_names) > 0,
        clusterBuildStrategies=strategy_names,
        registryEndpoint=settings.default_registry_url,
    )

    return PlatformStatusResponse(components=components, registry=registry)


class MCPGatewayStatusResponse(BaseModel):
    """Status of the MCP Gateway component."""

    status: Literal["Ready", "Degraded", "Missing"]


@router.get(
    "/mcp-gateway-status",
    response_model=MCPGatewayStatusResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_mcp_gateway_status(
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> MCPGatewayStatusResponse:
    """Return the health status of the MCP Gateway deployment."""
    # TODO: parameterize namespace/deployment if install location ever varies
    status = _check_deployment_ready(kube, "gateway-system", "mcp-gateway-istio")
    return MCPGatewayStatusResponse(status=status)
