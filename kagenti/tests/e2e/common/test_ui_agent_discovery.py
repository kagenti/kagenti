#!/usr/bin/env python3
"""
UI Agent Discovery E2E Tests

Tests that agents deployed via standard Kubernetes Deployments with the
kagenti.io/type=agent label are discoverable through the UI backend API.

This validates the agent discovery flow:
1. Deployment with kagenti.io/type=agent label exists
2. Backend API can query the Deployment
3. Agent appears in the list with correct metadata

Usage:
    pytest tests/e2e/common/test_ui_agent_discovery.py -v

Environment Variables:
    KAGENTI_BACKEND_URL: Backend API URL
        Kind: http://localhost:8000 (via port-forward)
        OpenShift: https://kagenti-ui-kagenti-system.apps.cluster.example.com/api
"""

import os
import pytest
import httpx


class TestUIAgentDiscovery:
    """Test agent discovery through the UI backend API."""

    @pytest.fixture
    def backend_url(self, is_openshift):
        """
        Get the backend API URL based on environment.

        For Kind: Expects port-forward to backend on localhost:8000
        For OpenShift: Uses route URL from environment variable
        """
        url = os.environ.get("KAGENTI_BACKEND_URL")
        if url:
            return url.rstrip("/")

        # Default URLs based on environment
        if is_openshift:
            # On OpenShift, the backend is accessed through the UI route
            # User should set KAGENTI_BACKEND_URL for their cluster
            pytest.skip(
                "KAGENTI_BACKEND_URL not set. Set it to your OpenShift backend route."
            )
        else:
            # Kind cluster with port-forward (port 8002 to avoid conflict with weather-service)
            return "http://localhost:8002"

    @pytest.mark.critical
    def test_weather_service_agent_discoverable(
        self, backend_url, http_client, k8s_apps_client
    ):
        """
        Verify weather-service agent is discoverable through the UI backend API.

        Prerequisites:
        1. weather-service Deployment exists in team1 namespace
        2. Deployment has label kagenti.io/type=agent
        3. Backend is accessible (port-forwarded or via route)
        """
        # First, verify the Deployment exists and has correct labels
        deployment = k8s_apps_client.read_namespaced_deployment(
            name="weather-service", namespace="team1"
        )
        labels = deployment.metadata.labels or {}

        assert labels.get("kagenti.io/type") == "agent", (
            f"weather-service Deployment missing kagenti.io/type=agent label. "
            f"Found labels: {labels}"
        )

        # Now verify it appears in the backend API response
        # This is a synchronous test, so we use httpx.get instead of http_client
        url = f"{backend_url}/api/v1/agents?namespace=team1"

        try:
            response = httpx.get(url, timeout=30.0)
        except httpx.ConnectError as e:
            pytest.fail(
                f"Could not connect to backend at {backend_url}. "
                f"For Kind, run: kubectl port-forward -n kagenti-system svc/kagenti-backend 8000:8000\n"
                f"Error: {e}"
            )

        assert response.status_code == 200, (
            f"Backend API returned {response.status_code}: {response.text}"
        )

        data = response.json()
        items = data.get("items", [])
        agent_names = [agent.get("name") for agent in items]

        assert "weather-service" in agent_names, (
            f"weather-service not found in UI API response. "
            f"Found agents: {agent_names}. "
            f"Check that backend has RBAC permissions to list Deployments in team1 namespace."
        )

    @pytest.mark.critical
    def test_weather_service_agent_metadata(self, backend_url, http_client):
        """
        Verify weather-service agent has correct metadata in UI API response.

        Checks that the agent response includes:
        - name: weather-service
        - namespace: team1
        - status: Ready (or similar healthy status)
        - labels: protocol=a2a, framework=LangGraph
        - workloadType: deployment
        """
        url = f"{backend_url}/api/v1/agents?namespace=team1"

        try:
            response = httpx.get(url, timeout=30.0)
        except httpx.ConnectError as e:
            pytest.skip(f"Backend not accessible: {e}")

        assert response.status_code == 200

        data = response.json()
        items = data.get("items", [])

        # Find weather-service agent
        weather_agent = next(
            (agent for agent in items if agent.get("name") == "weather-service"), None
        )

        assert weather_agent is not None, "weather-service not found in API response"

        # Verify namespace
        assert weather_agent.get("namespace") == "team1"

        # Verify workload type
        assert weather_agent.get("workloadType") == "deployment", (
            f"Expected workloadType=deployment, got {weather_agent.get('workloadType')}"
        )

        # Verify labels
        labels = weather_agent.get("labels", {})
        assert labels.get("protocol") == "a2a", (
            f"Expected protocol=a2a, got {labels.get('protocol')}"
        )

        # Status should be Ready or Running (depending on deployment state)
        status = weather_agent.get("status")
        assert status in ["Ready", "Running", "Progressing"], (
            f"Expected status Ready/Running, got {status}"
        )

    def test_namespace_label_present(self, k8s_client):
        """
        Verify team1 namespace has kagenti-enabled=true label.

        This label is required for the namespace to appear in the
        UI namespace selector dropdown.
        """
        namespace = k8s_client.read_namespace(name="team1")
        labels = namespace.metadata.labels or {}

        assert labels.get("kagenti-enabled") == "true", (
            f"team1 namespace missing kagenti-enabled=true label. "
            f"Found labels: {labels}. "
            f"This label is required for the namespace to appear in the UI."
        )

    def test_backend_rbac_can_list_deployments(self, k8s_apps_client):
        """
        Verify that listing Deployments with kagenti.io/type=agent label works.

        This simulates what the backend does to discover agents.
        If this fails, check the backend ServiceAccount RBAC permissions.
        """
        deployments = k8s_apps_client.list_namespaced_deployment(
            namespace="team1", label_selector="kagenti.io/type=agent"
        )

        assert len(deployments.items) > 0, (
            "No Deployments found with kagenti.io/type=agent label in team1. "
            "Check that weather-service is deployed correctly."
        )

        deployment_names = [d.metadata.name for d in deployments.items]
        assert "weather-service" in deployment_names, (
            f"weather-service not in agent Deployments. Found: {deployment_names}"
        )


class TestToolDiscovery:
    """Test tool discovery through the UI backend API."""

    @pytest.fixture
    def backend_url(self, is_openshift):
        """Get the backend API URL based on environment."""
        url = os.environ.get("KAGENTI_BACKEND_URL")
        if url:
            return url.rstrip("/")

        if is_openshift:
            pytest.skip("KAGENTI_BACKEND_URL not set for OpenShift")

        # Kind cluster with port-forward (port 8002 to avoid conflict with weather-service)
        return "http://localhost:8002"

    def test_weather_tool_discoverable(self, backend_url, k8s_apps_client):
        """
        Verify weather-tool is discoverable through the UI backend API.

        Prerequisites:
        1. weather-tool Deployment exists in team1 namespace
        2. Deployment has label kagenti.io/type=tool
        """
        # First verify the Deployment exists
        deployment = k8s_apps_client.read_namespaced_deployment(
            name="weather-tool", namespace="team1"
        )
        labels = deployment.metadata.labels or {}

        assert labels.get("kagenti.io/type") == "tool", (
            f"weather-tool Deployment missing kagenti.io/type=tool label. "
            f"Found labels: {labels}"
        )

        # Check API response
        url = f"{backend_url}/api/v1/tools?namespace=team1"

        try:
            response = httpx.get(url, timeout=30.0)
        except httpx.ConnectError as e:
            pytest.skip(f"Backend not accessible: {e}")

        assert response.status_code == 200

        data = response.json()
        items = data.get("items", [])
        tool_names = [tool.get("name") for tool in items]

        assert "weather-tool" in tool_names, (
            f"weather-tool not found in UI API response. Found tools: {tool_names}"
        )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
