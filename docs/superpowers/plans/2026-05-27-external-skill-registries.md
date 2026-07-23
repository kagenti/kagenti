---
draft: true       # excluded from https://www.rossoctl.dev/
---

# External Skill Registries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add external registry skill references — ConfigMaps that link to a remote skill registry — and fetch skill content into agent pods at startup via an `alpine:3` init container.

**Architecture:** A new `rossoctl.io/source=external` label distinguishes registry references (empty `data:`) from local skills (full content in `data:`). At agent creation, the backend computes `local_skills` and `external_skills` from `request.skills`, generates init container specs for external ones, then passes the results to the existing manifest builders via new optional parameters. A Rossoctl-managed `rossoctl-skill-fetcher-scripts` ConfigMap in each team namespace holds the per-registry shell scripts.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / kubernetes-client / React 18 / PatternFly 5 / TypeScript

**GitHub issue:** rossoctl/rossoctl#1691  
**Design spec:** `docs/superpowers/specs/2026-05-27-external-skill-registries-design.md`

---

## File Map

| File | Change |
|---|---|
| `rossoctl/backend/app/core/config.py` | Add `rossoctl_feature_flag_external_skills` |
| `rossoctl/backend/app/core/constants.py` | Add 8 new skill registry constants |
| `rossoctl/backend/app/routers/config.py` | Add `externalSkills` to `FeatureFlagsResponse` |
| `rossoctl/backend/app/routers/skills.py` | New models, helpers, `POST /skills/external` endpoint |
| `rossoctl/backend/app/routers/agents.py` | New helpers, modified mount logic, init container injection |
| `rossoctl/backend/tests/test_skills.py` | Tests for new models and endpoint |
| `rossoctl/backend/tests/test_agents_external_skills.py` | New test file for agents helpers |
| `rossoctl/ui-v2/src/types/index.ts` | Extend `Skill`, add `ExternalSkillInfo`, `CreateExternalSkillRequest` |
| `rossoctl/ui-v2/src/services/api.ts` | Add `skillService.createExternal()` |
| `rossoctl/ui-v2/src/hooks/useFeatureFlags.ts` | Add `externalSkills` flag |
| `rossoctl/ui-v2/src/pages/SkillCatalogPage.tsx` | Add "External" badge |
| `rossoctl/ui-v2/src/pages/SkillDetailPage.tsx` | Registry info card for external skills |
| `rossoctl/ui-v2/src/pages/ImportSkillPage.tsx` | "From Registry" tab |

---

## Task 1: Feature flag + constants

**Files:**
- Modify: `rossoctl/backend/app/core/config.py` (after line 80, inside the feature flags block)
- Modify: `rossoctl/backend/app/core/constants.py` (after line 173, after `AGENT_ENDPOINT`)
- Modify: `rossoctl/backend/app/routers/config.py` (lines 27-78)

- [ ] **Step 1.1: Add feature flag to config.py**

In `rossoctl/backend/app/core/config.py`, after line 80 (`rossoctl_feature_flag_acp: bool = False`):

```python
    rossoctl_feature_flag_external_skills: bool = False  # External skill registry references
```

- [ ] **Step 1.2: Add constants to constants.py**

In `rossoctl/backend/app/core/constants.py`, after the `AGENT_ENDPOINT` constant (line 173):

```python
# External skill registry constants
SKILL_SOURCE_LABEL = "rossoctl.io/source"
SKILL_SOURCE_EXTERNAL = "external"
SKILL_REGISTRY_TYPE_LABEL = "rossoctl.io/registry-type"
SKILL_REGISTRY_URL_ANNOTATION = "rossoctl.io/registry-url"
SKILL_REGISTRY_SKILL_NAME_ANNOTATION = "rossoctl.io/registry-skill-name"
SKILL_REGISTRY_SKILL_VERSION_ANNOTATION = "rossoctl.io/registry-skill-version"
SKILL_FETCHER_SCRIPTS_CM = "rossoctl-skill-fetcher-scripts"
SKILL_FETCHER_IMAGE = "alpine:3"
```

- [ ] **Step 1.3: Expose new flag in config.py router**

In `rossoctl/backend/app/routers/config.py`, add field to `FeatureFlagsResponse` (after line 35 `skills: bool = ...`):

```python
    externalSkills: bool = Field(description="External skill registry references")
```

And in the `get_feature_flags` function body (after `skills=settings.rossoctl_feature_flag_skills,`), add:

```python
        externalSkills=settings.rossoctl_feature_flag_external_skills,
```

- [ ] **Step 1.4: Verify the app starts**

```bash
cd rossoctl/backend
uv run uvicorn app.main:app --reload &
curl -s http://localhost:8000/api/config/features | python3 -m json.tool
# Expected: JSON with "externalSkills": false
pkill -f uvicorn
```

- [ ] **Step 1.5: Commit**

```bash
git add rossoctl/backend/app/core/config.py \
        rossoctl/backend/app/core/constants.py \
        rossoctl/backend/app/routers/config.py
git commit -s -m "feat(skills): add external_skills feature flag and registry constants

Adds rossoctl_feature_flag_external_skills (default False) and 8 new
constants for external skill registry support (rossoctl/rossoctl#1691).

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 2: skills.py — models, helpers, _is_external

**Files:**
- Modify: `rossoctl/backend/app/routers/skills.py`
- Modify: `rossoctl/backend/tests/test_skills.py`

- [ ] **Step 2.1: Write failing tests for new models and helpers**

Add to `rossoctl/backend/tests/test_skills.py`:

```python
from app.routers.skills import (
    _is_external,
    _configmap_to_external_skill_info,
    _configmap_to_skill,
)
from app.core.constants import (
    SKILL_SOURCE_LABEL, SKILL_SOURCE_EXTERNAL,
    SKILL_REGISTRY_TYPE_LABEL, SKILL_REGISTRY_URL_ANNOTATION,
    SKILL_REGISTRY_SKILL_NAME_ANNOTATION, SKILL_REGISTRY_SKILL_VERSION_ANNOTATION,
    SKILL_TYPE_LABEL, SKILL_TYPE_VALUE, SKILL_DISPLAY_NAME_ANNOTATION,
    SKILL_DESCRIPTION_ANNOTATION,
)
from unittest.mock import MagicMock
import datetime


def _make_cm(labels=None, annotations=None, data=None, name="test-skill"):
    """Build a minimal mock ConfigMap for testing."""
    cm = MagicMock()
    cm.metadata.name = name
    cm.metadata.namespace = "team1"
    cm.metadata.labels = labels or {}
    cm.metadata.annotations = annotations or {}
    cm.metadata.creation_timestamp = datetime.datetime(2026, 1, 1)
    cm.data = data or {}
    return cm


class TestIsExternal:
    def test_returns_true_for_external_label(self):
        cm = _make_cm(labels={SKILL_SOURCE_LABEL: SKILL_SOURCE_EXTERNAL})
        assert _is_external(cm) is True

    def test_returns_false_for_local_skill(self):
        cm = _make_cm(labels={SKILL_TYPE_LABEL: SKILL_TYPE_VALUE})
        assert _is_external(cm) is False

    def test_returns_false_when_no_source_label(self):
        cm = _make_cm(labels={})
        assert _is_external(cm) is False


class TestConfigmapToExternalSkillInfo:
    def test_builds_info_from_annotations(self):
        cm = _make_cm(
            labels={
                SKILL_SOURCE_LABEL: SKILL_SOURCE_EXTERNAL,
                SKILL_REGISTRY_TYPE_LABEL: "skillberry",
            },
            annotations={
                SKILL_REGISTRY_URL_ANNOTATION: "https://skillberry.example.com",
                SKILL_REGISTRY_SKILL_NAME_ANNOTATION: "code-review",
                SKILL_REGISTRY_SKILL_VERSION_ANNOTATION: "1.2.0",
            },
        )
        info = _configmap_to_external_skill_info(cm)
        assert info.registryType == "skillberry"
        assert info.registryUrl == "https://skillberry.example.com"
        assert info.registrySkillName == "code-review"
        assert info.registrySkillVersion == "1.2.0"

    def test_defaults_version_to_latest(self):
        cm = _make_cm(
            labels={SKILL_REGISTRY_TYPE_LABEL: "skillberry"},
            annotations={
                SKILL_REGISTRY_URL_ANNOTATION: "https://example.com",
                SKILL_REGISTRY_SKILL_NAME_ANNOTATION: "my-skill",
            },
        )
        info = _configmap_to_external_skill_info(cm)
        assert info.registrySkillVersion == "latest"


class TestConfigmapToSkillSourceField:
    def test_local_skill_has_no_source(self):
        cm = _make_cm(
            labels={SKILL_TYPE_LABEL: SKILL_TYPE_VALUE},
            annotations={SKILL_DISPLAY_NAME_ANNOTATION: "My Skill"},
            data={"SKILL.md": "# content"},
        )
        skill = _configmap_to_skill(cm)
        assert skill.source is None
        assert skill.externalInfo is None

    def test_external_skill_has_source_and_info(self):
        cm = _make_cm(
            labels={
                SKILL_TYPE_LABEL: SKILL_TYPE_VALUE,
                SKILL_SOURCE_LABEL: SKILL_SOURCE_EXTERNAL,
                SKILL_REGISTRY_TYPE_LABEL: "skillberry",
            },
            annotations={
                SKILL_DISPLAY_NAME_ANNOTATION: "Code Review",
                SKILL_REGISTRY_URL_ANNOTATION: "https://example.com",
                SKILL_REGISTRY_SKILL_NAME_ANNOTATION: "code-review",
            },
        )
        skill = _configmap_to_skill(cm)
        assert skill.source == "external"
        assert skill.externalInfo is not None
        assert skill.externalInfo.registryType == "skillberry"
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```bash
cd rossoctl/backend
uv run pytest tests/test_skills.py::TestIsExternal tests/test_skills.py::TestConfigmapToExternalSkillInfo tests/test_skills.py::TestConfigmapToSkillSourceField -v 2>&1 | tail -20
# Expected: ImportError or AttributeError — functions/classes don't exist yet
```

- [ ] **Step 2.3: Add new models and helpers to skills.py**

In `rossoctl/backend/app/routers/skills.py`:

**a) Add imports** at the top of the file (after existing imports):

```python
from app.core.constants import (
    # ... existing imports ...,
    SKILL_SOURCE_LABEL,
    SKILL_SOURCE_EXTERNAL,
    SKILL_REGISTRY_TYPE_LABEL,
    SKILL_REGISTRY_URL_ANNOTATION,
    SKILL_REGISTRY_SKILL_NAME_ANNOTATION,
    SKILL_REGISTRY_SKILL_VERSION_ANNOTATION,
)
```

**b) Add `ExternalSkillInfo` model** (add after the existing `SkillLabels` model, before `Skill`):

```python
class ExternalSkillInfo(BaseModel):
    """Registry metadata for externally-sourced skills."""

    registryType: str
    registryUrl: str
    registrySkillName: str
    registrySkillVersion: str
```

**c) Update `Skill` model** — add two optional fields after `usageCount`:

```python
    source: Optional[str] = None          # "external" or None for local
    externalInfo: Optional[ExternalSkillInfo] = None
```

Make sure `Optional` is imported: add `from typing import Optional` if not already present.

**d) Add `_is_external` helper** (add after the existing `_sanitize_configmap_key` / `_desanitize_configmap_key` helpers):

```python
def _is_external(cm) -> bool:
    """Return True if the ConfigMap is an external skill registry reference."""
    labels = cm.metadata.labels or {}
    return labels.get(SKILL_SOURCE_LABEL) == SKILL_SOURCE_EXTERNAL


def _configmap_to_external_skill_info(cm) -> ExternalSkillInfo:
    """Build ExternalSkillInfo from a registry-reference ConfigMap's annotations."""
    labels = cm.metadata.labels or {}
    annotations = cm.metadata.annotations or {}
    return ExternalSkillInfo(
        registryType=labels.get(SKILL_REGISTRY_TYPE_LABEL, ""),
        registryUrl=annotations.get(SKILL_REGISTRY_URL_ANNOTATION, ""),
        registrySkillName=annotations.get(SKILL_REGISTRY_SKILL_NAME_ANNOTATION, ""),
        registrySkillVersion=annotations.get(SKILL_REGISTRY_SKILL_VERSION_ANNOTATION, "latest"),
    )
```

**e) Update `_configmap_to_skill()`** — add source/externalInfo population at the end of the function (just before `return Skill(...)`). Find the existing return statement and update it to include:

```python
    source = SKILL_SOURCE_EXTERNAL if _is_external(cm) else None
    external_info = _configmap_to_external_skill_info(cm) if _is_external(cm) else None

    return Skill(
        # ... all existing fields ...,
        source=source,
        externalInfo=external_info,
    )
```

**f) Update `_configmap_to_skill_detail()`** — for external skills, `files` and `dataKeys` must be empty. Find the line where `files` is built (it iterates over `cm.data`) and wrap it:

```python
    if _is_external(cm):
        files = []
        data_keys = []
    else:
        # existing code that builds files from cm.data
        data_keys = list((cm.data or {}).keys())
        files = [...]  # existing file building logic
```

- [ ] **Step 2.4: Run tests to confirm they pass**

```bash
cd rossoctl/backend
uv run pytest tests/test_skills.py::TestIsExternal tests/test_skills.py::TestConfigmapToExternalSkillInfo tests/test_skills.py::TestConfigmapToSkillSourceField -v 2>&1 | tail -20
# Expected: 7 PASSED
```

- [ ] **Step 2.5: Run full test suite to catch regressions**

```bash
cd rossoctl/backend
uv run pytest tests/ -v 2>&1 | tail -30
# Expected: all existing tests still pass
```

- [ ] **Step 2.6: Commit**

```bash
git add rossoctl/backend/app/routers/skills.py \
        rossoctl/backend/tests/test_skills.py
git commit -s -m "feat(skills): add ExternalSkillInfo model and _is_external helpers

Adds ExternalSkillInfo Pydantic model, _is_external(), and
_configmap_to_external_skill_info() helpers. Updates Skill model
and _configmap_to_skill/_configmap_to_skill_detail to populate
source/externalInfo fields for registry-reference ConfigMaps.
Refs rossoctl/rossoctl#1691.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 3: skills.py — POST /skills/external endpoint

**Files:**
- Modify: `rossoctl/backend/app/routers/skills.py`
- Modify: `rossoctl/backend/tests/test_skills.py`

- [ ] **Step 3.1: Write failing test for create_external_skill endpoint**

Add to `rossoctl/backend/tests/test_skills.py`:

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


def _make_test_app():
    """Create a minimal FastAPI app with the skills router for testing."""
    from fastapi import FastAPI
    from app.routers.skills import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


class TestCreateExternalSkill:
    def test_create_external_skill_returns_success(self):
        """POST /api/skills/external creates a registry-reference ConfigMap."""
        mock_kube = MagicMock()
        mock_kube.core_api.create_namespaced_config_map.return_value = MagicMock(
            metadata=MagicMock(name="skillberry-code-review", namespace="team1")
        )

        with patch("app.routers.skills.get_kubernetes_service", return_value=mock_kube), \
             patch("app.core.config.settings.rossoctl_feature_flag_external_skills", True), \
             patch("app.core.config.settings.rossoctl_feature_flag_skills", True):
            client = TestClient(_make_test_app())
            resp = client.post("/api/skills/external", json={
                "name": "Code Review",
                "namespace": "team1",
                "description": "Reviews code for quality",
                "category": "development",
                "registryType": "skillberry",
                "registryUrl": "https://skillberry.example.com",
                "registrySkillName": "code-review",
                "registrySkillVersion": "1.2.0",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "skillberry" in body["name"] or "code-review" in body["name"]

    def test_create_external_skill_returns_404_when_flag_off(self):
        """POST /api/skills/external returns 404 when feature flag is disabled."""
        mock_kube = MagicMock()
        with patch("app.routers.skills.get_kubernetes_service", return_value=mock_kube), \
             patch("app.core.config.settings.rossoctl_feature_flag_external_skills", False), \
             patch("app.core.config.settings.rossoctl_feature_flag_skills", True):
            client = TestClient(_make_test_app())
            resp = client.post("/api/skills/external", json={
                "name": "test",
                "namespace": "team1",
                "registryType": "skillberry",
                "registryUrl": "https://example.com",
                "registrySkillName": "test",
            })
        assert resp.status_code == 404
```

- [ ] **Step 3.2: Run test to confirm it fails**

```bash
cd rossoctl/backend
uv run pytest tests/test_skills.py::TestCreateExternalSkill -v 2>&1 | tail -10
# Expected: FAILED (404 Not Found or missing route)
```

- [ ] **Step 3.3: Add CreateExternalSkillRequest model and endpoint to skills.py**

**a) Add `CreateExternalSkillRequest` model** (add after `CreateSkillRequest`):

```python
class CreateExternalSkillRequest(BaseModel):
    name: str
    namespace: str
    description: str = ""
    category: str = ""
    registryType: str
    registryUrl: str
    registrySkillName: str
    registrySkillVersion: str = "latest"
    origin: str = ""
```

**b) Add endpoint** (add after the existing `POST /skills` endpoint, before the usage endpoint):

```python
@router.post("/skills/external", response_model=CreateSkillResponse)
async def create_external_skill(
    request: CreateExternalSkillRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
    _: None = Depends(require_roles(ROLE_OPERATOR)),
) -> CreateSkillResponse:
    """Create an external skill registry reference (feature-flagged)."""
    if not settings.rossoctl_feature_flag_external_skills:
        raise HTTPException(status_code=404, detail="Not Found")

    if not request.registryType:
        raise HTTPException(status_code=400, detail="registryType is required")

    resource_name = _sanitize_k8s_name(request.name)
    labels: Dict[str, str] = {
        SKILL_TYPE_LABEL: SKILL_TYPE_VALUE,
        SKILL_SOURCE_LABEL: SKILL_SOURCE_EXTERNAL,
        SKILL_REGISTRY_TYPE_LABEL: request.registryType,
        APP_KUBERNETES_IO_NAME: resource_name,
        APP_KUBERNETES_IO_MANAGED_BY: ROSSOCTL_UI_CREATOR_LABEL,
    }
    if request.category:
        labels[SKILL_CATEGORY_LABEL] = request.category

    annotations: Dict[str, str] = {
        SKILL_DISPLAY_NAME_ANNOTATION: request.name,
        SKILL_USAGE_ANNOTATION: "0",
        SKILL_REGISTRY_URL_ANNOTATION: request.registryUrl,
        SKILL_REGISTRY_SKILL_NAME_ANNOTATION: request.registrySkillName,
        SKILL_REGISTRY_SKILL_VERSION_ANNOTATION: request.registrySkillVersion,
    }
    if request.description:
        annotations[SKILL_DESCRIPTION_ANNOTATION] = request.description
    if request.origin:
        annotations[SKILL_ORIGIN_ANNOTATION] = request.origin

    body = kubernetes.client.V1ConfigMap(
        metadata=kubernetes.client.V1ObjectMeta(
            name=resource_name,
            namespace=request.namespace,
            labels=labels,
            annotations=annotations,
        ),
        data={},
    )
    try:
        kube.core_api.create_namespaced_config_map(namespace=request.namespace, body=body)
    except ApiException as e:
        if e.status == 409:
            raise HTTPException(
                status_code=409, detail=f"Skill '{resource_name}' already exists"
            )
        raise HTTPException(status_code=500, detail=f"Kubernetes error: {e.reason}")

    return CreateSkillResponse(
        success=True,
        name=resource_name,
        namespace=request.namespace,
        message=f"External skill reference '{resource_name}' created successfully",
    )
```

Note: `APP_KUBERNETES_IO_NAME`, `APP_KUBERNETES_IO_MANAGED_BY`, `ROSSOCTL_UI_CREATOR_LABEL` are already imported in `skills.py` from `constants.py`. Add the new constants to the imports block at the top.

- [ ] **Step 3.4: Run tests to confirm they pass**

```bash
cd rossoctl/backend
uv run pytest tests/test_skills.py::TestCreateExternalSkill -v 2>&1 | tail -10
# Expected: 2 PASSED
```

- [ ] **Step 3.5: Run full test suite**

```bash
cd rossoctl/backend
uv run pytest tests/ -v 2>&1 | tail -30
# Expected: all tests pass
```

- [ ] **Step 3.6: Commit**

```bash
git add rossoctl/backend/app/routers/skills.py \
        rossoctl/backend/tests/test_skills.py
git commit -s -m "feat(skills): add POST /skills/external endpoint

Adds CreateExternalSkillRequest model and create_external_skill endpoint.
Creates registry-reference ConfigMaps with empty data and registry
metadata in annotations. Gated behind rossoctl_feature_flag_external_skills.
Refs rossoctl/rossoctl#1691.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 4: agents.py — external skill mount logic

**Files:**
- Modify: `rossoctl/backend/app/routers/agents.py`
- Create: `rossoctl/backend/tests/test_agents_external_skills.py`

The core change: 4 manifest builder functions (`_build_deployment_manifest`, `_build_statefulset_manifest`, `_build_job_manifest`, `_build_sandbox_manifest`) each call `_get_linked_skill_mounts(request)` at their top. We add new optional keyword parameters and a second call to get external skill data. `_get_linked_skill_mounts` gains a `skills_override` parameter to accept only local skills. `_build_env_vars` gains `ext_skill_paths` to combine local + external paths.

- [ ] **Step 4.1: Write failing tests**

Create `rossoctl/backend/tests/test_agents_external_skills.py`:

```python
# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0
"""Tests for external skill mount helpers in agents.py."""

import pytest
from unittest.mock import MagicMock, patch
from app.routers.agents import (
    _is_skill_external,
    _build_fetcher_scripts_data,
    _ensure_fetcher_scripts_cm,
    _get_external_skill_data,
)
from app.core.constants import (
    SKILL_SOURCE_LABEL, SKILL_SOURCE_EXTERNAL, SKILL_TYPE_LABEL, SKILL_TYPE_VALUE,
    SKILL_REGISTRY_TYPE_LABEL, SKILL_REGISTRY_URL_ANNOTATION,
    SKILL_REGISTRY_SKILL_NAME_ANNOTATION, SKILL_REGISTRY_SKILL_VERSION_ANNOTATION,
    SKILL_FETCHER_SCRIPTS_CM, SKILL_FETCHER_IMAGE, AGENT_SKILLS_MOUNT_ROOT,
)


def _make_ext_cm(name, registry_type="skillberry", registry_url="https://example.com",
                 skill_name="my-skill", skill_version="1.0.0"):
    cm = MagicMock()
    cm.metadata.name = name
    cm.metadata.labels = {
        SKILL_SOURCE_LABEL: SKILL_SOURCE_EXTERNAL,
        SKILL_TYPE_LABEL: SKILL_TYPE_VALUE,
        SKILL_REGISTRY_TYPE_LABEL: registry_type,
    }
    cm.metadata.annotations = {
        SKILL_REGISTRY_URL_ANNOTATION: registry_url,
        SKILL_REGISTRY_SKILL_NAME_ANNOTATION: skill_name,
        SKILL_REGISTRY_SKILL_VERSION_ANNOTATION: skill_version,
    }
    cm.data = {}
    return cm


def _make_local_cm(name):
    cm = MagicMock()
    cm.metadata.name = name
    cm.metadata.labels = {SKILL_TYPE_LABEL: SKILL_TYPE_VALUE}
    cm.metadata.annotations = {}
    cm.data = {"SKILL.md": "# content"}
    return cm


class TestIsSkillExternal:
    def test_returns_true_for_external_configmap(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = _make_ext_cm("my-skill")
        assert _is_skill_external(kube, "team1", "my-skill") is True

    def test_returns_false_for_local_configmap(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = _make_local_cm("my-skill")
        assert _is_skill_external(kube, "team1", "my-skill") is False

    def test_returns_false_when_configmap_not_found(self):
        from kubernetes.client.exceptions import ApiException
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        assert _is_skill_external(kube, "team1", "missing-skill") is False


class TestBuildFetcherScriptsData:
    def test_returns_dict_with_skillberry_and_generic_scripts(self):
        data = _build_fetcher_scripts_data()
        assert "skillberry.sh" in data
        assert "generic.sh" in data
        assert "curl" in data["skillberry.sh"]
        assert "REGISTRY_URL" in data["skillberry.sh"]
        assert "TARGET_DIR" in data["skillberry.sh"]

    def test_scripts_are_valid_shell(self):
        data = _build_fetcher_scripts_data()
        assert data["skillberry.sh"].startswith("#!/bin/sh")
        assert data["generic.sh"].startswith("#!/bin/sh")


class TestEnsureFetcherScriptsCm:
    def test_creates_configmap_when_missing(self):
        from kubernetes.client.exceptions import ApiException
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        _ensure_fetcher_scripts_cm(kube, "team1")
        kube.core_api.create_namespaced_config_map.assert_called_once()
        call_args = kube.core_api.create_namespaced_config_map.call_args
        assert call_args.kwargs["namespace"] == "team1" or call_args.args[0] == "team1"

    def test_replaces_configmap_when_exists(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = MagicMock()
        _ensure_fetcher_scripts_cm(kube, "team1")
        kube.core_api.replace_namespaced_config_map.assert_called_once()


class TestGetExternalSkillData:
    def test_returns_empty_when_no_external_skills(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = _make_local_cm("local-skill")
        init_containers, volumes, mounts, paths = _get_external_skill_data(
            kube, "team1", ["local-skill"]
        )
        assert init_containers == []
        assert volumes == []
        assert mounts == []
        assert paths == []

    def test_returns_init_container_for_external_skill(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.side_effect = lambda name, namespace: (
            _make_ext_cm(name) if name == "my-skill" else _make_local_cm(name)
        )
        init_containers, volumes, mounts, paths = _get_external_skill_data(
            kube, "team1", ["my-skill"]
        )
        assert len(init_containers) == 1
        assert init_containers[0]["image"] == SKILL_FETCHER_IMAGE
        assert len(volumes) >= 1  # at least 1 emptyDir + fetcher scripts vol
        assert len(mounts) >= 1
        assert len(paths) == 1
        assert paths[0] == f"{AGENT_SKILLS_MOUNT_ROOT}/my-skill"

    def test_fetcher_scripts_volume_shared_across_multiple_external_skills(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = _make_ext_cm("dummy")
        init_containers, volumes, mounts, paths = _get_external_skill_data(
            kube, "team1", ["skill-a", "skill-b"]
        )
        # Should have exactly 1 fetcher-scripts volume (shared), plus 2 emptyDir volumes
        scripts_vols = [v for v in volumes if v.get("name") == "fetcher-scripts-vol"]
        assert len(scripts_vols) == 1
        assert len(init_containers) == 2
```

- [ ] **Step 4.2: Run tests to confirm they fail**

```bash
cd rossoctl/backend
uv run pytest tests/test_agents_external_skills.py -v 2>&1 | tail -15
# Expected: ImportError — functions not yet defined
```

- [ ] **Step 4.3: Add new helpers to agents.py**

Add these functions to `rossoctl/backend/app/routers/agents.py` **right after** the existing `_get_linked_skill_mounts` function (currently ending around line 2512):

First, update the imports at the top of agents.py to include new constants:

```python
from app.core.constants import (
    # ... existing imports ...,
    SKILL_SOURCE_LABEL,
    SKILL_SOURCE_EXTERNAL,
    SKILL_REGISTRY_TYPE_LABEL,
    SKILL_REGISTRY_URL_ANNOTATION,
    SKILL_REGISTRY_SKILL_NAME_ANNOTATION,
    SKILL_REGISTRY_SKILL_VERSION_ANNOTATION,
    SKILL_FETCHER_SCRIPTS_CM,
    SKILL_FETCHER_IMAGE,
)
```

Then add after `_get_linked_skill_mounts`:

```python
def _is_skill_external(kube: "KubernetesService", namespace: str, skill_name: str) -> bool:
    """Return True if the named skill ConfigMap is an external registry reference."""
    try:
        cm = kube.core_api.read_namespaced_config_map(
            name=_sanitize_k8s_name(skill_name), namespace=namespace
        )
        labels = cm.metadata.labels or {}
        return labels.get(SKILL_SOURCE_LABEL) == SKILL_SOURCE_EXTERNAL
    except ApiException:
        return False


_SKILLBERRY_SH = """\
#!/bin/sh
set -e

SKILL_VERSION="${SKILL_VERSION:-latest}"
URL="${REGISTRY_URL}/api/v1/skills/${SKILL_NAME}/${SKILL_VERSION}/archive"

echo "Fetching ${SKILL_NAME}@${SKILL_VERSION} from ${URL}"

RETRIES=3
DELAY=2
for i in $(seq 1 $RETRIES); do
    if curl -fsSL -o /tmp/skill.tar.gz "${URL}"; then
        break
    fi
    if [ "$i" -eq "$RETRIES" ]; then
        echo "FATAL: fetch failed after ${RETRIES} attempts"
        exit 1
    fi
    echo "Attempt ${i} failed; retrying in ${DELAY}s..."
    sleep $DELAY
done

mkdir -p "${TARGET_DIR}"
tar -xzf /tmp/skill.tar.gz -C "${TARGET_DIR}"
echo "OK: ${SKILL_NAME}@${SKILL_VERSION} -> ${TARGET_DIR}"
"""

_GENERIC_SH = """\
#!/bin/sh
set -e

echo "Fetching skill from ${REGISTRY_URL}"

RETRIES=3
DELAY=2
for i in $(seq 1 $RETRIES); do
    if curl -fsSL -o /tmp/skill.tar.gz "${REGISTRY_URL}"; then
        break
    fi
    if [ "$i" -eq "$RETRIES" ]; then
        echo "FATAL: fetch failed after ${RETRIES} attempts"
        exit 1
    fi
    echo "Attempt ${i} failed; retrying in ${DELAY}s..."
    sleep $DELAY
done

mkdir -p "${TARGET_DIR}"
tar -xzf /tmp/skill.tar.gz -C "${TARGET_DIR}"
echo "OK: ${REGISTRY_URL} -> ${TARGET_DIR}"
"""


def _build_fetcher_scripts_data() -> Dict[str, str]:
    """Return ConfigMap data dict containing per-registry-type fetch scripts."""
    return {
        "skillberry.sh": _SKILLBERRY_SH,
        "generic.sh": _GENERIC_SH,
    }


def _ensure_fetcher_scripts_cm(kube: "KubernetesService", namespace: str) -> None:
    """Create or replace the rossoctl-skill-fetcher-scripts ConfigMap in namespace."""
    import kubernetes.client as k8s_client

    body = k8s_client.V1ConfigMap(
        metadata=k8s_client.V1ObjectMeta(
            name=SKILL_FETCHER_SCRIPTS_CM,
            namespace=namespace,
            labels={"app.kubernetes.io/managed-by": "rossoctl"},
        ),
        data=_build_fetcher_scripts_data(),
    )
    try:
        kube.core_api.read_namespaced_config_map(
            name=SKILL_FETCHER_SCRIPTS_CM, namespace=namespace
        )
        kube.core_api.replace_namespaced_config_map(
            name=SKILL_FETCHER_SCRIPTS_CM, namespace=namespace, body=body
        )
    except ApiException as e:
        if e.status == 404:
            kube.core_api.create_namespaced_config_map(namespace=namespace, body=body)
        else:
            raise


def _get_external_skill_data(
    kube: "KubernetesService",
    namespace: str,
    all_skills: List[str],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """Build init containers, volumes, and mounts for external-registry skills.

    Returns (init_containers, volumes, main_volume_mounts, skill_paths).
    One fetcher-scripts-vol is shared across all init containers.
    """
    init_containers: List[Dict[str, Any]] = []
    volumes: List[Dict[str, Any]] = []
    main_mounts: List[Dict[str, Any]] = []
    skill_paths: List[str] = []
    fetcher_vol_added = False

    for index, skill_name in enumerate(all_skills):
        if not skill_name:
            continue
        if not _is_skill_external(kube, namespace, skill_name):
            continue

        try:
            cm = kube.core_api.read_namespaced_config_map(
                name=_sanitize_k8s_name(skill_name), namespace=namespace
            )
        except ApiException:
            continue

        cm_labels = cm.metadata.labels or {}
        cm_annotations = cm.metadata.annotations or {}
        registry_type = cm_labels.get(SKILL_REGISTRY_TYPE_LABEL, "generic")
        registry_url = cm_annotations.get(SKILL_REGISTRY_URL_ANNOTATION, "")
        registry_skill_name = cm_annotations.get(SKILL_REGISTRY_SKILL_NAME_ANNOTATION, skill_name)
        registry_skill_version = cm_annotations.get(SKILL_REGISTRY_SKILL_VERSION_ANNOTATION, "latest")

        cm_name = _sanitize_k8s_name(skill_name)
        emptydir_vol_name = f"skill-ext-{index}"
        mount_path = f"{AGENT_SKILLS_MOUNT_ROOT}/{cm_name}"

        # Shared fetcher-scripts volume (added once)
        if not fetcher_vol_added:
            volumes.append({
                "name": "fetcher-scripts-vol",
                "configMap": {"name": SKILL_FETCHER_SCRIPTS_CM},
            })
            fetcher_vol_added = True

        # Per-skill emptyDir volume
        volumes.append({"name": emptydir_vol_name, "emptyDir": {}})

        # Init container for this skill
        init_containers.append({
            "name": f"fetch-skill-{index}",
            "image": SKILL_FETCHER_IMAGE,
            "command": [
                "/bin/sh",
                "-c",
                (
                    f"SCRIPT=/fetcher-scripts/{registry_type}.sh; "
                    "[ -f \"$SCRIPT\" ] || SCRIPT=/fetcher-scripts/generic.sh; "
                    "/bin/sh \"$SCRIPT\""
                ),
            ],
            "env": [
                {"name": "REGISTRY_TYPE", "value": registry_type},
                {"name": "REGISTRY_URL", "value": registry_url},
                {"name": "SKILL_NAME", "value": registry_skill_name},
                {"name": "SKILL_VERSION", "value": registry_skill_version},
                {"name": "TARGET_DIR", "value": mount_path},
            ],
            "volumeMounts": [
                {"name": emptydir_vol_name, "mountPath": mount_path},
                {"name": "fetcher-scripts-vol", "mountPath": "/fetcher-scripts", "readOnly": True},
            ],
        })

        # Main container mount (readOnly)
        main_mounts.append({
            "name": emptydir_vol_name,
            "mountPath": mount_path,
            "readOnly": True,
        })
        skill_paths.append(mount_path)

    return init_containers, volumes, main_mounts, skill_paths
```

- [ ] **Step 4.4: Modify `_get_linked_skill_mounts` to accept `skills_override`**

In the existing `_get_linked_skill_mounts` function (line ~2475), change the signature and the first line that reads `request.skills`:

**Before (line 2477):**
```python
def _get_linked_skill_mounts(
    request: "CreateAgentRequest",
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    """Build volume and mount definitions for linked skill ConfigMaps."""
    if not request.skills:
        return [], [], None
    ...
    for index, skill_name in enumerate(request.skills):
```

**After:**
```python
def _get_linked_skill_mounts(
    request: "CreateAgentRequest",
    skills_override: Optional[List[str]] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    """Build volume and mount definitions for linked skill ConfigMaps (local only)."""
    skills = skills_override if skills_override is not None else (request.skills or [])
    if not skills:
        return [], [], None
    ...
    for index, skill_name in enumerate(skills):
```

- [ ] **Step 4.5: Modify `_build_env_vars` to accept external skill paths**

In the existing `_build_env_vars` function (line ~2515), change signature and skill_folders logic:

**Before:**
```python
def _build_env_vars(request: "CreateAgentRequest") -> List[dict]:
    ...
    _, _, skill_folders = _get_linked_skill_mounts(request)
    if skill_folders:
        env_vars.append({"name": "SKILL_FOLDERS", "value": skill_folders})
```

**After:**
```python
def _build_env_vars(
    request: "CreateAgentRequest",
    local_skills: Optional[List[str]] = None,
    ext_skill_paths: Optional[List[str]] = None,
) -> List[dict]:
    ...
    _, _, local_folders = _get_linked_skill_mounts(request, skills_override=local_skills)
    all_paths = [p for p in ([local_folders] if local_folders else []) + (ext_skill_paths or []) if p]
    if all_paths:
        env_vars.append({"name": "SKILL_FOLDERS", "value": ",".join(all_paths)})
```

- [ ] **Step 4.6: Modify the 4 manifest builder functions to accept external skill data**

Each of the 4 builders (`_build_deployment_manifest`, `_build_statefulset_manifest`, `_build_job_manifest`, `_build_sandbox_manifest`) currently starts with:

```python
env_vars = _build_env_vars(request)
skill_volumes, skill_volume_mounts, _ = _get_linked_skill_mounts(request)
```

Change each to accept and use external skill parameters. Example for `_build_deployment_manifest`:

**Add to function signature:**
```python
def _build_deployment_manifest(
    request: "CreateAgentRequest",
    image: str,
    shipwright_build_name: Optional[str] = None,
    local_skills: Optional[List[str]] = None,
    ext_init_containers: Optional[List[Dict[str, Any]]] = None,
    ext_volumes: Optional[List[Dict[str, Any]]] = None,
    ext_volume_mounts: Optional[List[Dict[str, Any]]] = None,
    ext_skill_paths: Optional[List[str]] = None,
) -> dict:
```

**Change the first two lines:**
```python
    ext_init_containers = ext_init_containers or []
    ext_volumes = ext_volumes or []
    ext_volume_mounts = ext_volume_mounts or []
    ext_skill_paths = ext_skill_paths or []
    env_vars = _build_env_vars(request, local_skills=local_skills, ext_skill_paths=ext_skill_paths)
    skill_volumes, skill_volume_mounts, _ = _get_linked_skill_mounts(request, skills_override=local_skills)
```

**Add `initContainers` to the pod spec** (inside `manifest["spec"]["template"]["spec"]`), after the existing `"containers"` key:

```python
                    "volumes": [
                        {"name": "cache", "emptyDir": {}},
                        {"name": "marvin", "emptyDir": {}},
                        {"name": "shared-data", "emptyDir": {}},
                        *skill_volumes,
                        *ext_volumes,
                    ],
```

And in `volumeMounts`:
```python
                            "volumeMounts": [
                                {"name": "cache", "mountPath": "/app/.cache"},
                                {"name": "marvin", "mountPath": "/.marvin"},
                                {"name": "shared-data", "mountPath": "/shared"},
                                *skill_volume_mounts,
                                *ext_volume_mounts,
                            ],
```

And after `"containers"` list:
```python
                    *( {"initContainers": ext_init_containers} if ext_init_containers else {} ),
```

Wait — you can't use `*dict` spreading in a dict literal that way. Use conditional assignment instead:

```python
                pod_spec = {
                    "serviceAccountName": request.name,
                    "containers": [...],
                    "volumes": [...skill_volumes, *ext_volumes, ...],
                }
                if ext_init_containers:
                    pod_spec["initContainers"] = ext_init_containers
                manifest["spec"]["template"]["spec"] = pod_spec
```

Apply the same changes to `_build_statefulset_manifest`, `_build_job_manifest`, and `_build_sandbox_manifest`.

- [ ] **Step 4.7: Modify `create_agent` to compute and pass external skill data**

In the `create_agent` function (line ~3214), find the existing feature flag check around line 3238:

```python
    # Feature flag: reject skill linking if feature is disabled
    if request.skills and not settings.rossoctl_feature_flag_skills:
        raise HTTPException(...)
```

After this block, add:

```python
    # Compute external skill data (init containers + volumes) when feature is enabled
    local_skills: Optional[List[str]] = None
    ext_init_containers: List[Dict[str, Any]] = []
    ext_volumes: List[Dict[str, Any]] = []
    ext_volume_mounts: List[Dict[str, Any]] = []
    ext_skill_paths: List[str] = []

    if request.skills and settings.rossoctl_feature_flag_external_skills:
        _ensure_fetcher_scripts_cm(kube, request.namespace)
        ext_init_containers, ext_volumes, ext_volume_mounts, ext_skill_paths = (
            _get_external_skill_data(kube, request.namespace, request.skills)
        )
        # Local skills = those not identified as external
        local_skills = [
            s for s in request.skills
            if s and not _is_skill_external(kube, request.namespace, s)
        ]
```

Then pass these to each manifest builder call at lines 3303, 3315, 3327, 3337:

```python
                workload_manifest = _build_deployment_manifest(
                    request=request,
                    image=request.containerImage,
                    local_skills=local_skills,
                    ext_init_containers=ext_init_containers,
                    ext_volumes=ext_volumes,
                    ext_volume_mounts=ext_volume_mounts,
                    ext_skill_paths=ext_skill_paths,
                )
```

Apply the same for all 4 workload types. Also apply to the second set of manifest builder calls around line 3858+.

- [ ] **Step 4.8: Run tests to confirm new helpers pass**

```bash
cd rossoctl/backend
uv run pytest tests/test_agents_external_skills.py -v 2>&1 | tail -20
# Expected: all tests pass
```

- [ ] **Step 4.9: Run full test suite**

```bash
cd rossoctl/backend
uv run pytest tests/ -v 2>&1 | tail -30
# Expected: all tests pass
```

- [ ] **Step 4.10: Commit**

```bash
git add rossoctl/backend/app/routers/agents.py \
        rossoctl/backend/tests/test_agents_external_skills.py
git commit -s -m "feat(agents): inject init containers for external registry skills

Adds _is_skill_external, _ensure_fetcher_scripts_cm,
_get_external_skill_data, and _build_fetcher_scripts_data helpers.
Modifies _get_linked_skill_mounts and _build_env_vars to accept
local_skills/ext_skill_paths overrides. Updates all 4 manifest
builders and create_agent to split local vs. external skills and
inject alpine:3 init containers for external skill fetching.
Refs rossoctl/rossoctl#1691.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 5: Frontend — types and API service

**Files:**
- Modify: `rossoctl/ui-v2/src/types/index.ts` (around line 411)
- Modify: `rossoctl/ui-v2/src/services/api.ts` (after line 1528)

- [ ] **Step 5.1: Update Skill type and add new types in types/index.ts**

In `rossoctl/ui-v2/src/types/index.ts`, after the `SkillLabels` interface (around line 407) add:

```typescript
export interface ExternalSkillInfo {
  registryType: string;
  registryUrl: string;
  registrySkillName: string;
  registrySkillVersion: string;
}
```

Then update the `Skill` interface (currently lines 411-417) to add two optional fields:

```typescript
export interface Skill {
  name: string;
  namespace: string;
  resourceName: string;
  description: string;
  status: string;
  labels: SkillLabels;
  createdAt?: string;
  origin?: string;
  usageCount: number;
  source?: 'local' | 'external';        // NEW
  externalInfo?: ExternalSkillInfo;      // NEW
}
```

After the `CreateSkillRequest` interface (around line 428) add:

```typescript
export interface CreateExternalSkillRequest {
  name: string;
  namespace: string;
  description?: string;
  category?: string;
  registryType: string;
  registryUrl: string;
  registrySkillName: string;
  registrySkillVersion?: string;
  origin?: string;
}
```

- [ ] **Step 5.2: Add `externalSkills` to useFeatureFlags.ts**

In `rossoctl/ui-v2/src/hooks/useFeatureFlags.ts`, add to the `FeatureFlags` interface (after `admin: boolean`):

```typescript
  /** External skill registry references */
  externalSkills: boolean;
```

Add to `DEFAULT_FLAGS` (after `admin: false`):

```typescript
  externalSkills: false,
```

Add to the `validated` object in the `useEffect` (after `admin: data.admin === true`):

```typescript
          externalSkills: data.externalSkills === true,
```

- [ ] **Step 5.3: Add createExternal to skillService in api.ts**

In `rossoctl/ui-v2/src/services/api.ts`, inside `skillService` (after the `delete` method, before the closing `}`), add:

```typescript
  async createExternal(data: CreateExternalSkillRequest): Promise<CreateSkillResponse> {
    return apiFetch('/skills/external', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
```

Update the import of types in api.ts to include `CreateExternalSkillRequest` (find where `CreateSkillRequest` is imported from `@/types` and add `CreateExternalSkillRequest` alongside it).

- [ ] **Step 5.4: TypeScript compile check**

```bash
cd rossoctl/ui-v2
npx tsc --noEmit 2>&1 | head -30
# Expected: no errors
```

- [ ] **Step 5.5: Commit**

```bash
git add rossoctl/ui-v2/src/types/index.ts \
        rossoctl/ui-v2/src/services/api.ts \
        rossoctl/ui-v2/src/hooks/useFeatureFlags.ts
git commit -s -m "feat(ui): add ExternalSkillInfo type and skillService.createExternal

Extends Skill interface with optional source/externalInfo fields.
Adds CreateExternalSkillRequest type and skillService.createExternal()
API method. Refs rossoctl/rossoctl#1691.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 6: Frontend — SkillCatalogPage badge

**Files:**
- Modify: `rossoctl/ui-v2/src/pages/SkillCatalogPage.tsx`

- [ ] **Step 6.1: Add External badge to skill list rows**

`Label` is already imported in `SkillCatalogPage.tsx` (line 21). Find the table row where skill name is rendered (look for `<Td>` containing `skill.name` or a link to skill detail). Add the badge inline:

```tsx
<Td dataLabel="Name">
  <Button
    variant="link"
    isInline
    onClick={() => navigate(`/skills/${skill.namespace}/${skill.resourceName}`)}
  >
    {skill.name}
  </Button>
  {skill.source === 'external' && (
    <Label
      color="blue"
      isCompact
      style={{ marginLeft: '0.5rem' }}
    >
      External
    </Label>
  )}
</Td>
```

Read the file to find the exact surrounding JSX structure before making this change.

- [ ] **Step 6.2: TypeScript compile check**

```bash
cd rossoctl/ui-v2
npx tsc --noEmit 2>&1 | head -30
# Expected: no errors
```

- [ ] **Step 6.3: Commit**

```bash
git add rossoctl/ui-v2/src/pages/SkillCatalogPage.tsx
git commit -s -m "feat(ui): show External badge in skill catalog for registry skills

External skills (source=external) display a blue 'External' badge
next to their name in the skill catalog table.
Refs rossoctl/rossoctl#1691.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 7: Frontend — SkillDetailPage registry info card

**Files:**
- Modify: `rossoctl/ui-v2/src/pages/SkillDetailPage.tsx`

- [ ] **Step 7.1: Add registry info card for external skills**

Read `SkillDetailPage.tsx` in full first to understand where `SkillFileTree` is rendered. Then add a conditional block. After the skill metadata section, before the `SkillFileTree`:

```tsx
{skill.source === 'external' && skill.externalInfo ? (
  <Card>
    <CardTitle>Registry Information</CardTitle>
    <CardBody>
      <DescriptionList>
        <DescriptionListGroup>
          <DescriptionListTerm>Registry Type</DescriptionListTerm>
          <DescriptionListDescription>
            {skill.externalInfo.registryType}
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Registry URL</DescriptionListTerm>
          <DescriptionListDescription>
            <a href={skill.externalInfo.registryUrl} target="_blank" rel="noreferrer">
              {skill.externalInfo.registryUrl}
            </a>
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Skill Name</DescriptionListTerm>
          <DescriptionListDescription>
            {skill.externalInfo.registrySkillName}
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Version</DescriptionListTerm>
          <DescriptionListDescription>
            {skill.externalInfo.registrySkillVersion}
          </DescriptionListDescription>
        </DescriptionListGroup>
        {skill.origin && (
          <DescriptionListGroup>
            <DescriptionListTerm>Registry Link</DescriptionListTerm>
            <DescriptionListDescription>
              <a href={skill.origin} target="_blank" rel="noreferrer">
                View in Registry
              </a>
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
      </DescriptionList>
    </CardBody>
  </Card>
) : (
  <SkillFileTree skill={skill} />
)}
```

All PatternFly components used (`Card`, `CardTitle`, `CardBody`, `DescriptionList`, `DescriptionListGroup`, `DescriptionListTerm`, `DescriptionListDescription`) are already imported at the top of the file.

- [ ] **Step 7.2: TypeScript compile check**

```bash
cd rossoctl/ui-v2
npx tsc --noEmit 2>&1 | head -30
# Expected: no errors
```

- [ ] **Step 7.3: Commit**

```bash
git add rossoctl/ui-v2/src/pages/SkillDetailPage.tsx
git commit -s -m "feat(ui): show registry info card on external skill detail page

For external skills, replaces the file tree with a Registry Information
card showing type, URL, skill name, version, and a link to the registry.
Refs rossoctl/rossoctl#1691.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 8: Frontend — ImportSkillPage "From Registry" tab

**Files:**
- Modify: `rossoctl/ui-v2/src/pages/ImportSkillPage.tsx`

- [ ] **Step 8.1: Read ImportSkillPage.tsx in full**

Read the full file to understand the current form structure before modifying it.

```bash
wc -l rossoctl/ui-v2/src/pages/ImportSkillPage.tsx
# Then read the full file
```

- [ ] **Step 8.2: Add Tabs and registry form**

**a) Add new imports** (PatternFly `Tabs`, `Tab`, `TabTitleText`; and `Select`, `SelectOption`, `SelectList`, `MenuToggle` for the registry type dropdown):

```tsx
import {
  // ... existing imports ...,
  Tabs,
  Tab,
  TabTitleText,
  Select,
  SelectOption,
  SelectList,
  MenuToggle,
} from '@patternfly/react-core';
```

**b) Add `useFeatureFlags` import and tab state** (after existing imports and `useState` declarations):

Add import at top of file:
```tsx
import { useFeatureFlags } from '@/hooks/useFeatureFlags';
```

Inside the component:
```tsx
  const features = useFeatureFlags();
  const [activeTab, setActiveTab] = useState<'upload' | 'registry'>('upload');

  // Registry form state
  const [registryType, setRegistryType] = useState('skillberry');
  const [registryTypeOpen, setRegistryTypeOpen] = useState(false);
  const [registryUrl, setRegistryUrl] = useState('');
  const [registrySkillName, setRegistrySkillName] = useState('');
  const [registrySkillVersion, setRegistrySkillVersion] = useState('');
  const [registryName, setRegistryName] = useState('');
  const [registryDescription, setRegistryDescription] = useState('');
  const [registryCategory, setRegistryCategory] = useState('');
```

Import `apiFetch` and `FeatureFlagsResponse` at the top if not already present.

**c) Add registry submit mutation** (after the existing `useMutation` for local skill):

```tsx
  const registryMutation = useMutation({
    mutationFn: () =>
      skillService.createExternal({
        name: registryName,
        namespace,
        description: registryDescription,
        category: registryCategory,
        registryType,
        registryUrl,
        registrySkillName,
        registrySkillVersion: registrySkillVersion || 'latest',
      }),
    onSuccess: () => navigate('/skills'),
  });
```

**d) Wrap the existing form in a `<Tabs>` component:**

```tsx
  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Import Skill</Title>
      </PageSection>
      <PageSection>
        <Tabs
          activeKey={activeTab}
          onSelect={(_e, key) => setActiveTab(key as 'upload' | 'registry')}
        >
          <Tab eventKey="upload" title={<TabTitleText>Upload Files</TabTitleText>}>
            {/* entire existing form JSX goes here unchanged */}
          </Tab>
          {features?.externalSkills && (
            <Tab eventKey="registry" title={<TabTitleText>From Registry</TabTitleText>}>
              <Card>
                <CardBody>
                  <Form>
                    <FormGroup label="Registry Type" isRequired fieldId="registryType">
                      <Select
                        isOpen={registryTypeOpen}
                        onOpenChange={setRegistryTypeOpen}
                        selected={registryType}
                        onSelect={(_e, val) => { setRegistryType(val as string); setRegistryTypeOpen(false); }}
                        toggle={(ref) => (
                          <MenuToggle ref={ref} onClick={() => setRegistryTypeOpen(!registryTypeOpen)}>
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
                    <FormGroup label="Registry URL" isRequired fieldId="registryUrl">
                      <TextInput
                        id="registryUrl"
                        value={registryUrl}
                        onChange={(_e, v) => setRegistryUrl(v)}
                        placeholder="https://skillberry.example.com"
                      />
                    </FormGroup>
                    <FormGroup label="Skill Name in Registry" isRequired fieldId="registrySkillName">
                      <TextInput
                        id="registrySkillName"
                        value={registrySkillName}
                        onChange={(_e, v) => setRegistrySkillName(v)}
                        placeholder="code-review"
                      />
                    </FormGroup>
                    <FormGroup label="Version" fieldId="registrySkillVersion">
                      <TextInput
                        id="registrySkillVersion"
                        value={registrySkillVersion}
                        onChange={(_e, v) => setRegistrySkillVersion(v)}
                        placeholder="latest"
                      />
                    </FormGroup>
                    <FormGroup label="Display Name" isRequired fieldId="registryName">
                      <TextInput
                        id="registryName"
                        value={registryName}
                        onChange={(_e, v) => setRegistryName(v)}
                      />
                    </FormGroup>
                    <FormGroup label="Description" fieldId="registryDescription">
                      <TextArea
                        id="registryDescription"
                        value={registryDescription}
                        onChange={(_e, v) => setRegistryDescription(v)}
                        rows={3}
                      />
                    </FormGroup>
                    <FormGroup label="Category" fieldId="registryCategory">
                      <TextInput
                        id="registryCategory"
                        value={registryCategory}
                        onChange={(_e, v) => setRegistryCategory(v)}
                      />
                    </FormGroup>
                    {registryMutation.isError && (
                      <Alert variant="danger" title="Error creating external skill reference">
                        {registryMutation.error instanceof Error
                          ? registryMutation.error.message
                          : 'An error occurred'}
                      </Alert>
                    )}
                    <ActionGroup>
                      <Button
                        variant="primary"
                        onClick={() => registryMutation.mutate()}
                        isDisabled={!registryName || !registryUrl || !registrySkillName || registryMutation.isPending}
                        isLoading={registryMutation.isPending}
                      >
                        Register External Skill
                      </Button>
                      <Button variant="link" onClick={() => navigate('/skills')}>
                        Cancel
                      </Button>
                    </ActionGroup>
                  </Form>
                </CardBody>
              </Card>
            </Tab>
          )}
        </Tabs>
      </PageSection>
    </>
  );
```

- [ ] **Step 8.3: TypeScript compile check**

```bash
cd rossoctl/ui-v2
npx tsc --noEmit 2>&1 | head -30
# Expected: no errors (fix any type errors reported)
```

- [ ] **Step 8.4: Commit**

```bash
git add rossoctl/ui-v2/src/pages/ImportSkillPage.tsx
git commit -s -m "feat(ui): add From Registry tab to ImportSkillPage

Adds a 'From Registry' tab (shown when externalSkills feature flag
is enabled) with a form for registryType, URL, skill name, version,
display name, description, and category. Submits to
skillService.createExternal(). Refs rossoctl/rossoctl#1691.

Assisted-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 9: Lint and final push

- [ ] **Step 9.1: Run Python linter**

```bash
cd rossoctl/backend
uv run pre-commit run --all-files 2>&1 | tail -30
# Fix any reported issues, then re-run until clean
```

- [ ] **Step 9.2: Run frontend lint**

```bash
cd rossoctl/ui-v2
npm run lint 2>&1 | tail -30
# Fix any ESLint issues reported
```

- [ ] **Step 9.3: Run backend tests one final time**

```bash
cd rossoctl/backend
uv run pytest tests/ -v 2>&1 | tail -30
# Expected: all tests pass
```

- [ ] **Step 9.4: Push to eranra remote and create PR**

```bash
git push eranra feat/external-skill-registries

gh pr create \
  --title "feat(skills): external skill registry references (#1691)" \
  --base main \
  --head eranra:feat/external-skill-registries \
  --repo rossoctl/rossoctl \
  --body "$(cat <<'EOF'
## Summary

- Adds external skill registry references: lightweight ConfigMaps (`rossoctl.io/source=external`) that point to a remote registry instead of embedding file content
- At agent pod startup, an `alpine:3` init container fetches the skill archive from the registry and mounts it at the same path as local skills — transparent to the agent
- Registry-specific fetch scripts live in a `rossoctl-skill-fetcher-scripts` ConfigMap (created lazily in each team namespace); adding a new registry type requires only a new shell script
- Gated behind `rossoctl_feature_flag_external_skills` (default: `False`)

## Changes

- `config.py` — new `rossoctl_feature_flag_external_skills` flag
- `constants.py` — 8 new skill registry constants
- `config.py router` — exposes `externalSkills` in `/config/features`
- `skills.py` — `ExternalSkillInfo` model, `_is_external()` helpers, `POST /skills/external` endpoint
- `agents.py` — `_ensure_fetcher_scripts_cm()`, `_get_external_skill_data()`, init container injection in all 4 manifest builders
- UI — `External` badge in catalog, registry info card in detail, "From Registry" tab in import page

## Testing

- Unit tests for all new backend helpers in `test_skills.py` and `test_agents_external_skills.py`
- TypeScript compiles without errors

## Issue

Closes rossoctl/rossoctl#1691

Assisted-By: Claude Code
EOF
)"
```
