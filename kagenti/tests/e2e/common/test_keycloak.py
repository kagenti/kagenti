#!/usr/bin/env python3
"""
Keycloak E2E Tests - Common to Both Operators

Tests Keycloak deployment health and authentication (when enabled).

Usage:
    pytest tests/e2e/common/test_keycloak.py -v

Fixtures:
    keycloak_admin_credentials: Reads admin credentials from Kubernetes secret
    keycloak_token: Authenticates and returns Keycloak access token
"""

import pytest
from kubernetes.client.rest import ApiException


class TestKeycloakDeployment:
    """Test Keycloak deployment health."""

    @pytest.mark.requires_features(["keycloak"])
    def test_keycloak_namespace_exists(self, k8s_client):
        """Verify keycloak namespace exists."""
        try:
            namespace = k8s_client.read_namespace(name="keycloak")
            assert namespace is not None, "keycloak namespace not found"
        except ApiException as e:
            pytest.fail(f"keycloak namespace not found: {e}")

    @pytest.mark.critical
    @pytest.mark.requires_features(["keycloak"])
    def test_keycloak_deployment_ready(self, k8s_apps_client):
        """Verify Keycloak deployment or statefulset is ready."""
        deployment_error = None
        statefulset_error = None

        # Try deployment first
        try:
            deployment = k8s_apps_client.read_namespaced_deployment(
                name="keycloak", namespace="keycloak"
            )

            desired_replicas = deployment.spec.replicas or 1
            ready_replicas = deployment.status.ready_replicas or 0

            assert ready_replicas >= desired_replicas, (
                f"Keycloak deployment not ready: {ready_replicas}/{desired_replicas} replicas"
            )
            return  # Success
        except ApiException as e:
            deployment_error = str(e)

        # Try statefulset
        try:
            statefulset = k8s_apps_client.read_namespaced_stateful_set(
                name="keycloak", namespace="keycloak"
            )

            desired_replicas = statefulset.spec.replicas or 1
            ready_replicas = statefulset.status.ready_replicas or 0

            assert ready_replicas >= desired_replicas, (
                f"Keycloak statefulset not ready: {ready_replicas}/{desired_replicas} replicas"
            )
            return  # Success
        except ApiException as e:
            statefulset_error = str(e)

        # Both failed - report both errors
        pytest.fail(
            f"Keycloak not found as deployment or statefulset.\n"
            f"Deployment error: {deployment_error}\n"
            f"StatefulSet error: {statefulset_error}"
        )

    @pytest.mark.requires_features(["keycloak"])
    def test_keycloak_admin_login(self, keycloak_token):
        """
        Test Keycloak admin authentication.

        Verifies that we can authenticate with the Keycloak admin user
        and obtain an access token using credentials from Kubernetes secrets.

        This test uses the keycloak_token fixture which:
        1. Reads admin credentials from keycloak-initial-admin secret
        2. Authenticates to port-forwarded Keycloak (localhost:8081)
        3. Returns a valid OAuth token

        Args:
            keycloak_token: Fixture that provides Keycloak access token
        """
        # Verify we got a valid token from the fixture
        assert keycloak_token is not None, "keycloak_token fixture returned None"
        assert isinstance(keycloak_token, dict), (
            f"keycloak_token is not a dict: {type(keycloak_token)}"
        )

        # Verify required token fields
        assert "access_token" in keycloak_token, (
            f"No access_token in token. Keys: {keycloak_token.keys()}"
        )
        assert len(keycloak_token["access_token"]) > 0, "Access token is empty"
        assert "token_type" in keycloak_token, "No token_type in token"
        assert keycloak_token["token_type"].lower() == "bearer", (
            f"Unexpected token type: {keycloak_token['token_type']}"
        )

        print("\n✓ Successfully authenticated to Keycloak")
        print(f"  Token type: {keycloak_token.get('token_type', 'unknown')}")
        print(f"  Expires in: {keycloak_token.get('expires_in', 'unknown')} seconds")
        print(f"  Scopes: {keycloak_token.get('scope', 'unknown')}")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
