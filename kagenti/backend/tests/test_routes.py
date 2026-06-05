# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Unit tests for route utility functions.
"""

import pytest
from unittest.mock import MagicMock, patch

from kubernetes.client import ApiException


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


class TestResolveAgentUrl:
    """Test cases for resolve_agent_url()."""

    @patch("app.utils.routes.settings")
    def test_custom_port(self, mock_settings, kubernetes_service):
        """Service with non-default port returns URL with that port."""
        mock_settings.is_running_in_cluster = True
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "spec": {"ports": [{"port": 8082, "targetPort": 8082}]},
        }
        kubernetes_service._core_api.read_namespaced_service.return_value = mock_result

        from app.utils.routes import resolve_agent_url

        url = resolve_agent_url("my-agent", "team1", kubernetes_service)
        assert url == "http://my-agent.team1.svc.cluster.local:8082"

    @patch("app.utils.routes.settings")
    def test_default_port(self, mock_settings, kubernetes_service):
        """Service with default port 8080 returns URL with 8080."""
        mock_settings.is_running_in_cluster = True
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "spec": {"ports": [{"port": 8080, "targetPort": 8000}]},
        }
        kubernetes_service._core_api.read_namespaced_service.return_value = mock_result

        from app.utils.routes import resolve_agent_url

        url = resolve_agent_url("my-agent", "team1", kubernetes_service)
        assert url == "http://my-agent.team1.svc.cluster.local:8080"

    @patch("app.utils.routes.settings")
    def test_service_no_ports_reads_sandbox_containerport(self, mock_settings, kubernetes_service):
        """Service with empty ports → read containerPort from the owning Sandbox."""
        mock_settings.is_running_in_cluster = True
        svc = MagicMock()
        svc.to_dict.return_value = {"spec": {"ports": []}}
        kubernetes_service._core_api.read_namespaced_service.return_value = svc
        kubernetes_service.get_sandbox = MagicMock(
            return_value={
                "spec": {
                    "podTemplate": {"spec": {"containers": [{"ports": [{"containerPort": 8080}]}]}}
                }
            }
        )

        from app.utils.routes import resolve_agent_url

        url = resolve_agent_url("my-agent", "team1", kubernetes_service)
        assert url == "http://my-agent.team1.svc.cluster.local:8080"

    @patch("app.utils.routes.settings")
    def test_service_no_ports_reads_sandbox_env(self, mock_settings, kubernetes_service):
        """No containerPort → fall back to the PORT env var on the Sandbox."""
        mock_settings.is_running_in_cluster = True
        svc = MagicMock()
        svc.to_dict.return_value = {"spec": {"ports": []}}
        kubernetes_service._core_api.read_namespaced_service.return_value = svc
        kubernetes_service.get_sandbox = MagicMock(
            return_value={
                "spec": {
                    "podTemplate": {
                        "spec": {"containers": [{"env": [{"name": "PORT", "value": "9000"}]}]}
                    }
                }
            }
        )

        from app.utils.routes import resolve_agent_url

        url = resolve_agent_url("my-agent", "team1", kubernetes_service)
        assert url == "http://my-agent.team1.svc.cluster.local:9000"

    @patch("app.utils.routes.settings")
    def test_service_missing_no_sandbox_falls_back(self, mock_settings, kubernetes_service):
        """No Service and no Sandbox → DEFAULT_OFF_CLUSTER_PORT (8080)."""
        mock_settings.is_running_in_cluster = True
        kubernetes_service._core_api.read_namespaced_service.side_effect = ApiException(
            status=404, reason="Not Found"
        )
        kubernetes_service.get_sandbox = MagicMock(
            side_effect=ApiException(status=404, reason="Not Found")
        )

        from app.utils.routes import resolve_agent_url

        url = resolve_agent_url("my-agent", "team1", kubernetes_service)
        assert url == "http://my-agent.team1.svc.cluster.local:8080"

    @patch("app.utils.routes.settings")
    def test_service_missing_off_cluster(self, mock_settings, kubernetes_service):
        """No Service, no Sandbox, off-cluster → DEFAULT_OFF_CLUSTER_PORT with domain."""
        mock_settings.is_running_in_cluster = False
        mock_settings.domain_name = "localtest.me"
        kubernetes_service._core_api.read_namespaced_service.side_effect = ApiException(
            status=404, reason="Not Found"
        )
        kubernetes_service.get_sandbox = MagicMock(
            side_effect=ApiException(status=404, reason="Not Found")
        )

        from app.utils.routes import resolve_agent_url

        url = resolve_agent_url("my-agent", "team1", kubernetes_service)
        assert url == "http://my-agent.team1.localtest.me:8080"

    @patch("app.utils.routes.settings")
    def test_off_cluster_custom_port(self, mock_settings, kubernetes_service):
        """Off-cluster URL uses domain name with actual Service port."""
        mock_settings.is_running_in_cluster = False
        mock_settings.domain_name = "localtest.me"
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "spec": {"ports": [{"port": 9090, "targetPort": 8000}]},
        }
        kubernetes_service._core_api.read_namespaced_service.return_value = mock_result

        from app.utils.routes import resolve_agent_url

        url = resolve_agent_url("my-agent", "team1", kubernetes_service)
        assert url == "http://my-agent.team1.localtest.me:9090"


class TestSelectRoutePort:
    """Test cases for select_route_port()."""

    def test_empty_list_returns_default(self):
        from app.utils.routes import select_route_port

        assert select_route_port([], default_port=8080) == 8080

    def test_none_returns_default(self):
        from app.utils.routes import select_route_port

        assert select_route_port(None, default_port=9090) == 9090

    def test_prefers_http_named_port_dict(self):
        from app.utils.routes import select_route_port

        ports = [
            {"name": "grpc", "port": 9090},
            {"name": "http", "port": 8080},
        ]
        assert select_route_port(ports) == 8080

    def test_prefers_http_named_port_object(self):
        from app.utils.routes import select_route_port

        class FakePort:
            def __init__(self, name, port):
                self.name = name
                self.port = port

        ports = [FakePort("grpc", 9090), FakePort("http", 8080)]
        assert select_route_port(ports) == 8080

    def test_falls_back_to_first_port(self):
        from app.utils.routes import select_route_port

        ports = [{"name": "grpc", "port": 9090}, {"name": "metrics", "port": 2112}]
        assert select_route_port(ports) == 9090

    def test_falls_back_to_default_when_port_missing(self):
        from app.utils.routes import select_route_port

        ports = [{"name": "grpc"}]
        assert select_route_port(ports, default_port=8000) == 8000

    def test_single_http_port(self):
        from app.utils.routes import select_route_port

        ports = [{"name": "http", "port": 3000}]
        assert select_route_port(ports) == 3000

    def test_default_port_parameter(self):
        from app.utils.routes import select_route_port
        from app.core.constants import DEFAULT_IN_CLUSTER_PORT

        assert select_route_port([]) == DEFAULT_IN_CLUSTER_PORT
