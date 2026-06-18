# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for skill management utility functions.
"""

import pytest
from app.routers.skills import _sanitize_k8s_name


class TestSanitizeK8sName:
    """Tests for _sanitize_k8s_name function."""

    def test_basic_alphanumeric_and_case(self):
        """Test that alphanumeric names are lowercased."""
        assert _sanitize_k8s_name("MySkill123") == "myskill123"
        assert _sanitize_k8s_name("Skill-V2.0-Beta") == "skill-v2.0-beta"

    def test_special_chars_conversion(self):
        """Test that spaces and special characters are converted to dashes."""
        assert _sanitize_k8s_name("My Skill Name") == "my-skill-name"
        assert _sanitize_k8s_name("skill@#$%name") == "skill----name"

    def test_valid_chars_preserved(self):
        """Test that dots and hyphens are preserved (valid in k8s names)."""
        assert _sanitize_k8s_name("skill.v1.0") == "skill.v1.0"
        assert _sanitize_k8s_name("my-skill-name") == "my-skill-name"

    def test_leading_trailing_stripped(self):
        """Test that leading/trailing dots and dashes are stripped."""
        assert _sanitize_k8s_name("--skill.name--") == "skill.name"
        assert _sanitize_k8s_name("..skill..") == "skill"
        assert _sanitize_k8s_name("-.skill.-") == "skill"

    def test_empty_and_invalid_fallback(self):
        """Test that empty or all-invalid strings return 'skill' as fallback."""
        assert _sanitize_k8s_name("") == "skill"
        assert _sanitize_k8s_name("---") == "skill"
        assert _sanitize_k8s_name("...") == "skill"


# Made with Bob

from app.routers.skills import (
    _is_external,
    _configmap_to_external_skill_info,
    _configmap_to_skill,
)
from app.core.constants import (
    SKILL_SOURCE_LABEL,
    SKILL_SOURCE_EXTERNAL,
    SKILL_REGISTRY_TYPE_LABEL,
    SKILL_REGISTRY_URL_ANNOTATION,
    SKILL_REGISTRY_SKILL_NAME_ANNOTATION,
    SKILL_REGISTRY_SKILL_VERSION_ANNOTATION,
    SKILL_TYPE_LABEL,
    SKILL_TYPE_VALUE,
    SKILL_DISPLAY_NAME_ANNOTATION,
    SKILL_DESCRIPTION_ANNOTATION,
)
from unittest.mock import MagicMock
import datetime


def _make_cm(labels=None, annotations=None, data=None, name="test-skill"):
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


class TestCreateExternalSkill:
    """Tests for POST /skills/external endpoint."""

    def _make_app(self):
        from fastapi import FastAPI
        from app.routers.skills import router

        app = FastAPI()
        app.include_router(router)
        return app

    def test_create_external_skill_success(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch, MagicMock

        mock_kube = MagicMock()
        mock_kube.core_api.create_namespaced_config_map.return_value = MagicMock()

        public_addr = [(None, None, None, None, ("93.184.216.34", 0))]
        with (
            patch("app.routers.skills.get_kubernetes_service", return_value=mock_kube),
            patch("app.routers.skills.settings") as mock_settings,
            patch("app.routers.skills.socket.getaddrinfo", return_value=public_addr),
        ):
            mock_settings.kagenti_feature_flag_external_skills = True
            mock_settings.kagenti_feature_flag_skills = True
            client = TestClient(self._make_app())
            resp = client.post(
                "/skills/external",
                json={
                    "name": "Code Review",
                    "namespace": "team1",
                    "description": "Reviews code quality",
                    "category": "development",
                    "registryType": "skillberry",
                    "registryUrl": "https://skillberry.example.com",
                    "registrySkillName": "code-review",
                    "registrySkillVersion": "1.2.0",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["namespace"] == "team1"
        mock_kube.core_api.create_namespaced_config_map.assert_called_once()

    def test_create_external_skill_404_when_flag_off(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch, MagicMock

        mock_kube = MagicMock()

        with (
            patch("app.routers.skills.get_kubernetes_service", return_value=mock_kube),
            patch("app.routers.skills.settings") as mock_settings,
        ):
            mock_settings.kagenti_feature_flag_external_skills = False
            client = TestClient(self._make_app())
            resp = client.post(
                "/skills/external",
                json={
                    "name": "test",
                    "namespace": "team1",
                    "registryType": "skillberry",
                    "registryUrl": "https://example.com",
                    "registrySkillName": "test",
                },
            )
        assert resp.status_code == 404
