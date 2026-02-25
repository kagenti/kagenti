#!/usr/bin/env python3
"""
Kagenti Agent Sandbox Launcher — nono Landlock enforcement (Phase 3, C3)

Applies kernel-level filesystem restrictions via Landlock before spawning
the agent process. Once applied, restrictions are IRREVERSIBLE — even if
the agent is compromised, it cannot access paths outside the allowed set.

Defense-in-depth layer:
  Layer 1: Kubernetes SecurityContext (non-root, caps dropped, read-only root)
  Layer 2: Runtime isolation (gVisor/Kata RuntimeClass, optional)
  Layer 3: THIS — nono Landlock (in-process kernel sandboxing)
  Layer 4: Application policy (settings.json allow/deny/HITL)

Hardcoded blocklist (nono enforces, cannot be overridden):
  ~/.ssh, ~/.kube, ~/.aws, /etc/shadow

Usage:
  python3 nono-launcher.py [agent-command...]
  python3 nono-launcher.py python3 -m agent_server
"""

import os
import subprocess
import sys


def apply_sandbox():
    """Apply Landlock filesystem restrictions. IRREVERSIBLE."""
    try:
        from nono_py import CapabilitySet, AccessMode, apply
    except ImportError:
        print(
            "WARNING: nono-py not installed. Running without Landlock enforcement.",
            file=sys.stderr,
        )
        print("         Install with: pip install nono-py", file=sys.stderr)
        return False

    caps = CapabilitySet()

    # System paths — read-only (required for process execution)
    for path in ["/usr", "/bin", "/lib", "/lib64", "/opt", "/etc"]:
        if os.path.exists(path):
            caps.allow_path(path, AccessMode.READ)

    # Python runtime paths
    for path in ["/usr/local/lib/python3.11", "/usr/local/bin"]:
        if os.path.exists(path):
            caps.allow_path(path, AccessMode.READ)

    # Workspace — read-write (where the agent operates)
    workspace = os.environ.get("WORKSPACE_DIR", "/workspace")
    if os.path.exists(workspace):
        caps.allow_path(workspace, AccessMode.READ_WRITE)

    # Temp directory — read-write
    if os.path.exists("/tmp"):
        caps.allow_path("/tmp", AccessMode.READ_WRITE)

    # /proc and /dev — read-only (needed for Python runtime)
    for path in ["/proc", "/dev"]:
        if os.path.exists(path):
            caps.allow_path(path, AccessMode.READ)

    # Apply — IRREVERSIBLE from this point
    apply(caps)
    return True


def main():
    # Apply Landlock sandbox
    sandboxed = apply_sandbox()
    if sandboxed:
        print("nono Landlock sandbox applied (irreversible)", file=sys.stderr)
    else:
        print("Running without Landlock (nono-py not available)", file=sys.stderr)

    # Spawn the agent command
    if len(sys.argv) > 1:
        cmd = sys.argv[1:]
    else:
        # Default: sleep (for testing)
        cmd = ["/bin/sh", "-c", "echo 'Sandbox ready'; sleep 36000"]

    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
