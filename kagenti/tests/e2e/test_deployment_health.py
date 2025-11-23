#!/usr/bin/env python3
"""
Deployment Health E2E Tests for Kagenti Platform

Tests basic deployment health:
- No failed pods
- Deployments are ready
- Services have endpoints
- Pods are running without excessive restarts

These tests validate the platform is deployed correctly and healthy.

Usage:
    pytest tests/e2e/test_deployment_health.py -v
    pytest tests/e2e/test_deployment_health.py::TestDeploymentHealth::test_no_failed_pods -v
"""

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException


# ============================================================================
# Test: Overall Platform Health
# ============================================================================


class TestPlatformHealth:
    """Test overall platform health checks."""

    @pytest.mark.critical
    def test_no_failed_pods(self, k8s_client):
        """
        Verify there are no failed pods in the cluster.

        Checks that all pods are in Running or Succeeded phase.
        """
        # Get all pods across all namespaces
        pods = k8s_client.list_pod_for_all_namespaces(watch=False)

        # Find pods that are not in Running or Succeeded state
        failed_pods = [
            f"{pod.metadata.namespace}/{pod.metadata.name} ({pod.status.phase})"
            for pod in pods.items
            if pod.status.phase not in ["Running", "Succeeded"]
        ]

        assert len(failed_pods) == 0, (
            f"Found {len(failed_pods)} failed pods:\n" + "\n".join(failed_pods)
        )

    @pytest.mark.critical
    def test_no_crashlooping_pods(self, k8s_client):
        """
        Verify there are no crashlooping pods.

        Checks that no pods have excessive restart counts (>3).
        """
        pods = k8s_client.list_pod_for_all_namespaces(watch=False)

        crashlooping_pods = []
        for pod in pods.items:
            if pod.status.container_statuses:
                for container in pod.status.container_statuses:
                    if container.restart_count > 3:
                        crashlooping_pods.append(
                            f"{pod.metadata.namespace}/{pod.metadata.name} "
                            f"(container: {container.name}, restarts: {container.restart_count})"
                        )

        assert len(crashlooping_pods) == 0, (
            f"Found {len(crashlooping_pods)} crashlooping pods:\n"
            + "\n".join(crashlooping_pods)
        )


# ============================================================================
# Test: Weather Tool Deployment
# ============================================================================


class TestWeatherToolDeployment:
    """Test weather-tool deployment health."""

    @pytest.mark.critical
    def test_weather_tool_deployment_exists(self, k8s_apps_client):
        """Verify weather-tool deployment exists in team1 namespace."""
        try:
            deployment = k8s_apps_client.read_namespaced_deployment(
                name="weather-tool", namespace="team1"
            )
            assert deployment is not None, "weather-tool deployment not found"
        except ApiException as e:
            pytest.fail(f"weather-tool deployment not found: {e}")

    @pytest.mark.critical
    def test_weather_tool_deployment_ready(self, k8s_apps_client):
        """
        Verify weather-tool deployment is ready.

        Checks that the deployment has the desired number of ready replicas.
        """
        deployment = k8s_apps_client.read_namespaced_deployment(
            name="weather-tool", namespace="team1"
        )

        desired_replicas = deployment.spec.replicas or 1
        ready_replicas = deployment.status.ready_replicas or 0

        assert (
            ready_replicas >= desired_replicas
        ), f"weather-tool deployment not ready: {ready_replicas}/{desired_replicas} replicas"

    def test_weather_tool_pods_running(self, k8s_client, k8s_apps_client):
        """Verify weather-tool pods are in Running state."""
        # Get deployment to find actual label selector
        deployment = k8s_apps_client.read_namespaced_deployment(
            name="weather-tool", namespace="team1"
        )

        # Build label selector from deployment's matchLabels
        match_labels = deployment.spec.selector.match_labels
        label_selector = ",".join([f"{k}={v}" for k, v in match_labels.items()])

        pods = k8s_client.list_namespaced_pod(
            namespace="team1", label_selector=label_selector
        )

        assert len(pods.items) > 0, "No weather-tool pods found"

        for pod in pods.items:
            assert (
                pod.status.phase == "Running"
            ), f"weather-tool pod {pod.metadata.name} not running: {pod.status.phase}"

    def test_weather_tool_service_exists(self, k8s_client):
        """Verify weather-tool service exists."""
        try:
            service = k8s_client.read_namespaced_service(
                name="weather-tool", namespace="team1"
            )
            assert service is not None, "weather-tool service not found"
        except ApiException as e:
            pytest.fail(f"weather-tool service not found: {e}")

    def test_weather_tool_service_has_endpoints(self, k8s_client):
        """Verify weather-tool service has endpoints."""
        try:
            endpoints = k8s_client.read_namespaced_endpoints(
                name="weather-tool", namespace="team1"
            )

            # Check if endpoints exist
            has_endpoints = False
            if endpoints.subsets:
                for subset in endpoints.subsets:
                    if subset.addresses:
                        has_endpoints = True
                        break

            assert has_endpoints, "weather-tool service has no endpoints"

        except ApiException as e:
            pytest.fail(f"Could not read weather-tool endpoints: {e}")


# ============================================================================
# Test: Weather Service Deployment
# ============================================================================


class TestWeatherServiceDeployment:
    """Test weather-service (agent) deployment health."""

    @pytest.mark.critical
    def test_weather_service_deployment_exists(self, k8s_apps_client):
        """Verify weather-service deployment exists in team1 namespace."""
        try:
            deployment = k8s_apps_client.read_namespaced_deployment(
                name="weather-service", namespace="team1"
            )
            assert deployment is not None, "weather-service deployment not found"
        except ApiException as e:
            pytest.fail(f"weather-service deployment not found: {e}")

    @pytest.mark.critical
    def test_weather_service_deployment_ready(self, k8s_apps_client):
        """
        Verify weather-service deployment is ready.

        Checks that the deployment has the desired number of ready replicas.
        """
        deployment = k8s_apps_client.read_namespaced_deployment(
            name="weather-service", namespace="team1"
        )

        desired_replicas = deployment.spec.replicas or 1
        ready_replicas = deployment.status.ready_replicas or 0

        assert (
            ready_replicas >= desired_replicas
        ), f"weather-service deployment not ready: {ready_replicas}/{desired_replicas} replicas"

    def test_weather_service_pods_running(self, k8s_client, k8s_apps_client):
        """Verify weather-service pods are in Running state."""
        # Get deployment to find actual label selector
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
            ), f"weather-service pod {pod.metadata.name} not running: {pod.status.phase}"

    def test_weather_service_service_exists(self, k8s_client):
        """Verify weather-service service exists."""
        try:
            service = k8s_client.read_namespaced_service(
                name="weather-service", namespace="team1"
            )
            assert service is not None, "weather-service service not found"
        except ApiException as e:
            pytest.fail(f"weather-service service not found: {e}")

    def test_weather_service_service_has_endpoints(self, k8s_client):
        """Verify weather-service service has endpoints."""
        try:
            endpoints = k8s_client.read_namespaced_endpoints(
                name="weather-service", namespace="team1"
            )

            # Check if endpoints exist
            has_endpoints = False
            if endpoints.subsets:
                for subset in endpoints.subsets:
                    if subset.addresses:
                        has_endpoints = True
                        break

            assert has_endpoints, "weather-service service has no endpoints"

        except ApiException as e:
            pytest.fail(f"Could not read weather-service endpoints: {e}")


# ============================================================================
# Test: Keycloak Deployment (if not excluded)
# ============================================================================


class TestKeycloakDeployment:
    """Test Keycloak deployment health."""

    def test_keycloak_namespace_exists(self, k8s_client, excluded_apps):
        """Verify keycloak namespace exists (unless excluded)."""
        if "keycloak" in excluded_apps:
            pytest.skip("Keycloak excluded from tests")

        try:
            namespace = k8s_client.read_namespace(name="keycloak")
            assert namespace is not None, "keycloak namespace not found"
        except ApiException as e:
            pytest.fail(f"keycloak namespace not found: {e}")

    @pytest.mark.critical
    def test_keycloak_deployment_ready(self, k8s_apps_client, excluded_apps):
        """Verify Keycloak deployment or statefulset is ready."""
        if "keycloak" in excluded_apps:
            pytest.skip("Keycloak excluded from tests")

        # Try deployment first
        try:
            deployment = k8s_apps_client.read_namespaced_deployment(
                name="keycloak", namespace="keycloak"
            )

            desired_replicas = deployment.spec.replicas or 1
            ready_replicas = deployment.status.ready_replicas or 0

            assert (
                ready_replicas >= desired_replicas
            ), f"Keycloak deployment not ready: {ready_replicas}/{desired_replicas} replicas"
            return  # Success
        except ApiException:
            pass  # Try statefulset

        # Try statefulset
        try:
            statefulset = k8s_apps_client.read_namespaced_stateful_set(
                name="keycloak", namespace="keycloak"
            )

            desired_replicas = statefulset.spec.replicas or 1
            ready_replicas = statefulset.status.ready_replicas or 0

            assert (
                ready_replicas >= desired_replicas
            ), f"Keycloak statefulset not ready: {ready_replicas}/{desired_replicas} replicas"
        except ApiException as e:
            pytest.fail(f"Keycloak deployment/statefulset not found: {e}")


# ============================================================================
# Test: Platform Operator Deployment (if not excluded)
# ============================================================================


class TestPlatformOperatorDeployment:
    """Test Platform Operator deployment health."""

    @pytest.mark.critical
    def test_platform_operator_ready(self, k8s_apps_client, excluded_apps):
        """Verify Platform Operator deployment is ready."""
        if "operator" in excluded_apps:
            pytest.skip("Platform Operator excluded from tests")

        try:
            # Platform operator uses label control-plane=controller-manager
            deployments = k8s_apps_client.list_namespaced_deployment(
                namespace="kagenti-system",
                label_selector="control-plane=controller-manager",
            )

            assert (
                len(deployments.items) > 0
            ), "Platform Operator deployment not found in kagenti-system"

            deployment = deployments.items[0]
            desired_replicas = deployment.spec.replicas or 1
            ready_replicas = deployment.status.ready_replicas or 0

            assert (
                ready_replicas >= desired_replicas
            ), f"Platform Operator not ready: {ready_replicas}/{desired_replicas} replicas"

        except ApiException as e:
            pytest.fail(f"Could not check Platform Operator: {e}")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
