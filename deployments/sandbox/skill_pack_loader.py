"""
Kagenti SkillPackLoader — Versioned skill-pack init container (Phase 6)

Clones skill packs from pinned git sources, verifies GPG signatures and
content hashes, then copies skills into /workspace/.claude/skills/ where
the existing SkillsLoader picks them up.

Runs as an init container before the sandbox agent starts.

Usage:
    # CLI
    python skill_pack_loader.py --config /etc/kagenti/skill-packs.yaml --workspace /workspace

    # Library
    from skill_pack_loader import SkillPackLoader
    loader = SkillPackLoader("/etc/kagenti/skill-packs.yaml", "/workspace")
    for pack in loader.get_default_packs():
        loader.load_pack(pack)
"""

import argparse
import hashlib
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class SkillPackLoader:
    """Loads versioned skill packs from pinned git sources into a workspace."""

    def __init__(self, config_path: str, workspace: str):
        """Load the skill-packs.yaml manifest.

        Args:
            config_path: Path to skill-packs.yaml.
            workspace: Target workspace directory (e.g. /workspace).

        Raises:
            FileNotFoundError: If config_path does not exist.
        """
        config = Path(config_path)
        if not config.exists():
            raise FileNotFoundError(f"Skill-packs manifest not found: {config_path}")

        with open(config) as f:
            self.manifest = yaml.safe_load(f)

        self.workspace = workspace

    # ------------------------------------------------------------------
    # Pack filtering
    # ------------------------------------------------------------------

    def get_default_packs(self) -> list[dict]:
        """Return packs with ``default: true``."""
        return [p for p in self.manifest.get("packs", []) if p.get("default")]

    def get_packs(self, names: list[str]) -> list[dict]:
        """Return packs whose names appear in *names*.

        Unknown names are silently skipped.
        """
        name_set = set(names)
        return [p for p in self.manifest.get("packs", []) if p["name"] in name_set]

    # ------------------------------------------------------------------
    # Git operations
    # ------------------------------------------------------------------

    def clone_pack(self, pack: dict, target: str) -> None:
        """Clone a pack repo at a pinned commit.

        Performs ``git clone --no-checkout`` followed by ``git checkout <commit>``.

        Args:
            pack: A pack dict from the manifest (needs ``source`` and ``commit``).
            target: Local directory to clone into.

        Raises:
            RuntimeError: If either git command fails.
        """
        source = pack["source"]
        commit = pack["commit"]

        # Step 1: clone without checkout
        clone_cmd = ["git", "clone", "--no-checkout", source, target]
        result = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed for {source}: {result.stderr[:300]}")

        # Step 2: checkout the pinned commit
        checkout_cmd = ["git", "-C", target, "checkout", commit]
        result = subprocess.run(
            checkout_cmd, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise RuntimeError(f"git checkout {commit} failed: {result.stderr[:300]}")

    def verify_commit_signature(self, repo_path: str, commit: str, signer: str) -> bool:
        """Verify the GPG signature on a commit.

        Args:
            repo_path: Path to the git repository.
            commit: Commit hash to verify.
            signer: Expected signer identifier (for logging; git does the check).

        Returns:
            True if the signature is valid, False otherwise.
        """
        cmd = ["git", "-C", repo_path, "verify-commit", commit]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.warning(
                "Commit %s signature verification failed (expected signer: %s): %s",
                commit,
                signer,
                result.stderr[:200],
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Content integrity
    # ------------------------------------------------------------------

    def compute_content_hash(self, directory: str) -> str:
        """Compute a deterministic SHA-256 hash of all files in *directory*.

        Files are sorted by their relative path to ensure determinism.

        Returns:
            ``sha256:<hex>`` digest string.
        """
        h = hashlib.sha256()
        base = Path(directory)
        for fpath in sorted(base.rglob("*")):
            if fpath.is_file():
                rel = fpath.relative_to(base)
                h.update(str(rel).encode("utf-8"))
                h.update(fpath.read_bytes())
        return f"sha256:{h.hexdigest()}"

    def verify_content_hash(self, directory: str, expected: str) -> bool:
        """Compare the computed content hash against *expected*.

        Returns:
            True if they match, False otherwise.
        """
        actual = self.compute_content_hash(directory)
        if actual != expected:
            logger.warning(
                "Content hash mismatch: expected %s, got %s", expected, actual
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------

    def install_pack(self, skills_source: str, pack_name: str) -> None:
        """Copy skill files into the workspace's ``.claude/skills/<pack_name>/``.

        Args:
            skills_source: Source directory containing skill subdirectories.
            pack_name: Name of the pack (used as the target directory name).
        """
        target = Path(self.workspace) / ".claude" / "skills" / pack_name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skills_source, str(target), dirs_exist_ok=True)

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def load_pack(self, pack: dict) -> bool:
        """Orchestrate the full load pipeline for a single pack.

        Steps:
            1. Clone the repo at the pinned commit.
            2. Verify the commit's GPG signature.
            3. Verify the content hash of the skills directory.
            4. Install the skills into the workspace.

        Returns:
            True if the pack was loaded successfully, False on any failure.
        """
        import tempfile

        pack_name = pack["name"]
        logger.info("Loading skill pack: %s", pack_name)

        with tempfile.TemporaryDirectory(prefix=f"skillpack-{pack_name}-") as tmpdir:
            clone_target = os.path.join(tmpdir, "repo")

            # 1. Clone
            try:
                self.clone_pack(pack, clone_target)
            except RuntimeError as exc:
                logger.error("Clone failed for %s: %s", pack_name, exc)
                return False

            # 2. Verify signature (warn but continue if integrity field is empty)
            signer = pack.get("signer", "")
            if signer:
                if not self.verify_commit_signature(
                    clone_target, pack["commit"], signer
                ):
                    logger.error(
                        "Signature verification failed for %s — skipping", pack_name
                    )
                    return False

            # 3. Verify content hash
            skills_path = os.path.join(clone_target, pack.get("path", "skills/"))
            integrity = pack.get("integrity", "")
            if integrity:
                if not self.verify_content_hash(skills_path, integrity):
                    logger.error("Content hash mismatch for %s — skipping", pack_name)
                    return False

            # 4. Install
            self.install_pack(skills_path, pack_name)
            logger.info("Skill pack %s installed successfully", pack_name)
            return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    """CLI entry point for the skill-pack loader init container."""
    parser = argparse.ArgumentParser(
        description="Load versioned skill packs into a sandbox workspace."
    )
    parser.add_argument(
        "--config",
        default="/etc/kagenti/skill-packs.yaml",
        help="Path to skill-packs.yaml manifest",
    )
    parser.add_argument(
        "--workspace",
        default="/workspace",
        help="Target workspace directory",
    )
    parser.add_argument(
        "--packs",
        nargs="*",
        default=None,
        help="Specific pack names to load (default: load packs with default=true)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    loader = SkillPackLoader(config_path=args.config, workspace=args.workspace)

    if args.packs:
        packs = loader.get_packs(args.packs)
        logger.info("Loading %d selected pack(s): %s", len(packs), args.packs)
    else:
        packs = loader.get_default_packs()
        logger.info(
            "Loading %d default pack(s): %s",
            len(packs),
            [p["name"] for p in packs],
        )

    results = {}
    for pack in packs:
        results[pack["name"]] = loader.load_pack(pack)

    # Summary
    succeeded = [n for n, ok in results.items() if ok]
    failed = [n for n, ok in results.items() if not ok]
    logger.info("Results: %d succeeded, %d failed", len(succeeded), len(failed))
    if failed:
        logger.error("Failed packs: %s", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
