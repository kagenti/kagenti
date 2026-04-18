# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Pydantic models for API responses.
"""

from typing import List, Optional
from pydantic import BaseModel


class ResourceLabels(BaseModel):
    """Labels for agent/tool resources."""

    protocol: Optional[List[str]] = None
    framework: Optional[str] = None
    type: Optional[str] = None


class AgentSummary(BaseModel):
    """Summary information for an agent."""

    name: str
    namespace: str
    description: str
    status: str
    labels: ResourceLabels
    workloadType: Optional[str] = None
    createdAt: Optional[str] = None


class AgentListResponse(BaseModel):
    """Response for listing agents."""

    items: List[AgentSummary]


class ToolSummary(BaseModel):
    """Summary information for a tool."""

    name: str
    namespace: str
    description: str
    status: str
    labels: ResourceLabels
    createdAt: Optional[str] = None
    workloadType: Optional[str] = None  # "deployment" or "statefulset"


class ToolListResponse(BaseModel):
    """Response for listing tools."""

    items: List[ToolSummary]


class NamespaceListResponse(BaseModel):
    """Response for listing namespaces."""

    namespaces: List[str]


class DeleteResponse(BaseModel):
    """Response for delete operations."""

    success: bool
    message: str


class DashboardConfigResponse(BaseModel):
    """Response for dashboard configuration."""

    traces: str
    network: str
    mcpInspector: str
    mcpProxy: str
    keycloakConsole: str
    domainName: str


class MCPToolInfo(BaseModel):
    """Information about an MCP tool."""

    name: str
    description: Optional[str] = None
    input_schema: Optional[dict] = None


class MCPToolsResponse(BaseModel):
    """Response for MCP tools listing."""

    tools: List[MCPToolInfo]


class MCPInvokeResponse(BaseModel):
    """Response for MCP tool invocation."""

    result: dict
