# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Utility functions for creating HTTPRoutes (Kubernetes) and Routes (OpenShift).
"""

import logging

from kubernetes.client import ApiException

from app.services.kubernetes import KubernetesService
from app.core.config import settings

logger = logging.getLogger(__name__)


def detect_platform(kube: KubernetesService) -> str:
    """
    Detect if running on OpenShift or regular Kubernetes.

    Returns:
        'openshift' if route.openshift.io API is available, 'kubernetes' otherwise
    """
    try:
        # Try to list routes API groups
        # OpenShift exposes route.openshift.io/v1
        from kubernetes import client

        # Create API client
        api_instance = client.ApiClient(kube.client.api_client.configuration)

        # Get available API groups
        with api_instance as api:
            api_response = api.call_api(
                "/apis", "GET", response_type="object", _return_http_data_only=True
            )

        groups = api_response.get("groups", [])
        logger.debug(f"Available API groups: {[g.get('name') for g in groups]}")

        for group in groups:
            if group.get("name") == "route.openshift.io":
                logger.info("Detected OpenShift platform (route.openshift.io API found)")
                return "openshift"

        logger.info("Detected Kubernetes platform (no route.openshift.io API)")
        return "kubernetes"
    except Exception as e:
        logger.warning(f"Error detecting platform: {e}, defaulting to kubernetes")
        return "kubernetes"


def create_httproute(
    kube: KubernetesService,
    name: str,
    namespace: str,
    service_name: str,
    service_port: int,
    parent_ref_name: str = "http",
    parent_ref_namespace: str = "kagenti-system",
) -> None:
    """
    Create an HTTPRoute for Kubernetes Gateway API.

    Args:
        kube: Kubernetes service instance
        name: Name of the HTTPRoute
        namespace: Namespace for the HTTPRoute
        service_name: Name of the backend service
        service_port: Port of the backend service
        parent_ref_name: Name of the Gateway (default: "http")
        parent_ref_namespace: Namespace of the Gateway (default: "kagenti-system")
    """
    hostname = f"{name}.{namespace}.{settings.domain_name}"

    httproute_manifest = {
        "apiVersion": "gateway.networking.k8s.io/v1",
        "kind": "HTTPRoute",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": name,
            },
        },
        "spec": {
            "parentRefs": [
                {
                    "name": parent_ref_name,
                    "namespace": parent_ref_namespace,
                }
            ],
            "hostnames": [hostname],
            "rules": [
                {
                    "backendRefs": [
                        {
                            "name": service_name,
                            "port": service_port,
                        }
                    ]
                }
            ],
        },
    }

    try:
        kube.create_custom_resource(
            group="gateway.networking.k8s.io",
            version="v1",
            namespace=namespace,
            plural="httproutes",
            body=httproute_manifest,
        )
        logger.info(
            f"Created HTTPRoute '{name}' in namespace '{namespace}' with hostname '{hostname}'"
        )
    except ApiException as e:
        if e.status == 409:
            logger.warning(f"HTTPRoute '{name}' already exists in namespace '{namespace}'")
        else:
            logger.error(f"Failed to create HTTPRoute: {e}")
            raise


def create_openshift_route(
    kube: KubernetesService,
    name: str,
    namespace: str,
    service_name: str,
    service_port: int,
) -> None:
    """
    Create an OpenShift Route.

    Args:
        kube: Kubernetes service instance
        name: Name of the Route
        namespace: Namespace for the Route
        service_name: Name of the backend service
        service_port: Port of the backend service
    """
    route_manifest = {
        "apiVersion": "route.openshift.io/v1",
        "kind": "Route",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "annotations": {
                "openshift.io/host.generated": "true",
            },
        },
        "spec": {
            "path": "/",
            "port": {
                "targetPort": service_port,
            },
            "to": {
                "kind": "Service",
                "name": service_name,
            },
            "wildcardPolicy": "None",
            "tls": {
                "termination": "edge",
                "insecureEdgeTerminationPolicy": "Redirect",
            },
        },
    }

    try:
        kube.create_custom_resource(
            group="route.openshift.io",
            version="v1",
            namespace=namespace,
            plural="routes",
            body=route_manifest,
        )
        logger.info(f"Created OpenShift Route '{name}' in namespace '{namespace}'")
    except ApiException as e:
        if e.status == 409:
            logger.warning(f"Route '{name}' already exists in namespace '{namespace}'")
        else:
            logger.error(f"Failed to create Route: {e}")
            raise


def route_exists(
    kube: KubernetesService,
    name: str,
    namespace: str,
) -> bool:
    """
    Check if an HTTPRoute or Route exists for the given resource.

    Args:
        kube: Kubernetes service instance
        name: Name of the route
        namespace: Namespace for the route

    Returns:
        True if HTTPRoute or Route exists, False otherwise
    """
    platform = detect_platform(kube)

    try:
        if platform == "openshift":
            # Check for OpenShift Route
            kube.get_custom_resource(
                group="route.openshift.io",
                version="v1",
                namespace=namespace,
                plural="routes",
                name=name,
            )
            return True
        else:
            # Check for HTTPRoute
            kube.get_custom_resource(
                group="gateway.networking.k8s.io",
                version="v1",
                namespace=namespace,
                plural="httproutes",
                name=name,
            )
            return True
    except ApiException as e:
        if e.status == 404:
            return False
        # For other errors, log and return False
        logger.warning(f"Error checking route existence: {e}")
        return False
    except Exception as e:
        logger.warning(f"Unexpected error checking route existence: {e}")
        return False


def create_route_for_agent_or_tool(
    kube: KubernetesService,
    name: str,
    namespace: str,
    service_name: str,
    service_port: int,
) -> None:
    """
    Create an HTTPRoute or Route based on the platform.

    Auto-detects the platform and creates the appropriate resource.

    Args:
        kube: Kubernetes service instance
        name: Name of the route
        namespace: Namespace for the route
        service_name: Name of the backend service
        service_port: Port of the backend service
    """
    logger.info(
        f"Creating route for {name} in namespace {namespace}, "
        f"service={service_name}, port={service_port}"
    )

    platform = detect_platform(kube)
    logger.info(f"Detected platform: {platform}")

    if platform == "openshift":
        create_openshift_route(kube, name, namespace, service_name, service_port)
    else:
        create_httproute(kube, name, namespace, service_name, service_port)
