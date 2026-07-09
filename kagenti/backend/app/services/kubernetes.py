# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Kubernetes service for API client management and common operations.
"""
# pylint: disable=too-many-public-methods

import logging
import os
from functools import lru_cache
from typing import List, Optional

import kubernetes.client
import kubernetes.config
from kubernetes.client import ApiException
from kubernetes.config import ConfigException

from app.core.constants import (
    AGENT_SANDBOX_CRD_GROUP,
    AGENT_SANDBOX_CRD_VERSION,
    AGENT_SANDBOX_PLURAL,
    ENABLED_NAMESPACE_LABEL_KEY,
    ENABLED_NAMESPACE_LABEL_VALUE,
)

logger = logging.getLogger(__name__)


def _sanitize(value: str) -> str:
    """Strip newlines and control characters to prevent log injection (CWE-117).

    Uses str.replace for \n and \r which CodeQL recognizes as a sanitizer,
    plus strips other control characters.
    """
    return value.replace("\n", "").replace("\r", "").replace("\x00", "")


class KubernetesService:
    """Service class for Kubernetes API interactions."""

    def __init__(self):
        self.api_client = self._load_config()
        self._custom_api: Optional[kubernetes.client.CustomObjectsApi] = None
        self._core_api: Optional[kubernetes.client.CoreV1Api] = None
        self._apps_api: Optional[kubernetes.client.AppsV1Api] = None
        self._batch_api: Optional[kubernetes.client.BatchV1Api] = None
        self._rbac_api: Optional[kubernetes.client.RbacAuthorizationV1Api] = None
        self._apis_api: Optional[kubernetes.client.ApisApi] = None
        self._discovery_v1_api: Optional[kubernetes.client.DiscoveryV1Api] = None

    def _load_config(self) -> kubernetes.client.ApiClient:
        """Load Kubernetes configuration (in-cluster or kubeconfig)."""
        try:
            if os.getenv("KUBERNETES_SERVICE_HOST"):
                logger.info("Loading in-cluster Kubernetes config")
                kubernetes.config.load_incluster_config()
            else:
                logger.info("Loading kubeconfig from default location")
                kubernetes.config.load_kube_config()

            return kubernetes.client.ApiClient()

        except ConfigException as e:
            logger.error(f"Failed to load Kubernetes config: {e}")
            raise

    @property
    def custom_api(self) -> kubernetes.client.CustomObjectsApi:
        """Get CustomObjectsApi client."""
        if self._custom_api is None:
            self._custom_api = kubernetes.client.CustomObjectsApi(self.api_client)
        return self._custom_api

    @property
    def core_api(self) -> kubernetes.client.CoreV1Api:
        """Get CoreV1Api client."""
        if self._core_api is None:
            self._core_api = kubernetes.client.CoreV1Api(self.api_client)
        return self._core_api

    @property
    def apps_api(self) -> kubernetes.client.AppsV1Api:
        """Get AppsV1Api client for Deployments and StatefulSets."""
        if self._apps_api is None:
            self._apps_api = kubernetes.client.AppsV1Api(self.api_client)
        return self._apps_api

    @property
    def batch_api(self) -> kubernetes.client.BatchV1Api:
        """Get BatchV1Api client for Jobs."""
        if self._batch_api is None:
            self._batch_api = kubernetes.client.BatchV1Api(self.api_client)
        return self._batch_api

    @property
    def rbac_api(self) -> kubernetes.client.RbacAuthorizationV1Api:
        """Get RbacAuthorizationV1Api client for Roles and RoleBindings."""
        if self._rbac_api is None:
            self._rbac_api = kubernetes.client.RbacAuthorizationV1Api(self.api_client)
        return self._rbac_api

    @property
    def apis_api(self) -> kubernetes.client.ApisApi:
        """Get ApisApi client (GET /apis/ — API group discovery)."""
        if self._apis_api is None:
            self._apis_api = kubernetes.client.ApisApi(self.api_client)
        return self._apis_api

    @property
    def discovery_v1_api(self) -> kubernetes.client.DiscoveryV1Api:
        """Get DiscoveryV1Api client for EndpointSlices"""
        if self._discovery_v1_api is None:
            self._discovery_v1_api = kubernetes.client.DiscoveryV1Api(self.api_client)
        return self._discovery_v1_api

    def is_running_in_cluster(self) -> bool:
        """Check if running inside a Kubernetes cluster."""
        return bool(os.getenv("KUBERNETES_SERVICE_HOST"))

    def api_group_exists(self, group: str) -> bool:
        """Return True if the cluster advertises the given API group (GET /apis/)."""
        try:
            response = self.apis_api.get_api_versions(_request_timeout=10)
            groups = response.groups or []
            logger.debug(
                "Available API groups: %s",
                sorted(g.name for g in groups if g and g.name),
            )
            return any(g.name == group for g in groups if g and g.name)
        except ApiException as e:
            logger.warning("Error listing API groups: %s", e)
            return False

    def list_namespaces(self, label_selector: Optional[str] = None) -> List[str]:
        """List namespaces with optional label selector."""
        try:
            response = self.core_api.list_namespace(
                label_selector=label_selector,
                timeout_seconds=10,
            )
            return sorted([ns.metadata.name for ns in response.items if ns.metadata])
        except ApiException as e:
            logger.error(f"Error listing namespaces: {e}")
            return ["default"]

    def list_enabled_namespaces(self) -> List[str]:
        """List namespaces with kagenti-enabled=true label."""
        selector = f"{ENABLED_NAMESPACE_LABEL_KEY}={ENABLED_NAMESPACE_LABEL_VALUE}"
        return self.list_namespaces(label_selector=selector)

    def list_custom_resources(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        label_selector: Optional[str] = None,
    ) -> List[dict]:
        """List custom resources in a namespace."""
        namespace = _sanitize(namespace)
        plural = _sanitize(plural)
        try:
            response = self.custom_api.list_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                label_selector=label_selector,
            )
            return response.get("items", [])
        except ApiException as e:
            logger.error(f"Error listing {plural} in {namespace}: {e}")
            raise

    def list_cluster_custom_resources(
        self,
        group: str,
        version: str,
        plural: str,
        label_selector: Optional[str] = None,
        log_api_error: bool = True,
    ) -> dict:
        """List cluster-scoped custom resources (e.g., ClusterBuildStrategies)."""
        plural = _sanitize(plural)
        try:
            return self.custom_api.list_cluster_custom_object(
                group=group,
                version=version,
                plural=plural,
                label_selector=label_selector,
            )
        except ApiException as e:
            if log_api_error:
                logger.error(f"Error listing cluster-scoped {plural}: {e}")
            raise

    def get_custom_resource(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        name: str,
    ) -> dict:
        """Get a specific custom resource."""
        namespace = _sanitize(namespace)
        plural = _sanitize(plural)
        name = _sanitize(name)
        try:
            return self.custom_api.get_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                name=name,
            )
        except ApiException as e:
            logger.error(f"Error getting {plural}/{name} in {namespace}: {e}")
            raise

    def delete_custom_resource(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        name: str,
    ) -> dict:
        """Delete a custom resource."""
        namespace = _sanitize(namespace)
        plural = _sanitize(plural)
        name = _sanitize(name)
        try:
            return self.custom_api.delete_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                name=name,
            )
        except ApiException as e:
            logger.error(f"Error deleting {plural}/{name} in {namespace}: {e}")
            raise

    def create_custom_resource(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        body: dict,
    ) -> dict:
        """Create a custom resource."""
        namespace = _sanitize(namespace)
        plural = _sanitize(plural)
        try:
            return self.custom_api.create_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                body=body,
            )
        except ApiException as e:
            logger.error(f"Error creating {plural} in {namespace}: {e}")
            raise

    def patch_custom_resource(
        self,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        name: str,
        body: dict,
    ) -> dict:
        """Patch a custom resource."""
        namespace = _sanitize(namespace)
        plural = _sanitize(plural)
        name = _sanitize(name)
        try:
            return self.custom_api.patch_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                name=name,
                body=body,
            )
        except ApiException as e:
            logger.error(f"Error patching {plural}/{name} in {namespace}: {e}")
            raise

    # -------------------------------------------------------------------------
    # ServiceAccount Operations
    # -------------------------------------------------------------------------

    def ensure_service_account(self, namespace: str, name: str) -> None:
        """Create a ServiceAccount if it does not already exist.

        This is needed so that the webhook's SPIFFE identity derivation uses
        the workload name (e.g. ``git-issue-agent``) rather than falling back
        to the ReplicaSet hash.
        """
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            self.core_api.read_namespaced_service_account(name=name, namespace=namespace)
            logger.debug(f"ServiceAccount '{name}' already exists in {namespace}")
        except ApiException as e:
            if e.status == 404:
                sa = kubernetes.client.V1ServiceAccount(
                    metadata=kubernetes.client.V1ObjectMeta(
                        name=name,
                        namespace=namespace,
                        labels={"kagenti.io/managed-by": "kagenti-ui"},
                    ),
                )
                self.core_api.create_namespaced_service_account(namespace=namespace, body=sa)
                logger.info(f"Created ServiceAccount '{name}' in {namespace}")
            else:
                logger.error(f"Error checking ServiceAccount '{name}' in {namespace}: {e}")
                raise

    # -------------------------------------------------------------------------
    # ConfigMap Operations
    # -------------------------------------------------------------------------

    def ensure_configmap(
        self, namespace: str, name: str, data: dict, labels: Optional[dict] = None
    ) -> None:
        """Create a ConfigMap if it does not already exist.

        This is idempotent — if the ConfigMap already exists it is left unchanged
        so that user customizations are preserved.
        """
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            self.core_api.read_namespaced_config_map(name=name, namespace=namespace)
            logger.debug(f"ConfigMap '{name}' already exists in {namespace}")
        except ApiException as e:
            if e.status == 404:
                cm = kubernetes.client.V1ConfigMap(
                    metadata=kubernetes.client.V1ObjectMeta(
                        name=name,
                        namespace=namespace,
                        labels=labels or {"kagenti.io/managed-by": "kagenti-api"},
                    ),
                    data=data,
                )
                self.core_api.create_namespaced_config_map(namespace=namespace, body=cm)
                logger.info("Created ConfigMap '%s' in %s", name, namespace)
            else:
                logger.error(f"Error checking ConfigMap '{name}' in {namespace}: {e}")
                raise

    def upsert_configmap(
        self, namespace: str, name: str, data: dict, labels: Optional[dict] = None
    ) -> None:
        """Create or update a ConfigMap (create if missing, merge data keys if exists)."""
        cm_labels = labels or {"kagenti.io/managed-by": "kagenti-api"}
        try:
            existing = self.core_api.read_namespaced_config_map(name=name, namespace=namespace)
            existing.data = {**(existing.data or {}), **data}
            existing.metadata.labels = (existing.metadata.labels or {}) | cm_labels
            self.core_api.replace_namespaced_config_map(
                name=name, namespace=namespace, body=existing
            )
            logger.info("Updated existing ConfigMap")
        except ApiException as e:
            if e.status == 404:
                cm = kubernetes.client.V1ConfigMap(
                    metadata=kubernetes.client.V1ObjectMeta(
                        name=name,
                        namespace=namespace,
                        labels=cm_labels,
                    ),
                    data=data,
                )
                self.core_api.create_namespaced_config_map(namespace=namespace, body=cm)
                logger.info("Created new ConfigMap")
            else:
                logger.error("Error upserting ConfigMap")
                raise

    # -------------------------------------------------------------------------
    # RoleBinding Operations
    # -------------------------------------------------------------------------

    def ensure_rolebinding(
        self,
        namespace: str,
        name: str,
        cluster_role_name: str,
        subjects: list,
        labels: Optional[dict] = None,
    ) -> None:
        """Create a RoleBinding if it does not already exist."""
        # Sanitize for logging (CWE-117 / CodeQL Log Injection).
        # Kubernetes names are already constrained to [a-z0-9-.] but CodeQL
        # cannot verify that statically.
        safe_name = name.replace("\n", "").replace("\r", "")
        safe_ns = namespace.replace("\n", "").replace("\r", "")
        try:
            self.rbac_api.read_namespaced_role_binding(name=name, namespace=namespace)
            logger.debug("RoleBinding '%s' already exists in %s", safe_name, safe_ns)
        except ApiException as e:
            if e.status == 404:
                rb = kubernetes.client.V1RoleBinding(
                    metadata=kubernetes.client.V1ObjectMeta(
                        name=name,
                        namespace=namespace,
                        labels=labels or {"kagenti.io/managed-by": "kagenti-api"},
                    ),
                    role_ref=kubernetes.client.V1RoleRef(
                        api_group="rbac.authorization.k8s.io",
                        kind="ClusterRole",
                        name=cluster_role_name,
                    ),
                    subjects=subjects,
                )
                self.rbac_api.create_namespaced_role_binding(namespace=namespace, body=rb)
                logger.info("Created RoleBinding '%s' in %s", safe_name, safe_ns)
            else:
                logger.error("Error checking RoleBinding '%s' in %s: %s", safe_name, safe_ns, e)
                raise

    # -------------------------------------------------------------------------
    # Deployment Operations
    # -------------------------------------------------------------------------

    def create_deployment(self, namespace: str, body: dict) -> dict:
        """Create a Deployment in the specified namespace."""
        namespace = _sanitize(namespace)
        try:
            result = self.apps_api.create_namespaced_deployment(
                namespace=namespace,
                body=body,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error creating Deployment in {namespace}: {e}")
            raise

    def get_deployment(self, namespace: str, name: str) -> dict:
        """Get a Deployment by name."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            result = self.apps_api.read_namespaced_deployment(
                name=name,
                namespace=namespace,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error getting Deployment {name} in {namespace}: {e}")
            raise

    def list_deployments(self, namespace: str, label_selector: Optional[str] = None) -> List[dict]:
        """List Deployments in a namespace with optional label selector."""
        namespace = _sanitize(namespace)
        try:
            result = self.apps_api.list_namespaced_deployment(
                namespace=namespace,
                label_selector=label_selector,
            )
            return [item.to_dict() for item in result.items]
        except ApiException as e:
            logger.error(f"Error listing Deployments in {namespace}: {e}")
            raise

    def delete_deployment(self, namespace: str, name: str) -> None:
        """Delete a Deployment by name."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            self.apps_api.delete_namespaced_deployment(
                name=name,
                namespace=namespace,
            )
        except ApiException as e:
            logger.error(f"Error deleting Deployment {name} in {namespace}: {e}")
            raise

    def patch_deployment(self, namespace: str, name: str, body: dict) -> dict:
        """Patch a Deployment with the provided body."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            result = self.apps_api.patch_namespaced_deployment(
                name=name,
                namespace=namespace,
                body=body,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error patching Deployment {name} in {namespace}: {e}")
            raise

    # -------------------------------------------------------------------------
    # Service Operations
    # -------------------------------------------------------------------------

    def create_service(self, namespace: str, body: dict) -> dict:
        """Create a Service in the specified namespace."""
        namespace = _sanitize(namespace)
        try:
            result = self.core_api.create_namespaced_service(
                namespace=namespace,
                body=body,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error creating Service in {namespace}: {e}")
            raise

    def get_service(self, namespace: str, name: str) -> dict:
        """Get a Service by name."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            result = self.core_api.read_namespaced_service(
                name=name,
                namespace=namespace,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error getting Service {name} in {namespace}: {e}")
            raise

    def get_endpoint_slices(self, namespace: str, name: str) -> dict:
        """Get a EndpointSlices for a named Service."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            result = self.discovery_v1_api.list_namespaced_endpoint_slice(
                namespace=namespace, label_selector=f"kubernetes.io/service-name={name}"
            )
            return result.to_dict()
        except ApiException:
            logger.error(
                "Error getting EndpointSlices for Service %s/%s", namespace, name, exc_info=True
            )
            raise

    def list_services(self, namespace: str, label_selector: Optional[str] = None) -> List[dict]:
        """List Services in a namespace with optional label selector."""
        namespace = _sanitize(namespace)
        try:
            result = self.core_api.list_namespaced_service(
                namespace=namespace,
                label_selector=label_selector,
            )
            return [item.to_dict() for item in result.items]
        except ApiException as e:
            logger.error(f"Error listing Services in {namespace}: {e}")
            raise

    def delete_service(self, namespace: str, name: str) -> None:
        """Delete a Service by name."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        self.core_api.delete_namespaced_service(
            name=name,
            namespace=namespace,
        )

    # -------------------------------------------------------------------------
    # Secret Operations
    # -------------------------------------------------------------------------

    def create_secret(
        self,
        namespace: str,
        name: str,
        string_data: dict,
        labels: Optional[dict] = None,
    ) -> dict:
        """Create an Opaque Secret with the provided string data.

        If the secret already exists (409 Conflict), updates it in place.
        """
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        metadata = kubernetes.client.V1ObjectMeta(name=name, labels=labels)
        body = kubernetes.client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=metadata,
            string_data=string_data,
        )
        try:
            result = self.core_api.create_namespaced_secret(
                namespace=namespace,
                body=body,
            )
            return result.to_dict()
        except ApiException as e:
            if e.status == 409:
                result = self.core_api.patch_namespaced_secret(
                    name=name,
                    namespace=namespace,
                    body=body,
                )
                return result.to_dict()
            raise

    # -------------------------------------------------------------------------
    # ConfigMap Operations
    # -------------------------------------------------------------------------

    def create_configmap(
        self,
        namespace: str,
        name: str,
        data: dict,
        labels: Optional[dict] = None,
    ) -> dict:
        """Create a ConfigMap with the provided data.

        If the ConfigMap already exists (409 Conflict), updates it in place.
        """
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        metadata = kubernetes.client.V1ObjectMeta(name=name, labels=labels)
        body = kubernetes.client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=metadata,
            data=data,
        )
        try:
            result = self.core_api.create_namespaced_config_map(
                namespace=namespace,
                body=body,
            )
            return result.to_dict()
        except ApiException as e:
            if e.status == 409:
                # ConfigMap already exists — patch it
                result = self.core_api.patch_namespaced_config_map(
                    name=name,
                    namespace=namespace,
                    body=body,
                )
                return result.to_dict()
            raise

    # -------------------------------------------------------------------------
    # StatefulSet Operations
    # -------------------------------------------------------------------------

    def create_statefulset(self, namespace: str, body: dict) -> dict:
        """Create a StatefulSet in the specified namespace."""
        namespace = _sanitize(namespace)
        try:
            result = self.apps_api.create_namespaced_stateful_set(
                namespace=namespace,
                body=body,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error creating StatefulSet in {namespace}: {e}")
            raise

    def get_statefulset(self, namespace: str, name: str) -> dict:
        """Get a StatefulSet by name."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            result = self.apps_api.read_namespaced_stateful_set(
                name=name,
                namespace=namespace,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error getting StatefulSet {name} in {namespace}: {e}")
            raise

    def list_statefulsets(self, namespace: str, label_selector: Optional[str] = None) -> List[dict]:
        """List StatefulSets in a namespace with optional label selector."""
        namespace = _sanitize(namespace)
        try:
            result = self.apps_api.list_namespaced_stateful_set(
                namespace=namespace,
                label_selector=label_selector,
            )
            return [item.to_dict() for item in result.items]
        except ApiException as e:
            logger.error(f"Error listing StatefulSets in {namespace}: {e}")
            raise

    def delete_statefulset(self, namespace: str, name: str) -> None:
        """Delete a StatefulSet by name."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            self.apps_api.delete_namespaced_stateful_set(
                name=name,
                namespace=namespace,
            )
        except ApiException as e:
            logger.error(f"Error deleting StatefulSet {name} in {namespace}: {e}")
            raise

    def patch_statefulset(self, namespace: str, name: str, body: dict) -> dict:
        """Patch a StatefulSet with the provided body."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            result = self.apps_api.patch_namespaced_stateful_set(
                name=name,
                namespace=namespace,
                body=body,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error patching StatefulSet {name} in {namespace}: {e}")
            raise

    def get_workload_pod_status(self, namespace: str, label_selector: str) -> dict:
        """Inspect pods matching a label selector for readiness and waiting state.

        Returns {"ready": bool, "waiting_reason": str|None, "waiting_message": str|None}.
        `ready` is True if any matching pod reports a Ready condition. The waiting
        reason/message come from the first container found in a waiting state
        (e.g. CrashLoopBackOff, ImagePullBackOff, CreateContainerConfigError) — the
        signal used to derive a simulated tool's Error state (#2162).
        """
        namespace = _sanitize(namespace)
        label_selector = _sanitize(label_selector)
        try:
            pods = self.core_api.list_namespaced_pod(
                namespace=namespace, label_selector=label_selector
            ).items
        except ApiException as e:
            # A real RBAC/connectivity failure here would otherwise silently
            # look like "not ready" — surface it at warning level.
            logger.warning("Error listing pods in %s (%s): %s", namespace, label_selector, e)
            return {"ready": False, "waiting_reason": None, "waiting_message": None}

        ready = False
        waiting_reason = None
        waiting_message = None
        for pod in pods:
            conditions = (pod.status and pod.status.conditions) or []
            if any(c.type == "Ready" and c.status == "True" for c in conditions):
                ready = True
            container_statuses = (pod.status and pod.status.container_statuses) or []
            for cs in container_statuses:
                waiting = cs.state and cs.state.waiting
                if waiting and waiting.reason and waiting_reason is None:
                    waiting_reason = waiting.reason
                    waiting_message = waiting.message
        return {
            "ready": ready,
            "waiting_reason": waiting_reason,
            "waiting_message": waiting_message,
        }

    # -------------------------------------------------------------------------
    # Job Operations
    # -------------------------------------------------------------------------

    def create_job(self, namespace: str, body: dict) -> dict:
        """Create a Job in the specified namespace."""
        namespace = _sanitize(namespace)
        try:
            result = self.batch_api.create_namespaced_job(
                namespace=namespace,
                body=body,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error creating Job in {namespace}: {e}")
            raise

    def get_job(self, namespace: str, name: str) -> dict:
        """Get a Job by name."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            result = self.batch_api.read_namespaced_job(
                name=name,
                namespace=namespace,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error getting Job {name} in {namespace}: {e}")
            raise

    def list_jobs(self, namespace: str, label_selector: Optional[str] = None) -> List[dict]:
        """List Jobs in a namespace with optional label selector."""
        namespace = _sanitize(namespace)
        try:
            result = self.batch_api.list_namespaced_job(
                namespace=namespace,
                label_selector=label_selector,
            )
            return [item.to_dict() for item in result.items]
        except ApiException as e:
            logger.error(f"Error listing Jobs in {namespace}: {e}")
            raise

    def delete_job(self, namespace: str, name: str) -> None:
        """Delete a Job by name."""
        namespace = _sanitize(namespace)
        name = _sanitize(name)
        try:
            # Use propagationPolicy=Background to delete pods
            self.batch_api.delete_namespaced_job(
                name=name,
                namespace=namespace,
                propagation_policy="Background",
            )
        except ApiException as e:
            logger.error(f"Error deleting Job {name} in {namespace}: {e}")
            raise

    # -------------------------------------------------------------------------
    # Sandbox Operations
    # -------------------------------------------------------------------------

    def create_sandbox(self, namespace: str, body: dict) -> dict:
        """Create a Sandbox custom resource in the specified namespace."""
        return self.create_custom_resource(
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            namespace,
            AGENT_SANDBOX_PLURAL,
            body,
        )

    def get_sandbox(self, namespace: str, name: str) -> dict:
        """Get a Sandbox custom resource by name."""
        return self.get_custom_resource(
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            namespace,
            AGENT_SANDBOX_PLURAL,
            name,
        )

    def list_sandboxes(self, namespace: str, label_selector: Optional[str] = None) -> List[dict]:
        """List Sandbox custom resources in a namespace."""
        return self.list_custom_resources(
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            namespace,
            AGENT_SANDBOX_PLURAL,
            label_selector,
        )

    def delete_sandbox(self, namespace: str, name: str) -> None:
        """Delete a Sandbox custom resource by name."""
        self.delete_custom_resource(
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            namespace,
            AGENT_SANDBOX_PLURAL,
            name,
        )

    def patch_sandbox(self, namespace: str, name: str, body: dict) -> dict:
        """Patch a Sandbox custom resource."""
        return self.patch_custom_resource(
            AGENT_SANDBOX_CRD_GROUP,
            AGENT_SANDBOX_CRD_VERSION,
            namespace,
            AGENT_SANDBOX_PLURAL,
            name,
            body,
        )

    def list_persistent_volume_claims(
        self, namespace: str, label_selector: Optional[str] = None
    ) -> List[str]:
        """List PVC names in a namespace, optionally filtered by label."""
        result = self.core_api.list_namespaced_persistent_volume_claim(
            namespace=namespace, label_selector=label_selector or ""
        )
        return [pvc.metadata.name for pvc in result.items]

    def delete_persistent_volume_claim(self, namespace: str, name: str) -> None:
        """Delete a PersistentVolumeClaim by name."""
        self.core_api.delete_namespaced_persistent_volume_claim(name=name, namespace=namespace)


@lru_cache
def get_kubernetes_service() -> KubernetesService:
    """Get cached KubernetesService instance."""
    return KubernetesService()
