"""
Weather agent tests for platform-operator mode.

Tests for platform-operator specific resources (services, endpoints).
"""

import pytest
from kubernetes.client.rest import ApiException


class TestWeatherToolServices:
    """Test weather-tool service resources (platform-operator only)."""

    @pytest.mark.requires_features(["platformOperator"])
    def test_weather_tool_service_exists(self, k8s_client, weather_tool_service_name):
        """Verify weather-tool service exists."""
        try:
            service = k8s_client.read_namespaced_service(
                name=weather_tool_service_name, namespace="team1"
            )
            assert service is not None, f"{weather_tool_service_name} service not found"
        except ApiException as e:
            pytest.fail(f"{weather_tool_service_name} service not found: {e}")

    @pytest.mark.requires_features(["platformOperator"])
    def test_weather_tool_service_has_endpoints(
        self, k8s_client, weather_tool_service_name
    ):
        """Verify weather-tool service has endpoints."""
        try:
            endpoints = k8s_client.read_namespaced_endpoints(
                name=weather_tool_service_name, namespace="team1"
            )

            # Check if endpoints exist
            has_endpoints = False
            if endpoints.subsets:
                for subset in endpoints.subsets:
                    if subset.addresses:
                        has_endpoints = True
                        break

            assert (
                has_endpoints
            ), f"{weather_tool_service_name} service has no endpoints"

        except ApiException as e:
            pytest.fail(f"Could not read {weather_tool_service_name} endpoints: {e}")


class TestWeatherServiceServices:
    """Test weather-service service resources (platform-operator only)."""

    @pytest.mark.requires_features(["platformOperator"])
    def test_weather_service_service_exists(self, k8s_client, weather_service_name):
        """Verify weather-service service exists."""
        try:
            service = k8s_client.read_namespaced_service(
                name=weather_service_name, namespace="team1"
            )
            assert service is not None, f"{weather_service_name} service not found"
        except ApiException as e:
            pytest.fail(f"{weather_service_name} service not found: {e}")

    @pytest.mark.requires_features(["platformOperator"])
    def test_weather_service_service_has_endpoints(
        self, k8s_client, weather_service_name
    ):
        """Verify weather-service service has endpoints."""
        try:
            endpoints = k8s_client.read_namespaced_endpoints(
                name=weather_service_name, namespace="team1"
            )

            # Check if endpoints exist
            has_endpoints = False
            if endpoints.subsets:
                for subset in endpoints.subsets:
                    if subset.addresses:
                        has_endpoints = True
                        break

            assert has_endpoints, f"{weather_service_name} service has no endpoints"

        except ApiException as e:
            pytest.fail(f"Could not read {weather_service_name} endpoints: {e}")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
