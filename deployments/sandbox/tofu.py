"""
Kagenti TOFU (Trust On First Use) — Config file integrity verification (Phase 6, C4+C15)

On first sandbox creation, hashes CLAUDE.md, settings.json, and sources.json
and stores them in a ConfigMap. On subsequent runs, verifies hashes match.
If hashes changed, blocks sandbox creation (poisoned instruction detection).

Usage:
    from tofu import TofuVerifier
    verifier = TofuVerifier("/workspace/repo", namespace="team1")
    verifier.verify_or_initialize()  # First run: stores hashes. Later: verifies.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Optional


class TofuVerifier:
    """Trust-On-First-Use verifier for sandbox config files."""

    TRACKED_FILES = [
        "CLAUDE.md",
        ".claude/settings.json",
        "sources.json",
    ]

    def __init__(
        self,
        workspace: str,
        namespace: str = "team1",
        configmap_name: Optional[str] = None,
    ):
        self.workspace = Path(workspace)
        self.namespace = namespace
        self.configmap_name = configmap_name or f"tofu-{self.workspace.name}"

    def _hash_file(self, filepath: Path) -> Optional[str]:
        """SHA-256 hash of a file, or None if it doesn't exist."""
        if not filepath.exists():
            return None
        return hashlib.sha256(filepath.read_bytes()).hexdigest()

    def compute_hashes(self) -> dict[str, Optional[str]]:
        """Compute hashes for all tracked files."""
        hashes = {}
        for filename in self.TRACKED_FILES:
            filepath = self.workspace / filename
            hashes[filename] = self._hash_file(filepath)
        return hashes

    def get_stored_hashes(self) -> Optional[dict[str, Optional[str]]]:
        """Read stored hashes from ConfigMap (via kubectl)."""
        import subprocess

        result = subprocess.run(
            [
                "kubectl",
                "get",
                "configmap",
                self.configmap_name,
                "-n",
                self.namespace,
                "-o",
                "jsonpath={.data.hashes}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None  # ConfigMap doesn't exist (first run)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    def store_hashes(self, hashes: dict[str, Optional[str]]):
        """Store hashes in a ConfigMap."""
        import subprocess

        cm_data = json.dumps(hashes, indent=2)
        # Apply (create or update)
        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {
                        "name": self.configmap_name,
                        "namespace": self.namespace,
                        "labels": {
                            "app.kubernetes.io/part-of": "kagenti",
                            "app.kubernetes.io/component": "tofu-store",
                        },
                    },
                    "data": {"hashes": cm_data},
                }
            ),
            capture_output=True,
            text=True,
            timeout=10,
        )

    def verify_or_initialize(self) -> tuple[bool, str]:
        """Verify file integrity or initialize trust store.

        Returns (ok, message) tuple.
        On first run: stores hashes, returns (True, "initialized").
        On subsequent runs: verifies, returns (True, "verified") or (False, "mismatch: ...").
        """
        current = self.compute_hashes()
        stored = self.get_stored_hashes()

        if stored is None:
            # First run — trust on first use
            self.store_hashes(current)
            return (
                True,
                f"TOFU initialized: {len([v for v in current.values() if v])} files hashed",
            )

        # Verify
        mismatches = []
        for filename, current_hash in current.items():
            stored_hash = stored.get(filename)
            if current_hash != stored_hash:
                if current_hash is None:
                    mismatches.append(f"{filename}: DELETED (was {stored_hash[:8]}...)")
                elif stored_hash is None:
                    mismatches.append(f"{filename}: NEW (hash {current_hash[:8]}...)")
                else:
                    mismatches.append(
                        f"{filename}: CHANGED ({stored_hash[:8]}... → {current_hash[:8]}...)"
                    )

        if mismatches:
            return False, f"TOFU verification FAILED: {'; '.join(mismatches)}"

        return (
            True,
            f"TOFU verified: {len([v for v in current.values() if v])} files match",
        )


if __name__ == "__main__":
    import sys

    workspace = sys.argv[1] if len(sys.argv) > 1 else "/workspace/repo"

    verifier = TofuVerifier(workspace)
    hashes = verifier.compute_hashes()
    print("Current file hashes:")
    for filename, h in hashes.items():
        if h:
            print(f"  {filename}: {h[:16]}...")
        else:
            print(f"  {filename}: (not found)")
