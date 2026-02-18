# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Shared Shipwright build service.

This module provides common utilities for Shipwright builds that are used
by both agent and tool routers. It handles:
- Build manifest generation
- BuildRun manifest generation
- Build strategy selection
- BuildRun status parsing
- Resource configuration extraction from annotations
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.constants import (
    APP_KUBERNETES_IO_CREATED_BY,
    APP_KUBERNETES_IO_NAME,
    KAGENTI_UI_CREATOR_LABEL,
    KAGENTI_OPERATOR_LABEL_NAME,
    KAGENTI_TYPE_LABEL,
    KAGENTI_PROTOCOL_LABEL,
    KAGENTI_FRAMEWORK_LABEL,
    RESOURCE_TYPE_AGENT,
    RESOURCE_TYPE_TOOL,
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
    SHIPWRIGHT_GIT_SECRET_NAME,
    SHIPWRIGHT_DEFAULT_DOCKERFILE,
    SHIPWRIGHT_DEFAULT_TIMEOUT,
    SHIPWRIGHT_DEFAULT_RETENTION_SUCCEEDED,
    SHIPWRIGHT_DEFAULT_RETENTION_FAILED,
    SHIPWRIGHT_STRATEGY_INSECURE,
    SHIPWRIGHT_STRATEGY_SECURE,
    DEFAULT_INTERNAL_REGISTRY,
)
from app.models.shipwright import (
    ResourceType,
    ShipwrightBuildConfig,
    BuildSourceConfig,
    BuildOutputConfig,
    ResourceConfigFromBuild,
)

logger = logging.getLogger(__name__)


def select_build_strategy(registry_url: str, requested_strategy: Optional[str] = None) -> str:
    """
    Select the appropriate build strategy based on the registry.

    For internal registries (svc.cluster.local), uses the insecure push strategy.
    For external registries with TLS, uses the secure strategy.

    Args:
        registry_url: The registry URL to push images to
        requested_strategy: Optional explicitly requested strategy

    Returns:
        The build strategy name to use
    """
    is_internal_registry = (
        registry_url == DEFAULT_INTERNAL_REGISTRY or "svc.cluster.local" in registry_url
    )

    # If a strategy was explicitly requested, use it unless it's secure for internal registry
    if requested_strategy:
        if is_internal_registry and requested_strategy == SHIPWRIGHT_STRATEGY_SECURE:
            # Override to insecure for internal registries
            logger.debug(
                f"Overriding secure strategy to insecure for internal registry: {registry_url}"
            )
            return SHIPWRIGHT_STRATEGY_INSECURE
        return requested_strategy

    # Default strategy based on registry type
    return SHIPWRIGHT_STRATEGY_INSECURE if is_internal_registry else SHIPWRIGHT_STRATEGY_SECURE


def build_shipwright_build_manifest(
    name: str,
    namespace: str,
    resource_type: ResourceType,
    source_config: BuildSourceConfig,
    output_config: BuildOutputConfig,
    build_config: Optional[ShipwrightBuildConfig] = None,
    resource_config: Optional[Dict[str, Any]] = None,
    protocol: str = "a2a",
    framework: str = "LangGraph",
) -> Dict[str, Any]:
    """
    Build a Shipwright Build CRD manifest for building from source.

    Uses ClusterBuildStrategy (buildah or buildah-insecure-push) to build the container image.
    Stores resource configuration in annotations for later use when finalizing the build.

    Args:
        name: Name for the Build resource
        namespace: Kubernetes namespace
        resource_type: Type of resource (AGENT or TOOL)
        source_config: Git source configuration
        output_config: Output image configuration
        build_config: Optional Shipwright build configuration
        resource_config: Optional resource configuration to store in annotations
        protocol: Protocol label (a2a, mcp, etc.)
        framework: Framework label (LangGraph, CrewAI, etc.)

    Returns:
        Dict containing the Build manifest
    """
    # Use defaults if not provided
    if build_config is None:
        build_config = ShipwrightBuildConfig()

    # Determine output image
    output_image = f"{output_config.registry}/{output_config.imageName}:{output_config.imageTag}"

    # Select build strategy
    build_strategy = select_build_strategy(output_config.registry, build_config.buildStrategy)

    # Determine the annotation key based on resource type
    type_value = resource_type.value
    config_annotation_key = (
        "kagenti.io/agent-config"
        if resource_type == ResourceType.AGENT
        else "kagenti.io/tool-config"
    )

    # Build resource configuration to store in annotation
    # This will be used when finalizing the build to create the Agent/MCPServer CRD
    if resource_config is None:
        resource_config = {}

    # Ensure protocol and framework are in the resource config
    resource_config.setdefault("protocol", protocol)
    resource_config.setdefault("framework", framework)

    manifest: Dict[str, Any] = {
        "apiVersion": f"{SHIPWRIGHT_CRD_GROUP}/{SHIPWRIGHT_CRD_VERSION}",
        "kind": "Build",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                APP_KUBERNETES_IO_CREATED_BY: KAGENTI_UI_CREATOR_LABEL,
                APP_KUBERNETES_IO_NAME: KAGENTI_OPERATOR_LABEL_NAME,
                KAGENTI_TYPE_LABEL: type_value,
                KAGENTI_PROTOCOL_LABEL: protocol,
                KAGENTI_FRAMEWORK_LABEL: framework,
            },
            "annotations": {
                config_annotation_key: json.dumps(resource_config),
            },
        },
        "spec": {
            "source": {
                "type": "Git",
                "git": {
                    "url": source_config.gitUrl,
                    "revision": source_config.gitRevision,
                },
                "contextDir": source_config.contextDir,
            },
            "strategy": {
                "name": build_strategy,
                "kind": "ClusterBuildStrategy",
            },
            "paramValues": [
                {
                    "name": "dockerfile",
                    "value": build_config.dockerfile,
                },
            ],
            "output": {
                "image": output_image,
            },
            "timeout": build_config.buildTimeout,
            "retention": {
                "succeededLimit": SHIPWRIGHT_DEFAULT_RETENTION_SUCCEEDED,
                "failedLimit": SHIPWRIGHT_DEFAULT_RETENTION_FAILED,
            },
        },
    }

    # Add clone secret for private git repos
    if source_config.gitSecretName:
        manifest["spec"]["source"]["git"]["cloneSecret"] = source_config.gitSecretName

    # Add build arguments if specified
    if build_config.buildArgs:
        manifest["spec"]["paramValues"].append(
            {
                "name": "build-args",
                "values": [{"value": arg} for arg in build_config.buildArgs],
            }
        )

    # Add push secret for external registries
    if output_config.pushSecretName:
        manifest["spec"]["output"]["pushSecret"] = output_config.pushSecretName

    return manifest


def build_shipwright_buildrun_manifest(
    build_name: str,
    namespace: str,
    resource_type: ResourceType,
    labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Build a Shipwright BuildRun CRD manifest to trigger a build.

    Uses generateName to create unique BuildRun names.

    Args:
        build_name: Name of the Build to run
        namespace: Kubernetes namespace
        resource_type: Type of resource (AGENT or TOOL)
        labels: Optional additional labels to add

    Returns:
        Dict containing the BuildRun manifest
    """
    base_labels = {
        APP_KUBERNETES_IO_CREATED_BY: KAGENTI_UI_CREATOR_LABEL,
        "kagenti.io/build-name": build_name,
        KAGENTI_TYPE_LABEL: resource_type.value,
    }
    if labels:
        base_labels.update(labels)

    return {
        "apiVersion": f"{SHIPWRIGHT_CRD_GROUP}/{SHIPWRIGHT_CRD_VERSION}",
        "kind": "BuildRun",
        "metadata": {
            "generateName": f"{build_name}-run-",
            "namespace": namespace,
            "labels": base_labels,
        },
        "spec": {
            "build": {
                "name": build_name,
            },
        },
    }


def parse_buildrun_phase(conditions: List[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """
    Parse BuildRun conditions to determine the build phase.

    Args:
        conditions: List of condition dicts from BuildRun status

    Returns:
        Tuple of (phase, failure_message)
        - phase: "Pending", "Running", "Succeeded", or "Failed"
        - failure_message: Error message if failed, None otherwise
    """
    phase = "Pending"
    failure_message = None

    for cond in conditions:
        if cond.get("type") == "Succeeded":
            status = cond.get("status")
            if status == "True":
                phase = "Succeeded"
            elif status == "False":
                phase = "Failed"
                failure_message = cond.get("message")
            else:
                # status is "Unknown" - build is still running
                phase = "Running"
            break

    return phase, failure_message


def extract_resource_config_from_build(
    build: Dict[str, Any],
    resource_type: ResourceType,
) -> Optional[ResourceConfigFromBuild]:
    """
    Extract resource configuration from a Build's annotations.

    The configuration is stored in either kagenti.io/agent-config or
    kagenti.io/tool-config annotation as JSON.

    Args:
        build: The Build resource dict
        resource_type: Type of resource (AGENT or TOOL)

    Returns:
        ResourceConfigFromBuild if found and valid, None otherwise
    """
    annotations = build.get("metadata", {}).get("annotations", {})

    # Determine the annotation key based on resource type
    config_key = (
        "kagenti.io/agent-config"
        if resource_type == ResourceType.AGENT
        else "kagenti.io/tool-config"
    )

    config_json = annotations.get(config_key)
    if not config_json:
        return None

    try:
        config_dict = json.loads(config_json)
        return ResourceConfigFromBuild(**config_dict)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse resource config from annotation: {e}")
        return None


def get_latest_buildrun(
    buildruns: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Get the most recent BuildRun from a list.

    Args:
        buildruns: List of BuildRun resources

    Returns:
        The most recent BuildRun, or None if list is empty
    """
    if not buildruns:
        return None

    # Sort by creation timestamp and get the most recent
    buildruns.sort(
        key=lambda x: x.get("metadata", {}).get("creationTimestamp", ""),
        reverse=True,
    )
    return buildruns[0]


def extract_buildrun_info(
    buildrun: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract relevant information from a BuildRun resource.

    Args:
        buildrun: The BuildRun resource dict

    Returns:
        Dict containing extracted BuildRun info including:
        - name, phase, startTime, completionTime
        - outputImage, outputDigest
        - failureMessage (if failed)
    """
    metadata = buildrun.get("metadata", {})
    status = buildrun.get("status", {})
    conditions = status.get("conditions", [])

    # Parse phase
    phase, failure_message = parse_buildrun_phase(conditions)

    # Get output info
    output = status.get("output", {})

    return {
        "name": metadata.get("name"),
        "phase": phase,
        "startTime": status.get("startTime"),
        "completionTime": status.get("completionTime"),
        "outputImage": output.get("image"),
        "outputDigest": output.get("digest"),
        "failureMessage": failure_message,
    }


def is_build_succeeded(buildrun: Dict[str, Any]) -> bool:
    """
    Check if a BuildRun has succeeded.

    Args:
        buildrun: The BuildRun resource dict

    Returns:
        True if the build succeeded, False otherwise
    """
    conditions = buildrun.get("status", {}).get("conditions", [])
    phase, _ = parse_buildrun_phase(conditions)
    return phase == "Succeeded"


def get_output_image_from_buildrun(
    buildrun: Dict[str, Any],
    fallback_build: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Get the output image from a BuildRun status.

    Falls back to Build spec if not available in BuildRun status.

    Args:
        buildrun: The BuildRun resource dict
        fallback_build: Optional Build resource to fall back to

    Returns:
        Tuple of (output_image, output_digest)
    """
    output = buildrun.get("status", {}).get("output", {})
    output_image = output.get("image")
    output_digest = output.get("digest")

    # Fallback to Build spec if needed
    if not output_image and fallback_build:
        output_image = fallback_build.get("spec", {}).get("output", {}).get("image")

    return output_image, output_digest
