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


def _is_job_pod(pod) -> bool:
    """Check if a pod is owned by a Kubernetes Job.

    Job pods can fail and be retried - this is expected behavior.
    We should not count transient job pod failures as platform health issues.

    Detection methods:
    1. Check owner_references for kind="Job"
    2. Fallback: Check if pod name contains "-job-" pattern (Job naming convention)
    """
    # Method 1: Check owner references
    owner_refs = pod.metadata.owner_references
    if owner_refs is not None and len(owner_refs) > 0:
        for owner in owner_refs:
            if owner.kind == "Job":
                return True

    # Method 2: Fallback - check pod naming convention
    # Job pods are typically named <job-name>-<random-suffix>
    # Job names often end with "-job" by convention
    pod_name = pod.metadata.name or ""
    if "-job-" in pod_name:
        return True

    return False


KAGENTI_NAMESPACES = {
    "kagenti-system",
    "kagenti-webhook-system",
    "keycloak",
    "team1",
    "team2",
    "mcp-system",
    "spire-mgmt",
    "zero-trust-workload-identity-manager",
    "spire-system",
    "gateway-system",
    "istio-system",
    "istio-cni",
    "istio-ztunnel",
    "cert-manager",
}


def _in_kagenti_namespace(namespace: str) -> bool:
    return namespace in KAGENTI_NAMESPACES


class TestPlatformHealth:
    """Test overall platform health checks."""

    @pytest.mark.critical
    def test_no_failed_pods(self, k8s_client):
        """
        Verify there are no failed pods in Kagenti-managed namespaces.

        Checks that all pods are in Running or Succeeded phase.
        Excludes Job pods since they can fail and be retried (expected behavior).
        Scoped to Kagenti namespaces to avoid false positives from
        unrelated system pods on OpenShift.
        """
        pods = k8s_client.list_pod_for_all_namespaces(watch=False)

        failed_pods = [
            f"{pod.metadata.namespace}/{pod.metadata.name} ({pod.status.phase})"
            for pod in pods.items
            if _in_kagenti_namespace(pod.metadata.namespace)
            and pod.status.phase not in ["Running", "Succeeded"]
            and not _is_job_pod(pod)
        ]

        assert len(failed_pods) == 0, (
            f"Found {len(failed_pods)} failed pods:\n" + "\n".join(failed_pods)
        )

    @pytest.mark.critical
    def test_no_crashlooping_pods(self, k8s_client):
        """
        Verify there are no crashlooping pods in Kagenti-managed namespaces.

        Checks that no pods are currently in a CrashLoopBackOff state
        or have recently restarted (within the last 5 minutes).
        Initial startup restarts are ignored.
        Excludes Job pods since they use restartPolicy: OnFailure and
        transient restarts are expected — test_all_jobs_completed checks
        Job completion separately.
        """
        pods = k8s_client.list_pod_for_all_namespaces(watch=False)

        crashlooping_pods = []
        now = datetime.now(timezone.utc)
        recent_restart_threshold = timedelta(minutes=5)

        for pod in pods.items:
            if not _in_kagenti_namespace(pod.metadata.namespace):
                continue

            # Skip Job pods — they restart on failure by design
            if _is_job_pod(pod):
                continue

            if pod.status.container_statuses:
                for container in pod.status.container_statuses:
                    if container.state and container.state.waiting:
                        if container.state.waiting.reason == "CrashLoopBackOff":
                            crashlooping_pods.append(
                                f"{pod.metadata.namespace}/{pod.metadata.name} "
                                f"(container: {container.name}, state: CrashLoopBackOff, "
                                f"restarts: {container.restart_count})"
                            )
                            continue

                    if (
                        container.restart_count > 0
                        and container.state
                        and container.state.running
                    ):
                        started_at = container.state.running.started_at
                        if started_at:
                            time_since_start = now - started_at
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

    @pytest.mark.critical
    def test_all_jobs_completed(self, k8s_batch_client):
        """
        Verify that all Jobs in Kagenti-managed namespaces have completed.

        Checks that every Job has at least one successful completion
        (status.succeeded >= 1). Jobs that are still actively running
        are not considered failures. Helm hook jobs (oauth-secret) are
        allowed to fail since they run during install and may encounter
        transient Keycloak availability issues.
        """
        HELM_HOOK_JOBS = {
            "kagenti-agent-oauth-secret-job",
            "kagenti-ui-oauth-secret-job",
        }

        jobs = k8s_batch_client.list_job_for_all_namespaces(watch=False)

        failed_jobs = []
        for job in jobs.items:
            namespace = job.metadata.namespace
            if not _in_kagenti_namespace(namespace):
                continue

            job_name = job.metadata.name

            succeeded = job.status.succeeded or 0
            failed = job.status.failed or 0
            active = job.status.active or 0

            if active > 0:
                continue

            if job_name in HELM_HOOK_JOBS:
                continue

            if succeeded < 1:
                failed_jobs.append(
                    f"{namespace}/{job_name} (succeeded={succeeded}, failed={failed})"
                )

        assert len(failed_jobs) == 0, (
            f"Found {len(failed_jobs)} jobs that did not complete successfully:\n"
            + "\n".join(failed_jobs)
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

        assert ready_replicas >= desired_replicas, (
            f"weather-tool deployment not ready: {ready_replicas}/{desired_replicas} replicas"
        )

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
            assert pod.status.phase == "Running", (
                f"weather-tool pod {pod.metadata.name} not running: {pod.status.phase}"
            )


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

        assert ready_replicas >= desired_replicas, (
            f"weather-service deployment not ready: {ready_replicas}/{desired_replicas} replicas"
        )

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
            assert pod.status.phase == "Running", (
                f"weather-service pod {pod.metadata.name} not running: {pod.status.phase}"
            )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
