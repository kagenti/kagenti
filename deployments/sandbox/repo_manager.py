"""
Kagenti Sandbox Repo Manager — Multi-repo cloning with access control (Phase 5, C9 dynamic)

Controls which repositories can be cloned at runtime based on sources.json policy.
Git operations go through the HTTP proxy (Squid) for domain filtering, and AuthBridge
handles token exchange (SPIFFE SVID → scoped GitHub token) transparently.

Usage:
    from repo_manager import RepoManager
    mgr = RepoManager("/workspace", "/workspace/repo/sources.json")
    mgr.clone("https://github.com/kagenti/kagenti-extensions")  # allowed
    mgr.clone("https://github.com/evil-org/malware")  # blocked by policy
"""

import fnmatch
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


class RepoManager:
    """Manages multi-repo cloning with sources.json access control."""

    def __init__(
        self, workspace: str = "/workspace", sources_path: Optional[str] = None
    ):
        self.workspace = Path(workspace)
        self.repos_dir = self.workspace / "repos"
        self.repos_dir.mkdir(parents=True, exist_ok=True)

        # Load sources.json policy
        self.policy = {}
        if sources_path and Path(sources_path).exists():
            with open(sources_path) as f:
                self.policy = json.load(f)
        elif (self.workspace / "repo" / "sources.json").exists():
            with open(self.workspace / "repo" / "sources.json") as f:
                self.policy = json.load(f)

        self.allowed_remotes = self.policy.get("allowed_remotes", [])
        self.denied_remotes = self.policy.get("denied_remotes", [])
        self.limits = self.policy.get("resource_limits", {})
        self._cloned_repos: list[str] = []

    def is_allowed(self, repo_url: str) -> tuple[bool, str]:
        """Check if a repo URL is allowed by sources.json policy.

        Returns (allowed, reason) tuple.
        """
        # Check denied list first (deny overrides allow)
        for pattern in self.denied_remotes:
            if fnmatch.fnmatch(repo_url, pattern):
                return False, f"Denied by pattern: {pattern}"

        # Check allowed list
        if not self.allowed_remotes:
            return True, "No allowed_remotes configured (permissive mode)"

        for pattern in self.allowed_remotes:
            if fnmatch.fnmatch(repo_url, pattern):
                return True, f"Allowed by pattern: {pattern}"

        return False, f"Not in allowed_remotes: {self.allowed_remotes}"

    def clone(self, repo_url: str, branch: str = "main", depth: int = 1) -> Path:
        """Clone a repo into /workspace/repos/ after policy check.

        Returns the path to the cloned repo.
        Raises PermissionError if blocked by policy.
        Raises RuntimeError if clone fails.
        """
        # Policy check
        allowed, reason = self.is_allowed(repo_url)
        if not allowed:
            raise PermissionError(f"Repo clone blocked: {repo_url} — {reason}")

        # Resource limits check
        max_repos = self.limits.get("max_repos", 10)
        if len(self._cloned_repos) >= max_repos:
            raise RuntimeError(f"Max repos limit reached ({max_repos})")

        # Derive repo name from URL
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        dest = self.repos_dir / repo_name

        if dest.exists():
            shutil.rmtree(dest)

        # Clone via proxy (HTTP_PROXY/HTTPS_PROXY are set in env)
        cmd = [
            "git",
            "clone",
            f"--depth={depth}",
            f"--branch={branch}",
            repo_url,
            str(dest),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr[:300]}")

        self._cloned_repos.append(repo_url)
        return dest

    def list_cloned(self) -> list[str]:
        """Return list of cloned repo URLs."""
        return list(self._cloned_repos)

    def list_repos_on_disk(self) -> list[str]:
        """Return list of repo directories on disk."""
        if not self.repos_dir.exists():
            return []
        return [d.name for d in self.repos_dir.iterdir() if d.is_dir()]


if __name__ == "__main__":
    import sys

    workspace = sys.argv[1] if len(sys.argv) > 1 else "/workspace"
    sources = sys.argv[2] if len(sys.argv) > 2 else None

    mgr = RepoManager(workspace, sources)
    print(f"Allowed remotes: {mgr.allowed_remotes}")
    print(f"Denied remotes: {mgr.denied_remotes}")

    # Test policy
    test_urls = [
        "https://github.com/kagenti/kagenti-extensions",
        "https://github.com/kagenti/kagenti",
        "https://github.com/evil-org/malware",
        "https://github.com/random/other-repo",
    ]
    for url in test_urls:
        allowed, reason = mgr.is_allowed(url)
        status = "ALLOWED" if allowed else "BLOCKED"
        print(f"  {status}: {url} — {reason}")
