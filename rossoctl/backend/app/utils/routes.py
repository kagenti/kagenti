# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Utility functions for creating HTTPRoutes (Kubernetes) and Routes (OpenShift).
"""

import logging
from typing import List, Optional, Tuple

from kubernetes.client import ApiException

from app.services.kubernetes import KubernetesService
from app.core.config import settings
from app.core.constants import (
    AGENTRUNTIMES_PLURAL,
    CRD_GROUP,
    CRD_VERSION,
    DEFAULT_IN_CLUSTER_PORT,
    DEFAULT_OFF_CLUSTER_PORT,
)

logger = logging.getLogger(__name__)


def sanitize_log(value: str) -> str:
    """Strip newlines and control characters to prevent log injection (CWE-117)."""
    return str(value).replace("\n", "").replace("\r", "").replace("\x00", "")


def select_route_port(
    service_ports,
    default_port: int = DEFAULT_IN_CLUSTER_PORT,
) -> int:
    """Select the best port for an HTTPRoute/Route from service port configuration.

    Prefers the port named "http", falls back to the first port, then to the default.
    Accepts both ServicePort model objects (with .name/.port attributes) and dicts.

    Args:
        service_ports: List of service port configs (ServicePort objects or dicts).
        default_port: Port to use when no service ports are configured.

    Returns:
        The selected port number.
    """
    if not service_ports:
        return default_port

    def _get(sp, field):
        """Get a field from a ServicePort object or dict."""
        if isinstance(sp, dict):
            return sp.get(field)
        return getattr(sp, field, None)

    # Prefer port named "http"
    for sp in service_ports:
        if _get(sp, "name") == "http":
            port = _get(sp, "port")
            if port is not None:
                return port

    # Fall back to first port
    first_port = _get(service_ports[0], "port")
    if first_port is not None:
        return first_port

    return default_port


def detect_platform(kube: KubernetesService) -> str:
    """
    Detect if running on OpenShift or regular Kubernetes.

    Returns:
        'openshift' if route.openshift.io API is available, 'kubernetes' otherwise
    """
    try:
        if kube.api_group_exists("route.openshift.io"):
            logger.info("Detected OpenShift platform (route.openshift.io API found)")
            return "openshift"
        logger.info("Detected Kubernetes platform (no route.openshift.io API)")
        return "kubernetes"
    except Exception as e:
        logger.warning("Error detecting platform: %s, defaulting to kubernetes", e)
        return "kubernetes"


def create_httproute(
    kube: KubernetesService,
    name: str,
    namespace: str,
    service_name: str,
    service_port: int,
    parent_ref_name: str = "http",
    parent_ref_namespace: str = "rossoctl-system",
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
        parent_ref_namespace: Namespace of the Gateway (default: "rossoctl-system")
    """
    name = sanitize_log(name)
    namespace = sanitize_log(namespace)
    service_name = sanitize_log(service_name)
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
            "Created HTTPRoute '%s' in namespace '%s' with hostname '%s'",
            name,
            namespace,
            hostname,
        )
    except ApiException as e:
        if e.status == 409:
            logger.warning("HTTPRoute '%s' already exists in namespace '%s'", name, namespace)
        else:
            logger.error("Failed to create HTTPRoute: %s", e)
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
    name = sanitize_log(name)
    namespace = sanitize_log(namespace)
    service_name = sanitize_log(service_name)
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
        logger.info("Created OpenShift Route '%s' in namespace '%s'", name, namespace)
    except ApiException as e:
        if e.status == 409:
            logger.warning("Route '%s' already exists in namespace '%s'", name, namespace)
        else:
            logger.error("Failed to create Route: %s", e)
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
    name = sanitize_log(name)
    namespace = sanitize_log(namespace)
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
        logger.warning("Error checking route existence: %s", e)
        return False
    except Exception as e:
        logger.warning("Unexpected error checking route existence: %s", e)
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
    name = sanitize_log(name)
    namespace = sanitize_log(namespace)
    service_name = sanitize_log(service_name)
    logger.info(
        "Creating route for %s in namespace %s, service=%s, port=%s",
        name,
        namespace,
        service_name,
        service_port,
    )

    platform = detect_platform(kube)
    logger.info("Detected platform: %s", platform)

    if platform == "openshift":
        create_openshift_route(kube, name, namespace, service_name, service_port)
    else:
        create_httproute(kube, name, namespace, service_name, service_port)


def lookup_service_port(
    service_name: str,
    namespace: str,
    kube: KubernetesService,
    default_port: int,
) -> int:
    """Look up the first port of a K8s Service, falling back to *default_port*."""
    try:
        service = kube.get_service(namespace=namespace, name=service_name)
        ports = service.get("spec", {}).get("ports", [])
        if ports:
            return ports[0].get("port", default_port)
    except ApiException:
        logger.warning(
            "Could not look up Service %s in %s, using default port",
            sanitize_log(service_name),
            sanitize_log(namespace),
        )
    return default_port


def _lookup_sandbox_port(
    name: str,
    namespace: str,
    kube: KubernetesService,
) -> Optional[int]:
    """Return the container port advertised by a Sandbox's pod template, or None.

    Sandbox controllers create a headless Service with no ports
    (kubernetes-sigs/agent-sandbox#154), so callers must discover the port from
    the workload itself. Prefer containerPort, fall back to the PORT env var.
    """
    try:
        sandbox = kube.get_sandbox(namespace=namespace, name=name)
    except ApiException:
        return None
    containers = (
        sandbox.get("spec", {}).get("podTemplate", {}).get("spec", {}).get("containers", [])
    )
    if not containers:
        return None
    ports = containers[0].get("ports") or []
    if ports and isinstance(ports[0].get("containerPort"), int):
        return ports[0]["containerPort"]
    for env in containers[0].get("env", []) or []:
        if env.get("name") == "PORT":
            try:
                return int(env.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def resolve_agent_url(name: str, namespace: str, kube: KubernetesService) -> str:
    """Resolve the URL for an agent by discovering its port.

    1. If the Service exposes ports (Deployment/StatefulSet/Job path), use the
       first port.
    2. Else, if a Sandbox owns this name, read the port from its pod template
       (Sandbox-created Services are headless with no ports).
    3. Otherwise fall back to DEFAULT_OFF_CLUSTER_PORT, which matches both the
       default external port and the default the sandbox builder writes.
    """
    port = lookup_service_port(name, namespace, kube, default_port=0)
    if port:
        return get_agent_url(name, namespace, port)

    sandbox_port = _lookup_sandbox_port(name, namespace, kube)
    if sandbox_port is not None:
        return get_agent_url(name, namespace, sandbox_port)

    return get_agent_url(name, namespace, DEFAULT_OFF_CLUSTER_PORT)


def get_agent_url(name: str, namespace: str, port: int = DEFAULT_OFF_CLUSTER_PORT) -> str:
    """Get the URL for an A2A agent.

    Returns different URL formats based on deployment context:
    - In-cluster: http://{name}.{namespace}.svc.cluster.local:{port}
    - Off-cluster (local dev): http://{name}.{namespace}.{domain}:{port}
    """
    name = sanitize_log(name)
    namespace = sanitize_log(namespace)
    if settings.is_running_in_cluster:
        return f"http://{name}.{namespace}.svc.cluster.local:{port}"
    else:
        domain = settings.domain_name
        return f"http://{name}.{namespace}.{domain}:{port}"


def rollback_workload_resources(
    kube: KubernetesService,
    namespace: str,
    created: List[Tuple[str, str]],
) -> None:
    """Best-effort delete of resources created earlier in the same create call.

    Shared by the image-deployment paths of create_agent and create_tool to avoid
    leaking persistent resources when a later creation step fails. ``created`` is a
    list of ``(kind, name)`` tuples in creation order; this deletes them in reverse
    and swallows every error (including 404) so a rollback failure never masks the
    original exception.

    Only workload / Service / route / AgentRuntime resources created by the call are
    tracked — shared or idempotent resources (ServiceAccount, AuthBridge ConfigMaps,
    SCC RoleBinding, skill-fetcher ConfigMap) are intentionally left in place.

    Supported ``kind`` values: ``Deployment``, ``StatefulSet``, ``Job``, ``Sandbox``
    (whose PVCs are also removed), ``Service``, ``AgentRuntime``, ``HTTPRoute``,
    ``Route``.
    """
    for kind, res_name in reversed(created):
        try:
            if kind == "Deployment":
                kube.delete_deployment(namespace=namespace, name=res_name)
            elif kind == "StatefulSet":
                kube.delete_statefulset(namespace=namespace, name=res_name)
            elif kind == "Job":
                kube.delete_job(namespace=namespace, name=res_name)
            elif kind == "Sandbox":
                kube.delete_sandbox(namespace=namespace, name=res_name)
                # The Sandbox's PVCs are the highest-cost orphan; delete them too
                # (mirrors delete_agent's label-selector cleanup).
                for pvc_name in kube.list_persistent_volume_claims(
                    namespace=namespace,
                    label_selector=f"app.kubernetes.io/name={res_name}",
                ):
                    kube.delete_persistent_volume_claim(namespace=namespace, name=pvc_name)
            elif kind == "Service":
                kube.delete_service(namespace=namespace, name=res_name)
            elif kind == "AgentRuntime":
                kube.delete_custom_resource(
                    group=CRD_GROUP,
                    version=CRD_VERSION,
                    namespace=namespace,
                    plural=AGENTRUNTIMES_PLURAL,
                    name=res_name,
                )
            elif kind == "HTTPRoute":
                kube.delete_custom_resource(
                    group="gateway.networking.k8s.io",
                    version="v1",
                    namespace=namespace,
                    plural="httproutes",
                    name=res_name,
                )
            elif kind == "Route":
                kube.delete_custom_resource(
                    group="route.openshift.io",
                    version="v1",
                    namespace=namespace,
                    plural="routes",
                    name=res_name,
                )
            logger.info(
                "Rolled back %s '%s' in namespace '%s' after failed creation",
                kind,
                sanitize_log(res_name),
                sanitize_log(namespace),
            )
        except Exception as rollback_err:  # noqa: BLE001 - rollback must not raise
            logger.warning(
                "Rollback of %s '%s' in namespace '%s' failed: %s",
                kind,
                sanitize_log(res_name),
                sanitize_log(namespace),
                rollback_err,
            )
