#!/usr/bin/env python3
"""Sync all kagenti-teleport-setup files with the remote server pod.

Single script that handles the full lifecycle:
1. Check remote pod is available (health endpoint)
2. Compare all local files with remote using HTTP ETags (RFC 9110 Section 8.8)
3. If files differ: update ConfigMap, restart deployment
4. Verify all updates are reflected in the remote pod

Supports two channels:
- stable (default): fetches from GitHub kosh branch HEAD
- dev (--dev flag): uses local working tree files

Both channels coexist in the same ConfigMap. Dev files use a "dev--" key prefix.

Uses /checksums endpoint for efficient bulk comparison (one request returns
all file ETags). Individual files can also be checked via HEAD + If-None-Match
which returns 304 Not Modified if the file hasn't changed.

Usage:
    uv run kagenti/scripts/sync-kagenti-teleport-setup.py           # Sync stable from GitHub
    uv run kagenti/scripts/sync-kagenti-teleport-setup.py --dev     # Sync dev from local
    uv run kagenti/scripts/sync-kagenti-teleport-setup.py --status  # Check stable status
    uv run kagenti/scripts/sync-kagenti-teleport-setup.py --dev --status  # Check dev status
    uv run kagenti/scripts/sync-kagenti-teleport-setup.py --deploy  # Initial deploy
    uv run kagenti/scripts/sync-kagenti-teleport-setup.py --force   # Force redeploy
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
K8S_DIR = SCRIPT_DIR / "k8s"
SERVER_YAML = K8S_DIR / "kagenti-teleport-setup-server.yaml"
INDEX_HTML = K8S_DIR / "index.html"

NAMESPACE = "team1"
CONFIGMAP_NAME = "kagenti-teleport-setup"
DEPLOYMENT_NAME = "kagenti-teleport-setup"
ROUTE_NAME = "kagenti-teleport-setup"

DEFAULT_ROUTE_URL = "https://kagenti-teleport-setup-team1.apps.epoc002.ete14.res.ibm.com"

SERVED_FILES = [
    "kagenti-teleport-setup.py",
    "kosh.py",
    "teleport.sh",
    "sandbox.sh",
    "agent-sandbox.sb",
    "litellm_sandbox_policy.yaml",
    "setup-kosh-completions.sh",
    "bob-install.sh",
    "index.html",
]

DEV_FILE_PREFIX = "dev--"
GITHUB_REPO = "kagenti/kagenti"
GITHUB_BRANCH = "kosh"
GITHUB_SCRIPTS_PATH = "scripts"


# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------

def find_kubeconfig() -> str:
    if os.environ.get("KUBECONFIG"):
        return os.environ["KUBECONFIG"]
    repo_root = SCRIPT_DIR.parent.parent
    epoc_config = repo_root / ".kube" / "config-epoc"
    if epoc_config.exists():
        return str(epoc_config)
    home_config = pathlib.Path.home() / ".kube" / "config-epoc"
    if home_config.exists():
        return str(home_config)
    print("ERROR: Cannot find kubeconfig for EPOC cluster.", file=sys.stderr)
    print("  Set KUBECONFIG env var or place config at .kube/config-epoc", file=sys.stderr)
    sys.exit(1)


def find_kubectl() -> str:
    kubectl = shutil.which("kubectl") or shutil.which("oc")
    if not kubectl:
        print("ERROR: kubectl/oc not found in PATH", file=sys.stderr)
        sys.exit(1)
    return kubectl


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---------------------------------------------------------------------------
# GitHub fetch (for stable channel)
# ---------------------------------------------------------------------------

def fetch_github_commit_sha(branch: str = GITHUB_BRANCH) -> str | None:
    """Get latest commit SHA on the given branch via gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{GITHUB_REPO}/commits/{branch}", "--jq", ".sha"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def fetch_stable_files(tmp_dir: pathlib.Path) -> bool:
    """Download served files from GitHub kosh branch into tmp_dir.

    Returns True if at least kosh.py was downloaded successfully.
    """
    sha = fetch_github_commit_sha()
    if not sha:
        print("  ERROR: Could not fetch latest commit SHA from GitHub.", file=sys.stderr)
        print("  Make sure 'gh' CLI is installed and authenticated.", file=sys.stderr)
        return False

    print(f"  GitHub {GITHUB_REPO}@{GITHUB_BRANCH}: {sha[:12]}")
    ctx = ssl.create_default_context()

    fetched = 0
    for filename in SERVED_FILES:
        if filename == "index.html":
            src_path = f"scripts/k8s/index.html"
        else:
            src_path = f"{GITHUB_SCRIPTS_PATH}/{filename}"

        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{sha}/{src_path}"
        dst = tmp_dir / filename
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                dst.write_bytes(resp.read())
            fetched += 1
        except (urllib.error.URLError, OSError) as e:
            if filename == "kagenti-teleport-setup.py" or filename == "kosh.py":
                print(f"  ERROR: Failed to download {filename}: {e}", file=sys.stderr)
                return False
            print(f"  WARNING: Could not fetch {filename}: {e}")

    print(f"  Fetched {fetched} file(s) from GitHub")
    return True


# ---------------------------------------------------------------------------
# File resolution
# ---------------------------------------------------------------------------

def local_file_path(filename: str) -> pathlib.Path | None:
    """Resolve local path for a served filename."""
    if filename == "index.html":
        return INDEX_HTML if INDEX_HTML.exists() else None
    if filename == "setup.sh":
        p = K8S_DIR / "setup.sh"
        return p if p.exists() else None
    candidate = SCRIPT_DIR / filename
    return candidate if candidate.exists() else None


def compute_etag(filepath: pathlib.Path) -> str:
    """Compute strong ETag as quoted SHA-256 hex (RFC 9110 Section 8.8.3)."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f'"{h.hexdigest()}"'


# ---------------------------------------------------------------------------
# Step 1: Check remote pod is available
# ---------------------------------------------------------------------------

def check_pod_health(route_url: str) -> bool:
    """Check that the remote pod is reachable via /health endpoint."""
    url = f"{route_url}/health"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ssl_context(), timeout=10) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def get_route_url(kubectl: str, kubeconfig: str) -> str:
    result = subprocess.run(
        [kubectl, f"--kubeconfig={kubeconfig}", f"--namespace={NAMESPACE}",
         "get", "route", ROUTE_NAME, "-o", "jsonpath={.spec.host}"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0 and result.stdout:
        return f"https://{result.stdout}"
    return DEFAULT_ROUTE_URL


# ---------------------------------------------------------------------------
# Step 2: Compare files using HTTP ETags
# ---------------------------------------------------------------------------

def fetch_checksums(route_url: str, dev: bool = False) -> dict[str, str] | None:
    """GET /checksums or /dev/checksums → {filename: ETag}. Returns None if unreachable."""
    endpoint = "/dev/checksums" if dev else "/checksums"
    url = f"{route_url}{endpoint}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ssl_context(), timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        print(f"  {endpoint} unavailable: {e}", file=sys.stderr)
        return None


def compare_all(route_url: str, dev: bool = False,
                source_dir: pathlib.Path | None = None) -> tuple[list[str], list[str], list[str]]:
    """Compare all served files via /checksums.

    Returns (changed, missing_remote, missing_local).
    """
    remote_checksums = fetch_checksums(route_url, dev=dev)

    changed: list[str] = []
    missing_remote: list[str] = []
    missing_local: list[str] = []

    if remote_checksums is None:
        for f in SERVED_FILES:
            if source_dir:
                if (source_dir / f).exists():
                    changed.append(f)
            elif local_file_path(f):
                changed.append(f)
        return changed, missing_remote, missing_local

    for filename in SERVED_FILES:
        if source_dir:
            lpath = source_dir / filename
            if not lpath.exists():
                missing_local.append(filename)
                continue
        else:
            lpath = local_file_path(filename)
            if lpath is None:
                missing_local.append(filename)
                continue

        local_etag = compute_etag(lpath)
        remote_etag = remote_checksums.get(filename)

        if remote_etag is None:
            missing_remote.append(filename)
        elif local_etag != remote_etag:
            changed.append(filename)

    return changed, missing_remote, missing_local


# ---------------------------------------------------------------------------
# Step 3: Update ConfigMap + restart deployment
# ---------------------------------------------------------------------------

def update_configmap(kubectl: str, kubeconfig: str, dev: bool = False,
                     source_dir: pathlib.Path | None = None) -> bool:
    """Update content ConfigMap from served files.

    When dev=True, files are stored with "dev--" prefix in ConfigMap keys.
    When source_dir is provided, files are read from there instead of the default locations.
    Preserves existing keys from the other channel.
    """
    print("  Updating ConfigMap...")

    prefix = DEV_FILE_PREFIX if dev else ""

    from_file_args = []
    for filename in SERVED_FILES:
        if source_dir:
            lpath = source_dir / filename
            if not lpath.exists():
                continue
        else:
            lpath = local_file_path(filename)
            if not lpath:
                continue
        key = f"{prefix}{filename}"
        from_file_args.append(f"--from-file={key}={lpath}")

    if not from_file_args:
        print("  ERROR: No files found to sync", file=sys.stderr)
        return False

    # Fetch existing ConfigMap to preserve keys from the other channel
    get_result = subprocess.run(
        [kubectl, f"--kubeconfig={kubeconfig}", f"--namespace={NAMESPACE}",
         "get", "configmap", CONFIGMAP_NAME, "-o", "json"],
        capture_output=True, text=True, timeout=15,
    )

    existing_keys: dict[str, str] = {}
    if get_result.returncode == 0:
        try:
            cm_data = json.loads(get_result.stdout).get("data", {})
            for key, val in cm_data.items():
                # Keep keys from the OTHER channel
                if dev and not key.startswith(DEV_FILE_PREFIX):
                    existing_keys[key] = val
                elif not dev and key.startswith(DEV_FILE_PREFIX):
                    existing_keys[key] = val
        except (json.JSONDecodeError, KeyError):
            pass

    # Write preserved keys to temp files so we can include them in --from-file
    tmp_preserve_dir = pathlib.Path(tempfile.mkdtemp(prefix="kts-preserve-"))
    try:
        for key, val in existing_keys.items():
            tmp_file = tmp_preserve_dir / key
            tmp_file.write_text(val)
            from_file_args.append(f"--from-file={key}={tmp_file}")

        cmd = [
            kubectl, f"--kubeconfig={kubeconfig}", f"--namespace={NAMESPACE}",
            "create", "configmap", CONFIGMAP_NAME,
        ] + from_file_args + ["--dry-run=client", "-o", "yaml"]

        create_result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if create_result.returncode != 0:
            print(f"  ERROR: {create_result.stderr}", file=sys.stderr)
            return False

        apply_result = subprocess.run(
            [kubectl, f"--kubeconfig={kubeconfig}", f"--namespace={NAMESPACE}",
             "apply", "--server-side", "--force-conflicts", "-f", "-"],
            input=create_result.stdout, capture_output=True, text=True, timeout=30,
        )
        if apply_result.returncode != 0:
            print(f"  ERROR: {apply_result.stderr}", file=sys.stderr)
            return False
    finally:
        shutil.rmtree(tmp_preserve_dir, ignore_errors=True)

    channel = "dev" if dev else "stable"
    print(f"  ConfigMap updated ({len(from_file_args)} files, channel: {channel}).")
    return True


def restart_deployment(kubectl: str, kubeconfig: str) -> bool:
    print("  Restarting deployment...")
    result = subprocess.run(
        [kubectl, f"--kubeconfig={kubeconfig}", f"--namespace={NAMESPACE}",
         "rollout", "restart", f"deployment/{DEPLOYMENT_NAME}"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr}", file=sys.stderr)
        return False

    print("  Waiting for rollout...")
    result = subprocess.run(
        [kubectl, f"--kubeconfig={kubeconfig}", f"--namespace={NAMESPACE}",
         "rollout", "status", f"deployment/{DEPLOYMENT_NAME}", "--timeout=90s"],
        capture_output=True, text=True, timeout=100,
    )
    if result.returncode != 0:
        print(f"  WARNING: Rollout status: {result.stderr.strip()}", file=sys.stderr)
    else:
        print("  Deployment restarted.")
    return True


def deploy_all(kubectl: str, kubeconfig: str) -> bool:
    """Initial deployment: apply server YAML + create content ConfigMap."""
    print("=== Initial Deployment ===\n")

    if not SERVER_YAML.exists():
        print(f"ERROR: {SERVER_YAML} not found", file=sys.stderr)
        return False

    print("  Applying server manifests...")
    result = subprocess.run(
        [kubectl, f"--kubeconfig={kubeconfig}", f"--namespace={NAMESPACE}",
         "apply", "-f", str(SERVER_YAML)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr}", file=sys.stderr)
        return False
    print("  Server manifests applied.")

    if not update_configmap(kubectl, kubeconfig):
        return False

    print("  Waiting for rollout...")
    subprocess.run(
        [kubectl, f"--kubeconfig={kubeconfig}", f"--namespace={NAMESPACE}",
         "rollout", "status", f"deployment/{DEPLOYMENT_NAME}", "--timeout=90s"],
        capture_output=True, text=True, timeout=100,
    )
    return True


# ---------------------------------------------------------------------------
# Step 4: Verify all updates are reflected in remote pod
# ---------------------------------------------------------------------------

def verify_sync(route_url: str, dev: bool = False,
                source_dir: pathlib.Path | None = None, retries: int = 5) -> bool:
    """Verify all files match using /checksums after deployment."""
    channel = "dev" if dev else "stable"
    print(f"\n=== Verification ({channel}) ===\n")
    print("  Checking remote pod reflects all updates...")
    for attempt in range(retries):
        time.sleep(2)

        if not check_pod_health(route_url):
            print(f"    Attempt {attempt + 1}/{retries}: pod not ready...")
            continue

        changed, missing_remote, _ = compare_all(route_url, dev=dev, source_dir=source_dir)
        if not changed and not missing_remote:
            print("  VERIFIED: All remote files match (ETags identical).")
            return True

        remaining = changed + missing_remote
        print(f"    Attempt {attempt + 1}/{retries}: {len(remaining)} file(s) still differ...")

    print("  ERROR: Verification failed — remote does not match source", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def print_status(route_url: str) -> bool:
    """Print detailed sync status. Returns True if all in sync."""
    print("=== File Sync Status ===\n")
    print(f"  Route: {route_url}")
    print(f"  Method: HTTP ETag (RFC 9110 Section 8.8)\n")

    # Pod health
    healthy = check_pod_health(route_url)
    print(f"  Pod health: {'OK' if healthy else 'UNREACHABLE'}")
    if not healthy:
        print("  Cannot compare files — pod not reachable.")
        return False

    remote_checksums = fetch_checksums(route_url)
    if remote_checksums is None:
        print("  /checksums endpoint not available (old server version?).")
        return False

    print(f"\n  {'File':<35} {'Local ETag':<16} {'Remote ETag':<16} {'Status'}")
    print(f"  {'-'*35} {'-'*16} {'-'*16} {'-'*10}")

    all_synced = True
    for filename in SERVED_FILES:
        lpath = local_file_path(filename)
        if lpath is None:
            remote_short = remote_checksums.get(filename, "(missing)")
            if isinstance(remote_short, str) and len(remote_short) > 14:
                remote_short = remote_short[1:13] + "..."
            print(f"  {filename:<35} {'(no local)':<16} {remote_short:<16} SKIP")
            continue

        local_etag = compute_etag(lpath)
        remote_etag = remote_checksums.get(filename)

        local_short = local_etag[1:13] + "..."
        if remote_etag is None:
            remote_short = "(missing)"
            status = "MISSING"
            all_synced = False
        elif local_etag == remote_etag:
            remote_short = remote_etag[1:13] + "..."
            status = "OK"
        else:
            remote_short = remote_etag[1:13] + "..."
            status = "CHANGED"
            all_synced = False

        print(f"  {filename:<35} {local_short:<16} {remote_short:<16} {status}")

    print(f"\n  Overall: {'ALL IN SYNC' if all_synced else 'OUT OF SYNC'}")
    return all_synced


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync kagenti-teleport-setup files with remote pod (HTTP ETag comparison)",
    )
    parser.add_argument("--deploy", action="store_true",
                        help="Initial deploy (all manifests + ConfigMap)")
    parser.add_argument("--status", action="store_true",
                        help="Check sync status only (no changes)")
    parser.add_argument("--force", action="store_true",
                        help="Redeploy even if all files match")
    parser.add_argument("--dev", action="store_true",
                        help="Sync dev channel (files stored with dev-- prefix)")
    parser.add_argument("--github", action="store_true",
                        help="Fetch stable files from GitHub kosh branch (requires gh auth)")
    parser.add_argument("--tag", default=None,
                        help="Sync files from a git tag/ref (extracts to tmp dir, no checkout)")
    parser.add_argument("--url", default=None,
                        help="Override route URL")
    args = parser.parse_args()

    kubeconfig = find_kubeconfig()
    kubectl = find_kubectl()
    route_url = args.url or get_route_url(kubectl, kubeconfig)

    channel = "dev" if args.dev else "stable"
    print(f"  KUBECONFIG: {kubeconfig}")
    print(f"  Route URL: {route_url}")
    print(f"  Channel: {channel}\n")

    # --- Initial deploy ---
    if args.deploy:
        if not deploy_all(kubectl, kubeconfig):
            return 1
        if not verify_sync(route_url):
            return 1
        print(f"\n  DEPLOYED. URL: {route_url}/kagenti-teleport-setup.py")
        return 0

    # --- Step 1: Check pod availability ---
    print("=== Step 1: Check Remote Pod ===\n")
    healthy = check_pod_health(route_url)
    if healthy:
        print("  Pod is healthy.")
    else:
        print("  Pod not reachable.")
        if args.status:
            print("  Run with --deploy for initial setup.")
            return 1
        print("  Attempting to deploy...")
        if not deploy_all(kubectl, kubeconfig):
            return 1
        if not verify_sync(route_url):
            return 1
        print(f"\n  DEPLOYED. URL: {route_url}/kagenti-teleport-setup.py")
        return 0

    # --- Resolve source files ---
    # Both channels sync from local working tree.
    # Stable (default): writes files with plain keys (kosh.py)
    # Dev (--dev): writes files with dev-- prefix (dev--kosh.py)
    source_dir: pathlib.Path | None = None
    tmp_dir: pathlib.Path | None = None

    if args.tag:
        # Extract files from a git tag/ref without checking out
        tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="kts-tag-"))
        print(f"\n=== Extracting files from git ref '{args.tag}' ===\n")
        git_root = SCRIPT_DIR.parent  # kagenti/ is the git repo
        result = subprocess.run(
            ["git", "archive", "--format=tar", args.tag, "--", "scripts/"],
            cwd=str(git_root), capture_output=True,
        )
        if result.returncode != 0:
            print(f"  ERROR: git archive failed: {result.stderr.decode().strip()}", file=sys.stderr)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return 1
        import tarfile as _tarfile
        import io
        with _tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as tf:
            tf.extractall(path=str(tmp_dir))
        # Files are in tmp_dir/scripts/ — point source_dir there
        source_dir = tmp_dir / "scripts"
        if not source_dir.is_dir():
            print(f"  ERROR: no scripts/ directory in tag '{args.tag}'", file=sys.stderr)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return 1
        # Copy index.html from k8s/ subdir to source_dir for local_file_path() resolution
        tag_index = source_dir / "k8s" / "index.html"
        if tag_index.exists():
            shutil.copy2(str(tag_index), str(source_dir / "index.html"))
        tag_commit = subprocess.run(
            ["git", "log", "--oneline", "-1", args.tag],
            cwd=str(git_root), capture_output=True, text=True,
        ).stdout.strip()
        print(f"  Tag '{args.tag}' -> {tag_commit}")
        print(f"  Source dir: {source_dir}")

    elif args.github:
        # Fetch stable from GitHub kosh branch (requires gh auth)
        tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="kts-stable-"))
        print("\n=== Fetching stable from GitHub ===\n")
        if not fetch_stable_files(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return 1
        source_dir = tmp_dir

    try:
        # --- Step 2: Compare files ---
        print(f"\n=== Step 2: Compare Files ({channel}, HTTP ETag) ===\n")
        changed, missing_remote, missing_local = compare_all(
            route_url, dev=args.dev, source_dir=source_dir
        )

        if missing_local:
            print(f"  Skipping (no source file): {', '.join(missing_local)}")
        if not changed and not missing_remote:
            if args.force:
                print("  All files match, but --force specified.")
            else:
                print("  ALL IN SYNC. Nothing to do.")
                if not args.status:
                    url_path = "/dev/kagenti-teleport-setup.py" if args.dev else "/kagenti-teleport-setup.py"
                    print(f"  URL: {route_url}{url_path}")
                return 0

        if changed:
            print(f"  Changed: {', '.join(changed)}")
        if missing_remote:
            print(f"  Missing on remote: {', '.join(missing_remote)}")

        if args.status:
            print("\n  Run without --status to sync.")
            return 1

        # --- Step 3: Update ---
        print(f"\n=== Step 3: Update Remote Pod ({channel}) ===\n")
        if not update_configmap(kubectl, kubeconfig, dev=args.dev, source_dir=source_dir):
            return 1
        if not restart_deployment(kubectl, kubeconfig):
            return 1

        # --- Step 4: Verify ---
        if not verify_sync(route_url, dev=args.dev, source_dir=source_dir):
            return 1

        url_path = "/dev/kagenti-teleport-setup.py" if args.dev else "/kagenti-teleport-setup.py"
        print(f"\n  DONE. URL: {route_url}{url_path}")
        return 0
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
