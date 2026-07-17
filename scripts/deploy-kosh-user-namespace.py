#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Deploy an OpenShell tenant namespace on the ykt1 OpenShift cluster.

Creates the namespace, applies all required OpenShift fixes (SCC, CA bundle,
StorageClass), runs deploy-tenant.sh with correct parameters, and optionally
pre-authorizes a GitHub user in Keycloak before their first login.

Usage:
    uv run scripts/deploy-kosh-user-namespace.py <tenant-name>
    uv run scripts/deploy-kosh-user-namespace.py aslom
    uv run scripts/deploy-kosh-user-namespace.py aslom --github-user aslom
    uv run scripts/deploy-kosh-user-namespace.py aslom --dry-run
    uv run scripts/deploy-kosh-user-namespace.py aslom --gateway-image v0.0.56

Environment:
    KUBECONFIG: Path to kubeconfig (default: discovers .kube/config-ykt1)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CHART_DIR = REPO_ROOT / "charts" / "openshell"
DEPLOY_TENANT_SH = SCRIPT_DIR / "openshell" / "deploy-tenant.sh"

CLUSTER_DOMAIN = "apps.ykt1.hcp.res.ibm.com"
KEYCLOAK_NS = "keycloak"
OIDC_REALM = "openshell"


def run(cmd: list[str], check: bool = True, capture: bool = False, **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, check=check, capture_output=capture, text=True, **kwargs)


def kubectl(*args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["kubectl"] + list(args)
    return run(cmd, capture=capture, check=check)


def find_kubeconfig() -> str:
    if "KUBECONFIG" in os.environ:
        return os.environ["KUBECONFIG"]
    candidates = list(Path.cwd().glob(".kube/config-ykt1")) + list(Path.home().glob(".kube/config-ykt1"))
    for c in candidates:
        if c.exists():
            return str(c)
    sys.exit("ERROR: No kubeconfig found. Set KUBECONFIG or place .kube/config-ykt1 in project root.")


def ensure_namespace(tenant: str, dry_run: bool) -> None:
    result = kubectl("get", "namespace", tenant, capture=True, check=False)
    if result.returncode == 0:
        print(f"  Namespace {tenant} already exists")
        return
    print(f"  Creating namespace {tenant}...")
    if not dry_run:
        kubectl("create", "namespace", tenant)
        kubectl("label", "namespace", tenant,
                "pod-security.kubernetes.io/enforce=privileged",
                "pod-security.kubernetes.io/warn=privileged",
                "--overwrite")


def ensure_config_trusted_cabundle(tenant: str, dry_run: bool) -> None:
    """Create empty config-trusted-cabundle if not present (OpenShift CA operator may not inject it immediately)."""
    result = kubectl("get", "configmap", "config-trusted-cabundle", "-n", tenant, capture=True, check=False)
    if result.returncode == 0:
        print(f"  config-trusted-cabundle already exists in {tenant}")
        return
    print(f"  Creating empty config-trusted-cabundle in {tenant}...")
    if not dry_run:
        kubectl("create", "configmap", "config-trusted-cabundle", "-n", tenant)


def create_trusted_ca_bundle(tenant: str, dry_run: bool) -> None:
    """Combine system CA bundle + ingress operator CA into openshell-trusted-ca."""
    print(f"  Building openshell-trusted-ca for {tenant}...")
    if dry_run:
        print("  [dry-run] would create openshell-trusted-ca ConfigMap")
        return

    system_ca = kubectl("get", "configmap", "config-trusted-cabundle", "-n", tenant,
                        "-o", "jsonpath={.data.ca-bundle\\.crt}", capture=True, check=False).stdout or ""

    ingress_ca_b64 = kubectl("get", "secret", "router-ca", "-n", "openshift-ingress-operator",
                             "-o", "jsonpath={.data.tls\\.crt}", capture=True, check=False).stdout or ""
    ingress_ca = ""
    if ingress_ca_b64:
        import base64
        ingress_ca = base64.b64decode(ingress_ca_b64).decode()

    combined = system_ca + "\n" + ingress_ca
    proc = subprocess.run(
        ["kubectl", "create", "configmap", "openshell-trusted-ca", "-n", tenant,
         "--from-file=ca-bundle.crt=/dev/stdin", "--dry-run=client", "-o", "yaml"],
        input=combined, capture_output=True, text=True, check=True
    )
    subprocess.run(["kubectl", "apply", "-f", "-"], input=proc.stdout, check=True, text=True,
                   capture_output=True)
    print(f"  openshell-trusted-ca created/updated in {tenant}")


def grant_scc(tenant: str, dry_run: bool) -> None:
    """Grant anyuid SCC to openshell service accounts if needed."""
    sas = ["openshell-certgen", "openshell-gateway", "openshell-sandbox"]
    for sa in sas:
        result = kubectl("get", "sa", sa, "-n", tenant, capture=True, check=False)
        if result.returncode != 0:
            continue
        if not dry_run:
            run(["oc", "adm", "policy", "add-scc-to-user", "anyuid",
                 f"system:serviceaccount:{tenant}:{sa}"], check=False)
    print(f"  SCC grants applied for {tenant}")


def wait_for_keycloak(timeout: int = 120) -> bool:
    """Wait for Keycloak to be ready."""
    print("  Checking Keycloak readiness...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = kubectl("get", "pod", "keycloak-0", "-n", KEYCLOAK_NS,
                         "-o", "jsonpath={.status.containerStatuses[0].ready}",
                         capture=True, check=False)
        if result.stdout.strip() == "true":
            print("  Keycloak is ready")
            return True
        time.sleep(5)
    print("  WARNING: Keycloak not ready (gateway OIDC init will fail)")
    return False


def helm_deploy(tenant: str, dry_run: bool, gateway_image: str | None = None) -> bool:
    """Run helm install/upgrade for the tenant."""
    ingress_host = f"openshell-{tenant}.{CLUSTER_DOMAIN}"
    oidc_issuer = f"https://keycloak-{KEYCLOAK_NS}.{CLUSTER_DOMAIN}/realms/{OIDC_REALM}"

    cmd = [
        "helm", "upgrade", "--install", f"openshell-{tenant}",
        str(CHART_DIR),
        "--namespace", tenant,
        "--set", f"tenant={tenant}",
        "--set", "ingress.type=route",
        "--set", f"ingress.host={ingress_host}",
        "--set", f"oidc.issuer={oidc_issuer}",
        "--set", f"oidc.audience={tenant}",
        "--set", f"driver.namespace={tenant}",
        "--set", "trustedCABundle=openshell-trusted-ca",
        "--set", "openshift.enabled=true",
        "--timeout", "900s",
    ]
    if gateway_image:
        cmd += ["--set", f"images.gateway.tag={gateway_image}"]
    if dry_run:
        cmd += ["--dry-run"]
    else:
        cmd += ["--wait"]

    result = run(cmd, check=False)
    return result.returncode == 0


def restart_gateway(tenant: str, dry_run: bool) -> None:
    """Delete gateway pod to pick up new config."""
    if dry_run:
        print("  [dry-run] would restart gateway pod")
        return
    kubectl("delete", "pod", "openshell-server-0", "-n", tenant, check=False)
    print(f"  Restarted gateway pod in {tenant}")


def wait_for_gateway(tenant: str, timeout: int = 120) -> bool:
    """Wait for gateway to become ready."""
    print(f"  Waiting for gateway in {tenant}...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = kubectl("get", "pod", "openshell-server-0", "-n", tenant,
                         "-o", "jsonpath={.status.containerStatuses[?(@.name==\"gateway\")].ready}",
                         capture=True, check=False)
        if result.stdout.strip() == "true":
            print(f"  Gateway ready in {tenant}")
            return True
        time.sleep(5)
    print(f"  WARNING: Gateway not ready in {tenant} within {timeout}s")
    return False


def deploy_teleport_setup(tenant: str, dry_run: bool) -> bool:
    """Deploy kagenti-teleport-setup server (stable + dev channels) into tenant namespace."""
    sync_script = SCRIPT_DIR / "sync-kagenti-teleport-setup.py"
    if not sync_script.exists():
        print(f"  WARNING: {sync_script} not found — skipping teleport-setup deploy")
        return False

    env = os.environ.copy()
    env["OPENSHELL_NAMESPACE"] = tenant

    # Deploy stable channel
    print(f"  Deploying stable channel to namespace '{tenant}'...")
    if dry_run:
        print(f"  [dry-run] Would run: uv run {sync_script} --namespace {tenant} --deploy")
    else:
        result = run(
            ["uv", "run", str(sync_script), "--namespace", tenant, "--deploy"],
            check=False, capture=True, env=env,
        )
        if result.returncode != 0:
            # Fallback: try without --namespace flag (older versions use env var only)
            result = run(
                ["uv", "run", str(sync_script), "--deploy"],
                check=False, capture=True, env=env,
            )
        if result.returncode == 0:
            print(f"  Stable channel deployed")
        else:
            print(f"  WARNING: Stable deploy failed (exit {result.returncode})")
            if result.stderr:
                print(f"    {result.stderr[:200]}")
            return False

    # Deploy dev channel
    print(f"  Deploying dev channel to namespace '{tenant}'...")
    if dry_run:
        print(f"  [dry-run] Would run: uv run {sync_script} --namespace {tenant} --dev")
    else:
        result = run(
            ["uv", "run", str(sync_script), "--namespace", tenant, "--dev"],
            check=False, capture=True, env=env,
        )
        if result.returncode != 0:
            result = run(
                ["uv", "run", str(sync_script), "--dev"],
                check=False, capture=True, env=env,
            )
        if result.returncode == 0:
            print(f"  Dev channel deployed")
        else:
            print(f"  WARNING: Dev channel deploy failed (exit {result.returncode})")

    return True


def get_github_user_info(username: str) -> dict | None:
    """Retrieve GitHub user's numeric ID and profile via public API."""
    url = f"https://api.github.com/users/{username}"
    print(f"  Fetching GitHub profile for '{username}'...")
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            info = {
                "id": data["id"],
                "login": data["login"],
                "name": data.get("name", ""),
                "email": data.get("email", ""),
            }
            print(f"  GitHub user: login={info['login']} id={info['id']} name={info['name']}")
            return info
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  ERROR: GitHub user '{username}' not found")
        else:
            print(f"  ERROR: GitHub API returned HTTP {e.code}")
        return None
    except Exception as e:
        print(f"  ERROR: Failed to reach GitHub API: {e}")
        return None


def get_keycloak_admin_token(keycloak_url: str) -> str | None:
    """Get Keycloak admin token using credentials from cluster secret."""
    kc_user = kubectl("get", "secret", "keycloak-initial-admin", "-n", KEYCLOAK_NS,
                      "-o", "jsonpath={.data.username}", capture=True).stdout
    kc_pass = kubectl("get", "secret", "keycloak-initial-admin", "-n", KEYCLOAK_NS,
                      "-o", "jsonpath={.data.password}", capture=True).stdout
    import base64
    kc_user = base64.b64decode(kc_user).decode()
    kc_pass = base64.b64decode(kc_pass).decode()

    token_url = f"{keycloak_url}/realms/master/protocol/openid-connect/token"
    data = f"client_id=admin-cli&username={kc_user}&password={kc_pass}&grant_type=password"
    try:
        req = urllib.request.Request(token_url, data=data.encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())["access_token"]
    except Exception as e:
        print(f"  ERROR: Failed to get Keycloak admin token: {e}")
        return None


def keycloak_api(keycloak_url: str, token: str, method: str, path: str,
                 body: dict | None = None) -> tuple[int, dict | list | None]:
    """Make a Keycloak Admin REST API call. Returns (status_code, response_json)."""
    url = f"{keycloak_url}/admin/realms/{OIDC_REALM}{path}"
    req_data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=req_data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
            return resp.status, json.loads(content) if content else None
    except urllib.error.HTTPError as e:
        content = e.read()
        return e.code, json.loads(content) if content else None
    except Exception as e:
        print(f"  ERROR: Keycloak API call failed: {e}")
        return 0, None


def preauthorize_github_user(github_username: str, dry_run: bool) -> bool:
    """Pre-authorize a GitHub user in Keycloak before their first login.

    Steps:
    1. Get GitHub numeric user ID from public API
    2. Create user in Keycloak openshell realm (if not exists)
    3. Add user to openshell-users group
    4. Link GitHub IdP to the user account
    """
    gh_info = get_github_user_info(github_username)
    if not gh_info:
        return False

    if dry_run:
        print(f"  [dry-run] Would pre-authorize GitHub user '{github_username}' (id={gh_info['id']})")
        return True

    keycloak_url = f"https://keycloak-{KEYCLOAK_NS}.{CLUSTER_DOMAIN}"
    print(f"  Keycloak URL: {keycloak_url}")

    token = get_keycloak_admin_token(keycloak_url)
    if not token:
        return False
    print("  Admin token obtained")

    # Check if user already exists
    status, users = keycloak_api(keycloak_url, token, "GET",
                                  f"/users?username={github_username}&exact=true")
    if status != 200:
        print(f"  ERROR: Failed to query users (HTTP {status})")
        return False

    user_id = None
    if users:
        user_id = users[0]["id"]
        print(f"  User '{github_username}' already exists (id: {user_id[:8]}...)")
    else:
        # Create user
        first_name = gh_info["name"].split()[0] if gh_info["name"] else github_username
        last_name = " ".join(gh_info["name"].split()[1:]) if gh_info["name"] else ""
        user_payload = {
            "username": github_username,
            "enabled": True,
            "firstName": first_name,
            "lastName": last_name,
            "email": gh_info["email"] or f"{github_username}@users.noreply.github.com",
            "emailVerified": True,
        }
        status, resp = keycloak_api(keycloak_url, token, "POST", "/users", user_payload)
        if status == 201:
            print(f"  User '{github_username}' created in Keycloak")
            # Fetch the created user's ID
            status, users = keycloak_api(keycloak_url, token, "GET",
                                          f"/users?username={github_username}&exact=true")
            if users:
                user_id = users[0]["id"]
        elif status == 409:
            print(f"  User '{github_username}' already exists (conflict)")
            status, users = keycloak_api(keycloak_url, token, "GET",
                                          f"/users?username={github_username}&exact=true")
            if users:
                user_id = users[0]["id"]
        else:
            print(f"  ERROR: Failed to create user (HTTP {status}): {resp}")
            return False

    if not user_id:
        print("  ERROR: Could not determine user ID")
        return False

    # Find openshell-users group
    status, groups = keycloak_api(keycloak_url, token, "GET",
                                   "/groups?search=openshell-users&exact=true")
    group_id = None
    if status == 200 and groups:
        for g in groups:
            if g["name"] == "openshell-users":
                group_id = g["id"]
                break

    if not group_id:
        print("  WARNING: 'openshell-users' group not found — run kosh-github-keycloak-setup.sh first")
    else:
        # Add user to group
        status, _ = keycloak_api(keycloak_url, token, "PUT",
                                  f"/users/{user_id}/groups/{group_id}")
        if status == 204:
            print(f"  User added to 'openshell-users' group")
        elif status == 409:
            print(f"  User already in 'openshell-users' group")
        else:
            print(f"  WARNING: Failed to add user to group (HTTP {status})")

    # Link GitHub IdP
    idp_link = {
        "identityProvider": "github",
        "userId": str(gh_info["id"]),
        "userName": github_username,
    }
    status, _ = keycloak_api(keycloak_url, token, "POST",
                              f"/users/{user_id}/federated-identity/github", idp_link)
    if status == 204:
        print(f"  GitHub IdP linked (provider user id: {gh_info['id']})")
    elif status == 409:
        print(f"  GitHub IdP link already exists")
    else:
        print(f"  WARNING: Failed to link GitHub IdP (HTTP {status})")

    print(f"  Pre-authorization complete for '{github_username}'")
    return True


def cleanup_tenant(tenant: str, dry_run: bool) -> int:
    """Remove an OpenShell tenant: Helm release, Keycloak user, and namespace."""
    print(f"\n{'='*60}")
    print(f"  OpenShell Tenant Cleanup: {tenant}")
    print(f"  Dry run: {dry_run}")
    print(f"{'='*60}\n")

    # 1. Uninstall Helm release
    print("[1/4] Uninstall Helm release")
    result = run(["helm", "list", "-n", tenant, "-q"], capture=True, check=False)
    releases = result.stdout.strip().splitlines() if result.returncode == 0 else []
    helm_release = f"openshell-{tenant}"
    if helm_release in releases:
        if dry_run:
            print(f"  [dry-run] Would uninstall Helm release '{helm_release}'")
        else:
            run(["helm", "uninstall", helm_release, "-n", tenant], check=False)
            print(f"  Helm release '{helm_release}' uninstalled")
    else:
        print(f"  No Helm release '{helm_release}' found")

    # 2. Remove Keycloak user (same name as tenant)
    print("\n[2/4] Remove Keycloak user")
    keycloak_url = f"https://keycloak-{KEYCLOAK_NS}.{CLUSTER_DOMAIN}"
    if dry_run:
        print(f"  [dry-run] Would remove Keycloak user '{tenant}' from realm '{OIDC_REALM}'")
    else:
        token = get_keycloak_admin_token(keycloak_url)
        if token:
            status, users = keycloak_api(keycloak_url, token, "GET",
                                          f"/users?username={tenant}&exact=true")
            if status == 200 and users:
                user_id = users[0]["id"]
                del_status, _ = keycloak_api(keycloak_url, token, "DELETE", f"/users/{user_id}")
                if del_status == 204:
                    print(f"  Keycloak user '{tenant}' deleted")
                else:
                    print(f"  WARNING: Failed to delete Keycloak user (HTTP {del_status})")
            else:
                print(f"  Keycloak user '{tenant}' not found (nothing to delete)")
        else:
            print("  WARNING: Could not get Keycloak admin token — skipping user cleanup")

    # 3. Delete OpenShift Route (if lingering)
    print("\n[3/4] Delete Route")
    route_name = f"openshell-{tenant}"
    result = kubectl("get", "route", route_name, "-n", tenant, capture=True, check=False)
    if result.returncode == 0:
        if dry_run:
            print(f"  [dry-run] Would delete route '{route_name}'")
        else:
            kubectl("delete", "route", route_name, "-n", tenant, check=False)
            print(f"  Route '{route_name}' deleted")
    else:
        print(f"  No route '{route_name}' found")

    # 4. Delete namespace
    print("\n[4/4] Delete namespace")
    result = kubectl("get", "namespace", tenant, capture=True, check=False)
    if result.returncode == 0:
        if dry_run:
            print(f"  [dry-run] Would delete namespace '{tenant}'")
        else:
            kubectl("delete", "namespace", tenant)
            print(f"  Namespace '{tenant}' deleted")
    else:
        print(f"  Namespace '{tenant}' does not exist")

    print(f"\n{'='*60}")
    print(f"  Cleanup complete for tenant '{tenant}'")
    print(f"{'='*60}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy OpenShell tenant on ykt1 OpenShift cluster")
    parser.add_argument("tenant", help="Tenant/namespace name (e.g., aslom, team1)")
    parser.add_argument("--cleanup", action="store_true", help="Remove tenant: uninstall Helm, delete Keycloak user, delete namespace")
    parser.add_argument("--github-user", help="GitHub username to pre-authorize (creates Keycloak user, adds to group, links IdP)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without executing")
    parser.add_argument("--gateway-image", help="Override gateway image tag (e.g., v0.0.56)")
    parser.add_argument("--skip-keycloak-check", action="store_true", help="Skip Keycloak readiness check")
    parser.add_argument("--skip-helm", action="store_true", help="Only do pre-requisite fixes, skip helm deploy")
    parser.add_argument("--skip-teleport", action="store_true", help="Skip deploying kagenti-teleport-setup server")
    args = parser.parse_args()

    kubeconfig = find_kubeconfig()
    os.environ["KUBECONFIG"] = kubeconfig

    if args.cleanup:
        return cleanup_tenant(args.tenant, args.dry_run)

    print(f"\n{'='*60}")
    print(f"  OpenShell Tenant Deploy: {args.tenant}")
    print(f"  Cluster: {CLUSTER_DOMAIN}")
    print(f"  KUBECONFIG: {kubeconfig}")
    print(f"  Dry run: {args.dry_run}")
    print(f"{'='*60}\n")

    print("[1/8] Ensure namespace exists")
    ensure_namespace(args.tenant, args.dry_run)

    print("\n[2/8] Ensure config-trusted-cabundle ConfigMap")
    ensure_config_trusted_cabundle(args.tenant, args.dry_run)

    print("\n[3/8] Create combined trusted CA bundle")
    create_trusted_ca_bundle(args.tenant, args.dry_run)

    print("\n[4/8] Check Keycloak readiness")
    if not args.skip_keycloak_check:
        kc_ready = wait_for_keycloak(timeout=30)
        if not kc_ready:
            print("  Keycloak is not ready. Gateway will CrashLoop until it recovers.")
            print("  Continuing with deployment (gateway will self-heal when Keycloak is back).")
    else:
        print("  Skipped")

    if args.skip_helm:
        print("\n[5/8] Helm deploy — SKIPPED (--skip-helm)")
        print("\n[6/8] Gateway readiness — SKIPPED")

        if not args.skip_teleport:
            print("\n[7/8] Deploy kagenti-teleport-setup server")
            deploy_teleport_setup(args.tenant, args.dry_run)
        else:
            print("\n[7/8] Teleport setup — SKIPPED (--skip-teleport)")

        if args.github_user:
            print("\n[8/8] Pre-authorize GitHub user in Keycloak")
            preauthorize_github_user(args.github_user, args.dry_run)

        teleport_stable = f"https://kagenti-teleport-setup-{args.tenant}.{CLUSTER_DOMAIN}/kagenti-teleport-setup.py"
        teleport_dev = f"https://kagenti-teleport-setup-{args.tenant}.{CLUSTER_DOMAIN}/dev/kagenti-teleport-setup.py"
        print(f"\nPre-requisites applied. Run deploy-tenant.sh manually:")
        print(f"  {DEPLOY_TENANT_SH} {args.tenant}")
        print(f"\n  Teleport setup (stable): {teleport_stable}")
        print(f"  Teleport setup (dev):    {teleport_dev}")
        return 0

    print("\n[5/8] Helm install/upgrade")
    success = helm_deploy(args.tenant, args.dry_run, args.gateway_image)
    if not success and not args.dry_run:
        print("  Helm failed — attempting cleanup of stale certgen job and retry...")
        kubectl("delete", "job", "openshell-certgen", "-n", args.tenant, check=False)
        success = helm_deploy(args.tenant, args.dry_run, args.gateway_image)

    if not success and not args.dry_run:
        print("\n  ERROR: Helm deployment failed. Check logs:")
        print(f"    kubectl logs openshell-server-0 -n {args.tenant} -c gateway")
        return 1

    print("\n[6/8] Verify gateway readiness")
    if not args.dry_run:
        gw_ready = wait_for_gateway(args.tenant, timeout=90)
        if not gw_ready:
            print(f"\n  Gateway not ready. Common causes:")
            print(f"    - Keycloak down: kubectl get pods -n {KEYCLOAK_NS}")
            print(f"    - CA bundle issue: kubectl logs openshell-server-0 -n {args.tenant} -c gateway")
            return 1

    if not args.skip_teleport:
        print("\n[7/8] Deploy kagenti-teleport-setup server")
        deploy_teleport_setup(args.tenant, args.dry_run)
    else:
        print("\n[7/8] Teleport setup — SKIPPED (--skip-teleport)")

    if args.github_user:
        print("\n[8/8] Pre-authorize GitHub user in Keycloak")
        preauthorize_github_user(args.github_user, args.dry_run)
    else:
        print("\n[8/8] GitHub user pre-authorization — SKIPPED (no --github-user)")

    teleport_stable = f"https://kagenti-teleport-setup-{args.tenant}.{CLUSTER_DOMAIN}/kagenti-teleport-setup.py"
    teleport_dev = f"https://kagenti-teleport-setup-{args.tenant}.{CLUSTER_DOMAIN}/dev/kagenti-teleport-setup.py"

    print(f"\n{'='*60}")
    print(f"  Deployment complete!")
    print(f"  Gateway:                 https://openshell-{args.tenant}.{CLUSTER_DOMAIN}")
    print(f"  OIDC:                    https://keycloak-{KEYCLOAK_NS}.{CLUSTER_DOMAIN}/realms/{OIDC_REALM}")
    print(f"  Teleport setup (stable): {teleport_stable}")
    print(f"  Teleport setup (dev):    {teleport_dev}")
    if args.github_user:
        print(f"  GitHub user:             {args.github_user} (pre-authorized)")
    print(f"\n  User setup command (GitHub login — opens browser):")
    print(f"    uv run {teleport_stable} --tenant {args.tenant}")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
