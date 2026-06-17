# Skill Auto-Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cluster-wide auto-sync between a remote Skillberry registry and Kagenti's skill catalog, so skills are created, updated, and deleted automatically every N seconds.

**Architecture:** A backend async background loop (modeled on `services/reconciliation.py`) polls `GET {registryUrl}/skills/` on the configured interval, computes a diff against ConfigMaps labelled `kagenti.io/auto-sync=true`, and applies creates/patches/deletes. A single `kagenti-skill-autosync-config` ConfigMap in `kagenti-system` holds the cluster-wide config. Three REST endpoints let the UI enable/disable sync. The frontend adds an auto-sync control panel to the "From Registry" import tab and adapts the skill catalog page when sync is active.

**Tech Stack:** Python 3.11, FastAPI, kubernetes Python client, httpx (already a dep), React 18, PatternFly 5, TanStack Query v5, TypeScript.

## Global Constraints

- All new backend code: Python 3.11+, `uv` package manager, Apache 2.0 license header
- All new files: `# Copyright 2026 IBM Corp.\n# Licensed under the Apache License, Version 2.0` header
- Git commits: `git commit -s` (DCO sign-off required); trailer: `Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>`
- Feature gate: entire feature behind existing `kagenti_feature_flag_external_skills=true`
- No new feature flags; no new Python dependencies (httpx already in pyproject.toml)
- Backend tests: `uv run pytest kagenti/backend/tests/ -v` from repo root
- Backend linting: `make lint` (ruff)
- Auto-synced skills carry label `kagenti.io/auto-sync=true` in addition to all standard external-skill labels/annotations
- Spec: `docs/superpowers/specs/2026-06-17-skill-autosync-design.md`

---

## File Map

### New files
| Path | Responsibility |
|---|---|
| `kagenti/backend/app/services/skill_autosync.py` | Background loop, sync logic, diff computation |
| `kagenti/backend/tests/test_skill_autosync.py` | Unit tests for namespace distribution and diff logic |

### Modified files
| Path | Changes |
|---|---|
| `kagenti/backend/app/core/constants.py` | +4 auto-sync constants |
| `kagenti/backend/app/core/config.py` | +`skill_autosync_interval: int = 30` |
| `kagenti/backend/app/routers/skills.py` | +2 Pydantic models, +3 endpoints |
| `kagenti/backend/app/main.py` | Start autosync loop in lifespan |
| `kagenti/ui-v2/src/types/index.ts` | +`SkillAutoSyncConfig`, `SkillAutoSyncStatus` interfaces |
| `kagenti/ui-v2/src/services/api.ts` | +3 `skillService` methods |
| `kagenti/ui-v2/src/pages/ImportSkillPage.tsx` | Auto-sync panel in "From Registry" tab |
| `kagenti/ui-v2/src/pages/SkillCatalogPage.tsx` | Banner, badge, button swap when sync active |

---

## Task 1: Backend constants, config, and Pydantic models

**Files:**
- Modify: `kagenti/backend/app/core/constants.py` (append after line 182)
- Modify: `kagenti/backend/app/core/config.py` (append after line 84)
- Modify: `kagenti/backend/app/routers/skills.py` (add imports + 2 models before the `router =` line)

**Interfaces:**
- Produces: `SKILL_AUTOSYNC_CONFIG_CM`, `SKILL_AUTOSYNC_LABEL`, `SKILL_NS_TAG_PREFIX`, `SKILL_NS_DEFAULT_TAG` (used by service and router); `SkillAutoSyncRequest`, `SkillAutoSyncStatus` (used by Task 3 endpoints)

- [ ] **Step 1: Add constants**

In `kagenti/backend/app/core/constants.py`, append after the existing external skill registry block (after `SKILL_FETCHER_IMAGE = "alpine:3.21.3"`):

```python
# Skill auto-sync constants
SKILL_AUTOSYNC_CONFIG_CM = "kagenti-skill-autosync-config"
SKILL_AUTOSYNC_LABEL = "kagenti.io/auto-sync"
SKILL_NS_TAG_PREFIX = "namespace:"
SKILL_NS_DEFAULT_TAG = "namespace:default"
```

- [ ] **Step 2: Add config setting**

In `kagenti/backend/app/core/config.py`, append after line 84 (`kagenti_feature_flag_external_skills: bool = False`):

```python
skill_autosync_interval: int = 30  # seconds between registry sync checks (env: SKILL_AUTOSYNC_INTERVAL)
```

- [ ] **Step 3: Add Pydantic models to skills router**

In `kagenti/backend/app/routers/skills.py`, add these imports at the top (after the existing `from app.core.constants import (` block, add the new constants):

```python
    SKILL_AUTOSYNC_CONFIG_CM,
    SKILL_AUTOSYNC_LABEL,
```

Then add these two models after the `CreateSkillResponse` model definition:

```python
class SkillAutoSyncRequest(BaseModel):
    """Request model for enabling skill auto-sync."""

    registryType: str = Field("skillberry", max_length=63)
    registryUrl: str = Field(..., max_length=2048)
    syncInterval: int = Field(30, ge=10, le=3600)

    @field_validator("registryUrl")
    @classmethod
    def validate_registry_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("registryUrl must use http:// or https:// scheme")
        return v


class SkillAutoSyncStatus(BaseModel):
    """Response model for auto-sync status."""

    enabled: bool
    registryType: Optional[str] = None
    registryUrl: Optional[str] = None
    syncInterval: Optional[int] = None
    lastSyncedAt: Optional[str] = None
    skillCount: Optional[int] = None
```

- [ ] **Step 4: Verify imports parse cleanly**

```bash
cd kagenti/backend && uv run python -c "from app.core.constants import SKILL_AUTOSYNC_CONFIG_CM, SKILL_AUTOSYNC_LABEL, SKILL_NS_TAG_PREFIX, SKILL_NS_DEFAULT_TAG; from app.core.config import settings; print(settings.skill_autosync_interval)"
```

Expected output: `30`

- [ ] **Step 5: Commit**

```bash
git add kagenti/backend/app/core/constants.py kagenti/backend/app/core/config.py kagenti/backend/app/routers/skills.py
git commit -s -m "feat(skills): add auto-sync constants, config, and Pydantic models

Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"
```

---

## Task 2: Auto-sync background service

**Files:**
- Create: `kagenti/backend/app/services/skill_autosync.py`
- Create: `kagenti/backend/tests/test_skill_autosync.py`

**Interfaces:**
- Consumes: `SKILL_AUTOSYNC_CONFIG_CM`, `SKILL_AUTOSYNC_LABEL`, `SKILL_NS_TAG_PREFIX`, `SKILL_NS_DEFAULT_TAG` from constants; `settings.skill_autosync_interval` from config; `KubernetesService` + `get_kubernetes_service` from `app.services.kubernetes`; all `SKILL_*` constants from constants
- Produces: `run_skill_autosync_loop()` → `None` (entry point for `main.py`); `sync_skills_once(kube: KubernetesService) → int` (returns effective interval); `_namespace_distribution(registry_skills, kagenti_namespaces) → dict`; `_apply_diff(kube, namespace, target_skills, local_cms, registry_url, registry_type) → int`

- [ ] **Step 1: Write the failing tests**

Create `kagenti/backend/tests/test_skill_autosync.py`:

```python
# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0
"""Tests for skill auto-sync service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from kubernetes.client.exceptions import ApiException

from app.services.skill_autosync import (
    _namespace_distribution,
    _get_namespace_tags,
    _apply_diff,
    _get_autosync_config,
    sync_skills_once,
)
from app.core.constants import (
    SKILL_REGISTRY_SKILL_NAME_ANNOTATION,
    SKILL_REGISTRY_SKILL_VERSION_ANNOTATION,
    SKILL_AUTOSYNC_LABEL,
    SKILL_TYPE_LABEL,
    SKILL_TYPE_VALUE,
)


def _make_registry_skill(name, version="1.0", tags=None):
    return {"name": name, "version": version, "description": f"Desc {name}", "tags": tags or []}


def _make_local_cm(resource_name, reg_skill_name, version="1.0"):
    cm = MagicMock()
    cm.metadata.name = resource_name
    cm.metadata.annotations = {
        SKILL_REGISTRY_SKILL_NAME_ANNOTATION: reg_skill_name,
        SKILL_REGISTRY_SKILL_VERSION_ANNOTATION: version,
    }
    cm.metadata.labels = {SKILL_TYPE_LABEL: SKILL_TYPE_VALUE, SKILL_AUTOSYNC_LABEL: "true"}
    return cm


class TestGetNamespaceTags:
    def test_extracts_namespace_tags(self):
        skill = _make_registry_skill("s", tags=["namespace:team1", "python"])
        assert _get_namespace_tags(skill) == ["team1"]

    def test_returns_empty_for_no_namespace_tags(self):
        skill = _make_registry_skill("s", tags=["python", "analysis"])
        assert _get_namespace_tags(skill) == []

    def test_returns_default_tag(self):
        skill = _make_registry_skill("s", tags=["namespace:default"])
        assert _get_namespace_tags(skill) == ["default"]

    def test_handles_missing_tags_field(self):
        skill = {"name": "s", "version": "1.0"}
        assert _get_namespace_tags(skill) == []


class TestNamespaceDistribution:
    def test_default_tag_goes_to_all_namespaces(self):
        skills = [_make_registry_skill("s1", tags=["namespace:default"])]
        result = _namespace_distribution(skills, ["team1", "team2"])
        assert "s1" in [s["name"] for s in result["team1"]]
        assert "s1" in [s["name"] for s in result["team2"]]

    def test_specific_tag_goes_to_matching_namespace_only(self):
        skills = [_make_registry_skill("s1", tags=["namespace:team1"])]
        result = _namespace_distribution(skills, ["team1", "team2"])
        assert "s1" in [s["name"] for s in result["team1"]]
        assert result["team2"] == []

    def test_no_namespace_tag_treated_as_default(self):
        skills = [_make_registry_skill("s1", tags=["python"])]
        result = _namespace_distribution(skills, ["team1", "team2"])
        assert "s1" in [s["name"] for s in result["team1"]]
        assert "s1" in [s["name"] for s in result["team2"]]

    def test_specific_tag_for_unknown_namespace_is_ignored(self):
        skills = [_make_registry_skill("s1", tags=["namespace:team99"])]
        result = _namespace_distribution(skills, ["team1", "team2"])
        assert result["team1"] == []
        assert result["team2"] == []

    def test_multiple_namespace_tags(self):
        skills = [_make_registry_skill("s1", tags=["namespace:team1", "namespace:team2"])]
        result = _namespace_distribution(skills, ["team1", "team2"])
        assert "s1" in [s["name"] for s in result["team1"]]
        assert "s1" in [s["name"] for s in result["team2"]]

    def test_empty_registry_results_in_empty_distribution(self):
        result = _namespace_distribution([], ["team1"])
        assert result["team1"] == []


class TestApplyDiff:
    def test_creates_skill_not_in_kagenti(self):
        kube = MagicMock()
        target = [_make_registry_skill("new-skill")]
        local = []
        count = _apply_diff(kube, "team1", target, local, "http://reg", "skillberry")
        kube.core_api.create_namespaced_config_map.assert_called_once()
        assert count == 1

    def test_deletes_skill_removed_from_registry(self):
        kube = MagicMock()
        target = []
        local = [_make_local_cm("old-skill", "old-skill")]
        count = _apply_diff(kube, "team1", target, local, "http://reg", "skillberry")
        kube.core_api.delete_namespaced_config_map.assert_called_once_with(
            name="old-skill", namespace="team1"
        )
        assert count == 0

    def test_patches_version_when_changed(self):
        kube = MagicMock()
        target = [_make_registry_skill("my-skill", version="2.0")]
        local = [_make_local_cm("my-skill", "my-skill", version="1.0")]
        _apply_diff(kube, "team1", target, local, "http://reg", "skillberry")
        kube.core_api.patch_namespaced_config_map.assert_called_once()
        patch_body = kube.core_api.patch_namespaced_config_map.call_args[1]["body"]
        assert patch_body["metadata"]["annotations"][SKILL_REGISTRY_SKILL_VERSION_ANNOTATION] == "2.0"

    def test_no_op_when_version_unchanged(self):
        kube = MagicMock()
        target = [_make_registry_skill("my-skill", version="1.0")]
        local = [_make_local_cm("my-skill", "my-skill", version="1.0")]
        _apply_diff(kube, "team1", target, local, "http://reg", "skillberry")
        kube.core_api.create_namespaced_config_map.assert_not_called()
        kube.core_api.delete_namespaced_config_map.assert_not_called()
        kube.core_api.patch_namespaced_config_map.assert_not_called()


class TestGetAutosyncConfig:
    def test_returns_none_when_configmap_absent(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        assert _get_autosync_config(kube) is None

    def test_returns_data_dict_when_present(self):
        kube = MagicMock()
        cm = MagicMock()
        cm.data = {"enabled": "true", "registry-url": "http://reg", "registry-type": "skillberry", "sync-interval": "30"}
        kube.core_api.read_namespaced_config_map.return_value = cm
        config = _get_autosync_config(kube)
        assert config["enabled"] == "true"
        assert config["registry-url"] == "http://reg"


@pytest.mark.asyncio
class TestSyncSkillsOnce:
    async def test_returns_default_interval_when_not_configured(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        interval = await sync_skills_once(kube)
        assert interval == 30

    async def test_returns_default_interval_when_disabled(self):
        kube = MagicMock()
        cm = MagicMock()
        cm.data = {"enabled": "false", "registry-url": "http://reg", "sync-interval": "60"}
        kube.core_api.read_namespaced_config_map.return_value = cm
        interval = await sync_skills_once(kube)
        assert interval == 60

    async def test_returns_configured_interval_on_successful_sync(self):
        kube = MagicMock()
        cm = MagicMock()
        cm.data = {"enabled": "true", "registry-url": "http://reg", "registry-type": "skillberry", "sync-interval": "45"}
        kube.core_api.read_namespaced_config_map.return_value = cm
        kube.list_enabled_namespaces.return_value = ["team1"]
        kube.core_api.list_namespaced_config_map.return_value = MagicMock(items=[])
        with patch("app.services.skill_autosync._fetch_registry_skills", new=AsyncMock(return_value=[])):
            interval = await sync_skills_once(kube)
        assert interval == 45
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd kagenti/backend && uv run pytest tests/test_skill_autosync.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'app.services.skill_autosync'`

- [ ] **Step 3: Create the service**

Create `kagenti/backend/app/services/skill_autosync.py`:

```python
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


def _update_sync_status(
    kube: KubernetesService, skill_count: int, synced_at: str
) -> None:
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
        return response.json()


def _get_namespace_tags(skill: Dict[str, Any]) -> List[str]:
    """Return the values of namespace: tags on a Skillberry skill."""
    tags = skill.get("tags") or []
    return [t[len(SKILL_NS_TAG_PREFIX):] for t in tags if t.startswith(SKILL_NS_TAG_PREFIX)]


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
            logger.warning("Auto-sync: failed to create '%s' in '%s': %s", skill_name, namespace, exc)


def _patch_skill_version(
    kube: KubernetesService, namespace: str, resource_name: str, new_version: str
) -> None:
    body = {"metadata": {"annotations": {SKILL_REGISTRY_SKILL_VERSION_ANNOTATION: new_version}}}
    try:
        kube.core_api.patch_namespaced_config_map(
            name=resource_name, namespace=namespace, body=body
        )
        logger.info("Auto-sync: updated version for '%s' in '%s' → %s", resource_name, namespace, new_version)
    except ApiException as exc:
        logger.warning("Auto-sync: failed to patch version for '%s': %s", resource_name, exc)


def _delete_autosync_skill(
    kube: KubernetesService, namespace: str, resource_name: str
) -> None:
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
    if config is None or config.get("enabled") != "true":
        return int(config.get("sync-interval", settings.skill_autosync_interval)) if config else settings.skill_autosync_interval

    registry_url = config.get("registry-url", "")
    registry_type = config.get("registry-type", "skillberry")
    effective_interval = int(config.get("sync-interval", settings.skill_autosync_interval))

    if not registry_url:
        logger.warning("Auto-sync config present but registry-url is empty")
        return effective_interval

    try:
        registry_skills = await _fetch_registry_skills(registry_url)
    except Exception as exc:
        logger.warning("Auto-sync: failed to fetch skills from '%s': %s", registry_url, exc)
        return effective_interval

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
    """Background loop that periodically syncs skills from the configured registry."""
    await asyncio.sleep(settings.skill_autosync_interval)
    while True:
        interval = settings.skill_autosync_interval
        try:
            kube = get_kubernetes_service()
            interval = await sync_skills_once(kube)
        except Exception:
            logger.exception("Skill auto-sync error")
        await asyncio.sleep(interval)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd kagenti/backend && uv run pytest tests/test_skill_autosync.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Run linter**

```bash
cd kagenti/backend && uv run ruff check app/services/skill_autosync.py app/core/constants.py app/core/config.py
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add kagenti/backend/app/services/skill_autosync.py kagenti/backend/tests/test_skill_autosync.py
git commit -s -m "feat(skills): add auto-sync background service

Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"
```

---

## Task 3: Backend API endpoints (GET / POST / DELETE /skills/autosync)

**Files:**
- Modify: `kagenti/backend/app/routers/skills.py` (add 3 endpoints at bottom of file)

**Interfaces:**
- Consumes: `SkillAutoSyncRequest`, `SkillAutoSyncStatus` (from Task 1); `SKILL_AUTOSYNC_CONFIG_CM`, `SKILL_AUTOSYNC_LABEL`, `SKILL_TYPE_LABEL`, `SKILL_TYPE_VALUE` from constants; `KubernetesService`
- Produces: `GET /api/v1/skills/autosync` → `SkillAutoSyncStatus`; `POST /api/v1/skills/autosync` → `SkillAutoSyncStatus`; `DELETE /api/v1/skills/autosync` → HTTP 204

- [ ] **Step 1: Write failing route tests**

Create `kagenti/backend/tests/test_skill_autosync_api.py`:

```python
# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0
"""Tests for skill auto-sync REST endpoints."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from kubernetes.client.exceptions import ApiException

from app.main import app
from app.services.kubernetes import get_kubernetes_service
from app.core.constants import SKILL_AUTOSYNC_CONFIG_CM, SKILL_AUTOSYNC_LABEL, SKILL_TYPE_LABEL, SKILL_TYPE_VALUE


def _make_autosync_cm(enabled="true", registry_url="http://reg:8000", registry_type="skillberry", sync_interval="30", last_synced_at=None, skill_count=None):
    cm = MagicMock()
    cm.data = {
        "enabled": enabled,
        "registry-url": registry_url,
        "registry-type": registry_type,
        "sync-interval": sync_interval,
    }
    if last_synced_at:
        cm.data["last-synced-at"] = last_synced_at
    if skill_count is not None:
        cm.data["skill-count"] = str(skill_count)
    return cm


@pytest.fixture
def kube():
    mock = MagicMock()
    mock.list_enabled_namespaces.return_value = ["team1"]
    return mock


@pytest.fixture
def client(kube):
    app.dependency_overrides[get_kubernetes_service] = lambda: kube
    with patch("app.core.config.settings.kagenti_feature_flag_external_skills", True):
        with patch("app.core.config.settings.kagenti_feature_flag_skills", True):
            yield TestClient(app)
    app.dependency_overrides.clear()


class TestGetAutoSync:
    def test_returns_enabled_false_when_configmap_absent(self, client, kube):
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        resp = client.get("/api/v1/skills/autosync")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_returns_full_status_when_active(self, client, kube):
        kube.core_api.read_namespaced_config_map.return_value = _make_autosync_cm(
            last_synced_at="2026-06-17T10:00:00Z", skill_count=5
        )
        resp = client.get("/api/v1/skills/autosync")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["registryUrl"] == "http://reg:8000"
        assert body["syncInterval"] == 30
        assert body["skillCount"] == 5


class TestEnableAutoSync:
    def test_returns_409_when_skills_exist(self, client, kube):
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        skill_cm = MagicMock()
        skill_cm.items = [MagicMock()]
        kube.core_api.list_namespaced_config_map.return_value = skill_cm
        resp = client.post("/api/v1/skills/autosync", json={"registryUrl": "http://reg:8000", "registryType": "skillberry", "syncInterval": 30})
        assert resp.status_code == 409
        assert "existing skills" in resp.json()["detail"].lower()

    def test_creates_configmap_and_returns_status_when_no_skills_exist(self, client, kube):
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        skill_cm = MagicMock()
        skill_cm.items = []
        kube.core_api.list_namespaced_config_map.return_value = skill_cm
        resp = client.post("/api/v1/skills/autosync", json={"registryUrl": "http://reg:8000", "registryType": "skillberry", "syncInterval": 30})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
        kube.core_api.create_namespaced_config_map.assert_called_once()

    def test_rejects_invalid_registry_url(self, client, kube):
        resp = client.post("/api/v1/skills/autosync", json={"registryUrl": "not-a-url", "registryType": "skillberry", "syncInterval": 30})
        assert resp.status_code == 422


class TestDisableAutoSync:
    def test_deletes_all_autosync_skills_and_config(self, client, kube):
        autosync_cm = MagicMock()
        autosync_cm.items = [MagicMock(metadata=MagicMock(name="skill-a")), MagicMock(metadata=MagicMock(name="skill-b"))]
        kube.core_api.list_namespaced_config_map.return_value = autosync_cm
        resp = client.delete("/api/v1/skills/autosync")
        assert resp.status_code == 204
        assert kube.core_api.delete_namespaced_config_map.call_count >= 2

    def test_still_succeeds_when_configmap_already_absent(self, client, kube):
        kube.core_api.list_namespaced_config_map.return_value = MagicMock(items=[])
        kube.core_api.delete_namespaced_config_map.side_effect = ApiException(status=404)
        resp = client.delete("/api/v1/skills/autosync")
        assert resp.status_code == 204
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd kagenti/backend && uv run pytest tests/test_skill_autosync_api.py -v 2>&1 | head -30
```

Expected: failures (endpoints don't exist yet)

- [ ] **Step 3: Add the three endpoints to `routers/skills.py`**

At the bottom of `kagenti/backend/app/routers/skills.py`, append:

```python
# ---------------------------------------------------------------------------
# Auto-sync endpoints (feature-flagged: kagenti_feature_flag_external_skills)
# ---------------------------------------------------------------------------

_KAGENTI_SYSTEM = "kagenti-system"


def _get_autosync_configmap(kube: KubernetesService):
    """Read the auto-sync ConfigMap. Returns the CM object or None."""
    try:
        return kube.core_api.read_namespaced_config_map(
            name=SKILL_AUTOSYNC_CONFIG_CM, namespace=_KAGENTI_SYSTEM
        )
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise HTTPException(status_code=exc.status or 500, detail=str(exc))


def _configmap_to_autosync_status(cm) -> SkillAutoSyncStatus:
    data = cm.data or {}
    skill_count_raw = data.get("skill-count")
    return SkillAutoSyncStatus(
        enabled=data.get("enabled") == "true",
        registryType=data.get("registry-type"),
        registryUrl=data.get("registry-url"),
        syncInterval=int(data["sync-interval"]) if data.get("sync-interval") else None,
        lastSyncedAt=data.get("last-synced-at"),
        skillCount=int(skill_count_raw) if skill_count_raw else None,
    )


@router.get(
    "/autosync",
    response_model=SkillAutoSyncStatus,
)
async def get_autosync_status(
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SkillAutoSyncStatus:
    """Return current auto-sync status. Returns enabled=false when not configured."""
    if not settings.kagenti_feature_flag_external_skills:
        raise HTTPException(status_code=404, detail="Not Found")
    cm = _get_autosync_configmap(kube)
    if cm is None:
        return SkillAutoSyncStatus(enabled=False)
    return _configmap_to_autosync_status(cm)


@router.post(
    "/autosync",
    response_model=SkillAutoSyncStatus,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def enable_autosync(
    request: SkillAutoSyncRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SkillAutoSyncStatus:
    """Enable cluster-wide auto-sync. Rejects if any skills already exist."""
    if not settings.kagenti_feature_flag_external_skills:
        raise HTTPException(status_code=404, detail="Not Found")

    # Guard: no existing skills across any enabled namespace
    for namespace in kube.list_enabled_namespaces():
        try:
            existing = kube.core_api.list_namespaced_config_map(
                namespace=namespace,
                label_selector=f"{SKILL_TYPE_LABEL}={SKILL_TYPE_VALUE}",
            )
            if existing.items:
                raise HTTPException(
                    status_code=409,
                    detail="Remove all existing skills before enabling auto-sync",
                )
        except ApiException as exc:
            raise HTTPException(status_code=exc.status or 500, detail=str(exc))

    data = {
        "enabled": "true",
        "registry-type": request.registryType,
        "registry-url": request.registryUrl,
        "sync-interval": str(request.syncInterval),
    }
    body = k8s_client.V1ConfigMap(
        metadata=k8s_client.V1ObjectMeta(
            name=SKILL_AUTOSYNC_CONFIG_CM,
            namespace=_KAGENTI_SYSTEM,
            labels={"kagenti.io/type": "skill-autosync"},
        ),
        data=data,
    )
    try:
        kube.core_api.create_namespaced_config_map(namespace=_KAGENTI_SYSTEM, body=body)
    except ApiException as exc:
        if exc.status == 409:
            # Already exists — patch it
            kube.core_api.patch_namespaced_config_map(
                name=SKILL_AUTOSYNC_CONFIG_CM, namespace=_KAGENTI_SYSTEM, body={"data": data}
            )
        else:
            raise HTTPException(status_code=exc.status or 500, detail=str(exc))

    cm = _get_autosync_configmap(kube)
    return _configmap_to_autosync_status(cm)


@router.delete(
    "/autosync",
    status_code=204,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def disable_autosync(
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> None:
    """Disable auto-sync and delete all auto-synced skills across all namespaces."""
    if not settings.kagenti_feature_flag_external_skills:
        raise HTTPException(status_code=404, detail="Not Found")

    for namespace in kube.list_enabled_namespaces():
        try:
            cms = kube.core_api.list_namespaced_config_map(
                namespace=namespace,
                label_selector=f"{SKILL_TYPE_LABEL}={SKILL_TYPE_VALUE},{SKILL_AUTOSYNC_LABEL}=true",
            )
            for cm in cms.items:
                try:
                    kube.core_api.delete_namespaced_config_map(
                        name=cm.metadata.name, namespace=namespace
                    )
                except ApiException as exc:
                    if exc.status != 404:
                        logger.warning("Failed to delete auto-sync skill '%s': %s", cm.metadata.name, exc)
        except ApiException as exc:
            logger.warning("Failed to list auto-sync skills in '%s': %s", namespace, exc)

    try:
        kube.core_api.delete_namespaced_config_map(
            name=SKILL_AUTOSYNC_CONFIG_CM, namespace=_KAGENTI_SYSTEM
        )
    except ApiException as exc:
        if exc.status != 404:
            logger.warning("Failed to delete auto-sync config CM: %s", exc)
```

Also add `k8s_client` import at the top of `skills.py` if not already present — it's already there (`import kubernetes.client as k8s_client`).

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd kagenti/backend && uv run pytest tests/test_skill_autosync.py tests/test_skill_autosync_api.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Run linter**

```bash
cd kagenti/backend && uv run ruff check app/routers/skills.py
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add kagenti/backend/app/routers/skills.py kagenti/backend/tests/test_skill_autosync_api.py
git commit -s -m "feat(skills): add auto-sync REST endpoints (GET/POST/DELETE /skills/autosync)

Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"
```

---

## Task 4: Wire auto-sync loop into backend lifespan

**Files:**
- Modify: `kagenti/backend/app/main.py` (inside existing `external_skills` conditional block)

**Interfaces:**
- Consumes: `run_skill_autosync_loop` from `app.services.skill_autosync`; `settings.skill_autosync_interval`
- Produces: `skill_autosync_task` created in lifespan, cancelled on shutdown

- [ ] **Step 1: Add loop startup and shutdown to `main.py`**

In `kagenti/backend/app/main.py`, locate the `_skills_modules_loaded` block (around line 109). After it loads successfully, you'll wire the loop inside the `lifespan` function.

Find the `# Start build reconciliation loop` section in `lifespan` (around line 149). After the reconciliation task block, add:

```python
    # Start skill auto-sync loop (only when external_skills feature is enabled)
    skill_autosync_task = None
    if settings.kagenti_feature_flag_external_skills:
        from app.services.skill_autosync import run_skill_autosync_loop

        skill_autosync_task = asyncio.create_task(run_skill_autosync_loop())
        logger.info(
            "Skill auto-sync started (default interval: %ds)",
            settings.skill_autosync_interval,
        )
```

Then in the shutdown section (after `if reconciliation_task: reconciliation_task.cancel()`), add:

```python
    if skill_autosync_task:
        skill_autosync_task.cancel()
        try:
            await skill_autosync_task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 2: Verify the app starts cleanly**

```bash
cd kagenti/backend && uv run python -c "
import asyncio
from unittest.mock import patch
with patch('app.core.config.settings.kagenti_feature_flag_external_skills', False):
    from app.main import app
    print('App loaded OK')
"
```

Expected output: `App loaded OK`

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
cd kagenti/backend && uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all previously-passing tests still PASS

- [ ] **Step 4: Commit**

```bash
git add kagenti/backend/app/main.py
git commit -s -m "feat(skills): start auto-sync loop in backend lifespan

Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"
```

---

## Task 5: Frontend types and API client

**Files:**
- Modify: `kagenti/ui-v2/src/types/index.ts` (append near the existing Skill types)
- Modify: `kagenti/ui-v2/src/services/api.ts` (add 3 methods to `skillService`)

**Interfaces:**
- Produces: `SkillAutoSyncConfig` interface; `SkillAutoSyncStatus` interface; `skillService.getAutoSync()`, `skillService.enableAutoSync(cfg)`, `skillService.disableAutoSync()`

- [ ] **Step 1: Add types to `types/index.ts`**

Find the block where `CreateExternalSkillRequest` is defined (around line 460). After it, add:

```typescript
export interface SkillAutoSyncConfig {
  registryType: string
  registryUrl: string
  syncInterval: number
}

export interface SkillAutoSyncStatus {
  enabled: boolean
  registryType?: string
  registryUrl?: string
  syncInterval?: number
  lastSyncedAt?: string
  skillCount?: number
}
```

- [ ] **Step 2: Add import to `api.ts`**

In `kagenti/ui-v2/src/services/api.ts`, add `SkillAutoSyncConfig` and `SkillAutoSyncStatus` to the existing import from `@/types`:

```typescript
import type {
  // ... existing imports ...
  SkillAutoSyncConfig,
  SkillAutoSyncStatus,
} from '@/types';
```

- [ ] **Step 3: Add three methods to `skillService` in `api.ts`**

Inside `export const skillService = { ... }`, after the existing `createExternal` method and before the closing `};`, add:

```typescript
  async getAutoSync(): Promise<SkillAutoSyncStatus> {
    return apiFetch('/skills/autosync');
  },

  async enableAutoSync(cfg: SkillAutoSyncConfig): Promise<SkillAutoSyncStatus> {
    return apiFetch('/skills/autosync', {
      method: 'POST',
      body: JSON.stringify(cfg),
    });
  },

  async disableAutoSync(): Promise<void> {
    await apiFetch('/skills/autosync', { method: 'DELETE' });
  },
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd kagenti/ui-v2 && npx tsc --noEmit 2>&1 | grep -E "error TS|warning" | head -20
```

Expected: no errors relating to the new types or methods

- [ ] **Step 5: Commit**

```bash
git add kagenti/ui-v2/src/types/index.ts kagenti/ui-v2/src/services/api.ts
git commit -s -m "feat(skills): add auto-sync TypeScript types and API client methods

Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"
```

---

## Task 6: ImportSkillPage — auto-sync control panel

**Files:**
- Modify: `kagenti/ui-v2/src/pages/ImportSkillPage.tsx`

**Interfaces:**
- Consumes: `skillService.getAutoSync()`, `skillService.enableAutoSync()`, `skillService.disableAutoSync()` (Task 5); `SkillAutoSyncStatus`, `SkillAutoSyncConfig` (Task 5); `features.externalSkills` from `useFeatureFlags()`; `getSkillberryUiUrl` from `@/utils/validation`; `useQuery`, `useMutation` from `@tanstack/react-query`
- Produces: auto-sync panel rendered at the top of the "From Registry" tab; "Upload Files" tab disabled notice when sync is active

- [ ] **Step 1: Add new imports to `ImportSkillPage.tsx`**

Add these to the existing PatternFly import block (after existing imports):

```typescript
import {
  Modal,
  ModalVariant,
  Switch,
  NumberInput,
} from '@patternfly/react-core';
import { SyncAltIcon } from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { SkillAutoSyncConfig, SkillAutoSyncStatus } from '@/types';
```

Note: `useQuery` and `useMutation` are already imported — only add what is missing.

- [ ] **Step 2: Add auto-sync state variables**

Inside `ImportSkillPage`, after the existing state declarations, add:

```typescript
  const queryClient = useQueryClient();
  const [autoSyncRegistryUrl, setAutoSyncRegistryUrl] = React.useState('');
  const [autoSyncRegistryType, setAutoSyncRegistryType] = React.useState('skillberry');
  const [autoSyncInterval, setAutoSyncInterval] = React.useState(30);
  const [disableConfirmOpen, setDisableConfirmOpen] = React.useState(false);

  const { data: autoSyncStatus } = useQuery<SkillAutoSyncStatus>({
    queryKey: ['skillAutoSync'],
    queryFn: () => skillService.getAutoSync(),
    enabled: !!features.externalSkills,
    refetchInterval: 10_000,
  });

  const enableAutoSyncMutation = useMutation({
    mutationFn: (cfg: SkillAutoSyncConfig) => skillService.enableAutoSync(cfg),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['skillAutoSync'] }),
  });

  const disableAutoSyncMutation = useMutation({
    mutationFn: () => skillService.disableAutoSync(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skillAutoSync'] });
      setDisableConfirmOpen(false);
      navigate('/skills');
    },
  });

  const isAutoSyncActive = autoSyncStatus?.enabled === true;
```

- [ ] **Step 3: Replace the "From Registry" tab content**

Replace the entire `{features.externalSkills && (<Tab eventKey="registry" ...>...</Tab>)}` block with the following. This preserves all existing manual import form fields and adds the auto-sync panel at the top:

```tsx
{features.externalSkills && (
  <Tab eventKey="registry" title={<TabTitleText>From Registry</TabTitleText>}>
    <Card>
      <CardBody>
        {/* Auto-sync panel */}
        {isAutoSyncActive ? (
          <>
            <Alert
              variant="success"
              isInline
              title="Auto-sync active"
              style={{ marginBottom: '1.5rem' }}
              actionLinks={
                <>
                  <Button
                    variant="link"
                    component="a"
                    href={autoSyncStatus?.registryUrl ? `${autoSyncStatus.registryUrl}/` : '#'}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Manage skills in Skillberry Store ↗
                  </Button>
                  <Button
                    variant="link"
                    isDanger
                    onClick={() => setDisableConfirmOpen(true)}
                  >
                    Disable Auto-Sync
                  </Button>
                </>
              }
            >
              Syncing every {autoSyncStatus?.syncInterval ?? 30}s from{' '}
              <strong>{autoSyncStatus?.registryUrl}</strong>
              {autoSyncStatus?.skillCount !== undefined && (
                <span>
                  {' '}• {autoSyncStatus.skillCount} skills synced
                </span>
              )}
              {autoSyncStatus?.lastSyncedAt && (
                <span>
                  {' '}• Last synced: {new Date(autoSyncStatus.lastSyncedAt).toLocaleString()}
                </span>
              )}
            </Alert>

            <Modal
              variant={ModalVariant.small}
              title="Disable auto-sync?"
              isOpen={disableConfirmOpen}
              onClose={() => setDisableConfirmOpen(false)}
              actions={[
                <Button
                  key="confirm"
                  variant="danger"
                  isLoading={disableAutoSyncMutation.isPending}
                  onClick={() => disableAutoSyncMutation.mutate()}
                >
                  Disable and remove {autoSyncStatus?.skillCount ?? 'all'} synced skills
                </Button>,
                <Button key="cancel" variant="link" onClick={() => setDisableConfirmOpen(false)}>
                  Cancel
                </Button>,
              ]}
            >
              This will remove all auto-synced skills from Kagenti. Skills managed
              in Skillberry Store will not be affected.
            </Modal>
          </>
        ) : (
          <Form style={{ marginBottom: '2rem' }}>
            <TextContent style={{ marginBottom: '0.5rem' }}>
              <Title headingLevel="h3" size="md">Auto-Sync</Title>
              <Text component="p">
                Automatically keep Kagenti skills in sync with a remote registry.
                Skills are added, updated, and removed as the registry changes.
              </Text>
            </TextContent>
            <FormGroup label="Registry Type" fieldId="as-type">
              <Select
                isOpen={registryTypeOpen}
                onOpenChange={(isOpen) => setRegistryTypeOpen(isOpen)}
                selected={autoSyncRegistryType}
                onSelect={(_e, val) => {
                  setAutoSyncRegistryType(val as string);
                  setRegistryTypeOpen(false);
                }}
                toggle={(ref) => (
                  <MenuToggle ref={ref} onClick={() => setRegistryTypeOpen(!registryTypeOpen)}>
                    {autoSyncRegistryType}
                  </MenuToggle>
                )}
              >
                <SelectList>
                  <SelectOption value="skillberry">skillberry</SelectOption>
                </SelectList>
              </Select>
            </FormGroup>
            <FormGroup label="Registry URL" isRequired fieldId="as-url">
              <TextInput
                id="as-url"
                value={autoSyncRegistryUrl}
                onChange={(_e, v) => setAutoSyncRegistryUrl(v)}
                placeholder="http://skillberry.example.com:8000"
              />
            </FormGroup>
            <FormGroup label="Sync Interval" fieldId="as-interval">
              <Split hasGutter>
                <SplitItem>
                  <NumberInput
                    id="as-interval"
                    value={autoSyncInterval}
                    min={10}
                    max={3600}
                    onMinus={() => setAutoSyncInterval(Math.max(10, autoSyncInterval - 10))}
                    onPlus={() => setAutoSyncInterval(Math.min(3600, autoSyncInterval + 10))}
                    onChange={(e) => setAutoSyncInterval(Number((e.target as HTMLInputElement).value))}
                  />
                </SplitItem>
                <SplitItem style={{ lineHeight: '36px' }}>seconds</SplitItem>
              </Split>
            </FormGroup>
            {enableAutoSyncMutation.isError && (
              <Alert variant="danger" isInline title="Failed to enable auto-sync">
                {enableAutoSyncMutation.error instanceof Error
                  ? enableAutoSyncMutation.error.message
                  : 'An error occurred'}
              </Alert>
            )}
            <ActionGroup>
              <Button
                variant="primary"
                icon={<SyncAltIcon />}
                isLoading={enableAutoSyncMutation.isPending}
                isDisabled={!autoSyncRegistryUrl || enableAutoSyncMutation.isPending}
                onClick={() =>
                  enableAutoSyncMutation.mutate({
                    registryType: autoSyncRegistryType,
                    registryUrl: autoSyncRegistryUrl,
                    syncInterval: autoSyncInterval,
                  })
                }
              >
                Enable Auto-Sync
              </Button>
            </ActionGroup>
          </Form>
        )}

        {/* Manual import form — hidden when auto-sync is active */}
        {!isAutoSyncActive && (
          <Form>
            <FormGroup label="Namespace" isRequired fieldId="reg-namespace">
              <NamespaceSelector namespace={namespace} onNamespaceChange={setNamespace} />
            </FormGroup>
            <FormGroup label="Registry Type" isRequired fieldId="reg-type">
              <Select
                isOpen={registryTypeOpen}
                onOpenChange={(isOpen) => setRegistryTypeOpen(isOpen)}
                selected={registryType}
                onSelect={(_e, val) => {
                  setRegistryType(val as string);
                  setRegistryTypeOpen(false);
                }}
                toggle={(ref) => (
                  <MenuToggle
                    ref={ref}
                    onClick={() => setRegistryTypeOpen(!registryTypeOpen)}
                  >
                    {registryType}
                  </MenuToggle>
                )}
              >
                <SelectList>
                  <SelectOption value="skillberry">skillberry</SelectOption>
                  <SelectOption value="generic">generic</SelectOption>
                </SelectList>
              </Select>
            </FormGroup>
            <FormGroup label="Registry URL" isRequired fieldId="reg-url">
              <TextInput
                id="reg-url"
                value={registryUrl}
                onChange={(_e, v) => setRegistryUrl(v)}
                placeholder="http://host.docker.internal:8000"
              />
              <HelperText>
                <HelperTextItem>
                  Include <strong>http://</strong> or <strong>https://</strong> — e.g. <code>http://172.26.89.33:8000</code>
                </HelperTextItem>
              </HelperText>
              {registrySkillsError && (
                <Alert
                  variant="danger"
                  title="Could not load skills from registry"
                  isInline
                  isPlain
                  style={{ marginTop: '0.5rem' }}
                >
                  {registrySkillsError}
                </Alert>
              )}
            </FormGroup>
            <FormGroup label="Skill Name in Registry" isRequired fieldId="reg-skill-name">
              <Select
                isOpen={registrySkillNameOpen}
                onOpenChange={(isOpen) => setRegistrySkillNameOpen(isOpen)}
                onSelect={(_e, val) => {
                  const skill = registrySkills.find((s) => s.name === val);
                  if (skill) {
                    setRegistrySkillName(skill.name);
                    setRegistrySkillNameFilter(skill.name);
                    setRegistrySkillVersion(skill.version);
                    setRegistryName(skill.name);
                    setRegistryDescription(skill.description);
                  }
                  setRegistrySkillNameOpen(false);
                }}
                toggle={(ref) => (
                  <MenuToggle
                    ref={ref}
                    variant="typeahead"
                    onClick={() => {
                      if (!isSkillNameDisabled) setRegistrySkillNameOpen(!registrySkillNameOpen);
                    }}
                    isExpanded={registrySkillNameOpen}
                    isDisabled={isSkillNameDisabled}
                    style={{ width: '100%' }}
                  >
                    {registrySkillsLoading ? (
                      <Split hasGutter>
                        <SplitItem><Spinner size="sm" /></SplitItem>
                        <SplitItem>Loading skills...</SplitItem>
                      </Split>
                    ) : (
                      <TextInputGroup isPlain>
                        <TextInputGroupMain
                          value={registrySkillNameFilter}
                          onClick={() => setRegistrySkillNameOpen(true)}
                          onChange={(_e, val) => {
                            setRegistrySkillNameFilter(val);
                            if (val !== registrySkillName) setRegistrySkillName('');
                            if (!registrySkillNameOpen) setRegistrySkillNameOpen(true);
                          }}
                          autoComplete="off"
                          placeholder={isSkillNameDisabled ? 'Enter a valid Registry URL first' : 'Select or type a skill name'}
                        />
                        {registrySkillNameFilter && (
                          <TextInputGroupUtilities>
                            <Button
                              variant="plain"
                              onClick={() => {
                                setRegistrySkillNameFilter('');
                                setRegistrySkillName('');
                                setRegistrySkillVersion('');
                                setRegistryName('');
                                setRegistryDescription('');
                              }}
                              aria-label="Clear skill selection"
                            >
                              <TimesCircleIcon />
                            </Button>
                          </TextInputGroupUtilities>
                        )}
                      </TextInputGroup>
                    )}
                  </MenuToggle>
                )}
              >
                <SelectList>
                  {registrySkills
                    .filter(
                      (s) =>
                        !registrySkillNameFilter ||
                        s.name.toLowerCase().includes(registrySkillNameFilter.toLowerCase())
                    )
                    .map((s) => (
                      <SelectOption key={s.uuid} value={s.name} description={s.description}>
                        {s.name}
                      </SelectOption>
                    ))}
                  {!registrySkillsLoading && registrySkills.length === 0 && !registrySkillsError && isValidUrl(registryUrl) && (
                    <SelectOption key="empty" isDisabled value="">
                      No skills found in registry
                    </SelectOption>
                  )}
                </SelectList>
              </Select>
            </FormGroup>
            {registryType === 'skillberry' && registrySkillName && getSkillberryUiUrl(registryUrl, registrySkillName) && (
              <div style={{ marginTop: '0.25rem', fontSize: 'var(--pf-v5-global--FontSize--sm)' }}>
                <a
                  href={getSkillberryUiUrl(registryUrl, registrySkillName)}
                  target="_blank"
                  rel="noreferrer"
                >
                  View in skillberry-store ↗
                </a>
              </div>
            )}
            <FormGroup label="Version" fieldId="reg-version">
              <TextInput
                id="reg-version"
                value={registrySkillVersion}
                onChange={(_e, v) => setRegistrySkillVersion(v)}
                placeholder="latest"
                isDisabled={isRegistryFieldDisabled}
              />
            </FormGroup>
            <FormGroup label="Display Name" isRequired fieldId="reg-name">
              <TextInput
                id="reg-name"
                value={registryName}
                onChange={(_e, v) => setRegistryName(v)}
                isDisabled={isRegistryFieldDisabled}
              />
            </FormGroup>
            <FormGroup label="Description" fieldId="reg-description">
              <TextArea
                id="reg-description"
                value={registryDescription}
                onChange={(_e, v) => setRegistryDescription(v)}
                rows={3}
                isDisabled={isRegistryFieldDisabled}
              />
            </FormGroup>
            <FormGroup label="Category" fieldId="reg-category">
              <TextInput
                id="reg-category"
                value={registryCategory}
                onChange={(_e, v) => setRegistryCategory(v)}
                isDisabled={isRegistryFieldDisabled}
              />
            </FormGroup>
            {registryMutation.isError && (
              <Alert variant="danger" isInline title="Error creating external skill reference">
                {registryMutation.error instanceof Error
                  ? registryMutation.error.message
                  : 'An error occurred'}
              </Alert>
            )}
            <ActionGroup>
              <Button
                variant="primary"
                onClick={() => registryMutation.mutate()}
                isDisabled={
                  !registryName || !registryUrl || !registrySkillName || registryMutation.isPending
                }
                isLoading={registryMutation.isPending}
              >
                Register External Skill
              </Button>
              <Button variant="link" onClick={() => navigate('/skills')}>
                Cancel
              </Button>
            </ActionGroup>
          </Form>
        )}
      </CardBody>
    </Card>
  </Tab>
)}
```

- [ ] **Step 4: Add disabled notice to "Upload Files" tab**

In the "Upload Files" tab `<Card>` body, add this block at the very top, before `<TextContent>`:

```tsx
{isAutoSyncActive && (
  <Alert
    variant="info"
    isInline
    title="Auto-sync is active"
    style={{ marginBottom: '1rem' }}
  >
    Manual skill import is disabled while auto-sync is enabled.
    Go to the <strong>From Registry</strong> tab to disable auto-sync.
  </Alert>
)}
```

And disable the "Import Skill" submit button when auto-sync is active:

```tsx
<Button
  variant="primary"
  onClick={() => createMutation.mutate()}
  isLoading={createMutation.isPending}
  isDisabled={createMutation.isPending || submitSuccess || isAutoSyncActive}
>
  Import Skill
</Button>
```

Also add `NumberInput` to the PatternFly imports at the top of the file.

- [ ] **Step 5: TypeScript check**

```bash
cd kagenti/ui-v2 && npx tsc --noEmit 2>&1 | grep "error TS" | head -20
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add kagenti/ui-v2/src/pages/ImportSkillPage.tsx
git commit -s -m "feat(skills): add auto-sync control panel to Import Skill page

Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"
```

---

## Task 7: SkillCatalogPage — banner, badge, and button swap

**Files:**
- Modify: `kagenti/ui-v2/src/pages/SkillCatalogPage.tsx`

**Interfaces:**
- Consumes: `skillService.getAutoSync()` (Task 5); `SkillAutoSyncStatus` (Task 5); `useQuery` already imported; `Alert`, `ExternalLinkAltIcon` from PatternFly
- Produces: auto-sync banner, "Auto-synced" badge on skills, "Manage in Skillberry Store ↗" button swap

- [ ] **Step 1: Add new imports to `SkillCatalogPage.tsx`**

Add to the existing PatternFly import block:

```typescript
  Alert,
```

Add to PatternFly icons import block (or add a new one):

```typescript
import { PlusCircleIcon, WrenchIcon, ExternalLinkAltIcon } from '@patternfly/react-icons';
```

Add type import:

```typescript
import { Skill, SkillAutoSyncStatus } from '@/types';
import { skillService } from '@/services/api';
```

(`skillService` is already imported — only add what is missing.)

- [ ] **Step 2: Add auto-sync status query**

Inside `SkillCatalogPage`, after the existing `useQuery` for skills, add:

```typescript
  const { data: autoSyncStatus } = useQuery<SkillAutoSyncStatus>({
    queryKey: ['skillAutoSync'],
    queryFn: () => skillService.getAutoSync(),
  });

  const isAutoSyncActive = autoSyncStatus?.enabled === true;
```

- [ ] **Step 3: Add banner and swap the import button**

Replace the existing `<Button variant="primary" icon={<PlusCircleIcon />} onClick={() => navigate('/skills/import')}>Import Skill</Button>` with:

```tsx
{isAutoSyncActive ? (
  <Button
    variant="secondary"
    icon={<ExternalLinkAltIcon />}
    component="a"
    href={autoSyncStatus?.registryUrl ? `${autoSyncStatus.registryUrl}/` : '#'}
    target="_blank"
    rel="noreferrer"
  >
    Manage in Skillberry Store ↗
  </Button>
) : (
  <Button
    variant="primary"
    icon={<PlusCircleIcon />}
    onClick={() => navigate('/skills/import')}
  >
    Import Skill
  </Button>
)}
```

Add the auto-sync banner after `<PageSection>` (the toolbar section opening tag), before `<Toolbar>`:

```tsx
{isAutoSyncActive && (
  <Alert
    variant="info"
    isInline
    title={`Auto-sync active — syncing from ${autoSyncStatus?.registryUrl}`}
    style={{ marginBottom: '1rem' }}
    actionLinks={
      <Button
        variant="link"
        component="a"
        href={autoSyncStatus?.registryUrl ? `${autoSyncStatus.registryUrl}/` : '#'}
        target="_blank"
        rel="noreferrer"
      >
        Manage in Skillberry Store ↗
      </Button>
    }
  />
)}
```

- [ ] **Step 4: Add "Auto-synced" badge**

In the skill table row, find the `<Td dataLabel="Name">` cell. After the existing `External` label, add:

```tsx
{skill.labels?.['kagenti.io/auto-sync'] === 'true' && (
  <Label color="green" isCompact style={{ marginLeft: '0.5rem' }}>
    Auto-synced
  </Label>
)}
```

Note: The `Skill` type's `labels` field is `SkillLabels` which has `category` and `type`. The raw K8s label `kagenti.io/auto-sync` is not in the typed labels. Check if the backend `_configmap_to_skill` function includes it, or if we need to add it.

Looking at `_configmap_to_skill` in `skills.py`: the `labels` field only populates `category` and `type`. To surface the auto-sync label to the frontend, update `_configmap_to_skill` to also include `autoSync` in `SkillLabels`.

**Update `SkillLabels` model in `skills.py`:**

```python
class SkillLabels(BaseModel):
    category: Optional[str] = None
    type: Optional[str] = None
    autoSync: Optional[str] = None  # "true" when managed by auto-sync
```

**Update `_configmap_to_skill` to populate it:**

```python
    return Skill(
        ...
        labels=SkillLabels(
            category=labels.get(SKILL_CATEGORY_LABEL),
            type=labels.get("kagenti.io/skill-type"),
            autoSync=labels.get(SKILL_AUTOSYNC_LABEL),  # "true" or None
        ),
        ...
    )
```

**Update `SkillLabels` TypeScript interface in `types/index.ts`:**

```typescript
interface SkillLabels {
  category?: string
  type?: string
  autoSync?: string
}
```

**Update the badge in `SkillCatalogPage.tsx` to use the typed field:**

```tsx
{skill.labels?.autoSync === 'true' && (
  <Label color="green" isCompact style={{ marginLeft: '0.5rem' }}>
    Auto-synced
  </Label>
)}
```

- [ ] **Step 5: TypeScript check**

```bash
cd kagenti/ui-v2 && npx tsc --noEmit 2>&1 | grep "error TS" | head -20
```

Expected: no errors

- [ ] **Step 6: Run backend tests to check SkillLabels change doesn't break anything**

```bash
cd kagenti/backend && uv run pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add kagenti/ui-v2/src/pages/SkillCatalogPage.tsx kagenti/ui-v2/src/types/index.ts kagenti/backend/app/routers/skills.py
git commit -s -m "feat(skills): add auto-sync banner, badge, and button swap to Skill Catalog

Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run full backend test suite**

```bash
cd kagenti/backend && uv run pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests PASS

- [ ] **Run linter**

```bash
make lint
```

Expected: no errors

- [ ] **Run TypeScript check**

```bash
cd kagenti/ui-v2 && npx tsc --noEmit
```

Expected: no errors
