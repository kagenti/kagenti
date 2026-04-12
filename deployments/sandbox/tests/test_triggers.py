"""Tests for triggers.py — SandboxClaim creation from events."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from triggers import SandboxTrigger


class TestClaimStructure:
    """Verify SandboxClaim resource structure."""

    def _capture_claim(self, trigger_method, **kwargs):
        """Call a trigger method and capture the kubectl apply input."""
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            trigger_method(**kwargs)
            # kubectl apply -f - receives JSON on stdin
            call_kwargs = mock_run.call_args
            claim_json = call_kwargs.kwargs.get("input") or call_kwargs[1].get("input")
            return json.loads(claim_json)

    def test_cron_claim_api_version(self):
        trigger = SandboxTrigger(namespace="team1")
        claim = self._capture_claim(trigger.create_from_cron, skill="rca:ci")
        assert claim["apiVersion"] == "extensions.agents.x-k8s.io/v1alpha1"
        assert claim["kind"] == "SandboxClaim"

    def test_cron_claim_labels(self):
        trigger = SandboxTrigger(namespace="team1")
        claim = self._capture_claim(
            trigger.create_from_cron, skill="rca:ci", schedule="0 2 * * *"
        )
        labels = claim["metadata"]["labels"]
        assert labels["trigger-type"] == "cron"
        assert labels["trigger-skill"] == "rca:ci"
        assert labels["trigger-schedule"] == "0 2 * * *"
        assert labels["app.kubernetes.io/part-of"] == "kagenti"

    def test_webhook_claim_labels(self):
        trigger = SandboxTrigger(namespace="team2")
        claim = self._capture_claim(
            trigger.create_from_webhook,
            event_type="pull_request",
            repo="kagenti/kagenti",
            branch="feat/x",
            pr_number=42,
        )
        labels = claim["metadata"]["labels"]
        assert labels["trigger-type"] == "webhook"
        assert labels["trigger-event"] == "pull_request"
        assert labels["trigger-repo"] == "kagenti/kagenti"
        assert labels["trigger-pr"] == "42"
        assert claim["metadata"]["namespace"] == "team2"

    def test_alert_claim_labels(self):
        trigger = SandboxTrigger()
        claim = self._capture_claim(
            trigger.create_from_alert,
            alert_name="PodCrashLoop",
            cluster="prod",
            severity="critical",
        )
        labels = claim["metadata"]["labels"]
        assert labels["trigger-type"] == "alert"
        assert labels["trigger-alert"] == "PodCrashLoop"
        assert labels["trigger-severity"] == "critical"


class TestLifecycle:
    """Verify TTL and shutdown policy."""

    def test_ttl_calculation(self):
        trigger = SandboxTrigger(ttl_hours=4)
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            trigger.create_from_cron(skill="test")
            claim = json.loads(
                mock_run.call_args.kwargs.get("input")
                or mock_run.call_args[1].get("input")
            )
            lifecycle = claim["spec"]["lifecycle"]
            assert lifecycle["shutdownPolicy"] == "Delete"
            # shutdownTime should be parseable and in the future
            shutdown = datetime.strptime(
                lifecycle["shutdownTime"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
            assert shutdown > datetime.now(timezone.utc)

    def test_template_ref(self):
        trigger = SandboxTrigger(template="my-custom-template")
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            trigger.create_from_cron(skill="test")
            claim = json.loads(
                mock_run.call_args.kwargs.get("input")
                or mock_run.call_args[1].get("input")
            )
            assert claim["spec"]["sandboxTemplateRef"]["name"] == "my-custom-template"


class TestErrors:
    """Test error handling."""

    def test_kubectl_failure_raises(self):
        trigger = SandboxTrigger()
        mock_result = MagicMock(returncode=1, stderr="error: connection refused")
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Failed to create SandboxClaim"):
                trigger.create_from_cron(skill="test")
