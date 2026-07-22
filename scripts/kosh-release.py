#!/usr/bin/env python3
"""Manage the kosh-release tag and sync stable channel.

Shows commits on the kosh branch, lets you pick which commit becomes the
kosh-release tag, then syncs the stable channel from that tag.

Usage:
    uv run kagenti/scripts/kosh-release.py                # Show status + commits
    uv run kagenti/scripts/kosh-release.py --set HEAD     # Tag current HEAD
    uv run kagenti/scripts/kosh-release.py --set abc123   # Tag specific commit
    uv run kagenti/scripts/kosh-release.py --sync         # Sync stable from current tag
    uv run kagenti/scripts/kosh-release.py --set HEAD --sync  # Tag + sync in one step
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
GIT_ROOT = SCRIPT_DIR.parent  # kagenti/ is the git repo
SYNC_SCRIPT = SCRIPT_DIR / "sync-kagenti-teleport-setup.py"
TAG_NAME = "kosh-release"


def git(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    cmd = ["git", *args]
    return subprocess.run(cmd, cwd=str(GIT_ROOT), capture_output=capture, text=True)


def get_tag_commit() -> str | None:
    result = git("rev-parse", "--short", TAG_NAME)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def get_tag_message() -> str:
    result = git("log", "--oneline", "-1", TAG_NAME)
    return result.stdout.strip() if result.returncode == 0 else "(not set)"


def get_branch_head() -> str:
    result = git("rev-parse", "--short", "HEAD")
    return result.stdout.strip()


def show_status() -> None:
    print(f"\n{'='*60}")
    print(f"  kosh-release tag management")
    print(f"{'='*60}\n")

    tag_commit = get_tag_commit()
    head = get_branch_head()

    if tag_commit:
        tag_msg = get_tag_message()
        print(f"  Current tag:  {tag_msg}")
        if tag_commit == head:
            print(f"  Status:       tag is at HEAD (up to date)")
        else:
            # Count commits between tag and HEAD
            result = git("rev-list", "--count", f"{TAG_NAME}..HEAD")
            ahead = result.stdout.strip() if result.returncode == 0 else "?"
            print(f"  Status:       HEAD is {ahead} commit(s) ahead of tag")
    else:
        print(f"  Current tag:  (not set)")
        print(f"  Status:       no kosh-release tag exists yet")

    print(f"\n  Recent commits on kosh branch:\n")
    result = git("log", "--oneline", "-10", "--decorate")
    for line in result.stdout.splitlines():
        marker = "  >>> " if tag_commit and line.startswith(tag_commit) else "      "
        print(f"{marker}{line}")
    print()


def set_tag(ref: str) -> bool:
    # Resolve ref
    result = git("rev-parse", "--short", ref)
    if result.returncode != 0:
        print(f"  ERROR: cannot resolve ref '{ref}'", file=sys.stderr)
        return False
    short = result.stdout.strip()

    # Get commit message for confirmation
    result = git("log", "--oneline", "-1", ref)
    commit_msg = result.stdout.strip()

    print(f"\n  Setting {TAG_NAME} -> {commit_msg}")

    # Check if tag already exists at this commit
    existing = get_tag_commit()
    if existing == short:
        print(f"  Tag already at this commit. No change needed.")
        return True

    # Move the tag
    result = git("tag", "-f", TAG_NAME, "-a", "-m",
                 f"Stable kosh release at {short}", ref)
    if result.returncode != 0:
        print(f"  ERROR: git tag failed: {result.stderr.strip()}", file=sys.stderr)
        return False

    print(f"  Tag updated.")
    print(f"\n  To push: git -C kagenti push origin {TAG_NAME} --force")
    return True


def sync_stable() -> int:
    tag_commit = get_tag_commit()
    if not tag_commit:
        print(f"  ERROR: no {TAG_NAME} tag exists. Set it first with --set", file=sys.stderr)
        return 1

    print(f"\n  Syncing stable channel from {TAG_NAME} ({get_tag_message()})...\n")

    result = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--tag", TAG_NAME],
        cwd=str(GIT_ROOT.parent),
    )
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage kosh-release tag and sync stable channel",
    )
    parser.add_argument("--set", metavar="REF", default=None,
                        help="Set kosh-release tag to this commit (e.g. HEAD, abc123)")
    parser.add_argument("--sync", action="store_true",
                        help="Sync stable channel from current kosh-release tag")
    parser.add_argument("--status", action="store_true",
                        help="Show status only (default if no flags given)")
    args = parser.parse_args()

    # Default: show status
    if not args.set and not args.sync:
        show_status()
        print("  Usage:")
        print(f"    kosh-release.py --set HEAD       # tag current commit as stable")
        print(f"    kosh-release.py --set <commit>   # tag specific commit as stable")
        print(f"    kosh-release.py --sync           # sync stable channel from tag")
        print(f"    kosh-release.py --set HEAD --sync  # tag + sync")
        print()
        return 0

    if args.set:
        if not set_tag(args.set):
            return 1

    if args.sync:
        return sync_stable()

    if args.set and not args.sync:
        print(f"\n  Run with --sync to deploy this to the stable channel.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
