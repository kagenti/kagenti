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
