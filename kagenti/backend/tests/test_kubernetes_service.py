# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Unit tests for KubernetesService workload operations.

Tests cover Deployment, StatefulSet, Job, and Service CRUD operations
with proper mocking of the Kubernetes API client.
"""

import pytest
from unittest.mock import MagicMock, patch

# Import ApiException before mocking - this is the real exception class
from kubernetes.client import ApiException


@pytest.fixture
def kubernetes_service():
    """Create a KubernetesService instance with mocked APIs."""
    # Patch the config loading to avoid needing a real cluster
    with (
        patch("app.services.kubernetes.kubernetes.config.load_incluster_config"),
        patch("app.services.kubernetes.kubernetes.config.load_kube_config"),
        patch("app.services.kubernetes.kubernetes.client.ApiClient"),
        patch.dict("os.environ", {}, clear=False),
    ):
        from app.services.kubernetes import KubernetesService

        service = KubernetesService()
        # Mock the API clients
        service._apps_api = MagicMock()
        service._core_api = MagicMock()
        service._batch_api = MagicMock()
        return service


class TestDeploymentOperations:
    """Test cases for Deployment CRUD operations."""

    def test_create_deployment_success(self, kubernetes_service):
        """Test successful Deployment creation."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "metadata": {"name": "test-deploy", "namespace": "test-ns"},
            "spec": {"replicas": 1},
        }
        kubernetes_service._apps_api.create_namespaced_deployment.return_value = mock_result

        body = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "test-deploy"},
            "spec": {"replicas": 1},
        }
        result = kubernetes_service.create_deployment("test-ns", body)

        kubernetes_service._apps_api.create_namespaced_deployment.assert_called_once_with(
            namespace="test-ns",
            body=body,
        )
        assert result["metadata"]["name"] == "test-deploy"

    def test_create_deployment_api_error(self, kubernetes_service):
        """Test Deployment creation with API error."""
        kubernetes_service._apps_api.create_namespaced_deployment.side_effect = ApiException(
            status=409, reason="Conflict"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.create_deployment("test-ns", {"metadata": {"name": "test"}})

        assert exc_info.value.status == 409

    def test_get_deployment_success(self, kubernetes_service):
        """Test successful Deployment retrieval."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "metadata": {"name": "test-deploy", "namespace": "test-ns"},
            "status": {"readyReplicas": 1},
        }
        kubernetes_service._apps_api.read_namespaced_deployment.return_value = mock_result

        result = kubernetes_service.get_deployment("test-ns", "test-deploy")

        kubernetes_service._apps_api.read_namespaced_deployment.assert_called_once_with(
            name="test-deploy",
            namespace="test-ns",
        )
        assert result["metadata"]["name"] == "test-deploy"
        assert result["status"]["readyReplicas"] == 1

    def test_get_deployment_not_found(self, kubernetes_service):
        """Test Deployment retrieval when not found."""
        kubernetes_service._apps_api.read_namespaced_deployment.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.get_deployment("test-ns", "nonexistent")

        assert exc_info.value.status == 404

    def test_list_deployments_success(self, kubernetes_service):
        """Test successful Deployment listing."""
        mock_item1 = MagicMock()
        mock_item1.to_dict.return_value = {"metadata": {"name": "deploy-1"}}
        mock_item2 = MagicMock()
        mock_item2.to_dict.return_value = {"metadata": {"name": "deploy-2"}}

        mock_result = MagicMock()
        mock_result.items = [mock_item1, mock_item2]
        kubernetes_service._apps_api.list_namespaced_deployment.return_value = mock_result

        result = kubernetes_service.list_deployments("test-ns")

        kubernetes_service._apps_api.list_namespaced_deployment.assert_called_once_with(
            namespace="test-ns",
            label_selector=None,
        )
        assert len(result) == 2
        assert result[0]["metadata"]["name"] == "deploy-1"
        assert result[1]["metadata"]["name"] == "deploy-2"

    def test_list_deployments_with_label_selector(self, kubernetes_service):
        """Test Deployment listing with label selector."""
        mock_result = MagicMock()
        mock_result.items = []
        kubernetes_service._apps_api.list_namespaced_deployment.return_value = mock_result

        kubernetes_service.list_deployments("test-ns", label_selector="app=test")

        kubernetes_service._apps_api.list_namespaced_deployment.assert_called_once_with(
            namespace="test-ns",
            label_selector="app=test",
        )

    def test_list_deployments_api_error(self, kubernetes_service):
        """Test Deployment listing with API error."""
        kubernetes_service._apps_api.list_namespaced_deployment.side_effect = ApiException(
            status=403, reason="Forbidden"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.list_deployments("test-ns")

        assert exc_info.value.status == 403

    def test_delete_deployment_success(self, kubernetes_service):
        """Test successful Deployment deletion."""
        kubernetes_service._apps_api.delete_namespaced_deployment.return_value = None

        kubernetes_service.delete_deployment("test-ns", "test-deploy")

        kubernetes_service._apps_api.delete_namespaced_deployment.assert_called_once_with(
            name="test-deploy",
            namespace="test-ns",
        )

    def test_delete_deployment_not_found(self, kubernetes_service):
        """Test Deployment deletion when not found."""
        kubernetes_service._apps_api.delete_namespaced_deployment.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.delete_deployment("test-ns", "nonexistent")

        assert exc_info.value.status == 404

    def test_patch_deployment_success(self, kubernetes_service):
        """Test successful Deployment patching."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "metadata": {"name": "test-deploy"},
            "spec": {"replicas": 3},
        }
        kubernetes_service._apps_api.patch_namespaced_deployment.return_value = mock_result

        patch_body = {"spec": {"replicas": 3}}
        result = kubernetes_service.patch_deployment("test-ns", "test-deploy", patch_body)

        kubernetes_service._apps_api.patch_namespaced_deployment.assert_called_once_with(
            name="test-deploy",
            namespace="test-ns",
            body=patch_body,
        )
        assert result["spec"]["replicas"] == 3

    def test_patch_deployment_api_error(self, kubernetes_service):
        """Test Deployment patching with API error."""
        kubernetes_service._apps_api.patch_namespaced_deployment.side_effect = ApiException(
            status=422, reason="Unprocessable Entity"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.patch_deployment("test-ns", "test-deploy", {"spec": {}})

        assert exc_info.value.status == 422


class TestStatefulSetOperations:
    """Test cases for StatefulSet CRUD operations."""

    def test_create_statefulset_success(self, kubernetes_service):
        """Test successful StatefulSet creation."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "metadata": {"name": "test-sts", "namespace": "test-ns"},
            "spec": {"replicas": 1, "serviceName": "test-sts"},
        }
        kubernetes_service._apps_api.create_namespaced_stateful_set.return_value = mock_result

        body = {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": "test-sts"},
            "spec": {"replicas": 1, "serviceName": "test-sts"},
        }
        result = kubernetes_service.create_statefulset("test-ns", body)

        kubernetes_service._apps_api.create_namespaced_stateful_set.assert_called_once_with(
            namespace="test-ns",
            body=body,
        )
        assert result["metadata"]["name"] == "test-sts"

    def test_create_statefulset_api_error(self, kubernetes_service):
        """Test StatefulSet creation with API error."""
        kubernetes_service._apps_api.create_namespaced_stateful_set.side_effect = ApiException(
            status=422, reason="Unprocessable Entity"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.create_statefulset("test-ns", {"metadata": {"name": "test"}})

        assert exc_info.value.status == 422

    def test_get_statefulset_success(self, kubernetes_service):
        """Test successful StatefulSet retrieval."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "metadata": {"name": "test-sts", "namespace": "test-ns"},
            "status": {"readyReplicas": 1, "replicas": 1},
        }
        kubernetes_service._apps_api.read_namespaced_stateful_set.return_value = mock_result

        result = kubernetes_service.get_statefulset("test-ns", "test-sts")

        kubernetes_service._apps_api.read_namespaced_stateful_set.assert_called_once_with(
            name="test-sts",
            namespace="test-ns",
        )
        assert result["metadata"]["name"] == "test-sts"
        assert result["status"]["readyReplicas"] == 1

    def test_get_statefulset_not_found(self, kubernetes_service):
        """Test StatefulSet retrieval when not found."""
        kubernetes_service._apps_api.read_namespaced_stateful_set.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.get_statefulset("test-ns", "nonexistent")

        assert exc_info.value.status == 404

    def test_list_statefulsets_success(self, kubernetes_service):
        """Test successful StatefulSet listing."""
        mock_item1 = MagicMock()
        mock_item1.to_dict.return_value = {"metadata": {"name": "sts-1"}}
        mock_item2 = MagicMock()
        mock_item2.to_dict.return_value = {"metadata": {"name": "sts-2"}}

        mock_result = MagicMock()
        mock_result.items = [mock_item1, mock_item2]
        kubernetes_service._apps_api.list_namespaced_stateful_set.return_value = mock_result

        result = kubernetes_service.list_statefulsets("test-ns")

        kubernetes_service._apps_api.list_namespaced_stateful_set.assert_called_once_with(
            namespace="test-ns",
            label_selector=None,
        )
        assert len(result) == 2
        assert result[0]["metadata"]["name"] == "sts-1"

    def test_list_statefulsets_with_label_selector(self, kubernetes_service):
        """Test StatefulSet listing with label selector."""
        mock_result = MagicMock()
        mock_result.items = []
        kubernetes_service._apps_api.list_namespaced_stateful_set.return_value = mock_result

        kubernetes_service.list_statefulsets("test-ns", label_selector="kagenti.io/type=agent")

        kubernetes_service._apps_api.list_namespaced_stateful_set.assert_called_once_with(
            namespace="test-ns",
            label_selector="kagenti.io/type=agent",
        )

    def test_list_statefulsets_api_error(self, kubernetes_service):
        """Test StatefulSet listing with API error."""
        kubernetes_service._apps_api.list_namespaced_stateful_set.side_effect = ApiException(
            status=403, reason="Forbidden"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.list_statefulsets("test-ns")

        assert exc_info.value.status == 403

    def test_delete_statefulset_success(self, kubernetes_service):
        """Test successful StatefulSet deletion."""
        kubernetes_service._apps_api.delete_namespaced_stateful_set.return_value = None

        kubernetes_service.delete_statefulset("test-ns", "test-sts")

        kubernetes_service._apps_api.delete_namespaced_stateful_set.assert_called_once_with(
            name="test-sts",
            namespace="test-ns",
        )

    def test_delete_statefulset_not_found(self, kubernetes_service):
        """Test StatefulSet deletion when not found."""
        kubernetes_service._apps_api.delete_namespaced_stateful_set.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.delete_statefulset("test-ns", "nonexistent")

        assert exc_info.value.status == 404

    def test_patch_statefulset_success(self, kubernetes_service):
        """Test successful StatefulSet patching."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "metadata": {"name": "test-sts"},
            "spec": {"replicas": 3},
        }
        kubernetes_service._apps_api.patch_namespaced_stateful_set.return_value = mock_result

        patch_body = {"spec": {"replicas": 3}}
        result = kubernetes_service.patch_statefulset("test-ns", "test-sts", patch_body)

        kubernetes_service._apps_api.patch_namespaced_stateful_set.assert_called_once_with(
            name="test-sts",
            namespace="test-ns",
            body=patch_body,
        )
        assert result["spec"]["replicas"] == 3

    def test_patch_statefulset_api_error(self, kubernetes_service):
        """Test StatefulSet patching with API error."""
        kubernetes_service._apps_api.patch_namespaced_stateful_set.side_effect = ApiException(
            status=422, reason="Unprocessable Entity"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.patch_statefulset("test-ns", "test-sts", {"spec": {}})

        assert exc_info.value.status == 422


class TestJobOperations:
    """Test cases for Job CRUD operations."""

    def test_create_job_success(self, kubernetes_service):
        """Test successful Job creation."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "metadata": {"name": "test-job", "namespace": "test-ns"},
            "spec": {"template": {"spec": {"containers": []}}},
        }
        kubernetes_service._batch_api.create_namespaced_job.return_value = mock_result

        body = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": "test-job"},
            "spec": {"template": {"spec": {"containers": [], "restartPolicy": "Never"}}},
        }
        result = kubernetes_service.create_job("test-ns", body)

        kubernetes_service._batch_api.create_namespaced_job.assert_called_once_with(
            namespace="test-ns",
            body=body,
        )
        assert result["metadata"]["name"] == "test-job"

    def test_create_job_api_error(self, kubernetes_service):
        """Test Job creation with API error."""
        kubernetes_service._batch_api.create_namespaced_job.side_effect = ApiException(
            status=409, reason="Conflict"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.create_job("test-ns", {"metadata": {"name": "test"}})

        assert exc_info.value.status == 409

    def test_get_job_success(self, kubernetes_service):
        """Test successful Job retrieval."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "metadata": {"name": "test-job", "namespace": "test-ns"},
            "status": {
                "succeeded": 1,
                "conditions": [{"type": "Complete", "status": "True"}],
            },
        }
        kubernetes_service._batch_api.read_namespaced_job.return_value = mock_result

        result = kubernetes_service.get_job("test-ns", "test-job")

        kubernetes_service._batch_api.read_namespaced_job.assert_called_once_with(
            name="test-job",
            namespace="test-ns",
        )
        assert result["metadata"]["name"] == "test-job"
        assert result["status"]["succeeded"] == 1

    def test_get_job_not_found(self, kubernetes_service):
        """Test Job retrieval when not found."""
        kubernetes_service._batch_api.read_namespaced_job.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.get_job("test-ns", "nonexistent")

        assert exc_info.value.status == 404

    def test_list_jobs_success(self, kubernetes_service):
        """Test successful Job listing."""
        mock_item1 = MagicMock()
        mock_item1.to_dict.return_value = {"metadata": {"name": "job-1"}}
        mock_item2 = MagicMock()
        mock_item2.to_dict.return_value = {"metadata": {"name": "job-2"}}

        mock_result = MagicMock()
        mock_result.items = [mock_item1, mock_item2]
        kubernetes_service._batch_api.list_namespaced_job.return_value = mock_result

        result = kubernetes_service.list_jobs("test-ns")

        kubernetes_service._batch_api.list_namespaced_job.assert_called_once_with(
            namespace="test-ns",
            label_selector=None,
        )
        assert len(result) == 2
        assert result[0]["metadata"]["name"] == "job-1"

    def test_list_jobs_with_label_selector(self, kubernetes_service):
        """Test Job listing with label selector."""
        mock_result = MagicMock()
        mock_result.items = []
        kubernetes_service._batch_api.list_namespaced_job.return_value = mock_result

        kubernetes_service.list_jobs("test-ns", label_selector="kagenti.io/type=agent")

        kubernetes_service._batch_api.list_namespaced_job.assert_called_once_with(
            namespace="test-ns",
            label_selector="kagenti.io/type=agent",
        )

    def test_list_jobs_api_error(self, kubernetes_service):
        """Test Job listing with API error."""
        kubernetes_service._batch_api.list_namespaced_job.side_effect = ApiException(
            status=403, reason="Forbidden"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.list_jobs("test-ns")

        assert exc_info.value.status == 403

    def test_delete_job_success(self, kubernetes_service):
        """Test successful Job deletion."""
        kubernetes_service._batch_api.delete_namespaced_job.return_value = None

        kubernetes_service.delete_job("test-ns", "test-job")

        kubernetes_service._batch_api.delete_namespaced_job.assert_called_once_with(
            name="test-job",
            namespace="test-ns",
            propagation_policy="Background",
        )

    def test_delete_job_not_found(self, kubernetes_service):
        """Test Job deletion when not found."""
        kubernetes_service._batch_api.delete_namespaced_job.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.delete_job("test-ns", "nonexistent")

        assert exc_info.value.status == 404


class TestServiceOperations:
    """Test cases for Service CRUD operations."""

    def test_create_service_success(self, kubernetes_service):
        """Test successful Service creation."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "metadata": {"name": "test-svc", "namespace": "test-ns"},
            "spec": {"type": "ClusterIP", "ports": [{"port": 8080}]},
        }
        kubernetes_service._core_api.create_namespaced_service.return_value = mock_result

        body = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "test-svc"},
            "spec": {"type": "ClusterIP", "ports": [{"port": 8080}]},
        }
        result = kubernetes_service.create_service("test-ns", body)

        kubernetes_service._core_api.create_namespaced_service.assert_called_once_with(
            namespace="test-ns",
            body=body,
        )
        assert result["metadata"]["name"] == "test-svc"

    def test_create_service_api_error(self, kubernetes_service):
        """Test Service creation with API error."""
        kubernetes_service._core_api.create_namespaced_service.side_effect = ApiException(
            status=409, reason="Conflict"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.create_service("test-ns", {"metadata": {"name": "test"}})

        assert exc_info.value.status == 409

    def test_get_service_success(self, kubernetes_service):
        """Test successful Service retrieval."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "metadata": {"name": "test-svc", "namespace": "test-ns"},
            "spec": {"clusterIP": "10.0.0.1"},
        }
        kubernetes_service._core_api.read_namespaced_service.return_value = mock_result

        result = kubernetes_service.get_service("test-ns", "test-svc")

        kubernetes_service._core_api.read_namespaced_service.assert_called_once_with(
            name="test-svc",
            namespace="test-ns",
        )
        assert result["metadata"]["name"] == "test-svc"
        assert result["spec"]["clusterIP"] == "10.0.0.1"

    def test_get_service_not_found(self, kubernetes_service):
        """Test Service retrieval when not found."""
        kubernetes_service._core_api.read_namespaced_service.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.get_service("test-ns", "nonexistent")

        assert exc_info.value.status == 404

    def test_list_services_success(self, kubernetes_service):
        """Test successful Service listing."""
        mock_item1 = MagicMock()
        mock_item1.to_dict.return_value = {"metadata": {"name": "svc-1"}}
        mock_item2 = MagicMock()
        mock_item2.to_dict.return_value = {"metadata": {"name": "svc-2"}}

        mock_result = MagicMock()
        mock_result.items = [mock_item1, mock_item2]
        kubernetes_service._core_api.list_namespaced_service.return_value = mock_result

        result = kubernetes_service.list_services("test-ns")

        kubernetes_service._core_api.list_namespaced_service.assert_called_once_with(
            namespace="test-ns",
            label_selector=None,
        )
        assert len(result) == 2
        assert result[0]["metadata"]["name"] == "svc-1"

    def test_list_services_with_label_selector(self, kubernetes_service):
        """Test Service listing with label selector."""
        mock_result = MagicMock()
        mock_result.items = []
        kubernetes_service._core_api.list_namespaced_service.return_value = mock_result

        kubernetes_service.list_services("test-ns", label_selector="app=test")

        kubernetes_service._core_api.list_namespaced_service.assert_called_once_with(
            namespace="test-ns",
            label_selector="app=test",
        )

    def test_list_services_api_error(self, kubernetes_service):
        """Test Service listing with API error."""
        kubernetes_service._core_api.list_namespaced_service.side_effect = ApiException(
            status=403, reason="Forbidden"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.list_services("test-ns")

        assert exc_info.value.status == 403

    def test_delete_service_success(self, kubernetes_service):
        """Test successful Service deletion."""
        kubernetes_service._core_api.delete_namespaced_service.return_value = None

        kubernetes_service.delete_service("test-ns", "test-svc")

        kubernetes_service._core_api.delete_namespaced_service.assert_called_once_with(
            name="test-svc",
            namespace="test-ns",
        )

    def test_delete_service_not_found(self, kubernetes_service):
        """Test Service deletion when not found."""
        kubernetes_service._core_api.delete_namespaced_service.side_effect = ApiException(
            status=404, reason="Not Found"
        )

        with pytest.raises(ApiException) as exc_info:
            kubernetes_service.delete_service("test-ns", "nonexistent")

        assert exc_info.value.status == 404


class TestApiClientInitialization:
    """Test cases for API client lazy initialization."""

    def test_apps_api_lazy_init(self, kubernetes_service):
        """Test that apps_api is lazily initialized."""
        # Reset to test lazy init
        kubernetes_service._apps_api = None

        with patch("app.services.kubernetes.kubernetes.client.AppsV1Api") as mock_apps_api:
            mock_apps_api.return_value = MagicMock()
            # Access the property
            _ = kubernetes_service.apps_api
            # Should be initialized now
            assert kubernetes_service._apps_api is not None

    def test_batch_api_lazy_init(self, kubernetes_service):
        """Test that batch_api is lazily initialized."""
        # Reset to test lazy init
        kubernetes_service._batch_api = None

        with patch("app.services.kubernetes.kubernetes.client.BatchV1Api") as mock_batch_api:
            mock_batch_api.return_value = MagicMock()
            # Access the property
            _ = kubernetes_service.batch_api
            # Should be initialized now
            assert kubernetes_service._batch_api is not None

    def test_core_api_lazy_init(self, kubernetes_service):
        """Test that core_api is lazily initialized."""
        # Reset to test lazy init
        kubernetes_service._core_api = None

        with patch("app.services.kubernetes.kubernetes.client.CoreV1Api") as mock_core_api:
            mock_core_api.return_value = MagicMock()
            # Access the property
            _ = kubernetes_service.core_api
            # Should be initialized now
            assert kubernetes_service._core_api is not None


class TestNamespaceOperations:
    """Test cases for namespace operations."""

    def test_list_namespaces_success(self, kubernetes_service):
        """Test successful namespace listing."""
        mock_ns1 = MagicMock()
        mock_ns1.metadata.name = "ns-1"
        mock_ns2 = MagicMock()
        mock_ns2.metadata.name = "ns-2"

        mock_result = MagicMock()
        mock_result.items = [mock_ns1, mock_ns2]
        kubernetes_service._core_api.list_namespace.return_value = mock_result

        result = kubernetes_service.list_namespaces()

        kubernetes_service._core_api.list_namespace.assert_called_once_with(
            label_selector=None,
            timeout_seconds=10,
        )
        assert len(result) == 2
        assert "ns-1" in result
        assert "ns-2" in result

    def test_list_namespaces_with_label_selector(self, kubernetes_service):
        """Test namespace listing with label selector."""
        mock_result = MagicMock()
        mock_result.items = []
        kubernetes_service._core_api.list_namespace.return_value = mock_result

        kubernetes_service.list_namespaces(label_selector="kagenti-enabled=true")

        kubernetes_service._core_api.list_namespace.assert_called_once_with(
            label_selector="kagenti-enabled=true",
            timeout_seconds=10,
        )

    def test_list_namespaces_api_error_returns_default(self, kubernetes_service):
        """Test namespace listing returns default on API error."""
        kubernetes_service._core_api.list_namespace.side_effect = ApiException(
            status=403, reason="Forbidden"
        )

        result = kubernetes_service.list_namespaces()

        assert result == ["default"]

    def test_list_enabled_namespaces(self, kubernetes_service):
        """Test listing namespaces with kagenti-enabled label."""
        mock_ns = MagicMock()
        mock_ns.metadata.name = "team1"

        mock_result = MagicMock()
        mock_result.items = [mock_ns]
        kubernetes_service._core_api.list_namespace.return_value = mock_result

        result = kubernetes_service.list_enabled_namespaces()

        kubernetes_service._core_api.list_namespace.assert_called_once_with(
            label_selector="kagenti-enabled=true",
            timeout_seconds=10,
        )
        assert result == ["team1"]


class TestCustomResourceOperations:
    """Test cases for custom resource operations."""

    def test_list_custom_resources_success(self, kubernetes_service):
        """Test successful custom resource listing."""
        kubernetes_service._custom_api = MagicMock()
        kubernetes_service._custom_api.list_namespaced_custom_object.return_value = {
            "items": [
                {"metadata": {"name": "agent-1"}},
                {"metadata": {"name": "agent-2"}},
            ]
        }

        result = kubernetes_service.list_custom_resources(
            group="agent.kagenti.dev",
            version="v1alpha1",
            namespace="test-ns",
            plural="agents",
        )

        assert len(result) == 2
        assert result[0]["metadata"]["name"] == "agent-1"

    def test_get_custom_resource_success(self, kubernetes_service):
        """Test successful custom resource retrieval."""
        kubernetes_service._custom_api = MagicMock()
        kubernetes_service._custom_api.get_namespaced_custom_object.return_value = {
            "metadata": {"name": "test-agent"},
            "spec": {"description": "Test agent"},
        }

        result = kubernetes_service.get_custom_resource(
            group="agent.kagenti.dev",
            version="v1alpha1",
            namespace="test-ns",
            plural="agents",
            name="test-agent",
        )

        assert result["metadata"]["name"] == "test-agent"

    def test_create_custom_resource_success(self, kubernetes_service):
        """Test successful custom resource creation."""
        kubernetes_service._custom_api = MagicMock()
        kubernetes_service._custom_api.create_namespaced_custom_object.return_value = {
            "metadata": {"name": "new-agent"},
        }

        body = {"metadata": {"name": "new-agent"}}
        result = kubernetes_service.create_custom_resource(
            group="agent.kagenti.dev",
            version="v1alpha1",
            namespace="test-ns",
            plural="agents",
            body=body,
        )

        assert result["metadata"]["name"] == "new-agent"

    def test_delete_custom_resource_success(self, kubernetes_service):
        """Test successful custom resource deletion."""
        kubernetes_service._custom_api = MagicMock()
        kubernetes_service._custom_api.delete_namespaced_custom_object.return_value = {}

        kubernetes_service.delete_custom_resource(
            group="agent.kagenti.dev",
            version="v1alpha1",
            namespace="test-ns",
            plural="agents",
            name="test-agent",
        )

        kubernetes_service._custom_api.delete_namespaced_custom_object.assert_called_once()
