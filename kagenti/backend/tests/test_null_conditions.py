"""
Tests for handling null conditions in Kubernetes status responses.

Kubernetes resources that haven't fully reconciled can have
`status.conditions: null` rather than an empty list or a missing key.
This caused TypeError crashes when iterating over conditions.

See: https://github.com/kagenti/kagenti/pull/1241
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.routers.tools import _get_workload_status  # noqa: E402
from app.routers.agents import _is_deployment_ready  # noqa: E402


class TestNullConditionsHandling:
    """Verify status functions don't crash when conditions is None."""

    def test_tool_workload_status_with_null_conditions(self):
        """_get_workload_status should not crash when conditions is null."""
        workload = {
            "spec": {"replicas": 1},
            "status": {
                "readyReplicas": 0,
                "availableReplicas": 0,
                "conditions": None,
            },
        }
        result = _get_workload_status(workload)
        assert result == "Not Ready"

    def test_tool_workload_status_with_missing_conditions(self):
        """_get_workload_status should handle missing conditions key."""
        workload = {
            "spec": {"replicas": 1},
            "status": {
                "readyReplicas": 0,
                "availableReplicas": 0,
            },
        }
        result = _get_workload_status(workload)
        assert result == "Not Ready"

    def test_tool_workload_status_with_empty_conditions(self):
        """_get_workload_status should handle empty conditions list."""
        workload = {
            "spec": {"replicas": 1},
            "status": {
                "readyReplicas": 0,
                "availableReplicas": 0,
                "conditions": [],
            },
        }
        result = _get_workload_status(workload)
        assert result == "Not Ready"

    def test_tool_workload_status_ready_with_null_conditions(self):
        """Ready workload should still return Ready even with null conditions."""
        workload = {
            "spec": {"replicas": 1},
            "status": {
                "readyReplicas": 1,
                "availableReplicas": 1,
                "conditions": None,
            },
        }
        result = _get_workload_status(workload)
        assert result == "Ready"

    def test_agent_deployment_ready_with_null_conditions(self):
        """_is_deployment_ready should not crash when conditions is null."""
        resource = {
            "spec": {"replicas": 1},
            "status": {
                "readyReplicas": 0,
                "availableReplicas": 0,
                "conditions": None,
            },
        }
        result = _is_deployment_ready(resource)
        assert result == "Not Ready"

    def test_agent_deployment_ready_with_missing_status(self):
        """_is_deployment_ready should handle completely missing status."""
        resource = {"spec": {"replicas": 1}}
        result = _is_deployment_ready(resource)
        assert result == "Not Ready"
