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
        assert (
            patch_body["metadata"]["annotations"][SKILL_REGISTRY_SKILL_VERSION_ANNOTATION] == "2.0"
        )

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
        cm.data = {
            "enabled": "true",
            "registry-url": "http://reg",
            "registry-type": "skillberry",
            "sync-interval": "30",
        }
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
        cm.data = {
            "enabled": "true",
            "registry-url": "http://reg",
            "registry-type": "skillberry",
            "sync-interval": "45",
        }
        kube.core_api.read_namespaced_config_map.return_value = cm
        kube.list_enabled_namespaces.return_value = ["team1"]
        kube.core_api.list_namespaced_config_map.return_value = MagicMock(items=[])
        with patch(
            "app.services.skill_autosync._fetch_registry_skills",
            new=AsyncMock(return_value=[]),
        ):
            interval = await sync_skills_once(kube)
        assert interval == 45
