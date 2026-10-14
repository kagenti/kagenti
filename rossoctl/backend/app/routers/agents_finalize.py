# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Finalization of source-built agents.

Once a Shipwright BuildRun produces an image, this creates the actual workload
(Deployment/StatefulSet/Job/Sandbox), Service, route and AuthBridge wiring using
the config recorded on the Build.

Also invoked outside HTTP by ``app.services.reconciliation``, which imports
``finalize_shipwright_build`` from ``app.routers.agents`` inside a function body.

Split out of ``agents.py``; re-exported there for backwards compatibility.
Routes are attached to ``finalize_router`` and composed onto the main agents
router by ``agents.py`` -- see the ordering note there.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from kubernetes.client import ApiException

from app.core.auth import ROLE_OPERATOR, require_roles
from app.core.config import settings
from app.core.constants import (
    DEFAULT_IN_CLUSTER_PORT,
    DEFAULT_OFF_CLUSTER_PORT,
    RESOURCE_TYPE_AGENT,
    ROSSOCTL_TYPE_LABEL,
    SHIPWRIGHT_BUILDRUNS_PLURAL,
    SHIPWRIGHT_BUILDS_PLURAL,
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
    WORKLOAD_TYPE_DEPLOYMENT,
    WORKLOAD_TYPE_JOB,
    WORKLOAD_TYPE_SANDBOX,
    WORKLOAD_TYPE_STATEFULSET,
)
from app.routers.agents_authbridge import (
    _ensure_authbridge_configmaps,
    _ensure_authbridge_scc_rolebinding,
    _ensure_authproxy_routes,
)
from app.routers.agents_manifests import (
    _agentruntime_supported_workload,
    _build_deployment_manifest,
    _build_job_manifest,
    _build_sandbox_manifest,
    _build_service_manifest,
    _build_statefulset_manifest,
    _carryover_workload_labels,
    _create_or_replace_service,
    _ensure_agentruntime,
    _record_contexts,
    _resolve_context_mounts,
)
from app.routers.agents_models import (
    ContextAttachment,
    CreateAgentRequest,
    CreateAgentResponse,
    EnvVar,
    FinalizeShipwrightBuildRequest,
    OutboundRoute,
    PersistentStorageConfig,
    ServicePort,
)
from app.routers.agents_skills import (
    _ensure_card_unsigned_configmap,
    _ensure_fetcher_scripts_cm,
    _get_external_skill_data,
    _is_skill_external,
)
from app.services.agent_env_defaults import apply_agent_import_defaults
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.utils.naming import K8S_NAME_MAX_LENGTH, K8S_NAME_PATTERN
from app.utils.routes import create_route_for_agent_or_tool, select_route_port

logger = logging.getLogger(__name__)

finalize_router = APIRouter()


@finalize_router.post(
    "/{namespace}/{name}/finalize-shipwright-build",
    response_model=CreateAgentResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def finalize_shipwright_build(
    namespace: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
    name: str = Path(..., pattern=K8S_NAME_PATTERN, max_length=K8S_NAME_MAX_LENGTH),
    request: FinalizeShipwrightBuildRequest = Body(...),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> CreateAgentResponse:
    """
    Finalize a Shipwright build by creating the Deployment and Service.

    This endpoint should be called after the Shipwright BuildRun completes successfully.
    It retrieves the output image from the BuildRun status and creates the Deployment
    and Service for the agent.

    Agent configuration can be provided in the request body, or it will be read from
    the Build's rossoctl.io/agent-config annotation (stored during build creation).
    """
    logger.info(f"Finalizing Shipwright build '{name}' in namespace '{namespace}'")

    try:
        # Step 1: Get the latest BuildRun status to get the output image
        items = kube.list_custom_resources(
            group=SHIPWRIGHT_CRD_GROUP,
            version=SHIPWRIGHT_CRD_VERSION,
            namespace=namespace,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector=f"rossoctl.io/build-name={name}",
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
        agent_config_json = build_annotations.get("rossoctl.io/agent-config")
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
        if not workload_exists and settings.rossoctl_feature_flag_agent_sandbox:
            try:
                kube.get_sandbox(namespace=namespace, name=name)
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

        final_skills = request.skills
        if final_skills is None:
            final_skills = stored_config.get("skills")

        # Feature flag: reject skill linking if feature is disabled
        if final_skills and not settings.rossoctl_feature_flag_skills:
            raise HTTPException(
                status_code=400,
                detail="Skill linking is disabled. Enable ROSSOCTL_FEATURE_FLAG_SKILLS to use this feature.",
            )

        # Compute external skill data when feature is enabled (build path)
        build_local_skills: Optional[List[str]] = None
        build_ext_init_containers: List[Dict[str, Any]] = []
        build_ext_volumes: List[Dict[str, Any]] = []
        build_ext_volume_mounts: List[Dict[str, Any]] = []
        build_ext_skill_paths: List[str] = []

        if final_skills and settings.rossoctl_feature_flag_external_skills:
            _ensure_fetcher_scripts_cm(kube, namespace)
            (
                build_ext_init_containers,
                build_ext_volumes,
                build_ext_volume_mounts,
                build_ext_skill_paths,
            ) = _get_external_skill_data(kube, namespace, final_skills)
            build_local_skills = [
                s for s in final_skills if s and not _is_skill_external(kube, namespace, s)
            ]

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

        # Per-workload AuthBridge mode override
        final_auth_bridge_mode = (
            request.authBridgeMode
            if request.authBridgeMode is not None
            else stored_config.get("authBridgeMode")
        )

        # Per-workload mTLS mode (applies to AgentRuntime spec only;
        # the form stores it on the BuildRun annotation at submit time
        # and we read it back here so build-from-source agents inherit
        # the same setting as direct-image agents).
        final_mtls_mode = (
            request.mtlsMode if request.mtlsMode is not None else stored_config.get("mtlsMode")
        )

        # Per-workload TLS bridge (bool; None on the finalize request → inherit
        # the stored value). Same store-then-read-back flow as mtlsMode.
        final_tls_bridge_enabled = (
            request.tlsBridgeEnabled
            if request.tlsBridgeEnabled is not None
            else bool(stored_config.get("tlsBridgeEnabled"))
        )

        # AuthBridge layer-3 plugin composition (pluginPreset / plugins /
        # onError). Same store-then-read-back flow as mtlsMode so a
        # build-from-source agent inherits the plugin pipeline the user picked
        # at form-submit time (stashed on the BuildRun annotation).
        final_plugin_preset = (
            request.pluginPreset
            if request.pluginPreset is not None
            else stored_config.get("pluginPreset")
        )
        final_plugins = (
            request.plugins if request.plugins is not None else stored_config.get("plugins")
        )
        final_on_error = (
            request.onError if request.onError is not None else stored_config.get("onError")
        )

        # Persistent storage
        final_persistent_storage = request.persistentStorage
        if final_persistent_storage is None and stored_config.get("persistentStorage"):
            final_persistent_storage = PersistentStorageConfig(**stored_config["persistentStorage"])

        # Per-workload resource overrides. Same store-then-read-back flow as
        # mtlsMode: None on the finalize request → inherit whatever the form
        # stashed on the BuildRun annotation, else fall back to the platform
        # defaults inside the manifest builders.
        final_k8s_resource_limits = (
            request.k8sResourceLimits
            if request.k8sResourceLimits is not None
            else stored_config.get("k8sResourceLimits")
        )
        final_k8s_resource_requests = (
            request.k8sResourceRequests
            if request.k8sResourceRequests is not None
            else stored_config.get("k8sResourceRequests")
        )

        final_contexts = request.contexts
        if final_contexts is None and stored_config.get("contexts"):
            final_contexts = [ContextAttachment(**item) for item in stored_config["contexts"]]

        final_mcp_tool_name = (
            request.mcpToolName
            if request.mcpToolName is not None
            else stored_config.get("mcpToolName")
        )
        final_llm_preset = (
            request.llmPreset if request.llmPreset is not None else stored_config.get("llmPreset")
        )
        final_llm_model = (
            request.llmModel if request.llmModel is not None else stored_config.get("llmModel")
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
            skills=final_skills,
            servicePorts=final_service_ports,
            createHttpRoute=final_create_route,
            authBridgeEnabled=final_auth_bridge,
            spireEnabled=final_spire_enabled,
            authBridgeMode=final_auth_bridge_mode,
            mtlsMode=final_mtls_mode,
            tlsBridgeEnabled=final_tls_bridge_enabled,
            pluginPreset=final_plugin_preset,
            plugins=final_plugins,
            onError=final_on_error,
            outboundRoutes=final_outbound_routes,
            outboundPortsExclude=final_outbound_ports_exclude,
            inboundPortsExclude=final_inbound_ports_exclude,
            defaultOutboundPolicy=final_default_outbound_policy,
            persistentStorage=final_persistent_storage,
            contexts=final_contexts,
            gitPath=stored_config.get("gitPath")
            or build.get("spec", {}).get("source", {}).get("contextDir", ""),
            mcpToolName=final_mcp_tool_name,
            llmPreset=final_llm_preset,
            llmModel=final_llm_model,
            k8sResourceLimits=final_k8s_resource_limits,
            k8sResourceRequests=final_k8s_resource_requests,
        )
        agent_request = apply_agent_import_defaults(agent_request, kube)
        context_volumes, context_mounts, resolved_contexts = await _resolve_context_mounts(
            namespace, final_contexts, final_workload_type
        )
        build_ext_volumes.extend(context_volumes)
        build_ext_volume_mounts.extend(context_mounts)

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
                description=f"Agent '{name}' deployed from UI.",
                skill_names=final_skills or [],
            )

        # Create workload based on workloadType
        if final_workload_type == WORKLOAD_TYPE_DEPLOYMENT:
            workload_manifest = _build_deployment_manifest(
                request=agent_request,
                image=container_image,
                shipwright_build_name=name,
                local_skills=build_local_skills,
                ext_init_containers=build_ext_init_containers,
                ext_volumes=build_ext_volumes,
                ext_volume_mounts=build_ext_volume_mounts,
                ext_skill_paths=build_ext_skill_paths,
            )
            _record_contexts(workload_manifest, resolved_contexts)
            # Carry forward build-time rossoctl.io/* labels, minus rossoctl.io/type
            # (the operator sets that via the AgentRuntime CR below; a raw
            # Deployment carrying it is rejected by the agent-label-protection
            # policy -- issue #2489).
            carryover_labels = _carryover_workload_labels(build_labels)
            workload_manifest["metadata"]["labels"].update(carryover_labels)
            # Also update pod template labels
            workload_manifest["spec"]["template"]["metadata"]["labels"].update(carryover_labels)
            kube.create_deployment(namespace=namespace, body=workload_manifest)
            logger.info(
                f"Created Deployment '{name}' with image '{container_image}' in namespace '{namespace}'"
            )
        elif final_workload_type == WORKLOAD_TYPE_STATEFULSET:
            workload_manifest = _build_statefulset_manifest(
                request=agent_request,
                image=container_image,
                shipwright_build_name=name,
                local_skills=build_local_skills,
                ext_init_containers=build_ext_init_containers,
                ext_volumes=build_ext_volumes,
                ext_volume_mounts=build_ext_volume_mounts,
                ext_skill_paths=build_ext_skill_paths,
            )
            _record_contexts(workload_manifest, resolved_contexts)
            # Carry forward build-time rossoctl.io/* labels, minus rossoctl.io/type
            # (see the Deployment branch above -- issue #2489).
            carryover_labels = _carryover_workload_labels(build_labels)
            workload_manifest["metadata"]["labels"].update(carryover_labels)
            # Also update pod template labels
            workload_manifest["spec"]["template"]["metadata"]["labels"].update(carryover_labels)
            kube.create_statefulset(namespace=namespace, body=workload_manifest)
            logger.info(
                f"Created StatefulSet '{name}' with image '{container_image}' in namespace '{namespace}'"
            )
        elif final_workload_type == WORKLOAD_TYPE_JOB:
            workload_manifest = _build_job_manifest(
                request=agent_request,
                image=container_image,
                shipwright_build_name=name,
                local_skills=build_local_skills,
                ext_init_containers=build_ext_init_containers,
                ext_volumes=build_ext_volumes,
                ext_volume_mounts=build_ext_volume_mounts,
                ext_skill_paths=build_ext_skill_paths,
            )
            _record_contexts(workload_manifest, resolved_contexts)
            # Carry forward build-time rossoctl.io/* labels, minus rossoctl.io/type.
            # A Job isn't matched by the agent-label-protection policy (deployments
            # /statefulsets only), but we keep the same rule for consistency and to
            # avoid stamping a label the operator owns -- issue #2489.
            carryover_labels = _carryover_workload_labels(build_labels)
            workload_manifest["metadata"]["labels"].update(carryover_labels)
            # Also update pod template labels
            workload_manifest["spec"]["template"]["metadata"]["labels"].update(carryover_labels)
            kube.create_job(namespace=namespace, body=workload_manifest)
            logger.info(
                f"Created Job '{name}' with image '{container_image}' in namespace '{namespace}'"
            )
        elif final_workload_type == WORKLOAD_TYPE_SANDBOX:
            sandbox_manifest = _build_sandbox_manifest(
                request=agent_request,
                image=container_image,
                shipwright_build_name=name,
                local_skills=build_local_skills,
                ext_init_containers=build_ext_init_containers,
                ext_volumes=build_ext_volumes,
                ext_volume_mounts=build_ext_volume_mounts,
                ext_skill_paths=build_ext_skill_paths,
            )
            _record_contexts(sandbox_manifest, resolved_contexts)
            rossoctl_build_labels = {
                k: v
                for k, v in build_labels.items()
                if k.startswith(settings.rossoctl_label_prefix)
            }
            sandbox_manifest["metadata"]["labels"].update(rossoctl_build_labels)
            sandbox_manifest["spec"]["podTemplate"]["metadata"]["labels"].update(
                rossoctl_build_labels
            )
            kube.create_sandbox(namespace=namespace, body=sandbox_manifest)
            logger.info(f"Created Sandbox '{name}' in namespace '{namespace}' from build")

        # Create Service via the shared _create_or_replace_service helper
        # (skips only for Job workloads).
        service_manifest = _build_service_manifest(agent_request)
        # Carry forward build-time rossoctl.io/* labels onto the Service so
        # downstream label-based selectors / queries match. Use
        # settings.rossoctl_label_prefix (the project-wide constant) instead
        # of the literal "rossoctl.io/" so CodeQL's URL-substring rule
        # doesn't pattern-match the literal — see line 3626 above for the
        # same idiom.
        service_manifest["metadata"]["labels"].update(
            {k: v for k, v in build_labels.items() if k.startswith(settings.rossoctl_label_prefix)}
        )
        _create_or_replace_service(kube, namespace, name, service_manifest, final_workload_type)

        # Create AgentRuntime CR so the per-agent AuthBridge config is applied.
        # Sandbox is included (targetRef -> agents.x-k8s.io Sandbox); only Job is
        # excluded. Agents only — tools don't need sidecar injection.
        resource_type = build_labels.get(ROSSOCTL_TYPE_LABEL, RESOURCE_TYPE_AGENT)
        if (
            _agentruntime_supported_workload(final_workload_type)
            and resource_type == RESOURCE_TYPE_AGENT
        ):
            _ensure_agentruntime(
                kube=kube,
                name=name,
                namespace=namespace,
                workload_type=final_workload_type,
                auth_bridge_mode=final_auth_bridge_mode,
                mtls_mode=final_mtls_mode,
                tls_bridge_enabled=final_tls_bridge_enabled,
                plugin_preset=final_plugin_preset,
                plugins=final_plugins,
                on_error=final_on_error,
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
