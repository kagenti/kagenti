# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Skill auto-sync service.

Periodically polls a remote Skillberry registry and keeps Kagenti's
skill catalog in sync: creating external skill references for new skills,
patching version annotations when a skill is updated, and deleting
references when a skill is removed from the registry.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import kubernetes.client as k8s_client
from kubernetes.client.exceptions import ApiException

from app.core.config import settings
from app.core.constants import (
    APP_KUBERNETES_IO_MANAGED_BY,
    APP_KUBERNETES_IO_NAME,
    SKILL_AUTOSYNC_CONFIG_CM,
    SKILL_AUTOSYNC_LABEL,
    SKILL_DESCRIPTION_ANNOTATION,
    SKILL_DISPLAY_NAME_ANNOTATION,
    SKILL_NS_TAG_PREFIX,
    SKILL_REGISTRY_SKILL_NAME_ANNOTATION,
    SKILL_REGISTRY_SKILL_VERSION_ANNOTATION,
    SKILL_REGISTRY_TYPE_LABEL,
    SKILL_REGISTRY_URL_ANNOTATION,
    SKILL_SOURCE_EXTERNAL,
    SKILL_SOURCE_LABEL,
    SKILL_TYPE_LABEL,
    SKILL_TYPE_VALUE,
    SKILL_USAGE_ANNOTATION,
)
from app.services.kubernetes import KubernetesService, get_kubernetes_service

logger = logging.getLogger(__name__)

_KAGENTI_SYSTEM = "kagenti-system"


def _sanitize_k8s_name(name: str) -> str:
    out = "".join(c.lower() if c.isalnum() or c in ("-", ".") else "-" for c in name)
    out = out.strip("-.")
    return out or "skill"


def _get_autosync_config(kube: KubernetesService) -> Optional[Dict[str, str]]:
    """Read auto-sync ConfigMap from kagenti-system. Returns None if absent."""
    try:
        cm = kube.core_api.read_namespaced_config_map(
            name=SKILL_AUTOSYNC_CONFIG_CM,
            namespace=_KAGENTI_SYSTEM,
        )
        return cm.data or {}
    except ApiException as exc:
        if exc.status == 404:
            return None
        logger.warning("Failed to read auto-sync config: %s", exc)
        return None


def _update_sync_status(kube: KubernetesService, skill_count: int, synced_at: str) -> None:
    """Patch last-synced-at and skill-count into the auto-sync ConfigMap."""
    body = {"data": {"last-synced-at": synced_at, "skill-count": str(skill_count)}}
    try:
        kube.core_api.patch_namespaced_config_map(
            name=SKILL_AUTOSYNC_CONFIG_CM,
            namespace=_KAGENTI_SYSTEM,
            body=body,
        )
    except ApiException as exc:
        logger.warning("Failed to update sync status: %s", exc)


async def _fetch_registry_skills(registry_url: str) -> List[Dict[str, Any]]:
    """GET {registry_url}/skills/ and return the JSON array."""
    url = registry_url.rstrip("/") + "/skills/"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, list):
            raise ValueError(f"Registry returned non-list response: {type(result).__name__}")
        return result


def _get_namespace_tags(skill: Dict[str, Any]) -> List[str]:
    """Return the values of namespace: tags on a Skillberry skill."""
    tags = skill.get("tags") or []
    return [t[len(SKILL_NS_TAG_PREFIX) :] for t in tags if t.startswith(SKILL_NS_TAG_PREFIX)]


def _namespace_distribution(
    registry_skills: List[Dict[str, Any]],
    kagenti_namespaces: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Map each Kagenti namespace to the skills it should contain.

    namespace:default tag (or no namespace: tag) → all Kagenti namespaces.
    namespace:X tag → namespace X only (if X is an enabled Kagenti namespace).
    """
    distribution: Dict[str, List[Dict[str, Any]]] = {ns: [] for ns in kagenti_namespaces}
    for skill in registry_skills:
        ns_tags = _get_namespace_tags(skill)
        if not ns_tags or "default" in ns_tags:
            for ns in kagenti_namespaces:
                distribution[ns].append(skill)
        else:
            for ns_tag in ns_tags:
                if ns_tag in distribution:
                    distribution[ns_tag].append(skill)
    return distribution


def _get_autosync_skills(kube: KubernetesService, namespace: str) -> List[Any]:
    """List ConfigMaps labelled kagenti.io/auto-sync=true in a namespace."""
    try:
        result = kube.core_api.list_namespaced_config_map(
            namespace=namespace,
            label_selector=f"{SKILL_TYPE_LABEL}={SKILL_TYPE_VALUE},{SKILL_AUTOSYNC_LABEL}=true",
        )
        return result.items
    except ApiException as exc:
        logger.warning("Failed to list auto-sync skills in %s: %s", namespace, exc)
        return []


def _create_autosync_skill(
    kube: KubernetesService,
    namespace: str,
    skill: Dict[str, Any],
    registry_url: str,
    registry_type: str,
) -> None:
    skill_name = skill["name"]
    version = skill.get("version") or "latest"
    resource_name = _sanitize_k8s_name(skill_name)
    labels = {
        SKILL_TYPE_LABEL: SKILL_TYPE_VALUE,
        SKILL_SOURCE_LABEL: SKILL_SOURCE_EXTERNAL,
        SKILL_REGISTRY_TYPE_LABEL: registry_type,
        APP_KUBERNETES_IO_NAME: resource_name,
        APP_KUBERNETES_IO_MANAGED_BY: "kagenti-autosync",
        SKILL_AUTOSYNC_LABEL: "true",
    }
    annotations: Dict[str, str] = {
        SKILL_DISPLAY_NAME_ANNOTATION: skill_name,
        SKILL_USAGE_ANNOTATION: "0",
        SKILL_REGISTRY_URL_ANNOTATION: registry_url,
        SKILL_REGISTRY_SKILL_NAME_ANNOTATION: skill_name,
        SKILL_REGISTRY_SKILL_VERSION_ANNOTATION: version,
    }
    desc = skill.get("description") or ""
    if desc:
        annotations[SKILL_DESCRIPTION_ANNOTATION] = desc
    body = k8s_client.V1ConfigMap(
        metadata=k8s_client.V1ObjectMeta(
            name=resource_name,
            namespace=namespace,
            labels=labels,
            annotations=annotations,
        ),
        data={},
    )
    try:
        kube.core_api.create_namespaced_config_map(namespace=namespace, body=body)
        logger.info("Auto-sync: created '%s' in '%s'", skill_name, namespace)
    except ApiException as exc:
        if exc.status == 409:
            logger.debug("Auto-sync: '%s' already exists in '%s', skipping", skill_name, namespace)
        else:
            logger.warning(
                "Auto-sync: failed to create '%s' in '%s': %s", skill_name, namespace, exc
            )


def _patch_skill_version(
    kube: KubernetesService, namespace: str, resource_name: str, new_version: str
) -> None:
    body = {"metadata": {"annotations": {SKILL_REGISTRY_SKILL_VERSION_ANNOTATION: new_version}}}
    try:
        kube.core_api.patch_namespaced_config_map(
            name=resource_name, namespace=namespace, body=body
        )
        logger.info(
            "Auto-sync: updated version for '%s' in '%s' → %s",
            resource_name,
            namespace,
            new_version,
        )
    except ApiException as exc:
        logger.warning("Auto-sync: failed to patch version for '%s': %s", resource_name, exc)


def _delete_autosync_skill(kube: KubernetesService, namespace: str, resource_name: str) -> None:
    try:
        kube.core_api.delete_namespaced_config_map(name=resource_name, namespace=namespace)
        logger.info("Auto-sync: deleted '%s' from '%s'", resource_name, namespace)
    except ApiException as exc:
        if exc.status != 404:
            logger.warning("Auto-sync: failed to delete '%s': %s", resource_name, exc)


def _apply_diff(
    kube: KubernetesService,
    namespace: str,
    target_skills: List[Dict[str, Any]],
    local_cms: List[Any],
    registry_url: str,
    registry_type: str,
) -> int:
    """Apply diff between target registry skills and current local auto-synced skills.

    Returns the count of skills that should exist in this namespace after the diff.
    """
    local_by_name: Dict[str, Any] = {}
    for cm in local_cms:
        annos = cm.metadata.annotations or {}
        reg_name = annos.get(SKILL_REGISTRY_SKILL_NAME_ANNOTATION)
        if reg_name:
            local_by_name[reg_name] = cm

    target_by_name: Dict[str, Dict[str, Any]] = {s["name"]: s for s in target_skills}

    for name, skill in target_by_name.items():
        if name not in local_by_name:
            _create_autosync_skill(kube, namespace, skill, registry_url, registry_type)

    for name, cm in local_by_name.items():
        if name not in target_by_name:
            _delete_autosync_skill(kube, namespace, cm.metadata.name)

    for name, skill in target_by_name.items():
        if name in local_by_name:
            cm = local_by_name[name]
            annos = cm.metadata.annotations or {}
            local_ver = annos.get(SKILL_REGISTRY_SKILL_VERSION_ANNOTATION, "latest")
            reg_ver = skill.get("version") or "latest"
            if local_ver != reg_ver:
                _patch_skill_version(kube, namespace, cm.metadata.name, reg_ver)

    return len(target_by_name)


async def sync_skills_once(kube: KubernetesService) -> int:
    """Single sync pass.

    Returns the effective sleep interval to use (read from ConfigMap, or
    settings default when auto-sync is not configured/disabled).
    """
    config = _get_autosync_config(kube)
    if config is None:
        return settings.skill_autosync_interval
    if config.get("enabled") != "true":
        return int(config.get("sync-interval", settings.skill_autosync_interval))

    registry_url = config.get("registry-url", "")
    registry_type = config.get("registry-type", "skillberry")
    effective_interval = int(config.get("sync-interval", settings.skill_autosync_interval))

    if not registry_url:
        logger.warning("Auto-sync config present but registry-url is empty")
        return effective_interval

    try:
        registry_skills = await _fetch_registry_skills(registry_url)
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.warning("Auto-sync: transient fetch error from '%s': %s", registry_url, exc)
        return effective_interval
    except (ValueError, httpx.HTTPStatusError) as exc:
        # ValueError covers non-list JSON; HTTPStatusError covers 4xx/5xx — both are
        # registry-side problems unlikely to resolve on the next cycle without intervention.
        logger.error("Auto-sync: permanent error from '%s': %s", registry_url, exc)
        return effective_interval
    except Exception as exc:
        logger.warning("Auto-sync: unexpected error from '%s': %s", registry_url, exc)
        return effective_interval

    # Filter by allowed tags (AND-any: skill must have at least one allowed tag).
    # If allowed-tags is absent or empty, no filtering is applied.
    tags_raw = config.get("allowed-tags", "")
    allowed_tags = {t.strip() for t in tags_raw.split(",") if t.strip()}
    if allowed_tags:
        before = len(registry_skills)
        registry_skills = [
            s for s in registry_skills if allowed_tags.intersection(set(s.get("tags") or []))
        ]
        logger.debug(
            "Auto-sync: tag filter %s kept %d/%d skills",
            allowed_tags,
            len(registry_skills),
            before,
        )

    kagenti_namespaces = kube.list_enabled_namespaces()
    distribution = _namespace_distribution(registry_skills, kagenti_namespaces)

    total_count = 0
    for namespace, target_skills in distribution.items():
        try:
            local_cms = _get_autosync_skills(kube, namespace)
            total_count += _apply_diff(
                kube, namespace, target_skills, local_cms, registry_url, registry_type
            )
        except Exception:
            logger.warning("Auto-sync: error in namespace '%s', skipping", namespace, exc_info=True)

    synced_at = datetime.now(timezone.utc).isoformat()
    _update_sync_status(kube, total_count, synced_at)
    logger.info(
        "Auto-sync: complete — %d skills across %d namespace(s)",
        total_count,
        len(kagenti_namespaces),
    )
    return effective_interval


async def run_skill_autosync_loop() -> None:
    """Background loop that periodically syncs skills from the configured registry.

    Multi-replica note: each replica runs this loop independently. Concurrent syncs
    are safe — 409 conflicts on ConfigMap writes are handled gracefully — but result
    in N×registry fetches and N-1 redundant K8s writes per interval. Leader election
    is a known future improvement; acceptable for single-replica deployments behind
    the feature flag.
    """
    await asyncio.sleep(settings.skill_autosync_interval)
    while True:
        interval = settings.skill_autosync_interval
        try:
            kube = get_kubernetes_service()
            interval = await sync_skills_once(kube)
        except Exception:
            logger.exception("Skill auto-sync error")
        await asyncio.sleep(interval)
