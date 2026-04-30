# pylint: disable=too-many-lines
# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Agent API endpoints.
"""

import json
import logging
import re
import socket
import ipaddress
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
import kubernetes.client
from kubernetes.client import ApiException
from pydantic import BaseModel, Field, field_validator

from app.core.auth import ROLE_OPERATOR, ROLE_VIEWER, require_roles
from app.utils.routes import get_agent_url
from app.core.constants import (
    CRD_GROUP,
    CRD_VERSION,
    AGENTS_PLURAL,
    AGENTRUNTIMES_PLURAL,
    KAGENTI_TYPE_LABEL,
    PROTOCOL_LABEL_PREFIX,
    KAGENTI_FRAMEWORK_LABEL,
    KAGENTI_INJECT_LABEL,
    KAGENTI_WORKLOAD_TYPE_LABEL,
    KAGENTI_DESCRIPTION_ANNOTATION,
    APP_KUBERNETES_IO_CREATED_BY,
    APP_KUBERNETES_IO_NAME,
    APP_KUBERNETES_IO_MANAGED_BY,
    APP_KUBERNETES_IO_COMPONENT,
    KAGENTI_UI_CREATOR_LABEL,
    KAGENTI_OPERATOR_LABEL_NAME,
    RESOURCE_TYPE_AGENT,
    DEFAULT_IN_CLUSTER_PORT,
    DEFAULT_OFF_CLUSTER_PORT,
    DEFAULT_IMAGE_POLICY,
    DEFAULT_RESOURCE_LIMITS,
    DEFAULT_RESOURCE_REQUESTS,
    DEFAULT_ENV_VARS,
    AGENT_ENDPOINT,
    # Shipwright constants
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
    SHIPWRIGHT_BUILDS_PLURAL,
    SHIPWRIGHT_BUILDRUNS_PLURAL,
    SHIPWRIGHT_CLUSTER_BUILD_STRATEGIES_PLURAL,
    DEFAULT_INTERNAL_REGISTRY,
    # Workload type constants
    WORKLOAD_TYPE_DEPLOYMENT,
    WORKLOAD_TYPE_STATEFULSET,
    WORKLOAD_TYPE_JOB,
    WORKLOAD_TYPE_SANDBOX,
    AGENT_SANDBOX_CRD_GROUP,
    AGENT_SANDBOX_CRD_VERSION,
    AGENT_SANDBOX_EXT_GROUP,
    AGENT_SANDBOX_EXT_VERSION,
    SUPPORTED_WORKLOAD_TYPES,
    # Migration constants (Phase 4)
    MIGRATION_SOURCE_ANNOTATION,
    MIGRATION_TIMESTAMP_ANNOTATION,
    # SPIRE identity constants
    KAGENTI_SPIRE_LABEL,
    KAGENTI_SPIRE_ENABLED_VALUE,
    # Per-sidecar injection labels
    KAGENTI_ENVOY_PROXY_INJECT_LABEL,
    KAGENTI_SPIFFE_HELPER_INJECT_LABEL,
    KAGENTI_CLIENT_REGISTRATION_INJECT_LABEL,
    # Port exclusion annotations
    KAGENTI_OUTBOUND_PORTS_EXCLUDE,
    KAGENTI_INBOUND_PORTS_EXCLUDE,
    # AuthBridge ConfigMap defaults
    DEFAULT_KEYCLOAK_INTERNAL_URL,
    DEFAULT_KEYCLOAK_REALM,
    DEFAULT_SPIFFE_HELPER_CONF,
    DEFAULT_ENVOY_YAML,
)
from app.core.config import settings
from app.models.responses import (
    AgentSummary,
    AgentListResponse,
    ResourceLabels,
    DeleteResponse,
)
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.utils.routes import (
    create_route_for_agent_or_tool,
    detect_platform,
    route_exists,
    sanitize_log,
    select_route_port,
)
from app.models.shipwright import (
    ResourceType,
    ShipwrightBuildConfig,
    BuildSourceConfig,
    BuildOutputConfig,
    BuildStatusCondition,
    ClusterBuildStrategyInfo,
    ClusterBuildStrategiesResponse,
    ShipwrightBuildListResponse,
    ShipwrightBuildStatusResponse,
    ShipwrightBuildRunStatusResponse,
    ResourceConfigFromBuild,
)
from app.services.shipwright import (
    build_shipwright_build_manifest,
    build_shipwright_buildrun_manifest,
    extract_resource_config_from_build,
    get_latest_buildrun,
    extract_buildrun_info,
    resolve_clone_secret,
)
from app.services.shipwright_builds import collect_kagenti_shipwright_builds


class OutboundRoute(BaseModel):
    """A single outbound token exchange route for authproxy-routes ConfigMap."""

    host: str = Field(..., min_length=1)
    target_audience: str = Field(..., min_length=1)
    token_scopes: str = "openid"


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
    port: int = 8080
    targetPort: int = 8000
    protocol: str = "TCP"


class CreateAgentRequest(BaseModel):
    """Request to create a new agent."""

    name: str
    namespace: str
    protocol: str = "a2a"
    framework: str = "LangGraph"
    envVars: Optional[List[EnvVar]] = None

    # Workload type: 'deployment', 'statefulset', or 'job'
    workloadType: str = WORKLOAD_TYPE_DEPLOYMENT

    # Deployment method: 'source' (build from git) or 'image' (use existing image)
    deploymentMethod: str = "source"

    # Build from source fields
    gitUrl: str = ""
    gitPath: str = ""
    gitBranch: str = "main"
    imageTag: str = "v0.0.1"
    registryUrl: Optional[str] = None
    registrySecret: Optional[str] = None
    startCommand: Optional[str] = None

    # Deploy from existing image fields
    containerImage: Optional[str] = None
    imagePullSecret: Optional[str] = None

    # Pod configuration
    servicePorts: Optional[List[ServicePort]] = None

    # HTTPRoute/Route creation
    createHttpRoute: bool = False

    # AuthBridge sidecar injection (default enabled for agents)
    authBridgeEnabled: bool = True
    # SPIRE identity (spiffe-helper sidecar injection)
    spireEnabled: bool = False

    # Per-sidecar injection controls (None = use webhook defaults)
    envoyProxyInject: Optional[bool] = None
    spiffeHelperInject: Optional[bool] = None
    clientRegistrationInject: Optional[bool] = None

    # Port exclusion annotations
    outboundPortsExclude: Optional[str] = None
    inboundPortsExclude: Optional[str] = None

    # AuthBridge config overrides (authbridge-config ConfigMap)
    defaultOutboundPolicy: Optional[Literal["passthrough", "exchange"]] = None

    # Outbound routing rules (authproxy-routes ConfigMap)
    outboundRoutes: Optional[List["OutboundRoute"]] = None

    # Shipwright build configuration
    shipwrightConfig: Optional[ShipwrightBuildConfig] = None

    @field_validator("workloadType")
    @classmethod
    def validate_workload_type(cls, v: str) -> str:
        """Validate that workload type is supported."""
        if v not in SUPPORTED_WORKLOAD_TYPES:
            raise ValueError(
                f"Unsupported workload type: {v}. "
                f"Supported types: {', '.join(SUPPORTED_WORKLOAD_TYPES)}"
            )
        return v


class CreateAgentResponse(BaseModel):
    """Response after creating an agent."""

    success: bool
    name: str
    namespace: str
    message: str


class AgentShipwrightBuildInfoResponse(BaseModel):  # pylint: disable=too-many-instance-attributes
    """Full Shipwright Build information for agents.

    This is an agent-specific wrapper that includes agentConfig for backwards compatibility.
    """

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

    # Agent configuration from annotations (agent-specific)
    agentConfig: Optional[ResourceConfigFromBuild] = None


# Migration Models (Phase 4: Agent CRD to Deployment migration)


class MigrateAgentRequest(BaseModel):
    """Request to migrate an Agent CRD to a Deployment."""

    delete_old: bool = False  # Whether to delete the Agent CRD after successful migration


class MigrateAgentResponse(BaseModel):
    """Response after migrating an agent."""

    success: bool
    migrated: bool
    name: str
    namespace: str
    message: str
    deployment_created: bool = False
    service_created: bool = False
    agent_crd_deleted: bool = False


class MigratableAgentInfo(BaseModel):
    """Information about an agent that can be migrated."""

    name: str
    namespace: str
    status: str
    has_deployment: bool  # True if a Deployment already exists with same name
    labels: Dict[str, str]
    description: Optional[str] = None


class ListMigratableAgentsResponse(BaseModel):
    """Response containing list of agents that can be migrated."""

    agents: List[MigratableAgentInfo]
    total: int
    already_migrated: int  # Count of agents that already have Deployments


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


def _is_deployment_ready(resource_data: dict) -> str:
    """Check if a Kubernetes Deployment is ready based on status.

    For Deployments, checks:
    1. conditions array for type="Available" with status="True"
    2. replicas vs readyReplicas count

    Also maintains backward compatibility with Agent CRD status format.
    """
    status = resource_data.get("status", {})
    conditions = status.get("conditions") or []

    # Check for Kubernetes Deployment conditions (type=Available)
    for condition in conditions:
        cond_type = condition.get("type")
        cond_status = condition.get("status")

        # Kubernetes Deployment uses "Available" condition
        if cond_type == "Available" and cond_status == "True":
            return "Ready"

        # Agent CRD uses "Ready" condition (backward compatibility)
        if cond_type == "Ready" and cond_status == "True":
            return "Ready"

    # Check replica counts for Deployments
    replicas = status.get("replicas") or 0
    ready_replicas = status.get("ready_replicas") or status.get("readyReplicas", 0)
    if 0 < replicas <= ready_replicas:
        return "Ready"

    # Fallback: check deploymentStatus.phase for older Agent CRD versions
    deployment_status = status.get("deploymentStatus", {})
    phase = deployment_status.get("phase", "")
    if phase in ("Ready", "Running"):
        return "Ready"

    return "Not Ready"


def _get_deployment_description(deployment: dict) -> str:
    """Extract description from Deployment annotations."""
    annotations = deployment.get("metadata", {}).get("annotations", {})
    return annotations.get(
        KAGENTI_DESCRIPTION_ANNOTATION,
        annotations.get("description", "No description"),
    )


def _is_statefulset_ready(resource_data: dict) -> str:
    """Check if a Kubernetes StatefulSet is ready based on status."""
    status = resource_data.get("status", {})

    # Check replica counts for StatefulSets
    replicas = status.get("replicas") or 0
    ready_replicas = status.get("ready_replicas") or status.get("readyReplicas", 0)

    if replicas == 0:
        return "Not Ready"
    if ready_replicas >= replicas:
        return "Ready"
    if ready_replicas > 0:
        return "Progressing"
    return "Not Ready"


def _get_statefulset_description(statefulset: dict) -> str:
    """Extract description from StatefulSet annotations."""
    annotations = statefulset.get("metadata", {}).get("annotations", {})
    return annotations.get(
        KAGENTI_DESCRIPTION_ANNOTATION,
        annotations.get("description", "No description"),
    )


def _get_job_status(job: dict) -> str:
    """Get the status of a Kubernetes Job.

    Returns status values consistent with Deployments and StatefulSets:
    - "Ready": Job completed successfully (equivalent to Job condition "Complete")
    - "Failed": Job failed (equivalent to Job condition "Failed")
    - "Progressing": Job is actively running (has active pods)
    - "Not Ready": Job is pending/not yet started

    This mapping ensures UI consistency across all workload types.
    """
    status = job.get("status", {})
    conditions = status.get("conditions") or []

    # Check conditions for completed or failed
    for condition in conditions:
        cond_type = condition.get("type")
        cond_status = condition.get("status")

        if cond_type == "Complete" and cond_status == "True":
            return "Ready"  # Job completed successfully
        if cond_type == "Failed" and cond_status == "True":
            return "Failed"

    # Check active/succeeded/failed counts
    active = status.get("active") or 0
    succeeded = status.get("succeeded") or 0
    failed = status.get("failed") or 0

    if succeeded > 0:
        return "Ready"  # Job completed successfully
    if failed > 0:
        return "Failed"
    if active > 0:
        return "Progressing"  # Job is actively running
    return "Not Ready"  # Job pending/not started


def _get_job_description(job: dict) -> str:
    """Extract description from Job annotations."""
    annotations = job.get("metadata", {}).get("annotations", {})
    return annotations.get(
        KAGENTI_DESCRIPTION_ANNOTATION,
        annotations.get("description", "No description"),
    )


def _is_sandbox_ready(sandbox: dict) -> str:
    """Check if a Sandbox or SandboxClaim is ready by examining its status conditions."""
    status = sandbox.get("status", {})
    conditions = status.get("conditions", [])
    for cond in conditions:
        if cond.get("type") == "Ready":
            if cond.get("status") == "True":
                return "Ready"
            return "Not Ready"
    return "Pending"


def _get_sandbox_description(sandbox: dict) -> str:
    """Extract description from a Sandbox or SandboxClaim resource."""
    metadata = sandbox.get("metadata", {})
    annotations = metadata.get("annotations", {})
    return annotations.get(KAGENTI_DESCRIPTION_ANNOTATION, "No description")


def _format_timestamp(timestamp) -> Optional[str]:
    """Convert a timestamp to ISO format string.

    The Kubernetes Python client returns datetime objects for timestamp fields,
    but our Pydantic models expect strings.
    """
    if timestamp is None:
        return None
    if isinstance(timestamp, str):
        return timestamp
    # Handle datetime objects from K8s Python client
    if hasattr(timestamp, "isoformat"):
        return timestamp.isoformat()
    return str(timestamp)


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


@router.get(
    "", response_model=AgentListResponse, dependencies=[Depends(require_roles(ROLE_VIEWER))]
)
async def list_agents(
    namespace: str = Query(default="default", description="Kubernetes namespace"),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> AgentListResponse:
    """
    List all agents in the specified namespace.

    Returns agents deployed as Deployments, StatefulSets, Jobs, or Sandboxes with the
    kagenti.io/type=agent label.
    During migration period, also includes legacy Agent CRDs that haven't been
    migrated yet (controlled by enable_legacy_agent_crd setting).
    """
    try:
        label_selector = f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_AGENT}"

        agents = []
        agent_names = set()

        # Query Deployments with agent label
        deployments = kube.list_deployments(
            namespace=namespace,
            label_selector=label_selector,
        )

        for deployment in deployments:
            metadata = deployment.get("metadata", {})
            name = metadata.get("name", "")
            agent_names.add(name)
            labels = metadata.get("labels", {})

            agents.append(
                AgentSummary(
                    name=name,
                    namespace=metadata.get("namespace", namespace),
                    description=_get_deployment_description(deployment),
                    status=_is_deployment_ready(deployment),
                    labels=_extract_labels(labels),
                    workloadType=WORKLOAD_TYPE_DEPLOYMENT,
                    createdAt=_format_timestamp(
                        metadata.get("creation_timestamp") or metadata.get("creationTimestamp")
                    ),
                )
            )

        # Query StatefulSets with agent label
        statefulsets = kube.list_statefulsets(
            namespace=namespace,
            label_selector=label_selector,
        )

        for statefulset in statefulsets:
            metadata = statefulset.get("metadata", {})
            name = metadata.get("name", "")
            if name in agent_names:
                logger.warning(
                    f"Duplicate agent name '{name}' detected: StatefulSet skipped because "
                    f"a Deployment with the same name already exists in namespace '{namespace}'. "
                    "This may indicate a configuration issue."
                )
                continue
            agent_names.add(name)
            labels = metadata.get("labels", {})

            agents.append(
                AgentSummary(
                    name=name,
                    namespace=metadata.get("namespace", namespace),
                    description=_get_statefulset_description(statefulset),
                    status=_is_statefulset_ready(statefulset),
                    labels=_extract_labels(labels),
                    workloadType=WORKLOAD_TYPE_STATEFULSET,
                    createdAt=_format_timestamp(
                        metadata.get("creation_timestamp") or metadata.get("creationTimestamp")
                    ),
                )
            )

        # Query Jobs with agent label
        jobs = kube.list_jobs(
            namespace=namespace,
            label_selector=label_selector,
        )

        for job in jobs:
            metadata = job.get("metadata", {})
            name = metadata.get("name", "")
            if name in agent_names:
                logger.warning(
                    f"Duplicate agent name '{name}' detected: Job skipped because "
                    f"a Deployment or StatefulSet with the same name already exists in namespace '{namespace}'. "
                    "This may indicate a configuration issue."
                )
                continue
            agent_names.add(name)
            labels = metadata.get("labels", {})

            agents.append(
                AgentSummary(
                    name=name,
                    namespace=metadata.get("namespace", namespace),
                    description=_get_job_description(job),
                    status=_get_job_status(job),
                    labels=_extract_labels(labels),
                    workloadType=WORKLOAD_TYPE_JOB,
                    createdAt=_format_timestamp(
                        metadata.get("creation_timestamp") or metadata.get("creationTimestamp")
                    ),
                )
            )

        # Query SandboxClaims with agent label (feature-flagged)
        if settings.kagenti_feature_flag_agent_sandbox:
            try:
                claims = kube.list_sandbox_claims(
                    namespace=namespace,
                    label_selector=label_selector,
                )
                for claim in claims:
                    metadata = claim.get("metadata", {})
                    name = metadata.get("name", "")
                    if name in agent_names:
                        logger.warning(
                            f"Duplicate agent name '{name}' detected: SandboxClaim skipped "
                            f"because a workload with the same name already exists in "
                            f"namespace '{namespace}'. This may indicate a configuration issue."
                        )
                        continue
                    agent_names.add(name)
                    labels = metadata.get("labels", {})

                    agents.append(
                        AgentSummary(
                            name=name,
                            namespace=metadata.get("namespace", namespace),
                            description=_get_sandbox_description(claim),
                            status=_is_sandbox_ready(claim),
                            labels=_extract_labels(labels),
                            workloadType=WORKLOAD_TYPE_SANDBOX,
                            createdAt=_format_timestamp(
                                metadata.get("creation_timestamp")
                                or metadata.get("creationTimestamp")
                            ),
                        )
                    )
            except ApiException as e:
                if e.status == 404:
                    logger.debug("SandboxClaim CRD not installed")
                elif e.status == 403:
                    logger.debug("SandboxClaim RBAC: insufficient permissions")
                else:
                    logger.warning(f"Failed to list SandboxClaims: {e.reason}")

        # Backward compatibility: Also list legacy Agent CRDs (during migration period)
        if settings.enable_legacy_agent_crd:
            try:
                agent_crds = kube.list_custom_resources(
                    group=CRD_GROUP,
                    version=CRD_VERSION,
                    namespace=namespace,
                    plural=AGENTS_PLURAL,
                )
                for agent_crd in agent_crds:
                    metadata = agent_crd.get("metadata", {})
                    name = metadata.get("name", "")
                    # Skip if already listed via workload (already migrated)
                    if name in agent_names:
                        continue

                    labels = metadata.get("labels", {})
                    spec = agent_crd.get("spec", {})
                    status = agent_crd.get("status", {})

                    # Determine status from Agent CRD
                    agent_status = "Not Ready"
                    for cond in status.get("conditions") or []:
                        if cond.get("type") == "Ready" and cond.get("status") == "True":
                            agent_status = "Ready"
                            break

                    # Get description
                    description = spec.get("description") or metadata.get("annotations", {}).get(
                        KAGENTI_DESCRIPTION_ANNOTATION, "No description"
                    )

                    agents.append(
                        AgentSummary(
                            name=name,
                            namespace=metadata.get("namespace", namespace),
                            description=description,
                            status=agent_status,
                            labels=_extract_labels(labels),
                            workloadType=WORKLOAD_TYPE_DEPLOYMENT,
                            createdAt=_format_timestamp(
                                metadata.get("creation_timestamp")
                                or metadata.get("creationTimestamp")
                            ),
                        )
                    )
            except ApiException as e:
                # CRD not installed or not accessible - that's fine, just skip
                if e.status not in (404, 403):
                    logger.warning(f"Failed to list legacy Agent CRDs: {e.reason}")

        return AgentListResponse(items=agents)

    except ApiException as e:
        if e.status == 403:
            raise HTTPException(
                status_code=403,
                detail="Permission denied. Check RBAC configuration.",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@router.get("/{namespace}/{name}", dependencies=[Depends(require_roles(ROLE_VIEWER))])
async def get_agent(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> Any:
    """Get detailed information about a specific agent.

    Returns workload details (Deployment, StatefulSet, or Job) along with
    associated Service information.
    """
    workload = None
    workload_type = None

    # Try to get Deployment first
    try:
        workload = kube.get_deployment(namespace=namespace, name=name)
        workload_type = WORKLOAD_TYPE_DEPLOYMENT
    except ApiException as e:
        if e.status != 404:
            raise HTTPException(status_code=e.status, detail=str(e.reason))

    # If not found, try StatefulSet
    if workload is None:
        try:
            workload = kube.get_statefulset(namespace=namespace, name=name)
            workload_type = WORKLOAD_TYPE_STATEFULSET
        except ApiException as e:
            if e.status != 404:
                raise HTTPException(status_code=e.status, detail=str(e.reason))

    # If still not found, try Job
    if workload is None:
        try:
            workload = kube.get_job(namespace=namespace, name=name)
            workload_type = WORKLOAD_TYPE_JOB
        except ApiException as e:
            if e.status != 404:
                raise HTTPException(status_code=e.status, detail=str(e.reason))

    # If still not found, try SandboxClaim (feature-flagged)
    if workload is None and settings.kagenti_feature_flag_agent_sandbox:
        try:
            workload = kube.get_sandbox_claim(namespace=namespace, name=name)
            workload_type = WORKLOAD_TYPE_SANDBOX
        except ApiException as e:
            if e.status != 404:
                raise HTTPException(status_code=e.status, detail=str(e.reason))

    if workload is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{name}' not found in namespace '{namespace}'",
        )

    # Try to get the associated Service (not applicable for Jobs)
    service = None
    if workload_type not in (WORKLOAD_TYPE_JOB, WORKLOAD_TYPE_SANDBOX):
        try:
            service = kube.get_service(namespace=namespace, name=name)
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Failed to get Service for agent '{name}': {e.reason}")

    # Build response with workload info and optional Service info
    metadata = workload.get("metadata", {})
    labels = metadata.get("labels", {})
    annotations = metadata.get("annotations", {})

    # Compute ready status based on workload type
    if workload_type == WORKLOAD_TYPE_DEPLOYMENT:
        ready_status = _is_deployment_ready(workload)
    elif workload_type == WORKLOAD_TYPE_STATEFULSET:
        ready_status = _is_statefulset_ready(workload)
    elif workload_type == WORKLOAD_TYPE_JOB:
        ready_status = _get_job_status(workload)
    elif workload_type == WORKLOAD_TYPE_SANDBOX:
        ready_status = _is_sandbox_ready(workload)
    else:
        ready_status = "Unknown"

    response = {
        "metadata": {
            "name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
            "labels": labels,
            "annotations": annotations,
            "creationTimestamp": _format_timestamp(
                metadata.get("creation_timestamp") or metadata.get("creationTimestamp")
            ),
            "uid": metadata.get("uid"),
        },
        "spec": workload.get("spec", {}),
        "status": workload.get("status", {}),
        "workloadType": labels.get(KAGENTI_WORKLOAD_TYPE_LABEL, workload_type),
        "readyStatus": ready_status,  # Computed ready status for frontend
    }

    # Add service info if available
    if service:
        service_spec = service.get("spec", {})
        response["service"] = {
            "name": service.get("metadata", {}).get("name"),
            "type": service_spec.get("type"),
            "clusterIP": service_spec.get("cluster_ip") or service_spec.get("clusterIP"),
            "ports": service_spec.get("ports", []),
        }

    return response


@router.get("/{namespace}/{name}/route-status", dependencies=[Depends(require_roles(ROLE_VIEWER))])
async def get_agent_route_status(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> dict:
    """Check if an HTTPRoute or Route exists for the agent."""
    exists = route_exists(kube, name, namespace)
    return {"hasRoute": exists}


@router.delete(
    "/{namespace}/{name}",
    response_model=DeleteResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def delete_agent(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> DeleteResponse:
    """Delete an agent and its associated resources from the cluster.

    This deletes:
    - Deployment, StatefulSet, Job, or Sandbox (whichever exists)
    - Service
    - HTTPRoute or OpenShift Route (whichever exists)
    - Shipwright Build CR (if exists)
    - Shipwright BuildRun CRs (if exist)
    - Legacy: Agent CR (if exists, for backward compatibility)
    """
    messages = []
    safe_name = sanitize_log(name)

    # Delete the Deployment (if exists)
    try:
        kube.delete_deployment(namespace=namespace, name=name)
        messages.append(f"Deployment '{name}' deleted")
    except ApiException as e:
        if e.status == 404:
            logger.debug("Deployment '%s' not found (may be other workload type)", safe_name)
        else:
            logger.warning("Failed to delete Deployment '%s': %s", safe_name, e.reason)

    # Delete the StatefulSet (if exists)
    try:
        kube.delete_statefulset(namespace=namespace, name=name)
        messages.append(f"StatefulSet '{name}' deleted")
    except ApiException as e:
        if e.status == 404:
            logger.debug("StatefulSet '%s' not found", safe_name)
        else:
            logger.warning("Failed to delete StatefulSet '%s': %s", safe_name, e.reason)

    # Delete the Job (if exists)
    try:
        kube.delete_job(namespace=namespace, name=name)
        messages.append(f"Job '{name}' deleted")
    except ApiException as e:
        if e.status == 404:
            logger.debug("Job '%s' not found", safe_name)
        else:
            logger.warning("Failed to delete Job '%s': %s", safe_name, e.reason)

    # Delete the SandboxClaim + SandboxTemplate (if exists)
    if settings.kagenti_feature_flag_agent_sandbox:
        try:
            kube.delete_sandbox_claim(namespace=namespace, name=name)
            messages.append(f"SandboxClaim '{name}' deleted")
        except ApiException as e:
            if e.status == 404:
                logger.debug("SandboxClaim '%s' not found (may be other workload type)", safe_name)
            else:
                logger.warning("Failed to delete SandboxClaim '%s': %s", safe_name, e.reason)
        try:
            kube.delete_sandbox_template(namespace=namespace, name=name)
            messages.append(f"SandboxTemplate '{name}' deleted")
        except ApiException as e:
            if e.status == 404:
                logger.debug("SandboxTemplate '%s' not found", safe_name)
            else:
                logger.warning("Failed to delete SandboxTemplate '%s': %s", safe_name, e.reason)

    # Delete the Service
    try:
        kube.delete_service(namespace=namespace, name=name)
        messages.append(f"Service '{name}' deleted")
    except ApiException as e:
        if e.status == 404:
            # Service doesn't exist, that's fine
            pass
        else:
            logger.warning("Failed to delete Service '%s': %s", safe_name, e.reason)

    # Delete the HTTPRoute (if exists)
    try:
        kube.delete_custom_resource(
            group="gateway.networking.k8s.io",
            version="v1",
            namespace=namespace,
            plural="httproutes",
            name=name,
        )
        messages.append(f"HTTPRoute '{name}' deleted")
    except ApiException as e:
        if e.status == 404:
            # HTTPRoute doesn't exist, that's fine
            pass
        else:
            logger.warning("Failed to delete HTTPRoute '%s': %s", safe_name, e.reason)

    # Delete the OpenShift Route (if exists)
    try:
        kube.delete_custom_resource(
            group="route.openshift.io",
            version="v1",
            namespace=namespace,
            plural="routes",
            name=name,
        )
        messages.append(f"Route '{name}' deleted")
    except ApiException as e:
        if e.status == 404:
            # Route doesn't exist, that's fine
            pass
        else:
            logger.warning("Failed to delete Route '%s': %s", safe_name, e.reason)

    # Delete the AgentRuntime CR (if exists)
    try:
        kube.delete_custom_resource(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=AGENTRUNTIMES_PLURAL,
            name=name,
        )
        messages.append(f"AgentRuntime '{name}' deleted")
    except ApiException as e:
        if e.status == 404:
            pass
        else:
            logger.warning("Failed to delete AgentRuntime '%s': %s", safe_name, e.reason)

    # Legacy cleanup: Delete the Agent CR if it exists
    try:
        kube.delete_custom_resource(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=AGENTS_PLURAL,
            name=name,
        )
        messages.append(f"Agent CR '{name}' deleted (legacy)")
    except ApiException as e:
        if e.status == 404:
            # Agent CR doesn't exist, that's expected for new deployments
            pass
        else:
            logger.warning("Failed to delete Agent CR '%s': %s", safe_name, e.reason)

    # Delete Shipwright BuildRuns associated with the build
    try:
        buildruns = kube.list_custom_resources(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector=f"kagenti.io/build-name={name}",
        )
        for buildrun in buildruns:
            buildrun_name = buildrun.get("metadata", {}).get("name")
            if buildrun_name:
                try:
                    kube.delete_custom_resource(
                        group=SHIPWRIGHT_CRD_GROUP,
                        version=SHIPWRIGHT_CRD_VERSION,
                        namespace=namespace,
                        plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                        name=buildrun_name,
                    )
                    messages.append(f"BuildRun '{buildrun_name}' deleted")
                except ApiException as e:
                    if e.status != 404:
                        logger.warning(
                            "Failed to delete BuildRun '%s': %s",
                            sanitize_log(buildrun_name),
                            e.reason,
                        )
    except ApiException as e:
        if e.status != 404:
            logger.warning("Failed to list BuildRuns for '%s': %s", safe_name, e.reason)

    # Delete the Shipwright Build CR if it exists
    try:
        kube.delete_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name=name,
        )
        messages.append(f"Shipwright Build '{name}' deleted")
    except ApiException as e:
        if e.status == 404:
            # Shipwright Build doesn't exist, that's fine (might be image-based or Tekton deployment)
            pass
        else:
            logger.warning("Failed to delete Shipwright Build '%s': %s", safe_name, e.reason)

    return DeleteResponse(success=True, message="; ".join(messages))


# =============================================================================
# Migration Endpoints (Phase 4: Agent CRD to Deployment migration)
# =============================================================================


@router.get(
    "/migration/migratable",
    response_model=ListMigratableAgentsResponse,
    summary="List agents that can be migrated from Agent CRD to Deployment",
    tags=["migration"],
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_migratable_agents(
    namespace: str = Query(default="default", description="Kubernetes namespace"),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ListMigratableAgentsResponse:
    """
    List all Agent CRDs in a namespace that can be migrated to Deployments.

    Returns information about each agent including whether a Deployment
    already exists (indicating migration is complete).
    """
    try:
        # List legacy Agent CRDs
        agent_crds = kube.list_custom_resources(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=AGENTS_PLURAL,
        )
    except ApiException as e:
        if e.status == 404:
            # CRD not installed
            return ListMigratableAgentsResponse(agents=[], total=0, already_migrated=0)
        raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Get list of existing Deployments to check for already-migrated agents
    try:
        existing_deployments = kube.list_deployments(
            namespace=namespace,
            label_selector=f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_AGENT}",
        )
        existing_names = {d.get("metadata", {}).get("name") for d in existing_deployments}
    except ApiException:
        existing_names = set()

    agents = []
    already_migrated = 0

    for agent in agent_crds:
        metadata = agent.get("metadata", {})
        name = metadata.get("name", "")
        labels = metadata.get("labels", {})
        has_deployment = name in existing_names

        if has_deployment:
            already_migrated += 1

        # Get description from spec or annotations
        spec = agent.get("spec", {})
        description = spec.get("description") or metadata.get("annotations", {}).get(
            KAGENTI_DESCRIPTION_ANNOTATION, ""
        )

        # Determine status
        status = agent.get("status", {})
        agent_status = "Unknown"
        for cond in status.get("conditions") or []:
            if cond.get("type") == "Ready":
                agent_status = "Ready" if cond.get("status") == "True" else "Not Ready"
                break

        agents.append(
            MigratableAgentInfo(
                name=name,
                namespace=namespace,
                status=agent_status,
                has_deployment=has_deployment,
                labels=labels,
                description=description,
            )
        )

    return ListMigratableAgentsResponse(
        agents=agents,
        total=len(agents),
        already_migrated=already_migrated,
    )


@router.post(
    "/{namespace}/{name}/migrate",
    response_model=MigrateAgentResponse,
    summary="Migrate an Agent CRD to a Deployment",
    tags=["migration"],
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def migrate_agent(
    namespace: str,
    name: str,
    request: MigrateAgentRequest = MigrateAgentRequest(),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> MigrateAgentResponse:
    """
    Migrate an Agent CRD to a Deployment.

    This endpoint:
    1. Reads the existing Agent CRD specification
    2. Creates a Deployment with the same pod template
    3. Creates a Service for the Deployment
    4. Optionally deletes the Agent CRD (if delete_old=True)

    If a Deployment already exists with the same name, the migration will fail
    unless the existing Deployment was created by kagenti-operator (in which
    case we just need to clean up the Agent CRD).
    """
    logger.info(f"Starting migration of Agent CRD '{name}' in namespace '{namespace}'")

    deployment_created = False
    service_created = False
    agent_crd_deleted = False

    # Step 1: Get the Agent CRD
    try:
        agent = kube.get_custom_resource(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=AGENTS_PLURAL,
            name=name,
        )
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Agent CRD '{name}' not found in namespace '{namespace}'",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Step 2: Check if Deployment already exists
    deployment_exists = False
    deployment_managed_by_operator = False
    try:
        existing_deployment = kube.get_deployment(namespace=namespace, name=name)
        deployment_exists = True
        # Check if it was created by kagenti-operator
        dep_labels = existing_deployment.get("metadata", {}).get("labels", {})
        deployment_managed_by_operator = (
            dep_labels.get(APP_KUBERNETES_IO_CREATED_BY) == KAGENTI_OPERATOR_LABEL_NAME
            or dep_labels.get(APP_KUBERNETES_IO_MANAGED_BY) == KAGENTI_OPERATOR_LABEL_NAME
        )
        logger.info(
            f"Deployment '{name}' already exists, managed_by_operator={deployment_managed_by_operator}"
        )
    except ApiException as e:
        if e.status != 404:
            raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Step 3: Check if Service already exists
    service_exists = False
    try:
        kube.get_service(namespace=namespace, name=name)
        service_exists = True
        logger.info(f"Service '{name}' already exists")
    except ApiException as e:
        if e.status != 404:
            raise HTTPException(status_code=e.status, detail=str(e.reason))

    # Step 4: Build and create Deployment (if needed)
    if deployment_exists:
        if deployment_managed_by_operator:
            # Deployment was created by operator, we just need to update labels
            # to mark it as migrated (managed by kagenti-ui now)
            try:
                patch = {
                    "metadata": {
                        "labels": {
                            APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
                        },
                        "annotations": {
                            MIGRATION_SOURCE_ANNOTATION: "agent-crd",
                            MIGRATION_TIMESTAMP_ANNOTATION: datetime.now(timezone.utc).isoformat(),
                        },
                    }
                }
                kube.patch_deployment(namespace=namespace, name=name, body=patch)
                logger.info(f"Patched Deployment '{name}' with migration annotations")
            except ApiException as e:
                logger.warning(f"Failed to patch Deployment '{name}': {e.reason}")
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Deployment '{name}' already exists and was not created by kagenti-operator. "
                "Cannot migrate. Delete the existing Deployment first or use a different name.",
            )
    else:
        # Create new Deployment from Agent CRD spec
        deployment_manifest = _build_deployment_from_agent_crd(agent)
        kube.ensure_service_account(namespace=namespace, name=name)
        try:
            kube.create_deployment(namespace=namespace, body=deployment_manifest)
            deployment_created = True
            logger.info(f"Created Deployment '{name}' from Agent CRD")
        except ApiException as e:
            raise HTTPException(
                status_code=e.status,
                detail=f"Failed to create Deployment: {e.reason}",
            )

    # Step 5: Build and create Service (if needed)
    if not service_exists:
        service_manifest = _build_service_from_agent_crd(agent)
        try:
            kube.create_service(namespace=namespace, body=service_manifest)
            service_created = True
            logger.info(f"Created Service '{name}' from Agent CRD")
        except ApiException as e:
            # If Deployment was created, try to clean up
            if deployment_created:
                try:
                    kube.delete_deployment(namespace=namespace, name=name)
                except Exception as cleanup_error:
                    logger.warning(
                        "Failed to clean up Deployment '%s' after Service creation error: %s",
                        name,
                        cleanup_error,
                    )
            raise HTTPException(
                status_code=e.status,
                detail=f"Failed to create Service: {e.reason}",
            )

    # Step 6: Delete the Agent CRD (if requested)
    if request.delete_old:
        try:
            kube.delete_custom_resource(
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=namespace,
                plural=AGENTS_PLURAL,
                name=name,
            )
            agent_crd_deleted = True
            logger.info(f"Deleted Agent CRD '{name}'")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Failed to delete Agent CRD '{name}': {e.reason}")

    # Build response message
    messages = []
    if deployment_created:
        messages.append("Deployment created")
    elif deployment_exists and deployment_managed_by_operator:
        messages.append("Deployment updated (was created by operator)")
    if service_created:
        messages.append("Service created")
    elif service_exists:
        messages.append("Service already exists")
    if agent_crd_deleted:
        messages.append("Agent CRD deleted")
    elif request.delete_old:
        messages.append("Agent CRD deletion requested but skipped")

    return MigrateAgentResponse(
        success=True,
        migrated=True,
        name=name,
        namespace=namespace,
        message="; ".join(messages) if messages else "Migration completed",
        deployment_created=deployment_created,
        service_created=service_created,
        agent_crd_deleted=agent_crd_deleted,
    )


@router.post(
    "/migration/migrate-all",
    response_model=Dict[str, Any],
    summary="Migrate all Agent CRDs in a namespace to Deployments",
    tags=["migration"],
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def migrate_all_agents(
    namespace: str = Query(default="default", description="Kubernetes namespace"),
    delete_old: bool = Query(default=False, description="Delete Agent CRDs after migration"),
    dry_run: bool = Query(default=True, description="If True, only show what would be migrated"),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> Dict[str, Any]:
    """
    Migrate all Agent CRDs in a namespace to Deployments.

    Use dry_run=True (default) to see what would be migrated before actually performing
    the migration. Set dry_run=False to execute the migration.
    """
    # First, get the list of migratable agents
    migratable = await list_migratable_agents(namespace=namespace, kube=kube)

    results = {
        "namespace": namespace,
        "dry_run": dry_run,
        "delete_old": delete_old,
        "total_agents": migratable.total,
        "already_migrated": migratable.already_migrated,
        "to_migrate": migratable.total - migratable.already_migrated,
        "migrated": [],
        "skipped": [],
        "failed": [],
    }

    for agent_info in migratable.agents:
        if agent_info.has_deployment:
            results["skipped"].append(
                {
                    "name": agent_info.name,
                    "reason": "Deployment already exists",
                }
            )
            continue

        if dry_run:
            results["migrated"].append(
                {
                    "name": agent_info.name,
                    "status": "would be migrated (dry-run)",
                }
            )
        else:
            try:
                result = await migrate_agent(
                    namespace=namespace,
                    name=agent_info.name,
                    request=MigrateAgentRequest(delete_old=delete_old),
                    kube=kube,
                )
                results["migrated"].append(
                    {
                        "name": agent_info.name,
                        "status": "migrated",
                        "message": result.message,
                    }
                )
            except HTTPException as e:
                results["failed"].append(
                    {
                        "name": agent_info.name,
                        "error": e.detail,
                    }
                )
            except Exception as e:
                results["failed"].append(
                    {
                        "name": agent_info.name,
                        "error": str(e),
                    }
                )

    return results


def _build_deployment_from_agent_crd(agent: dict) -> dict:
    """
    Build a Kubernetes Deployment manifest from an Agent CRD.

    Args:
        agent: The Agent CRD resource dictionary.

    Returns:
        Deployment manifest dictionary.
    """
    metadata = agent.get("metadata", {})
    spec = agent.get("spec", {})
    name = metadata.get("name", "")
    namespace = metadata.get("namespace", "default")

    # Get labels from Agent CRD and update for Deployment
    labels = metadata.get("labels", {}).copy()
    labels[KAGENTI_WORKLOAD_TYPE_LABEL] = WORKLOAD_TYPE_DEPLOYMENT
    labels[APP_KUBERNETES_IO_MANAGED_BY] = KAGENTI_UI_CREATOR_LABEL

    # Get annotations
    annotations = metadata.get("annotations", {}).copy()
    annotations[MIGRATION_SOURCE_ANNOTATION] = "agent-crd"
    annotations[MIGRATION_TIMESTAMP_ANNOTATION] = datetime.now(timezone.utc).isoformat()

    # Description
    description = spec.get("description", "")
    if description:
        annotations[KAGENTI_DESCRIPTION_ANNOTATION] = description

    # Extract pod template from Agent CRD
    pod_template_spec = spec.get("podTemplateSpec", {})
    pod_spec = pod_template_spec.get("spec", {})

    # If no pod template, try to build one from imageSource
    if not pod_spec:
        image_source = spec.get("imageSource", {})
        image = image_source.get("image", "")
        if not image:
            raise HTTPException(
                status_code=400,
                detail=f"Agent CRD '{name}' has no podTemplateSpec or imageSource.image",
            )

        pod_spec = {
            "serviceAccountName": name,
            "containers": [
                {
                    "name": "agent",
                    "image": image,
                    "imagePullPolicy": DEFAULT_IMAGE_POLICY,
                    "resources": {
                        "limits": DEFAULT_RESOURCE_LIMITS,
                        "requests": DEFAULT_RESOURCE_REQUESTS,
                    },
                    "ports": [
                        {
                            "name": "http",
                            "containerPort": DEFAULT_IN_CLUSTER_PORT,
                            "protocol": "TCP",
                        }
                    ],
                    "volumeMounts": [
                        {"name": "cache", "mountPath": "/app/.cache"},
                        {"name": "shared-data", "mountPath": "/shared"},
                    ],
                }
            ],
            "volumes": [
                {"name": "cache", "emptyDir": {}},
                {"name": "shared-data", "emptyDir": {}},
            ],
        }

    # Ensure serviceAccountName is set so the webhook's SPIFFE identity
    # derivation uses the workload name rather than the ReplicaSet hash.
    pod_spec.setdefault("serviceAccountName", name)

    # Build selector labels
    selector_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_AGENT,
        APP_KUBERNETES_IO_NAME: name,
    }

    # Build pod template labels (merge selector labels with other labels)
    pod_labels = labels.copy()

    # Get replicas
    replicas = spec.get("replicas", 1)

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
            "replicas": replicas,
            "selector": {
                "matchLabels": selector_labels,
            },
            "template": {
                "metadata": {
                    "labels": pod_labels,
                },
                "spec": pod_spec,
            },
        },
    }


def _build_service_from_agent_crd(agent: dict) -> dict:
    """
    Build a Kubernetes Service manifest from an Agent CRD.

    Args:
        agent: The Agent CRD resource dictionary.

    Returns:
        Service manifest dictionary.
    """
    metadata = agent.get("metadata", {})
    spec = agent.get("spec", {})
    name = metadata.get("name", "")
    namespace = metadata.get("namespace", "default")

    # Get labels
    labels = metadata.get("labels", {}).copy()
    labels[APP_KUBERNETES_IO_MANAGED_BY] = KAGENTI_UI_CREATOR_LABEL

    # Build selector labels
    selector_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_AGENT,
        APP_KUBERNETES_IO_NAME: name,
    }

    # Get service ports from Agent CRD
    service_ports_spec = spec.get("servicePorts", [])
    if service_ports_spec:
        service_ports = [
            {
                "name": sp.get("name", "http"),
                "port": sp.get("port", DEFAULT_OFF_CLUSTER_PORT),
                "targetPort": sp.get("targetPort", DEFAULT_IN_CLUSTER_PORT),
                "protocol": sp.get("protocol", "TCP"),
            }
            for sp in service_ports_spec
        ]
    else:
        service_ports = [
            {
                "name": "http",
                "port": DEFAULT_OFF_CLUSTER_PORT,
                "targetPort": DEFAULT_IN_CLUSTER_PORT,
                "protocol": "TCP",
            }
        ]

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "type": "ClusterIP",
            "selector": selector_labels,
            "ports": service_ports,
        },
    }


@router.get(
    "/build-strategies",
    response_model=ClusterBuildStrategiesResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_build_strategies(
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ClusterBuildStrategiesResponse:
    """List available ClusterBuildStrategies for Shipwright builds.

    Returns the list of ClusterBuildStrategy resources available in the cluster.
    """
    try:
        response = kube.list_cluster_custom_resources(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            plural=SHIPWRIGHT_CLUSTER_BUILD_STRATEGIES_PLURAL,
        )

        strategy_list = []
        for strategy in response.get("items", []):
            metadata = strategy.get("metadata", {})
            spec = strategy.get("spec", {})
            # Get description from annotations or spec
            annotations = metadata.get("annotations", {})
            description = annotations.get("description") or spec.get("description")

            strategy_list.append(
                ClusterBuildStrategyInfo(
                    name=metadata.get("name", ""),
                    description=description,
                )
            )

        return ClusterBuildStrategiesResponse(strategies=strategy_list)

    except ApiException as e:
        logger.error(f"Failed to list ClusterBuildStrategies: {e}")
        raise HTTPException(
            status_code=e.status,
            detail=f"Failed to list build strategies: {e.reason}",
        )


class AgentShipwrightBuildSummary(BaseModel):
    """One Shipwright Build CR for an agent (git/source pipeline)."""

    name: str
    namespace: str
    registered: bool = False
    strategy: str = ""
    gitUrl: str = ""
    gitRevision: str = ""
    contextDir: str = ""
    outputImage: str = ""
    creationTimestamp: Optional[str] = None


class AgentShipwrightBuildListResponse(BaseModel):
    items: List[AgentShipwrightBuildSummary]


@router.get(
    "/shipwright-builds",
    response_model=AgentShipwrightBuildListResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_agent_shipwright_builds(
    namespace: str = Query(
        default="",
        description="Kubernetes namespace (required unless all_namespaces=true)",
    ),
    all_namespaces: bool = Query(
        default=False,
        alias="allNamespaces",
        description="If true, list builds in all kagenti-enabled namespaces",
    ),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> AgentShipwrightBuildListResponse:
    """List Shipwright Build resources created for agents (kagenti.io/type=agent)."""
    label_selector = f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_AGENT}"
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

    items: List[AgentShipwrightBuildSummary] = []
    for ns in namespaces_to_scan:
        try:
            builds = kube.list_custom_resources(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace=ns,
                plural=SHIPWRIGHT_BUILDS_PLURAL,
                label_selector=label_selector,
            )
        except ApiException as e:
            if e.status == 403:
                logger.warning("Skip namespace %s listing shipwright builds: %s", ns, e.reason)
                continue
            if e.status == 404:
                continue
            raise HTTPException(status_code=e.status, detail=str(e.reason))

        for b in builds:
            md = b.get("metadata", {})
            spec = b.get("spec", {})
            status = b.get("status", {})
            source = spec.get("source", {}) or {}
            git = source.get("git", {}) or {}
            strat = spec.get("strategy", {}) or {}
            out = spec.get("output", {}) or {}
            items.append(
                AgentShipwrightBuildSummary(
                    name=md.get("name", ""),
                    namespace=md.get("namespace", ns),
                    registered=bool(status.get("registered", False)),
                    strategy=strat.get("name", "") or "",
                    gitUrl=git.get("url", "") or "",
                    gitRevision=git.get("revision", "") or "",
                    contextDir=source.get("contextDir", "") or "",
                    outputImage=out.get("image", "") or "",
                    creationTimestamp=_format_timestamp(
                        md.get("creationTimestamp") or md.get("creation_timestamp")
                    ),
                )
            )

    items.sort(key=lambda x: (x.namespace, x.name))
    return AgentShipwrightBuildListResponse(items=items)


@router.get(
    "/shipwright-builds",
    response_model=ShipwrightBuildListResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_agent_shipwright_builds(
    namespace: str = Query(
        default="",
        description="Kubernetes namespace (required unless all_namespaces=true)",
    ),
    all_namespaces: bool = Query(
        default=False,
        alias="allNamespaces",
        description="If true, list builds in all kagenti-enabled namespaces",
    ),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ShipwrightBuildListResponse:
    """List Shipwright Build resources for agents only (kagenti.io/type=agent)."""
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
            kube, namespaces_to_scan, RESOURCE_TYPE_AGENT, logger
        )
    except ApiException as e:
        raise HTTPException(status_code=e.status, detail=str(e.reason))

    return ShipwrightBuildListResponse(items=items)


@router.get(
    "/{namespace}/{name}/shipwright-build",
    response_model=ShipwrightBuildStatusResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_shipwright_build_status(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ShipwrightBuildStatusResponse:
    """Get the Shipwright Build status for an agent.

    Returns the Build resource status including whether it's registered
    and ready for BuildRuns.
    """
    try:
        build = kube.get_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name=name,
        )

        metadata = build.get("metadata", {})
        status = build.get("status", {})

        # Check if build is registered (strategy validated)
        registered = status.get("registered", False)
        reason = status.get("reason")
        message = status.get("message")

        return ShipwrightBuildStatusResponse(
            name=metadata.get("name", name),
            namespace=metadata.get("namespace", namespace),
            registered=registered,
            reason=reason,
            message=message,
        )

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Shipwright Build '{name}' not found in namespace '{namespace}'",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@router.get(
    "/{namespace}/{name}/shipwright-buildrun",
    response_model=ShipwrightBuildRunStatusResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_shipwright_buildrun_status(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> ShipwrightBuildRunStatusResponse:
    """Get the latest Shipwright BuildRun status for an agent build.

    Lists BuildRuns with label selector for the build name and returns
    the most recent one's status.
    """
    try:
        # List BuildRuns with label selector for this build
        items = kube.list_custom_resources(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector=f"kagenti.io/build-name={name}",
        )

        if not items:
            raise HTTPException(
                status_code=404,
                detail=f"No BuildRuns found for build '{name}' in namespace '{namespace}'",
            )

        # Sort by creation timestamp and get the most recent
        items.sort(
            key=lambda x: x.get("metadata", {}).get("creationTimestamp", ""),
            reverse=True,
        )
        latest_buildrun = items[0]

        metadata = latest_buildrun.get("metadata", {})
        status = latest_buildrun.get("status", {})
        spec = latest_buildrun.get("spec", {})

        # Extract conditions
        conditions = []
        for cond in status.get("conditions") or []:
            conditions.append(
                BuildStatusCondition(
                    type=cond.get("type", ""),
                    status=cond.get("status", ""),
                    reason=cond.get("reason"),
                    message=cond.get("message"),
                    lastTransitionTime=cond.get("lastTransitionTime"),
                )
            )

        # Determine phase from conditions
        phase = "Pending"
        failure_message = None
        for cond in conditions:
            if cond.type == "Succeeded":
                if cond.status == "True":
                    phase = "Succeeded"
                elif cond.status == "False":
                    phase = "Failed"
                    failure_message = cond.message
                else:
                    phase = "Running"
                break

        # Get output image info
        output = status.get("output", {})
        output_image = output.get("image")
        output_digest = output.get("digest")

        return ShipwrightBuildRunStatusResponse(
            name=metadata.get("name", ""),
            namespace=metadata.get("namespace", namespace),
            buildName=spec.get("build", {}).get("name", name),
            phase=phase,
            startTime=status.get("startTime"),
            completionTime=status.get("completionTime"),
            outputImage=output_image,
            outputDigest=output_digest,
            failureMessage=failure_message,
            conditions=conditions,
        )

    except ApiException as e:
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"BuildRun not found for build '{name}' in namespace '{namespace}'",
            )
        raise HTTPException(status_code=e.status, detail=str(e.reason))


@router.post(
    "/{namespace}/{name}/shipwright-buildrun", dependencies=[Depends(require_roles(ROLE_OPERATOR))]
)
async def trigger_shipwright_buildrun(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> Dict[str, Any]:
    """Trigger a new Shipwright BuildRun for an existing Build.

    Creates a new BuildRun resource to start a build execution.
    """
    try:
        # First verify the Build exists
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
        buildrun_manifest = _build_agent_shipwright_buildrun_manifest(
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


@router.get(
    "/{namespace}/{name}/shipwright-build-info",
    response_model=AgentShipwrightBuildInfoResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_shipwright_build_info(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> AgentShipwrightBuildInfoResponse:
    """Get full Shipwright Build information including agent config and BuildRun status.

    This endpoint provides all the information needed for the build progress page:
    - Build configuration and status
    - Latest BuildRun status
    - Agent configuration stored in annotations
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

        # Parse agent config from annotations using shared utility
        agent_config = extract_resource_config_from_build(build, ResourceType.AGENT)

        # Build response with basic build info
        response = AgentShipwrightBuildInfoResponse(
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
            agentConfig=agent_config,
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


def _build_authbridge_runtime_yaml(
    keycloak_url: str,
    realm: str,
    issuer: str,
    spire_enabled: bool,
) -> str:
    """Build the YAML config for the unified authbridge binary.

    The operator reads this as the base for per-agent ConfigMap generation,
    merging in mode and listener addresses at injection time. The Helm chart
    creates an equivalent ConfigMap for pre-declared namespaces
    (see charts/kagenti/templates/agent-namespaces.yaml).
    """
    identity_type = "spiffe" if spire_enabled else "client-secret"
    config = {
        "mode": "envoy-sidecar",
        "inbound": {"issuer": issuer},
        "outbound": {
            "keycloak_url": keycloak_url,
            "keycloak_realm": realm,
            "default_policy": "passthrough",
        },
        "identity": {
            "type": identity_type,
            "client_id_file": "/shared/client-id.txt",
            "client_secret_file": "/shared/client-secret.txt",
        },
        "bypass": {
            "inbound_paths": [
                "/.well-known/*",
                "/healthz",
                "/readyz",
                "/livez",
            ]
        },
    }
    if spire_enabled:
        config["identity"]["jwt_svid_path"] = "/opt/jwt_svid.token"

    return yaml.dump(config, default_flow_style=False)


def _ensure_authbridge_configmaps(
    kube: KubernetesService,
    namespace: str,
    spire_enabled: bool = False,
) -> None:
    """Ensure the 4 ConfigMaps required by AuthBridge sidecars exist.

    Creates each ConfigMap only if it does not already exist, so user
    customizations (e.g. pointing at a different Keycloak server) are
    preserved on subsequent agent deploys.

    ConfigMaps created:
      - authbridge-config: flat key-value Keycloak URLs for client-registration
      - authbridge-runtime-config: YAML config for the unified authbridge binary
      - envoy-config: Envoy proxy listeners and ext-proc integration
      - spiffe-helper-config: SPIFFE workload API socket paths and SVID output

    For Helm-managed namespaces, the Helm chart creates equivalent
    ConfigMaps at install time (see agent-namespaces.yaml).
    """
    keycloak_url = settings.keycloak_url or DEFAULT_KEYCLOAK_INTERNAL_URL
    realm = settings.effective_keycloak_realm or DEFAULT_KEYCLOAK_REALM
    # ISSUER must use the public/external URL because it must match the
    # "iss" claim in JWT tokens issued by Keycloak (split-horizon DNS).
    issuer = f"{settings.effective_keycloak_url}/realms/{realm}"

    # 1. authbridge-config (flat key-value for client-registration and legacy go-processor)
    kube.ensure_configmap(
        namespace=namespace,
        name="authbridge-config",
        data={
            "KEYCLOAK_URL": keycloak_url,
            "KEYCLOAK_REALM": realm,
            "ISSUER": issuer,
            "SPIRE_ENABLED": "true" if spire_enabled else "false",
        },
    )

    # 2. authbridge-runtime-config (YAML config for the unified authbridge binary)
    # The operator reads this at admission time and creates a per-agent ConfigMap
    # with mode and listener addresses merged in.
    kube.ensure_configmap(
        namespace=namespace,
        name="authbridge-runtime-config",
        data={
            "config.yaml": _build_authbridge_runtime_yaml(
                keycloak_url=keycloak_url,
                realm=realm,
                issuer=issuer,
                spire_enabled=spire_enabled,
            )
        },
    )

    # 3. envoy-config
    kube.ensure_configmap(
        namespace=namespace,
        name="envoy-config",
        data={"envoy.yaml": DEFAULT_ENVOY_YAML},
    )

    # 4. spiffe-helper-config
    kube.ensure_configmap(
        namespace=namespace,
        name="spiffe-helper-config",
        data={"helper.conf": DEFAULT_SPIFFE_HELPER_CONF},
    )

    logger.info(f"Ensured AuthBridge ConfigMaps in namespace '{namespace}'")


def _ensure_authproxy_routes(
    kube: KubernetesService,
    namespace: str,
    routes: List["OutboundRoute"],
) -> None:
    """Create or update the authproxy-routes ConfigMap with outbound token exchange rules."""
    import yaml as _yaml

    # AuthProxy go-processor expects a YAML list at file root (static.go), not {"routes": [...]}.
    routes_list = [r.model_dump() for r in routes]
    kube.upsert_configmap(
        namespace=namespace,
        name="authproxy-routes",
        data={"routes.yaml": _yaml.dump(routes_list, default_flow_style=False)},
    )
    logger.info(
        "Upserted authproxy-routes ConfigMap in namespace '%s' with %d route(s)",
        namespace,
        len(routes),
    )


def _ensure_authbridge_scc_rolebinding(
    kube: KubernetesService,
    namespace: str,
) -> None:
    """On OpenShift, ensure the AuthBridge SCC RoleBinding exists.

    AuthBridge sidecars need NET_ADMIN/NET_RAW capabilities, RunAsAny UIDs,
    and CSI volumes that OpenShift's default restricted-v2 SCC blocks.
    The Helm chart creates the ``kagenti-authbridge`` SCC and its ClusterRole;
    this function creates the per-namespace RoleBinding that grants it to all
    service accounts in the namespace.

    On non-OpenShift clusters this is a no-op.  If the ClusterRole doesn't
    exist (SCC not installed), a warning is logged and the function returns
    without error — the agent will still be created, but pods may fail with
    SCC errors until the SCC is installed.
    """
    if detect_platform(kube) != "openshift":
        return

    cluster_role_name = "system:openshift:scc:kagenti-authbridge"

    # Verify the ClusterRole exists (implies the SCC was installed)
    try:
        kube.rbac_api.read_cluster_role(name=cluster_role_name)
    except ApiException as e:
        if e.status == 404:
            logger.warning(
                "ClusterRole '%s' not found. "
                "The kagenti-authbridge SCC may not be installed. "
                "Agent pods may fail with SCC errors. "
                "Install via: helm upgrade kagenti charts/kagenti --set openshift=true",
                cluster_role_name,
            )
            return
        raise

    kube.ensure_rolebinding(
        namespace=namespace,
        name="agent-authbridge-scc",
        cluster_role_name=cluster_role_name,
        subjects=[
            kubernetes.client.RbacV1Subject(
                kind="Group",
                api_group="rbac.authorization.k8s.io",
                name=f"system:serviceaccounts:{namespace}",
            ),
        ],
    )


def _ensure_card_unsigned_configmap(
    kube: KubernetesService,
    name: str,
    namespace: str,
    service_port: int = DEFAULT_IN_CLUSTER_PORT,
) -> None:
    """Create the <agent>-card-unsigned ConfigMap if it does not exist.

    The Kagenti operator webhook checks for this ConfigMap when a
    Deployment is admitted.  If it exists, the webhook injects a
    ``sign-agentcard`` init container that signs the agent card with
    the workload's SPIRE SVID.  The ConfigMap must therefore be
    created **before** the Deployment.
    """
    agent_url = f"http://{name}.{namespace}.svc.cluster.local:{service_port}"
    agent_card = json.dumps(
        {
            "name": name,
            "url": agent_url,
            "version": "1.0.0",
            "capabilities": {},
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["text/plain"],
            "skills": [],
        },
        indent=2,
    )
    kube.ensure_configmap(
        namespace=namespace,
        name=f"{name}-card-unsigned",
        data={"agent.json": agent_card},
    )


def _build_agent_shipwright_build_manifest(
    request: CreateAgentRequest, clone_secret_name: Optional[str] = None
) -> dict:
    """
    Build a Shipwright Build CRD manifest for building an agent from source.

    This is a wrapper around the shared build_shipwright_build_manifest function
    that converts CreateAgentRequest to the shared function's parameters.
    """
    # Determine registry URL
    registry_url = request.registryUrl or DEFAULT_INTERNAL_REGISTRY

    # Build source config
    source_config = BuildSourceConfig(
        gitUrl=request.gitUrl,
        gitRevision=request.gitBranch,
        contextDir=request.gitPath or ".",
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
        "workloadType": request.workloadType,  # Store workload type for finalization
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
    # Add env vars if present
    if request.envVars:
        resource_config["envVars"] = [ev.model_dump(exclude_none=True) for ev in request.envVars]
    # Add service ports if present
    if request.servicePorts:
        resource_config["servicePorts"] = [sp.model_dump() for sp in request.servicePorts]

    return build_shipwright_build_manifest(
        name=request.name,
        namespace=request.namespace,
        resource_type=ResourceType.AGENT,
        source_config=source_config,
        output_config=output_config,
        build_config=request.shipwrightConfig,
        resource_config=resource_config,
        protocol=request.protocol,
        framework=request.framework,
    )


def _build_agent_shipwright_buildrun_manifest(
    build_name: str, namespace: str, labels: Optional[Dict[str, str]] = None
) -> dict:
    """
    Build a Shipwright BuildRun CRD manifest to trigger an agent build.

    This is a wrapper around the shared build_shipwright_buildrun_manifest function.
    """
    return build_shipwright_buildrun_manifest(
        build_name=build_name,
        namespace=namespace,
        resource_type=ResourceType.AGENT,
        labels=labels,
    )


# -----------------------------------------------------------------------------
# Workload Manifest Builders (Phase 1 - Migration to Standard K8s Workloads)
# -----------------------------------------------------------------------------


def _build_env_vars(request: "CreateAgentRequest") -> List[dict]:
    """
    Build environment variables list with support for valueFrom references.

    Args:
        request: The agent creation request containing envVars.

    Returns:
        List of environment variable dictionaries.
    """
    env_vars = list(DEFAULT_ENV_VARS)
    service_port = (
        request.servicePorts[0].port if request.servicePorts else DEFAULT_OFF_CLUSTER_PORT
    )
    env_vars.append(
        {
            "name": AGENT_ENDPOINT,
            "value": get_agent_url(request.name, request.namespace, service_port),
        }
    )
    if request.envVars:
        for ev in request.envVars:
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


def _build_common_labels(
    request: "CreateAgentRequest",
    workload_type: str = WORKLOAD_TYPE_DEPLOYMENT,
) -> Dict[str, str]:
    """
    Build common labels for agent workloads.

    All agent workloads MUST have these labels:
    - kagenti.io/type: agent
    - app.kubernetes.io/name: <agent-name>
    - protocol.kagenti.io/<protocol>: "" (at least one)

    Args:
        request: The agent creation request.
        workload_type: The type of workload (deployment, statefulset, job).

    Returns:
        Dictionary of labels.
    """
    labels = {
        # Required labels
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_AGENT,
        APP_KUBERNETES_IO_NAME: request.name,
        # Recommended labels
        KAGENTI_FRAMEWORK_LABEL: request.framework,
        KAGENTI_WORKLOAD_TYPE_LABEL: workload_type,
        APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
        APP_KUBERNETES_IO_COMPONENT: RESOURCE_TYPE_AGENT,
        # AuthBridge sidecar injection control
        KAGENTI_INJECT_LABEL: "enabled" if request.authBridgeEnabled else "disabled",
    }
    # Protocol label(s) using new prefix format
    if request.protocol:
        labels[f"{PROTOCOL_LABEL_PREFIX}{request.protocol}"] = ""
    # SPIRE identity label (triggers spiffe-helper sidecar injection by kagenti-webhook)
    if request.spireEnabled:
        labels[KAGENTI_SPIRE_LABEL] = KAGENTI_SPIRE_ENABLED_VALUE
    # Per-sidecar injection labels (opt-out for envoy/spiffe, opt-in for client-registration)
    if request.envoyProxyInject is False:
        labels[KAGENTI_ENVOY_PROXY_INJECT_LABEL] = "false"
    if request.spiffeHelperInject is False:
        labels[KAGENTI_SPIFFE_HELPER_INJECT_LABEL] = "false"
    if request.clientRegistrationInject is True:
        labels[KAGENTI_CLIENT_REGISTRATION_INJECT_LABEL] = "true"
    return labels


def _build_common_annotations(request: "CreateAgentRequest") -> Dict[str, str]:
    """Build pod template annotations for port exclusions and other webhook directives."""
    annotations: Dict[str, str] = {}
    if request.outboundPortsExclude:
        annotations[KAGENTI_OUTBOUND_PORTS_EXCLUDE] = request.outboundPortsExclude
    if request.inboundPortsExclude:
        annotations[KAGENTI_INBOUND_PORTS_EXCLUDE] = request.inboundPortsExclude
    return annotations


def _build_selector_labels(request: "CreateAgentRequest") -> Dict[str, str]:
    """
    Build selector labels for matching pods to workloads and services.

    Args:
        request: The agent creation request.

    Returns:
        Dictionary of selector labels.
    """
    return {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_AGENT,
        APP_KUBERNETES_IO_NAME: request.name,
    }


def _build_agentruntime_manifest(
    name: str,
    namespace: str,
    workload_type: str,
    agent_type: str = RESOURCE_TYPE_AGENT,
) -> dict:
    """Build an AgentRuntime CR manifest for the given workload."""
    kind_map = {
        WORKLOAD_TYPE_DEPLOYMENT: "Deployment",
        WORKLOAD_TYPE_STATEFULSET: "StatefulSet",
    }
    return {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": "AgentRuntime",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                KAGENTI_TYPE_LABEL: agent_type,
                APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
            },
        },
        "spec": {
            "type": agent_type,
            "targetRef": {
                "apiVersion": "apps/v1",
                "kind": kind_map.get(workload_type, "Deployment"),
                "name": name,
            },
        },
    }


def _ensure_agentruntime(
    kube: "KubernetesService",
    name: str,
    namespace: str,
    workload_type: str,
    agent_type: str = RESOURCE_TYPE_AGENT,
) -> None:
    """Create an AgentRuntime CR for the workload. Skip if it already exists."""
    manifest = _build_agentruntime_manifest(name, namespace, workload_type, agent_type)
    try:
        kube.create_custom_resource(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=AGENTRUNTIMES_PLURAL,
            body=manifest,
        )
        logger.info("Created AgentRuntime '%s' in namespace '%s'", name, namespace)
    except ApiException as e:
        if e.status == 409:
            logger.info("AgentRuntime '%s' already exists in namespace '%s'", name, namespace)
        else:
            logger.warning("Failed to create AgentRuntime '%s': %s", name, e.reason)


def _build_deployment_manifest(
    request: "CreateAgentRequest",
    image: str,
    shipwright_build_name: Optional[str] = None,
) -> dict:
    """
    Build a Kubernetes Deployment manifest for an agent.

    Args:
        request: The agent creation request.
        image: The container image URL.
        shipwright_build_name: Optional name of the Shipwright Build that created
            this agent (for annotation tracking).

    Returns:
        Deployment manifest dictionary.
    """
    env_vars = _build_env_vars(request)
    labels = _build_common_labels(request, WORKLOAD_TYPE_DEPLOYMENT)
    selector_labels = _build_selector_labels(request)

    # Build annotations
    annotations: Dict[str, str] = {
        KAGENTI_DESCRIPTION_ANNOTATION: f"Agent '{request.name}' deployed from UI.",
    }
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name

    # Build container ports
    container_port = DEFAULT_IN_CLUSTER_PORT
    if request.servicePorts and len(request.servicePorts) > 0:
        container_port = request.servicePorts[0].targetPort

    manifest = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": request.name,
            "namespace": request.namespace,
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
                    "labels": {
                        **labels,
                    },
                    "annotations": _build_common_annotations(request),
                },
                "spec": {
                    "serviceAccountName": request.name,
                    "containers": [
                        {
                            "name": "agent",
                            "image": image,
                            "imagePullPolicy": DEFAULT_IMAGE_POLICY,
                            "resources": {
                                "limits": DEFAULT_RESOURCE_LIMITS,
                                "requests": DEFAULT_RESOURCE_REQUESTS,
                            },
                            "env": env_vars,
                            "ports": [
                                {
                                    "name": "http",
                                    "containerPort": container_port,
                                    "protocol": "TCP",
                                },
                            ],
                            "volumeMounts": [
                                {"name": "cache", "mountPath": "/app/.cache"},
                                {"name": "marvin", "mountPath": "/.marvin"},
                                {"name": "shared-data", "mountPath": "/shared"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "cache", "emptyDir": {}},
                        {"name": "marvin", "emptyDir": {}},
                        {"name": "shared-data", "emptyDir": {}},
                    ],
                },
            },
        },
    }

    # Add image pull secrets if specified
    if request.imagePullSecret:
        manifest["spec"]["template"]["spec"]["imagePullSecrets"] = [
            {"name": request.imagePullSecret}
        ]

    return manifest


def _build_service_manifest(request: "CreateAgentRequest") -> dict:
    """
    Build a Kubernetes Service manifest for an agent.

    Args:
        request: The agent creation request.

    Returns:
        Service manifest dictionary.
    """
    labels = _build_common_labels(request, WORKLOAD_TYPE_DEPLOYMENT)
    selector_labels = _build_selector_labels(request)

    # Build service ports
    if request.servicePorts:
        service_ports = [
            {
                "name": sp.name,
                "port": sp.port,
                "targetPort": sp.targetPort,
                "protocol": sp.protocol,
            }
            for sp in request.servicePorts
        ]
    else:
        service_ports = [
            {
                "name": "http",
                "port": DEFAULT_OFF_CLUSTER_PORT,
                "targetPort": DEFAULT_IN_CLUSTER_PORT,
                "protocol": "TCP",
            }
        ]

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": request.name,
            "namespace": request.namespace,
            "labels": labels,
        },
        "spec": {
            "type": "ClusterIP",
            "selector": selector_labels,
            "ports": service_ports,
        },
    }


def _build_statefulset_manifest(
    request: "CreateAgentRequest",
    image: str,
    shipwright_build_name: Optional[str] = None,
) -> dict:
    """
    Build a Kubernetes StatefulSet manifest for an agent.

    StatefulSets are useful for agents that require:
    - Stable, unique network identifiers
    - Stable, persistent storage
    - Ordered, graceful deployment and scaling
    - Ordered, automated rolling updates

    Args:
        request: The agent creation request.
        image: The container image URL.
        shipwright_build_name: Optional name of the Shipwright Build.

    Returns:
        StatefulSet manifest dictionary.
    """
    env_vars = _build_env_vars(request)
    labels = _build_common_labels(request, WORKLOAD_TYPE_STATEFULSET)
    selector_labels = _build_selector_labels(request)

    # Build annotations
    annotations: Dict[str, str] = {
        KAGENTI_DESCRIPTION_ANNOTATION: f"Agent '{request.name}' deployed as StatefulSet from UI.",
    }
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name

    # Build container ports
    container_port = DEFAULT_IN_CLUSTER_PORT
    if request.servicePorts and len(request.servicePorts) > 0:
        container_port = request.servicePorts[0].targetPort

    manifest = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": request.name,
            "namespace": request.namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "serviceName": request.name,  # StatefulSet requires a headless service name
            "replicas": 1,
            "selector": {
                "matchLabels": selector_labels,
            },
            "template": {
                "metadata": {
                    "labels": {
                        **labels,
                    },
                    "annotations": _build_common_annotations(request),
                },
                "spec": {
                    "serviceAccountName": request.name,
                    "containers": [
                        {
                            "name": "agent",
                            "image": image,
                            "imagePullPolicy": DEFAULT_IMAGE_POLICY,
                            "resources": {
                                "limits": DEFAULT_RESOURCE_LIMITS,
                                "requests": DEFAULT_RESOURCE_REQUESTS,
                            },
                            "env": env_vars,
                            "ports": [
                                {
                                    "name": "http",
                                    "containerPort": container_port,
                                    "protocol": "TCP",
                                },
                            ],
                            "volumeMounts": [
                                {"name": "cache", "mountPath": "/app/.cache"},
                                {"name": "marvin", "mountPath": "/.marvin"},
                                {"name": "shared-data", "mountPath": "/shared"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "cache", "emptyDir": {}},
                        {"name": "marvin", "emptyDir": {}},
                        {"name": "shared-data", "emptyDir": {}},
                    ],
                },
            },
        },
    }

    # Add image pull secrets if specified
    if request.imagePullSecret:
        manifest["spec"]["template"]["spec"]["imagePullSecrets"] = [
            {"name": request.imagePullSecret}
        ]

    return manifest


def _build_job_manifest(
    request: "CreateAgentRequest",
    image: str,
    shipwright_build_name: Optional[str] = None,
) -> dict:
    """
    Build a Kubernetes Job manifest for an agent.

    Jobs are useful for agents that:
    - Run to completion (batch processing)
    - Should not be restarted automatically
    - Perform one-time tasks or scheduled workloads

    Args:
        request: The agent creation request.
        image: The container image URL.
        shipwright_build_name: Optional name of the Shipwright Build.

    Returns:
        Job manifest dictionary.
    """
    env_vars = _build_env_vars(request)
    labels = _build_common_labels(request, WORKLOAD_TYPE_JOB)

    # Build annotations
    annotations: Dict[str, str] = {
        KAGENTI_DESCRIPTION_ANNOTATION: f"Agent '{request.name}' deployed as Job from UI.",
    }
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name

    # Build container ports
    container_port = DEFAULT_IN_CLUSTER_PORT
    if request.servicePorts and len(request.servicePorts) > 0:
        container_port = request.servicePorts[0].targetPort

    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": request.name,
            "namespace": request.namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "backoffLimit": 3,  # Number of retries before considering the job failed
            "template": {
                "metadata": {
                    "labels": {
                        **labels,
                    },
                    "annotations": _build_common_annotations(request),
                },
                "spec": {
                    "serviceAccountName": request.name,
                    "restartPolicy": "OnFailure",
                    "containers": [
                        {
                            "name": "agent",
                            "image": image,
                            "imagePullPolicy": DEFAULT_IMAGE_POLICY,
                            "resources": {
                                "limits": DEFAULT_RESOURCE_LIMITS,
                                "requests": DEFAULT_RESOURCE_REQUESTS,
                            },
                            "env": env_vars,
                            "ports": [
                                {
                                    "name": "http",
                                    "containerPort": container_port,
                                    "protocol": "TCP",
                                },
                            ],
                            "volumeMounts": [
                                {"name": "cache", "mountPath": "/app/.cache"},
                                {"name": "marvin", "mountPath": "/.marvin"},
                                {"name": "shared-data", "mountPath": "/shared"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "cache", "emptyDir": {}},
                        {"name": "marvin", "emptyDir": {}},
                        {"name": "shared-data", "emptyDir": {}},
                    ],
                },
            },
        },
    }

    # Add image pull secrets if specified
    if request.imagePullSecret:
        manifest["spec"]["template"]["spec"]["imagePullSecrets"] = [
            {"name": request.imagePullSecret}
        ]

    return manifest


def _build_sandbox_template_manifest(
    request: "CreateAgentRequest",
    image: str,
    shipwright_build_name: Optional[str] = None,
) -> dict:
    """Build a SandboxTemplate manifest (extensions.agents.x-k8s.io/v1alpha1)."""
    env_vars = _build_env_vars(request)
    labels = _build_common_labels(request, WORKLOAD_TYPE_SANDBOX)

    annotations: Dict[str, str] = {
        KAGENTI_DESCRIPTION_ANNOTATION: f"Agent '{request.name}' deployed from UI.",
    }
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name

    container_port = DEFAULT_IN_CLUSTER_PORT
    if request.servicePorts and len(request.servicePorts) > 0:
        container_port = request.servicePorts[0].targetPort

    manifest = {
        "apiVersion": f"{AGENT_SANDBOX_EXT_GROUP}/{AGENT_SANDBOX_EXT_VERSION}",
        "kind": "SandboxTemplate",
        "metadata": {
            "name": request.name,
            "namespace": request.namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "podTemplate": {
                "metadata": {
                    "labels": {
                        **labels,
                    },
                    "annotations": _build_common_annotations(request),
                },
                "spec": {
                    "serviceAccountName": request.name,
                    "containers": [
                        {
                            "name": "agent",
                            "image": image,
                            "imagePullPolicy": DEFAULT_IMAGE_POLICY,
                            "resources": {
                                "limits": DEFAULT_RESOURCE_LIMITS,
                                "requests": DEFAULT_RESOURCE_REQUESTS,
                            },
                            "env": env_vars,
                            "ports": [
                                {
                                    "name": "http",
                                    "containerPort": container_port,
                                    "protocol": "TCP",
                                },
                            ],
                            "volumeMounts": [
                                {"name": "cache", "mountPath": "/app/.cache"},
                                {"name": "marvin", "mountPath": "/.marvin"},
                                {"name": "shared-data", "mountPath": "/shared"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "cache", "emptyDir": {}},
                        {"name": "marvin", "emptyDir": {}},
                        {"name": "shared-data", "emptyDir": {}},
                    ],
                },
            },
        },
    }

    if request.imagePullSecret:
        manifest["spec"]["podTemplate"]["spec"]["imagePullSecrets"] = [
            {"name": request.imagePullSecret}
        ]

    return manifest


def _build_sandbox_claim_manifest(
    request: "CreateAgentRequest",
    shipwright_build_name: Optional[str] = None,
) -> dict:
    """Build a SandboxClaim manifest (extensions.agents.x-k8s.io/v1alpha1)."""
    labels = _build_common_labels(request, WORKLOAD_TYPE_SANDBOX)

    annotations: Dict[str, str] = {
        KAGENTI_DESCRIPTION_ANNOTATION: f"Agent '{request.name}' deployed from UI.",
    }
    if shipwright_build_name:
        annotations["kagenti.io/shipwright-build"] = shipwright_build_name

    return {
        "apiVersion": f"{AGENT_SANDBOX_EXT_GROUP}/{AGENT_SANDBOX_EXT_VERSION}",
        "kind": "SandboxClaim",
        "metadata": {
            "name": request.name,
            "namespace": request.namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "sandboxTemplateRef": {"name": request.name},
        },
    }


@router.post(
    "", response_model=CreateAgentResponse, dependencies=[Depends(require_roles(ROLE_OPERATOR))]
)
async def create_agent(
    request: CreateAgentRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> CreateAgentResponse:
    """
    Create a new agent.

    Supports two deployment methods:
    - 'source': Build from git repository using Shipwright Build + BuildRun
    - 'image': Deploy from existing container image as workload + Service

    Supports four workload types:
    - 'deployment': Standard Kubernetes Deployment (default)
    - 'statefulset': StatefulSet for stateful agents
    - 'job': Job for batch/one-time agents
    - 'sandbox': Sandbox CR for isolated agents (requires feature flag)
    """
    logger.info(
        f"Creating agent '{request.name}' in namespace '{request.namespace}', "
        f"workloadType={request.workloadType}, "
        f"createHttpRoute={request.createHttpRoute}"
    )
    try:
        if request.deploymentMethod == "image":
            # Deploy from existing container image
            if not request.containerImage:
                raise HTTPException(
                    status_code=400,
                    detail="containerImage is required for image deployment",
                )

            # Ensure a dedicated ServiceAccount exists so the webhook's
            # SPIFFE identity uses the workload name, not the ReplicaSet hash.
            kube.ensure_service_account(namespace=request.namespace, name=request.name)

            # Ensure AuthBridge ConfigMaps exist in the target namespace
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
                    extra_config = {
                        "DEFAULT_OUTBOUND_POLICY": request.defaultOutboundPolicy,
                    }
                    kube.upsert_configmap(
                        namespace=request.namespace,
                        name="authbridge-config",
                        data=extra_config,
                    )

            # On OpenShift, ensure the AuthBridge SCC RoleBinding exists
            if request.authBridgeEnabled:
                _ensure_authbridge_scc_rolebinding(kube=kube, namespace=request.namespace)

            # Create card-unsigned ConfigMap so the webhook injects
            # the sign-agentcard init container at Deployment admission.
            if request.spireEnabled:
                service_port = (
                    request.servicePorts[0].port
                    if request.servicePorts
                    else DEFAULT_IN_CLUSTER_PORT
                )
                _ensure_card_unsigned_configmap(
                    kube=kube,
                    name=request.name,
                    namespace=request.namespace,
                    service_port=service_port,
                )

            # Create workload based on workloadType
            if request.workloadType == WORKLOAD_TYPE_DEPLOYMENT:
                workload_manifest = _build_deployment_manifest(
                    request=request,
                    image=request.containerImage,
                )
                kube.create_deployment(
                    namespace=request.namespace,
                    body=workload_manifest,
                )
                logger.info(
                    f"Created Deployment '{request.name}' in namespace '{request.namespace}'"
                )
            elif request.workloadType == WORKLOAD_TYPE_STATEFULSET:
                workload_manifest = _build_statefulset_manifest(
                    request=request,
                    image=request.containerImage,
                )
                kube.create_statefulset(
                    namespace=request.namespace,
                    body=workload_manifest,
                )
                logger.info(
                    f"Created StatefulSet '{request.name}' in namespace '{request.namespace}'"
                )
            elif request.workloadType == WORKLOAD_TYPE_JOB:
                workload_manifest = _build_job_manifest(
                    request=request,
                    image=request.containerImage,
                )
                kube.create_job(
                    namespace=request.namespace,
                    body=workload_manifest,
                )
                logger.info(f"Created Job '{request.name}' in namespace '{request.namespace}'")
            elif request.workloadType == WORKLOAD_TYPE_SANDBOX:
                template_manifest = _build_sandbox_template_manifest(
                    request=request,
                    image=request.containerImage,
                )
                kube.create_sandbox_template(
                    namespace=request.namespace,
                    body=template_manifest,
                )
                claim_manifest = _build_sandbox_claim_manifest(request=request)
                try:
                    kube.create_sandbox_claim(
                        namespace=request.namespace,
                        body=claim_manifest,
                    )
                except Exception:
                    try:
                        kube.delete_sandbox_template(namespace=request.namespace, name=request.name)
                    except Exception:
                        logger.warning(
                            "Failed to clean up orphaned SandboxTemplate '%s'",
                            request.name,
                        )
                    raise
                logger.info(
                    f"Created SandboxTemplate + SandboxClaim '{request.name}' "
                    f"in namespace '{request.namespace}'"
                )

            # Create Service (not needed for Jobs or Sandboxes)
            if request.workloadType not in (WORKLOAD_TYPE_JOB, WORKLOAD_TYPE_SANDBOX):
                service_manifest = _build_service_manifest(request)
                kube.create_service(
                    namespace=request.namespace,
                    body=service_manifest,
                )
                logger.info(f"Created Service '{request.name}' in namespace '{request.namespace}'")

            # Create AgentRuntime CR so the webhook injects sidecars on pod rollout
            if request.workloadType not in (WORKLOAD_TYPE_JOB, WORKLOAD_TYPE_SANDBOX):
                _ensure_agentruntime(
                    kube=kube,
                    name=request.name,
                    namespace=request.namespace,
                    workload_type=request.workloadType,
                )

            message = f"Agent '{request.name}' deployed as {request.workloadType} successfully."

            # Create HTTPRoute/Route if requested (not applicable for Jobs or Sandboxes)
            if request.createHttpRoute and request.workloadType not in (
                WORKLOAD_TYPE_JOB,
                WORKLOAD_TYPE_SANDBOX,
            ):
                service_port = select_route_port(
                    request.servicePorts,
                    default_port=DEFAULT_OFF_CLUSTER_PORT,
                )
                create_route_for_agent_or_tool(
                    kube=kube,
                    name=request.name,
                    namespace=request.namespace,
                    service_name=request.name,
                    service_port=service_port,
                )
                message += " HTTPRoute/Route created for external access."

        else:
            # Build from source using Shipwright Build + BuildRun
            if not request.gitUrl:
                raise HTTPException(
                    status_code=400,
                    detail="gitUrl is required for source deployment",
                )

            # Step 1: Create Shipwright Build CR
            clone_secret = resolve_clone_secret(kube.core_api, request.namespace)
            build_manifest = _build_agent_shipwright_build_manifest(
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
                f"Created Shipwright Build '{request.name}' in namespace '{request.namespace}'"
            )

            # Step 2: Create BuildRun CR to trigger the build
            # Get labels from the Build manifest to propagate to BuildRun
            build_labels = build_manifest.get("metadata", {}).get("labels", {})
            buildrun_manifest = _build_agent_shipwright_buildrun_manifest(
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
                f"Created Shipwright BuildRun '{buildrun_name}' in namespace '{request.namespace}'"
            )

            message = (
                f"Shipwright build started for agent '{request.name}'. "
                f"BuildRun: '{buildrun_name}'. "
                f"Poll the build status and create the Agent after the build completes."
            )

            # Note: For Shipwright builds, HTTPRoute is NOT created here.
            # It will be created when the Agent is finalized after build completion.
            if request.createHttpRoute:
                message += " HTTPRoute will be created after the build completes."

        return CreateAgentResponse(
            success=True,
            name=request.name,
            namespace=request.namespace,
            message=message,
        )

    except ApiException as e:
        if e.status == 409:
            raise HTTPException(
                status_code=409,
                detail=f"Agent '{request.name}' already exists in namespace '{request.namespace}'",
            )
        if e.status == 404:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Required CRD or resource not found for workload type "
                    f"'{request.workloadType}'. Ensure the necessary controllers "
                    f"are installed (e.g. Shipwright for source builds, "
                    f"agent-sandbox controller for sandbox workloads)."
                ),
            )
        logger.error(f"Failed to create agent: {e}")
        raise HTTPException(status_code=e.status, detail=str(e.reason))


class FinalizeShipwrightBuildRequest(BaseModel):
    """Request to finalize a Shipwright build and create the Agent.

    All fields are optional. If not provided, the values stored in the Build's
    kagenti.io/agent-config annotation will be used.
    """

    # These fields mirror CreateAgentRequest for Agent creation
    # All optional - will use values from Build annotation if not provided
    protocol: Optional[str] = None
    framework: Optional[str] = None
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


@router.post(
    "/{namespace}/{name}/finalize-shipwright-build",
    response_model=CreateAgentResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def finalize_shipwright_build(
    namespace: str,
    name: str,
    request: FinalizeShipwrightBuildRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> CreateAgentResponse:
    """
    Finalize a Shipwright build by creating the Deployment and Service.

    This endpoint should be called after the Shipwright BuildRun completes successfully.
    It retrieves the output image from the BuildRun status and creates the Deployment
    and Service for the agent.

    Agent configuration can be provided in the request body, or it will be read from
    the Build's kagenti.io/agent-config annotation (stored during build creation).
    """
    logger.info(f"Finalizing Shipwright build '{name}' in namespace '{namespace}'")

    try:
        # Step 1: Get the latest BuildRun status to get the output image
        items = kube.list_custom_resources(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector=f"kagenti.io/build-name={name}",
        )

        if not items:
            raise HTTPException(
                status_code=404,
                detail=f"No BuildRuns found for build '{name}' in namespace '{namespace}'",
            )

        # Sort by creation timestamp and get the most recent
        items.sort(
            key=lambda x: x.get("metadata", {}).get("creationTimestamp", ""),
            reverse=True,
        )
        latest_buildrun = items[0]
        buildrun_status = latest_buildrun.get("status", {})

        # Check if build succeeded
        conditions = buildrun_status.get("conditions") or []
        build_succeeded = False
        failure_message = None
        for cond in conditions:
            if cond.get("type") == "Succeeded":
                if cond.get("status") == "True":
                    build_succeeded = True
                else:
                    failure_message = cond.get("message", "Build failed")
                break

        if not build_succeeded:
            raise HTTPException(
                status_code=400,
                detail=f"Build has not succeeded yet. Status: {failure_message or 'In progress'}",
            )

        # Get Build resource for labels and stored agent config (needed for workload type check)
        build = kube.get_custom_resource(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name=name,
        )
        build_metadata = build.get("metadata", {})
        build_labels = build_metadata.get("labels", {})
        build_annotations = build_metadata.get("annotations", {})

        # Parse stored agent config from Build annotations
        stored_config: Dict[str, Any] = {}
        agent_config_json = build_annotations.get("kagenti.io/agent-config")
        if agent_config_json:
            try:
                stored_config = json.loads(agent_config_json)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse agent config from Build annotation: {e}")

        # Determine expected workload type from stored config
        expected_workload_type = stored_config.get("workloadType", WORKLOAD_TYPE_DEPLOYMENT)

        # Check if workload already exists (idempotency check)
        # This handles the case where finalize is called multiple times
        workload_exists = False
        existing_workload_type = None
        try:
            kube.get_deployment(namespace=namespace, name=name)
            workload_exists = True
            existing_workload_type = WORKLOAD_TYPE_DEPLOYMENT
        except ApiException as e:
            if e.status != 404:
                raise
        if not workload_exists:
            try:
                kube.get_statefulset(namespace=namespace, name=name)
                workload_exists = True
                existing_workload_type = WORKLOAD_TYPE_STATEFULSET
            except ApiException as e:
                if e.status != 404:
                    raise
        if not workload_exists:
            try:
                kube.get_job(namespace=namespace, name=name)
                workload_exists = True
                existing_workload_type = WORKLOAD_TYPE_JOB
            except ApiException as e:
                if e.status != 404:
                    raise
        if not workload_exists and settings.kagenti_feature_flag_agent_sandbox:
            try:
                kube.get_sandbox_claim(namespace=namespace, name=name)
                workload_exists = True
                existing_workload_type = WORKLOAD_TYPE_SANDBOX
            except ApiException as e:
                if e.status != 404:
                    raise

        if workload_exists:
            # Check if existing workload type matches expected type from config
            if existing_workload_type != expected_workload_type:
                logger.warning(
                    f"Workload type mismatch for '{name}' in namespace '{namespace}': "
                    f"existing workload is {existing_workload_type}, but stored config "
                    f"specifies {expected_workload_type}. This may indicate a configuration issue."
                )
                return CreateAgentResponse(
                    success=True,
                    name=name,
                    namespace=namespace,
                    message=(
                        f"Agent '{name}' already deployed as {existing_workload_type}, "
                        f"but stored config specifies {expected_workload_type}. "
                        "The existing workload was preserved."
                    ),
                )
            logger.info(
                f"Workload '{name}' already exists as {existing_workload_type} in namespace '{namespace}'. "
                "Skipping creation (finalize already completed)."
            )
            return CreateAgentResponse(
                success=True,
                name=name,
                namespace=namespace,
                message=f"Agent '{name}' already deployed as {existing_workload_type}.",
            )

        # Get the output image from BuildRun status
        output = buildrun_status.get("output", {})
        output_image = output.get("image")
        output_digest = output.get("digest")

        if not output_image:
            # Fallback: try to get image from Build spec (build already fetched earlier)
            output_image = build.get("spec", {}).get("output", {}).get("image")

        if not output_image:
            raise HTTPException(
                status_code=500,
                detail="Could not determine output image from build",
            )

        # If we have a digest, use it for immutable image reference
        container_image = f"{output_image}@{output_digest}" if output_digest else output_image

        # Merge request with stored config (request values take precedence)
        # Note: build, build_labels, build_annotations, and stored_config were fetched earlier
        final_protocol = (
            request.protocol
            if request.protocol is not None
            else stored_config.get("protocol", "a2a")
        )
        final_framework = (
            request.framework
            if request.framework is not None
            else stored_config.get("framework", "LangGraph")
        )
        final_create_route = (
            request.createHttpRoute
            if request.createHttpRoute is not None
            else stored_config.get("createHttpRoute", False)
        )
        final_registry_secret = (
            request.imagePullSecret
            if request.imagePullSecret is not None
            else stored_config.get("registrySecret")
        )
        final_auth_bridge = (
            request.authBridgeEnabled
            if request.authBridgeEnabled is not None
            else stored_config.get("authBridgeEnabled", True)
        )
        # Use expected_workload_type computed earlier (from stored config)
        final_workload_type = expected_workload_type

        # For envVars and servicePorts, use request if provided, otherwise use stored config
        final_env_vars = request.envVars
        if final_env_vars is None and "envVars" in stored_config:
            # Convert stored dict format back to EnvVar objects
            final_env_vars = [EnvVar(**ev) for ev in stored_config["envVars"]]

        final_service_ports = request.servicePorts
        if final_service_ports is None and "servicePorts" in stored_config:
            # Convert stored dict format back to ServicePort objects
            final_service_ports = [ServicePort(**sp) for sp in stored_config["servicePorts"]]

        # Propagate SPIRE identity setting from stored config
        final_spire_enabled = stored_config.get("spireEnabled", False)

        # Port exclusion and advanced config
        final_outbound_ports_exclude = (
            request.outboundPortsExclude
            if request.outboundPortsExclude is not None
            else stored_config.get("outboundPortsExclude")
        )
        final_inbound_ports_exclude = (
            request.inboundPortsExclude
            if request.inboundPortsExclude is not None
            else stored_config.get("inboundPortsExclude")
        )
        final_default_outbound_policy = (
            request.defaultOutboundPolicy
            if request.defaultOutboundPolicy is not None
            else stored_config.get("defaultOutboundPolicy")
        )
        # Outbound routing rules
        final_outbound_routes = None
        stored_routes = stored_config.get("outboundRoutes")
        if request.outboundRoutes is not None:
            final_outbound_routes = request.outboundRoutes
        elif stored_routes:
            final_outbound_routes = [OutboundRoute(**r) for r in stored_routes]

        # Per-sidecar injection controls
        final_envoy_proxy_inject = (
            request.envoyProxyInject
            if request.envoyProxyInject is not None
            else stored_config.get("envoyProxyInject")
        )
        final_spiffe_helper_inject = (
            request.spiffeHelperInject
            if request.spiffeHelperInject is not None
            else stored_config.get("spiffeHelperInject")
        )
        final_client_registration_inject = (
            request.clientRegistrationInject
            if request.clientRegistrationInject is not None
            else stored_config.get("clientRegistrationInject")
        )

        # Step 3: Create workload + Service with the built image
        # Build a CreateAgentRequest-like object for manifest builders
        agent_request = CreateAgentRequest(
            name=name,
            namespace=namespace,
            protocol=final_protocol,
            framework=final_framework,
            deploymentMethod="image",
            workloadType=final_workload_type,
            containerImage=container_image,
            imagePullSecret=final_registry_secret,
            envVars=final_env_vars,
            servicePorts=final_service_ports,
            createHttpRoute=final_create_route,
            authBridgeEnabled=final_auth_bridge,
            spireEnabled=final_spire_enabled,
            envoyProxyInject=final_envoy_proxy_inject,
            spiffeHelperInject=final_spiffe_helper_inject,
            clientRegistrationInject=final_client_registration_inject,
            outboundRoutes=final_outbound_routes,
            outboundPortsExclude=final_outbound_ports_exclude,
            inboundPortsExclude=final_inbound_ports_exclude,
            defaultOutboundPolicy=final_default_outbound_policy,
        )

        # Ensure a dedicated ServiceAccount exists so the webhook's
        # SPIFFE identity uses the workload name, not the ReplicaSet hash.
        kube.ensure_service_account(namespace=namespace, name=name)

        # Ensure AuthBridge ConfigMaps exist in the target namespace
        if final_auth_bridge:
            _ensure_authbridge_configmaps(
                kube=kube,
                namespace=namespace,
                spire_enabled=final_spire_enabled,
            )
            if final_outbound_routes:
                _ensure_authproxy_routes(
                    kube=kube,
                    namespace=namespace,
                    routes=final_outbound_routes,
                )

        # On OpenShift, ensure the AuthBridge SCC RoleBinding exists
        if final_auth_bridge:
            _ensure_authbridge_scc_rolebinding(kube=kube, namespace=namespace)

        # Create card-unsigned ConfigMap so the webhook injects
        # the sign-agentcard init container at Deployment admission.
        if final_spire_enabled:
            service_port = (
                final_service_ports[0].port if final_service_ports else DEFAULT_IN_CLUSTER_PORT
            )
            _ensure_card_unsigned_configmap(
                kube=kube,
                name=name,
                namespace=namespace,
                service_port=service_port,
            )

        # Create workload based on workloadType
        if final_workload_type == WORKLOAD_TYPE_DEPLOYMENT:
            workload_manifest = _build_deployment_manifest(
                request=agent_request,
                image=container_image,
                shipwright_build_name=name,
            )
            # Add additional labels from Build
            workload_manifest["metadata"]["labels"].update(
                {k: v for k, v in build_labels.items() if k.startswith("kagenti.io/")}
            )
            # Also update pod template labels
            workload_manifest["spec"]["template"]["metadata"]["labels"].update(
                {k: v for k, v in build_labels.items() if k.startswith("kagenti.io/")}
            )
            kube.create_deployment(namespace=namespace, body=workload_manifest)
            logger.info(
                f"Created Deployment '{name}' with image '{container_image}' in namespace '{namespace}'"
            )
        elif final_workload_type == WORKLOAD_TYPE_STATEFULSET:
            workload_manifest = _build_statefulset_manifest(
                request=agent_request,
                image=container_image,
                shipwright_build_name=name,
            )
            # Add additional labels from Build
            workload_manifest["metadata"]["labels"].update(
                {k: v for k, v in build_labels.items() if k.startswith("kagenti.io/")}
            )
            # Also update pod template labels
            workload_manifest["spec"]["template"]["metadata"]["labels"].update(
                {k: v for k, v in build_labels.items() if k.startswith("kagenti.io/")}
            )
            kube.create_statefulset(namespace=namespace, body=workload_manifest)
            logger.info(
                f"Created StatefulSet '{name}' with image '{container_image}' in namespace '{namespace}'"
            )
        elif final_workload_type == WORKLOAD_TYPE_JOB:
            workload_manifest = _build_job_manifest(
                request=agent_request,
                image=container_image,
                shipwright_build_name=name,
            )
            # Add additional labels from Build
            workload_manifest["metadata"]["labels"].update(
                {k: v for k, v in build_labels.items() if k.startswith("kagenti.io/")}
            )
            # Also update pod template labels
            workload_manifest["spec"]["template"]["metadata"]["labels"].update(
                {k: v for k, v in build_labels.items() if k.startswith("kagenti.io/")}
            )
            kube.create_job(namespace=namespace, body=workload_manifest)
            logger.info(
                f"Created Job '{name}' with image '{container_image}' in namespace '{namespace}'"
            )
        elif final_workload_type == WORKLOAD_TYPE_SANDBOX:
            template_manifest = _build_sandbox_template_manifest(
                request=agent_request,
                image=container_image,
                shipwright_build_name=name,
            )
            kagenti_build_labels = {
                k: v for k, v in build_labels.items() if k.startswith(settings.kagenti_label_prefix)
            }
            template_manifest["metadata"]["labels"].update(kagenti_build_labels)
            template_manifest["spec"]["podTemplate"]["metadata"]["labels"].update(
                kagenti_build_labels
            )
            kube.create_sandbox_template(namespace=namespace, body=template_manifest)
            claim_manifest = _build_sandbox_claim_manifest(
                request=agent_request,
                shipwright_build_name=name,
            )
            claim_manifest["metadata"]["labels"].update(kagenti_build_labels)
            try:
                kube.create_sandbox_claim(namespace=namespace, body=claim_manifest)
            except Exception:
                try:
                    kube.delete_sandbox_template(namespace=namespace, name=name)
                except Exception:
                    logger.warning("Failed to clean up orphaned SandboxTemplate '%s'", name)
                raise
            logger.info(
                f"Created SandboxTemplate + SandboxClaim '{name}' "
                f"in namespace '{namespace}' from build"
            )

        # Create Service (not needed for Jobs or Sandboxes)
        if final_workload_type not in (WORKLOAD_TYPE_JOB, WORKLOAD_TYPE_SANDBOX):
            service_manifest = _build_service_manifest(agent_request)
            # Add additional labels from Build
            service_manifest["metadata"]["labels"].update(
                {k: v for k, v in build_labels.items() if k.startswith("kagenti.io/")}
            )
            kube.create_service(namespace=namespace, body=service_manifest)
            logger.info(f"Created Service '{name}' in namespace '{namespace}'")

        # Create AgentRuntime CR so the webhook injects sidecars on pod rollout
        # Only for agents — tools don't need sidecar injection
        resource_type = build_labels.get(KAGENTI_TYPE_LABEL, RESOURCE_TYPE_AGENT)
        if (
            final_workload_type not in (WORKLOAD_TYPE_JOB, WORKLOAD_TYPE_SANDBOX)
            and resource_type == RESOURCE_TYPE_AGENT
        ):
            _ensure_agentruntime(
                kube=kube,
                name=name,
                namespace=namespace,
                workload_type=final_workload_type,
            )

        message = f"Agent '{name}' deployed as {final_workload_type} with image '{output_image}'."

        # Step 4: Create HTTPRoute/Route if requested (not applicable for Jobs or Sandboxes)
        if final_create_route and final_workload_type not in (
            WORKLOAD_TYPE_JOB,
            WORKLOAD_TYPE_SANDBOX,
        ):
            service_port = select_route_port(
                final_service_ports,
                default_port=DEFAULT_OFF_CLUSTER_PORT,
            )
            create_route_for_agent_or_tool(
                kube=kube,
                name=name,
                namespace=namespace,
                service_name=name,
                service_port=service_port,
            )
            message += " HTTPRoute/Route created for external access."

        return CreateAgentResponse(
            success=True,
            name=name,
            namespace=namespace,
            message=message,
        )

    except ApiException as e:
        if e.status == 409:
            raise HTTPException(
                status_code=409,
                detail=f"Agent '{name}' already exists in namespace '{namespace}'",
            )
        logger.error(f"Failed to finalize build: {e}")
        raise HTTPException(status_code=e.status, detail=str(e.reason))


# New models for env parsing
class ParseEnvRequest(BaseModel):
    """Request to parse .env file content."""

    content: str


class ParseEnvResponse(BaseModel):
    """Response with parsed environment variables."""

    envVars: List[Dict[str, Any]]
    warnings: Optional[List[str]] = None


class FetchEnvUrlRequest(BaseModel):
    """Request to fetch .env file from URL."""

    url: str


class FetchEnvUrlResponse(BaseModel):
    """Response with fetched .env file content."""

    content: str
    url: str


# Blocked IP ranges for SSRF protection
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
]


def is_ip_blocked(ip_str: str) -> bool:
    """Check if IP is in blocked range for SSRF protection."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in BLOCKED_IP_RANGES)
    except ValueError:
        return False


@router.post(
    "/parse-env",
    response_model=ParseEnvResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def parse_env_file(request: ParseEnvRequest) -> ParseEnvResponse:
    """
    Parse .env file content and return structured environment variables.
    Supports:
    - Standard KEY=value format
    - Extended JSON format for secretKeyRef and configMapKeyRef

    Example extended format:
    SECRET_KEY='{"valueFrom": {"secretKeyRef": {"name": "openai-secret", "key": "apikey"}}}'
    """
    env_vars = []
    warnings = []

    lines = request.content.strip().split("\n")

    for line_num, line in enumerate(lines, 1):
        # Skip empty lines and comments
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Parse KEY=VALUE
        if "=" not in line:
            warnings.append(f"Line {line_num}: Invalid format, missing '='")
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        # Validate environment variable name
        env_var_pattern = r"^[A-Za-z_][A-Za-z0-9_]*$"
        if not re.match(env_var_pattern, key):
            warnings.append(
                f"Line {line_num}: Invalid variable name '{key}'. "
                "Name must start with a letter or underscore and contain only "
                "letters, digits, and underscores."
            )
            continue

        # Remove quotes if present
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        # Try to parse as JSON (for extended format)
        if value.startswith("{") and value.endswith("}"):
            try:
                parsed = json.loads(value)
                if "valueFrom" in parsed:
                    env_var = {"name": key, "valueFrom": parsed["valueFrom"]}
                    env_vars.append(env_var)
                    continue
                else:
                    # It's valid JSON but not our expected format, treat as string
                    warnings.append(
                        f"Line {line_num}: JSON value without 'valueFrom' key, treating as string"
                    )
            except json.JSONDecodeError as e:
                warnings.append(f"Line {line_num}: Invalid JSON in value: {str(e)}")

        # Standard value
        env_vars.append({"name": key, "value": value})

    return ParseEnvResponse(envVars=env_vars, warnings=warnings if warnings else None)


@router.post(
    "/fetch-env-url",
    response_model=FetchEnvUrlResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def fetch_env_from_url(request: FetchEnvUrlRequest) -> FetchEnvUrlResponse:
    """
    Fetch .env file content from a remote URL.
    Supports HTTP/HTTPS URLs with security validations to prevent SSRF attacks.

    Example URLs:
    - https://raw.githubusercontent.com/kagenti/agent-examples/main/a2a/git_issue_agent/.env.openai
    - https://example.com/config/.env
    """
    import os
    import ssl
    from pathlib import Path

    logger.info(f"Fetching .env file from URL: {request.url}")

    # Log SSL/Certificate configuration
    logger.info(f"SSL_CERT_FILE env: {os.environ.get('SSL_CERT_FILE', 'NOT SET')}")
    logger.info(f"REQUESTS_CA_BUNDLE env: {os.environ.get('REQUESTS_CA_BUNDLE', 'NOT SET')}")
    logger.info(f"Default SSL context: {ssl.get_default_verify_paths()}")

    # Check if cert files exist
    cert_paths = [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/certs/ca-bundle.crt",
        "/usr/local/share/ca-certificates/",
    ]
    for cert_path in cert_paths:
        exists = (
            Path(cert_path).exists() if cert_path.endswith(".crt") else Path(cert_path).is_dir()
        )
        logger.info(f"Certificate path {cert_path}: {'EXISTS' if exists else 'NOT FOUND'}")

    # Security validation - only allow http/https
    parsed_url = urlparse(request.url)
    if parsed_url.scheme not in ["http", "https"]:
        raise HTTPException(status_code=400, detail="Only HTTP/HTTPS URLs are supported")

    # Validate hostname exists
    if not parsed_url.hostname:
        raise HTTPException(status_code=400, detail="Invalid URL: hostname not found")

    # Prevent SSRF attacks - block private IPs
    try:
        ip = socket.gethostbyname(parsed_url.hostname)
        logger.debug(f"Resolved {parsed_url.hostname} to {ip}")
        if is_ip_blocked(ip):
            logger.warning(f"Blocked private IP address: {ip}")
            raise HTTPException(
                status_code=400, detail="Private IP addresses are not allowed for security reasons"
            )
    except socket.gaierror as e:
        # Domain can't be resolved - log but let httpx handle it
        logger.warning(f"Could not resolve hostname {parsed_url.hostname}: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Error checking IP for {parsed_url.hostname}: {e}")

    # Fetch content with timeout
    try:
        # Explicitly use system CA bundle instead of Kubernetes service account CA
        # Kubernetes sets SSL_CERT_FILE to /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        # which doesn't include public CAs like GitHub. We need to explicitly point to system CAs.
        ca_bundle_path = "/etc/ssl/certs/ca-certificates.crt"
        if not Path(ca_bundle_path).exists():
            # Fallback to alternative paths
            for fallback in ["/etc/ssl/certs/ca-bundle.crt", "/etc/pki/tls/certs/ca-bundle.crt"]:
                if Path(fallback).exists():
                    ca_bundle_path = fallback
                    break

        logger.info(f"Using CA bundle: {ca_bundle_path}")

        # Create SSL context with system certificates
        ssl_context = ssl.create_default_context(cafile=ca_bundle_path)

        async with httpx.AsyncClient(
            timeout=10.0, follow_redirects=True, verify=ssl_context
        ) as client:
            logger.debug(f"Making HTTP request to {request.url}")
            response = await client.get(request.url)
            response.raise_for_status()

            logger.info(f"Successfully fetched URL, content length: {len(response.text)} bytes")

            # Validate content isn't too large (max 1MB)
            content = response.text
            if len(content) > 1024 * 1024:
                raise HTTPException(status_code=413, detail="File content too large (max 1MB)")

            return FetchEnvUrlResponse(content=content, url=request.url)
    except httpx.TimeoutException as e:
        logger.error(f"Timeout fetching URL {request.url}: {e}")
        raise HTTPException(status_code=504, detail="Request timeout while fetching URL")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching URL {request.url}: {e.response.status_code}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Failed to fetch URL: {e.response.status_code} {e.response.reason_phrase}",
        )
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching URL {request.url}: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error fetching URL {request.url}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


if settings.kagenti_feature_flag_authbridge_api:

    @router.get(
        "/{namespace}/{name}/identity-config", dependencies=[Depends(require_roles(ROLE_OPERATOR))]
    )
    async def get_agent_identity_config(
        namespace: str,
        name: str,
        kube: KubernetesService = Depends(get_kubernetes_service),
    ) -> dict:
        """
        Fetch the AuthBridge configuration for an Agent.
        """

        namespace = sanitize_log(namespace)
        name = sanitize_log(name)

        try:
            addresses = _get_service_endpoints(kube=kube, namespace=namespace, name=name)
        except ApiException as e:
            raise HTTPException(status_code=502, detail=e.reason)

        attempts = 0
        for address in addresses:
            attempts += 1
            # AuthBridge serves config and status on port 9093
            url = f"http://{address}:9093/config"
            try:
                data = await _fetch_authbridge_json(url)
                data["AuthBridge"] = True
                return data
            except Exception:
                # It isn't an error for an endpoint to be unreachable, only for all pods to be unreachable
                logger.info("Failed to talk to url %s; skipping", url, exc_info=True)

        if attempts == 0:
            raise HTTPException(status_code=404, detail=f"{name} not found")

        logger.info("Could not invoke any AuthBridge endpoints for %s/%s", namespace, name)
        # We return HTTP 200 if no pods respond - this might be a valid agent w/o AuthBridge
        return {"AuthBridge": False}

    @router.get(
        "/{namespace}/{name}/identity-status", dependencies=[Depends(require_roles(ROLE_OPERATOR))]
    )
    async def get_agent_identity_status(
        namespace: str,
        name: str,
        kube: KubernetesService = Depends(get_kubernetes_service),
    ) -> dict:
        """
        Fetch the AuthBridge statistics and status for an Agent.
        """

        namespace = sanitize_log(namespace)
        name = sanitize_log(name)

        try:
            addresses = _get_service_endpoints(kube=kube, namespace=namespace, name=name)
        except ApiException as e:
            raise HTTPException(status_code=502, detail=e.reason)

        attempts = 0
        for address in addresses:
            attempts += 1
            # AuthBridge serves config and status on port 9093
            url = f"http://{address}:9093/stats"
            try:
                data = await _fetch_authbridge_json(url)
                data["AuthBridge"] = True
                return data
            except Exception:
                # It isn't an error for an endpoint to be unreachable, only for all pods to be unreachable
                logger.info("Failed to talk to url %s; skipping", url, exc_info=True)

        if attempts == 0:
            raise HTTPException(status_code=404, detail=f"{name} not found")

        logger.info("Could not invoke any AuthBridge endpoints for %s/%s", namespace, name)
        # We return HTTP 200 if no pods respond - this might be a valid agent w/o AuthBridge
        return {"AuthBridge": False}


def _get_service_endpoints(kube: KubernetesService, namespace: str, name: str) -> List[str]:
    """
    Get addresses for a K8s service
    """

    addresses: list[str] = []
    endpoint_slices = kube.get_endpoint_slices(namespace=namespace, name=name)

    for endpoint_slice in endpoint_slices.get("items", []):
        for endpoint in endpoint_slice.get("endpoints", []):
            for address in endpoint.get("addresses", []):
                addresses.append(address)

    return addresses


async def _fetch_authbridge_json(url: str) -> dict:
    """
    Fetch JSON from an AuthBridge sidecar endpoint.

    Raises on HTTP errors, oversized responses, or non-dict payloads.
    """

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        logger.debug("Making HTTP request to %s", url)
        response = await client.get(url)
        response.raise_for_status()

        content = response.text
        if len(content) > 1024 * 1024:
            raise HTTPException(status_code=502, detail="File content too large (max 1MB)")

        data = json.loads(content)
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="File content not AuthBridge JSON")

        return data
