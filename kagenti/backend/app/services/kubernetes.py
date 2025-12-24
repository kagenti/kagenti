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

from app.core.config import settings
from app.core.constants import ENABLED_NAMESPACE_LABEL_KEY, ENABLED_NAMESPACE_LABEL_VALUE

logger = logging.getLogger(__name__)


class KubernetesService:
    """Service class for Kubernetes API interactions."""

    def __init__(self):
        self.api_client = self._load_config()
        self._custom_api: Optional[kubernetes.client.CustomObjectsApi] = None
        self._core_api: Optional[kubernetes.client.CoreV1Api] = None

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


@lru_cache
def get_kubernetes_service() -> KubernetesService:
    """Get cached KubernetesService instance."""
    return KubernetesService()
