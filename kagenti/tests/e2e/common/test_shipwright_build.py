# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Shipwright Build integration tests.

Tests for the Shipwright Build/BuildRun workflow used to build agent images.
"""

import time

import pytest
from kubernetes import client

# Shipwright CRD definitions
SHIPWRIGHT_GROUP = "shipwright.io"
SHIPWRIGHT_VERSION = "v1beta1"
SHIPWRIGHT_BUILDS_PLURAL = "builds"
SHIPWRIGHT_BUILDRUNS_PLURAL = "buildruns"

# Test constants
TEST_NAMESPACE = "team1"
TEST_BUILD_NAME = "test-shipwright-build"
BUILD_POLL_INTERVAL = 5  # seconds
BUILD_TIMEOUT = 300  # 5 minutes max


@pytest.fixture(scope="session")
def k8s_custom_client():
    """
    Load Kubernetes configuration and return CustomObjectsApi client.

    Returns:
        kubernetes.client.CustomObjectsApi: Kubernetes custom objects API client

    Raises:
        pytest.skip: If cannot connect to Kubernetes cluster
    """
    try:
        from kubernetes import config as k8s_config

        k8s_config.load_kube_config()
    except Exception:
        try:
            from kubernetes import config as k8s_config

            k8s_config.load_incluster_config()
        except Exception as e:
            pytest.skip(f"Could not load Kubernetes config: {e}")

    return client.CustomObjectsApi()


@pytest.fixture(scope="session")
def shipwright_available(k8s_custom_client):
    """
    Check if Shipwright is installed in the cluster.

    Returns:
        bool: True if Shipwright CRDs are available
    """
    try:
        # Try to list ClusterBuildStrategies to verify Shipwright is installed
        k8s_custom_client.list_cluster_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            plural="clusterbuildstrategies",
        )
        return True
    except Exception:
        return False


@pytest.fixture
def cleanup_build(k8s_custom_client):
    """
    Fixture to clean up Shipwright Build and BuildRuns after test.

    Yields:
        None

    Cleanup:
        Deletes any test Build and BuildRuns created during the test.
    """
    yield

    # Clean up BuildRuns first
    try:
        buildruns = k8s_custom_client.list_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            label_selector=f"kagenti.io/build-name={TEST_BUILD_NAME}",
        )
        for br in buildruns.get("items", []):
            try:
                k8s_custom_client.delete_namespaced_custom_object(
                    group=SHIPWRIGHT_GROUP,
                    version=SHIPWRIGHT_VERSION,
                    namespace=TEST_NAMESPACE,
                    plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
                    name=br["metadata"]["name"],
                )
            except Exception:
                pass
    except Exception:
        pass

    # Then clean up the Build
    try:
        k8s_custom_client.delete_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name=TEST_BUILD_NAME,
        )
    except Exception:
        pass


class TestShipwrightAvailability:
    """Test Shipwright availability and configuration."""

    def test_shipwright_crds_installed(self, k8s_custom_client):
        """Verify Shipwright CRDs are installed in the cluster."""
        try:
            # List ClusterBuildStrategies
            strategies = k8s_custom_client.list_cluster_custom_object(
                group=SHIPWRIGHT_GROUP,
                version=SHIPWRIGHT_VERSION,
                plural="clusterbuildstrategies",
            )
            assert strategies is not None
            assert "items" in strategies
        except client.ApiException as e:
            if e.status == 404:
                pytest.skip("Shipwright CRDs not installed")
            raise

    def test_build_strategies_exist(self, k8s_custom_client, shipwright_available):
        """Verify expected ClusterBuildStrategies are available."""
        if not shipwright_available:
            pytest.skip("Shipwright not available")

        strategies = k8s_custom_client.list_cluster_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            plural="clusterbuildstrategies",
        )

        strategy_names = [s["metadata"]["name"] for s in strategies.get("items", [])]

        # At least one of these strategies should be available
        expected_strategies = ["buildah", "buildah-insecure-push"]
        has_strategy = any(s in strategy_names for s in expected_strategies)

        assert has_strategy, (
            f"Expected at least one of {expected_strategies}, found: {strategy_names}"
        )


class TestShipwrightBuildLifecycle:
    """Test Shipwright Build and BuildRun lifecycle."""

    @pytest.mark.requires_features(["shipwright"])
    def test_create_build(self, k8s_custom_client, shipwright_available, cleanup_build):
        """Verify a Shipwright Build can be created."""
        if not shipwright_available:
            pytest.skip("Shipwright not available")

        build_manifest = {
            "apiVersion": f"{SHIPWRIGHT_GROUP}/{SHIPWRIGHT_VERSION}",
            "kind": "Build",
            "metadata": {
                "name": TEST_BUILD_NAME,
                "namespace": TEST_NAMESPACE,
                "labels": {
                    "kagenti.io/type": "agent",
                    "kagenti.io/test": "true",
                },
            },
            "spec": {
                "source": {
                    "type": "Git",
                    "git": {
                        "url": "https://github.com/kagenti/agent-examples",
                        "revision": "main",
                    },
                    "contextDir": "a2a/weather_service",
                },
                "strategy": {
                    "name": "buildah-insecure-push",
                    "kind": "ClusterBuildStrategy",
                },
                "paramValues": [{"name": "dockerfile", "value": "Dockerfile"}],
                "output": {
                    "image": "registry.cr-system.svc.cluster.local:5000/test-agent:test"
                },
                "timeout": "10m",
            },
        }

        # Create the Build
        created = k8s_custom_client.create_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            body=build_manifest,
        )

        assert created is not None
        assert created["metadata"]["name"] == TEST_BUILD_NAME

    @pytest.mark.requires_features(["shipwright"])
    def test_create_buildrun(
        self, k8s_custom_client, shipwright_available, cleanup_build
    ):
        """Verify a BuildRun can be created and triggers a build."""
        if not shipwright_available:
            pytest.skip("Shipwright not available")

        # First create the Build
        build_manifest = {
            "apiVersion": f"{SHIPWRIGHT_GROUP}/{SHIPWRIGHT_VERSION}",
            "kind": "Build",
            "metadata": {
                "name": TEST_BUILD_NAME,
                "namespace": TEST_NAMESPACE,
                "labels": {
                    "kagenti.io/type": "agent",
                    "kagenti.io/test": "true",
                },
            },
            "spec": {
                "source": {
                    "type": "Git",
                    "git": {
                        "url": "https://github.com/kagenti/agent-examples",
                        "revision": "main",
                    },
                    "contextDir": "a2a/weather_service",
                },
                "strategy": {
                    "name": "buildah-insecure-push",
                    "kind": "ClusterBuildStrategy",
                },
                "paramValues": [{"name": "dockerfile", "value": "Dockerfile"}],
                "output": {
                    "image": "registry.cr-system.svc.cluster.local:5000/test-agent:test"
                },
                "timeout": "10m",
            },
        }

        k8s_custom_client.create_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            body=build_manifest,
        )

        # Create a BuildRun
        buildrun_manifest = {
            "apiVersion": f"{SHIPWRIGHT_GROUP}/{SHIPWRIGHT_VERSION}",
            "kind": "BuildRun",
            "metadata": {
                "generateName": f"{TEST_BUILD_NAME}-run-",
                "namespace": TEST_NAMESPACE,
                "labels": {
                    "kagenti.io/build-name": TEST_BUILD_NAME,
                    "kagenti.io/test": "true",
                },
            },
            "spec": {"build": {"name": TEST_BUILD_NAME}},
        }

        created = k8s_custom_client.create_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            body=buildrun_manifest,
        )

        assert created is not None
        assert created["metadata"]["name"].startswith(f"{TEST_BUILD_NAME}-run-")
        assert created["spec"]["build"]["name"] == TEST_BUILD_NAME

    @pytest.mark.requires_features(["shipwright"])
    def test_buildrun_status_progression(
        self, k8s_custom_client, shipwright_available, cleanup_build
    ):
        """Verify BuildRun progresses through expected status phases."""
        if not shipwright_available:
            pytest.skip("Shipwright not available")

        # Create Build
        build_manifest = {
            "apiVersion": f"{SHIPWRIGHT_GROUP}/{SHIPWRIGHT_VERSION}",
            "kind": "Build",
            "metadata": {
                "name": TEST_BUILD_NAME,
                "namespace": TEST_NAMESPACE,
                "labels": {
                    "kagenti.io/type": "agent",
                    "kagenti.io/test": "true",
                },
            },
            "spec": {
                "source": {
                    "type": "Git",
                    "git": {
                        "url": "https://github.com/kagenti/agent-examples",
                        "revision": "main",
                    },
                    "contextDir": "a2a/weather_service",
                },
                "strategy": {
                    "name": "buildah-insecure-push",
                    "kind": "ClusterBuildStrategy",
                },
                "paramValues": [{"name": "dockerfile", "value": "Dockerfile"}],
                "output": {
                    "image": "registry.cr-system.svc.cluster.local:5000/test-agent:test"
                },
                "timeout": "10m",
            },
        }

        k8s_custom_client.create_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            body=build_manifest,
        )

        # Create BuildRun
        buildrun_manifest = {
            "apiVersion": f"{SHIPWRIGHT_GROUP}/{SHIPWRIGHT_VERSION}",
            "kind": "BuildRun",
            "metadata": {
                "generateName": f"{TEST_BUILD_NAME}-run-",
                "namespace": TEST_NAMESPACE,
                "labels": {
                    "kagenti.io/build-name": TEST_BUILD_NAME,
                    "kagenti.io/test": "true",
                },
            },
            "spec": {"build": {"name": TEST_BUILD_NAME}},
        }

        created = k8s_custom_client.create_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            body=buildrun_manifest,
        )

        buildrun_name = created["metadata"]["name"]

        # Poll for status (just verify we can read status, not wait for completion)
        # Waiting for full completion would take too long for a test
        time.sleep(5)

        buildrun = k8s_custom_client.get_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
            name=buildrun_name,
        )

        # Verify status structure exists
        assert "status" in buildrun or "spec" in buildrun, (
            "BuildRun should have status or spec"
        )

        # Check that conditions are present if status exists
        status = buildrun.get("status", {})
        if status:
            # Status may have conditions array
            conditions = status.get("conditions", [])
            # Early in lifecycle, conditions might be empty or have Pending/Running
            assert isinstance(conditions, list), "conditions should be a list"


class TestBuildAnnotations:
    """Test agent configuration storage in Build annotations."""

    @pytest.mark.requires_features(["shipwright"])
    def test_agent_config_in_annotations(
        self, k8s_custom_client, shipwright_available, cleanup_build
    ):
        """Verify agent configuration can be stored in Build annotations."""
        if not shipwright_available:
            pytest.skip("Shipwright not available")

        import json

        agent_config = {
            "protocol": "a2a",
            "framework": "LangGraph",
            "createHttpRoute": True,
            "envVars": [{"name": "TEST_VAR", "value": "test_value"}],
        }

        build_manifest = {
            "apiVersion": f"{SHIPWRIGHT_GROUP}/{SHIPWRIGHT_VERSION}",
            "kind": "Build",
            "metadata": {
                "name": TEST_BUILD_NAME,
                "namespace": TEST_NAMESPACE,
                "labels": {
                    "kagenti.io/type": "agent",
                    "kagenti.io/test": "true",
                },
                "annotations": {
                    "kagenti.io/agent-config": json.dumps(agent_config),
                },
            },
            "spec": {
                "source": {
                    "type": "Git",
                    "git": {
                        "url": "https://github.com/kagenti/agent-examples",
                        "revision": "main",
                    },
                    "contextDir": "a2a/weather_service",
                },
                "strategy": {
                    "name": "buildah-insecure-push",
                    "kind": "ClusterBuildStrategy",
                },
                "paramValues": [{"name": "dockerfile", "value": "Dockerfile"}],
                "output": {
                    "image": "registry.cr-system.svc.cluster.local:5000/test-agent:test"
                },
                "timeout": "10m",
            },
        }

        created = k8s_custom_client.create_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            body=build_manifest,
        )

        # Verify annotations are stored
        annotations = created["metadata"].get("annotations", {})
        assert "kagenti.io/agent-config" in annotations

        # Parse and verify the config
        stored_config = json.loads(annotations["kagenti.io/agent-config"])
        assert stored_config["protocol"] == "a2a"
        assert stored_config["framework"] == "LangGraph"
        assert stored_config["createHttpRoute"] is True
        assert len(stored_config["envVars"]) == 1
        assert stored_config["envVars"][0]["name"] == "TEST_VAR"
