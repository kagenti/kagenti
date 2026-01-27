#!/usr/bin/env python3
# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Migration script for MCPServer CRDs to Kubernetes Deployments.

This script migrates legacy MCPServer CRD resources (Toolhive) to standard
Kubernetes Deployments and Services. It's part of Phase 5 of the migration
plan (migrate-tool-mcpserver-to-workloads.md).

Usage:
    # List tools that can be migrated (dry-run by default)
    python -m kagenti.tools.migrate_tools --namespace team1

    # Migrate all tools in a namespace (dry-run)
    python -m kagenti.tools.migrate_tools --namespace team1 --dry-run

    # Actually migrate all tools
    python -m kagenti.tools.migrate_tools --namespace team1 --no-dry-run

    # Migrate and delete old MCPServer CRDs
    python -m kagenti.tools.migrate_tools --namespace team1 --no-dry-run --delete-old

    # Migrate a specific tool
    python -m kagenti.tools.migrate_tools --namespace team1 --tool my-tool --no-dry-run

    # Output results as JSON
    python -m kagenti.tools.migrate_tools --namespace team1 --json
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
# Toolhive CRD Definitions
TOOLHIVE_CRD_GROUP = "toolhive.stacklok.dev"
TOOLHIVE_CRD_VERSION = "v1alpha1"
TOOLHIVE_MCP_PLURAL = "mcpservers"

# Kagenti Labels
KAGENTI_TYPE_LABEL = "kagenti.io/type"
KAGENTI_PROTOCOL_LABEL = "kagenti.io/protocol"
KAGENTI_FRAMEWORK_LABEL = "kagenti.io/framework"
KAGENTI_TRANSPORT_LABEL = "kagenti.io/transport"
KAGENTI_WORKLOAD_TYPE_LABEL = "kagenti.io/workload-type"
KAGENTI_DESCRIPTION_ANNOTATION = "kagenti.io/description"
MIGRATION_SOURCE_ANNOTATION = "kagenti.io/migrated-from"
MIGRATION_TIMESTAMP_ANNOTATION = "kagenti.io/migration-timestamp"
ORIGINAL_SERVICE_ANNOTATION = "kagenti.io/original-service"

APP_KUBERNETES_IO_NAME = "app.kubernetes.io/name"
APP_KUBERNETES_IO_MANAGED_BY = "app.kubernetes.io/managed-by"
APP_KUBERNETES_IO_CREATED_BY = "app.kubernetes.io/created-by"

# Resource types and values
RESOURCE_TYPE_TOOL = "tool"
VALUE_PROTOCOL_MCP = "mcp"
VALUE_TRANSPORT_STREAMABLE_HTTP = "streamable_http"
WORKLOAD_TYPE_DEPLOYMENT = "deployment"
KAGENTI_UI_CREATOR_LABEL = "kagenti-ui"

# Service naming
TOOL_SERVICE_SUFFIX = "-mcp"
TOOLHIVE_SERVICE_PREFIX = "mcp-"
TOOLHIVE_SERVICE_SUFFIX = "-proxy"

# Default values
DEFAULT_IN_CLUSTER_PORT = 8000
DEFAULT_IMAGE_POLICY = "Always"
DEFAULT_RESOURCE_LIMITS = {"cpu": "500m", "memory": "1Gi"}
DEFAULT_RESOURCE_REQUESTS = {"cpu": "100m", "memory": "256Mi"}

# Default environment variables
DEFAULT_ENV_VARS = [
    {"name": "PORT", "value": "8000"},
    {"name": "HOST", "value": "0.0.0.0"},
    {
        "name": "OTEL_EXPORTER_OTLP_ENDPOINT",
        "value": "http://otel-collector.kagenti-system.svc.cluster.local:8335",
    },
    {
        "name": "KEYCLOAK_URL",
        "value": "http://keycloak.keycloak.svc.cluster.local:8080",
    },
    {"name": "UV_CACHE_DIR", "value": "/app/.cache/uv"},
]


class ToolMigrationClient:
    """Client for migrating MCPServer CRDs to Deployments."""

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

    def list_mcpserver_crds(self, namespace: str) -> List[Dict]:
        """List all MCPServer CRDs in a namespace that are Kagenti tools.

        Only returns MCPServer resources that have the kagenti.io/type=tool label.
        """
        try:
            response = self.custom_api.list_namespaced_custom_object(
                group=TOOLHIVE_CRD_GROUP,
                version=TOOLHIVE_CRD_VERSION,
                namespace=namespace,
                plural=TOOLHIVE_MCP_PLURAL,
                label_selector=f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_TOOL}",
            )
            return response.get("items", [])
        except ApiException as e:
            if e.status == 404:
                logger.warning("MCPServer CRD not installed in cluster")
                return []
            raise

    def get_mcpserver_crd(self, namespace: str, name: str) -> Optional[Dict]:
        """Get a specific MCPServer CRD."""
        try:
            return self.custom_api.get_namespaced_custom_object(
                group=TOOLHIVE_CRD_GROUP,
                version=TOOLHIVE_CRD_VERSION,
                namespace=namespace,
                plural=TOOLHIVE_MCP_PLURAL,
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

    def statefulset_exists(self, namespace: str, name: str) -> bool:
        """Check if a StatefulSet exists."""
        try:
            self.apps_api.read_namespaced_stateful_set(name=name, namespace=namespace)
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

    def delete_mcpserver_crd(self, namespace: str, name: str) -> None:
        """Delete an MCPServer CRD."""
        self.custom_api.delete_namespaced_custom_object(
            group=TOOLHIVE_CRD_GROUP,
            version=TOOLHIVE_CRD_VERSION,
            namespace=namespace,
            plural=TOOLHIVE_MCP_PLURAL,
            name=name,
        )


def _get_toolhive_service_name(tool_name: str) -> str:
    """Get the old Toolhive-style service name.

    Toolhive creates services named: mcp-{name}-proxy
    """
    return f"{TOOLHIVE_SERVICE_PREFIX}{tool_name}{TOOLHIVE_SERVICE_SUFFIX}"


def _get_new_service_name(tool_name: str) -> str:
    """Get the new Kagenti-style service name.

    New tools use services named: {name}-mcp
    """
    return f"{tool_name}{TOOL_SERVICE_SUFFIX}"


def build_deployment_from_mcpserver(mcpserver: Dict) -> Dict:
    """
    Build a Kubernetes Deployment manifest from an MCPServer CRD.

    Args:
        mcpserver: The MCPServer CRD resource dictionary.

    Returns:
        Deployment manifest dictionary.
    """
    metadata = mcpserver.get("metadata", {})
    spec = mcpserver.get("spec", {})
    name = metadata.get("name", "")
    namespace = metadata.get("namespace", "default")

    # Get labels from MCPServer CRD and update for Deployment
    labels = metadata.get("labels", {}).copy()

    # Ensure required labels are set
    labels[KAGENTI_TYPE_LABEL] = RESOURCE_TYPE_TOOL
    labels[APP_KUBERNETES_IO_NAME] = name
    labels[KAGENTI_PROTOCOL_LABEL] = VALUE_PROTOCOL_MCP
    labels[KAGENTI_TRANSPORT_LABEL] = VALUE_TRANSPORT_STREAMABLE_HTTP
    labels[KAGENTI_WORKLOAD_TYPE_LABEL] = WORKLOAD_TYPE_DEPLOYMENT
    labels[APP_KUBERNETES_IO_MANAGED_BY] = KAGENTI_UI_CREATOR_LABEL

    # Preserve framework label if present
    if KAGENTI_FRAMEWORK_LABEL not in labels:
        labels[KAGENTI_FRAMEWORK_LABEL] = "Python"

    # Build annotations with migration tracking
    annotations = metadata.get("annotations", {}).copy()
    annotations[MIGRATION_SOURCE_ANNOTATION] = "mcpserver-crd"
    annotations[MIGRATION_TIMESTAMP_ANNOTATION] = datetime.now(timezone.utc).isoformat()
    annotations[ORIGINAL_SERVICE_ANNOTATION] = _get_toolhive_service_name(name)

    # Get image from spec
    image = spec.get("image", "")
    if not image:
        raise ValueError(f"MCPServer CRD '{name}' has no image specified")

    # Get port configuration
    target_port = spec.get("targetPort", DEFAULT_IN_CLUSTER_PORT)

    # Extract pod template from MCPServer CRD
    pod_template_spec = spec.get("podTemplateSpec", {})
    pod_spec = pod_template_spec.get("spec", {})

    # Get containers from pod template or build default
    containers = pod_spec.get("containers", [])
    if containers:
        # Use existing container configuration
        container = containers[0].copy()
        # Ensure image is set (override if different in spec.image)
        if image:
            container["image"] = image
        # Ensure imagePullPolicy is set
        if "imagePullPolicy" not in container:
            container["imagePullPolicy"] = DEFAULT_IMAGE_POLICY
        # Ensure ports are set
        if "ports" not in container:
            container["ports"] = [
                {"name": "http", "containerPort": target_port, "protocol": "TCP"}
            ]
        # Ensure resources are set
        if "resources" not in container:
            container["resources"] = {
                "limits": DEFAULT_RESOURCE_LIMITS,
                "requests": DEFAULT_RESOURCE_REQUESTS,
            }
        # Ensure volumeMounts are set
        if "volumeMounts" not in container:
            container["volumeMounts"] = [
                {"name": "cache", "mountPath": "/app/.cache"},
                {"name": "tmp", "mountPath": "/tmp"},
            ]
    else:
        # Build default container spec
        env_vars = list(DEFAULT_ENV_VARS)
        container = {
            "name": "mcp",
            "image": image,
            "imagePullPolicy": DEFAULT_IMAGE_POLICY,
            "env": env_vars,
            "ports": [
                {"name": "http", "containerPort": target_port, "protocol": "TCP"}
            ],
            "resources": {
                "limits": DEFAULT_RESOURCE_LIMITS,
                "requests": DEFAULT_RESOURCE_REQUESTS,
            },
            "volumeMounts": [
                {"name": "cache", "mountPath": "/app/.cache"},
                {"name": "tmp", "mountPath": "/tmp"},
            ],
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
                "runAsUser": 1000,
            },
        }

    # Get volumes from pod template or use defaults
    volumes = pod_spec.get(
        "volumes",
        [
            {"name": "cache", "emptyDir": {}},
            {"name": "tmp", "emptyDir": {}},
        ],
    )

    # Get security context from pod template or use defaults
    security_context = pod_spec.get(
        "securityContext",
        {
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
    )

    # Get image pull secrets
    image_pull_secrets = pod_spec.get("imagePullSecrets", [])

    # Get service account name
    service_account_name = pod_spec.get("serviceAccountName")

    # Build selector labels
    selector_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
    }

    # Build pod template labels
    pod_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
        KAGENTI_PROTOCOL_LABEL: VALUE_PROTOCOL_MCP,
        KAGENTI_TRANSPORT_LABEL: VALUE_TRANSPORT_STREAMABLE_HTTP,
    }
    # Add framework if present
    if KAGENTI_FRAMEWORK_LABEL in labels:
        pod_labels[KAGENTI_FRAMEWORK_LABEL] = labels[KAGENTI_FRAMEWORK_LABEL]

    # Build pod spec
    new_pod_spec = {
        "securityContext": security_context,
        "containers": [container],
        "volumes": volumes,
    }

    if service_account_name:
        new_pod_spec["serviceAccountName"] = service_account_name

    if image_pull_secrets:
        new_pod_spec["imagePullSecrets"] = image_pull_secrets

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
            "replicas": 1,
            "selector": {
                "matchLabels": selector_labels,
            },
            "template": {
                "metadata": {
                    "labels": pod_labels,
                },
                "spec": new_pod_spec,
            },
        },
    }


def build_service_from_mcpserver(mcpserver: Dict) -> Dict:
    """
    Build a Kubernetes Service manifest from an MCPServer CRD.

    Uses the new naming convention: {name}-mcp

    Args:
        mcpserver: The MCPServer CRD resource dictionary.

    Returns:
        Service manifest dictionary.
    """
    metadata = mcpserver.get("metadata", {})
    spec = mcpserver.get("spec", {})
    name = metadata.get("name", "")
    namespace = metadata.get("namespace", "default")

    # New service name
    service_name = _get_new_service_name(name)

    # Get labels
    labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        KAGENTI_PROTOCOL_LABEL: VALUE_PROTOCOL_MCP,
        APP_KUBERNETES_IO_NAME: name,
        APP_KUBERNETES_IO_MANAGED_BY: KAGENTI_UI_CREATOR_LABEL,
    }

    # Build selector labels
    selector_labels = {
        KAGENTI_TYPE_LABEL: RESOURCE_TYPE_TOOL,
        APP_KUBERNETES_IO_NAME: name,
    }

    # Get port from MCPServer spec
    port = spec.get("port", DEFAULT_IN_CLUSTER_PORT)
    target_port = spec.get("targetPort", DEFAULT_IN_CLUSTER_PORT)

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "type": "ClusterIP",
            "selector": selector_labels,
            "ports": [
                {
                    "name": "http",
                    "port": port,
                    "targetPort": target_port,
                    "protocol": "TCP",
                }
            ],
        },
    }


def migrate_tool(
    client: ToolMigrationClient,
    namespace: str,
    mcpserver: Dict,
    delete_old: bool = False,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Migrate a single MCPServer CRD to a Deployment.

    Args:
        client: The ToolMigrationClient instance.
        namespace: The Kubernetes namespace.
        mcpserver: The MCPServer CRD dictionary.
        delete_old: Whether to delete the MCPServer CRD after migration.
        dry_run: If True, don't actually create/delete resources.

    Returns:
        Migration result dictionary.
    """
    metadata = mcpserver.get("metadata", {})
    name = metadata.get("name", "")

    result = {
        "name": name,
        "namespace": namespace,
        "status": "pending",
        "deployment_created": False,
        "service_created": False,
        "mcpserver_deleted": False,
        "messages": [],
        "errors": [],
        "old_service": _get_toolhive_service_name(name),
        "new_service": _get_new_service_name(name),
    }

    # Check if Deployment already exists
    if client.deployment_exists(namespace, name):
        result["status"] = "skipped"
        result["messages"].append("Deployment already exists")
        return result

    # Check if StatefulSet already exists
    if client.statefulset_exists(namespace, name):
        result["status"] = "skipped"
        result["messages"].append("StatefulSet already exists (already migrated)")
        return result

    if dry_run:
        result["status"] = "dry-run"
        result["messages"].append("Would create Deployment")

        new_service_name = _get_new_service_name(name)
        if not client.service_exists(namespace, new_service_name):
            result["messages"].append(f"Would create Service '{new_service_name}'")
        else:
            result["messages"].append(f"Service '{new_service_name}' already exists")

        if delete_old:
            result["messages"].append("Would delete MCPServer CRD")
        return result

    # Build and create Deployment
    try:
        deployment_manifest = build_deployment_from_mcpserver(mcpserver)
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
    new_service_name = _get_new_service_name(name)
    if not client.service_exists(namespace, new_service_name):
        try:
            service_manifest = build_service_from_mcpserver(mcpserver)
            client.create_service(namespace, service_manifest)
            result["service_created"] = True
            result["messages"].append(f"Service '{new_service_name}' created")
            logger.info(f"Created Service '{new_service_name}'")
        except Exception as e:
            result["errors"].append(f"Failed to create Service: {str(e)}")
            logger.error(f"Failed to create Service '{new_service_name}': {e}")
            # Continue - Deployment was created, Service failure is not fatal
    else:
        result["messages"].append(f"Service '{new_service_name}' already exists")

    # Delete MCPServer CRD (if requested)
    if delete_old:
        try:
            client.delete_mcpserver_crd(namespace, name)
            result["mcpserver_deleted"] = True
            result["messages"].append("MCPServer CRD deleted")
            logger.info(f"Deleted MCPServer CRD '{name}'")
        except Exception as e:
            result["errors"].append(f"Failed to delete MCPServer CRD: {str(e)}")
            logger.error(f"Failed to delete MCPServer CRD '{name}': {e}")

    result["status"] = "migrated" if not result["errors"] else "partial"
    return result


def main():
    """Main entry point for the migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate Kagenti MCPServer CRDs to Kubernetes Deployments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List tools that can be migrated
  python -m kagenti.tools.migrate_tools --namespace team1

  # Dry-run migration (default, shows what would happen)
  python -m kagenti.tools.migrate_tools --namespace team1 --dry-run

  # Actually migrate all tools
  python -m kagenti.tools.migrate_tools --namespace team1 --no-dry-run

  # Migrate and delete old MCPServer CRDs
  python -m kagenti.tools.migrate_tools --namespace team1 --no-dry-run --delete-old

  # Migrate a specific tool
  python -m kagenti.tools.migrate_tools --namespace team1 --tool my-tool --no-dry-run

  # Output results as JSON
  python -m kagenti.tools.migrate_tools --namespace team1 --json

Note:
  - The old Toolhive-created service name is: mcp-{name}-proxy
  - The new Kagenti service name is: {name}-mcp
  - After migration, update any MCP connection URLs to use the new service name
        """,
    )
    parser.add_argument(
        "--namespace",
        "-n",
        default="default",
        help="Kubernetes namespace to migrate tools from (default: default)",
    )
    parser.add_argument(
        "--tool",
        "-t",
        help="Specific tool name to migrate (if not specified, migrates all)",
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
        help="Delete MCPServer CRDs after successful migration (default: False)",
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
        client = ToolMigrationClient()
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes client: {e}")
        sys.exit(1)

    # Get MCPServer CRDs to migrate
    if args.tool:
        # Migrate specific tool
        mcpserver = client.get_mcpserver_crd(args.namespace, args.tool)
        if not mcpserver:
            logger.error(
                f"MCPServer CRD '{args.tool}' not found in namespace '{args.namespace}'"
            )
            sys.exit(1)
        mcpservers = [mcpserver]
    else:
        # List all MCPServer CRDs with kagenti.io/type=tool label
        mcpservers = client.list_mcpserver_crds(args.namespace)

    if not mcpservers:
        logger.info(f"No MCPServer CRDs found in namespace '{args.namespace}'")
        if args.json:
            print(json.dumps({"namespace": args.namespace, "tools": [], "total": 0}))
        sys.exit(0)

    # Print header
    if not args.json:
        mode = "DRY-RUN" if args.dry_run else "MIGRATION"
        print(f"\n{'=' * 60}")
        print(f"Kagenti MCPServer CRD Migration - {mode}")
        print(f"{'=' * 60}")
        print(f"Namespace: {args.namespace}")
        print(f"Delete old CRDs: {args.delete_old}")
        print(f"Total MCPServer CRDs found: {len(mcpservers)}")
        print(f"{'=' * 60}\n")

    # Migrate tools
    results = []
    for mcpserver in mcpservers:
        result = migrate_tool(
            client=client,
            namespace=args.namespace,
            mcpserver=mcpserver,
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
            print(f"   Old service: {result['old_service']}")
            print(f"   New service: {result['new_service']}")
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

        if not args.dry_run and summary["migrated"] > 0:
            print(
                "\n⚠️  Important: Update MCP connection URLs to use new service names:"
            )
            print(
                "   Old: http://mcp-{name}-proxy.{namespace}.svc.cluster.local:8000/mcp"
            )
            print("   New: http://{name}-mcp.{namespace}.svc.cluster.local:8000/mcp")

    # Exit with error code if any failures
    if summary["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
