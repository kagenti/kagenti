# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for agent/deployment readiness check functions.
"""

import pytest
from app.routers.agents import _is_deployment_ready, _is_statefulset_ready


class TestDeploymentReadiness:
    """Tests for _is_deployment_ready function."""

    def test_deployment_ready_with_replicas(self):
        """Test deployment is ready when replicas match ready_replicas."""
        resource_data = {"status": {"replicas": 3, "readyReplicas": 3}}
        assert _is_deployment_ready(resource_data) == "Ready"

    def test_deployment_not_ready_with_fewer_ready_replicas(self):
        """Test deployment is not ready when ready_replicas < replicas."""
        resource_data = {"status": {"replicas": 3, "readyReplicas": 1}}
        assert _is_deployment_ready(resource_data) == "Not Ready"

    def test_deployment_with_none_replicas(self):
        """Test deployment handles None replicas value without crashing.

        This is the bug fix: when status contains replicas: null,
        status.get("replicas", 0) returns None instead of 0,
        causing TypeError on comparison.
        """
        resource_data = {
            "status": {
                "replicas": None,  # This is what causes the bug
                "readyReplicas": 0,
            }
        }
        # Should not raise TypeError: '>' not supported between instances of 'NoneType' and 'int'
        result = _is_deployment_ready(resource_data)
        assert result == "Not Ready"  # 0 replicas means not ready

    def test_deployment_with_none_replicas_and_ready_replicas(self):
        """Test deployment handles None replicas with non-zero ready replicas."""
        resource_data = {"status": {"replicas": None, "readyReplicas": 1}}
        result = _is_deployment_ready(resource_data)
        assert result == "Not Ready"

    def test_deployment_with_missing_replicas_key(self):
        """Test deployment handles missing replicas key."""
        resource_data = {"status": {"readyReplicas": 3}}
        result = _is_deployment_ready(resource_data)
        assert result == "Not Ready"

    def test_deployment_with_zero_replicas(self):
        """Test deployment with zero replicas."""
        resource_data = {"status": {"replicas": 0, "readyReplicas": 0}}
        result = _is_deployment_ready(resource_data)
        assert result == "Not Ready"


class TestStatefulSetReadiness:
    """Tests for _is_statefulset_ready function."""

    def test_statefulset_ready(self):
        """Test statefulset is ready when replicas match ready_replicas."""
        resource_data = {"status": {"replicas": 3, "readyReplicas": 3}}
        assert _is_statefulset_ready(resource_data) == "Ready"

    def test_statefulset_progressing(self):
        """Test statefulset is progressing when some replicas are ready."""
        resource_data = {"status": {"replicas": 3, "readyReplicas": 1}}
        assert _is_statefulset_ready(resource_data) == "Progressing"

    def test_statefulset_not_ready(self):
        """Test statefulset is not ready when no replicas are ready."""
        resource_data = {"status": {"replicas": 3, "readyReplicas": 0}}
        assert _is_statefulset_ready(resource_data) == "Not Ready"

    def test_statefulset_with_none_replicas(self):
        """Test statefulset handles None replicas value without crashing.

        This is the bug fix: when status contains replicas: null,
        status.get("replicas", 0) returns None instead of 0,
        causing TypeError on comparison.
        """
        resource_data = {
            "status": {
                "replicas": None,  # This is what causes the bug
                "readyReplicas": 0,
            }
        }
        # Should not raise TypeError
        result = _is_statefulset_ready(resource_data)
        assert result == "Not Ready"  # 0 replicas means not ready

    def test_statefulset_with_none_replicas_and_ready_replicas(self):
        """Test statefulset handles None replicas with non-zero ready replicas."""
        resource_data = {"status": {"replicas": None, "readyReplicas": 2}}
        result = _is_statefulset_ready(resource_data)
        # With replicas=None (treated as 0) and ready_replicas=2,
        # it should be "Not Ready" since replicas == 0
        assert result == "Not Ready"

    def test_statefulset_with_missing_replicas_key(self):
        """Test statefulset handles missing replicas key."""
        resource_data = {"status": {"readyReplicas": 3}}
        result = _is_statefulset_ready(resource_data)
        assert result == "Not Ready"

    def test_statefulset_with_zero_replicas(self):
        """Test statefulset with zero replicas."""
        resource_data = {"status": {"replicas": 0, "readyReplicas": 0}}
        result = _is_statefulset_ready(resource_data)
        assert result == "Not Ready"
