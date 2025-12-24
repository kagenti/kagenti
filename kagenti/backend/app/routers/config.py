# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Configuration API endpoints.
"""

from fastapi import APIRouter

from app.core.config import settings
from app.models.responses import DashboardConfigResponse

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/dashboards", response_model=DashboardConfigResponse)
async def get_dashboard_config() -> DashboardConfigResponse:
    """
    Get dashboard URLs for observability tools.

    Returns URLs for Phoenix (traces), Kiali (network), and MCP Inspector.
    """
    domain = settings.domain_name

    return DashboardConfigResponse(
        traces=settings.traces_dashboard_url or f"http://phoenix.{domain}:8080",
        network=settings.network_dashboard_url or f"http://kiali.{domain}:8080",
        mcpInspector=settings.mcp_inspector_url or f"http://mcp-inspector.{domain}:8080",
    )
