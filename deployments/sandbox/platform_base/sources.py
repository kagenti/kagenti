"""Capability loader for sources.json.

sources.json is baked into the agent container image and declares what
resources exist on the image: package managers, registries, git remotes,
web domains, and runtime limits.  The sandbox executor uses it alongside
settings.json -- settings.json controls what operations are *allowed*,
sources.json controls what resources are *available*.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


_DEFAULT_MAX_EXECUTION_TIME_SECONDS = 300
_DEFAULT_MAX_MEMORY_MB = 2048


@dataclass(frozen=True)
class SourcesConfig:
    """Structured representation of a ``sources.json`` file."""

    _data: dict[str, Any] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourcesConfig:
        """Create a *SourcesConfig* from a parsed JSON dictionary."""
        return cls(_data=data)

    @classmethod
    def from_file(cls, path: Path) -> SourcesConfig:
        """Load a *SourcesConfig* from a ``sources.json`` file on disk."""
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    # ------------------------------------------------------------------
    # Package-manager queries
    # ------------------------------------------------------------------

    def is_package_manager_enabled(self, name: str) -> bool:
        """Return *True* if the named package manager is enabled."""
        managers: dict[str, Any] = self._data.get("package_managers", {})
        entry = managers.get(name)
        if entry is None:
            return False
        return bool(entry.get("enabled", False))

    def is_package_blocked(self, manager: str, package: str) -> bool:
        """Return *True* if *package* is on the block-list for *manager*."""
        managers: dict[str, Any] = self._data.get("package_managers", {})
        entry = managers.get(manager)
        if entry is None:
            return False
        blocked: list[str] = entry.get("blocked_packages", [])
        return package in blocked

    # ------------------------------------------------------------------
    # Git-remote queries
    # ------------------------------------------------------------------

    def is_git_remote_allowed(self, url: str) -> bool:
        """Return *True* if *url* matches one of the ``allowed_remotes`` patterns.

        Pattern matching uses :func:`fnmatch.fnmatch`.  If git access is
        disabled in the config the method always returns *False*.
        """
        git_section: dict[str, Any] = self._data.get("git", {})
        if not git_section.get("enabled", False):
            return False
        patterns: list[str] = git_section.get("allowed_remotes", [])
        return any(fnmatch(url, pattern) for pattern in patterns)

    # ------------------------------------------------------------------
    # Web-access queries
    # ------------------------------------------------------------------

    def is_web_access_enabled(self) -> bool:
        """Return *True* if web access is enabled."""
        return bool(self._data.get("web_access", {}).get("enabled", False))

    def is_domain_allowed(self, domain: str) -> bool:
        """Return *True* if *domain* matches the allowed_domains list.

        Uses :func:`fnmatch.fnmatch` for pattern matching (e.g. ``*.github.com``).
        Returns *False* if web access is disabled.
        """
        web: dict[str, Any] = self._data.get("web_access", {})
        if not web.get("enabled", False):
            return False

        # Check blocked first
        for pattern in web.get("blocked_domains", []):
            if fnmatch(domain, pattern):
                return False

        # Check allowed
        for pattern in web.get("allowed_domains", []):
            if fnmatch(domain, pattern):
                return True

        return False

    # ------------------------------------------------------------------
    # Runtime-limit properties
    # ------------------------------------------------------------------

    @property
    def max_execution_time_seconds(self) -> int:
        """Maximum execution time for a single run, in seconds."""
        runtime: dict[str, Any] = self._data.get("runtime", {})
        return int(
            runtime.get(
                "max_execution_time_seconds", _DEFAULT_MAX_EXECUTION_TIME_SECONDS
            )
        )

    @property
    def max_memory_mb(self) -> int:
        """Maximum memory for a single run, in megabytes."""
        runtime: dict[str, Any] = self._data.get("runtime", {})
        return int(runtime.get("max_memory_mb", _DEFAULT_MAX_MEMORY_MB))
