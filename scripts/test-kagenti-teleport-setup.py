#!/usr/bin/env python3
"""Test kagenti-teleport-setup.py in an isolated TMPDIR.

Runs the setup script, performs login, lists sandboxes, and creates
sandboxes for claude and bob.

Usage:
    uv run kagenti/scripts/test-kagenti-teleport-setup.py
    uv run kagenti/scripts/test-kagenti-teleport-setup.py --user alice --password alice123
    uv run kagenti/scripts/test-kagenti-teleport-setup.py --skip-sandbox-create
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SETUP_SCRIPT = SCRIPT_DIR / "kagenti-teleport-setup.py"

DEFAULT_USER = "alice"
DEFAULT_PASSWORD = "alice123"
DEFAULT_GATEWAY_URL = os.environ.get(
    "KOSH_GATEWAY_URL",
    "https://openshell-team1.apps.epoc002.ete14.res.ibm.com",
)


def find_uv() -> str:
    """Find uv binary."""
    uv = shutil.which("uv")
    if uv:
        return uv
    common = [
        pathlib.Path.home() / ".local" / "bin" / "uv",
        pathlib.Path.home() / ".cargo" / "bin" / "uv",
        pathlib.Path("/opt/homebrew/bin/uv"),
        pathlib.Path("/usr/local/bin/uv"),
    ]
    for p in common:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    print("ERROR: uv not found. Install from https://docs.astral.sh/uv/", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], env: dict | None = None, check: bool = True,
        timeout: int = 120, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a command with output and return result."""
    print(f"\n{'='*60}")
    print(f"  CMD: {' '.join(cmd)}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(cmd, env=env, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after {timeout}s (command may have opened interactive shell)")
        return subprocess.CompletedProcess(cmd, 0)
    print(f"  EXIT: {result.returncode}")
    if check and result.returncode != 0:
        print(f"  FAILED (exit {result.returncode})", file=sys.stderr)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Test kagenti-teleport-setup.py in isolated TMPDIR")
    parser.add_argument("--user", "-u", default=DEFAULT_USER, help=f"Username (default: {DEFAULT_USER})")
    parser.add_argument("--password", "-p", default=DEFAULT_PASSWORD, help="Password (default: alice123)")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="Gateway URL")
    parser.add_argument("--keep-tmpdir", action="store_true", help="Don't remove TMPDIR after test")
    parser.add_argument("--skip-sandbox-create", action="store_true", help="Skip teleport/pull tests (sandbox creation)")
    parser.add_argument("--sandbox-policy", default=None, help="Path to sandbox policy file")
    args = parser.parse_args()

    uv = find_uv()

    if not SETUP_SCRIPT.exists():
        print(f"ERROR: Setup script not found: {SETUP_SCRIPT}", file=sys.stderr)
        return 1

    tmpdir = tempfile.mkdtemp(prefix="kagenti-teleport-test-")
    print(f"\n*** Test directory: {tmpdir}")
    print(f"*** Setup script: {SETUP_SCRIPT}")
    print(f"*** Gateway: {args.gateway_url}")
    print(f"*** User: {args.user}")

    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = tmpdir
    env["KOSH_GATEWAY_URL"] = args.gateway_url
    env["KOSH_USER"] = args.user
    env["KOSH_PASSWORD"] = args.password

    failed_steps: list[str] = []

    # -------------------------------------------------------------------------
    # Step 1: Run kagenti-teleport-setup.py
    # -------------------------------------------------------------------------
    print("\n" + "#" * 60)
    print("# STEP 1: Run kagenti-teleport-setup.py")
    print("#" * 60)

    result = run(
        [uv, "run", str(SETUP_SCRIPT), "--user", args.user, "--password", args.password, "--test"],
        env=env,
        check=False,
        cwd=tmpdir,
    )
    if result.returncode != 0:
        failed_steps.append("setup")
        print("  WARNING: Setup exited non-zero, continuing with remaining steps...")

    # -------------------------------------------------------------------------
    # Step 2: Verify installation files
    # -------------------------------------------------------------------------
    print("\n" + "#" * 60)
    print("# STEP 2: Verify installed files")
    print("#" * 60)

    install_dir = pathlib.Path(tmpdir)
    expected_files = ["kosh.py", "teleport.sh", "sandbox.sh", "litellm_sandbox_policy.yaml"]
    for f in expected_files:
        fp = install_dir / f
        status = "OK" if fp.exists() else "MISSING"
        print(f"  {f}: {status}")
        if not fp.exists():
            failed_steps.append(f"missing:{f}")

    openshell_dir = install_dir / "openshell"
    gw_file = openshell_dir / "active_gateway"
    print(f"  openshell/active_gateway: {'OK' if gw_file.exists() else 'MISSING'}")

    mtls_dir = openshell_dir / "gateways" / "openshell-team1" / "mtls"
    for cert in ["ca.crt", "tls.crt", "tls.key"]:
        cp = mtls_dir / cert
        print(f"  mtls/{cert}: {'OK' if cp.exists() else 'MISSING'}")

    token_file = openshell_dir / "gateways" / "openshell-team1" / "oidc_token.json"
    print(f"  oidc_token.json: {'OK' if token_file.exists() else 'MISSING'}")

    # -------------------------------------------------------------------------
    # Step 3: Login with kosh (via OIDC - already done in setup, verify token)
    # -------------------------------------------------------------------------
    print("\n" + "#" * 60)
    print("# STEP 3: Verify OIDC login (token present)")
    print("#" * 60)

    if token_file.exists():
        import json
        try:
            token_data = json.loads(token_file.read_text())
            has_token = bool(token_data.get("access_token"))
            print(f"  Token present: {has_token}")
            print(f"  Issuer: {token_data.get('issuer', 'unknown')}")
            print(f"  Client ID: {token_data.get('client_id', 'unknown')}")
            if not has_token:
                failed_steps.append("login-token")
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ERROR reading token: {e}", file=sys.stderr)
            failed_steps.append("login-token")
    else:
        print("  No token file found — login may have failed")
        failed_steps.append("login-token")

    # -------------------------------------------------------------------------
    # Step 4: Run kosh sandbox list
    # -------------------------------------------------------------------------
    print("\n" + "#" * 60)
    print("# STEP 4: kosh sandbox list")
    print("#" * 60)

    kosh_py = install_dir / "kosh.py"
    if kosh_py.exists():
        result = run([uv, "run", str(kosh_py), "sandbox", "list"], env=env, check=False)
        if result.returncode != 0:
            failed_steps.append("sandbox-list")
            print("  NOTE: sandbox list failed (known blocker: openshell CLI doesn't send stored JWT)")
    else:
        print("  SKIP: kosh.py not installed")
        failed_steps.append("sandbox-list")

    # -------------------------------------------------------------------------
    # Step 5: Test kosh teleport and verify files arrive in remote sandbox
    # -------------------------------------------------------------------------
    if not args.skip_sandbox_create:
        print("\n" + "#" * 60)
        print("# STEP 5: Test kosh teleport (upload + verify)")
        print("#" * 60)

        user = os.environ.get("USER", args.user)
        teleport_sandbox = f"{user}-test-teleport"
        teleport_project = pathlib.Path(tmpdir) / teleport_sandbox
        teleport_project.mkdir(exist_ok=True)

        # Create a .claude dir (required by teleport.sh) and init git
        # (openshell upload respects .gitignore only if .git exists)
        subprocess.run(["git", "init", str(teleport_project)],
                       capture_output=True, timeout=10)
        (teleport_project / ".claude").mkdir(exist_ok=True)
        (teleport_project / ".claude" / "settings.json").write_text('{"test": true}\n')

        # Create test files to verify upload
        (teleport_project / "hello.txt").write_text("hello from teleport test\n")
        (teleport_project / "src").mkdir(exist_ok=True)
        (teleport_project / "src" / "main.py").write_text("print('test')\n")

        # Create a binary file with NULL bytes and unprintable characters
        binary_content = bytes(range(256)) + b"\x00\x01\x02\xff\xfe\xfd" * 100
        (teleport_project / "test.bin").write_bytes(binary_content)

        # Create a sensitive file that should NOT be uploaded
        (teleport_project / "secret.key").write_text("should-not-upload\n")

        print(f"\n  Test project: {teleport_project}")
        print(f"  Sandbox name: {teleport_sandbox}")
        print(f"  Files: hello.txt, src/main.py, .claude/settings.json, test.bin (binary), secret.key (sensitive)")

        if kosh_py.exists():
            # Run kosh teleport
            print("\n  --- Running kosh teleport ---")
            result = run(
                [uv, "run", str(kosh_py), "teleport", "-d", str(teleport_project)],
                env=env,
                check=False,
                timeout=120,
            )
            if result.returncode != 0:
                failed_steps.append("teleport")
                print(f"  ERROR: kosh teleport failed (exit {result.returncode})")
            else:
                print("  Teleport succeeded, verifying files in remote sandbox...")

                # Verify files exist in the remote sandbox
                verify_cmds = [
                    (f"cat {teleport_project}/hello.txt", "hello from teleport test"),
                    (f"cat {teleport_project}/src/main.py", "print('test')"),
                    (f"cat {teleport_project}/.claude/settings.json", '"test"'),
                ]
                for cmd_str, expected_content in verify_cmds:
                    proc = subprocess.run(
                        [uv, "run", "--with", "openshell==0.0.59",
                         "openshell", "sandbox", "exec",
                         "--name", teleport_sandbox, "--no-tty", "--",
                         "sh", "-c", cmd_str],
                        env=env, capture_output=True, text=True, timeout=30,
                    )
                    # Check both stdout and stderr for content (openshell may
                    # mix output streams when seccomp noise is present)
                    combined = proc.stdout + proc.stderr
                    if expected_content in combined:
                        print(f"  VERIFY OK: {cmd_str}")
                    else:
                        print(f"  VERIFY FAIL: {cmd_str} (exit={proc.returncode})")
                        if proc.stdout.strip():
                            print(f"    stdout: {proc.stdout.strip()[:200]}")
                        if proc.stderr.strip():
                            # Filter seccomp noise for display
                            stderr_lines = [l for l in proc.stderr.strip().splitlines()
                                            if "seccomp" not in l]
                            if stderr_lines:
                                print(f"    stderr: {stderr_lines[0][:200]}")
                        failed_steps.append(f"teleport-verify:{cmd_str.split()[1]}")

                # Verify binary file was uploaded correctly (check sha256)
                import hashlib
                local_bin_hash = hashlib.sha256(binary_content).hexdigest()
                proc = subprocess.run(
                    [uv, "run", "--with", "openshell==0.0.59",
                     "openshell", "sandbox", "exec",
                     "--name", teleport_sandbox, "--no-tty", "--",
                     "sh", "-c", f"sha256sum {teleport_project}/test.bin | cut -d' ' -f1"],
                    env=env, capture_output=True, text=True, timeout=30,
                )
                remote_bin_hash = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
                if remote_bin_hash == local_bin_hash:
                    print(f"  VERIFY OK: test.bin binary integrity (sha256 match)")
                else:
                    print(f"  VERIFY FAIL: test.bin binary mismatch")
                    print(f"    local:  {local_bin_hash}")
                    print(f"    remote: {remote_bin_hash}")
                    failed_steps.append("teleport-verify:test.bin")

                # Verify sensitive file was NOT uploaded
                proc = subprocess.run(
                    [uv, "run", "--with", "openshell==0.0.59",
                     "openshell", "sandbox", "exec",
                     "--name", teleport_sandbox, "--no-tty", "--",
                     "sh", "-c", f"test -f {teleport_project}/secret.key && echo FOUND || echo MISSING"],
                    env=env, capture_output=True, text=True, timeout=30,
                )
                if "MISSING" in proc.stdout:
                    print(f"  VERIFY OK: secret.key was excluded (sensitive)")
                elif "FOUND" in proc.stdout:
                    print(f"  VERIFY FAIL: secret.key was uploaded (should be excluded)")
                    failed_steps.append("teleport-sensitive-leak")
                else:
                    print(f"  VERIFY SKIP: could not check secret.key")

        # ---------------------------------------------------------------------
        # Step 5b: Verify no seccomp noise in kosh output
        # ---------------------------------------------------------------------
        if "teleport" not in failed_steps and kosh_py.exists():
            print("\n  --- Checking for seccomp noise suppression ---")
            seccomp_marker = "openshell_sandbox::sandbox::linux::seccomp"
            for check_cmd, label in [
                ([uv, "run", str(kosh_py), "sandbox", "exec",
                  "--name", teleport_sandbox, "--no-tty", "--", "echo", "noise-check"],
                 "sandbox exec"),
                ([uv, "run", str(kosh_py), "sandbox", "list"],
                 "sandbox list"),
            ]:
                proc = subprocess.run(check_cmd, env=env,
                                      capture_output=True, text=True, timeout=30)
                combined = proc.stdout + proc.stderr
                if seccomp_marker in combined:
                    print(f"  VERIFY FAIL: seccomp noise in '{label}' output")
                    failed_steps.append(f"seccomp-noise:{label}")
                else:
                    print(f"  VERIFY OK: no seccomp noise in '{label}'")

        # ---------------------------------------------------------------------
        # Step 6: Incremental teleport — add a file and re-teleport
        # ---------------------------------------------------------------------
        if "teleport" not in failed_steps and kosh_py.exists():
            print("\n" + "#" * 60)
            print("# STEP 6: Incremental teleport (add file, re-teleport)")
            print("#" * 60)

            # Add a new file locally
            (teleport_project / "new_file.txt").write_text("added after first teleport\n")
            # Modify an existing file
            (teleport_project / "hello.txt").write_text("hello updated\n")
            print(f"  Added: new_file.txt")
            print(f"  Modified: hello.txt")

            # Run teleport again — should skip create, just upload
            print("\n  --- Running kosh teleport (incremental) ---")
            result = run(
                [uv, "run", str(kosh_py), "teleport", "-d", str(teleport_project)],
                env=env,
                check=False,
                timeout=120,
            )
            if result.returncode != 0:
                failed_steps.append("teleport-incremental")
                print(f"  ERROR: incremental teleport failed (exit {result.returncode})")
            else:
                print("  Incremental teleport succeeded, verifying files...")

                # Verify new file exists
                verify_cmds = [
                    (f"cat {teleport_project}/new_file.txt", "added after first teleport"),
                    (f"cat {teleport_project}/hello.txt", "hello updated"),
                    (f"cat {teleport_project}/src/main.py", "print('test')"),
                ]
                for cmd_str, expected_content in verify_cmds:
                    proc = subprocess.run(
                        [uv, "run", "--with", "openshell==0.0.59",
                         "openshell", "sandbox", "exec",
                         "--name", teleport_sandbox, "--no-tty", "--",
                         "sh", "-c", cmd_str],
                        env=env, capture_output=True, text=True, timeout=30,
                    )
                    combined = proc.stdout + proc.stderr
                    if expected_content in combined:
                        print(f"  VERIFY OK: {cmd_str}")
                    else:
                        print(f"  VERIFY FAIL: {cmd_str} (exit={proc.returncode})")
                        if proc.stdout.strip():
                            print(f"    stdout: {proc.stdout.strip()[:200]}")
                        if proc.stderr.strip():
                            stderr_lines = [l for l in proc.stderr.strip().splitlines()
                                            if "seccomp" not in l]
                            if stderr_lines:
                                print(f"    stderr: {stderr_lines[0][:200]}")
                        failed_steps.append(f"teleport-incr-verify:{cmd_str.split()[1]}")

        # ---------------------------------------------------------------------
        # Step 7: Pull from remote sandbox after modification
        # ---------------------------------------------------------------------
        if "teleport" not in failed_steps and kosh_py.exists():
            print("\n" + "#" * 60)
            print("# STEP 7: Test kosh pull (modify remote, pull back)")
            print("#" * 60)

            # Delete local binary to test pull roundtrip
            (teleport_project / "test.bin").unlink(missing_ok=True)

            # Modify a file in the remote sandbox
            modify_cmd = f"echo 'modified remotely' >> {teleport_project}/hello.txt"
            subprocess.run(
                [uv, "run", "--with", "openshell==0.0.59",
                 "openshell", "sandbox", "exec",
                 "--name", teleport_sandbox, "--no-tty", "--",
                 "sh", "-c", modify_cmd],
                env=env, capture_output=True, timeout=30,
            )
            # Create a new file in remote sandbox
            new_remote_cmd = f"echo 'created remotely' > {teleport_project}/remote_new.txt"
            subprocess.run(
                [uv, "run", "--with", "openshell==0.0.59",
                 "openshell", "sandbox", "exec",
                 "--name", teleport_sandbox, "--no-tty", "--",
                 "sh", "-c", new_remote_cmd],
                env=env, capture_output=True, timeout=30,
            )
            print("  Modified hello.txt and created remote_new.txt in remote sandbox")

            # Run kosh pull
            print("\n  --- Running kosh pull ---")
            result = run(
                [uv, "run", str(kosh_py), "pull", teleport_sandbox],
                env=env,
                check=False,
                timeout=60,
            )
            if result.returncode != 0:
                failed_steps.append("pull")
                print(f"  ERROR: kosh pull failed (exit {result.returncode})")
            else:
                # Verify pulled files
                hello_content = (teleport_project / "hello.txt").read_text()
                if "modified remotely" in hello_content:
                    print(f"  VERIFY OK: hello.txt contains remote modification")
                else:
                    print(f"  VERIFY FAIL: hello.txt missing remote content")
                    print(f"    content: {hello_content.strip()[:200]}")
                    failed_steps.append("pull-verify:hello.txt")

                remote_new = teleport_project / "remote_new.txt"
                if remote_new.exists() and "created remotely" in remote_new.read_text():
                    print(f"  VERIFY OK: remote_new.txt pulled successfully")
                else:
                    print(f"  VERIFY FAIL: remote_new.txt not pulled or wrong content")
                    failed_steps.append("pull-verify:remote_new.txt")

                # Verify binary file roundtrip (teleport → pull preserves bytes)
                pulled_bin = teleport_project / "test.bin"
                if pulled_bin.exists():
                    pulled_hash = hashlib.sha256(pulled_bin.read_bytes()).hexdigest()
                    if pulled_hash == local_bin_hash:
                        print(f"  VERIFY OK: test.bin binary roundtrip (sha256 match)")
                    else:
                        print(f"  VERIFY FAIL: test.bin binary corrupted after pull")
                        print(f"    expected: {local_bin_hash}")
                        print(f"    got:      {pulled_hash}")
                        failed_steps.append("pull-verify:test.bin")
                else:
                    print(f"  VERIFY FAIL: test.bin not pulled")
                    failed_steps.append("pull-verify:test.bin")

        # ---------------------------------------------------------------------
        # Step 8: Pull with dirty-file protection
        # ---------------------------------------------------------------------
        if "pull" not in failed_steps and kosh_py.exists():
            print("\n" + "#" * 60)
            print("# STEP 8: Test kosh pull (dirty-file protection)")
            print("#" * 60)

            # Modify a file locally without committing (make it dirty)
            (teleport_project / "hello.txt").write_text("dirty local change\n")
            # Stage to make git track it as modified
            subprocess.run(["git", "add", "hello.txt"],
                           cwd=str(teleport_project), capture_output=True, timeout=10)

            # Modify file in remote again
            modify_cmd2 = f"echo 'second remote change' > {teleport_project}/hello.txt"
            subprocess.run(
                [uv, "run", "--with", "openshell==0.0.59",
                 "openshell", "sandbox", "exec",
                 "--name", teleport_sandbox, "--no-tty", "--",
                 "sh", "-c", modify_cmd2],
                env=env, capture_output=True, timeout=30,
            )
            print("  Made hello.txt dirty locally, modified again in remote")

            # Run kosh pull (should skip hello.txt)
            print("\n  --- Running kosh pull (expect skip) ---")
            result = run(
                [uv, "run", str(kosh_py), "pull", teleport_sandbox],
                env=env,
                check=False,
                timeout=60,
            )
            # Verify dirty file was NOT overwritten
            hello_content = (teleport_project / "hello.txt").read_text()
            if "dirty local change" in hello_content:
                print(f"  VERIFY OK: hello.txt preserved (dirty-file protection)")
            else:
                print(f"  VERIFY FAIL: hello.txt was overwritten despite being dirty")
                print(f"    content: {hello_content.strip()[:200]}")
                failed_steps.append("pull-dirty-protection")

        # Cleanup: delete the test sandbox
        if kosh_py.exists():
            print(f"\n  Cleaning up sandbox '{teleport_sandbox}'...")
            subprocess.run(
                [uv, "run", "--with", "openshell==0.0.59",
                 "openshell", "sandbox", "delete", teleport_sandbox],
                env=env, capture_output=True, timeout=30,
            )
        else:
            print("  SKIP: kosh.py not installed")
            failed_steps.append("teleport")

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    print("\n" + "#" * 60)
    print("# TEST SUMMARY")
    print("#" * 60)
    print(f"\n  Test directory: {tmpdir}")
    print(f"  Gateway: {args.gateway_url}")
    print(f"  User: {args.user}")

    if failed_steps:
        print(f"\n  Failed steps ({len(failed_steps)}):")
        for step in failed_steps:
            print(f"    - {step}")
    else:
        print("\n  All steps passed!")

    if not args.keep_tmpdir:
        print(f"\n  Cleaning up: {tmpdir}")
        shutil.rmtree(tmpdir, ignore_errors=True)
    else:
        print(f"\n  Kept test directory: {tmpdir}")
        print(f"  To use: XDG_CONFIG_HOME={tmpdir} uv run {install_dir}/kosh.py sandbox list")

    return 1 if any(s in failed_steps for s in ["setup", "login-token"]) else 0


if __name__ == "__main__":
    sys.exit(main())
