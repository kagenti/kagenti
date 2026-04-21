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

import pytest
import httpx


class TestUIAgentDiscovery:
    """Test agent discovery through the UI backend API."""

    @pytest.fixture(autouse=True)
    def _setup_ssl(self, is_openshift, openshift_ingress_ca):
        """Set SSL context for OpenShift routes."""
        import ssl

        if is_openshift:
            self._verify = ssl.create_default_context(cafile=openshift_ingress_ca)
        else:
            self._verify = True

    # backend_url fixture is inherited from conftest.py (session-scoped)

    @pytest.mark.critical
    def test_weather_service_agent_discoverable(
        self, backend_url, http_client, k8s_apps_client, keycloak_agent_token
    ):
        """
        Verify weather-service agent is discoverable through the UI backend API.

        Prerequisites:
        1. weather-service Deployment exists in team1 namespace
        2. Deployment has label kagenti.io/type=agent
        3. Backend is accessible (port-forwarded or via route)
        4. Valid Keycloak token available (backend requires ROLE_VIEWER)
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

        if not keycloak_agent_token:
            pytest.skip(
                "No Keycloak agent token available - cannot authenticate to backend API"
            )

        # Backend API requires Bearer token with kagenti-viewer role
        headers = {"Authorization": f"Bearer {keycloak_agent_token}"}

        # Now verify it appears in the backend API response
        url = f"{backend_url}/api/v1/agents?namespace=team1"

        try:
            response = httpx.get(
                url, timeout=30.0, verify=self._verify, headers=headers
            )
        except httpx.ConnectError as e:
            pytest.fail(
                f"Backend not accessible at {backend_url}. "
                f"Port-forward may not be running or route is unreachable. Error: {e}"
            )

        assert response.status_code == 200, (
            f"Backend API returned {response.status_code} at {url}. "
            f"Response: {response.text[:500]}"
        )

        data = response.json()
        items = data.get("items", [])
        agent_names = [agent.get("name") for agent in items]

        assert agent_names, (
            "Backend API returned empty agent list. "
            "This may indicate a backend bug or RBAC issue. "
            "The Kubernetes API can find agents (see test_backend_rbac_can_list_deployments)."
        )

        assert "weather-service" in agent_names, (
            f"weather-service not found in UI API response. "
            f"Found agents: {agent_names}. "
            f"Check that backend has RBAC permissions to list Deployments in team1 namespace."
        )

    @pytest.mark.critical
    def test_weather_service_agent_metadata(
        self, backend_url, http_client, keycloak_agent_token
    ):
        """
        Verify weather-service agent has correct metadata in UI API response.

        Checks that the agent response includes:
        - name: weather-service
        - namespace: team1
        - status: Ready (or similar healthy status)
        - labels: protocol=a2a, framework=LangGraph
        - workloadType: deployment
        """
        if not keycloak_agent_token:
            pytest.skip(
                "No Keycloak agent token available - cannot authenticate to backend API"
            )

        headers = {"Authorization": f"Bearer {keycloak_agent_token}"}
        url = f"{backend_url}/api/v1/agents?namespace=team1"

        try:
            response = httpx.get(
                url, timeout=30.0, verify=self._verify, headers=headers
            )
        except httpx.ConnectError as e:
            pytest.fail(f"Backend not accessible at {backend_url}: {e}")

        assert response.status_code == 200, (
            f"Backend API returned {response.status_code} at {url}. "
            f"Response: {response.text[:500]}"
        )

        data = response.json()
        items = data.get("items", [])

        # Find weather-service agent
        weather_agent = next(
            (agent for agent in items if agent.get("name") == "weather-service"), None
        )

        assert weather_agent is not None, (
            "weather-service not found in API response. "
            f"Found agents: {[a.get('name') for a in items]}. "
            "Backend may not be discovering agents correctly."
        )

        # Verify namespace
        assert weather_agent.get("namespace") == "team1"

        # Verify workload type
        assert weather_agent.get("workloadType") == "deployment", (
            f"Expected workloadType=deployment, got {weather_agent.get('workloadType')}"
        )

        # Verify labels
        labels = weather_agent.get("labels", {})
        protocol = labels.get("protocol")
        # Backend may return protocol as string or list
        if isinstance(protocol, list):
            assert "a2a" in protocol, f"Expected 'a2a' in protocol list, got {protocol}"
        else:
            assert protocol == "a2a", f"Expected protocol=a2a, got {protocol}"

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

    @pytest.fixture(autouse=True)
    def _setup_ssl(self, is_openshift, openshift_ingress_ca):
        """Set SSL context for OpenShift routes."""
        import ssl

        if is_openshift:
            self._verify = ssl.create_default_context(cafile=openshift_ingress_ca)
        else:
            self._verify = True

    # backend_url fixture is inherited from conftest.py (session-scoped)

    def test_weather_tool_discoverable(
        self, backend_url, k8s_apps_client, keycloak_agent_token
    ):
        """
        Verify weather-tool is discoverable through the UI backend API.

        Prerequisites:
        1. weather-tool Deployment exists in team1 namespace
        2. Deployment has label kagenti.io/type=tool
        3. Valid Keycloak token available (backend requires ROLE_VIEWER)
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

        if not keycloak_agent_token:
            pytest.skip(
                "No Keycloak agent token available - cannot authenticate to backend API"
            )

        headers = {"Authorization": f"Bearer {keycloak_agent_token}"}

        # Check API response
        url = f"{backend_url}/api/v1/tools?namespace=team1"

        try:
            response = httpx.get(
                url, timeout=30.0, verify=self._verify, headers=headers
            )
        except httpx.ConnectError as e:
            pytest.fail(f"Backend not accessible at {backend_url}: {e}")

        assert response.status_code == 200, (
            f"Backend tools API returned {response.status_code} at {url}. "
            f"Response: {response.text[:500]}"
        )

        data = response.json()
        items = data.get("items", [])
        tool_names = [tool.get("name") for tool in items]

        assert tool_names, (
            "Backend API returned empty tool list. "
            "Backend may not be discovering tools correctly."
        )

        assert "weather-tool" in tool_names, (
            f"weather-tool not found in UI API response. Found tools: {tool_names}"
        )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
