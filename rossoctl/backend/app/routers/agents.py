# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Agent API endpoints.

This module owns the agent read/delete endpoints and composes the rest of the
Agent API from focused submodules:

* ``agents_models``     -- request/response models
* ``agents_status``     -- workload readiness/status derivation
* ``agents_manifests``  -- Deployment/StatefulSet/Job/Sandbox/Service builders
* ``agents_skills``     -- linked-skill wiring and Shipwright build manifests
* ``agents_authbridge`` -- AuthBridge ConfigMaps/RBAC and identity endpoints
* ``agents_migration``  -- legacy Agent CRD -> workload migration
* ``agents_shipwright`` -- Shipwright build/buildrun endpoints
* ``agents_create``     -- agent creation
* ``agents_finalize``   -- finalization of source-built agents
* ``agents_env``        -- .env parsing/fetching helpers

Names those submodules define are re-exported here (see ``__all__``) because
other modules and the test suite import them from ``app.routers.agents``.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from kubernetes.client import ApiException

from app.core.auth import ROLE_OPERATOR, ROLE_VIEWER, require_roles
from app.core.config import settings
from app.core.constants import (
    AGENTRUNTIMES_PLURAL,
    AGENTS_PLURAL,
    CRD_GROUP,
    CRD_VERSION,
    RESOURCE_TYPE_AGENT,
    ROSSOCTL_DESCRIPTION_ANNOTATION,
    ROSSOCTL_TYPE_LABEL,
    ROSSOCTL_WORKLOAD_TYPE_LABEL,
    SHIPWRIGHT_BUILDRUNS_PLURAL,
    SHIPWRIGHT_BUILDS_PLURAL,
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
    WORKLOAD_TYPE_DEPLOYMENT,
    WORKLOAD_TYPE_JOB,
    WORKLOAD_TYPE_SANDBOX,
    WORKLOAD_TYPE_STATEFULSET,
)
from app.models.responses import (
    AgentListResponse,
    AgentSummary,
    DeleteResponse,
    ResourceLabels,
)
from app.models.shipwright import ShipwrightBuildConfig
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.services.shipwright import extract_buildrun_info, get_latest_buildrun
from app.services.shipwright_builds import collect_rossoctl_shipwright_builds
from app.utils.naming import K8S_NAME_MAX_LENGTH, K8S_NAME_PATTERN
from app.utils.routes import route_exists, sanitize_log

# --- Re-exports -------------------------------------------------------------
# Imported for backwards compatibility: other modules and tests import these
# from `app.routers.agents`. See __all__ at the bottom of this module.
from app.routers.agents_authbridge import (
    authbridge_router,
    _build_authbridge_runtime_yaml,
    _build_authbridge_runtime_yaml_fallback,
    _ensure_authbridge_configmaps,
    _ensure_authbridge_scc_rolebinding,
    _ensure_authproxy_routes,
    _fetch_authbridge_json,
    _get_authbridge_runtime_yaml,
    _get_service_endpoints,
)
from app.routers.agents_create import create_agent
from app.routers.agents_env import (
    env_router,
    BLOCKED_IP_RANGES,
    fetch_env_from_url,
    is_ip_blocked,
    parse_env_file,
)

# `finalize_shipwright_build` is re-exported here because
# app/services/reconciliation.py imports it from `app.routers.agents` inside a
# function body, and tests patch the string target
# "app.routers.agents.finalize_shipwright_build". That late import is what makes
# the patch effective -- do not promote it to a module-level import there.
from app.routers.agents_finalize import finalize_router, finalize_shipwright_build
from app.routers.agents_manifests import (
    CONTEXTS_ANNOTATION,
    build_container_resources,
    _agentruntime_supported_workload,
    _build_agentruntime_manifest,
    _build_common_annotations,
    _build_common_labels,
    _build_deployment_manifest,
    _build_env_vars,
    _build_job_manifest,
    _build_sandbox_manifest,
    _build_selector_labels,
    _build_service_manifest,
    _build_statefulset_manifest,
    _create_or_replace_service,
    _ensure_agentruntime,
    _resolve_context_mounts,
)
from app.routers.agents_migration import (
    migration_router,
    _build_deployment_from_agent_crd,
    _build_service_from_agent_crd,
    list_migratable_agents,
    migrate_agent,
    migrate_all_agents,
)
from app.routers.agents_models import (
    AgentShipwrightBuildInfoResponse,
    ConfigMapKeyRef,
    ContextAttachment,
    CreateAgentRequest,
    CreateAgentResponse,
    EnvVar,
    EnvVarSource,
    FetchEnvUrlRequest,
    FetchEnvUrlResponse,
    FinalizeShipwrightBuildRequest,
    ListMigratableAgentsResponse,
    MigratableAgentInfo,
    MigrateAgentRequest,
    MigrateAgentResponse,
    OutboundRoute,
    ParseEnvRequest,
    ParseEnvResponse,
    PersistentStorageConfig,
    SecretKeyRef,
    ServicePort,
)
from app.routers.agents_shipwright import (
    shipwright_router,
    get_shipwright_build_info,
    get_shipwright_build_status,
    get_shipwright_buildrun_status,
    list_agent_shipwright_builds,
    list_build_strategies,
    trigger_shipwright_buildrun,
)
from app.routers.agents_skills import (
    _build_agent_shipwright_build_manifest,
    _build_agent_shipwright_buildrun_manifest,
    _build_fetcher_scripts_data,
    _ensure_card_unsigned_configmap,
    _ensure_fetcher_scripts_cm,
    _get_external_skill_data,
    _get_linked_skill_mounts,
    _is_skill_external,
    _load_agent_skill_summaries,
)
from app.routers.agents_status import (
    _extract_labels,
    _format_timestamp,
    _get_deployment_description,
    _get_job_description,
    _get_job_status,
    _get_sandbox_description,
    _get_statefulset_description,
    _is_deployment_ready,
    _is_sandbox_ready,
    _is_statefulset_ready,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


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
    rossoctl.io/type=agent label.
    During migration period, also includes legacy Agent CRDs that haven't been
    migrated yet (controlled by enable_legacy_agent_crd setting).
    """
    try:
        label_selector = f"{ROSSOCTL_TYPE_LABEL}={RESOURCE_TYPE_AGENT}"

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

        # Query Sandboxes with agent label (feature-flagged)
        if settings.rossoctl_feature_flag_agent_sandbox:
            try:
                sandboxes = kube.list_sandboxes(
                    namespace=namespace,
                    label_selector=label_selector,
                )
                for sandbox in sandboxes:
                    metadata = sandbox.get("metadata", {})
                    name = metadata.get("name", "")
                    if name in agent_names:
                        logger.warning(
                            f"Duplicate agent name '{name}' detected: Sandbox skipped "
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
                            description=_get_sandbox_description(sandbox),
                            status=_is_sandbox_ready(sandbox),
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
                    logger.debug("Sandbox CRD not installed")
                elif e.status == 403:
                    logger.debug("Sandbox RBAC: insufficient permissions")
                else:
                    logger.warning(f"Failed to list Sandboxes: {e.reason}")

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
                        ROSSOCTL_DESCRIPTION_ANNOTATION, "No description"
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

        # Surface in-progress / failed Shipwright source builds that have no
        # workload yet. A source-built agent has no Deployment/StatefulSet/etc.
        # until its build Succeeds and is finalized, so without this it would be
        # invisible here while building or after a failure. Guarded so a
        # build-listing failure never breaks the core agent list.
        try:
            builds = collect_rossoctl_shipwright_builds(
                kube, [namespace], RESOURCE_TYPE_AGENT, logger
            )
            for build in builds:
                # Workload already exists (build Succeeded + finalized, or a
                # name collision) -> already listed above; skip to avoid dupes.
                if build.name in agent_names:
                    continue

                try:
                    buildruns = kube.list_custom_resources(
                        group=SHIPWRIGHT_CRD_GROUP,
                        version=SHIPWRIGHT_CRD_VERSION,
                        namespace=build.namespace,
                        plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                        label_selector=f"rossoctl.io/build-name={build.name}",
                    )
                except ApiException:
                    # Constant message only (CodeQL py/log-injection): never
                    # interpolate namespace / build name / API reason.
                    logger.warning("Failed to list BuildRuns for a Shipwright build")
                    buildruns = []

                # No BuildRun yet -> build just started; treat as "Building".
                phase = "Pending"
                latest = get_latest_buildrun(buildruns) if buildruns else None
                if latest:
                    phase = extract_buildrun_info(latest)["phase"]

                # Succeeded builds either already have a workload (listed above)
                # or are about to be finalized into one; don't surface them here.
                if phase == "Succeeded":
                    continue
                status = "Build Failed" if phase == "Failed" else "Building"

                agents.append(
                    AgentSummary(
                        name=build.name,
                        namespace=build.namespace,
                        description="Building from source",
                        status=status,
                        labels=_extract_labels({ROSSOCTL_TYPE_LABEL: build.resourceType}),
                        # Note that we may be building a non-deployment.  TODO record and retrieve build type.
                        workloadType=WORKLOAD_TYPE_DEPLOYMENT,
                        # Collector already formats this as an ISO string, so do
                        # not pass it through _format_timestamp (datetime-only).
                        createdAt=build.creationTimestamp,
                    )
                )
                agent_names.add(build.name)
        except ApiException:
            logger.warning("Failed to list Shipwright builds for agents", exc_info=True)

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
    namespace: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
    name: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
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

    # If still not found, try Sandbox (feature-flagged)
    if workload is None and settings.rossoctl_feature_flag_agent_sandbox:
        try:
            workload = kube.get_sandbox(namespace=namespace, name=name)
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
    if workload_type != WORKLOAD_TYPE_JOB:
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
        "workloadType": labels.get(ROSSOCTL_WORKLOAD_TYPE_LABEL, workload_type),
        "readyStatus": ready_status,  # Computed ready status for frontend
    }

    stored_contexts = annotations.get(CONTEXTS_ANNOTATION)
    if stored_contexts:
        try:
            response["contexts"] = json.loads(stored_contexts)
        except (TypeError, json.JSONDecodeError):
            logger.warning("Ignoring invalid context attachment annotation on agent")

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
    namespace: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
    name: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
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
    namespace: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
    name: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
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

    # Delete the Sandbox (if exists) and its PVCs
    if settings.rossoctl_feature_flag_agent_sandbox:
        try:
            kube.delete_sandbox(namespace=namespace, name=name)
            messages.append(f"Sandbox '{name}' deleted")
        except ApiException as e:
            if e.status == 404:
                logger.debug("Sandbox '%s' not found (may be other workload type)", safe_name)
            else:
                logger.warning("Failed to delete Sandbox '%s': %s", safe_name, e.reason)

        try:
            pvcs = kube.list_persistent_volume_claims(
                namespace=namespace,
                label_selector=f"app.kubernetes.io/name={name}",
            )
            for pvc_name in pvcs:
                kube.delete_persistent_volume_claim(namespace=namespace, name=pvc_name)
                messages.append(f"PVC '{pvc_name}' deleted")
        except ApiException as e:
            if e.status != 404:
                logger.warning("Failed to clean up PVCs for '%s': %s", safe_name, e.reason)

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
            label_selector=f"rossoctl.io/build-name={name}",
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


# Sub-routers are composed here, AFTER the four endpoints defined above, so that
# registration order matches the original single-file layout. Order is
# significant: FastAPI resolves routes in registration order, and these are the
# positions the endpoints occupied before the split.
#
# `list_agents` deliberately stays in this module: tests patch
# "app.routers.agents.settings", which only affects code whose module globals
# live here. Moving it would silently disable that patch.
router.include_router(migration_router)
router.include_router(shipwright_router)
# `create_agent` is registered directly rather than via a sub-router: its path is
# "" (exactly /agents), which FastAPI rejects on a prefix-less sub-router.
router.post(
    "", response_model=CreateAgentResponse, dependencies=[Depends(require_roles(ROLE_OPERATOR))]
)(create_agent)
router.include_router(finalize_router)
router.include_router(env_router)
router.include_router(authbridge_router)

# Names re-exported for backwards compatibility (imported by app.routers.tools,
# app.services.reconciliation, app.services.agent_env_defaults and the tests).
#
# The underscore-prefixed entries below are deliberate, not an oversight. Before
# this module was split up they were module-level privates of `agents.py`, and
# roughly twenty test modules still import them from `app.routers.agents` (e.g.
# `from app.routers.agents import _build_sandbox_manifest`); the tests also patch
# some of them by that dotted path. Listing them keeps those imports working and
# stops linters from stripping the "unused" re-export imports above. Removing an
# entry here will break the importing test rather than fail anything in this
# file, so prefer updating the importers first if you want one gone.
__all__ = [
    # router + endpoints owned by this module
    "router",
    "list_agents",
    "get_agent",
    "get_agent_route_status",
    "delete_agent",
    # endpoints defined in submodules
    "create_agent",
    "fetch_env_from_url",
    "finalize_shipwright_build",
    "get_shipwright_build_info",
    "get_shipwright_build_status",
    "get_shipwright_buildrun_status",
    "list_agent_shipwright_builds",
    "list_build_strategies",
    "list_migratable_agents",
    "migrate_agent",
    "migrate_all_agents",
    "parse_env_file",
    "trigger_shipwright_buildrun",
    # models
    "AgentShipwrightBuildInfoResponse",
    "ConfigMapKeyRef",
    "ContextAttachment",
    "CreateAgentRequest",
    "CreateAgentResponse",
    "EnvVar",
    "EnvVarSource",
    "FetchEnvUrlRequest",
    "FetchEnvUrlResponse",
    "FinalizeShipwrightBuildRequest",
    "ListMigratableAgentsResponse",
    "MigratableAgentInfo",
    "MigrateAgentRequest",
    "MigrateAgentResponse",
    "OutboundRoute",
    "ParseEnvRequest",
    "ParseEnvResponse",
    "PersistentStorageConfig",
    "SecretKeyRef",
    "ServicePort",
    # helpers
    "build_container_resources",
    "is_ip_blocked",
    "BLOCKED_IP_RANGES",
    "_agentruntime_supported_workload",
    "_build_agent_shipwright_build_manifest",
    "_build_agent_shipwright_buildrun_manifest",
    "_build_agentruntime_manifest",
    "_build_authbridge_runtime_yaml",
    "_build_authbridge_runtime_yaml_fallback",
    "_build_common_annotations",
    "_build_common_labels",
    "_build_deployment_from_agent_crd",
    "_build_deployment_manifest",
    "_build_env_vars",
    "_build_fetcher_scripts_data",
    "_build_job_manifest",
    "_build_sandbox_manifest",
    "_build_selector_labels",
    "_build_service_from_agent_crd",
    "_build_service_manifest",
    "_build_statefulset_manifest",
    "_create_or_replace_service",
    "_ensure_agentruntime",
    "_resolve_context_mounts",
    "_ensure_authbridge_configmaps",
    "_ensure_authbridge_scc_rolebinding",
    "_ensure_authproxy_routes",
    "_ensure_card_unsigned_configmap",
    "_ensure_fetcher_scripts_cm",
    "_extract_labels",
    "_fetch_authbridge_json",
    "_format_timestamp",
    "_get_authbridge_runtime_yaml",
    "_get_deployment_description",
    "_get_external_skill_data",
    "_get_job_description",
    "_get_job_status",
    "_get_linked_skill_mounts",
    "_get_sandbox_description",
    "_get_service_endpoints",
    "_get_statefulset_description",
    "_is_deployment_ready",
    "_is_sandbox_ready",
    "_is_skill_external",
    "_is_statefulset_ready",
    "_load_agent_skill_summaries",
    # models/constants re-exported for tests
    "ResourceLabels",
    "ShipwrightBuildConfig",
    "WORKLOAD_TYPE_DEPLOYMENT",
    "WORKLOAD_TYPE_JOB",
    "WORKLOAD_TYPE_SANDBOX",
    "WORKLOAD_TYPE_STATEFULSET",
]
