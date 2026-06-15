"""Workspace manager for per-context_id directory isolation.

Each A2A context_id gets its own subdirectory under workspace_root
(typically mounted from a shared RWX PVC at /workspace). The manager
creates standardised subdirectories and tracks metadata in .context.json.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_SUBDIRS = ["scripts", "data", "repos", "output"]


class WorkspaceManager:
    """Manages per-context workspace directories on shared storage.

    Parameters
    ----------
    workspace_root:
        Absolute path to the shared workspace mount (e.g. ``/workspace``).
    agent_name:
        Name of the agent that owns the workspaces.
    namespace:
        Kubernetes namespace the agent is running in.
    ttl_days:
        Default time-to-live for workspace directories.
    """

    def __init__(
        self,
        workspace_root: str,
        agent_name: str,
        namespace: str = "",
        ttl_days: int = 7,
    ) -> None:
        self.workspace_root = workspace_root
        self.agent_name = agent_name
        self.namespace = namespace
        self.ttl_days = ttl_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_workspace_path(self, context_id: str) -> str:
        """Return the workspace path for *context_id* without creating it.

        Raises ValueError if context_id would escape workspace_root.
        """
        workspace_path = os.path.join(self.workspace_root, context_id)
        resolved = os.path.realpath(workspace_path)
        if not resolved.startswith(os.path.realpath(self.workspace_root)):
            raise ValueError(
                f"context_id escapes workspace root: {context_id!r}"
            )
        return workspace_path

    def ensure_workspace(self, context_id: str) -> str:
        """Create (or re-use) the workspace for *context_id*.

        On first call the directory tree and ``.context.json`` are created.
        On subsequent calls ``last_accessed_at`` in the metadata file is
        updated.

        Returns the absolute path to the workspace directory.

        Raises
        ------
        ValueError
            If *context_id* is empty.
        """
        if not context_id:
            raise ValueError("context_id must not be empty")

        workspace_path = self.get_workspace_path(context_id)
        context_file = Path(workspace_path) / ".context.json"

        # Create the workspace root and subdirs (idempotent via exist_ok).
        for subdir in WORKSPACE_SUBDIRS:
            os.makedirs(os.path.join(workspace_path, subdir), exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()

        if context_file.exists():
            # Update last_accessed_at, preserve everything else.
            data = json.loads(context_file.read_text())
            data["last_accessed_at"] = now
            data["disk_usage_bytes"] = self._disk_usage(workspace_path)
            context_file.write_text(json.dumps(data, indent=2) + "\n")
        else:
            # First time -- write fresh metadata.
            data = {
                "context_id": context_id,
                "agent": self.agent_name,
                "namespace": self.namespace,
                "created_at": now,
                "last_accessed_at": now,
                "ttl_days": self.ttl_days,
                "disk_usage_bytes": 0,
            }
            context_file.write_text(json.dumps(data, indent=2) + "\n")

        return workspace_path

    def list_contexts(self) -> list[str]:
        """Return a list of context_ids that have workspace directories.

        Only directories that contain a ``.context.json`` file are
        considered valid contexts.
        """
        root = Path(self.workspace_root)
        if not root.is_dir():
            return []

        contexts: list[str] = []
        for entry in root.iterdir():
            if entry.is_dir() and (entry / ".context.json").exists():
                contexts.append(entry.name)
        return contexts

    def cleanup_expired(self) -> list[str]:
        """Remove workspace directories whose TTL has expired.

        Reads ``created_at`` and ``ttl_days`` from each context's
        ``.context.json``.  If ``created_at + ttl_days`` is in the past,
        the workspace directory is deleted.

        Returns a list of context_ids that were cleaned up.
        """
        import shutil

        root = Path(self.workspace_root)
        if not root.is_dir():
            return []

        now = datetime.now(timezone.utc)
        cleaned: list[str] = []

        for entry in root.iterdir():
            context_file = entry / ".context.json"
            if not entry.is_dir() or not context_file.exists():
                continue

            try:
                data = json.loads(context_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            created_str = data.get("created_at")
            ttl = data.get("ttl_days", self.ttl_days)

            if not created_str:
                continue

            try:
                created_at = datetime.fromisoformat(created_str)
            except ValueError:
                continue

            from datetime import timedelta

            if now > created_at + timedelta(days=ttl):
                try:
                    shutil.rmtree(entry)
                    cleaned.append(entry.name)
                except OSError:
                    pass  # best-effort cleanup

        return cleaned

    def get_total_disk_usage(self) -> int:
        """Return total disk usage in bytes across all workspaces."""
        root = Path(self.workspace_root)
        if not root.is_dir():
            return 0
        return self._disk_usage(str(root))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _disk_usage(path: str) -> int:
        """Return total size in bytes of all files under *path*."""
        total = 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                try:
                    total += os.path.getsize(fpath)
                except OSError:
                    pass
        return total
