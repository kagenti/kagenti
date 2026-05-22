#!/usr/bin/env python3
# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Migration script for Agent CRDs to Kubernetes Deployments.

This script migrates legacy Agent CRD resources to standard Kubernetes
Deployments and Services. It's part of Phase 4 of the migration plan
(migrate-agent-crd-to-workloads.md).

Usage:
    # List agents that can be migrated (dry-run by default)
    python -m kagenti.tools.migrate_agents --namespace team1

    # Migrate all agents in a namespace (dry-run)
    python -m kagenti.tools.migrate_agents --namespace team1 --dry-run

    # Actually migrate all agents
    python -m kagenti.tools.migrate_agents --namespace team1 --no-dry-run

    # Migrate and delete old Agent CRDs
    python -m kagenti.tools.migrate_agents --namespace team1 --no-dry-run --delete-old

    # Migrate a specific agent
    python -m kagenti.tools.migrate_agents --namespace team1 --agent my-agent --no-dry-run
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

try:
    import kubernetes
    import kubernetes.client
    import kubernetes.config
    from kubernetes.client import ApiException
except ImportError as exc:
    raise ImportError(
        "kubernetes package not installed. Run: pip install kubernetes"
    ) from exc


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# Constants (matching backend/app/core/constants.py)
CRD_GROUP = "agent.kagenti.dev"
CRD_VERSION = "v1alpha1"
AGENTS_PLURAL = "agents"

KAGENTI_TYPE_LABEL = "kagenti.io/type"
KAGENTI_PROTOCOL_LABEL = "kagenti.io/protocol"  # deprecated; kept for reading old CRDs
PROTOCOL_LABEL_PREFIX = "protocol.kagenti.io/"
KAGENTI_FRAMEWORK_LABEL = "kagenti.io/framework"
KAGENTI_WORKLOAD_TYPE_LABEL = "kagenti.io/workload-type"
KAGENTI_DESCRIPTION_ANNOTATION = "kagenti.io/description"
MIGRATION_SOURCE_ANNOTATION = "kagenti.io/migrated-from"
MIGRATION_TIMESTAMP_ANNOTATION = "kagenti.io/migration-timestamp"

APP_KUBERNETES_IO_NAME = "app.kubernetes.io/name"
APP_KUBERNETES_IO_MANAGED_BY = "app.kubernetes.io/managed-by"

RESOURCE_TYPE_AGENT = "agent"
WORKLOAD_TYPE_DEPLOYMENT = "deployment"
KAGENTI_UI_CREATOR_LABEL = "kagenti-ui"
KAGENTI_OPERATOR_LABEL_NAME = "kagenti-operator"

DEFAULT_IN_CLUSTER_PORT = 8000
DEFAULT_OFF_CLUSTER_PORT = 8080
DEFAULT_IMAGE_POLICY = "Always"
DEFAULT_RESOURCE_LIMITS = {"cpu": "500m", "memory": "1Gi"}
DEFAULT_RESOURCE_REQUESTS = {"cpu": "100m", "memory": "256Mi"}


class MigrationClient:
    """Client for migrating Agent CRDs to Deployments."""

    def __init__(self):
        """Initialize Kubernetes clients."""
        try:
            # Try in-cluster config first
            kubernetes.config.load_incluster_config()
            logger.info("Using in-cluster Kubernetes configuration")
        except kubernetes.config.ConfigException:
            # Fall back to kubeconfig
            kubernetes.config.load_kube_config()
            logger.info("Using kubeconfig for Kubernetes configuration")

        self.api_client = kubernetes.client.ApiClient()
        self.custom_api = kubernetes.client.CustomObjectsApi(self.api_client)
        self.apps_api = kubernetes.client.AppsV1Api(self.api_client)
        self.core_api = kubernetes.client.CoreV1Api(self.api_client)

    def list_agent_crds(self, namespace: str) -> List[Dict]:
        """List all Agent CRDs in a namespace."""
        try:
            response = self.custom_api.list_namespaced_custom_object(
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=namespace,
                plural=AGENTS_PLURAL,
            )
            return response.get("items", [])
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Agent CRD not installed in cluster")
                return []
            raise

    def get_agent_crd(self, namespace: str, name: str) -> Optional[Dict]:
        """Get a specific Agent CRD."""
        try:
            return self.custom_api.get_namespaced_custom_object(
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=namespace,
                plural=AGENTS_PLURAL,
                name=name,
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def deployment_exists(self, namespace: str, name: str) -> bool:
        """Check if a Deployment exists."""
        try:
            self.apps_api.read_namespaced_deployment(name=name, namespace=namespace)
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    def service_exists(self, namespace: str, name: str) -> bool:
        """Check if a Service exists."""
        try:
            self.core_api.read_namespaced_service(name=name, namespace=namespace)
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    def create_deployment(self, namespace: str, body: Dict) -> Dict:
        """Create a Deployment."""
        result = self.apps_api.create_namespaced_deployment(
            namespace=namespace,
            body=body,
        )
        return result.to_dict()

    def create_service(self, namespace: str, body: Dict) -> Dict:
        """Create a Service."""
        result = self.core_api.create_namespaced_service(
            namespace=namespace,
            body=body,
        )
        return result.to_dict()

    def delete_agent_crd(self, namespace: str, name: str) -> None:
        """Delete an Agent CRD."""
        self.custom_api.delete_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=AGENTS_PLURAL,
            name=name,
        )


def build_deployment_from_agent_crd(agent: Dict) -> Dict:
    """
    Build a Kubernetes Deployment manifest from an Agent CRD.

    Args:
        agent: The Agent CRD resource dictionary.

    Returns:
        Deployment manifest dictionary.
    """
    metadata = agent.get("metadata", {})
    spec = agent.get("spec", {})
    name = metadata.get("name", "")
    namespace = metadata.get("namespace", "default")

    # Get labels from Agent CRD and update for Deployment
    labels = metadata.get("labels", {}).copy()
    labels[KAGENTI_WORKLOAD_TYPE_LABEL] = WORKLOAD_TYPE_DEPLOYMENT
    labels[APP_KUBERNETES_IO_MANAGED_BY] = KAGENTI_UI_CREATOR_LABEL

    # Get annotations
    annotations = metadata.get("annotations", {}).copy()
    annotations[MIGRATION_SOURCE_ANNOTATION] = "agent-crd"
    annotations[MIGRATION_TIMESTAMP_ANNOTATION] = datetime.now(timezone.utc).isoformat()

    # Description
    description = spec.get("description", "")
    if description:
        annotations[KAGENTI_DESCRIPTION_ANNOTATION] = description

    # Extract pod template from Agent CRD
    pod_template_spec = spec.get("podTemplateSpec", {})
    pod_spec = pod_template_spec.get("spec", {})

    # If no pod template, try to build one from imageSource
    if not pod_spec:
        image_source = spec.get("imageSource", {})
        image = image_source.get("image", "")
        if not image:
            # Note: The API layer uses HTTPException for this condition, but this
            # standalone CLI migration script raises ValueError instead. This keeps
            # dependencies minimal while providing equivalent failure semantics.
            raise ValueError(
                f"Agent CRD '{name}' has no podTemplateSpec or imageSource.image"
            )

        pod_spec = {
            "containers": [
                {
                    "name": "agent",
                    "image": image,
                    "imagePullPolicy": DEFAULT_IMAGE_POLICY,
                    "resources": {
                        "limits": DEFAULT_RESOURCE_LIMITS,
                        "requests": DEFAULT_RESOURCE_REQUESTS,
                    },
                    "ports": [
                        {
                            "name": "http",
                            "containerPort": DEFAULT_IN_CLUSTER_PORT,
                            "protocol": "TCP",
                        }
                    ],
                    "volumeMounts": [
                        {"name": "cache", "mountPath": "/app/.cache"},
                        {"name": "shared-data", "mountPath": "/shared"},
                    ],
                }
            ],
            "volumes": [
                {"name": "cache", "emptyDir": {}},
                {"name": "shared-data", "emptyDir": {}},
            ],
        }

    # Build selector labels
    selector_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_AGENT,
        APP_KUBERNETES_IO_NAME: name,
    }

    # Build pod template labels (merge selector labels with other labels)
    pod_labels = labels.copy()

    # Get replicas
    replicas = spec.get("replicas", 1)

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "replicas": replicas,
            "selector": {
                "matchLabels": selector_labels,
            },
            "template": {
                "metadata": {
                    "labels": pod_labels,
                },
                "spec": pod_spec,
            },
        },
    }


def build_service_from_agent_crd(agent: Dict) -> Dict:
    """
    Build a Kubernetes Service manifest from an Agent CRD.

    Args:
        agent: The Agent CRD resource dictionary.

    Returns:
        Service manifest dictionary.
    """
    metadata = agent.get("metadata", {})
    spec = agent.get("spec", {})
    name = metadata.get("name", "")
    namespace = metadata.get("namespace", "default")

    # Get labels
    labels = metadata.get("labels", {}).copy()
    labels[APP_KUBERNETES_IO_MANAGED_BY] = KAGENTI_UI_CREATOR_LABEL

    # Build selector labels
    selector_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_AGENT,
        APP_KUBERNETES_IO_NAME: name,
    }

    # Get service ports from Agent CRD
    service_ports_spec = spec.get("servicePorts", [])
    if service_ports_spec:
        service_ports = [
            {
                "name": sp.get("name", "http"),
                "port": sp.get("port", DEFAULT_OFF_CLUSTER_PORT),
                "targetPort": sp.get("targetPort", DEFAULT_IN_CLUSTER_PORT),
                "protocol": sp.get("protocol", "TCP"),
            }
            for sp in service_ports_spec
        ]
    else:
        service_ports = [
            {
                "name": "http",
                "port": DEFAULT_OFF_CLUSTER_PORT,
                "targetPort": DEFAULT_IN_CLUSTER_PORT,
                "protocol": "TCP",
            }
        ]

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "type": "ClusterIP",
            "selector": selector_labels,
            "ports": service_ports,
        },
    }


def migrate_agent(
    client: MigrationClient,
    namespace: str,
    agent: Dict,
    delete_old: bool = False,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Migrate a single Agent CRD to a Deployment.

    Args:
        client: The MigrationClient instance.
        namespace: The Kubernetes namespace.
        agent: The Agent CRD dictionary.
        delete_old: Whether to delete the Agent CRD after migration.
        dry_run: If True, don't actually create/delete resources.

    Returns:
        Migration result dictionary.
    """
    metadata = agent.get("metadata", {})
    name = metadata.get("name", "")

    result = {
        "name": name,
        "namespace": namespace,
        "status": "pending",
        "deployment_created": False,
        "service_created": False,
        "agent_crd_deleted": False,
        "messages": [],
        "errors": [],
    }

    # Check if Deployment already exists
    if client.deployment_exists(namespace, name):
        result["status"] = "skipped"
        result["messages"].append("Deployment already exists")
        return result

    if dry_run:
        result["status"] = "dry-run"
        result["messages"].append("Would create Deployment")
        if not client.service_exists(namespace, name):
            result["messages"].append("Would create Service")
        else:
            result["messages"].append("Service already exists")
        if delete_old:
            result["messages"].append("Would delete Agent CRD")
        return result

    # Build and create Deployment
    try:
        deployment_manifest = build_deployment_from_agent_crd(agent)
        client.create_deployment(namespace, deployment_manifest)
        result["deployment_created"] = True
        result["messages"].append("Deployment created")
        logger.info(f"Created Deployment '{name}'")
    except Exception as e:
        result["status"] = "failed"
        result["errors"].append(f"Failed to create Deployment: {str(e)}")
        logger.error(f"Failed to create Deployment '{name}': {e}")
        return result

    # Build and create Service (if needed)
    if not client.service_exists(namespace, name):
        try:
            service_manifest = build_service_from_agent_crd(agent)
            client.create_service(namespace, service_manifest)
            result["service_created"] = True
            result["messages"].append("Service created")
            logger.info(f"Created Service '{name}'")
        except Exception as e:
            result["errors"].append(f"Failed to create Service: {str(e)}")
            logger.error(f"Failed to create Service '{name}': {e}")
            # Continue - Deployment was created, Service failure is not fatal
    else:
        result["messages"].append("Service already exists")

    # Delete Agent CRD (if requested)
    if delete_old:
        try:
            client.delete_agent_crd(namespace, name)
            result["agent_crd_deleted"] = True
            result["messages"].append("Agent CRD deleted")
            logger.info(f"Deleted Agent CRD '{name}'")
        except Exception as e:
            result["errors"].append(f"Failed to delete Agent CRD: {str(e)}")
            logger.error(f"Failed to delete Agent CRD '{name}': {e}")

    result["status"] = "migrated" if not result["errors"] else "partial"
    return result


def main():
    """Main entry point for the migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate Kagenti Agent CRDs to Kubernetes Deployments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List agents that can be migrated
  python -m kagenti.tools.migrate_agents --namespace team1

  # Dry-run migration (default, shows what would happen)
  python -m kagenti.tools.migrate_agents --namespace team1 --dry-run

  # Actually migrate all agents
  python -m kagenti.tools.migrate_agents --namespace team1 --no-dry-run

  # Migrate and delete old Agent CRDs
  python -m kagenti.tools.migrate_agents --namespace team1 --no-dry-run --delete-old

  # Migrate a specific agent
  python -m kagenti.tools.migrate_agents --namespace team1 --agent my-agent --no-dry-run
        """,
    )
    parser.add_argument(
        "--namespace",
        "-n",
        default="default",
        help="Kubernetes namespace to migrate agents from (default: default)",
    )
    parser.add_argument(
        "--agent",
        "-a",
        help="Specific agent name to migrate (if not specified, migrates all)",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Show what would be done without making changes (default: True)",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Actually perform the migration",
    )
    parser.add_argument(
        "--delete-old",
        action="store_true",
        default=False,
        help="Delete Agent CRDs after successful migration (default: False)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize client
    try:
        client = MigrationClient()
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes client: {e}")
        sys.exit(1)

    # Get agents to migrate
    if args.agent:
        # Migrate specific agent
        agent = client.get_agent_crd(args.namespace, args.agent)
        if not agent:
            logger.error(
                f"Agent CRD '{args.agent}' not found in namespace '{args.namespace}'"
            )
            sys.exit(1)
        agents = [agent]
    else:
        # List all Agent CRDs
        agents = client.list_agent_crds(args.namespace)

    if not agents:
        logger.info(f"No Agent CRDs found in namespace '{args.namespace}'")
        if args.json:
            print(json.dumps({"namespace": args.namespace, "agents": [], "total": 0}))
        sys.exit(0)

    # Print header
    if not args.json:
        mode = "DRY-RUN" if args.dry_run else "MIGRATION"
        print(f"\n{'=' * 60}")
        print(f"Kagenti Agent CRD Migration - {mode}")
        print(f"{'=' * 60}")
        print(f"Namespace: {args.namespace}")
        print(f"Delete old CRDs: {args.delete_old}")
        print(f"Total Agent CRDs found: {len(agents)}")
        print(f"{'=' * 60}\n")

    # Migrate agents
    results = []
    for agent in agents:
        result = migrate_agent(
            client=client,
            namespace=args.namespace,
            agent=agent,
            delete_old=args.delete_old,
            dry_run=args.dry_run,
        )
        results.append(result)

        if not args.json:
            status_icon = {
                "dry-run": "🔍",
                "migrated": "✅",
                "skipped": "⏭️",
                "partial": "⚠️",
                "failed": "❌",
            }.get(result["status"], "❓")

            print(f"{status_icon} {result['name']}: {result['status']}")
            for msg in result["messages"]:
                print(f"   - {msg}")
            for err in result["errors"]:
                print(f"   ❌ {err}")
            print()

    # Summary
    summary = {
        "namespace": args.namespace,
        "dry_run": args.dry_run,
        "delete_old": args.delete_old,
        "total": len(results),
        "migrated": sum(1 for r in results if r["status"] == "migrated"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] in ("failed", "partial")),
        "dry_run_count": sum(1 for r in results if r["status"] == "dry-run"),
        "results": results,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{'=' * 60}")
        print("SUMMARY")
        print(f"{'=' * 60}")
        print(f"Total: {summary['total']}")
        if args.dry_run:
            print(f"Would migrate: {summary['dry_run_count']}")
        else:
            print(f"Migrated: {summary['migrated']}")
        print(f"Skipped (already migrated): {summary['skipped']}")
        print(f"Failed: {summary['failed']}")
        print(f"{'=' * 60}")

        if args.dry_run and summary["dry_run_count"] > 0:
            print(
                "\n💡 This was a dry-run. Use --no-dry-run to actually perform the migration."
            )

    # Exit with error code if any failures
    if summary["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
