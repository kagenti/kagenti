# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0
"""Tests for external skill mount helpers in agents.py."""

from unittest.mock import MagicMock
from kubernetes.client.exceptions import ApiException
from app.routers.agents import (
    _is_skill_external,
    _build_fetcher_scripts_data,
    _ensure_fetcher_scripts_cm,
    _get_external_skill_data,
)
from app.core.constants import (
    SKILL_SOURCE_LABEL,
    SKILL_SOURCE_EXTERNAL,
    SKILL_TYPE_LABEL,
    SKILL_TYPE_VALUE,
    SKILL_REGISTRY_TYPE_LABEL,
    SKILL_REGISTRY_URL_ANNOTATION,
    SKILL_REGISTRY_SKILL_NAME_ANNOTATION,
    SKILL_REGISTRY_SKILL_VERSION_ANNOTATION,
    SKILL_FETCHER_SCRIPTS_CM,
    SKILL_FETCHER_IMAGE,
    AGENT_SKILLS_MOUNT_ROOT,
)


def _make_ext_cm(
    name="my-skill",
    registry_type="skillberry",
    registry_url="https://example.com",
    skill_name="my-skill",
    skill_version="1.0.0",
):
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


def _make_local_cm(name="local-skill"):
    cm = MagicMock()
    cm.metadata.name = name
    cm.metadata.labels = {SKILL_TYPE_LABEL: SKILL_TYPE_VALUE}
    cm.metadata.annotations = {}
    cm.data = {"SKILL.md": "# content"}
    return cm


class TestIsSkillExternal:
    def test_returns_true_for_external_configmap(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = _make_ext_cm()
        assert _is_skill_external(kube, "team1", "my-skill") is True

    def test_returns_false_for_local_configmap(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = _make_local_cm()
        assert _is_skill_external(kube, "team1", "my-skill") is False

    def test_returns_false_when_configmap_not_found(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        assert _is_skill_external(kube, "team1", "missing-skill") is False


class TestBuildFetcherScriptsData:
    def test_returns_skillberry_and_generic_scripts(self):
        data = _build_fetcher_scripts_data()
        assert "skillberry.sh" in data
        assert "generic.sh" in data

    def test_scripts_contain_required_env_vars(self):
        data = _build_fetcher_scripts_data()
        assert "REGISTRY_URL" in data["skillberry.sh"]
        assert "TARGET_DIR" in data["skillberry.sh"]
        assert "SKILL_NAME" in data["skillberry.sh"]
        assert "REGISTRY_URL" in data["generic.sh"]
        assert "TARGET_DIR" in data["generic.sh"]

    def test_scripts_start_with_shebang(self):
        data = _build_fetcher_scripts_data()
        assert data["skillberry.sh"].startswith("#!/bin/sh")
        assert data["generic.sh"].startswith("#!/bin/sh")


class TestEnsureFetcherScriptsCm:
    def test_creates_configmap_when_missing(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.side_effect = ApiException(status=404)
        _ensure_fetcher_scripts_cm(kube, "team1")
        kube.core_api.create_namespaced_config_map.assert_called_once()

    def test_replaces_configmap_when_exists(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = MagicMock()
        _ensure_fetcher_scripts_cm(kube, "team1")
        kube.core_api.replace_namespaced_config_map.assert_called_once()
        kube.core_api.create_namespaced_config_map.assert_not_called()


class TestGetExternalSkillData:
    def test_returns_empty_for_all_local_skills(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = _make_local_cm()
        init_cs, vols, mounts, paths = _get_external_skill_data(kube, "team1", ["local"])
        assert init_cs == []
        assert vols == []
        assert mounts == []
        assert paths == []

    def test_returns_init_container_for_external_skill(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = _make_ext_cm()
        init_cs, vols, mounts, paths = _get_external_skill_data(kube, "team1", ["my-skill"])
        assert len(init_cs) == 1
        assert init_cs[0]["image"] == SKILL_FETCHER_IMAGE
        assert len(paths) == 1
        assert paths[0] == f"{AGENT_SKILLS_MOUNT_ROOT}/my-skill"

    def test_fetcher_scripts_volume_added_once_for_multiple_external_skills(self):
        kube = MagicMock()
        kube.core_api.read_namespaced_config_map.return_value = _make_ext_cm()
        init_cs, vols, mounts, paths = _get_external_skill_data(
            kube, "team1", ["skill-a", "skill-b"]
        )
        scripts_vols = [v for v in vols if v.get("name") == "fetcher-scripts-vol"]
        assert len(scripts_vols) == 1
        assert len(init_cs) == 2
        assert len(paths) == 2
