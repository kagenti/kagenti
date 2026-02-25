"""
Kagenti Sandbox Triggers — Autonomous sandbox creation (Phase 7, C17)

Creates SandboxClaim resources from trigger events:
- Cron: scheduled tasks (nightly CI health, weekly reports)
- Webhook: GitHub PR events, issue comments with /agent command
- Alert: PagerDuty/Prometheus alerts for incident response

This module provides the trigger logic. Integration with the Kagenti backend
FastAPI app adds the HTTP endpoints.

Usage:
    from triggers import SandboxTrigger
    trigger = SandboxTrigger(namespace="team1", template="kagenti-agent-sandbox")

    # Cron trigger
    trigger.create_from_cron(skill="rca:ci", schedule="0 2 * * *")

    # Webhook trigger (GitHub PR)
    trigger.create_from_webhook(event_type="pull_request", repo="kagenti/kagenti", branch="feat/x")

    # Alert trigger
    trigger.create_from_alert(alert_name="PodCrashLoop", cluster="prod")
"""

import json
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional


class SandboxTrigger:
    """Creates SandboxClaims from trigger events."""

    def __init__(
        self,
        namespace: str = "team1",
        template: str = "kagenti-agent-sandbox",
        ttl_hours: int = 2,
    ):
        self.namespace = namespace
        self.template = template
        self.ttl_hours = ttl_hours

    def _create_claim(
        self, name: str, labels: dict, env_overrides: Optional[dict] = None
    ) -> str:
        """Create a SandboxClaim resource.

        Returns the claim name.
        """
        shutdown_time = (
            datetime.now(timezone.utc) + timedelta(hours=self.ttl_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        claim = {
            "apiVersion": "extensions.agents.x-k8s.io/v1alpha1",
            "kind": "SandboxClaim",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": {
                    "app.kubernetes.io/part-of": "kagenti",
                    "app.kubernetes.io/component": "sandbox-trigger",
                    **labels,
                },
            },
            "spec": {
                "sandboxTemplateRef": {"name": self.template},
                "lifecycle": {
                    "shutdownPolicy": "Delete",
                    "shutdownTime": shutdown_time,
                },
            },
        }

        result = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=json.dumps(claim),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create SandboxClaim: {result.stderr}")

        return name

    def create_from_cron(
        self, skill: str, schedule: str = "", repo_url: str = ""
    ) -> str:
        """Create sandbox from a cron trigger.

        Args:
            skill: The skill to run (e.g., "rca:ci", "k8s:health")
            schedule: Cron expression (for documentation, actual cron runs externally)
            repo_url: Repo to clone in the sandbox
        """
        suffix = uuid.uuid4().hex[:6]
        name = f"cron-{skill.replace(':', '-')}-{suffix}"

        return self._create_claim(
            name,
            labels={
                "trigger-type": "cron",
                "trigger-skill": skill,
                "trigger-schedule": schedule or "manual",
            },
        )

    def create_from_webhook(
        self, event_type: str, repo: str, branch: str = "main", pr_number: int = 0
    ) -> str:
        """Create sandbox from a GitHub webhook event.

        Args:
            event_type: GitHub event (pull_request, issue_comment, check_suite)
            repo: Repository (org/name)
            branch: Branch to check out
            pr_number: PR number (if applicable)
        """
        suffix = uuid.uuid4().hex[:6]
        safe_repo = repo.replace("/", "-")
        name = f"gh-{safe_repo}-{suffix}"

        return self._create_claim(
            name,
            labels={
                "trigger-type": "webhook",
                "trigger-event": event_type,
                "trigger-repo": repo,
                "trigger-branch": branch,
                **({"trigger-pr": str(pr_number)} if pr_number else {}),
            },
        )

    def create_from_alert(
        self, alert_name: str, cluster: str = "", severity: str = "warning"
    ) -> str:
        """Create sandbox from an alert (PagerDuty, Prometheus).

        Args:
            alert_name: Alert name (e.g., PodCrashLoop, HighErrorRate)
            cluster: Cluster name where alert fired
            severity: Alert severity (warning, critical)
        """
        suffix = uuid.uuid4().hex[:6]
        name = f"alert-{alert_name.lower()}-{suffix}"

        return self._create_claim(
            name,
            labels={
                "trigger-type": "alert",
                "trigger-alert": alert_name,
                "trigger-cluster": cluster or "unknown",
                "trigger-severity": severity,
            },
        )


# FastAPI endpoint integration (to be added to Kagenti backend)
FASTAPI_ROUTES = '''
# Add to kagenti/backend/main.py:

from triggers import SandboxTrigger

trigger = SandboxTrigger()

@app.post("/api/v1/sandbox/trigger")
async def create_sandbox_trigger(request: dict):
    """Create a sandbox from a trigger event."""
    trigger_type = request.get("type", "webhook")

    if trigger_type == "cron":
        name = trigger.create_from_cron(
            skill=request["skill"],
            schedule=request.get("schedule", ""),
        )
    elif trigger_type == "webhook":
        name = trigger.create_from_webhook(
            event_type=request["event"],
            repo=request["repo"],
            branch=request.get("branch", "main"),
            pr_number=request.get("pr_number", 0),
        )
    elif trigger_type == "alert":
        name = trigger.create_from_alert(
            alert_name=request["alert"],
            cluster=request.get("cluster", ""),
            severity=request.get("severity", "warning"),
        )
    else:
        raise HTTPException(400, f"Unknown trigger type: {trigger_type}")

    return {"sandbox_claim": name, "namespace": trigger.namespace}
'''


if __name__ == "__main__":
    # Dry-run test (doesn't create real resources)
    print("Trigger examples (dry-run):")
    print(f"  Cron:    cron-rca-ci-abc123")
    print(f"  Webhook: gh-kagenti-kagenti-def456")
    print(f"  Alert:   alert-podcrashloop-789abc")
    print(f"\nFastAPI integration: POST /api/v1/sandbox/trigger")
