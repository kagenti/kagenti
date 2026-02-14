# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Build reconciliation loop.

Periodically scans for orphaned Shipwright Builds whose BuildRun succeeded
but whose workload (Deployment/StatefulSet/Job) was never created — typically
because the user navigated away from the UI build-progress page before
finalization.

The loop calls the existing finalize functions directly, reusing all
idempotency checks, config merging, and workload creation logic.
"""

import asyncio
import logging

from fastapi import HTTPException
from kubernetes.client import ApiException

from app.core.config import settings
from app.core.constants import (
    KAGENTI_TYPE_LABEL,
    RESOURCE_TYPE_AGENT,
    RESOURCE_TYPE_TOOL,
    SHIPWRIGHT_BUILDRUNS_PLURAL,
    SHIPWRIGHT_BUILDS_PLURAL,
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
)
from app.services.kubernetes import KubernetesService, get_kubernetes_service
from app.services.shipwright import get_latest_buildrun, is_build_succeeded

logger = logging.getLogger(__name__)


def _workload_exists(kube: KubernetesService, namespace: str, name: str) -> bool:
    """Check if any workload (Deployment, StatefulSet, or Job) exists for the given name."""
    for getter in (kube.get_deployment, kube.get_statefulset, kube.get_job):
        try:
            getter(namespace=namespace, name=name)
            return True
        except ApiException as e:
            if e.status != 404:
                raise
    return False


async def reconcile_builds() -> None:
    """Single reconciliation pass — find and finalize orphaned builds."""
    kube = get_kubernetes_service()
    namespaces = kube.list_enabled_namespaces()

    for namespace in namespaces:
        try:
            builds = kube.list_custom_resources(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace=namespace,
                plural=SHIPWRIGHT_BUILDS_PLURAL,
                label_selector=KAGENTI_TYPE_LABEL,
            )
        except ApiException:
            logger.warning(
                "Failed to list Shipwright Builds in namespace '%s', skipping",
                namespace,
                exc_info=True,
            )
            continue

        for build in builds:
            name = build["metadata"]["name"]
            resource_type = build["metadata"].get("labels", {}).get(KAGENTI_TYPE_LABEL)

            if resource_type not in (RESOURCE_TYPE_AGENT, RESOURCE_TYPE_TOOL):
                continue

            try:
                await _reconcile_single_build(kube, namespace, name, resource_type)
            except Exception:
                logger.warning(
                    "Failed to reconcile build '%s/%s', will retry next cycle",
                    namespace,
                    name,
                    exc_info=True,
                )


async def _reconcile_single_build(
    kube: KubernetesService,
    namespace: str,
    name: str,
    resource_type: str,
) -> None:
    """Attempt to finalize a single orphaned build."""
    # Get latest BuildRun
    buildruns = kube.list_custom_resources(
        group=SHIPWRIGHT_CRD_GROUP,
        version=SHIPWRIGHT_CRD_VERSION,
        namespace=namespace,
        plural=SHIPWRIGHT_BUILDRUNS_PLURAL,
        label_selector=f"kagenti.io/build-name={name}",
    )

    latest = get_latest_buildrun(buildruns)
    if not latest or not is_build_succeeded(latest):
        return  # Build not done yet, skip

    # Quick pre-check: skip if workload already exists
    if _workload_exists(kube, namespace, name):
        return

    logger.info(
        "Reconciling orphaned build '%s/%s' (type=%s)",
        namespace,
        name,
        resource_type,
    )

    try:
        if resource_type == RESOURCE_TYPE_AGENT:
            from app.routers.agents import (
                FinalizeShipwrightBuildRequest,
                finalize_shipwright_build,
            )

            await finalize_shipwright_build(
                namespace=namespace,
                name=name,
                request=FinalizeShipwrightBuildRequest(),
                kube=kube,
            )
        elif resource_type == RESOURCE_TYPE_TOOL:
            from app.routers.tools import (
                FinalizeToolBuildRequest,
                finalize_tool_shipwright_build,
            )

            await finalize_tool_shipwright_build(
                namespace=namespace,
                name=name,
                request=FinalizeToolBuildRequest(),
                kube=kube,
            )

        logger.info(
            "Successfully finalized orphaned build '%s/%s'",
            namespace,
            name,
        )
    except HTTPException as exc:
        # 409 = workload already exists (race with UI), 400 = build not ready
        if exc.status_code in (409, 400):
            logger.debug(
                "Finalize for '%s/%s' returned %d: %s",
                namespace,
                name,
                exc.status_code,
                exc.detail,
            )
        else:
            raise


async def run_reconciliation_loop() -> None:
    """Background loop that periodically reconciles builds."""
    interval = settings.build_reconciliation_interval
    # Sleep first — give the cluster time to settle after startup
    await asyncio.sleep(interval)

    while True:
        try:
            await reconcile_builds()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Build reconciliation error")

        await asyncio.sleep(interval)
