# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for Agent CRD to Deployment migration functionality (Phase 4).
"""

import pytest
from unittest.mock import MagicMock, patch

# IMPORTANT: Mock Setup Before Import Pattern
# ============================================
# The migration script (migrate_agents.py) has a bare `import kubernetes` at the
# top level, followed by a try-except that catches ImportError and exits with a
# clear error message if the kubernetes package isn't installed.
#
# For testing without a real Kubernetes cluster (or without the kubernetes package
# installed), we must mock the kubernetes modules BEFORE importing the migration
# script. This is achieved using patch.dict on sys.modules within a `with` block.
#
# Why this pattern is necessary:
# 1. Python caches imported modules in sys.modules
# 2. The `import kubernetes` statement in migrate_agents.py executes immediately
#    when the module is first imported
# 3. By pre-populating sys.modules with mocked versions, Python finds our mocks
#    instead of trying to import the real kubernetes package
# 4. This allows tests to run in CI environments without kubernetes installed
#
# Note: The `with` block ensures the mocks are in place during the import.
# After the import, the module is cached and subsequent accesses use the
# already-imported (mocked) version.
with patch.dict(
    "sys.modules",
    {
        "kubernetes": MagicMock(),
        "kubernetes.client": MagicMock(),
        "kubernetes.config": MagicMock(),
    },
):
    from kagenti.tools.migrate_agents import (
        build_deployment_from_agent_crd,
        build_service_from_agent_crd,
        KAGENTI_TYPE_LABEL,
        KAGENTI_WORKLOAD_TYPE_LABEL,
        APP_KUBERNETES_IO_NAME,
        APP_KUBERNETES_IO_MANAGED_BY,
        MIGRATION_SOURCE_ANNOTATION,
        MIGRATION_TIMESTAMP_ANNOTATION,
        RESOURCE_TYPE_AGENT,
        WORKLOAD_TYPE_DEPLOYMENT,
        KAGENTI_UI_CREATOR_LABEL,
    )


class TestBuildDeploymentFromAgentCRD:
    """Test cases for build_deployment_from_agent_crd function."""

    def test_basic_deployment_from_agent_crd(self):
        """Test building a Deployment from a basic Agent CRD."""
        agent_crd = {
            "metadata": {
                "name": "test-agent",
                "namespace": "test-ns",
                "labels": {
                    "kagenti.io/type": "agent",
                    "kagenti.io/protocol": "a2a",
                },
            },
            "spec": {
                "description": "Test agent description",
                "replicas": 2,
                "imageSource": {
                    "image": "registry.example.com/test-agent:v1.0.0",
                },
                "servicePorts": [
                    {"name": "http", "port": 8080, "targetPort": 8000},
                ],
            },
        }

        deployment = build_deployment_from_agent_crd(agent_crd)

        # Verify basic structure
        assert deployment["apiVersion"] == "apps/v1"
        assert deployment["kind"] == "Deployment"
        assert deployment["metadata"]["name"] == "test-agent"
        assert deployment["metadata"]["namespace"] == "test-ns"

        # Verify labels
        labels = deployment["metadata"]["labels"]
        assert labels[KAGENTI_WORKLOAD_TYPE_LABEL] == WORKLOAD_TYPE_DEPLOYMENT
        assert labels[APP_KUBERNETES_IO_MANAGED_BY] == KAGENTI_UI_CREATOR_LABEL

        # Verify annotations
        annotations = deployment["metadata"]["annotations"]
        assert annotations[MIGRATION_SOURCE_ANNOTATION] == "agent-crd"
        assert MIGRATION_TIMESTAMP_ANNOTATION in annotations

        # Verify spec
        assert deployment["spec"]["replicas"] == 2

        # Verify selector
        selector = deployment["spec"]["selector"]["matchLabels"]
        assert selector[KAGENTI_TYPE_LABEL] == RESOURCE_TYPE_AGENT
        assert selector[APP_KUBERNETES_IO_NAME] == "test-agent"

    def test_deployment_with_pod_template_spec(self):
        """Test building a Deployment from Agent CRD with podTemplateSpec."""
        agent_crd = {
            "metadata": {
                "name": "agent-with-template",
                "namespace": "default",
                "labels": {"kagenti.io/type": "agent"},
            },
            "spec": {
                "replicas": 1,
                "podTemplateSpec": {
                    "spec": {
                        "containers": [
                            {
                                "name": "custom-agent",
                                "image": "my-image:latest",
                                "env": [{"name": "MY_VAR", "value": "my-value"}],
                            }
                        ],
                    },
                },
            },
        }

        deployment = build_deployment_from_agent_crd(agent_crd)

        # Verify pod spec is preserved
        pod_spec = deployment["spec"]["template"]["spec"]
        assert len(pod_spec["containers"]) == 1
        assert pod_spec["containers"][0]["name"] == "custom-agent"
        assert pod_spec["containers"][0]["image"] == "my-image:latest"
        assert pod_spec["containers"][0]["env"][0]["name"] == "MY_VAR"

    def test_deployment_without_image_raises_error(self):
        """Test that missing image raises an error."""
        agent_crd = {
            "metadata": {
                "name": "bad-agent",
                "namespace": "default",
                "labels": {},
            },
            "spec": {},
        }

        with pytest.raises(ValueError) as exc_info:
            build_deployment_from_agent_crd(agent_crd)

        assert "has no podTemplateSpec or imageSource.image" in str(exc_info.value)


class TestBuildServiceFromAgentCRD:
    """Test cases for build_service_from_agent_crd function."""

    def test_basic_service_from_agent_crd(self):
        """Test building a Service from a basic Agent CRD."""
        agent_crd = {
            "metadata": {
                "name": "test-agent",
                "namespace": "test-ns",
                "labels": {"kagenti.io/type": "agent"},
            },
            "spec": {
                "servicePorts": [
                    {"name": "http", "port": 8080, "targetPort": 8000, "protocol": "TCP"},
                ],
            },
        }

        service = build_service_from_agent_crd(agent_crd)

        # Verify basic structure
        assert service["apiVersion"] == "v1"
        assert service["kind"] == "Service"
        assert service["metadata"]["name"] == "test-agent"
        assert service["metadata"]["namespace"] == "test-ns"

        # Verify spec
        assert service["spec"]["type"] == "ClusterIP"

        # Verify selector
        selector = service["spec"]["selector"]
        assert selector[KAGENTI_TYPE_LABEL] == RESOURCE_TYPE_AGENT
        assert selector[APP_KUBERNETES_IO_NAME] == "test-agent"

        # Verify ports
        ports = service["spec"]["ports"]
        assert len(ports) == 1
        assert ports[0]["name"] == "http"
        assert ports[0]["port"] == 8080
        assert ports[0]["targetPort"] == 8000

    def test_service_with_default_ports(self):
        """Test that Service uses default ports when not specified."""
        agent_crd = {
            "metadata": {
                "name": "test-agent",
                "namespace": "default",
                "labels": {},
            },
            "spec": {},
        }

        service = build_service_from_agent_crd(agent_crd)

        ports = service["spec"]["ports"]
        assert len(ports) == 1
        assert ports[0]["port"] == 8080  # DEFAULT_OFF_CLUSTER_PORT
        assert ports[0]["targetPort"] == 8000  # DEFAULT_IN_CLUSTER_PORT


class TestMigrationEndpointModels:
    """Test cases for migration API models."""

    def test_migratable_agent_info_model(self):
        """Test MigratableAgentInfo model structure."""
        # This is a placeholder for integration tests
        # The actual model testing would require importing from the backend
        pass

    def test_migrate_agent_response_model(self):
        """Test MigrateAgentResponse model structure."""
        # This is a placeholder for integration tests
        pass
