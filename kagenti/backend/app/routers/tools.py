# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tool API endpoints.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
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
    KAGENTI_TRANSPORT_LABEL,
    KAGENTI_WORKLOAD_TYPE_LABEL,
    KAGENTI_DESCRIPTION_ANNOTATION,
    APP_KUBERNETES_IO_CREATED_BY,
    APP_KUBERNETES_IO_NAME,
    APP_KUBERNETES_IO_MANAGED_BY,
    KAGENTI_UI_CREATOR_LABEL,
    RESOURCE_TYPE_TOOL,
    VALUE_PROTOCOL_MCP,
    VALUE_TRANSPORT_STREAMABLE_HTTP,
    TOOL_SERVICE_SUFFIX,
    WORKLOAD_TYPE_DEPLOYMENT,
    WORKLOAD_TYPE_STATEFULSET,
    DEFAULT_IN_CLUSTER_PORT,
    DEFAULT_RESOURCE_LIMITS,
    DEFAULT_RESOURCE_REQUESTS,
    DEFAULT_ENV_VARS,
    # Shipwright constants
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
    SHIPWRIGHT_BUILDS_PLURAL,
    SHIPWRIGHT_BUILDRUNS_PLURAL,
    DEFAULT_INTERNAL_REGISTRY,
    # Migration constants
    MIGRATION_SOURCE_ANNOTATION,
    MIGRATION_TIMESTAMP_ANNOTATION,
    ORIGINAL_SERVICE_ANNOTATION,
    TOOLHIVE_SERVICE_PREFIX,
    TOOLHIVE_SERVICE_SUFFIX,
    MIGRATION_SOURCE_MCPSERVER_CRD,
)
from app.models.responses import (
    ToolSummary,
    ToolListResponse,
    ResourceLabels,
    DeleteResponse,
)
from app.models.shipwright import (
    ResourceType,
    ShipwrightBuildConfig,
    BuildSourceConfig,
    BuildOutputConfig,
    BuildStatusCondition,
    ResourceConfigFromBuild,
)
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.services.shipwright import (
    build_shipwright_build_manifest,
    build_shipwright_buildrun_manifest,
    extract_resource_config_from_build,
    get_latest_buildrun,
    extract_buildrun_info,
    is_build_succeeded,
    get_output_image_from_buildrun,
)
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


class PersistentStorageConfig(BaseModel):
    """Persistent storage configuration for StatefulSet tools."""

    enabled: bool = False
    size: str = "1Gi"


class CreateToolRequest(BaseModel):
    """Request to create a new MCP tool.

    Tools can be deployed from:
    1. Existing container images (deploymentMethod="image")
    2. Source code via Shipwright build (deploymentMethod="source")

    Workload types:
    - "deployment" (default): Standard Kubernetes Deployment
    - "statefulset": StatefulSet with persistent storage
    """

    name: str
    namespace: str
    protocol: str = "streamable_http"
    framework: str = "Python"
    description: Optional[str] = None
    envVars: Optional[List[EnvVar]] = None
    servicePorts: Optional[List[ServicePort]] = None

    # Workload type: "deployment" (default) or "statefulset"
    workloadType: str = "deployment"

    # Persistent storage config (for StatefulSet)
    persistentStorage: Optional[PersistentStorageConfig] = None

    # Deployment method: "image" (existing) or "source" (Shipwright build)
    deploymentMethod: str = "image"

    # For image deployment (existing)
    containerImage: Optional[str] = None
    imagePullSecret: Optional[str] = None

    # For source build (Shipwright)
    gitUrl: Optional[str] = None
    gitRevision: str = "main"
    contextDir: Optional[str] = None
    registryUrl: Optional[str] = None
    registrySecret: Optional[str] = None
    imageTag: str = "v0.0.1"
    shipwrightConfig: Optional[ShipwrightBuildConfig] = None

    # HTTPRoute/Route creation
    createHttpRoute: bool = False


class FinalizeToolBuildRequest(BaseModel):
    """Request to finalize a tool Shipwright build by creating the Deployment/StatefulSet."""

    protocol: Optional[str] = None
    framework: Optional[str] = None
    workloadType: Optional[str] = None  # "deployment" or "statefulset"
    persistentStorage: Optional[PersistentStorageConfig] = None
    envVars: Optional[List[EnvVar]] = None
    servicePorts: Optional[List[ServicePort]] = None
    createHttpRoute: Optional[bool] = None
    imagePullSecret: Optional[str] = None


class ToolShipwrightBuildInfoResponse(BaseModel):
    """Full Shipwright Build information for tools."""

    # Build info
    name: str
    namespace: str
    buildRegistered: bool
    buildReason: Optional[str] = None
    buildMessage: Optional[str] = None
    outputImage: str
    strategy: str
    gitUrl: str
    gitRevision: str
    contextDir: str

    # Latest BuildRun info (if any)
    hasBuildRun: bool = False
    buildRunName: Optional[str] = None
    buildRunPhase: Optional[str] = None  # Pending, Running, Succeeded, Failed
    buildRunStartTime: Optional[str] = None
    buildRunCompletionTime: Optional[str] = None
    buildRunOutputImage: Optional[str] = None
    buildRunOutputDigest: Optional[str] = None
    buildRunFailureMessage: Optional[str] = None

    # Tool configuration from annotations
    toolConfig: Optional[ResourceConfigFromBuild] = None


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


# =============================================================================
# Migration Models (Phase 5: MCPServer CRD to Deployment migration)
# =============================================================================


class MigratableToolInfo(BaseModel):
    """Information about a tool that can be migrated from MCPServer CRD."""

    name: str
    namespace: str
    status: str
    has_deployment: bool  # True if a Deployment already exists with same name
    has_statefulset: bool  # True if a StatefulSet already exists with same name
    labels: Dict[str, str]
    description: Optional[str] = None
    old_service_name: str  # mcp-{name}-proxy (Toolhive)
    new_service_name: str  # {name}-mcp (Kagenti)


class ListMigratableToolsResponse(BaseModel):
    """Response containing list of tools that can be migrated."""

    tools: List[MigratableToolInfo]
    total: int
    already_migrated: int  # Count of tools that already have Deployments/StatefulSets


class MigrateToolRequest(BaseModel):
    """Request to migrate a tool from MCPServer CRD to Deployment."""

    workload_type: str = WORKLOAD_TYPE_DEPLOYMENT  # "deployment" or "statefulset"
    delete_old: bool = False  # Delete MCPServer CRD after migration


class MigrateToolResponse(BaseModel):
    """Response after migrating a tool."""

    success: bool
    name: str
    namespace: str
    message: str
    deployment_created: bool = False
    service_created: bool = False
    mcpserver_deleted: bool = False
    old_service_name: str = ""  # mcp-{name}-proxy
    new_service_name: str = ""  # {name}-mcp


class BatchMigrateToolsRequest(BaseModel):
    """Request to migrate multiple tools in a namespace."""

    workload_type: str = WORKLOAD_TYPE_DEPLOYMENT
    delete_old: bool = False
    dry_run: bool = True


class BatchMigrateToolsResponse(BaseModel):
    """Response after batch migration."""

    total: int
    migrated: int
    skipped: int
    failed: int
    results: List[MigrateToolResponse]
    dry_run: bool


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tools", tags=["tools"])


def _get_toolhive_service_name(tool_name: str) -> str:
    """Get the old Toolhive-style service name.

    Toolhive creates services named: mcp-{name}-proxy
    """
    return f"{TOOLHIVE_SERVICE_PREFIX}{tool_name}{TOOLHIVE_SERVICE_SUFFIX}"


def _is_mcpserver_ready(resource_data: dict) -> str:
    """Check if an MCPServer CRD is ready based on status phase.

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


def _format_timestamp(timestamp) -> Optional[str]:
    """Convert a timestamp to ISO format string.

    The Kubernetes Python client returns datetime objects for timestamp fields,
    but our Pydantic models expect strings.
    """
    if timestamp is None:
        return None
    if isinstance(timestamp, str):
        return timestamp
    if hasattr(timestamp, "isoformat"):
        return timestamp.isoformat()
    return str(timestamp)


def _get_workload_status(workload: dict) -> str:
    """Get status for a Deployment or StatefulSet workload.

    Args:
        workload: Deployment or StatefulSet resource dict

    Returns:
        Status string: "Ready", "Progressing", "Failed", or "Not Ready"
    """
    status = workload.get("status", {})
    spec = workload.get("spec", {})

    # Get replica counts
    desired_replicas = spec.get("replicas", 1)
    ready_replicas = status.get("ready_replicas") or status.get("readyReplicas", 0)
    available_replicas = status.get("available_replicas") or status.get("availableReplicas", 0)

    # Check conditions for more detail
    conditions = status.get("conditions", [])
    for condition in conditions:
        cond_type = condition.get("type", "")
        cond_status = condition.get("status", "")
        cond_reason = condition.get("reason", "")

        # Check for failure conditions
        if cond_type == "Available" and cond_status == "False":
            if "ProgressDeadlineExceeded" in cond_reason:
                return "Failed"

        # Check for progressing
        if cond_type == "Progressing" and cond_status == "True":
            if ready_replicas < desired_replicas:
                return "Progressing"

    # Check if all replicas are ready
    if ready_replicas >= desired_replicas and available_replicas >= desired_replicas:
        return "Ready"

    # Still progressing
    if ready_replicas > 0:
        return "Progressing"

    return "Not Ready"


def _get_workload_type_from_resource(resource: dict) -> str:
    """Determine workload type from a Kubernetes resource.

    Args:
        resource: Kubernetes resource dict

    Returns:
        Workload type: "deployment", "statefulset", or "unknown"
    """
    kind = resource.get("kind", "")
    if kind == "Deployment":
        return WORKLOAD_TYPE_DEPLOYMENT
    elif kind == "StatefulSet":
        return WORKLOAD_TYPE_STATEFULSET
    else:
        # Check labels
        labels = resource.get("metadata", {}).get("labels", {})
        return labels.get(KAGENTI_WORKLOAD_TYPE_LABEL, "unknown")


def _extract_labels(labels: dict) -> ResourceLabels:
    """Extract kagenti labels from Kubernetes labels."""
    return ResourceLabels(
        protocol=labels.get("kagenti.io/protocol"),
        framework=labels.get("kagenti.io/framework"),
        type=labels.get("kagenti.io/type"),
    )


def _build_tool_shipwright_build_manifest(request: CreateToolRequest) -> dict:
    """
    Build a Shipwright Build CRD manifest for building a tool from source.

    This is a wrapper around the shared build_shipwright_build_manifest function
    that converts CreateToolRequest to the shared function's parameters.
    """
    # Determine registry URL
    registry_url = request.registryUrl or DEFAULT_INTERNAL_REGISTRY

    # Build source config
    source_config = BuildSourceConfig(
        gitUrl=request.gitUrl or "",
        gitRevision=request.gitRevision,
        contextDir=request.contextDir or ".",
    )

    # Build output config
    output_config = BuildOutputConfig(
        registry=registry_url,
        imageName=request.name,
        imageTag=request.imageTag,
        pushSecretName=request.registrySecret,
    )

    # Build resource configuration to store in annotation
    resource_config: Dict[str, Any] = {
        "protocol": request.protocol,
        "framework": request.framework,
        "createHttpRoute": request.createHttpRoute,
        "registrySecret": request.registrySecret,
        "workloadType": request.workloadType,
    }
    # Add persistent storage config if present (for StatefulSet)
    if request.persistentStorage:
        resource_config["persistentStorage"] = request.persistentStorage.model_dump()
    # Add env vars if present
    if request.envVars:
        resource_config["envVars"] = [ev.model_dump() for ev in request.envVars]
    # Add service ports if present
    if request.servicePorts:
        resource_config["servicePorts"] = [sp.model_dump() for sp in request.servicePorts]

    return build_shipwright_build_manifest(
        name=request.name,
        namespace=request.namespace,
        resource_type=ResourceType.TOOL,
        source_config=source_config,
        output_config=output_config,
        build_config=request.shipwrightConfig,
        resource_config=resource_config,
        protocol=request.protocol,
        framework=request.framework,
    )


def _build_tool_shipwright_buildrun_manifest(
    build_name: str, namespace: str, labels: Optional[Dict[str, str]] = None
) -> dict:
    """
    Build a Shipwright BuildRun CRD manifest to trigger a tool build.

    This is a wrapper around the shared build_shipwright_buildrun_manifest function.
    """
    return build_shipwright_buildrun_manifest(
        build_name=build_name,
        namespace=namespace,
        resource_type=ResourceType.TOOL,
        labels=labels,
    )


@router.get("", response_model=ToolListResponse)
async def list_tools(
    namespace: str = Query(default="default", description="Kubernetes namespace"),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ToolListResponse:
    """
    List all MCP tools in the specified namespace.

    Returns tools that have the kagenti.io/type=tool label.
    Queries both Deployments and StatefulSets.

    If enable_legacy_mcpserver_crd is enabled, also includes MCPServer CRDs
    that haven't been migrated yet.
    """
    try:
        label_selector = f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_TOOL}"
        tools = []
        existing_names = set()  # Track names to avoid duplicates with legacy CRDs

        # Query Deployments with tool label
        try:
            deployments = kube.list_deployments(namespace, label_selector)
            for deploy in deployments:
                metadata = deploy.get("metadata", {})
                annotations = metadata.get("annotations", {})
                name = metadata.get("name", "")
                existing_names.add(name)

                tools.append(
                    ToolSummary(
                        name=name,
                        namespace=metadata.get("namespace", namespace),
                        description=annotations.get(KAGENTI_DESCRIPTION_ANNOTATION, ""),
                        status=_get_workload_status(deploy),
                        labels=_extract_labels(metadata.get("labels", {})),
                        createdAt=_format_timestamp(
                            metadata.get("creation_timestamp") or metadata.get("creationTimestamp")
                        ),
                        workloadType=WORKLOAD_TYPE_DEPLOYMENT,
                    )
                )
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Error listing Deployments: {e}")

        # Query StatefulSets with tool label
        try:
            statefulsets = kube.list_statefulsets(namespace, label_selector)
            for sts in statefulsets:
                metadata = sts.get("metadata", {})
                annotations = metadata.get("annotations", {})
                name = metadata.get("name", "")
                existing_names.add(name)

                tools.append(
                    ToolSummary(
                        name=name,
                        namespace=metadata.get("namespace", namespace),
                        description=annotations.get(KAGENTI_DESCRIPTION_ANNOTATION, ""),
                        status=_get_workload_status(sts),
                        labels=_extract_labels(metadata.get("labels", {})),
                        createdAt=_format_timestamp(
                            metadata.get("creation_timestamp") or metadata.get("creationTimestamp")
                        ),
                        workloadType=WORKLOAD_TYPE_STATEFULSET,
                    )
                )
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Error listing StatefulSets: {e}")

        # If legacy MCPServer CRD support is enabled, include unmigrated CRDs
        if settings.enable_legacy_mcpserver_crd:
            try:
                mcpserver_crds = kube.list_custom_resources(
                    group=TOOLHIVE_CRD_GROUP,
                    version=TOOLHIVE_CRD_VERSION,
                    namespace=namespace,
                    plural=TOOLHIVE_MCP_PLURAL,
                    label_selector=label_selector,
                )
                for mcpserver in mcpserver_crds:
                    metadata = mcpserver.get("metadata", {})
                    name = metadata.get("name", "")

                    # Skip if already migrated (has Deployment or StatefulSet)
                    if name in existing_names:
                        continue

                    annotations = metadata.get("annotations", {})
                    tools.append(
                        ToolSummary(
                            name=name,
                            namespace=metadata.get("namespace", namespace),
                            description=annotations.get(KAGENTI_DESCRIPTION_ANNOTATION, ""),
                            status=_is_mcpserver_ready(mcpserver),
                            labels=_extract_labels(metadata.get("labels", {})),
                            createdAt=_format_timestamp(
                                metadata.get("creation_timestamp")
                                or metadata.get("creationTimestamp")
                            ),
                            workloadType="mcpserver",  # Legacy workload type
                        )
                    )
            except ApiException as e:
                if e.status != 404:
                    logger.warning(f"Error listing MCPServer CRDs: {e}")

        return ToolListResponse(items=tools)

    except ApiException as e:
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
    """Get detailed information about a specific tool.

    Tries to find the tool as a Deployment first, then as a StatefulSet.
    Returns the workload details along with associated Service information.
    """
    workload = None
    workload_type = None

    # Try Deployment first
    try:
        workload = kube.get_deployment(namespace, name)
        workload_type = WORKLOAD_TYPE_DEPLOYMENT
    except ApiException as e:
        if e.status != 404:
            raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Try StatefulSet if Deployment not found
    if workload is None:
        try:
            workload = kube.get_statefulset(namespace, name)
            workload_type = WORKLOAD_TYPE_STATEFULSET
        except ApiException as e:
            if e.status == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Tool '{name}' not found in namespace '{namespace}'",
                )
            raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Get associated Service
    service_info = None
    service_name = _get_tool_service_name(name)
    try:
        service = kube.get_service(namespace, service_name)
        # Transform raw K8s Service to ServiceInfo format expected by frontend
        service_info = {
            "name": service.get("metadata", {}).get("name"),
            "type": service.get("spec", {}).get("type"),
            "clusterIP": service.get("spec", {}).get("cluster_ip"),
            "ports": service.get("spec", {}).get("ports", []),
        }
    except ApiException as e:
        if e.status != 404:
            logger.warning(f"Error getting Service '{service_name}': {e}")

    # Build response with workload and service details
    # Return both raw status (for conditions display) and computed readyStatus string
    return {
        "metadata": workload.get("metadata", {}),
        "spec": workload.get("spec", {}),
        "status": workload.get("status", {}),
        "readyStatus": _get_workload_status(workload),
        "workloadType": workload_type,
        "service": service_info,
    }


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
    """Delete a tool and associated resources from the cluster.

    Deletes in order:
    1. Shipwright BuildRuns (if any)
    2. Shipwright Build (if any)
    3. Deployment or StatefulSet
    4. Service
    """
    deleted_resources = []

    # Delete BuildRuns first (they reference the Build)
    try:
        buildruns = kube.list_custom_resources(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector=f"kagenti.io/build-name={name}",
        )
        for buildrun in buildruns:
            br_name = buildrun.get("metadata", {}).get("name")
            if br_name:
                try:
                    kube.delete_custom_resource(
                        group=SHIPWRIGHT_CRD_GROUP,
                        version=SHIPWRIGHT_CRD_VERSION,
                        namespace=namespace,
                        plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                        name=br_name,
                    )
                    deleted_resources.append(f"BuildRun/{br_name}")
                except ApiException:
                    pass  # Ignore individual BuildRun deletion errors
    except ApiException:
        pass  # Ignore if BuildRuns not found

    # Delete Shipwright Build
    try:
        kube.delete_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name=name,
        )
        deleted_resources.append(f"Build/{name}")
    except ApiException as e:
        if e.status != 404:
            logger.warning(f"Failed to delete Shipwright Build '{name}': {e}")

    # Delete Deployment (if exists)
    try:
        kube.delete_deployment(namespace, name)
        deleted_resources.append(f"Deployment/{name}")
    except ApiException as e:
        if e.status != 404:
            logger.warning(f"Failed to delete Deployment '{name}': {e}")

    # Delete StatefulSet (if exists)
    try:
        kube.delete_statefulset(namespace, name)
        deleted_resources.append(f"StatefulSet/{name}")
    except ApiException as e:
        if e.status != 404:
            logger.warning(f"Failed to delete StatefulSet '{name}': {e}")

    # Delete Service
    service_name = _get_tool_service_name(name)
    try:
        kube.delete_service(namespace, service_name)
        deleted_resources.append(f"Service/{service_name}")
    except ApiException as e:
        if e.status != 404:
            logger.warning(f"Failed to delete Service '{service_name}': {e}")

    if deleted_resources:
        return DeleteResponse(
            success=True,
            message=f"Tool '{name}' deleted. Resources: {', '.join(deleted_resources)}",
        )
    else:
        return DeleteResponse(success=True, message=f"Tool '{name}' already deleted")


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
            "description": f"Tool '{request.name}' deployed from existing image '{request.containerImage}'",
            "image": request.containerImage,
            "transport": "streamable-http",
            "port": port,
            "targetPort": target_port,
            "proxyPort": DEFAULT_IN_CLUSTER_PORT,
            "podTemplateSpec": {
                "spec": {
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


def _build_tool_deployment_manifest(
    name: str,
    namespace: str,
    image: str,
    protocol: str = "streamable_http",
    framework: str = "Python",
    description: str = "",
    env_vars: Optional[List[Dict[str, str]]] = None,
    service_ports: Optional[List[Dict[str, Any]]] = None,
    image_pull_secret: Optional[str] = None,
    shipwright_build_name: Optional[str] = None,
) -> dict:
    """
    Build a Kubernetes Deployment manifest for an MCP tool.

    This replaces the MCPServer CRD approach by directly creating Deployments.

    Args:
        name: Tool name
        namespace: Kubernetes namespace
        image: Container image URL (may include digest)
        protocol: Tool protocol (default: streamable_http)
        framework: Tool framework (default: Python)
        description: Tool description
        env_vars: Additional environment variables
        service_ports: Service port configuration
        image_pull_secret: Image pull secret name
        shipwright_build_name: Name of Shipwright build (if built from source)

    Returns:
        Deployment manifest dict
    """
    # Build environment variables
    all_env_vars = list(DEFAULT_ENV_VARS)
    if env_vars:
        all_env_vars.extend(env_vars)

    # Determine target port
    target_port = DEFAULT_IN_CLUSTER_PORT
    if service_ports and len(service_ports) > 0:
        target_port = service_ports[0].get("targetPort", DEFAULT_IN_CLUSTER_PORT)

    # Build labels - required labels per migration plan
    labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
        KAGENTI_PROTOCOL_LABEL: VALUE_PROTOCOL_MCP,
        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
        KAGENTI_FRAMEWORK_LABEL: framework,
        KAGENTI_WORKLOAD_TYPE_LABEL: WORKLOAD_TYPE_DEPLOYMENT,
        APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
    }

    # Build annotations
    annotations = {}
    if description:
        annotations[KAGENTI_DESCRIPTION_ANNOTATION] = description
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name

    manifest = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
            "annotations": annotations if annotations else None,
        },
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
                    APP_KUBERNETES_IO_NAME: name,
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
                        APP_KUBERNETES_IO_NAME: name,
                        KAGENTI_PROTOCOL_LABEL: VALUE_PROTOCOL_MCP,
                        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
                        KAGENTI_FRAMEWORK_LABEL: framework,
                    }
                },
                "spec": {
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "mcp",
                            "image": image,
                            "imagePullPolicy": "Always",
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                                "runAsUser": 1000,
                            },
                            "env": all_env_vars,
                            "ports": [
                                {
                                    "containerPort": target_port,
                                    "name": "http",
                                    "protocol": "TCP",
                                }
                            ],
                            "resources": {
                                "limits": DEFAULT_RESOURCE_LIMITS,
                                "requests": DEFAULT_RESOURCE_REQUESTS,
                            },
                            "volumeMounts": [
                                {"name": "cache", "mountPath": "/app/.cache"},
                                {"name": "tmp", "mountPath": "/tmp"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "cache", "emptyDir": {}},
                        {"name": "tmp", "emptyDir": {}},
                    ],
                },
            },
        },
    }

    # Remove None annotations
    if manifest["metadata"]["annotations"] is None:
        del manifest["metadata"]["annotations"]

    # Add image pull secrets if specified
    if image_pull_secret:
        manifest["spec"]["template"]["spec"]["imagePullSecrets"] = [{"name": image_pull_secret}]

    return manifest


def _build_tool_statefulset_manifest(
    name: str,
    namespace: str,
    image: str,
    protocol: str = "streamable_http",
    framework: str = "Python",
    description: str = "",
    env_vars: Optional[List[Dict[str, str]]] = None,
    service_ports: Optional[List[Dict[str, Any]]] = None,
    image_pull_secret: Optional[str] = None,
    shipwright_build_name: Optional[str] = None,
    storage_size: str = "1Gi",
) -> dict:
    """
    Build a Kubernetes StatefulSet manifest for an MCP tool.

    Use StatefulSet for tools that require persistent storage.

    Args:
        name: Tool name
        namespace: Kubernetes namespace
        image: Container image URL (may include digest)
        protocol: Tool protocol (default: streamable_http)
        framework: Tool framework (default: Python)
        description: Tool description
        env_vars: Additional environment variables
        service_ports: Service port configuration
        image_pull_secret: Image pull secret name
        shipwright_build_name: Name of Shipwright build (if built from source)
        storage_size: PVC storage size (default: 1Gi)

    Returns:
        StatefulSet manifest dict
    """
    # Build environment variables
    all_env_vars = list(DEFAULT_ENV_VARS)
    if env_vars:
        all_env_vars.extend(env_vars)

    # Determine target port
    target_port = DEFAULT_IN_CLUSTER_PORT
    if service_ports and len(service_ports) > 0:
        target_port = service_ports[0].get("targetPort", DEFAULT_IN_CLUSTER_PORT)

    # Service name for StatefulSet (must match the headless service)
    service_name = f"{name}{TOOL_SERVICE_SUFFIX}"

    # Build labels - required labels per migration plan
    labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
        KAGENTI_PROTOCOL_LABEL: VALUE_PROTOCOL_MCP,
        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
        KAGENTI_FRAMEWORK_LABEL: framework,
        KAGENTI_WORKLOAD_TYPE_LABEL: WORKLOAD_TYPE_STATEFULSET,
        APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
    }

    # Build annotations
    annotations = {}
    if description:
        annotations[KAGENTI_DESCRIPTION_ANNOTATION] = description
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name

    manifest = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
            "annotations": annotations if annotations else None,
        },
        "spec": {
            "serviceName": service_name,
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
                    APP_KUBERNETES_IO_NAME: name,
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
                        APP_KUBERNETES_IO_NAME: name,
                        KAGENTI_PROTOCOL_LABEL: VALUE_PROTOCOL_MCP,
                        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
                        KAGENTI_FRAMEWORK_LABEL: framework,
                    }
                },
                "spec": {
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "mcp",
                            "image": image,
                            "imagePullPolicy": "Always",
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                                "runAsUser": 1000,
                            },
                            "env": all_env_vars,
                            "ports": [
                                {
                                    "containerPort": target_port,
                                    "name": "http",
                                    "protocol": "TCP",
                                }
                            ],
                            "resources": {
                                "limits": DEFAULT_RESOURCE_LIMITS,
                                "requests": DEFAULT_RESOURCE_REQUESTS,
                            },
                            "volumeMounts": [
                                {"name": "data", "mountPath": "/data"},
                                {"name": "cache", "mountPath": "/app/.cache"},
                                {"name": "tmp", "mountPath": "/tmp"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "cache", "emptyDir": {}},
                        {"name": "tmp", "emptyDir": {}},
                    ],
                },
            },
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "data"},
                    "spec": {
                        "accessModes": ["ReadWriteOnce"],
                        "resources": {"requests": {"storage": storage_size}},
                    },
                }
            ],
        },
    }

    # Remove None annotations
    if manifest["metadata"]["annotations"] is None:
        del manifest["metadata"]["annotations"]

    # Add image pull secrets if specified
    if image_pull_secret:
        manifest["spec"]["template"]["spec"]["imagePullSecrets"] = [{"name": image_pull_secret}]

    return manifest


def _build_tool_service_manifest(
    name: str,
    namespace: str,
    service_ports: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """
    Build a Kubernetes Service manifest for an MCP tool.

    Service naming convention: {name}-mcp
    This creates a ClusterIP service that routes to the tool pods.

    Args:
        name: Tool name
        namespace: Kubernetes namespace
        service_ports: Service port configuration

    Returns:
        Service manifest dict
    """
    # Determine ports
    if service_ports and len(service_ports) > 0:
        port = service_ports[0].get("port", DEFAULT_IN_CLUSTER_PORT)
        target_port = service_ports[0].get("targetPort", DEFAULT_IN_CLUSTER_PORT)
    else:
        port = DEFAULT_IN_CLUSTER_PORT
        target_port = DEFAULT_IN_CLUSTER_PORT

    # Service name follows the convention: {name}-mcp
    service_name = f"{name}{TOOL_SERVICE_SUFFIX}"

    manifest = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "namespace": namespace,
            "labels": {
                KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
                KAGENTI_PROTOCOL_LABEL: VALUE_PROTOCOL_MCP,
                APP_KUBERNETES_IO_NAME: name,
                APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
            },
        },
        "spec": {
            "type": "ClusterIP",
            "selector": {
                KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
                APP_KUBERNETES_IO_NAME: name,
            },
            "ports": [
                {
                    "name": "http",
                    "port": port,
                    "targetPort": target_port,
                    "protocol": "TCP",
                }
            ],
        },
    }

    return manifest


def _get_tool_service_name(name: str) -> str:
    """Get the service name for a tool.

    Args:
        name: Tool name

    Returns:
        Service name following convention: {name}-mcp
    """
    return f"{name}{TOOL_SERVICE_SUFFIX}"


@router.post("", response_model=CreateToolResponse)
async def create_tool(
    request: CreateToolRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> CreateToolResponse:
    """
    Create a new MCP tool.

    Supports two deployment methods:
    1. "image" - Deploy from existing container image (Deployment + Service)
    2. "source" - Build from source using Shipwright, then deploy

    Supports two workload types:
    1. "deployment" (default) - Standard Kubernetes Deployment
    2. "statefulset" - StatefulSet with persistent storage

    For source builds, creates a Shipwright Build + BuildRun and returns.
    The Deployment/StatefulSet is created later via the finalize-shipwright-build endpoint.
    """
    try:
        # Validate workload type
        if request.workloadType not in [WORKLOAD_TYPE_DEPLOYMENT, WORKLOAD_TYPE_STATEFULSET]:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported workload type: {request.workloadType}. "
                f"Supported types: {WORKLOAD_TYPE_DEPLOYMENT}, {WORKLOAD_TYPE_STATEFULSET}",
            )

        if request.deploymentMethod == "source":
            # Source build using Shipwright
            if not request.gitUrl:
                raise HTTPException(
                    status_code=400,
                    detail="gitUrl is required for source deployment",
                )

            # Step 1: Create Shipwright Build CR
            build_manifest = _build_tool_shipwright_build_manifest(request)
            kube.create_custom_resource(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace=request.namespace,
                plural=SHIPWRIGHT_BUILDS_PLURAL,
                body=build_manifest,
            )
            logger.info(
                f"Created Shipwright Build '{request.name}' for tool in namespace '{request.namespace}'"
            )

            # Step 2: Create BuildRun CR to trigger the build
            build_labels = build_manifest.get("metadata", {}).get("labels", {})
            buildrun_manifest = _build_tool_shipwright_buildrun_manifest(
                build_name=request.name,
                namespace=request.namespace,
                labels=build_labels,
            )
            created_buildrun = kube.create_custom_resource(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace=request.namespace,
                plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                body=buildrun_manifest,
            )
            buildrun_name = created_buildrun.get("metadata", {}).get("name", "")
            logger.info(
                f"Created Shipwright BuildRun '{buildrun_name}' for tool in namespace '{request.namespace}'"
            )

            message = (
                f"Shipwright build started for tool '{request.name}'. "
                f"BuildRun: {buildrun_name}. "
                f"Monitor progress at /tools/{request.namespace}/{request.name}/build"
            )

            return CreateToolResponse(
                success=True,
                name=request.name,
                namespace=request.namespace,
                message=message,
            )

        else:
            # Image deployment - create Deployment/StatefulSet + Service
            if not request.containerImage:
                raise HTTPException(
                    status_code=400,
                    detail="containerImage is required for image deployment",
                )

            # Prepare env vars
            env_vars = None
            if request.envVars:
                env_vars = [{"name": ev.name, "value": ev.value} for ev in request.envVars]

            # Prepare service ports
            service_ports = None
            if request.servicePorts:
                service_ports = [sp.model_dump() for sp in request.servicePorts]

            # Set description if not provided
            description = request.description
            if not description:
                description = (
                    f"Tool '{request.name}' deployed from existing image '{request.containerImage}'"
                )

            # Create workload (Deployment or StatefulSet)
            if request.workloadType == WORKLOAD_TYPE_STATEFULSET:
                # Determine storage size
                storage_size = "1Gi"
                if request.persistentStorage and request.persistentStorage.enabled:
                    storage_size = request.persistentStorage.size

                workload_manifest = _build_tool_statefulset_manifest(
                    name=request.name,
                    namespace=request.namespace,
                    image=request.containerImage,
                    protocol=request.protocol,
                    framework=request.framework,
                    env_vars=env_vars,
                    service_ports=service_ports,
                    image_pull_secret=request.imagePullSecret,
                    storage_size=storage_size,
                    description=description,
                )
                kube.create_statefulset(request.namespace, workload_manifest)
                logger.info(
                    f"Created StatefulSet '{request.name}' for tool in namespace '{request.namespace}'"
                )
            else:
                # Default: Deployment
                workload_manifest = _build_tool_deployment_manifest(
                    name=request.name,
                    namespace=request.namespace,
                    image=request.containerImage,
                    protocol=request.protocol,
                    framework=request.framework,
                    env_vars=env_vars,
                    service_ports=service_ports,
                    image_pull_secret=request.imagePullSecret,
                    description=description,
                )
                kube.create_deployment(request.namespace, workload_manifest)
                logger.info(
                    f"Created Deployment '{request.name}' for tool in namespace '{request.namespace}'"
                )

            # Create Service for the tool
            service_manifest = _build_tool_service_manifest(
                name=request.name,
                namespace=request.namespace,
                service_ports=service_ports,
            )
            kube.create_service(request.namespace, service_manifest)
            service_name = _get_tool_service_name(request.name)
            logger.info(
                f"Created Service '{service_name}' for tool in namespace '{request.namespace}'"
            )

            message = f"Tool '{request.name}' deployment started ({request.workloadType})."

            # Create HTTPRoute/Route if requested
            # Service is now {name}-mcp on port 8000
            if request.createHttpRoute:
                service_port = DEFAULT_IN_CLUSTER_PORT
                if service_ports and len(service_ports) > 0:
                    service_port = service_ports[0].get("port", DEFAULT_IN_CLUSTER_PORT)

                create_route_for_agent_or_tool(
                    kube=kube,
                    name=request.name,
                    namespace=request.namespace,
                    service_name=service_name,
                    service_port=service_port,
                )
                message += " HTTPRoute/Route created for external access."

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
                detail="Failed to create tool resources. Check cluster connectivity.",
            )
        logger.error(f"Failed to create tool: {e}")
        raise HTTPException(status_code=e.status, detail=str(e.reason))


# Shipwright Build Endpoints for Tools


@router.get(
    "/{namespace}/{name}/shipwright-build-info",
    response_model=ToolShipwrightBuildInfoResponse,
)
async def get_tool_shipwright_build_info(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ToolShipwrightBuildInfoResponse:
    """Get full Shipwright Build information including tool config and BuildRun status.

    This endpoint provides all the information needed for the build progress page:
    - Build configuration and status
    - Latest BuildRun status
    - Tool configuration stored in annotations
    """
    try:
        # Get the Build resource
        build = kube.get_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name=name,
        )

        metadata = build.get("metadata", {})
        spec = build.get("spec", {})
        status = build.get("status", {})

        # Extract build info
        source = spec.get("source", {})
        git_info = source.get("git", {})
        strategy = spec.get("strategy", {})
        output = spec.get("output", {})

        # Parse tool config from annotations using shared utility
        tool_config = extract_resource_config_from_build(build, ResourceType.TOOL)

        # Build response with basic build info
        response = ToolShipwrightBuildInfoResponse(
            name=metadata.get("name", name),
            namespace=metadata.get("namespace", namespace),
            buildRegistered=status.get("registered", False),
            buildReason=status.get("reason"),
            buildMessage=status.get("message"),
            outputImage=output.get("image", ""),
            strategy=strategy.get("name", ""),
            gitUrl=git_info.get("url", ""),
            gitRevision=git_info.get("revision", ""),
            contextDir=source.get("contextDir", ""),
            toolConfig=tool_config,
        )

        # Try to get the latest BuildRun
        try:
            items = kube.list_custom_resources(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace=namespace,
                plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                label_selector=f"kagenti.io/build-name={name}",
            )

            if items:
                latest_buildrun = get_latest_buildrun(items)
                if latest_buildrun:
                    buildrun_info = extract_buildrun_info(latest_buildrun)

                    response.hasBuildRun = True
                    response.buildRunName = buildrun_info["name"]
                    response.buildRunPhase = buildrun_info["phase"]
                    response.buildRunStartTime = buildrun_info["startTime"]
                    response.buildRunCompletionTime = buildrun_info["completionTime"]
                    response.buildRunOutputImage = buildrun_info["outputImage"]
                    response.buildRunOutputDigest = buildrun_info["outputDigest"]
                    response.buildRunFailureMessage = buildrun_info["failureMessage"]

        except ApiException as e:
            # BuildRun not found is OK, just means no build has been triggered
            if e.status != 404:
                logger.warning(f"Failed to get BuildRun for build '{name}': {e}")

        return response

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Shipwright Build '{name}' not found in namespace '{namespace}'",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@router.post("/{namespace}/{name}/shipwright-buildrun")
async def create_tool_buildrun(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> dict:
    """Trigger a new BuildRun for an existing Shipwright Build.

    This endpoint creates a new BuildRun CR that references the existing Build.
    Use this to retry a failed build or trigger a new build after source changes.
    """
    try:
        # Verify the Build exists
        build = kube.get_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name=name,
        )

        # Get labels from the Build to propagate to BuildRun
        build_labels = build.get("metadata", {}).get("labels", {})
        buildrun_labels = {
            k: v
            for k, v in build_labels.items()
            if k.startswith("kagenti.io/") or k.startswith("app.kubernetes.io/")
        }

        # Create BuildRun manifest
        buildrun_manifest = _build_tool_shipwright_buildrun_manifest(
            build_name=name,
            namespace=namespace,
            labels=buildrun_labels,
        )

        # Create the BuildRun
        created_buildrun = kube.create_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            body=buildrun_manifest,
        )

        return {
            "success": True,
            "buildRunName": created_buildrun.get("metadata", {}).get("name"),
            "namespace": namespace,
            "buildName": name,
            "message": "BuildRun created successfully",
        }

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Build '{name}' not found in namespace '{namespace}'",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@router.post("/{namespace}/{name}/finalize-shipwright-build", response_model=CreateToolResponse)
async def finalize_tool_shipwright_build(
    namespace: str,
    name: str,
    request: FinalizeToolBuildRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> CreateToolResponse:
    """Create Deployment/StatefulSet + Service after Shipwright build completes successfully.

    This endpoint:
    1. Gets the latest BuildRun and verifies it succeeded
    2. Extracts the output image from BuildRun status
    3. Reads tool config from Build annotations
    4. Creates Deployment or StatefulSet with the built image
    5. Creates Service for the tool
    6. Creates HTTPRoute if createHttpRoute is true
    7. Adds kagenti.io/shipwright-build annotation to workload
    """
    try:
        # Get the Build resource
        build = kube.get_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name=name,
        )

        # Get the latest BuildRun
        buildruns = kube.list_custom_resources(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector=f"kagenti.io/build-name={name}",
        )

        if not buildruns:
            raise HTTPException(
                status_code=400,
                detail=f"No BuildRun found for Build '{name}'. Run a build first.",
            )

        latest_buildrun = get_latest_buildrun(buildruns)
        if not latest_buildrun:
            raise HTTPException(
                status_code=400,
                detail=f"No BuildRun found for Build '{name}'. Run a build first.",
            )

        # Verify build succeeded
        if not is_build_succeeded(latest_buildrun):
            buildrun_info = extract_buildrun_info(latest_buildrun)
            raise HTTPException(
                status_code=400,
                detail=f"Build not succeeded. Current phase: {buildrun_info['phase']}. "
                f"Error: {buildrun_info.get('failureMessage', 'N/A')}",
            )

        # Get output image from BuildRun or Build
        output_image, output_digest = get_output_image_from_buildrun(
            latest_buildrun, fallback_build=build
        )
        if not output_image:
            raise HTTPException(
                status_code=500,
                detail="Could not determine output image from BuildRun",
            )

        # Include digest in image reference if available
        if output_digest:
            image_with_digest = f"{output_image}@{output_digest}"
        else:
            image_with_digest = output_image

        # Extract tool config from Build annotations
        tool_config = extract_resource_config_from_build(build, ResourceType.TOOL)
        if tool_config:
            tool_config_dict = tool_config.model_dump()
        else:
            tool_config_dict = {}

        # Apply request overrides
        protocol = request.protocol or tool_config_dict.get("protocol", "streamable_http")
        framework = request.framework or tool_config_dict.get("framework", "Python")
        create_http_route = (
            request.createHttpRoute
            if request.createHttpRoute is not None
            else tool_config_dict.get("createHttpRoute", False)
        )

        # Determine workload type
        workload_type = request.workloadType or tool_config_dict.get(
            "workloadType", WORKLOAD_TYPE_DEPLOYMENT
        )

        # Build env vars
        env_vars = None
        if request.envVars:
            env_vars = [{"name": ev.name, "value": ev.value} for ev in request.envVars]
        elif tool_config_dict.get("envVars"):
            env_vars = tool_config_dict["envVars"]

        # Build service ports
        service_ports = None
        if request.servicePorts:
            service_ports = [sp.model_dump() for sp in request.servicePorts]
        elif tool_config_dict.get("servicePorts"):
            service_ports = tool_config_dict["servicePorts"]

        # Determine image pull secret
        image_pull_secret = request.imagePullSecret or tool_config_dict.get("registrySecret")

        # Create workload (Deployment or StatefulSet)
        if workload_type == WORKLOAD_TYPE_STATEFULSET:
            # Determine storage size - check request first, then tool config
            storage_size = "1Gi"
            if request.persistentStorage and request.persistentStorage.enabled:
                storage_size = request.persistentStorage.size
            elif tool_config_dict.get("persistentStorage", {}).get("enabled"):
                storage_size = tool_config_dict["persistentStorage"].get("size", "1Gi")

            workload_manifest = _build_tool_statefulset_manifest(
                name=name,
                namespace=namespace,
                image=image_with_digest,
                protocol=protocol,
                framework=framework,
                description=tool_config_dict.get("description", ""),
                env_vars=env_vars,
                service_ports=service_ports,
                image_pull_secret=image_pull_secret,
                shipwright_build_name=name,
                storage_size=storage_size,
            )
            kube.create_statefulset(namespace, workload_manifest)
            logger.info(
                f"Created StatefulSet '{name}' in namespace '{namespace}' from Shipwright build"
            )
        else:
            # Default: Deployment
            workload_manifest = _build_tool_deployment_manifest(
                name=name,
                namespace=namespace,
                image=image_with_digest,
                protocol=protocol,
                framework=framework,
                description=tool_config_dict.get("description", ""),
                env_vars=env_vars,
                service_ports=service_ports,
                image_pull_secret=image_pull_secret,
                shipwright_build_name=name,
            )
            kube.create_deployment(namespace, workload_manifest)
            logger.info(
                f"Created Deployment '{name}' in namespace '{namespace}' from Shipwright build"
            )

        # Create Service for the tool
        service_manifest = _build_tool_service_manifest(
            name=name,
            namespace=namespace,
            service_ports=service_ports,
        )
        kube.create_service(namespace, service_manifest)
        service_name = _get_tool_service_name(name)
        logger.info(
            f"Created Service '{service_name}' in namespace '{namespace}' from Shipwright build"
        )

        message = f"Tool '{name}' created from Shipwright build ({workload_type})."

        # Create HTTPRoute if requested
        if create_http_route:
            service_port = DEFAULT_IN_CLUSTER_PORT
            if service_ports and len(service_ports) > 0:
                service_port = service_ports[0].get("port", DEFAULT_IN_CLUSTER_PORT)

            create_route_for_agent_or_tool(
                kube=kube,
                name=name,
                namespace=namespace,
                service_name=service_name,
                service_port=service_port,
            )
            message += " HTTPRoute/Route created for external access."

        return CreateToolResponse(
            success=True,
            name=name,
            namespace=namespace,
            message=message,
        )

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Shipwright Build '{name}' not found in namespace '{namespace}'",
            )
        if e.status == 409:
            raise HTTPException(
                status_code=409,
                detail=f"Tool '{name}' already exists in namespace '{namespace}'",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))


def _get_tool_url(name: str, namespace: str) -> str:
    """Get the URL for an MCP tool server.

    Service naming convention:
    - Service name: {name}-mcp
    - Port: 8000

    Returns different URL formats based on deployment context:
    - In-cluster: http://{name}-mcp.{namespace}.svc.cluster.local:8000
    - Off-cluster (local dev): http://{name}.{domain}:8080 (via HTTPRoute)
    """
    if settings.is_running_in_cluster:
        # In-cluster: use service DNS with new naming convention
        service_name = _get_tool_service_name(name)
        return f"http://{service_name}.{namespace}.svc.cluster.local:{DEFAULT_IN_CLUSTER_PORT}"
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


# =============================================================================
# MIGRATION ENDPOINTS (Phase 5: MCPServer CRD to Deployment migration)
# =============================================================================


def _build_deployment_from_mcpserver(mcpserver: Dict, namespace: str) -> Dict:
    """
    Build a Kubernetes Deployment manifest from an MCPServer CRD.

    Args:
        mcpserver: The MCPServer CRD resource dictionary.
        namespace: Kubernetes namespace.

    Returns:
        Deployment manifest dictionary.
    """
    metadata = mcpserver.get("metadata", {})
    spec = mcpserver.get("spec", {})
    name = metadata.get("name", "")

    # Get labels from MCPServer CRD and update for Deployment
    labels = metadata.get("labels", {}).copy()

    # Ensure required labels are set
    labels[KAGENTI_TYPE_LABEL] = RESOURCE_TYPE_TOOL
    labels[APP_KUBERNETES_IO_NAME] = name
    labels[KAGENTI_PROTOCOL_LABEL] = VALUE_PROTOCOL_MCP
    labels[KAGENTI_TRANSPORT_LABEL] = VALUE_TRANSPORT_STREAMABLE_HTTP
    labels[KAGENTI_WORKLOAD_TYPE_LABEL] = WORKLOAD_TYPE_DEPLOYMENT
    labels[APP_KUBERNETES_IO_MANAGED_BY] = KAGENTI_UI_CREATOR_LABEL

    # Preserve framework label if present
    if KAGENTI_FRAMEWORK_LABEL not in labels:
        labels[KAGENTI_FRAMEWORK_LABEL] = "Python"

    # Build annotations with migration tracking
    annotations = metadata.get("annotations", {}).copy()
    annotations[MIGRATION_SOURCE_ANNOTATION] = MIGRATION_SOURCE_MCPSERVER_CRD
    annotations[MIGRATION_TIMESTAMP_ANNOTATION] = datetime.now(timezone.utc).isoformat()
    annotations[ORIGINAL_SERVICE_ANNOTATION] = _get_toolhive_service_name(name)

    # Get image from spec
    image = spec.get("image", "")
    if not image:
        raise ValueError(f"MCPServer CRD '{name}' has no image specified")

    # Get port configuration
    target_port = spec.get("targetPort", DEFAULT_IN_CLUSTER_PORT)

    # Extract pod template from MCPServer CRD
    pod_template_spec = spec.get("podTemplateSpec", {})
    pod_spec = pod_template_spec.get("spec", {})

    # Get containers from pod template or build default
    containers = pod_spec.get("containers", [])
    if containers:
        # Use existing container configuration
        container = containers[0].copy()
        # Ensure image is set (override if different in spec.image)
        if image:
            container["image"] = image
        # Ensure imagePullPolicy is set
        if "imagePullPolicy" not in container:
            container["imagePullPolicy"] = "Always"
        # Ensure ports are set
        if "ports" not in container:
            container["ports"] = [{"name": "http", "containerPort": target_port, "protocol": "TCP"}]
        # Ensure resources are set
        if "resources" not in container:
            container["resources"] = {
                "limits": DEFAULT_RESOURCE_LIMITS,
                "requests": DEFAULT_RESOURCE_REQUESTS,
            }
        # Ensure volumeMounts are set
        if "volumeMounts" not in container:
            container["volumeMounts"] = [
                {"name": "cache", "mountPath": "/app/.cache"},
                {"name": "tmp", "mountPath": "/tmp"},
            ]
    else:
        # Build default container spec
        env_vars = list(DEFAULT_ENV_VARS)
        container = {
            "name": "mcp",
            "image": image,
            "imagePullPolicy": "Always",
            "env": env_vars,
            "ports": [{"name": "http", "containerPort": target_port, "protocol": "TCP"}],
            "resources": {
                "limits": DEFAULT_RESOURCE_LIMITS,
                "requests": DEFAULT_RESOURCE_REQUESTS,
            },
            "volumeMounts": [
                {"name": "cache", "mountPath": "/app/.cache"},
                {"name": "tmp", "mountPath": "/tmp"},
            ],
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
                "runAsUser": 1000,
            },
        }

    # Get volumes from pod template or use defaults
    volumes = pod_spec.get(
        "volumes",
        [
            {"name": "cache", "emptyDir": {}},
            {"name": "tmp", "emptyDir": {}},
        ],
    )

    # Get security context from pod template or use defaults
    security_context = pod_spec.get(
        "securityContext",
        {
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
    )

    # Get image pull secrets
    image_pull_secrets = pod_spec.get("imagePullSecrets", [])

    # Get service account name
    service_account_name = pod_spec.get("serviceAccountName")

    # Build selector labels
    selector_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
    }

    # Build pod template labels
    pod_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
        KAGENTI_PROTOCOL_LABEL: VALUE_PROTOCOL_MCP,
        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
    }
    # Add framework if present
    if KAGENTI_FRAMEWORK_LABEL in labels:
        pod_labels[KAGENTI_FRAMEWORK_LABEL] = labels[KAGENTI_FRAMEWORK_LABEL]

    # Build pod spec
    new_pod_spec = {
        "securityContext": security_context,
        "containers": [container],
        "volumes": volumes,
    }

    if service_account_name:
        new_pod_spec["serviceAccountName"] = service_account_name

    if image_pull_secrets:
        new_pod_spec["imagePullSecrets"] = image_pull_secrets

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": selector_labels,
            },
            "template": {
                "metadata": {
                    "labels": pod_labels,
                },
                "spec": new_pod_spec,
            },
        },
    }


def _build_service_from_mcpserver(mcpserver: Dict, namespace: str) -> Dict:
    """
    Build a Kubernetes Service manifest from an MCPServer CRD.

    Uses the new naming convention: {name}-mcp

    Args:
        mcpserver: The MCPServer CRD resource dictionary.
        namespace: Kubernetes namespace.

    Returns:
        Service manifest dictionary.
    """
    metadata = mcpserver.get("metadata", {})
    spec = mcpserver.get("spec", {})
    name = metadata.get("name", "")

    # New service name
    service_name = _get_tool_service_name(name)

    # Get labels
    labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        KAGENTI_PROTOCOL_LABEL: VALUE_PROTOCOL_MCP,
        APP_KUBERNETES_IO_NAME: name,
        APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
    }

    # Build selector labels
    selector_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
    }

    # Get port from MCPServer spec
    port = spec.get("port", DEFAULT_IN_CLUSTER_PORT)
    target_port = spec.get("targetPort", DEFAULT_IN_CLUSTER_PORT)

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "type": "ClusterIP",
            "selector": selector_labels,
            "ports": [
                {
                    "name": "http",
                    "port": port,
                    "targetPort": target_port,
                    "protocol": "TCP",
                }
            ],
        },
    }


@router.get(
    "/migration/migratable",
    response_model=ListMigratableToolsResponse,
    summary="List tools that can be migrated from MCPServer CRD to Deployment",
    tags=["migration"],
)
async def list_migratable_tools(
    namespace: str = Query(default="default", description="Kubernetes namespace"),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ListMigratableToolsResponse:
    """
    List all MCPServer CRDs in a namespace that can be migrated to Deployments.

    Returns information about each tool including whether a Deployment
    already exists (indicating migration is complete).
    """
    try:
        # List MCPServer CRDs with kagenti.io/type=tool label
        mcpserver_crds = kube.list_custom_resources(
            group=TOOLHIVE_CRD_GROUP,
            version=TOOLHIVE_CRD_VERSION,
            namespace=namespace,
            plural=TOOLHIVE_MCP_PLURAL,
            label_selector=f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_TOOL}",
        )
    except ApiException as e:
        if e.status == 404:
            # CRD not installed
            return ListMigratableToolsResponse(tools=[], total=0, already_migrated=0)
        raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Get list of existing Deployments and StatefulSets to check for already-migrated tools
    existing_deployment_names = set()
    existing_statefulset_names = set()

    try:
        existing_deployments = kube.list_deployments(
            namespace=namespace,
            label_selector=f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_TOOL}",
        )
        existing_deployment_names = {
            d.get("metadata", {}).get("name") for d in existing_deployments
        }
    except ApiException:
        # If listing deployments fails, continue with empty set - not critical for operation
        pass

    try:
        existing_statefulsets = kube.list_statefulsets(
            namespace=namespace,
            label_selector=f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_TOOL}",
        )
        existing_statefulset_names = {
            s.get("metadata", {}).get("name") for s in existing_statefulsets
        }
    except ApiException:
        # If listing statefulsets fails, continue with empty set - not critical for operation
        pass

    tools = []
    already_migrated = 0

    for mcpserver in mcpserver_crds:
        metadata = mcpserver.get("metadata", {})
        name = metadata.get("name", "")
        labels = metadata.get("labels", {})
        has_deployment = name in existing_deployment_names
        has_statefulset = name in existing_statefulset_names

        if has_deployment or has_statefulset:
            already_migrated += 1

        # Get description from annotations
        description = metadata.get("annotations", {}).get(KAGENTI_DESCRIPTION_ANNOTATION, "")

        # Determine status
        status = _is_mcpserver_ready(mcpserver)

        tools.append(
            MigratableToolInfo(
                name=name,
                namespace=namespace,
                status=status,
                has_deployment=has_deployment,
                has_statefulset=has_statefulset,
                labels=labels,
                description=description,
                old_service_name=_get_toolhive_service_name(name),
                new_service_name=_get_tool_service_name(name),
            )
        )

    return ListMigratableToolsResponse(
        tools=tools,
        total=len(tools),
        already_migrated=already_migrated,
    )


@router.post(
    "/{namespace}/{name}/migrate",
    response_model=MigrateToolResponse,
    summary="Migrate an MCPServer CRD to a Deployment",
    tags=["migration"],
)
async def migrate_tool(
    namespace: str,
    name: str,
    request: MigrateToolRequest = MigrateToolRequest(),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> MigrateToolResponse:
    """
    Migrate an MCPServer CRD to a Deployment.

    This endpoint:
    1. Reads the existing MCPServer CRD specification
    2. Creates a Deployment with the same pod template
    3. Creates a Service with new naming convention ({name}-mcp)
    4. Optionally deletes the MCPServer CRD (if delete_old=True)

    Note: After migration, MCP connection URLs need to be updated:
    - Old: http://mcp-{name}-proxy.{namespace}.svc.cluster.local:8000/mcp
    - New: http://{name}-mcp.{namespace}.svc.cluster.local:8000/mcp
    """
    logger.info(f"Starting migration of MCPServer CRD '{name}' in namespace '{namespace}'")

    deployment_created = False
    service_created = False
    mcpserver_deleted = False
    old_service_name = _get_toolhive_service_name(name)
    new_service_name = _get_tool_service_name(name)

    # Only deployment is currently supported for migration
    if request.workload_type != WORKLOAD_TYPE_DEPLOYMENT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported workload type for migration: {request.workload_type}. "
            f"Only 'deployment' is currently supported.",
        )

    # Step 1: Get the MCPServer CRD
    try:
        mcpserver = kube.get_custom_resource(
            group=TOOLHIVE_CRD_GROUP,
            version=TOOLHIVE_CRD_VERSION,
            namespace=namespace,
            plural=TOOLHIVE_MCP_PLURAL,
            name=name,
        )
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"MCPServer CRD '{name}' not found in namespace '{namespace}'",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Step 2: Check if Deployment already exists
    try:
        kube.get_deployment(namespace=namespace, name=name)
        # Deployment already exists - skip migration
        return MigrateToolResponse(
            success=True,
            name=name,
            namespace=namespace,
            message=f"Tool '{name}' already has a Deployment. Migration skipped.",
            deployment_created=False,
            service_created=False,
            mcpserver_deleted=False,
            old_service_name=old_service_name,
            new_service_name=new_service_name,
        )
    except ApiException as e:
        if e.status != 404:
            raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Step 3: Check if StatefulSet already exists
    try:
        kube.get_statefulset(namespace=namespace, name=name)
        # StatefulSet already exists - skip migration
        return MigrateToolResponse(
            success=True,
            name=name,
            namespace=namespace,
            message=f"Tool '{name}' already has a StatefulSet. Migration skipped.",
            deployment_created=False,
            service_created=False,
            mcpserver_deleted=False,
            old_service_name=old_service_name,
            new_service_name=new_service_name,
        )
    except ApiException as e:
        if e.status != 404:
            raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Step 4: Build and create Deployment
    try:
        deployment_manifest = _build_deployment_from_mcpserver(mcpserver, namespace)
        kube.create_deployment(namespace, deployment_manifest)
        deployment_created = True
        logger.info(f"Created Deployment '{name}'")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ApiException as e:
        raise HTTPException(
            status_code=e.status,
            detail=f"Failed to create Deployment: {e.reason}",
        )

    # Step 5: Check if new Service already exists, create if not
    try:
        kube.get_service(namespace=namespace, name=new_service_name)
        logger.info(f"Service '{new_service_name}' already exists")
    except ApiException as e:
        if e.status == 404:
            # Create new Service
            try:
                service_manifest = _build_service_from_mcpserver(mcpserver, namespace)
                kube.create_service(namespace, service_manifest)
                service_created = True
                logger.info(f"Created Service '{new_service_name}'")
            except ApiException as e2:
                logger.error(f"Failed to create Service '{new_service_name}': {e2}")
                # Continue - Deployment was created, Service failure is not fatal
        else:
            raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Step 6: Delete MCPServer CRD (if requested)
    if request.delete_old:
        try:
            kube.delete_custom_resource(
                group=TOOLHIVE_CRD_GROUP,
                version=TOOLHIVE_CRD_VERSION,
                namespace=namespace,
                plural=TOOLHIVE_MCP_PLURAL,
                name=name,
            )
            mcpserver_deleted = True
            logger.info(f"Deleted MCPServer CRD '{name}'")
        except ApiException as e:
            logger.error(f"Failed to delete MCPServer CRD '{name}': {e}")
            # Continue - this is not fatal

    return MigrateToolResponse(
        success=True,
        name=name,
        namespace=namespace,
        message=f"Tool '{name}' migrated successfully. "
        f"Update MCP URLs: {old_service_name} -> {new_service_name}",
        deployment_created=deployment_created,
        service_created=service_created,
        mcpserver_deleted=mcpserver_deleted,
        old_service_name=old_service_name,
        new_service_name=new_service_name,
    )


@router.post(
    "/migration/migrate-all",
    response_model=BatchMigrateToolsResponse,
    summary="Migrate all MCPServer CRDs in a namespace to Deployments",
    tags=["migration"],
)
async def batch_migrate_tools(
    namespace: str = Query(default="default", description="Kubernetes namespace"),
    request: BatchMigrateToolsRequest = BatchMigrateToolsRequest(),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> BatchMigrateToolsResponse:
    """
    Migrate all MCPServer CRDs in a namespace to Deployments.

    By default, performs a dry-run. Set dry_run=false to actually migrate.
    """
    logger.info(
        f"Starting batch migration of MCPServer CRDs in namespace '{namespace}' "
        f"(dry_run={request.dry_run})"
    )

    # List all MCPServer CRDs with kagenti.io/type=tool label
    try:
        mcpserver_crds = kube.list_custom_resources(
            group=TOOLHIVE_CRD_GROUP,
            version=TOOLHIVE_CRD_VERSION,
            namespace=namespace,
            plural=TOOLHIVE_MCP_PLURAL,
            label_selector=f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_TOOL}",
        )
    except ApiException as e:
        if e.status == 404:
            return BatchMigrateToolsResponse(
                total=0,
                migrated=0,
                skipped=0,
                failed=0,
                results=[],
                dry_run=request.dry_run,
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))

    results = []
    migrated = 0
    skipped = 0
    failed = 0

    for mcpserver in mcpserver_crds:
        mcpserver_name = mcpserver.get("metadata", {}).get("name", "")
        old_service_name = _get_toolhive_service_name(mcpserver_name)
        new_service_name = _get_tool_service_name(mcpserver_name)

        if request.dry_run:
            # Dry run - check if would be migrated or skipped
            would_skip = False
            try:
                kube.get_deployment(namespace=namespace, name=mcpserver_name)
                would_skip = True
            except ApiException:
                logging.debug(
                    "Deployment %s not found in namespace %s during dry-run migration",
                    mcpserver_name,
                    namespace,
                )

            if not would_skip:
                try:
                    kube.get_statefulset(namespace=namespace, name=mcpserver_name)
                    would_skip = True
                except ApiException:
                    logging.debug(
                        "StatefulSet %s not found in namespace %s during dry-run migration",
                        mcpserver_name,
                        namespace,
                    )

            if would_skip:
                skipped += 1
                results.append(
                    MigrateToolResponse(
                        success=True,
                        name=mcpserver_name,
                        namespace=namespace,
                        message="Would be skipped (Deployment/StatefulSet already exists)",
                        deployment_created=False,
                        service_created=False,
                        mcpserver_deleted=False,
                        old_service_name=old_service_name,
                        new_service_name=new_service_name,
                    )
                )
            else:
                migrated += 1
                results.append(
                    MigrateToolResponse(
                        success=True,
                        name=mcpserver_name,
                        namespace=namespace,
                        message="Would be migrated",
                        deployment_created=True,
                        service_created=True,
                        mcpserver_deleted=request.delete_old,
                        old_service_name=old_service_name,
                        new_service_name=new_service_name,
                    )
                )
        else:
            # Actual migration
            try:
                result = await migrate_tool(
                    namespace=namespace,
                    name=mcpserver_name,
                    request=MigrateToolRequest(
                        workload_type=request.workload_type,
                        delete_old=request.delete_old,
                    ),
                    kube=kube,
                )
                results.append(result)

                if result.deployment_created:
                    migrated += 1
                else:
                    skipped += 1
            except HTTPException as e:
                failed += 1
                results.append(
                    MigrateToolResponse(
                        success=False,
                        name=mcpserver_name,
                        namespace=namespace,
                        message=f"Migration failed: {e.detail}",
                        deployment_created=False,
                        service_created=False,
                        mcpserver_deleted=False,
                        old_service_name=old_service_name,
                        new_service_name=new_service_name,
                    )
                )

    return BatchMigrateToolsResponse(
        total=len(results),
        migrated=migrated,
        skipped=skipped,
        failed=failed,
        results=results,
        dry_run=request.dry_run,
    )
