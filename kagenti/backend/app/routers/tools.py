# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tool API endpoints.
"""

import logging
from typing import Any, List, Optional
from contextlib import AsyncExitStack

from fastapi import APIRouter, Depends, HTTPException, Query
from kubernetes.client import ApiException
from pydantic import BaseModel
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.core.config import settings
from app.core.constants import (
    TOOLHIVE_CRD_GROUP,
    TOOLHIVE_CRD_VERSION,
    TOOLHIVE_MCP_PLURAL,
    KAGENTI_TYPE_LABEL,
    KAGENTI_PROTOCOL_LABEL,
    KAGENTI_FRAMEWORK_LABEL,
    APP_KUBERNETES_IO_CREATED_BY,
    KAGENTI_UI_CREATOR_LABEL,
    RESOURCE_TYPE_TOOL,
    DEFAULT_IN_CLUSTER_PORT,
    DEFAULT_RESOURCE_LIMITS,
    DEFAULT_RESOURCE_REQUESTS,
    DEFAULT_ENV_VARS,
)
from app.models.responses import (
    ToolSummary,
    ToolListResponse,
    ResourceLabels,
    DeleteResponse,
)
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.utils.routes import create_route_for_agent_or_tool, route_exists


class EnvVar(BaseModel):
    """Environment variable."""

    name: str
    value: str


class ServicePort(BaseModel):
    """Service port configuration."""

    name: str = "http"
    port: int = 8000
    targetPort: int = 8000
    protocol: str = "TCP"


class CreateToolRequest(BaseModel):
    """Request to create a new MCP tool.

    Tools are deployed from existing container images using the MCPServer CRD.
    Unlike agents, tools do not support building from source.
    """

    name: str
    namespace: str
    containerImage: str  # Required: full image URL with tag
    protocol: str = "streamable_http"
    framework: str = "Python"
    envVars: Optional[List[EnvVar]] = None
    imagePullSecret: Optional[str] = None
    servicePorts: Optional[List[ServicePort]] = None
    # HTTPRoute/Route creation
    createHttpRoute: bool = False


class CreateToolResponse(BaseModel):
    """Response after creating a tool."""

    success: bool
    name: str
    namespace: str
    message: str


class MCPToolSchema(BaseModel):
    """Schema for an MCP tool."""

    name: str
    description: Optional[str] = None
    input_schema: Optional[dict] = None


class MCPToolsResponse(BaseModel):
    """Response containing available MCP tools."""

    tools: List[MCPToolSchema]


class MCPInvokeRequest(BaseModel):
    """Request to invoke an MCP tool."""

    tool_name: str
    arguments: dict = {}


class MCPInvokeResponse(BaseModel):
    """Response from MCP tool invocation."""

    result: Any


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tools", tags=["tools"])


def _is_deployment_ready(resource_data: dict) -> str:
    """Check if a tool deployment is ready based on status phase.

    For MCPServer CRD, the authoritative ready state is .status.phase == "Running".
    Conditions can be used for intermediate states but phase is the final indicator.
    """
    status = resource_data.get("status", {})

    # Primary check: status.phase for MCPServer CRD
    # "Running" indicates the tool is fully ready
    phase = status.get("phase", "")
    if phase == "Running":
        return "Ready"

    return "Not Ready"


def _extract_labels(labels: dict) -> ResourceLabels:
    """Extract kagenti labels from Kubernetes labels."""
    return ResourceLabels(
        protocol=labels.get("kagenti.io/protocol"),
        framework=labels.get("kagenti.io/framework"),
        type=labels.get("kagenti.io/type"),
    )


@router.get("", response_model=ToolListResponse)
async def list_tools(
    namespace: str = Query(default="default", description="Kubernetes namespace"),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ToolListResponse:
    """
    List all MCP tools in the specified namespace.

    Returns tools that have the kagenti.io/type=tool label.
    """
    try:
        label_selector = f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_TOOL}"

        items = kube.list_custom_resources(
            group=TOOLHIVE_CRD_GROUP,
            version=TOOLHIVE_CRD_VERSION,
            namespace=namespace,
            plural=TOOLHIVE_MCP_PLURAL,
            label_selector=label_selector,
        )

        tools = []
        for item in items:
            metadata = item.get("metadata", {})
            spec = item.get("spec", {})

            tools.append(
                ToolSummary(
                    name=metadata.get("name", ""),
                    namespace=metadata.get("namespace", namespace),
                    description=spec.get("description", "No description"),
                    status=_is_deployment_ready(item),
                    labels=_extract_labels(metadata.get("labels", {})),
                    createdAt=metadata.get("creationTimestamp"),
                )
            )

        return ToolListResponse(items=tools)

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail="MCPServer CRD not found. Is ToolHive installed?",
            )
        if e.status == 403:
            raise HTTPException(
                status_code=403,
                detail="Permission denied. Check RBAC configuration.",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@router.get("/{namespace}/{name}")
async def get_tool(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> Any:
    """Get detailed information about a specific tool."""
    try:
        tool = kube.get_custom_resource(
            group=TOOLHIVE_CRD_GROUP,
            version=TOOLHIVE_CRD_VERSION,
            namespace=namespace,
            plural=TOOLHIVE_MCP_PLURAL,
            name=name,
        )
        return tool

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Tool '{name}' not found in namespace '{namespace}'",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@router.get("/{namespace}/{name}/route-status")
async def get_tool_route_status(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> dict:
    """Check if an HTTPRoute or Route exists for the tool."""
    exists = route_exists(kube, name, namespace)
    return {"hasRoute": exists}


@router.delete("/{namespace}/{name}", response_model=DeleteResponse)
async def delete_tool(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> DeleteResponse:
    """Delete a tool from the cluster."""
    try:
        kube.delete_custom_resource(
            group=TOOLHIVE_CRD_GROUP,
            version=TOOLHIVE_CRD_VERSION,
            namespace=namespace,
            plural=TOOLHIVE_MCP_PLURAL,
            name=name,
        )
        return DeleteResponse(success=True, message=f"Tool '{name}' deleted")

    except ApiException as e:
        if e.status == 404:
            return DeleteResponse(success=True, message=f"Tool '{name}' already deleted")
        raise HTTPException(status_code=e.status, detail=str(e.reason))


def _build_mcpserver_manifest(request: CreateToolRequest) -> dict:
    """
    Build an MCPServer CRD manifest for deploying an MCP tool.

    Tools are deployed using the ToolHive MCPServer CRD.
    """
    # Build environment variables
    env_vars = list(DEFAULT_ENV_VARS)
    if request.envVars:
        for ev in request.envVars:
            env_vars.append({"name": ev.name, "value": ev.value})

    # Build service ports
    if request.servicePorts:
        port = request.servicePorts[0].port
        target_port = request.servicePorts[0].targetPort
    else:
        port = DEFAULT_IN_CLUSTER_PORT
        target_port = DEFAULT_IN_CLUSTER_PORT

    manifest = {
        "apiVersion": f"{TOOLHIVE_CRD_GROUP}/{TOOLHIVE_CRD_VERSION}",
        "kind": "MCPServer",
        "metadata": {
            "name": request.name,
            "namespace": request.namespace,
            "labels": {
                APP_KUBERNETES_IO_CREATED_BY: KAGENTI_UI_CREATOR_LABEL,
                KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
                KAGENTI_PROTOCOL_LABEL: request.protocol,
                KAGENTI_FRAMEWORK_LABEL: request.framework,
            },
        },
        "spec": {
            "image": request.containerImage,
            "transport": "streamable-http",
            "port": port,
            "targetPort": target_port,
            "proxyPort": DEFAULT_IN_CLUSTER_PORT,
            "podTemplateSpec": {
                "spec": {
                    "serviceAccountName": request.name,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "volumes": [
                        {"name": "cache", "emptyDir": {}},
                        {"name": "tmp-dir", "emptyDir": {}},
                    ],
                    "containers": [
                        {
                            "name": "mcp",
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                                "runAsUser": 1000,
                            },
                            "resources": {
                                "limits": DEFAULT_RESOURCE_LIMITS,
                                "requests": DEFAULT_RESOURCE_REQUESTS,
                            },
                            "env": env_vars,
                            "volumeMounts": [
                                {"name": "cache", "mountPath": "/app/.cache", "readOnly": False},
                                {"name": "tmp-dir", "mountPath": "/tmp", "readOnly": False},
                            ],
                        }
                    ],
                },
            },
        },
    }

    # Add image pull secrets if specified
    if request.imagePullSecret:
        manifest["spec"]["podTemplateSpec"]["spec"]["imagePullSecrets"] = [
            {"name": request.imagePullSecret}
        ]

    return manifest


@router.post("", response_model=CreateToolResponse)
async def create_tool(
    request: CreateToolRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> CreateToolResponse:
    """
    Create a new MCP tool by submitting an MCPServer CRD.

    Tools are deployed from existing container images using the ToolHive
    MCPServer CRD. Unlike agents, tools do not support building from source.
    """
    if not request.containerImage:
        raise HTTPException(
            status_code=400,
            detail="containerImage is required for tool deployment",
        )

    manifest = _build_mcpserver_manifest(request)

    try:
        kube.create_custom_resource(
            group=TOOLHIVE_CRD_GROUP,
            version=TOOLHIVE_CRD_VERSION,
            namespace=request.namespace,
            plural=TOOLHIVE_MCP_PLURAL,
            body=manifest,
        )

        message = f"Tool '{request.name}' deployment started."

        # Create HTTPRoute/Route if requested
        # ToolHive creates a proxy service named mcp-{name}-proxy on port 8000
        if request.createHttpRoute:
            # ToolHive creates the proxy service with this naming pattern
            proxy_service_name = f"mcp-{request.name}-proxy"
            proxy_service_port = 8000

            create_route_for_agent_or_tool(
                kube=kube,
                name=request.name,
                namespace=request.namespace,
                service_name=proxy_service_name,
                service_port=proxy_service_port,
            )
            message += f" HTTPRoute/Route created for external access."

        return CreateToolResponse(
            success=True,
            name=request.name,
            namespace=request.namespace,
            message=message,
        )

    except ApiException as e:
        if e.status == 409:
            raise HTTPException(
                status_code=409,
                detail=f"Tool '{request.name}' already exists in namespace '{request.namespace}'",
            )
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail="MCPServer CRD not found. Is ToolHive installed?",
            )
        logger.error(f"Failed to create tool: {e}")
        raise HTTPException(status_code=e.status, detail=str(e.reason))


def _get_tool_url(name: str, namespace: str) -> str:
    """Get the URL for an MCP tool server.

    ToolHive creates a proxy service with the naming pattern:
    - Service name: mcp-{name}-proxy
    - Port: 8000

    Returns different URL formats based on deployment context:
    - In-cluster: http://mcp-{name}-proxy.{namespace}.svc.cluster.local:8000
    - Off-cluster (local dev): http://{name}.{domain}:8080 (via HTTPRoute)
    """
    if settings.is_running_in_cluster:
        # In-cluster: use ToolHive proxy service DNS
        # ToolHive creates services named mcp-{name}-proxy on port 8000
        return f"http://mcp-{name}-proxy.{namespace}.svc.cluster.local:8000"
    else:
        # Off-cluster: use external domain (e.g., localtest.me) via HTTPRoute
        domain = settings.domain_name
        return f"http://{name}.{domain}:8080"


@router.post("/{namespace}/{name}/connect", response_model=MCPToolsResponse)
async def connect_to_tool(
    namespace: str,
    name: str,
) -> MCPToolsResponse:
    """
    Connect to an MCP server and list available tools.

    This endpoint connects to the MCP server and retrieves the list of
    available tools using the MCP client library.
    """
    tool_url = _get_tool_url(name, namespace)
    mcp_endpoint = f"{tool_url}/mcp"

    logger.info(f"Connecting to MCP server at {mcp_endpoint}")

    exit_stack = AsyncExitStack()
    try:
        async with exit_stack:
            # Connect using MCP streamable-http transport
            streams_context = streamablehttp_client(url=mcp_endpoint, headers={})
            read_stream, write_stream, _ = await streams_context.__aenter__()

            # Create and initialize MCP session
            session_context = ClientSession(read_stream, write_stream)
            session: ClientSession = await session_context.__aenter__()
            await session.initialize()

            logger.info(f"MCP session initialized for tool '{name}'")

            # List available tools
            response = await session.list_tools()
            tools = []
            if response and hasattr(response, "tools"):
                for tool in response.tools:
                    tools.append(
                        MCPToolSchema(
                            name=tool.name,
                            description=tool.description,
                            input_schema=(
                                tool.inputSchema if hasattr(tool, "inputSchema") else None
                            ),
                        )
                    )
                logger.info(f"Listed {len(tools)} tools from MCP server '{name}'")

            return MCPToolsResponse(tools=tools)

    except ConnectionError as e:
        logger.error(f"Connection error to MCP server: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to MCP server at {tool_url}",
        )
    except Exception as e:
        logger.error(f"Unexpected error connecting to MCP server: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error connecting to MCP server: {str(e)}",
        )


@router.post("/{namespace}/{name}/invoke", response_model=MCPInvokeResponse)
async def invoke_tool(
    namespace: str,
    name: str,
    request: MCPInvokeRequest,
) -> MCPInvokeResponse:
    """
    Invoke an MCP tool with the given arguments.

    This endpoint calls a specific tool on the MCP server with
    the provided arguments and returns the result.
    """
    tool_url = _get_tool_url(name, namespace)
    mcp_endpoint = f"{tool_url}/mcp"

    exit_stack = AsyncExitStack()
    try:
        async with exit_stack:
            # Connect using MCP streamable-http transport
            streams_context = streamablehttp_client(url=mcp_endpoint, headers={})
            read_stream, write_stream, _ = await streams_context.__aenter__()

            # Create and initialize MCP session
            session_context = ClientSession(read_stream, write_stream)
            session: ClientSession = await session_context.__aenter__()
            await session.initialize()

            logger.info(f"MCP session initialized for tool invocation on '{name}'")

            # Call the tool using the MCP client library
            result = await session.call_tool(request.tool_name, request.arguments)

            logger.info(f"Tool '{request.tool_name}' invoked successfully on '{name}'")

            # Convert the result to a serializable format
            result_data = {}
            if result:
                if hasattr(result, "content"):
                    # Extract content from the result
                    content_list = []
                    for content_item in result.content:
                        if hasattr(content_item, "text"):
                            content_list.append({"type": "text", "text": content_item.text})
                        elif hasattr(content_item, "data"):
                            content_list.append({"type": "data", "data": content_item.data})
                        else:
                            content_list.append({"type": "unknown", "value": str(content_item)})
                    result_data["content"] = content_list
                if hasattr(result, "isError"):
                    result_data["isError"] = result.isError

            return MCPInvokeResponse(result=result_data)

    except ConnectionError as e:
        logger.error(f"Connection error to MCP server: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to MCP server at {tool_url}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error invoking MCP tool: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error invoking MCP tool: {str(e)}",
        )
