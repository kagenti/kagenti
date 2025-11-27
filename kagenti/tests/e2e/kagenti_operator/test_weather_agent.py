"""
Weather agent tests for kagenti-operator mode.

Tests for the weather-service agent deployed via kagenti-operator.
"""

import pytest
from kubernetes.client.exceptions import ApiException


class TestWeatherAgent:
    """Test weather-service agent deployment in kagenti-operator mode."""

    @pytest.mark.requires_features(["kagentiOperator"])
    def test_deployment_exists(self, k8s_apps_client):
        """Verify weather-service deployment exists."""
        try:
            deployment = k8s_apps_client.read_namespaced_deployment(
                name="weather-service", namespace="team1"
            )
            assert deployment is not None, "weather-service deployment not found"
        except ApiException as e:
            pytest.fail(f"weather-service deployment not found: {e}")

    @pytest.mark.requires_features(["kagentiOperator"])
    def test_deployment_ready(self, k8s_apps_client):
        """Verify weather-service deployment is ready."""
        deployment = k8s_apps_client.read_namespaced_deployment(
            name="weather-service", namespace="team1"
        )

        desired_replicas = deployment.spec.replicas or 1
        ready_replicas = deployment.status.ready_replicas or 0

        assert (
            ready_replicas >= desired_replicas
        ), f"weather-service not ready: {ready_replicas}/{desired_replicas} replicas"

    @pytest.mark.requires_features(["kagentiOperator"])
    def test_pods_running(self, k8s_client, k8s_apps_client):
        """Verify weather-service pods are running."""
        deployment = k8s_apps_client.read_namespaced_deployment(
            name="weather-service", namespace="team1"
        )

        # Build label selector from deployment's matchLabels
        match_labels = deployment.spec.selector.match_labels
        label_selector = ",".join([f"{k}={v}" for k, v in match_labels.items()])

        pods = k8s_client.list_namespaced_pod(
            namespace="team1", label_selector=label_selector
        )

        assert len(pods.items) > 0, "No weather-service pods found"

        for pod in pods.items:
            assert (
                pod.status.phase == "Running"
            ), f"Pod {pod.metadata.name} not running: {pod.status.phase}"

    @pytest.mark.requires_features(["kagentiOperator"])
    def test_service_exists(self, k8s_client, weather_service_name):
        """Verify weather-service service exists with correct name."""
        try:
            service = k8s_client.read_namespaced_service(
                name=weather_service_name, namespace="team1"
            )
            assert service is not None, f"{weather_service_name} service not found"
        except ApiException as e:
            pytest.fail(f"{weather_service_name} service not found: {e}")
