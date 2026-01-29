# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Integration tests for Shipwright tool builds.

These tests validate end-to-end flows for building and deploying MCP tools
using the Shipwright build system. They run against a real Kubernetes cluster.

After a successful build, tools are deployed as standard Kubernetes Deployments
+ Services (not MCPServer CRDs).
"""

import json
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
TEST_TOOL_BUILD_NAME = "test-tool-shipwright-build"
BUILD_POLL_INTERVAL = 5  # seconds
BUILD_TIMEOUT = 300  # 5 minutes max


def parse_buildrun_phase(buildrun: dict) -> str:
    """Parse BuildRun phase from status conditions.

    This is a local implementation for e2e tests to avoid importing from app module.

    Args:
        buildrun: BuildRun resource dict

    Returns:
        Phase string: Pending, Running, Succeeded, Failed, or Unknown
    """
    status = buildrun.get("status", {})
    conditions = status.get("conditions", [])

    for condition in conditions:
        if condition.get("type") == "Succeeded":
            cond_status = condition.get("status")
            reason = condition.get("reason", "")

            if cond_status == "True":
                return "Succeeded"
            elif cond_status == "False":
                return "Failed"
            elif reason in ("Pending", "Running"):
                return reason

    return "Unknown"


def is_build_succeeded(buildrun: dict) -> bool:
    """Check if BuildRun succeeded."""
    return parse_buildrun_phase(buildrun) == "Succeeded"


def get_latest_buildrun(buildruns: list) -> dict:
    """Get the most recent BuildRun from a list.

    Args:
        buildruns: List of BuildRun resources

    Returns:
        The BuildRun with the latest creationTimestamp
    """
    if not buildruns:
        return None

    return max(
        buildruns,
        key=lambda br: br.get("metadata", {}).get("creationTimestamp", ""),
    )


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
        k8s_custom_client.list_cluster_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            plural="clusterbuildstrategies",
        )
        return True
    except Exception:
        return False


@pytest.fixture
def cleanup_tool_build(k8s_custom_client):
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
            label_selector=f"kagenti.io/build-name={TEST_TOOL_BUILD_NAME}",
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
            name=TEST_TOOL_BUILD_NAME,
        )
    except Exception:
        pass


class TestToolShipwrightBuildIntegration:
    """Integration tests for tool Shipwright build workflow."""

    def test_create_tool_build(
        self, k8s_custom_client, shipwright_available, cleanup_tool_build
    ):
        """Test creating a Shipwright Build for a tool."""
        if not shipwright_available:
            pytest.skip("Shipwright not available")

        # Create Build manifest for a tool
        build_manifest = {
            "apiVersion": f"{SHIPWRIGHT_GROUP}/{SHIPWRIGHT_VERSION}",
            "kind": "Build",
            "metadata": {
                "name": TEST_TOOL_BUILD_NAME,
                "namespace": TEST_NAMESPACE,
                "labels": {
                    "kagenti.io/type": "tool",
                    "kagenti.io/protocol": "streamable_http",
                    "kagenti.io/framework": "Python",
                },
                "annotations": {
                    "kagenti.io/tool-config": json.dumps(
                        {
                            "protocol": "streamable_http",
                            "framework": "Python",
                            "description": "Test weather tool",
                            "createHttpRoute": False,
                        }
                    ),
                },
            },
            "spec": {
                "source": {
                    "type": "Git",
                    "git": {
                        "url": "https://github.com/kagenti/agent-examples",
                        "revision": "main",
                    },
                    "contextDir": "mcp/weather_tool",
                },
                "strategy": {
                    "name": "buildah-insecure-push",
                    "kind": "ClusterBuildStrategy",
                },
                "output": {
                    "image": f"registry.cr-system.svc.cluster.local:5000/{TEST_TOOL_BUILD_NAME}:test",
                },
                "timeout": "10m",
            },
        }

        # Create the Build
        result = k8s_custom_client.create_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            body=build_manifest,
        )

        assert result["metadata"]["name"] == TEST_TOOL_BUILD_NAME
        assert result["metadata"]["labels"]["kagenti.io/type"] == "tool"

    def test_tool_config_stored_in_build_annotations(
        self, k8s_custom_client, shipwright_available, cleanup_tool_build
    ):
        """Test that tool configuration is stored in Build annotations."""
        if not shipwright_available:
            pytest.skip("Shipwright not available")

        tool_config = {
            "protocol": "streamable_http",
            "framework": "Python",
            "description": "Weather lookup tool",
            "createHttpRoute": True,
            "envVars": [{"name": "API_KEY", "value": "test"}],
        }

        # Create Build with tool config annotation
        build_manifest = {
            "apiVersion": f"{SHIPWRIGHT_GROUP}/{SHIPWRIGHT_VERSION}",
            "kind": "Build",
            "metadata": {
                "name": TEST_TOOL_BUILD_NAME,
                "namespace": TEST_NAMESPACE,
                "labels": {
                    "kagenti.io/type": "tool",
                },
                "annotations": {
                    "kagenti.io/tool-config": json.dumps(tool_config),
                },
            },
            "spec": {
                "source": {
                    "type": "Git",
                    "git": {
                        "url": "https://github.com/kagenti/agent-examples",
                        "revision": "main",
                    },
                    "contextDir": "mcp/weather_tool",
                },
                "strategy": {
                    "name": "buildah-insecure-push",
                    "kind": "ClusterBuildStrategy",
                },
                "output": {
                    "image": f"registry.cr-system.svc.cluster.local:5000/{TEST_TOOL_BUILD_NAME}:test",
                },
            },
        }

        k8s_custom_client.create_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            body=build_manifest,
        )

        # Retrieve the Build and verify annotations
        build = k8s_custom_client.get_namespaced_custom_object(
            group=SHIPWRIGHT_GROUP,
            version=SHIPWRIGHT_VERSION,
            namespace=TEST_NAMESPACE,
            plural=SHIPWRIGHT_BUILDS_PLURAL,
            name=TEST_TOOL_BUILD_NAME,
        )

        annotations = build["metadata"].get("annotations", {})
        assert "kagenti.io/tool-config" in annotations

        stored_config = json.loads(annotations["kagenti.io/tool-config"])
        assert stored_config["protocol"] == "streamable_http"
        assert stored_config["framework"] == "Python"
        assert stored_config["createHttpRoute"] is True


class TestToolBuildPhaseDetection:
    """Tests for BuildRun phase detection logic."""

    def test_buildrun_pending_phase(self):
        """Test detecting Pending phase from BuildRun status."""
        buildrun = {
            "status": {
                "conditions": [
                    {"type": "Succeeded", "status": "Unknown", "reason": "Pending"}
                ]
            }
        }
        assert parse_buildrun_phase(buildrun) == "Pending"

    def test_buildrun_running_phase(self):
        """Test detecting Running phase from BuildRun status."""
        buildrun = {
            "status": {
                "conditions": [
                    {"type": "Succeeded", "status": "Unknown", "reason": "Running"}
                ],
                "startTime": "2026-01-21T10:00:00Z",
            }
        }
        assert parse_buildrun_phase(buildrun) == "Running"

    def test_buildrun_succeeded_phase(self):
        """Test detecting Succeeded phase from BuildRun status."""
        buildrun = {
            "status": {
                "conditions": [
                    {"type": "Succeeded", "status": "True", "reason": "Succeeded"}
                ],
                "output": {
                    "image": "registry.local/tool:v1",
                    "digest": "sha256:abc123",
                },
            }
        }
        assert parse_buildrun_phase(buildrun) == "Succeeded"
        assert is_build_succeeded(buildrun) is True

    def test_buildrun_failed_phase(self):
        """Test detecting Failed phase from BuildRun status."""
        buildrun = {
            "status": {
                "conditions": [
                    {
                        "type": "Succeeded",
                        "status": "False",
                        "reason": "Failed",
                        "message": "build failed",
                    }
                ]
            }
        }
        assert parse_buildrun_phase(buildrun) == "Failed"
        assert is_build_succeeded(buildrun) is False


class TestToolBuildRunSelection:
    """Tests for BuildRun selection logic."""

    def test_latest_buildrun_selected(self):
        """Test that the latest BuildRun is selected from a list."""
        buildruns = [
            {
                "metadata": {
                    "name": "tool-run-1",
                    "creationTimestamp": "2026-01-21T10:00:00Z",
                },
                "status": {
                    "conditions": [
                        {"type": "Succeeded", "status": "False", "reason": "Failed"}
                    ]
                },
            },
            {
                "metadata": {
                    "name": "tool-run-2",
                    "creationTimestamp": "2026-01-21T11:00:00Z",
                },
                "status": {
                    "conditions": [
                        {"type": "Succeeded", "status": "Unknown", "reason": "Running"}
                    ]
                },
            },
        ]

        latest = get_latest_buildrun(buildruns)
        assert latest["metadata"]["name"] == "tool-run-2"

    def test_empty_buildrun_list(self):
        """Test handling empty BuildRun list."""
        assert get_latest_buildrun([]) is None


class TestToolBuildErrorScenarios:
    """Tests for build error handling."""

    def test_invalid_git_url_detected(self):
        """Test that invalid git URL failure is detected."""
        failed_buildrun = {
            "status": {
                "conditions": [
                    {
                        "type": "Succeeded",
                        "status": "False",
                        "reason": "Failed",
                        "message": "fatal: repository 'invalid-url' not found",
                    }
                ]
            }
        }
        assert parse_buildrun_phase(failed_buildrun) == "Failed"
        assert is_build_succeeded(failed_buildrun) is False

    def test_missing_dockerfile_detected(self):
        """Test that missing Dockerfile failure is detected."""
        failed_buildrun = {
            "status": {
                "conditions": [
                    {
                        "type": "Succeeded",
                        "status": "False",
                        "reason": "Failed",
                        "message": "unable to find Dockerfile in context",
                    }
                ]
            }
        }
        assert parse_buildrun_phase(failed_buildrun) == "Failed"

    def test_registry_push_failure_detected(self):
        """Test that registry push failure is detected."""
        failed_buildrun = {
            "status": {
                "conditions": [
                    {
                        "type": "Succeeded",
                        "status": "False",
                        "reason": "Failed",
                        "message": "unauthorized: authentication required",
                    }
                ]
            }
        }
        assert parse_buildrun_phase(failed_buildrun) == "Failed"
        assert is_build_succeeded(failed_buildrun) is False
