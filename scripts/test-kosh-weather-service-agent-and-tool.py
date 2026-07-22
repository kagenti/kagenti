#!/usr/bin/env python3
"""Test: Deploy weather tool + agent via kosh CLI, verify, then clean up.

Replicates the weather-agent demo flow using kosh deploy commands:
1. Login to Kagenti
2. Deploy weather-tool (MCP tool from image)
3. Deploy weather-service (A2A agent from image)
4. Verify both appear in catalog
5. Undeploy both

Usage:
    uv run kagenti/scripts/test-kosh-weather-service-agent-and-tool.py
    uv run kagenti/scripts/test-kosh-weather-service-agent-and-tool.py --skip-cleanup
    uv run kagenti/scripts/test-kosh-weather-service-agent-and-tool.py --kagenti-url https://...

Environment variables:
    KAGENTI_URL          — Kagenti backend URL
    KAGENTI_KEYCLOAK_URL — Keycloak URL
    KAGENTI_USER         — Username (default: alice)
    KAGENTI_PASSWORD     — Password (default: alice123)
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import time

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
KOSH_PY = SCRIPT_DIR / "kosh.py"

DEFAULT_KAGENTI_URL = os.environ.get(
    "KAGENTI_URL",
    "https://kagenti-backend-kagenti-system.apps.epoc002.ete14.res.ibm.com",
)
DEFAULT_KEYCLOAK_URL = os.environ.get(
    "KAGENTI_KEYCLOAK_URL",
    "https://keycloak-keycloak.apps.epoc002.ete14.res.ibm.com",
)
DEFAULT_USER = os.environ.get("KAGENTI_USER", "dev-user")
DEFAULT_PASSWORD = os.environ.get("KAGENTI_PASSWORD", "UonNQPfcSmzPmDSP")

NAMESPACE = "team1"
TOOL_NAME = "weather-tool"
TOOL_IMAGE = "ghcr.io/kagenti/agent-examples/weather_tool:latest"
AGENT_NAME = "weather-service"
AGENT_IMAGE = "ghcr.io/kagenti/agent-examples/weather_service:latest"


def run_kosh(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run kosh.py with given arguments."""
    uv = shutil.which("uv")
    if not uv:
        print("ERROR: uv not found", file=sys.stderr)
        sys.exit(1)

    cmd = [uv, "run", str(KOSH_PY)] + args
    print(f"\n  $ kosh {' '.join(args)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            print(f"    [stderr] {line}")
    if check and result.returncode != 0:
        print(f"  FAILED (exit code {result.returncode})")
        sys.exit(1)
    return result


def step(num: int, description: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Step {num}: {description}")
    print(f"{'='*60}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Test weather agent/tool deployment via kosh")
    parser.add_argument("--kagenti-url", default=DEFAULT_KAGENTI_URL)
    parser.add_argument("--keycloak-url", default=DEFAULT_KEYCLOAK_URL)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--namespace", default=NAMESPACE)
    parser.add_argument("--skip-cleanup", action="store_true",
                        help="Don't undeploy after test")
    parser.add_argument("--cleanup-only", action="store_true",
                        help="Only undeploy (skip deploy)")
    args = parser.parse_args()

    print("=" * 60)
    print("  Weather Agent + Tool Deployment Test")
    print("=" * 60)
    print(f"  Kagenti URL:  {args.kagenti_url}")
    print(f"  Keycloak URL: {args.keycloak_url}")
    print(f"  User:         {args.user}")
    print(f"  Namespace:    {args.namespace}")

    # Step 1: Login
    step(1, "Login to Kagenti")
    run_kosh([
        "login",
        "--kagenti-url", args.kagenti_url,
        "--keycloak-url", args.keycloak_url,
        "--user", args.user,
        "--password", args.password,
    ])

    if args.cleanup_only:
        step(6, "Cleanup only — undeploy")
        run_kosh(["undeploy", "tool", "--name", TOOL_NAME, "-n", args.namespace, "--yes"],
                 check=False)
        run_kosh(["undeploy", "agent", "--name", AGENT_NAME, "-n", args.namespace, "--yes"],
                 check=False)
        print("\n  Cleanup done.")
        return 0

    # Step 2: Deploy weather tool
    step(2, f"Deploy tool '{TOOL_NAME}' from image")
    run_kosh([
        "deploy", "tool",
        "--name", TOOL_NAME,
        "--namespace", args.namespace,
        "--image", TOOL_IMAGE,
        "--protocol", "streamable_http",
        "--port", "8000",
        "--target-port", "8000",
    ])

    # Step 3: Deploy weather agent
    step(3, f"Deploy agent '{AGENT_NAME}' from image")
    run_kosh([
        "deploy", "agent",
        "--name", AGENT_NAME,
        "--namespace", args.namespace,
        "--image", AGENT_IMAGE,
        "--protocol", "a2a",
        "--framework", "LangGraph",
        "--port", "8080",
        "--target-port", "8000",
        "--authbridge",
        "--spire",
    ])

    # Step 4: Verify in catalog
    step(4, "Verify tool appears in catalog")
    result = run_kosh(["catalog", "tools", "-n", args.namespace])
    if TOOL_NAME not in result.stdout:
        print(f"  ERROR: '{TOOL_NAME}' not found in catalog output")
        return 1
    print(f"  OK: '{TOOL_NAME}' found in catalog")

    step(5, "Verify agent appears in catalog")
    result = run_kosh(["catalog", "agents", "-n", args.namespace])
    if AGENT_NAME not in result.stdout:
        print(f"  ERROR: '{AGENT_NAME}' not found in catalog output")
        return 1
    print(f"  OK: '{AGENT_NAME}' found in catalog")

    # Step 6: Cleanup
    if args.skip_cleanup:
        print("\n  --skip-cleanup: Leaving resources deployed.")
        print(f"  To clean up later: kosh undeploy agent --name {AGENT_NAME} -n {args.namespace}")
        print(f"                     kosh undeploy tool --name {TOOL_NAME} -n {args.namespace}")
    else:
        step(6, "Undeploy tool and agent")
        run_kosh(["undeploy", "tool", "--name", TOOL_NAME, "-n", args.namespace, "--yes"])
        run_kosh(["undeploy", "agent", "--name", AGENT_NAME, "-n", args.namespace, "--yes"])
        print("  Cleanup complete.")

    print("\n" + "=" * 60)
    print("  ALL STEPS PASSED")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
