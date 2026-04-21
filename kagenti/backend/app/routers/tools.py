# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tool API endpoints.
"""

import logging
import re
from typing import Any, Dict, List, Literal, Optional
from contextlib import AsyncExitStack

from fastapi import APIRouter, Depends, HTTPException, Query
from kubernetes.client import ApiException
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, field_validator

from app.core.auth import ROLE_OPERATOR, ROLE_VIEWER, require_roles
from app.core.config import settings
from app.core.constants import (
    KAGENTI_TYPE_LABEL,
    PROTOCOL_LABEL_PREFIX,
    KAGENTI_FRAMEWORK_LABEL,
    KAGENTI_INJECT_LABEL,
    KAGENTI_TRANSPORT_LABEL,
    KAGENTI_WORKLOAD_TYPE_LABEL,
    KAGENTI_DESCRIPTION_ANNOTATION,
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
    # SPIRE identity constants
    KAGENTI_SPIRE_LABEL,
    KAGENTI_SPIRE_ENABLED_VALUE,
    # Per-sidecar injection labels
    KAGENTI_ENVOY_PROXY_INJECT_LABEL,
    KAGENTI_SPIFFE_HELPER_INJECT_LABEL,
    KAGENTI_CLIENT_REGISTRATION_INJECT_LABEL,
    KAGENTI_OUTBOUND_PORTS_EXCLUDE,
    KAGENTI_INBOUND_PORTS_EXCLUDE,
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
    ResourceConfigFromBuild,
    ShipwrightBuildListResponse,
)
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.services.shipwright_builds import collect_kagenti_shipwright_builds
from app.services.shipwright import (
    build_shipwright_build_manifest,
    build_shipwright_buildrun_manifest,
    extract_resource_config_from_build,
    get_latest_buildrun,
    extract_buildrun_info,
    is_build_succeeded,
    get_output_image_from_buildrun,
    resolve_clone_secret,
)
from app.utils.routes import create_route_for_agent_or_tool, route_exists
from app.routers.agents import (
    _ensure_authbridge_configmaps,
    _ensure_authproxy_routes,
    OutboundRoute,
)


class SecretKeyRef(BaseModel):
    """Reference to a key in a Secret."""

    name: str
    key: str


class ConfigMapKeyRef(BaseModel):
    """Reference to a key in a ConfigMap."""

    name: str
    key: str


class EnvVarSource(BaseModel):
    """Source for environment variable value."""

    secretKeyRef: Optional[SecretKeyRef] = None
    configMapKeyRef: Optional[ConfigMapKeyRef] = None


class EnvVar(BaseModel):
    """Environment variable with support for direct values and references."""

    name: str
    value: Optional[str] = None
    valueFrom: Optional[EnvVarSource] = None

    @field_validator("name")
    @classmethod
    def validate_env_var_name(cls, v: str) -> str:
        """Validate environment variable name according to Kubernetes rules.

        Valid env var names must:
        - Contain only letters (A-Z, a-z), digits (0-9), and underscores (_)
        - Not start with a digit
        """
        if not v:
            raise ValueError("Environment variable name cannot be empty")

        # Kubernetes env var name pattern: must start with letter or underscore,
        # followed by any combination of letters, digits, or underscores
        pattern = r"^[A-Za-z_][A-Za-z0-9_]*$"

        if not re.match(pattern, v):
            raise ValueError(
                f"Invalid environment variable name '{v}'. "
                "Name must start with a letter or underscore and contain only "
                "letters, digits, and underscores (e.g., MY_VAR, API_KEY, var123)."
            )

        return v

    @field_validator("valueFrom")
    @classmethod
    def check_value_or_value_from(cls, v, info):
        """Ensure either value or valueFrom is provided, but not both."""
        values = info.data
        has_value = values.get("value") is not None
        has_value_from = v is not None

        if not has_value and not has_value_from:
            raise ValueError("Either value or valueFrom must be provided")
        if has_value and has_value_from:
            raise ValueError("Cannot specify both value and valueFrom")

        return v


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

    # AuthBridge sidecar injection (default disabled for tools)
    authBridgeEnabled: bool = False
    # SPIRE identity (spiffe-helper sidecar injection)
    spireEnabled: bool = False

    # Per-sidecar injection controls (None = use webhook defaults)
    envoyProxyInject: Optional[bool] = None
    spiffeHelperInject: Optional[bool] = None
    clientRegistrationInject: Optional[bool] = None

    # Port exclusion annotations
    outboundPortsExclude: Optional[str] = None
    inboundPortsExclude: Optional[str] = None

    # AuthBridge config overrides
    defaultOutboundPolicy: Optional[Literal["passthrough", "exchange"]] = None

    # Outbound routing rules (authproxy-routes ConfigMap)
    outboundRoutes: Optional[List["OutboundRoute"]] = None


class FinalizeToolBuildRequest(BaseModel):
    """Request to finalize a tool Shipwright build by creating the Deployment/StatefulSet."""

    protocol: Optional[str] = None
    framework: Optional[str] = None
    workloadType: Optional[str] = None  # "deployment" or "statefulset"
    persistentStorage: Optional[PersistentStorageConfig] = None
    envVars: Optional[List[EnvVar]] = None
    servicePorts: Optional[List[ServicePort]] = None
    createHttpRoute: Optional[bool] = None
    authBridgeEnabled: Optional[bool] = None
    imagePullSecret: Optional[str] = None
    envoyProxyInject: Optional[bool] = None
    spiffeHelperInject: Optional[bool] = None
    clientRegistrationInject: Optional[bool] = None
    outboundRoutes: Optional[List[OutboundRoute]] = None
    outboundPortsExclude: Optional[str] = None
    inboundPortsExclude: Optional[str] = None
    defaultOutboundPolicy: Optional[Literal["passthrough", "exchange"]] = None


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


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tools", tags=["tools"])


def _build_tool_env_vars(
    env_var_list: Optional[List[EnvVar]] = None,
) -> List[dict]:
    """
    Build environment variables list with support for valueFrom references.

    Always includes DEFAULT_ENV_VARS so that tools receive required
    platform variables (PORT, HOST, OTEL_EXPORTER_OTLP_ENDPOINT, etc.).

    Args:
        env_var_list: Optional list of EnvVar models from the request.

    Returns:
        List of environment variable dictionaries.
    """
    env_vars = list(DEFAULT_ENV_VARS)
    if env_var_list:
        for ev in env_var_list:
            if ev.value is not None:
                # Direct value
                env_vars.append({"name": ev.name, "value": ev.value})
            elif ev.valueFrom is not None:
                # Reference to Secret or ConfigMap
                env_entry: Dict[str, Any] = {"name": ev.name, "valueFrom": {}}

                if ev.valueFrom.secretKeyRef:
                    env_entry["valueFrom"]["secretKeyRef"] = {
                        "name": ev.valueFrom.secretKeyRef.name,
                        "key": ev.valueFrom.secretKeyRef.key,
                    }
                elif ev.valueFrom.configMapKeyRef:
                    env_entry["valueFrom"]["configMapKeyRef"] = {
                        "name": ev.valueFrom.configMapKeyRef.name,
                        "key": ev.valueFrom.configMapKeyRef.key,
                    }

                env_vars.append(env_entry)
    return env_vars


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
    # Extract protocols from protocol.kagenti.io/<name> prefix labels.
    protocols = [
        k[len(PROTOCOL_LABEL_PREFIX) :]
        for k in labels
        if k.startswith(PROTOCOL_LABEL_PREFIX) and len(k) > len(PROTOCOL_LABEL_PREFIX)
    ]
    # Fall back to deprecated kagenti.io/protocol single-value label.
    if not protocols:
        legacy = labels.get("kagenti.io/protocol")
        if legacy:
            protocols = [legacy]

    return ResourceLabels(
        protocol=protocols or None,
        framework=labels.get("kagenti.io/framework"),
        type=labels.get("kagenti.io/type"),
    )


def _build_tool_shipwright_build_manifest(
    request: CreateToolRequest, clone_secret_name: Optional[str] = None
) -> dict:
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
        gitSecretName=clone_secret_name,
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
        "authBridgeEnabled": request.authBridgeEnabled,
        "spireEnabled": request.spireEnabled,
        "envoyProxyInject": request.envoyProxyInject,
        "spiffeHelperInject": request.spiffeHelperInject,
        "clientRegistrationInject": request.clientRegistrationInject,
    }
    if request.outboundRoutes:
        resource_config["outboundRoutes"] = [r.model_dump() for r in request.outboundRoutes]
    if request.outboundPortsExclude:
        resource_config["outboundPortsExclude"] = request.outboundPortsExclude
    if request.inboundPortsExclude:
        resource_config["inboundPortsExclude"] = request.inboundPortsExclude
    if request.defaultOutboundPolicy:
        resource_config["defaultOutboundPolicy"] = request.defaultOutboundPolicy
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


@router.get(
    "/shipwright-builds",
    response_model=ShipwrightBuildListResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_tool_shipwright_builds(
    namespace: str = Query(
        default="",
        description="Kubernetes namespace (required unless allNamespaces=true)",
    ),
    all_namespaces: bool = Query(
        default=False,
        alias="allNamespaces",
        description="If true, list builds in all kagenti-enabled namespaces",
    ),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ShipwrightBuildListResponse:
    """List Shipwright Build resources for tools only (kagenti.io/type=tool)."""
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
            kube, namespaces_to_scan, RESOURCE_TYPE_TOOL, logger
        )
    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=str(e.reason))

    return ShipwrightBuildListResponse(items=items)


@router.get("", response_model=ToolListResponse, dependencies=[Depends(require_roles(ROLE_VIEWER))])
async def list_tools(
    namespace: str = Query(default="default", description="Kubernetes namespace"),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ToolListResponse:
    """
    List all MCP tools in the specified namespace.

    Returns tools that have the kagenti.io/type=tool label.
    Queries both Deployments and StatefulSets.

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

        return ToolListResponse(items=tools)

    except ApiException as e:
        if e.status == 403:
            raise HTTPException(
                status_code=403,
                detail="Permission denied. Check RBAC configuration.",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@router.get("/{namespace}/{name}", dependencies=[Depends(require_roles(ROLE_VIEWER))])
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


@router.get("/{namespace}/{name}/route-status", dependencies=[Depends(require_roles(ROLE_VIEWER))])
async def get_tool_route_status(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> dict:
    """Check if an HTTPRoute or Route exists for the tool."""
    exists = route_exists(kube, name, namespace)
    return {"hasRoute": exists}


@router.delete(
    "/{namespace}/{name}",
    response_model=DeleteResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
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


def _build_container_ports(
    service_ports: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build container port entries from service port configuration.

    Args:
        service_ports: Service port configuration list

    Returns:
        List of container port dicts for use in pod spec
    """
    if not service_ports:
        return [
            {
                "containerPort": DEFAULT_IN_CLUSTER_PORT,
                "name": "http",
                "protocol": "TCP",
            }
        ]

    ports = []
    for sp in service_ports:
        ports.append(
            {
                "containerPort": sp.get("targetPort", DEFAULT_IN_CLUSTER_PORT),
                "name": sp.get("name", "http"),
                "protocol": sp.get("protocol", "TCP"),
            }
        )
    return ports


def _build_service_ports(
    service_ports: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build service port entries from service port configuration.

    Args:
        service_ports: Service port configuration list

    Returns:
        List of service port dicts for use in Service spec
    """
    if not service_ports:
        return [
            {
                "name": "http",
                "port": DEFAULT_IN_CLUSTER_PORT,
                "targetPort": DEFAULT_IN_CLUSTER_PORT,
                "protocol": "TCP",
            }
        ]

    ports = []
    for sp in service_ports:
        ports.append(
            {
                "name": sp.get("name", "http"),
                "port": sp.get("port", DEFAULT_IN_CLUSTER_PORT),
                "targetPort": sp.get("targetPort", DEFAULT_IN_CLUSTER_PORT),
                "protocol": sp.get("protocol", "TCP"),
            }
        )
    return ports


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
    auth_bridge_enabled: bool = False,
    spire_enabled: bool = False,
    envoy_proxy_inject: Optional[bool] = None,
    spiffe_helper_inject: Optional[bool] = None,
    client_registration_inject: Optional[bool] = None,
    outbound_ports_exclude: Optional[str] = None,
    inbound_ports_exclude: Optional[str] = None,
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
    # Callers are expected to provide DEFAULT_ENV_VARS via _build_tool_env_vars()
    all_env_vars = env_vars if env_vars else list(DEFAULT_ENV_VARS)

    # Build container ports from service_ports
    container_ports = _build_container_ports(service_ports)

    # Build labels - required labels per migration plan
    labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
        f"{PROTOCOL_LABEL_PREFIX}{VALUE_PROTOCOL_MCP}": "",
        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
        KAGENTI_FRAMEWORK_LABEL: framework,
        KAGENTI_WORKLOAD_TYPE_LABEL: WORKLOAD_TYPE_DEPLOYMENT,
        APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
        KAGENTI_INJECT_LABEL: "enabled" if auth_bridge_enabled else "disabled",
    }

    # Pod template labels (subset used on pod template metadata)
    pod_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
        f"{PROTOCOL_LABEL_PREFIX}{VALUE_PROTOCOL_MCP}": "",
        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
        KAGENTI_FRAMEWORK_LABEL: framework,
        KAGENTI_INJECT_LABEL: "enabled" if auth_bridge_enabled else "disabled",
    }

    # SPIRE identity label (triggers spiffe-helper sidecar injection by kagenti-webhook)
    if spire_enabled:
        labels[KAGENTI_SPIRE_LABEL] = KAGENTI_SPIRE_ENABLED_VALUE
        pod_labels[KAGENTI_SPIRE_LABEL] = KAGENTI_SPIRE_ENABLED_VALUE
    if envoy_proxy_inject is False:
        labels[KAGENTI_ENVOY_PROXY_INJECT_LABEL] = "false"
        pod_labels[KAGENTI_ENVOY_PROXY_INJECT_LABEL] = "false"
    if spiffe_helper_inject is False:
        labels[KAGENTI_SPIFFE_HELPER_INJECT_LABEL] = "false"
        pod_labels[KAGENTI_SPIFFE_HELPER_INJECT_LABEL] = "false"
    if client_registration_inject is True:
        labels[KAGENTI_CLIENT_REGISTRATION_INJECT_LABEL] = "true"
        pod_labels[KAGENTI_CLIENT_REGISTRATION_INJECT_LABEL] = "true"

    # Build annotations
    annotations = {}
    pod_annotations: Dict[str, str] = {}
    if description:
        annotations[KAGENTI_DESCRIPTION_ANNOTATION] = description
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name
    if outbound_ports_exclude:
        pod_annotations[KAGENTI_OUTBOUND_PORTS_EXCLUDE] = outbound_ports_exclude
    if inbound_ports_exclude:
        pod_annotations[KAGENTI_INBOUND_PORTS_EXCLUDE] = inbound_ports_exclude

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
                    "labels": pod_labels,
                    "annotations": pod_annotations,
                },
                "spec": {
                    "serviceAccountName": name,
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
                            "ports": container_ports,
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
    auth_bridge_enabled: bool = False,
    spire_enabled: bool = False,
    envoy_proxy_inject: Optional[bool] = None,
    spiffe_helper_inject: Optional[bool] = None,
    client_registration_inject: Optional[bool] = None,
    outbound_ports_exclude: Optional[str] = None,
    inbound_ports_exclude: Optional[str] = None,
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
    # Callers are expected to provide DEFAULT_ENV_VARS via _build_tool_env_vars()
    all_env_vars = env_vars if env_vars else list(DEFAULT_ENV_VARS)

    # Build container ports from service_ports
    container_ports = _build_container_ports(service_ports)

    # Service name for StatefulSet (must match the headless service)
    service_name = f"{name}{TOOL_SERVICE_SUFFIX}"

    # Build labels - required labels per migration plan
    labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
        f"{PROTOCOL_LABEL_PREFIX}{VALUE_PROTOCOL_MCP}": "",
        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
        KAGENTI_FRAMEWORK_LABEL: framework,
        KAGENTI_WORKLOAD_TYPE_LABEL: WORKLOAD_TYPE_STATEFULSET,
        APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
        KAGENTI_INJECT_LABEL: "enabled" if auth_bridge_enabled else "disabled",
    }

    # Pod template labels (subset used on pod template metadata)
    pod_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
        f"{PROTOCOL_LABEL_PREFIX}{VALUE_PROTOCOL_MCP}": "",
        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
        KAGENTI_FRAMEWORK_LABEL: framework,
        KAGENTI_INJECT_LABEL: "enabled" if auth_bridge_enabled else "disabled",
    }

    # SPIRE identity label (triggers spiffe-helper sidecar injection by kagenti-webhook)
    if spire_enabled:
        labels[KAGENTI_SPIRE_LABEL] = KAGENTI_SPIRE_ENABLED_VALUE
        pod_labels[KAGENTI_SPIRE_LABEL] = KAGENTI_SPIRE_ENABLED_VALUE
    if envoy_proxy_inject is False:
        labels[KAGENTI_ENVOY_PROXY_INJECT_LABEL] = "false"
        pod_labels[KAGENTI_ENVOY_PROXY_INJECT_LABEL] = "false"
    if spiffe_helper_inject is False:
        labels[KAGENTI_SPIFFE_HELPER_INJECT_LABEL] = "false"
        pod_labels[KAGENTI_SPIFFE_HELPER_INJECT_LABEL] = "false"
    if client_registration_inject is True:
        labels[KAGENTI_CLIENT_REGISTRATION_INJECT_LABEL] = "true"
        pod_labels[KAGENTI_CLIENT_REGISTRATION_INJECT_LABEL] = "true"

    # Build annotations
    annotations = {}
    pod_annotations: Dict[str, str] = {}
    if description:
        annotations[KAGENTI_DESCRIPTION_ANNOTATION] = description
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name
    if outbound_ports_exclude:
        pod_annotations[KAGENTI_OUTBOUND_PORTS_EXCLUDE] = outbound_ports_exclude
    if inbound_ports_exclude:
        pod_annotations[KAGENTI_INBOUND_PORTS_EXCLUDE] = inbound_ports_exclude

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
                    "labels": pod_labels,
                    "annotations": pod_annotations,
                },
                "spec": {
                    "serviceAccountName": name,
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
                            "ports": container_ports,
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
    # Build service port list
    ports = _build_service_ports(service_ports)

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
                f"{PROTOCOL_LABEL_PREFIX}{VALUE_PROTOCOL_MCP}": "",
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
            "ports": ports,
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


@router.post(
    "", response_model=CreateToolResponse, dependencies=[Depends(require_roles(ROLE_OPERATOR))]
)
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
            clone_secret = resolve_clone_secret(kube.core_api, request.namespace)
            build_manifest = _build_tool_shipwright_build_manifest(
                request, clone_secret_name=clone_secret
            )
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

            # Prepare env vars (always called so tools get DEFAULT_ENV_VARS)
            env_vars = _build_tool_env_vars(request.envVars)

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

            # Ensure a dedicated ServiceAccount exists so the webhook's
            # SPIFFE identity uses the workload name, not the ReplicaSet hash.
            kube.ensure_service_account(namespace=request.namespace, name=request.name)

            if request.authBridgeEnabled:
                _ensure_authbridge_configmaps(
                    kube=kube,
                    namespace=request.namespace,
                    spire_enabled=request.spireEnabled,
                )
                if request.outboundRoutes:
                    _ensure_authproxy_routes(
                        kube=kube,
                        namespace=request.namespace,
                        routes=request.outboundRoutes,
                    )
                if request.defaultOutboundPolicy:
                    extra = {
                        "DEFAULT_OUTBOUND_POLICY": request.defaultOutboundPolicy,
                    }
                    kube.upsert_configmap(
                        namespace=request.namespace,
                        name="authbridge-config",
                        data=extra,
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
                    auth_bridge_enabled=request.authBridgeEnabled,
                    spire_enabled=request.spireEnabled,
                    envoy_proxy_inject=request.envoyProxyInject,
                    spiffe_helper_inject=request.spiffeHelperInject,
                    client_registration_inject=request.clientRegistrationInject,
                    outbound_ports_exclude=request.outboundPortsExclude,
                    inbound_ports_exclude=request.inboundPortsExclude,
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
                    auth_bridge_enabled=request.authBridgeEnabled,
                    spire_enabled=request.spireEnabled,
                    envoy_proxy_inject=request.envoyProxyInject,
                    spiffe_helper_inject=request.spiffeHelperInject,
                    client_registration_inject=request.clientRegistrationInject,
                    outbound_ports_exclude=request.outboundPortsExclude,
                    inbound_ports_exclude=request.inboundPortsExclude,
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
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
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


@router.post(
    "/{namespace}/{name}/shipwright-buildrun", dependencies=[Depends(require_roles(ROLE_OPERATOR))]
)
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


@router.post(
    "/{namespace}/{name}/finalize-shipwright-build",
    response_model=CreateToolResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
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
        auth_bridge_enabled = (
            request.authBridgeEnabled
            if request.authBridgeEnabled is not None
            else tool_config_dict.get("authBridgeEnabled", False)
        )

        # Determine workload type
        workload_type = request.workloadType or tool_config_dict.get(
            "workloadType", WORKLOAD_TYPE_DEPLOYMENT
        )

        # Build env vars (always include DEFAULT_ENV_VARS)
        if request.envVars:
            env_vars = _build_tool_env_vars(request.envVars)
        elif tool_config_dict.get("envVars"):
            env_vars = _build_tool_env_vars([EnvVar(**ev) for ev in tool_config_dict["envVars"]])
        else:
            env_vars = _build_tool_env_vars()

        # Build service ports
        service_ports = None
        if request.servicePorts:
            service_ports = [sp.model_dump() for sp in request.servicePorts]
        elif tool_config_dict.get("servicePorts"):
            service_ports = tool_config_dict["servicePorts"]

        # Determine image pull secret
        image_pull_secret = request.imagePullSecret or tool_config_dict.get("registrySecret")

        # Propagate SPIRE identity setting from stored config
        spire_enabled = tool_config_dict.get("spireEnabled", False)

        # Outbound routing rules
        final_outbound_routes = None
        stored_routes = tool_config_dict.get("outboundRoutes")
        if request.outboundRoutes is not None:
            final_outbound_routes = request.outboundRoutes
        elif stored_routes:
            final_outbound_routes = [OutboundRoute(**r) for r in stored_routes]

        # Per-sidecar injection controls
        envoy_proxy_inject = (
            request.envoyProxyInject
            if request.envoyProxyInject is not None
            else tool_config_dict.get("envoyProxyInject")
        )
        spiffe_helper_inject = (
            request.spiffeHelperInject
            if request.spiffeHelperInject is not None
            else tool_config_dict.get("spiffeHelperInject")
        )
        client_registration_inject = (
            request.clientRegistrationInject
            if request.clientRegistrationInject is not None
            else tool_config_dict.get("clientRegistrationInject")
        )

        # Port exclusion and policy overrides
        outbound_ports_exclude = (
            request.outboundPortsExclude
            if request.outboundPortsExclude is not None
            else tool_config_dict.get("outboundPortsExclude")
        )
        inbound_ports_exclude = (
            request.inboundPortsExclude
            if request.inboundPortsExclude is not None
            else tool_config_dict.get("inboundPortsExclude")
        )
        final_default_outbound_policy = (
            request.defaultOutboundPolicy
            if request.defaultOutboundPolicy is not None
            else tool_config_dict.get("defaultOutboundPolicy")
        )

        # Ensure a dedicated ServiceAccount exists so the webhook's
        # SPIFFE identity uses the workload name, not the ReplicaSet hash.
        kube.ensure_service_account(namespace=namespace, name=name)

        if auth_bridge_enabled:
            _ensure_authbridge_configmaps(
                kube=kube,
                namespace=namespace,
                spire_enabled=spire_enabled,
            )
            if final_outbound_routes:
                _ensure_authproxy_routes(
                    kube=kube,
                    namespace=namespace,
                    routes=final_outbound_routes,
                )
            if final_default_outbound_policy:
                extra = {
                    "DEFAULT_OUTBOUND_POLICY": final_default_outbound_policy,
                }
                kube.upsert_configmap(
                    namespace=namespace,
                    name="authbridge-config",
                    data=extra,
                )

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
                auth_bridge_enabled=auth_bridge_enabled,
                spire_enabled=spire_enabled,
                envoy_proxy_inject=envoy_proxy_inject,
                spiffe_helper_inject=spiffe_helper_inject,
                client_registration_inject=client_registration_inject,
                outbound_ports_exclude=outbound_ports_exclude,
                inbound_ports_exclude=inbound_ports_exclude,
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
                auth_bridge_enabled=auth_bridge_enabled,
                spire_enabled=spire_enabled,
                envoy_proxy_inject=envoy_proxy_inject,
                spiffe_helper_inject=spiffe_helper_inject,
                client_registration_inject=client_registration_inject,
                outbound_ports_exclude=outbound_ports_exclude,
                inbound_ports_exclude=inbound_ports_exclude,
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


def _get_tool_url(name: str, namespace: str, port: int = DEFAULT_IN_CLUSTER_PORT) -> str:
    """Get the URL for an MCP tool server.

    Service naming convention:
    - Service name: {name}-mcp
    - Port: configurable, defaults to 8000

    Returns different URL formats based on deployment context:
    - In-cluster: http://{name}-mcp.{namespace}.svc.cluster.local:{port}
    - Off-cluster (local dev): http://{name}.{domain}:8080 (via HTTPRoute)
    """
    if settings.is_running_in_cluster:
        # In-cluster: use service DNS with new naming convention
        service_name = _get_tool_service_name(name)
        return f"http://{service_name}.{namespace}.svc.cluster.local:{port}"
    else:
        # Off-cluster: use external domain (e.g., localtest.me) via HTTPRoute
        domain = settings.domain_name
        return f"http://{name}.{domain}:8080"


def _get_tool_service_port(kube: KubernetesService, name: str, namespace: str) -> int:
    """Look up the actual service port for a tool from K8s.

    Falls back to DEFAULT_IN_CLUSTER_PORT if the service cannot be found.
    """
    try:
        service = kube.get_service(namespace, _get_tool_service_name(name))
        ports = service.get("spec", {}).get("ports", [])
        if ports:
            return ports[0].get("port", DEFAULT_IN_CLUSTER_PORT)
    except ApiException:
        pass
    return DEFAULT_IN_CLUSTER_PORT


@router.post(
    "/{namespace}/{name}/connect",
    response_model=MCPToolsResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def connect_to_tool(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> MCPToolsResponse:
    """
    Connect to an MCP server and list available tools.

    This endpoint connects to the MCP server and retrieves the list of
    available tools using the MCP client library.
    """
    service_port = _get_tool_service_port(kube, name, namespace)
    tool_url = _get_tool_url(name, namespace, port=service_port)
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


@router.post(
    "/{namespace}/{name}/invoke",
    response_model=MCPInvokeResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def invoke_tool(
    namespace: str,
    name: str,
    request: MCPInvokeRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> MCPInvokeResponse:
    """
    Invoke an MCP tool with the given arguments.

    This endpoint calls a specific tool on the MCP server with
    the provided arguments and returns the result.
    """
    service_port = _get_tool_service_port(kube, name, namespace)
    tool_url = _get_tool_url(name, namespace, port=service_port)
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
