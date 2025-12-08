#!/usr/bin/env python3
"""
Platform Health E2E Tests - Common to Both Operators

Tests basic platform health that works regardless of operator mode:
- No failed pods
- No crashlooping pods
- Core deployments are ready

Usage:
    pytest tests/e2e/common/test_platform_health.py -v
"""

import pytest
from datetime import datetime, timezone, timedelta


# TEST COMMENT testing CI
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

        Checks that no pods are currently in a CrashLoopBackOff state
        or have recently restarted (within the last 5 minutes).
        Initial startup restarts are ignored.
        """
        pods = k8s_client.list_pod_for_all_namespaces(watch=False)

        crashlooping_pods = []
        now = datetime.now(timezone.utc)
        recent_restart_threshold = timedelta(minutes=5)

        for pod in pods.items:
            # Check if pod is in CrashLoopBackOff state
            if pod.status.container_statuses:
                for container in pod.status.container_statuses:
                    # Check for CrashLoopBackOff state
                    if container.state and container.state.waiting:
                        if container.state.waiting.reason == "CrashLoopBackOff":
                            crashlooping_pods.append(
                                f"{pod.metadata.namespace}/{pod.metadata.name} "
                                f"(container: {container.name}, state: CrashLoopBackOff, "
                                f"restarts: {container.restart_count})"
                            )
                            continue

                    # Check for recent restarts (not just total count)
                    if (
                        container.restart_count > 0
                        and container.state
                        and container.state.running
                    ):
                        started_at = container.state.running.started_at
                        if started_at:
                            time_since_start = now - started_at
                            # If pod restarted recently (within 5 min) and has multiple restarts, flag it
                            if (
                                time_since_start < recent_restart_threshold
                                and container.restart_count > 2
                            ):
                                crashlooping_pods.append(
                                    f"{pod.metadata.namespace}/{pod.metadata.name} "
                                    f"(container: {container.name}, recent restarts: {container.restart_count}, "
                                    f"last started: {time_since_start.total_seconds():.0f}s ago)"
                                )

        assert len(crashlooping_pods) == 0, (
            f"Found {len(crashlooping_pods)} crashlooping pods:\n"
            + "\n".join(crashlooping_pods)
        )


class TestWeatherToolDeployment:
    """Test weather-tool deployment health (common to both operators)."""

    @pytest.mark.critical
    def test_weather_tool_deployment_exists(self, k8s_apps_client):
        """Verify weather-tool deployment exists in team1 namespace."""
        from kubernetes.client.rest import ApiException

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


class TestWeatherServiceDeployment:
    """Test weather-service (agent) deployment health (common to both operators)."""

    @pytest.mark.critical
    def test_weather_service_deployment_exists(self, k8s_apps_client):
        """Verify weather-service deployment exists in team1 namespace."""
        from kubernetes.client.rest import ApiException

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


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
