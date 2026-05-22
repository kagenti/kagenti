# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Helpers for listing Shipwright Build CRs owned by Kagenti (agents/tools).
"""

import logging
from typing import List, Optional

from kubernetes.client import ApiException

from app.core.constants import (
    KAGENTI_TYPE_LABEL,
    RESOURCE_TYPE_AGENT,
    RESOURCE_TYPE_TOOL,
    SHIPWRIGHT_CRD_GROUP,
    SHIPWRIGHT_CRD_VERSION,
    SHIPWRIGHT_BUILDS_PLURAL,
)
from app.models.shipwright import ShipwrightBuildListItem
from app.services.kubernetes import KubernetesService


def format_shipwright_build_timestamp(timestamp) -> Optional[str]:
    """Normalize K8s metadata.creationTimestamp to an ISO-like string."""
    if timestamp is None:
        return None
    if isinstance(timestamp, str):
        return timestamp
    if hasattr(timestamp, "isoformat"):
        return timestamp.isoformat()
    return str(timestamp)


def label_selector_for_kagenti_builds(builds_for: str) -> str:
    """
    Build a label selector for Shipwright Build CRs managed by Kagenti.

    Args:
        builds_for: ``RESOURCE_TYPE_AGENT``, ``RESOURCE_TYPE_TOOL``, or
            ``SHIPWRIGHT_BUILDS_LIST_SCOPE_ALL`` / any other value (both types).
    """
    if builds_for == RESOURCE_TYPE_AGENT:
        return f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_AGENT}"
    if builds_for == RESOURCE_TYPE_TOOL:
        return f"{KAGENTI_TYPE_LABEL}={RESOURCE_TYPE_TOOL}"
    return f"{KAGENTI_TYPE_LABEL} in ({RESOURCE_TYPE_AGENT},{RESOURCE_TYPE_TOOL})"


def shipwright_build_crd_to_list_item(
    build: dict, default_namespace: str
) -> ShipwrightBuildListItem:
    """Map a Shipwright Build CR dict to ShipwrightBuildListItem."""
    md = build.get("metadata", {}) or {}
    spec = build.get("spec", {}) or {}
    status = build.get("status", {}) or {}
    source = spec.get("source", {}) or {}
    git = source.get("git", {}) or {}
    strat = spec.get("strategy", {}) or {}
    out = spec.get("output", {}) or {}
    labels = md.get("labels", {}) or {}
    rtype = labels.get(KAGENTI_TYPE_LABEL, "") or ""

    return ShipwrightBuildListItem(
        name=md.get("name", ""),
        namespace=md.get("namespace", default_namespace),
        resourceType=rtype,
        registered=bool(status.get("registered", False)),
        strategy=strat.get("name", "") or "",
        gitUrl=git.get("url", "") or "",
        gitRevision=git.get("revision", "") or "",
        contextDir=source.get("contextDir", "") or "",
        outputImage=out.get("image", "") or "",
        creationTimestamp=format_shipwright_build_timestamp(
            md.get("creationTimestamp") or md.get("creation_timestamp")
        ),
    )


def sort_build_list_items(items: List[ShipwrightBuildListItem]) -> List[ShipwrightBuildListItem]:
    """Stable sort by namespace, then name."""
    return sorted(items, key=lambda x: (x.namespace, x.name))


def collect_kagenti_shipwright_builds(
    kube: KubernetesService,
    namespaces: List[str],
    builds_for: str,
    logger: Optional[logging.Logger] = None,
) -> List[ShipwrightBuildListItem]:
    """
    List Shipwright Build CRs in the given namespaces filtered by kagenti.io/type label.

    Args:
        kube: Kubernetes API service.
        namespaces: Namespaces to scan (caller resolves enabled-only vs single NS).
        builds_for: ``RESOURCE_TYPE_AGENT``, ``RESOURCE_TYPE_TOOL``, or
            ``SHIPWRIGHT_BUILDS_LIST_SCOPE_ALL``.
        logger: Optional logger for permission-skip warnings.

    Returns:
        Sorted list of build summaries.

    Raises:
        ApiException: On unexpected API errors (403/404 per-namespace are swallowed).
    """
    log = logger or logging.getLogger(__name__)
    label_selector = label_selector_for_kagenti_builds(builds_for)
    items: List[ShipwrightBuildListItem] = []
    for ns in namespaces:
        try:
            # Call CustomObjectsApi directly so user-derived namespace is not logged by
            # KubernetesService.list_custom_resources (CodeQL py/log-injection).
            response = kube.custom_api.list_namespaced_custom_object(
                group=SHIPWRIGHT_CRD_GROUP,
                version=SHIPWRIGHT_CRD_VERSION,
                namespace=ns,
                plural=SHIPWRIGHT_BUILDS_PLURAL,
                label_selector=label_selector,
            )
            builds = response.get("items", [])
        except ApiException as e:
            if e.status == 403:
                # Log only a constant message: namespace / API reason are user- or cluster-derived
                # and trigger CodeQL py/log-injection under security-extended (.github/workflows/security-scans.yaml).
                log.warning(
                    "Skipping Shipwright build list for a namespace: Kubernetes API returned Forbidden (403)"
                )
                continue
            if e.status == 404:
                continue
            raise
        for b in builds:
            items.append(shipwright_build_crd_to_list_item(b, ns))
    return sort_build_list_items(items)
