# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Configuration API endpoints.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import require_roles, ROLE_VIEWER
from app.core.config import settings
from app.models.responses import DashboardConfigResponse


class FeatureFlagsResponse(BaseModel):
    sandbox: bool
    integrations: bool
    triggers: bool


router = APIRouter(prefix="/config", tags=["config"])


@router.get("/features", response_model=FeatureFlagsResponse)
async def get_feature_flags() -> FeatureFlagsResponse:
    """Return enabled feature flags for UI gating. Public endpoint — flags are not sensitive."""
    return FeatureFlagsResponse(
        sandbox=settings.kagenti_feature_flag_sandbox,
        integrations=settings.kagenti_feature_flag_integrations,
        triggers=settings.kagenti_feature_flag_triggers,
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
    populated from the kagenti-ui-config ConfigMap.
    """
    domain = settings.domain_name

    return DashboardConfigResponse(
        traces=settings.traces_dashboard_url,
        network=settings.network_dashboard_url or f"http://kiali.{domain}:8080",
        mcpInspector=settings.mcp_inspector_url or f"http://mcp-inspector.{domain}:8080",
        mcpProxy=settings.mcp_proxy_full_address or f"http://mcp-proxy.{domain}:8080",
        keycloakConsole=(
            settings.keycloak_console_url
            or f"{settings.effective_keycloak_url}/admin/{settings.effective_keycloak_realm}/console/"
        ),
        domainName=domain,
    )
