# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for LLM virtual key management API.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytest.importorskip("app.routers.llm_keys", reason="llm_keys module not available")

from app.routers.llm_keys import (
    _get_team_id,
    _ensure_team,
    _create_virtual_key,
    _master_headers,
    KeyCreateRequest,
    TeamCreateRequest,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def set_master_key(monkeypatch):
    """Set LITELLM_MASTER_KEY for all tests."""
    monkeypatch.setattr("app.routers.llm_keys.LITELLM_MASTER_KEY", "sk-test-master")
    monkeypatch.setattr("app.routers.llm_keys.LITELLM_BASE_URL", "http://litellm-test:4000")


# ---------------------------------------------------------------------------
# _master_headers
# ---------------------------------------------------------------------------


class TestMasterHeaders:
    def test_returns_auth_header(self):
        headers = _master_headers()
        assert headers["Authorization"] == "Bearer sk-test-master"
        assert headers["Content-Type"] == "application/json"

    def test_raises_503_when_no_key(self, monkeypatch):
        monkeypatch.setattr("app.routers.llm_keys.LITELLM_MASTER_KEY", "")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _master_headers()
        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# _get_team_id
# ---------------------------------------------------------------------------


class TestGetTeamId:
    @pytest.mark.asyncio
    async def test_finds_team_by_alias(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"team_alias": "team1", "team_id": "tid-123"},
            {"team_alias": "team2", "team_id": "tid-456"},
        ]

        with patch("app.routers.llm_keys.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await _get_team_id("team1")
            assert result == "tid-123"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"team_alias": "team2", "team_id": "tid-456"},
        ]

        with patch("app.routers.llm_keys.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await _get_team_id("team1")
            assert result is None

    @pytest.mark.asyncio
    async def test_handles_nested_response(self):
        """LiteLLM may return {"data": [...]} or a flat list."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"team_alias": "team1", "team_id": "tid-789"}]}

        with patch("app.routers.llm_keys.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await _get_team_id("team1")
            assert result == "tid-789"


# ---------------------------------------------------------------------------
# _ensure_team
# ---------------------------------------------------------------------------


class TestEnsureTeam:
    @pytest.mark.asyncio
    async def test_returns_existing_team(self):
        with patch("app.routers.llm_keys._get_team_id", return_value="tid-existing"):
            result = await _ensure_team("team1")
            assert result == "tid-existing"

    @pytest.mark.asyncio
    async def test_creates_new_team(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"team_id": "tid-new"}

        with patch("app.routers.llm_keys._get_team_id", return_value=None):
            with patch("app.routers.llm_keys.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.request = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value = mock_client

                result = await _ensure_team("team1", max_budget=200)
                assert result == "tid-new"

                # Verify the request was made correctly
                call_args = mock_client.request.call_args
                assert call_args[0][0] == "POST"
                assert "/team/new" in call_args[0][1]


# ---------------------------------------------------------------------------
# _create_virtual_key
# ---------------------------------------------------------------------------


class TestCreateVirtualKey:
    @pytest.mark.asyncio
    async def test_creates_key_with_team(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"token": "sk-virtual-abc123"}

        with patch("app.routers.llm_keys.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            key = await _create_virtual_key(
                team_id="tid-123",
                key_alias="my-agent",
                namespace="team1",
                max_budget=50.0,
                models=["llama-4-scout"],
            )
            assert key == "sk-virtual-abc123"

            # Verify models passed in request
            call_args = mock_client.request.call_args
            body = call_args[1].get("json", {})
            assert body.get("team_id") == "tid-123"
            assert body.get("models") == ["llama-4-scout"]

    @pytest.mark.asyncio
    async def test_creates_key_without_models(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": "sk-virtual-def456"}

        with patch("app.routers.llm_keys.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            key = await _create_virtual_key(
                team_id="tid-123",
                key_alias="my-agent",
                namespace="team1",
            )
            assert key == "sk-virtual-def456"

            body = mock_client.request.call_args[1].get("json", {})
            assert "models" not in body


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestPydanticModels:
    def test_team_create_defaults(self):
        req = TeamCreateRequest(namespace="team1")
        assert req.max_budget == 500.0
        assert req.budget_duration == "30d"
        assert req.models is None

    def test_key_create_defaults(self):
        req = KeyCreateRequest(namespace="team1", agent_name="sandbox-agent")
        assert req.max_budget == 100.0
        assert req.budget_duration == "30d"
        assert req.models is None

    def test_key_create_with_models(self):
        req = KeyCreateRequest(
            namespace="team1",
            agent_name="sandbox-agent",
            models=["llama-4-scout", "mistral-small"],
        )
        assert req.models == ["llama-4-scout", "mistral-small"]


# ---------------------------------------------------------------------------
# DEFAULT_LLM_SECRET consistency
# ---------------------------------------------------------------------------


class TestSecretDefaults:
    def test_sandbox_deploy_default_matches(self):
        """sandbox_deploy.py DEFAULT_LLM_SECRET should match the key
        created by 38-deploy-litellm.sh (litellm-virtual-keys/api-key)."""
        sandbox_deploy = pytest.importorskip(
            "app.routers.sandbox_deploy", reason="sandbox_deploy module not available"
        )
        default_secret = sandbox_deploy.DEFAULT_LLM_SECRET
        default_key = sandbox_deploy.DEFAULT_LLM_SECRET_KEY

        assert default_secret == "litellm-virtual-keys"
        assert default_key == "api-key"
