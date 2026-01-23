# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Kubernetes service for API client management and common operations.
"""

import logging
import os
from functools import lru_cache
from typing import List, Optional

import kubernetes.client
import kubernetes.config
from kubernetes.client import ApiException
from kubernetes.config import ConfigException

from app.core.constants import ENABLED_NAMESPACE_LABEL_KEY, ENABLED_NAMESPACE_LABEL_VALUE

logger = logging.getLogger(__name__)


class KubernetesService:
    """Service class for Kubernetes API interactions."""

    def __init__(self):
        self.api_client = self._load_config()
        self._custom_api: Optional[kubernetes.client.CustomObjectsApi] = None
        self._core_api: Optional[kubernetes.client.CoreV1Api] = None
        self._apps_api: Optional[kubernetes.client.AppsV1Api] = None
        self._batch_api: Optional[kubernetes.client.BatchV1Api] = None

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

    def is_running_in_cluster(self) -> bool:
        """Check if running inside a Kubernetes cluster."""
        return bool(os.getenv("KUBERNETES_SERVICE_HOST"))

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
    ) -> dict:
        """List cluster-scoped custom resources (e.g., ClusterBuildStrategies)."""
        try:
            return self.custom_api.list_cluster_custom_object(
                group=group,
                version=version,
                plural=plural,
                label_selector=label_selector,
            )
        except ApiException as e:
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

    # -------------------------------------------------------------------------
    # Deployment Operations
    # -------------------------------------------------------------------------

    def create_deployment(self, namespace: str, body: dict) -> dict:
        """Create a Deployment in the specified namespace."""
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
        try:
            result = self.core_api.read_namespaced_service(
                name=name,
                namespace=namespace,
            )
            return result.to_dict()
        except ApiException as e:
            logger.error(f"Error getting Service {name} in {namespace}: {e}")
            raise

    def list_services(self, namespace: str, label_selector: Optional[str] = None) -> List[dict]:
        """List Services in a namespace with optional label selector."""
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
        try:
            self.core_api.delete_namespaced_service(
                name=name,
                namespace=namespace,
            )
        except ApiException as e:
            logger.error(f"Error deleting Service {name} in {namespace}: {e}")
            raise

    # -------------------------------------------------------------------------
    # StatefulSet Operations
    # -------------------------------------------------------------------------

    def create_statefulset(self, namespace: str, body: dict) -> dict:
        """Create a StatefulSet in the specified namespace."""
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

    # -------------------------------------------------------------------------
    # Job Operations
    # -------------------------------------------------------------------------

    def create_job(self, namespace: str, body: dict) -> dict:
        """Create a Job in the specified namespace."""
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


@lru_cache
def get_kubernetes_service() -> KubernetesService:
    """Get cached KubernetesService instance."""
    return KubernetesService()
