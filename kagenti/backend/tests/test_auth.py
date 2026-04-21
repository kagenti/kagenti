# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for authentication and authorization utilities.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    ROLE_HIERARCHY,
    get_effective_roles,
    require_roles,
    TokenData,
)


class TestRoleConstants:
    """Test role constant definitions."""

    def test_role_constants_are_strings(self):
        """Role constants should be string values."""
        assert isinstance(ROLE_VIEWER, str)
        assert isinstance(ROLE_OPERATOR, str)
        assert isinstance(ROLE_ADMIN, str)

    def test_role_constants_have_kagenti_prefix(self):
        """Role constants should have kagenti- prefix for Keycloak."""
        assert ROLE_VIEWER.startswith("kagenti-")
        assert ROLE_OPERATOR.startswith("kagenti-")
        assert ROLE_ADMIN.startswith("kagenti-")

    def test_role_hierarchy_structure(self):
        """Role hierarchy should be properly defined."""
        assert ROLE_ADMIN in ROLE_HIERARCHY
        assert ROLE_OPERATOR in ROLE_HIERARCHY
        assert ROLE_VIEWER in ROLE_HIERARCHY

    def test_admin_inherits_operator_directly(self):
        """Admin should directly inherit only operator (viewer is transitive)."""
        assert ROLE_OPERATOR in ROLE_HIERARCHY[ROLE_ADMIN]
        # Viewer is NOT listed directly - it's inherited transitively via operator
        assert ROLE_VIEWER not in ROLE_HIERARCHY[ROLE_ADMIN]

    def test_operator_inherits_viewer(self):
        """Operator should inherit viewer role."""
        assert ROLE_VIEWER in ROLE_HIERARCHY[ROLE_OPERATOR]

    def test_viewer_inherits_nothing(self):
        """Viewer should not inherit any roles."""
        assert ROLE_HIERARCHY[ROLE_VIEWER] == []


class TestGetEffectiveRoles:
    """Test role hierarchy expansion."""

    def test_admin_gets_all_roles_transitively(self):
        """Admin role should expand to include all roles via transitive inheritance."""
        effective = get_effective_roles([ROLE_ADMIN])
        assert ROLE_ADMIN in effective
        assert ROLE_OPERATOR in effective
        # Viewer is inherited transitively: admin -> operator -> viewer
        assert ROLE_VIEWER in effective

    def test_operator_gets_viewer(self):
        """Operator role should expand to include viewer."""
        effective = get_effective_roles([ROLE_OPERATOR])
        assert ROLE_OPERATOR in effective
        assert ROLE_VIEWER in effective
        assert ROLE_ADMIN not in effective

    def test_viewer_stays_viewer(self):
        """Viewer role should not expand."""
        effective = get_effective_roles([ROLE_VIEWER])
        assert ROLE_VIEWER in effective
        assert ROLE_OPERATOR not in effective
        assert ROLE_ADMIN not in effective

    def test_empty_roles(self):
        """Empty role list should return empty set."""
        effective = get_effective_roles([])
        assert effective == set()

    def test_unknown_role_preserved(self):
        """Unknown roles should be preserved without expansion."""
        effective = get_effective_roles(["custom-role"])
        assert "custom-role" in effective
        assert len(effective) == 1

    def test_multiple_roles_combined(self):
        """Multiple roles should combine their hierarchies."""
        effective = get_effective_roles([ROLE_OPERATOR, "custom-role"])
        assert ROLE_OPERATOR in effective
        assert ROLE_VIEWER in effective
        assert "custom-role" in effective
        assert ROLE_ADMIN not in effective

    def test_duplicate_roles_handled(self):
        """Duplicate roles in input should not cause issues."""
        effective = get_effective_roles([ROLE_ADMIN, ROLE_ADMIN, ROLE_OPERATOR])
        assert ROLE_ADMIN in effective
        assert ROLE_OPERATOR in effective
        assert ROLE_VIEWER in effective
        # Should still only have 3 unique roles
        assert len(effective) == 3

    def test_already_inherited_role_in_input(self):
        """Having both a role and its inherited role should work correctly."""
        # User has both admin and viewer explicitly
        effective = get_effective_roles([ROLE_ADMIN, ROLE_VIEWER])
        assert ROLE_ADMIN in effective
        assert ROLE_OPERATOR in effective
        assert ROLE_VIEWER in effective
        assert len(effective) == 3


class TestTokenDataHasRole:
    """Test TokenData.has_role with hierarchy support."""

    def test_admin_has_all_roles(self):
        """User with admin role should have all roles via hierarchy."""
        token = TokenData(
            sub="user-1",
            username="admin",
            email="admin@example.com",
            roles=[ROLE_ADMIN],
            raw_token={},
        )
        assert token.has_role(ROLE_ADMIN)
        assert token.has_role(ROLE_OPERATOR)
        assert token.has_role(ROLE_VIEWER)

    def test_operator_has_operator_and_viewer(self):
        """User with operator role should have operator and viewer."""
        token = TokenData(
            sub="user-2",
            username="operator",
            email="operator@example.com",
            roles=[ROLE_OPERATOR],
            raw_token={},
        )
        assert not token.has_role(ROLE_ADMIN)
        assert token.has_role(ROLE_OPERATOR)
        assert token.has_role(ROLE_VIEWER)

    def test_viewer_has_only_viewer(self):
        """User with viewer role should only have viewer."""
        token = TokenData(
            sub="user-3",
            username="viewer",
            email="viewer@example.com",
            roles=[ROLE_VIEWER],
            raw_token={},
        )
        assert not token.has_role(ROLE_ADMIN)
        assert not token.has_role(ROLE_OPERATOR)
        assert token.has_role(ROLE_VIEWER)

    def test_no_roles_has_nothing(self):
        """User with no roles should not have any kagenti roles."""
        token = TokenData(
            sub="user-4",
            username="nobody",
            email="nobody@example.com",
            roles=[],
            raw_token={},
        )
        assert not token.has_role(ROLE_ADMIN)
        assert not token.has_role(ROLE_OPERATOR)
        assert not token.has_role(ROLE_VIEWER)

    def test_custom_role_check(self):
        """Custom roles should work without hierarchy."""
        token = TokenData(
            sub="user-5",
            username="custom",
            email="custom@example.com",
            roles=["custom-role"],
            raw_token={},
        )
        assert token.has_role("custom-role")
        assert not token.has_role("other-role")


# =============================================================================
# Endpoint RBAC Integration Tests
# =============================================================================


def create_test_app():
    """Create a minimal FastAPI app for testing RBAC on endpoints."""
    from fastapi import Depends

    app = FastAPI()

    @app.get("/viewer-only")
    async def viewer_endpoint(user: TokenData = Depends(require_roles(ROLE_VIEWER))):
        return {"user": user.username, "roles": user.roles}

    @app.get("/operator-only")
    async def operator_endpoint(user: TokenData = Depends(require_roles(ROLE_OPERATOR))):
        return {"user": user.username, "roles": user.roles}

    @app.get("/admin-only")
    async def admin_endpoint(user: TokenData = Depends(require_roles(ROLE_ADMIN))):
        return {"user": user.username, "roles": user.roles}

    return app


def mock_token_data(roles: list[str]) -> TokenData:
    """Create a mock TokenData with specified roles."""
    return TokenData(
        sub="test-user",
        username="testuser",
        email="test@example.com",
        roles=roles,
        raw_token={},
    )


class TestEndpointRBAC:
    """Integration tests for endpoint RBAC protection."""

    @pytest.fixture
    def app(self):
        """Create test application."""
        return create_test_app()

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_unauthenticated_returns_401(self, client):
        """Unauthenticated requests to protected endpoints should return 401."""
        with patch("app.core.auth.settings") as mock_settings:
            mock_settings.enable_auth = True

            response = client.get("/viewer-only")
            assert response.status_code == 401

    def test_viewer_can_access_viewer_endpoint(self, client):
        """User with viewer role should access viewer-only endpoint."""
        with patch("app.core.auth.settings") as mock_settings:
            mock_settings.enable_auth = True

            with patch(
                "app.core.auth.validate_token",
                new_callable=AsyncMock,
                return_value=mock_token_data([ROLE_VIEWER]),
            ):
                response = client.get(
                    "/viewer-only", headers={"Authorization": "Bearer fake-token"}
                )
                assert response.status_code == 200
                assert response.json()["user"] == "testuser"

    def test_viewer_cannot_access_operator_endpoint(self, client):
        """User with only viewer role should get 403 on operator-only endpoint."""
        with patch("app.core.auth.settings") as mock_settings:
            mock_settings.enable_auth = True

            with patch(
                "app.core.auth.validate_token",
                new_callable=AsyncMock,
                return_value=mock_token_data([ROLE_VIEWER]),
            ):
                response = client.get(
                    "/operator-only", headers={"Authorization": "Bearer fake-token"}
                )
                assert response.status_code == 403

    def test_operator_can_access_viewer_endpoint(self, client):
        """User with operator role should access viewer-only endpoint via hierarchy."""
        with patch("app.core.auth.settings") as mock_settings:
            mock_settings.enable_auth = True

            with patch(
                "app.core.auth.validate_token",
                new_callable=AsyncMock,
                return_value=mock_token_data([ROLE_OPERATOR]),
            ):
                response = client.get(
                    "/viewer-only", headers={"Authorization": "Bearer fake-token"}
                )
                assert response.status_code == 200

    def test_operator_can_access_operator_endpoint(self, client):
        """User with operator role should access operator-only endpoint."""
        with patch("app.core.auth.settings") as mock_settings:
            mock_settings.enable_auth = True

            with patch(
                "app.core.auth.validate_token",
                new_callable=AsyncMock,
                return_value=mock_token_data([ROLE_OPERATOR]),
            ):
                response = client.get(
                    "/operator-only", headers={"Authorization": "Bearer fake-token"}
                )
                assert response.status_code == 200

    def test_operator_cannot_access_admin_endpoint(self, client):
        """User with operator role should get 403 on admin-only endpoint."""
        with patch("app.core.auth.settings") as mock_settings:
            mock_settings.enable_auth = True

            with patch(
                "app.core.auth.validate_token",
                new_callable=AsyncMock,
                return_value=mock_token_data([ROLE_OPERATOR]),
            ):
                response = client.get("/admin-only", headers={"Authorization": "Bearer fake-token"})
                assert response.status_code == 403

    def test_admin_can_access_all_endpoints(self, client):
        """User with admin role should access all endpoints via hierarchy."""
        with patch("app.core.auth.settings") as mock_settings:
            mock_settings.enable_auth = True

            with patch(
                "app.core.auth.validate_token",
                new_callable=AsyncMock,
                return_value=mock_token_data([ROLE_ADMIN]),
            ):
                # Admin can access viewer endpoint
                response = client.get(
                    "/viewer-only", headers={"Authorization": "Bearer fake-token"}
                )
                assert response.status_code == 200

                # Admin can access operator endpoint
                response = client.get(
                    "/operator-only", headers={"Authorization": "Bearer fake-token"}
                )
                assert response.status_code == 200

                # Admin can access admin endpoint
                response = client.get("/admin-only", headers={"Authorization": "Bearer fake-token"})
                assert response.status_code == 200

    def test_auth_disabled_allows_all(self, client):
        """When auth is disabled, all endpoints should be accessible."""
        with patch("app.core.auth.settings") as mock_settings:
            mock_settings.enable_auth = False

            # No token needed when auth is disabled
            response = client.get("/admin-only")
            assert response.status_code == 200
            # Mock user should have admin role
            assert "admin" in response.json()["user"]
