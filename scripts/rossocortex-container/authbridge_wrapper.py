#!/usr/bin/env python3
"""rosscortex — Local AuthBridge proxy wrapper for credential injection without Kubernetes."""
from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader

ROSSCORTEX_VERSION = "0.1.0"
CONFIG_DIR = Path(os.environ.get("ROSSOCORTEX_CONFIG_DIR", Path.home() / ".config" / "rossocortex"))
SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = SCRIPT_DIR / "templates"
BIN_DIR = SCRIPT_DIR / "bin"
BUILD_INFO_PATH = SCRIPT_DIR / "BUILD_INFO.json"
PID_FILE = CONFIG_DIR / "rossocortex.pid"

DEFAULT_PORT = 3130
DEFAULT_REVERSE_PROXY_PORT = 18081
DEFAULT_TRANSPARENT_PORT = 18082
DEFAULT_SESSION_PORT = 19095
DEFAULT_STATS_PORT = 19096


def _find_kagenti_extensions() -> Path:
    env_dir = os.environ.get("KAGENTI_EXTENSIONS_DIR")
    if env_dir:
        return Path(env_dir)
    candidates = [
        SCRIPT_DIR.parent.parent.parent / "kagenti-extensions",
        Path.home() / "kagenti-extensions",
    ]
    for c in candidates:
        if (c / "authbridge" / "cmd" / "authbridge-proxy").is_dir():
            return c
    return candidates[0]


def _authbridge_binary() -> Path:
    return BIN_DIR / "authbridge-proxy"


def _load_build_info() -> dict | None:
    if BUILD_INFO_PATH.exists():
        return json.loads(BUILD_INFO_PATH.read_text())
    return None


@click.group()
def cli():
    """rosscortex — Local AuthBridge credential-injection proxy."""
    pass


@cli.command()
def version():
    """Show rosscortex version and authbridge-proxy build info."""
    click.echo(f"rosscortex {ROSSCORTEX_VERSION}")
    info = _load_build_info()
    if info:
        click.echo(f"authbridge-proxy: {info['authbridge_commit']} ({info['authbridge_repo']} {info['authbridge_branch']})")
        click.echo(f"go: {info.get('go_version', 'unknown')}")
        click.echo(f"built: {info['built_at']}")
    else:
        binary = _authbridge_binary()
        if binary.exists():
            click.echo(f"authbridge-proxy: binary at {binary} (no build info)")
        else:
            click.echo("authbridge-proxy: not built (run 'rosscortex build')")
    click.echo(f"config: {CONFIG_DIR}/")


@cli.command()
@click.option("--extensions-dir", type=click.Path(exists=True), help="Path to kagenti-extensions repo")
def build(extensions_dir: str | None):
    """Build authbridge-proxy from kagenti-extensions source."""
    ext_dir = Path(extensions_dir) if extensions_dir else _find_kagenti_extensions()
    authbridge_dir = ext_dir / "authbridge"
    plugin_dir = authbridge_dir / "authlib" / "plugins" / "placeholderresolve"

    if not authbridge_dir.is_dir():
        click.echo(f"ERROR: authbridge directory not found at {authbridge_dir}", err=True)
        click.echo(f"Set KAGENTI_EXTENSIONS_DIR or pass --extensions-dir", err=True)
        sys.exit(1)

    if not plugin_dir.is_dir():
        click.echo(f"WARNING: placeholderresolve plugin not found at {plugin_dir}", err=True)
        click.echo("The 'feat/placeholder-resolve-plugin' branch may not be merged.", err=True)
        click.echo("Attempting to fetch from huang195 fork...", err=True)
        _fetch_placeholder_plugin(ext_dir)
        if not plugin_dir.is_dir():
            click.echo("ERROR: Could not obtain placeholderresolve plugin.", err=True)
            sys.exit(1)

    budgettrack_dir = authbridge_dir / "authlib" / "plugins" / "litellm_budgettrack"
    budgettrack_reg = authbridge_dir / "cmd" / "authbridge-proxy" / "plugins_litellm_budgettrack.go"
    if not budgettrack_dir.is_dir():
        click.echo("Installing litellm_budgettrack plugin from rossocortex-container...")
        _install_litellm_budgettrack_plugin(ext_dir)

    go_version = _get_go_version()
    if not go_version:
        click.echo("ERROR: Go not found. Install Go 1.25+ from https://go.dev/dl/", err=True)
        sys.exit(1)

    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, cwd=ext_dir
    ).stdout.strip()

    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True, text=True, cwd=ext_dir
    ).stdout.strip() or "detached"

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    output = _authbridge_binary()

    ldflags = f"-s -w -X main.version=rosscortex-{commit}"
    env = {**os.environ, "CGO_ENABLED": "0", "GOOS": "darwin" if sys.platform == "darwin" else "linux", "GOARCH": "arm64" if platform.machine() == "arm64" else "amd64"}

    click.echo(f"Building authbridge-proxy from {ext_dir} (commit {commit})...")
    result = subprocess.run(
        ["go", "build", f"-ldflags={ldflags}", "-o", str(output), "./cmd/authbridge-proxy"],
        cwd=str(authbridge_dir), env=env,
    )
    if result.returncode != 0:
        click.echo("ERROR: Build failed.", err=True)
        sys.exit(1)

    remote_url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True, cwd=ext_dir
    ).stdout.strip()
    repo_name = remote_url.replace("git@github.com:", "").replace("https://github.com/", "").replace(".git", "")

    build_info = {
        "authbridge_commit": commit,
        "authbridge_repo": repo_name,
        "authbridge_branch": branch,
        "go_version": go_version,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rosscortex_version": ROSSCORTEX_VERSION,
        "platform": f"{env['GOOS']}/{env['GOARCH']}",
    }
    BUILD_INFO_PATH.write_text(json.dumps(build_info, indent=2) + "\n")

    click.echo(f"Built: {output}")
    click.echo(f"Commit: {commit} ({repo_name} {branch})")


@cli.command()
@click.option("--port", default=DEFAULT_PORT, help="Proxy listen port")
@click.option("--budget", default=0.0, type=float, help="Daily budget in USD (0 = disabled)")
@click.option("--force", is_flag=True, help="Overwrite existing CA and config")
def init(port: int, budget: float, force: bool):
    """Generate CA, credentials directory, and config.yaml."""
    ca_dir = CONFIG_DIR / "ca"
    credentials_dir = CONFIG_DIR / "credentials"
    config_file = CONFIG_DIR / "config.yaml"

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ca_dir.mkdir(parents=True, exist_ok=True)
    credentials_dir.mkdir(parents=True, exist_ok=True)

    ca_cert = ca_dir / "tls.crt"
    ca_key = ca_dir / "tls.key"

    if ca_cert.exists() and not force:
        click.echo(f"CA already exists at {ca_cert} (use --force to regenerate)")
    else:
        click.echo("Generating TLS-bridge CA certificate...")
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
            "-subj", "/CN=Rosscortex Local CA/O=kagenti",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout", str(ca_key), "-out", str(ca_cert),
        ], check=True, capture_output=True)
        ca_key.chmod(0o600)
        click.echo(f"  CA cert: {ca_cert}")
        click.echo(f"  CA key:  {ca_key}")

    for env_key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"):
        value = os.environ.get(env_key)
        if value:
            cred_file = credentials_dir / env_key
            if not cred_file.exists() or force:
                cred_file.write_text(value)
                cred_file.chmod(0o600)
                click.echo(f"  Credential: {env_key} -> {cred_file}")

    spend_file = CONFIG_DIR / "spend-authbridge.json"

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("config.yaml.j2")
    rendered = template.render(
        port=port,
        reverse_proxy_port=DEFAULT_REVERSE_PROXY_PORT,
        transparent_port=DEFAULT_TRANSPARENT_PORT,
        session_port=DEFAULT_SESSION_PORT,
        stats_port=DEFAULT_STATS_PORT,
        ca_dir=str(ca_dir),
        credentials_dir=str(credentials_dir),
        inference_parser=True,
        mcp_parser=True,
        budget_track=budget > 0,
        spend_file=str(spend_file),
        max_budget=budget,
    )

    if not config_file.exists() or force:
        config_file.write_text(rendered)
        click.echo(f"  Config: {config_file}")
    else:
        click.echo(f"Config already exists at {config_file} (use --force to overwrite)")

    click.echo(f"\nDone. Credentials directory: {credentials_dir}/")
    click.echo("Add credential files (one per key):")
    click.echo(f"  echo 'sk-ant-...' > {credentials_dir}/ANTHROPIC_AUTH_TOKEN")


@cli.command()
@click.option("--port", default=DEFAULT_PORT, help="Proxy listen port")
@click.option("--daemon", is_flag=True, help="Run in background")
@click.option("--config", "config_path", type=click.Path(), help="Custom config.yaml path")
def start(port: int, daemon: bool, config_path: str | None):
    """Start the authbridge-proxy."""
    binary = _authbridge_binary()
    if not binary.exists():
        click.echo("ERROR: authbridge-proxy not built. Run 'rosscortex build' first.", err=True)
        sys.exit(1)

    config_file = Path(config_path) if config_path else CONFIG_DIR / "config.yaml"
    if not config_file.exists():
        click.echo("ERROR: Config not found. Run 'rosscortex init' first.", err=True)
        sys.exit(1)

    ca_cert = CONFIG_DIR / "ca" / "tls.crt"
    if not ca_cert.exists():
        click.echo("ERROR: CA cert not found. Run 'rosscortex init' first.", err=True)
        sys.exit(1)

    creds_dir = CONFIG_DIR / "credentials"
    cred_files = list(creds_dir.iterdir()) if creds_dir.exists() else []
    click.echo(f"Credentials loaded: {[f.name for f in cred_files]}")

    import socket
    for check_port in (port, 8080):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", check_port)) == 0:
                click.echo(f"WARNING: port {check_port} is already in use.", err=True)
                if check_port == 8080:
                    click.echo("  authbridge-proxy requires :8080 for its reverse proxy listener.", err=True)
                    click.echo("  Kill the process using port 8080 and retry.", err=True)
                    sys.exit(1)

    cmd = [str(binary), "--config", str(config_file)]

    if daemon:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        PID_FILE.write_text(str(proc.pid))
        click.echo(f"rosscortex started (pid={proc.pid}, port={port})")
    else:
        click.echo(f"rosscortex proxy starting on :{port}")
        click.echo("")
        click.echo("For openshell sandboxes:")
        click.echo(f"  export OPENSHELL_EXTERNAL_PROXY=host.docker.internal:{port}")
        click.echo(f"  export OPENSHELL_EXTERNAL_CA={ca_cert}")
        click.echo("")
        click.echo("For podman/docker:")
        click.echo(f"  docker run -e HTTPS_PROXY=http://host.docker.internal:{port} \\")
        click.echo(f"    -v {ca_cert}:/etc/ssl/rosscortex-ca.crt:ro \\")
        click.echo(f"    -e NODE_EXTRA_CA_CERTS=/etc/ssl/rosscortex-ca.crt ...")
        click.echo("")
        click.echo("Press Ctrl+C to stop.")
        click.echo("---")

        proc = subprocess.Popen(cmd)
        PID_FILE.write_text(str(proc.pid))
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
        finally:
            PID_FILE.unlink(missing_ok=True)


@cli.command()
def stop():
    """Stop a running rosscortex daemon."""
    if not PID_FILE.exists():
        click.echo("No rosscortex daemon running (no pid file).")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Stopped rosscortex (pid={pid})")
    except ProcessLookupError:
        click.echo(f"Process {pid} not found (stale pid file)")
    PID_FILE.unlink(missing_ok=True)


@cli.command()
def status():
    """Show proxy status and loaded credentials."""
    binary = _authbridge_binary()
    click.echo(f"Binary: {'OK' if binary.exists() else 'NOT BUILT'} ({binary})")

    config_file = CONFIG_DIR / "config.yaml"
    click.echo(f"Config: {'OK' if config_file.exists() else 'NOT INITIALIZED'} ({config_file})")

    ca_cert = CONFIG_DIR / "ca" / "tls.crt"
    click.echo(f"CA: {'OK' if ca_cert.exists() else 'MISSING'} ({ca_cert})")

    creds_dir = CONFIG_DIR / "credentials"
    if creds_dir.exists():
        cred_files = sorted(creds_dir.iterdir())
        click.echo(f"Credentials ({len(cred_files)}):")
        for f in cred_files:
            click.echo(f"  {f.name}")
    else:
        click.echo("Credentials: NONE")

    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            click.echo(f"Proxy: RUNNING (pid={pid})")
        except ProcessLookupError:
            click.echo(f"Proxy: STOPPED (stale pid file)")
    else:
        click.echo("Proxy: STOPPED")


def _install_litellm_budgettrack_plugin(ext_dir: Path):
    """Copy the litellm_budgettrack plugin from rossocortex-container into kagenti-extensions."""
    import shutil
    src_plugin = SCRIPT_DIR.parent.parent.parent / "kagenti-extensions" / "authbridge" / "authlib" / "plugins" / "litellm_budgettrack"
    dst_plugin = ext_dir / "authbridge" / "authlib" / "plugins" / "litellm_budgettrack"
    dst_reg = ext_dir / "authbridge" / "cmd" / "authbridge-proxy" / "plugins_litellm_budgettrack.go"

    if src_plugin.is_dir():
        shutil.copytree(src_plugin, dst_plugin, dirs_exist_ok=True)
    else:
        click.echo(f"  WARNING: litellm_budgettrack source not found at {src_plugin}", err=True)
        return

    if not dst_reg.exists():
        dst_reg.write_text(
            '//go:build !exclude_plugin_litellm_budgettrack\n\n'
            'package main\n\n'
            'import _ "github.com/kagenti/kagenti-extensions/authbridge/authlib/plugins/litellm_budgettrack"\n'
        )

    click.echo("  Installed litellm_budgettrack plugin into kagenti-extensions.")


def _fetch_placeholder_plugin(ext_dir: Path):
    """Attempt to fetch the placeholder-resolve plugin from huang195 fork."""
    remotes = subprocess.run(
        ["git", "remote"], capture_output=True, text=True, cwd=ext_dir
    ).stdout.strip().split("\n")

    if "huang195" not in remotes:
        subprocess.run(
            ["git", "remote", "add", "huang195", "https://github.com/huang195/kagenti-extensions.git"],
            cwd=ext_dir, check=True
        )

    subprocess.run(
        ["git", "fetch", "huang195", "feat/placeholder-resolve-plugin"],
        cwd=ext_dir, check=True
    )
    subprocess.run(
        ["git", "checkout", "huang195/feat/placeholder-resolve-plugin", "--",
         "authbridge/authlib/plugins/placeholderresolve",
         "authbridge/cmd/authbridge-proxy/plugins_placeholderresolve.go"],
        cwd=ext_dir, check=True
    )
    click.echo("  Checked out placeholderresolve plugin from huang195 fork.")


def _get_go_version() -> str | None:
    try:
        result = subprocess.run(["go", "version"], capture_output=True, text=True)
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            return parts[2].removeprefix("go") if len(parts) >= 3 else "unknown"
    except FileNotFoundError:
        pass
    return None


if __name__ == "__main__":
    cli()
