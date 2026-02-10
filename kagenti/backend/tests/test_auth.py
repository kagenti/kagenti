# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for authentication and authorization utilities.
"""

import pytest

from app.core.auth import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    ROLE_HIERARCHY,
    get_effective_roles,
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

    def test_admin_inherits_all_roles(self):
        """Admin should inherit operator and viewer roles."""
        assert ROLE_OPERATOR in ROLE_HIERARCHY[ROLE_ADMIN]
        assert ROLE_VIEWER in ROLE_HIERARCHY[ROLE_ADMIN]

    def test_operator_inherits_viewer(self):
        """Operator should inherit viewer role."""
        assert ROLE_VIEWER in ROLE_HIERARCHY[ROLE_OPERATOR]

    def test_viewer_inherits_nothing(self):
        """Viewer should not inherit any roles."""
        assert ROLE_HIERARCHY[ROLE_VIEWER] == []


class TestGetEffectiveRoles:
    """Test role hierarchy expansion."""

    def test_admin_gets_all_roles(self):
        """Admin role should expand to include all roles."""
        effective = get_effective_roles([ROLE_ADMIN])
        assert ROLE_ADMIN in effective
        assert ROLE_OPERATOR in effective
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
