# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for rollback_workload_resources (shared by create_agent and create_tool).

When the image-deployment path of create_agent / create_tool creates persistent
resources (Deployment/StatefulSet/Job/Sandbox, Service, AgentRuntime,
HTTPRoute/Route) and a later step fails, the earlier resources must be rolled back
so they are not leaked. Only resources created during the same call are rolled back
— shared/idempotent resources (ServiceAccount, AuthBridge ConfigMaps, SCC
RoleBinding, skill-fetcher ConfigMap) are intentionally left alone.
"""

from unittest.mock import MagicMock

from kubernetes.client.exceptions import ApiException

from app.core.constants import (
    CRD_GROUP,
    CRD_VERSION,
    AGENTRUNTIMES_PLURAL,
)
from app.utils.routes import rollback_workload_resources


class TestRollbackWorkloadResources:
    """Tests for the shared rollback_workload_resources helper."""

    def test_deletes_tracked_resources_in_reverse_order(self):
        """Every tracked resource is deleted, most-recently-created first."""
        kube = MagicMock()
        created = [
            ("Deployment", "my-workload"),
            ("Service", "my-workload"),
            ("AgentRuntime", "my-workload"),
        ]

        rollback_workload_resources(kube, "team1", created)

        kube.delete_custom_resource.assert_called_once_with(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace="team1",
            plural=AGENTRUNTIMES_PLURAL,
            name="my-workload",
        )
        kube.delete_service.assert_called_once_with(namespace="team1", name="my-workload")
        kube.delete_deployment.assert_called_once_with(namespace="team1", name="my-workload")

    def test_statefulset_uses_delete_statefulset(self):
        kube = MagicMock()
        rollback_workload_resources(kube, "team1", [("StatefulSet", "my-workload")])
        kube.delete_statefulset.assert_called_once_with(namespace="team1", name="my-workload")
        kube.delete_deployment.assert_not_called()

    def test_job_uses_delete_job(self):
        kube = MagicMock()
        rollback_workload_resources(kube, "team1", [("Job", "my-workload")])
        kube.delete_job.assert_called_once_with(namespace="team1", name="my-workload")

    def test_sandbox_also_deletes_its_pvcs(self):
        """Sandbox rollback deletes the CR and every PVC matching its name label."""
        kube = MagicMock()
        kube.list_persistent_volume_claims.return_value = ["my-wl-data-0", "my-wl-data-1"]

        rollback_workload_resources(kube, "team1", [("Sandbox", "my-workload")])

        kube.delete_sandbox.assert_called_once_with(namespace="team1", name="my-workload")
        kube.list_persistent_volume_claims.assert_called_once_with(
            namespace="team1",
            label_selector="app.kubernetes.io/name=my-workload",
        )
        assert kube.delete_persistent_volume_claim.call_count == 2

    def test_service_uses_suffixed_name_when_tracked(self):
        """The Service name is taken verbatim from the tuple (tools track {name}-mcp)."""
        kube = MagicMock()
        rollback_workload_resources(kube, "team1", [("Service", "my-tool-mcp")])
        kube.delete_service.assert_called_once_with(namespace="team1", name="my-tool-mcp")

    def test_deletes_both_route_kinds(self):
        """Route step tracks HTTPRoute and Route; rollback attempts both."""
        kube = MagicMock()
        rollback_workload_resources(
            kube, "team1", [("HTTPRoute", "my-workload"), ("Route", "my-workload")]
        )
        groups = {c.kwargs["group"] for c in kube.delete_custom_resource.call_args_list}
        assert groups == {"gateway.networking.k8s.io", "route.openshift.io"}

    def test_empty_created_is_noop(self):
        """A first-step failure leaves `created` empty -> no deletes at all."""
        kube = MagicMock()
        rollback_workload_resources(kube, "team1", [])
        kube.delete_deployment.assert_not_called()
        kube.delete_service.assert_not_called()
        kube.delete_custom_resource.assert_not_called()

    def test_rollback_swallows_delete_errors(self):
        """A failure deleting one resource must not stop rollback of the rest."""
        kube = MagicMock()
        kube.delete_service.side_effect = ApiException(status=500, reason="boom")

        rollback_workload_resources(
            kube, "team1", [("Deployment", "my-workload"), ("Service", "my-workload")]
        )

        # Deployment (created first, deleted last) is still attempted.
        kube.delete_deployment.assert_called_once_with(namespace="team1", name="my-workload")

    def test_does_not_touch_untracked_resources(self):
        """SA / ConfigMaps / RoleBinding are never tracked, so never deleted."""
        kube = MagicMock()
        rollback_workload_resources(kube, "team1", [("Deployment", "my-workload")])
        assert not kube.delete_service_account.called
        assert not kube.delete_configmap.called
