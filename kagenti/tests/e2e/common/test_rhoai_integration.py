#!/usr/bin/env python3
"""
RHOAI Integration E2E Tests

Tests RHOAI deployment health and Istio coexistence when RHOAI is enabled.

Usage:
    pytest tests/e2e/common/test_rhoai_integration.py -v
"""

import subprocess

import pytest
from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException


@pytest.fixture(scope="session")
def k8s_custom_client():
    """
    Load Kubernetes configuration and return CustomObjectsApi client.

    Returns:
        kubernetes.client.CustomObjectsApi: Kubernetes custom objects API client

    Raises:
        pytest.skip: If cannot connect to Kubernetes cluster
    """
    try:
        k8s_config.load_kube_config()
    except k8s_config.ConfigException:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException as e:
            pytest.skip(f"Could not load Kubernetes config: {e}")

    return client.CustomObjectsApi()


class TestRHOAIOperatorHealth:
    """Test RHOAI operator deployment health."""

    @pytest.mark.requires_features(["rhoai"])
    def test_rhoai_operator_namespace_exists(self, k8s_client):
        """Verify redhat-ods-operator namespace exists."""
        try:
            ns = k8s_client.read_namespace(name="redhat-ods-operator")
            assert ns is not None
        except ApiException as e:
            pytest.fail(f"redhat-ods-operator namespace not found: {e}")

    @pytest.mark.requires_features(["rhoai"])
    def test_rhoai_operator_running(self, k8s_client):
        """Verify RHOAI operator pod is Running."""
        pods = k8s_client.list_namespaced_pod(
            namespace="redhat-ods-operator",
            label_selector="name=rhods-operator",
        )
        assert len(pods.items) > 0, "No RHOAI operator pods found"
        for pod in pods.items:
            assert pod.status.phase == "Running", (
                f"RHOAI operator pod {pod.metadata.name} is {pod.status.phase}"
            )


class TestRHOAIDataScienceCluster:
    """Test DataScienceCluster CR health."""

    @pytest.mark.requires_features(["rhoai"])
    def test_datasciencecluster_exists(self, k8s_custom_client):
        """Verify DataScienceCluster CR exists."""
        dsc = k8s_custom_client.get_cluster_custom_object(
            group="datasciencecluster.opendatahub.io",
            version="v1",
            plural="datascienceclusters",
            name="default-dsc",
        )
        assert dsc is not None

    @pytest.mark.requires_features(["rhoai"])
    def test_datasciencecluster_ready(self, k8s_custom_client):
        """Verify DataScienceCluster is in Ready phase."""
        dsc = k8s_custom_client.get_cluster_custom_object(
            group="datasciencecluster.opendatahub.io",
            version="v1",
            plural="datascienceclusters",
            name="default-dsc",
        )
        phase = dsc.get("status", {}).get("phase", "Unknown")
        assert phase == "Ready", f"DataScienceCluster phase is {phase}, expected Ready"

    @pytest.mark.requires_features(["rhoai"])
    def test_kserve_controller_running(self, k8s_client):
        """Verify KServe controller manager is Running."""
        pods = k8s_client.list_namespaced_pod(
            namespace="redhat-ods-applications",
            label_selector="control-plane=kserve-controller-manager",
        )
        assert len(pods.items) > 0, "No KServe controller pods found"
        for pod in pods.items:
            assert pod.status.phase == "Running", (
                f"KServe controller pod {pod.metadata.name} is {pod.status.phase}"
            )


class TestRHOAICoexistence:
    """Test RHOAI and Kagenti Istio coexistence (gateway + ambient)."""

    @pytest.mark.requires_features(["rhoai", "istio"])
    def test_ztunnel_no_bad_signature(self, k8s_client):
        """Verify ztunnel logs show no BadSignature errors."""
        result = subprocess.run(
            [
                "kubectl",
                "logs",
                "-n",
                "istio-ztunnel",
                "-l",
                "app=ztunnel",
                "--tail=200",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert "BadSignature" not in result.stdout, (
            "ztunnel logs contain BadSignature errors - CA mismatch detected"
        )

    @pytest.mark.requires_features(["rhoai", "istio"])
    def test_shared_root_ca(self, k8s_client):
        """Verify both Istio control planes share the same root CA."""
        try:
            cm_kagenti = k8s_client.read_namespaced_config_map(
                name="istio-ca-root-cert",
                namespace="kagenti-system",
            )
        except ApiException as e:
            if e.status == 404:
                pytest.skip(
                    "istio-ca-root-cert not found in kagenti-system"
                    " — namespace not meshed"
                )
            raise
        try:
            cm_gateway = k8s_client.read_namespaced_config_map(
                name="istio-ca-root-cert",
                namespace="gateway-system",
            )
        except ApiException as e:
            if e.status == 404:
                pytest.skip(
                    "istio-ca-root-cert not found in gateway-system"
                    " — namespace not meshed"
                )
            raise
        kagenti_ca = cm_kagenti.data.get("root-cert.pem", "")
        gateway_ca = cm_gateway.data.get("root-cert.pem", "")
        assert kagenti_ca == gateway_ca, (
            "Root CA mismatch between kagenti-system and gateway-system. "
            "Both Istio control planes should share the same root CA."
        )

    @pytest.mark.requires_features(["rhoai"])
    def test_rhoai_gateway_route_exists(self, k8s_custom_client):
        """Verify RHOAI data-science-gateway route exists in openshift-ingress."""
        # RHOAI 3.x creates a data-science-gateway route via its Istio gateway.
        # This exists regardless of whether the RHOAI dashboard component is enabled.
        try:
            route = k8s_custom_client.get_namespaced_custom_object(
                group="route.openshift.io",
                version="v1",
                namespace="openshift-ingress",
                plural="routes",
                name="data-science-gateway",
            )
            host = route.get("spec", {}).get("host", "")
            assert host, "data-science-gateway route has no host"
        except Exception as e:
            pytest.fail(
                f"data-science-gateway route not found in openshift-ingress: {e}"
            )
