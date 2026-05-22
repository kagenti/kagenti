# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Unit tests for lookup_service_port() used by tool URL resolution.
"""

import pytest
from unittest.mock import MagicMock, patch

from kubernetes.client import ApiException

from app.utils.routes import lookup_service_port


@pytest.fixture
def kubernetes_service():
    """Create a KubernetesService instance with mocked APIs."""
    with (
        patch("app.services.kubernetes.kubernetes.config.load_incluster_config"),
        patch("app.services.kubernetes.kubernetes.config.load_kube_config"),
        patch("app.services.kubernetes.kubernetes.client.ApiClient"),
        patch.dict("os.environ", {}, clear=False),
    ):
        from app.services.kubernetes import KubernetesService

        service = KubernetesService()
        service._apps_api = MagicMock()
        service._core_api = MagicMock()
        service._batch_api = MagicMock()
        return service


class TestLookupServicePort:
    """Test cases for lookup_service_port()."""

    def test_returns_actual_port(self, kubernetes_service):
        """Service with a non-default port returns that port."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "spec": {"ports": [{"port": 9090, "targetPort": 9090}]},
        }
        kubernetes_service._core_api.read_namespaced_service.return_value = mock_result

        port = lookup_service_port("my-tool-mcp", "team1", kubernetes_service, 8000)
        assert port == 9090
        kubernetes_service._core_api.read_namespaced_service.assert_called_once_with(
            name="my-tool-mcp", namespace="team1"
        )

    def test_returns_default_when_port_matches(self, kubernetes_service):
        """Service with the default port returns the default port."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "spec": {"ports": [{"port": 8000, "targetPort": 8000}]},
        }
        kubernetes_service._core_api.read_namespaced_service.return_value = mock_result

        port = lookup_service_port("my-tool-mcp", "team1", kubernetes_service, 8000)
        assert port == 8000

    def test_service_not_found_returns_default(self, kubernetes_service):
        """Missing Service returns the default port."""
        kubernetes_service._core_api.read_namespaced_service.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        port = lookup_service_port("my-tool-mcp", "team1", kubernetes_service, 8000)
        assert port == 8000

    def test_service_no_ports_returns_default(self, kubernetes_service):
        """Service with empty ports list returns the default port."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"spec": {"ports": []}}
        kubernetes_service._core_api.read_namespaced_service.return_value = mock_result

        port = lookup_service_port("my-tool-mcp", "team1", kubernetes_service, 8000)
        assert port == 8000

    def test_different_default_port(self, kubernetes_service):
        """Default port parameter is respected when Service is missing."""
        kubernetes_service._core_api.read_namespaced_service.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        port = lookup_service_port("my-agent", "team1", kubernetes_service, 8080)
        assert port == 8080
