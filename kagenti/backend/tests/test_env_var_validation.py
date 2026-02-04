# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Tests for environment variable name validation.

This test suite verifies that environment variable names are properly validated
according to Kubernetes rules before agent/tool creation.
"""

import pytest
from pydantic import ValidationError

from app.routers.agents import EnvVar as AgentEnvVar
from app.routers.tools import EnvVar as ToolEnvVar


class TestAgentEnvVarValidation:
    """Test environment variable validation for agents."""

    def test_valid_env_var_names(self):
        """Test that valid environment variable names are accepted."""
        valid_names = [
            "API_KEY",
            "DATABASE_URL",
            "MY_VAR",
            "var123",
            "MY_VAR_123",
            "_PRIVATE_VAR",
            "UPPER",
            "lower",
            "MixedCase123",
        ]

        for name in valid_names:
            # Should not raise ValidationError
            env_var = AgentEnvVar(name=name, value="test_value")
            assert env_var.name == name

    def test_invalid_env_var_names(self):
        """Test that invalid environment variable names are rejected."""
        invalid_names = [
            "123VAR",  # Starts with digit
            "MY-VAR",  # Contains hyphen
            "MY.VAR",  # Contains dot
            "MY VAR",  # Contains space
            "MY=VAR",  # Contains equals
            "MY$VAR",  # Contains dollar sign
            "MY@VAR",  # Contains at sign
            "MY-VAR-123",  # Contains hyphens
            "MCP_TRANSPORT=http",  # Contains equals (common mistake)
            "",  # Empty name
        ]

        for name in invalid_names:
            with pytest.raises(ValidationError) as exc_info:
                AgentEnvVar(name=name, value="test_value")

            # Verify the error message mentions the validation rule
            assert "Invalid environment variable name" in str(exc_info.value)

    def test_env_var_with_valuefrom(self):
        """Test that valueFrom env vars also validate the name."""
        # Valid name with secretKeyRef
        env_var = AgentEnvVar(
            name="MY_SECRET", valueFrom={"secretKeyRef": {"name": "my-secret", "key": "password"}}
        )
        assert env_var.name == "MY_SECRET"

        # Invalid name with secretKeyRef
        with pytest.raises(ValidationError) as exc_info:
            AgentEnvVar(
                name="123-INVALID",
                valueFrom={"secretKeyRef": {"name": "my-secret", "key": "password"}},
            )
        assert "Invalid environment variable name" in str(exc_info.value)


class TestToolEnvVarValidation:
    """Test environment variable validation for tools."""

    def test_valid_env_var_names(self):
        """Test that valid environment variable names are accepted."""
        valid_names = [
            "API_KEY",
            "DATABASE_URL",
            "MY_VAR",
            "var123",
            "_PRIVATE_VAR",
        ]

        for name in valid_names:
            # Should not raise ValidationError
            env_var = ToolEnvVar(name=name, value="test_value")
            assert env_var.name == name

    def test_invalid_env_var_names(self):
        """Test that invalid environment variable names are rejected."""
        invalid_names = [
            "123VAR",  # Starts with digit
            "MY-VAR",  # Contains hyphen
            "MY.VAR",  # Contains dot
            "MY VAR",  # Contains space
            "MY=VAR",  # Contains equals
        ]

        for name in invalid_names:
            with pytest.raises(ValidationError) as exc_info:
                ToolEnvVar(name=name, value="test_value")

            # Verify the error message mentions the validation rule
            assert "Invalid environment variable name" in str(exc_info.value)


class TestEnvVarNamePatterns:
    """Test specific edge cases for environment variable names."""

    def test_underscore_prefix(self):
        """Test that names can start with underscore."""
        env_var = AgentEnvVar(name="_PRIVATE", value="test")
        assert env_var.name == "_PRIVATE"

    def test_digits_in_middle(self):
        """Test that digits are allowed in the middle and end."""
        env_var = AgentEnvVar(name="VAR_123_END", value="test")
        assert env_var.name == "VAR_123_END"

    def test_cannot_start_with_digit(self):
        """Test that names cannot start with a digit."""
        with pytest.raises(ValidationError):
            AgentEnvVar(name="1VAR", value="test")

    def test_special_characters_rejected(self):
        """Test that special characters are rejected."""
        special_chars = ["-", ".", "=", "$", "@", "#", "%", "^", "&", "*", "(", ")", "+"]

        for char in special_chars:
            with pytest.raises(ValidationError):
                AgentEnvVar(name=f"VAR{char}NAME", value="test")

    def test_empty_name_rejected(self):
        """Test that empty names are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            AgentEnvVar(name="", value="test")
        assert "Environment variable name cannot be empty" in str(exc_info.value)
