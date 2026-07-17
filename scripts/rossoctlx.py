#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "jinja2>=3.1"]
# ///
"""rossoctlx — CLI to manage a running rossocortex proxy.

Usage:
    ./rossoctlx.py version
    ./rossoctlx.py version --control-url http://localhost:8181
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROSSOCTL_VERSION = "0.2.2"  # keep in sync with scripts/pyproject.toml [project].version
DEFAULT_CONTROL_URL = "http://localhost:8181"
DEFAULT_PROXY_PORT = 8185
_xdg_config = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
CONFIG_DIR = Path(os.environ.get("ROSSOCORTEX_CONFIG_DIR", str(Path(_xdg_config) / "rossocortex")))
AGENTS_FILE = CONFIG_DIR / "agents.json"
AGENTS_DIR = CONFIG_DIR / "agents"
_local_dir_env = os.environ.get("ROSSOCORTEX_CONTAINER_LOCAL_DIR")
ROSSOCORTEX_CONTAINER_DIR = Path(_local_dir_env) if _local_dir_env else Path(__file__).resolve().parent / "rossocortex-container"
TEMPLATES_DIR = ROSSOCORTEX_CONTAINER_DIR / "templates"
AGENT_PORT_BASE = 13000
PORTS_PER_AGENT = 5
ROSSOCORTEX_SCRIPT = ROSSOCORTEX_CONTAINER_DIR / "rossocortex.py"
PID_FILE = CONFIG_DIR / "rossocortex.pid"
STATE_FILE = CONFIG_DIR / "rossocortex-state.json"

# Fallback copy of rossocortex-container/templates/config.yaml.j2, used when the
# on-disk template is not present (e.g. installed as a standalone pip package with
# only rossoctlx.py shipped). Keep in sync with the file in rossocortex-container/.
EMBEDDED_AGENT_CONFIG_TEMPLATE = """\
mode: proxy-sidecar

listener:
  reverse_proxy_addr: ":{{ reverse_proxy_port }}"
  forward_proxy_addr: "0.0.0.0:{{ port }}"
  transparent_proxy_addr: ":{{ transparent_port }}"
  reverse_proxy_backend: "http://127.0.0.1:1"
  session_api_addr: ":{{ session_port }}"

tls_bridge:
  mode: enabled
  ca_dir: {{ ca_dir }}
  ports: [443]

session:
  enabled: true

stats:
  address: ":{{ stats_port }}"

pipeline:
  outbound:
    plugins:
      - name: placeholder-resolve
        config:
          source: secret_dir
          secret_dir: {{ credentials_dir }}
{% if inference_parser %}
      - name: inference-parser
{% endif %}
{% if mcp_parser %}
      - name: mcp-parser
{% endif %}
  inbound:
    plugins:
{% if budget_track %}
      - name: litellm-budget-track
        config:
          spend_file: {{ spend_file }}
          max_budget: {{ max_budget }}
{% endif %}
"""


def _is_running() -> int | str | None:
    """Return PID (int) or container ID (str) if rossocortex is running, None otherwise."""
    if not PID_FILE.exists():
        return None
    content = PID_FILE.read_text().strip()
    if content.startswith("container:"):
        container_id = content.split(":", 1)[1]
        import subprocess as sp
        runtime = _find_container_runtime()
        if runtime:
            result = sp.run([runtime, "ps", "-q", "-f", f"name={CONTAINER_NAME}"], capture_output=True, text=True)
            if result.stdout.strip():
                return f"container:{container_id}"
        PID_FILE.unlink(missing_ok=True)
        return None
    try:
        pid = int(content)
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return None


def _save_state(port: int, control_port: int, pid: int, upstream: str, mode: str, **extra):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "pid": pid, "port": port, "control_port": control_port,
        "upstream": upstream, "mode": mode,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    state.update({k: v for k, v in extra.items() if v is not None})
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _port_is_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _find_free_port(start: int, count: int = 2) -> list[int]:
    """Find `count` consecutive free ports starting from `start`."""
    ports = []
    candidate = start
    while len(ports) < count:
        if _port_is_free(candidate):
            ports.append(candidate)
        else:
            ports.clear()
        candidate += 1
        if candidate > start + 100:
            break
    return ports


def _diagnose_start_failure(port: int, control_port: int, upstream: str, no_authbridge: bool, output: str, returncode: int):
    """Analyze rossocortex startup failure and print root cause."""
    import os
    print(f"\n--- Diagnosis ---", file=sys.stderr)
    print(f"  {_config_dir_note()}", file=sys.stderr)

    if output.strip():
        print(f"Process output:", file=sys.stderr)
        for line in output.strip().splitlines()[-20:]:
            print(f"  {line}", file=sys.stderr)
        print(file=sys.stderr)

    if "No module named" in output:
        module = output.split("No module named")[-1].strip().strip("'\"")
        print(f"Root cause: Missing Python dependency '{module}'", file=sys.stderr)
        print(f"  Fix: uv run --no-project --script rossocortex.py ...", file=sys.stderr)
        return

    if "Address already in use" in output or "OSError" in output:
        print(f"Root cause: Port conflict", file=sys.stderr)
        for p in (port, control_port):
            if not _port_is_free(p):
                _show_port_owner(p)
        print(f"  Fix: kill the process or use --port / --control-port", file=sys.stderr)
        return

    if not no_authbridge:
        binary = ROSSOCORTEX_SCRIPT.parent / "bin" / "authbridge-proxy"
        config = Path(os.environ.get("ROSSOCORTEX_CONFIG_DIR", Path.home() / ".config" / "rossocortex")) / "config.yaml"

        if "binary not found" in output or not binary.exists():
            print(f"Root cause: AuthBridge binary missing", file=sys.stderr)
            print(f"  Expected: {binary}", file=sys.stderr)
            print(f"  Fix: cd {ROSSOCORTEX_SCRIPT.parent} && uv run python authbridge_wrapper.py build", file=sys.stderr)
            return

        if "config not found" in output or not config.exists():
            print(f"Root cause: AuthBridge config missing", file=sys.stderr)
            print(f"  Expected: {config}", file=sys.stderr)
            print(f"  Fix: cd {ROSSOCORTEX_SCRIPT.parent} && uv run python authbridge_wrapper.py init --budget 5.00", file=sys.stderr)
            return

        if "AuthBridge exited immediately" in output:
            print(f"Root cause: AuthBridge subprocess crashed", file=sys.stderr)
            if "address already in use" in output:
                import re
                bind_match = re.search(r"listen tcp [^:]*:(\d+): bind: address already in use", output)
                if bind_match:
                    blocked_port = int(bind_match.group(1))
                    print(f"  AuthBridge port {blocked_port} is already in use", file=sys.stderr)
                    _show_port_owner(blocked_port)
                else:
                    ab_ports = _get_authbridge_ports(config)
                    for p in ab_ports:
                        if not _port_is_free(p):
                            _show_port_owner(p)
            else:
                ab_ports = _get_authbridge_ports(config)
                for p in ab_ports:
                    if not _port_is_free(p):
                        _show_port_owner(p)
            print(f"  Fix: kill conflicting processes, or use --no-authbridge for direct mode", file=sys.stderr)
            return

    if "No credential found" in output:
        print(f"Root cause: No API key available (direct mode requires a credential)", file=sys.stderr)
        print(f"  Fix: export ANTHROPIC_AUTH_TOKEN=sk-... (or LITELLM_API_KEY)", file=sys.stderr)
        return

    if not upstream:
        print(f"Root cause: No upstream URL configured", file=sys.stderr)
        print(f"  Fix: --upstream <URL> or export ROSSOCORTEX_UPSTREAM=...", file=sys.stderr)
        return

    print(f"Root cause: Unknown (exit code {returncode})", file=sys.stderr)
    print(f"  Try running rossocortex.py directly to see full output:", file=sys.stderr)
    print(f"  {ROSSOCORTEX_SCRIPT} --budget 5.00 --upstream {upstream or '<URL>'} --port {port}", file=sys.stderr)


def _show_port_owner(port: int):
    """Show which process holds a port."""
    import subprocess as sp
    try:
        result = sp.run(
            ["lsof", "-i", f"TCP:{port}", "-sTCP:LISTEN", "-nP", "-t"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().splitlines()
        if pids:
            for pid in pids[:3]:
                ps = sp.run(["ps", "-p", pid, "-o", "pid=,command="], capture_output=True, text=True, timeout=5)
                cmd_line = ps.stdout.strip()
                print(f"  Port {port} held by: {cmd_line}", file=sys.stderr)
        else:
            print(f"  Port {port} in use (cannot identify owner)", file=sys.stderr)
    except (FileNotFoundError, PermissionError, OSError, sp.TimeoutExpired):
        print(f"  Port {port} in use (lsof unavailable or permission denied)", file=sys.stderr)


def _get_authbridge_ports(config_path: Path) -> list[int]:
    """Extract port numbers from an authbridge config.yaml."""
    ports = []
    if not config_path.exists():
        return [3130, 18081, 18082, 19095, 19096]
    try:
        for line in config_path.read_text().splitlines():
            stripped = line.strip()
            if "_addr" in stripped and ":" in stripped:
                part = stripped.split(":")[-1].strip().strip('"').strip("'")
                if part.isdigit():
                    ports.append(int(part))
    except OSError:
        pass
    return ports or [3130, 18081, 18082, 19095, 19096]


def _run_authbridge_wrapper(subcmd: list[str]) -> int:
    """Run authbridge_wrapper.py with its dependencies. Returns exit code."""
    import subprocess as sp
    wrapper = ROSSOCORTEX_SCRIPT.parent / "authbridge_wrapper.py"
    if not wrapper.exists():
        print(f"  ERROR: authbridge_wrapper.py not found at {wrapper}", file=sys.stderr)
        return 1
    cmd = ["uv", "run", "--no-project", "--with", "click>=8.0", "--with", "jinja2>=3.1",
           "python", str(wrapper)] + subcmd
    print(f"  $ {' '.join(cmd)}")
    result = sp.run(cmd, cwd=str(ROSSOCORTEX_SCRIPT.parent))
    return result.returncode


def _ensure_authbridge_binary() -> bool:
    """Build authbridge-proxy if missing. Returns True if binary is available."""
    binary = ROSSOCORTEX_SCRIPT.parent / "bin" / "authbridge-proxy"
    if binary.exists():
        return True

    print("AuthBridge binary not found — building automatically...")
    rc = _run_authbridge_wrapper(["build"])
    if rc != 0:
        print(f"  Build failed (exit code {rc})", file=sys.stderr)
        return False
    return binary.exists()


def _ensure_authbridge_config(budget: float) -> bool:
    """Config is always generated at startup by rossocortex.py — just ensure CA exists."""
    config_dir = Path(os.environ.get("ROSSOCORTEX_CONFIG_DIR", Path.home() / ".config" / "rossocortex"))
    ca_cert = config_dir / "ca" / "tls.crt"
    if ca_cert.exists():
        return True

    print("CA certificate not found — initializing...")
    rc = _run_authbridge_wrapper(["init", "--budget", str(budget)])
    if rc != 0:
        print(f"  Init failed (exit code {rc})", file=sys.stderr)
        return False
    return ca_cert.exists()


# Credential names in priority order (files checked first, then env vars).
# Mirrors rossocortex.py's credential lookup order.
CREDENTIAL_NAMES = ("LITELLM_API_KEY", "ROSSOCORTEX_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY")


def _config_dir_note() -> str:
    """Describe the active config dir and which override (if any) selected it."""
    if os.environ.get("ROSSOCORTEX_CONFIG_DIR"):
        src = "ROSSOCORTEX_CONFIG_DIR override active"
    elif os.environ.get("XDG_CONFIG_HOME"):
        src = "XDG_CONFIG_HOME override active"
    else:
        src = "default (~/.config)"
    return f"Config dir: {CONFIG_DIR}  [{src}]"


def _find_credential() -> tuple[str, str] | None:
    """Return (source, name) of the first available LiteLLM credential, or None.

    Checks credential files in CONFIG_DIR/credentials first, then environment
    variables, following the same priority order rossocortex uses at runtime.
    """
    creds_dir = CONFIG_DIR / "credentials"
    for name in CREDENTIAL_NAMES:
        f = creds_dir / name
        try:
            if f.exists() and f.read_text().strip():
                return (f"file {f}", name)
        except OSError:
            pass
    for name in CREDENTIAL_NAMES:
        if os.environ.get(name, "").strip():
            return (f"env ${name}", name)
    return None


def _check_credential_prereq() -> bool:
    """Verify a LiteLLM API key is available. Print an actionable message if not."""
    found = _find_credential()
    if found:
        return True
    creds_dir = CONFIG_DIR / "credentials"
    key_file = creds_dir / "LITELLM_API_KEY"
    print("ERROR: No LiteLLM API key found — rossocortex has no credential to inject.", file=sys.stderr)
    print("  rossocortex proxies to LiteLLM and must hold a valid virtual key.", file=sys.stderr)
    print(f"  {_config_dir_note()}", file=sys.stderr)
    print("  Provide one of the following (checked in this order):", file=sys.stderr)
    print("    1. A credential file (recommended, persists across restarts):", file=sys.stderr)
    print(f"         mkdir -p {creds_dir}", file=sys.stderr)
    print(f"         printf '%s' 'sk-your-litellm-key' > {key_file}", file=sys.stderr)
    print(f"         chmod 600 {key_file}", file=sys.stderr)
    print("    2. An environment variable (auto-saved to the credential file on first start):", file=sys.stderr)
    print("         export ANTHROPIC_AUTH_TOKEN=sk-your-litellm-key", file=sys.stderr)
    print("  Note: use a LiteLLM virtual key, NOT a raw provider key (e.g. sk-ant-...).", file=sys.stderr)
    return False


def _print_upstream_missing(env_hint: str):
    """Print an actionable message when no upstream LiteLLM URL is configured."""
    print("ERROR: No upstream LiteLLM URL configured.", file=sys.stderr)
    print("  rossocortex is a proxy — it forwards every request to a LiteLLM instance,", file=sys.stderr)
    print("  so it needs to know where that instance lives.", file=sys.stderr)
    print(f"  {_config_dir_note()}", file=sys.stderr)
    print("  Provide one of the following:", file=sys.stderr)
    print("    1. Pass it on the command line:", file=sys.stderr)
    print("         ./rossoctlx.py start --upstream https://your-litellm.example.com", file=sys.stderr)
    print(f"    2. Set an environment variable ({env_hint}):", file=sys.stderr)
    print("         export ROSSOCORTEX_UPSTREAM=https://your-litellm.example.com", file=sys.stderr)
    print("  Example (this cluster's LiteLLM):", file=sys.stderr)
    print("         export ROSSOCORTEX_UPSTREAM=https://ete-litellm.ai-models.vpc-int.res.ibm.com", file=sys.stderr)


def _summary_lines(control_url: str) -> list[str]:
    """Build a concise summary: version, status, budget, authbridge, agents.

    Queries the running server's control API for live version/budget; falls back
    to the saved state file when the control API is unreachable.
    """
    data = None
    try:
        resp = httpx.get(f"{control_url}/version", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
    except Exception:
        data = None

    state = _load_state()
    label = _runtime_label()
    lines = []

    if data:
        lines.append(f"rossocortex {data.get('rossocortex_version', '?')} — running "
                     f"({label}, pid={data.get('pid', '?')}, mode={data.get('mode', '?')})")
        lines.append(f"  upstream:   {data.get('upstream', '?')}")
        b = data.get("budget", {})
        lines.append(f"  budget:     ${b.get('spent_today', 0):.4f} / ${b.get('daily_limit', 0):.2f} "
                     f"({b.get('calls_today', 0)} calls today)")
        ab = data.get("authbridge")
        if ab:
            commit = ab.get("commit") or "?"
            origin = " ".join(x for x in (ab.get("repo"), ab.get("branch")) if x)
            line = f"  authbridge: {commit}"
            if origin:
                line += f" ({origin})"
            line += f" — {len(ab.get('plugins', []))} plugins"
            lines.append(line)
        else:
            lines.append("  authbridge: not active (direct mode)")
    else:
        lines.append(f"rossocortex — {label}, pid={state.get('pid', '?')}, mode={state.get('mode', '?')}")
        lines.append(f"  upstream:   {state.get('upstream', '?')}")
        lines.append(f"  budget:     ${state.get('budget', '?')}/day")
        if state.get("authbridge"):
            lines.append(f"  authbridge: {state['authbridge']}")

    lines.append(f"  control:    {control_url}")
    lines.append(f"  {_config_dir_note()}")

    agents = _load_agents().get("agents", {})
    if agents:
        lines.append(f"  agents ({len(agents)}):")
        for name, info in agents.items():
            spend = _load_agent_spend(name)
            spent = spend.get("total_spend", 0.0)
            calls = spend.get("total_calls", 0)
            ab_budget = info.get("budget")
            bstr = f"${ab_budget:.2f}" if ab_budget else "unlimited"
            lines.append(f"    - {name}: ${spent:.4f} / {bstr} ({calls} calls)")
    else:
        lines.append("  agents:     none registered")
    return lines


def _emit_summary(title: str, control_url: str, echo: bool = True, to_log: bool = True):
    """Write a titled summary block to the request log and/or echo it to stdout."""
    lines = _summary_lines(control_url)
    if to_log:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        block = [f"===== {title} @ {ts} =====", *lines, "=" * 42]
        log_file = _log_file()
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with log_file.open("a") as f:
                f.write("\n".join(block) + "\n")
        except OSError:
            pass
    if echo:
        print(f"# {title}")
        for line in lines:
            print(line)


def _print_next_steps():
    """Print a concise 'what to do next' block after a successful start."""
    me = sys.argv[0]
    print("\nNext steps:")
    print(f"  {me} status                      # check the proxy is healthy")
    print(f"  {me} agent my-agent --budget=5   # register an agent, get its proxy creds")
    print(f"  {me} agents                      # list registered agents")
    print(f"  {me} log -f                      # follow the request log")


def cmd_start(port: int, control_port: int, upstream: str, budget: float, no_authbridge: bool):
    """Start rossocortex as a background daemon."""
    pid = _is_running()
    if pid:
        state = _load_state()
        cp = state.get("control_port", control_port)
        print(f"rossocortex already running (pid={pid}, port={state.get('port', '?')})")
        _emit_summary("rossocortex already running", f"http://localhost:{cp}", echo=True, to_log=False)
        return

    if not upstream:
        import os
        upstream = os.environ.get("ROSSOCORTEX_UPSTREAM") or os.environ.get("ANTHROPIC_BASE_URL") or ""
    if not upstream:
        _print_upstream_missing("ROSSOCORTEX_UPSTREAM or ANTHROPIC_BASE_URL")
        sys.exit(1)

    if not _check_credential_prereq():
        sys.exit(1)

    if not _port_is_free(port) or not _port_is_free(control_port):
        free = _find_free_port(port, 2)
        if len(free) < 2:
            print(f"ERROR: Cannot find free ports near {port}", file=sys.stderr)
            for p in (port, control_port):
                if not _port_is_free(p):
                    _show_port_owner(p)
            print(f"  {_config_dir_note()}", file=sys.stderr)
            sys.exit(1)
        port, control_port = free[0], free[1]
        print(f"Ports in use, using: proxy={port}, control={control_port}")

    if not no_authbridge:
        if not _ensure_authbridge_binary():
            print(f"  Or start in direct mode: {sys.argv[0]} start --no-authbridge", file=sys.stderr)
            sys.exit(1)
        if not _ensure_authbridge_config(budget):
            print(f"  Or start in direct mode: {sys.argv[0]} start --no-authbridge", file=sys.stderr)
            sys.exit(1)

    cmd = [
        str(ROSSOCORTEX_SCRIPT),
        "--budget", str(budget),
        "--upstream", upstream,
        "--port", str(port),
        "--control-port", str(control_port),
    ]
    if no_authbridge:
        cmd.append("--no-authbridge")

    import subprocess, tempfile
    log_file = tempfile.NamedTemporaryFile(mode="w", prefix="rossocortex-", suffix=".log", delete=False)
    proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)

    import time
    wait_secs = 5 if not no_authbridge else 2
    time.sleep(wait_secs)
    log_file.flush()
    if proc.poll() is not None:
        log_file.close()
        output = Path(log_file.name).read_text()
        print(f"ERROR: rossocortex exited immediately (code {proc.returncode})", file=sys.stderr)
        _diagnose_start_failure(port, control_port, upstream, no_authbridge, output, proc.returncode)
        Path(log_file.name).unlink(missing_ok=True)
        sys.exit(1)

    log_file.close()
    Path(log_file.name).unlink(missing_ok=True)

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(proc.pid))
    mode = "direct" if no_authbridge else "authbridge"
    import os
    config_dir = Path(os.environ.get("ROSSOCORTEX_CONFIG_DIR", Path.home() / ".config" / "rossocortex"))
    creds_dir = config_dir / "credentials"
    cred_files = sorted(creds_dir.iterdir()) if creds_dir.exists() else []
    cred_names = ', '.join(f.name for f in cred_files) if cred_files else 'none'
    ca_cert = config_dir / "ca" / "tls.crt"
    local_dir = str(ROSSOCORTEX_CONTAINER_DIR)
    authbridge_info = None
    if not no_authbridge:
        build_info_path = ROSSOCORTEX_CONTAINER_DIR / "BUILD_INFO.json"
        if build_info_path.exists():
            import json as _json
            bi = _json.loads(build_info_path.read_text())
            authbridge_info = f"{bi.get('authbridge_commit','?')} ({bi.get('authbridge_repo','')}) built {bi.get('built_at','?')}"
    _save_state(port, control_port, proc.pid, upstream, mode,
                local_dir=local_dir, budget=budget,
                credentials=cred_names,
                ca_cert=str(ca_cert) if ca_cert.exists() else None,
                config_dir=str(config_dir),
                authbridge=authbridge_info,
                command=' '.join(cmd))
    _emit_summary("rossocortex started", f"http://localhost:{control_port}", echo=True, to_log=True)
    _print_next_steps()


CONTAINER_NAME = "rossocortex"


def _find_container_runtime() -> str | None:
    import shutil
    preferred = os.environ.get("ROSSOCORTEX_RUNTIME", "")
    if preferred and shutil.which(preferred):
        return preferred
    for cmd in ("docker", "podman"):
        if shutil.which(cmd):
            return cmd
    return None


def cmd_start_container(port: int, control_port: int, upstream: str, budget: float, image: str):
    """Start rossocortex as a container."""
    import subprocess as sp

    runtime = _find_container_runtime()
    if not runtime:
        print("ERROR: docker or podman required for --container mode", file=sys.stderr)
        print(f"  {_config_dir_note()}", file=sys.stderr)
        sys.exit(1)

    existing = sp.run([runtime, "ps", "-q", "-f", f"name={CONTAINER_NAME}"],
                      capture_output=True, text=True)
    if existing.stdout.strip():
        print(f"rossocortex container already running")
        state = _load_state()
        print(f"  port={state.get('port', port)}, control={state.get('control_port', control_port)}")
        return

    if not upstream:
        upstream = os.environ.get("ROSSOCORTEX_UPSTREAM") or os.environ.get("ANTHROPIC_BASE_URL") or ""
    if not upstream:
        _print_upstream_missing("ROSSOCORTEX_UPSTREAM")
        sys.exit(1)

    if not _check_credential_prereq():
        sys.exit(1)

    if not _port_is_free(port) or not _port_is_free(control_port):
        free = _find_free_port(port, 2)
        if len(free) < 2:
            print(f"ERROR: Cannot find free ports near {port}", file=sys.stderr)
            print(f"  {_config_dir_note()}", file=sys.stderr)
            sys.exit(1)
        port, control_port = free[0], free[1]
        print(f"Ports in use, using: proxy={port}, control={control_port}")

    config_dir = Path(os.environ.get("ROSSOCORTEX_CONFIG_DIR", Path.home() / ".config" / "rossocortex"))
    creds_dir = config_dir / "credentials"
    ca_dir = config_dir / "ca"

    creds_dir.mkdir(parents=True, exist_ok=True)
    ca_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("LITELLM_API_KEY") or ""
    if api_key:
        cred_file = creds_dir / "ANTHROPIC_AUTH_TOKEN"
        if not cred_file.exists():
            cred_file.write_text(api_key)
            cred_file.chmod(0o600)

    sp.run([runtime, "rm", "-f", CONTAINER_NAME], capture_output=True)

    cmd = [
        runtime, "run", "-d",
        "--name", CONTAINER_NAME,
        "-p", f"{port}:{port}",
        "-p", f"{control_port}:{control_port}",
        "-v", f"{config_dir}:/etc/rossocortex",
        "-e", f"ROSSOCORTEX_UPSTREAM={upstream}",
        "-e", f"ROSSOCORTEX_PORT={port}",
        "-e", f"ROSSOCORTEX_CONTROL_PORT={control_port}",
        "-e", f"ROSSOCORTEX_DAILY_BUDGET={budget}",
    ]

    # Forward the upstream-TLS toggle into the container (internal/self-signed upstreams).
    if os.environ.get("ROSSOCORTEX_UPSTREAM_INSECURE", "").lower() in ("1", "true", "yes"):
        cmd += ["-e", "ROSSOCORTEX_UPSTREAM_INSECURE=1"]

    cmd.append(image)

    print(f"Starting rossocortex container ({runtime})...")
    print(f"  $ {' '.join(cmd)}")
    result = sp.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: container start failed", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        print(f"  {_config_dir_note()}", file=sys.stderr)
        sys.exit(1)

    container_id = result.stdout.strip()[:12]

    import time
    time.sleep(3)

    check = sp.run([runtime, "ps", "-q", "-f", f"name={CONTAINER_NAME}"], capture_output=True, text=True)
    if not check.stdout.strip():
        print("ERROR: container exited immediately", file=sys.stderr)
        logs = sp.run([runtime, "logs", CONTAINER_NAME], capture_output=True, text=True)
        print(logs.stdout[-500:] if logs.stdout else "", file=sys.stderr)
        print(logs.stderr[-500:] if logs.stderr else "", file=sys.stderr)
        print(f"  {_config_dir_note()}", file=sys.stderr)
        sys.exit(1)

    docker_cmd = ' '.join(cmd)
    cred_names = ', '.join(f.name for f in sorted(creds_dir.iterdir())) if creds_dir.exists() else 'none'
    ca_cert = ca_dir / "tls.crt"
    _save_state(port, control_port, 0, upstream, "container",
                image=image, runtime=runtime, container_id=container_id,
                docker_cmd=docker_cmd, budget=budget,
                credentials=cred_names,
                ca_cert=str(ca_cert) if ca_cert.exists() else None,
                config_dir=str(config_dir))
    PID_FILE.write_text(f"container:{container_id}")

    _emit_summary("rossocortex started", f"http://localhost:{control_port}", echo=True, to_log=True)
    _print_next_steps()


def cmd_stop():
    """Stop running rossocortex daemon or container."""
    import subprocess as sp

    # Log a final summary while the server is still up (captures live version/agents).
    pre_state = _load_state()
    pre_cp = pre_state.get("control_port")
    if pre_cp:
        _emit_summary("rossocortex stopping", f"http://localhost:{pre_cp}", echo=False, to_log=True)

    stopped = False

    runtime = _find_container_runtime()
    if runtime:
        result = sp.run([runtime, "ps", "-q", "-f", f"name={CONTAINER_NAME}"], capture_output=True, text=True)
        if result.stdout.strip():
            sp.run([runtime, "stop", CONTAINER_NAME], capture_output=True)
            sp.run([runtime, "rm", "-f", CONTAINER_NAME], capture_output=True)
            print(f"rossocortex container stopped")
            stopped = True

    pid_content = PID_FILE.read_text().strip() if PID_FILE.exists() else ""
    if pid_content and not pid_content.startswith("container:"):
        try:
            pid = int(pid_content)
            os.kill(pid, 15)
            print(f"rossocortex stopped (pid={pid})")
            stopped = True
        except (ValueError, ProcessLookupError, PermissionError):
            pass

    PID_FILE.unlink(missing_ok=True)
    state = _load_state()
    if state:
        state["pid"] = 0
        state["mode"] = "stopped"
        STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")

    if not stopped:
        print("rossocortex is not running")


def _ensure_running(control_url: str) -> bool:
    """Check if rossocortex is running, return True if yes."""
    try:
        httpx.get(f"{control_url}/version", timeout=2.0)
        return True
    except httpx.ConnectError:
        return False


def _runtime_label() -> str:
    """Return 'container' or 'local' based on how rossocortex is running."""
    state = _load_state()
    mode = state.get("mode", "")
    if mode == "container":
        return "container"
    return "local"


def cmd_status(control_url: str):
    try:
        resp = httpx.get(f"{control_url}/version", timeout=3.0)
        data = resp.json()
        label = _runtime_label()
        state = _load_state()
        print(f"rossocortex is running ({label}, pid={data['pid']})")
        print(f"  Mode:       {data['mode']}")
        print(f"  Budget:     ${data['budget']['spent_today']:.4f} / ${data['budget']['daily_limit']:.2f} ({data['budget']['calls_today']} calls)")
        print(f"  Upstream:   {data['upstream']}")
        proxy_port = state.get("port", "?")
        ctrl_port = state.get("control_port", "?")
        if label == "container":
            owner = f"container '{CONTAINER_NAME}'" + (f" ({state['container_id']})" if state.get("container_id") else "")
        else:
            owner = f"local pid {data['pid']}"
        print(f"  Ports:      proxy {proxy_port}, control {ctrl_port}  (published by {owner})")
        print(f"  Control:    {control_url}")
        print(f"  Config:     {CONFIG_DIR}")

        agents_data = _load_agents()
        agents = agents_data.get("agents", {})
        if agents:
            print(f"  Agents ({len(agents)}):")
            for name, info in agents.items():
                agent_budget = info.get("budget")
                spend_data = _load_agent_spend(name)
                spent = spend_data.get("total_spend", 0.0)
                calls = spend_data.get("total_calls", 0)
                budget_str = f"${agent_budget:.2f}" if agent_budget else "unlimited"
                print(f"    {name}: ${spent:.4f} / {budget_str} ({calls} calls)")
    except httpx.ConnectError:
        state = _load_state()
        if state:
            print(f"rossocortex is NOT running (stale state)")
            print(f"  Ports (last run): proxy {state.get('port', '?')}, control {state.get('control_port', '?')}  (mode={state.get('mode', '?')})")
            print(f"  Config: {CONFIG_DIR}")
            print(f"  Tried:  {control_url}")
        else:
            print(f"rossocortex is NOT running")
            print(f"  Config: {CONFIG_DIR}")
        sys.exit(1)
    except Exception as e:
        print(f"rossocortex status unknown: {e}")
        print(f"  Config: {CONFIG_DIR}")
        sys.exit(2)


def cmd_version(control_url: str):
    # Always print the client version first so it's answerable in bug reports even
    # when no server is running.
    print(f"rossoctlx {ROSSOCTL_VERSION} (client)\n")
    try:
        resp = httpx.get(f"{control_url}/version", timeout=5.0)
    except httpx.ConnectError:
        print(f"Server: not running (cannot connect to {control_url})", file=sys.stderr)
        print(f"  Start one with: rossoctlx start --upstream <URL>", file=sys.stderr)
        sys.exit(1)

    if resp.status_code != 200:
        print(f"ERROR: Control API returned {resp.status_code}", file=sys.stderr)
        sys.exit(1)

    data = resp.json()
    label = _runtime_label()

    print(f"rossocortex {data['rossocortex_version']} ({label})")
    print(f"  Runtime:    {label}")
    print(f"  Mode:       {data['mode']}")
    print(f"  Upstream:   {data['upstream']}")
    print(f"  Proxy port: {data['port']}")
    print(f"  Control:    {control_url}")
    print(f"  PID:        {data['pid']}")
    print()

    budget = data.get("budget", {})
    print(f"Budget:")
    print(f"  Daily limit: ${budget.get('daily_limit', 0):.2f}")
    print(f"  Spent today: ${budget.get('spent_today', 0):.4f}")
    print(f"  Calls today: {budget.get('calls_today', 0)}")
    print()

    ab = data.get("authbridge")
    if ab:
        print(f"AuthBridge:")
        print(f"  Binary:   {ab.get('binary', 'unknown')}")
        print(f"  Commit:   {ab.get('commit', 'unknown')} ({ab.get('repo', '')} {ab.get('branch', '')})")
        print(f"  Go:       {ab.get('go_version', 'unknown')}")
        print(f"  Built:    {ab.get('built_at', 'unknown')}")
        print(f"  Platform: {ab.get('platform', 'unknown')}")
        plugins = ab.get("plugins", [])
        print(f"  Plugins ({len(plugins)}):")
        for p in plugins:
            print(f"    - {p}")
    else:
        print(f"AuthBridge: not active (direct mode)")


def _load_agents() -> dict:
    if not AGENTS_FILE.exists():
        return {"agents": {}}
    try:
        return json.loads(AGENTS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"agents": {}}


def _save_agents(data: dict):
    AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENTS_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _allocate_ports(agents: dict) -> dict:
    """Allocate next available port block for a new agent, skipping in-use ports."""
    used_bases = set()
    for info in agents.values():
        ports = info.get("ports", {})
        if ports.get("forward"):
            used_bases.add(ports["forward"] - (ports["forward"] - AGENT_PORT_BASE) % PORTS_PER_AGENT)
    base = AGENT_PORT_BASE
    while True:
        if base in used_bases:
            base += PORTS_PER_AGENT
            continue
        if all(_port_is_free(base + i) for i in range(PORTS_PER_AGENT)):
            break
        base += PORTS_PER_AGENT
        if base > AGENT_PORT_BASE + 500:
            raise RuntimeError("Cannot find free port block for agent authbridge")
    return {
        "forward": base,
        "reverse": base + 1,
        "transparent": base + 2,
        "stats": base + 3,
        "session": base + 4,
    }


def _generate_agent_config(agent_name: str, ports: dict, budget: float | None, credentials_path: str | None = None):
    """Render authbridge config.yaml for an agent."""
    agent_dir = AGENTS_DIR / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)

    creds_dir = agent_dir / "credentials"
    if credentials_path:
        creds_dir = Path(credentials_path)
    elif not creds_dir.exists():
        shared_creds = CONFIG_DIR / "credentials"
        if shared_creds.exists():
            creds_dir.symlink_to(shared_creds)
        else:
            creds_dir.mkdir(parents=True, exist_ok=True)

    ca_dir = CONFIG_DIR / "ca"
    spend_file = agent_dir / "spend-authbridge.json"
    config_file = agent_dir / "config.yaml"

    try:
        from jinja2 import Environment, FileSystemLoader, Template
    except ImportError:
        print("ERROR: jinja2 required for config generation. Install: pip install jinja2", file=sys.stderr)
        sys.exit(1)

    template_file = TEMPLATES_DIR / "config.yaml.j2"
    if template_file.exists():
        env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
        template = env.get_template("config.yaml.j2")
    else:
        # No on-disk template (e.g. pip-installed standalone) — use embedded copy.
        template = Template(EMBEDDED_AGENT_CONFIG_TEMPLATE)
    rendered = template.render(
        port=ports["forward"],
        reverse_proxy_port=ports["reverse"],
        transparent_port=ports["transparent"],
        session_port=ports["session"],
        stats_port=ports["stats"],
        ca_dir=str(ca_dir),
        credentials_dir=str(creds_dir),
        inference_parser=True,
        mcp_parser=True,
        budget_track=budget is not None and budget > 0,
        spend_file=str(spend_file),
        max_budget=budget or 0,
    )
    config_file.write_text(rendered)
    return config_file


def _load_agent_spend(agent_name: str) -> dict:
    path = CONFIG_DIR / f"spend-{agent_name}.json"
    if not path.exists():
        return {"total_spend": 0.0, "total_calls": 0}
    try:
        data = json.loads(path.read_text())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if data.get("date") != today:
            return {"total_spend": 0.0, "total_calls": 0}
        return data
    except (json.JSONDecodeError, OSError):
        return {"total_spend": 0.0, "total_calls": 0}


def cmd_agent_id(agent_name: str | None, proxy_port: int, list_agents: bool, delete: bool = False, budget: float | None = None, credentials: str | None = None, network_allow: list[str] | None = None, network_deny: list[str] | None = None):
    if delete:
        if not agent_name:
            print("ERROR: agent_name required with --delete", file=sys.stderr)
            sys.exit(1)
        data = _load_agents()
        agents = data.get("agents", {})
        if agent_name not in agents:
            print(f"ERROR: agent '{agent_name}' not found", file=sys.stderr)
            sys.exit(1)
        del agents[agent_name]
        _save_agents(data)
        import shutil
        agent_dir = AGENTS_DIR / agent_name
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        spend_file = CONFIG_DIR / f"spend-{agent_name}.json"
        spend_file.unlink(missing_ok=True)
        print(f"Deleted agent '{agent_name}'")
        return

    if list_agents:
        data = _load_agents()
        agents = data.get("agents", {})
        if not agents:
            print("No registered agents.")
            return
        print(f"Registered agents ({len(agents)}):")
        for name, info in agents.items():
            agent_budget = info.get("budget")
            spend_data = _load_agent_spend(name)
            spent = spend_data.get("total_spend", 0.0)
            calls = spend_data.get("total_calls", 0)
            budget_str = f"--budget={agent_budget:.2f}" if agent_budget else "--budget=unlimited"
            allow = info.get("network_allow", [])
            deny = info.get("network_deny", [])
            policy_parts = []
            for h in allow:
                policy_parts.append(f"--network-allow='{h}'" if any(c in h for c in '*?[]') else f"--network-allow={h}")
            for h in deny:
                policy_parts.append(f"--network-deny='{h}'" if any(c in h for c in '*?[]') else f"--network-deny={h}")
            policy_str = f"  {' '.join(policy_parts)}" if policy_parts else ""
            print(f"  {name}  {budget_str}{policy_str}  spent=${spent:.4f}  ({calls} calls)")
        return

    if not agent_name:
        print("ERROR: agent_name required (or use --list)", file=sys.stderr)
        sys.exit(1)

    data = _load_agents()
    agents = data.setdefault("agents", {})

    is_new = agent_name not in agents
    if not is_new:
        token = agents[agent_name]["token"]
        changed = False
        if budget is not None:
            if budget == 0:
                agents[agent_name].pop("budget", None)
            else:
                agents[agent_name]["budget"] = budget
            changed = True
        if credentials is not None:
            agents[agent_name]["credentials"] = credentials
            changed = True
        if network_allow is not None:
            agents[agent_name]["network_allow"] = network_allow
            changed = True
        if network_deny is not None:
            agents[agent_name]["network_deny"] = network_deny
            changed = True
        if "ports" not in agents[agent_name]:
            agents[agent_name]["ports"] = _allocate_ports(agents)
            changed = True
        if changed:
            _save_agents(data)
            _generate_agent_config(
                agent_name, agents[agent_name]["ports"],
                agents[agent_name].get("budget"),
                agents[agent_name].get("credentials"),
            )
    else:
        token = secrets.token_hex(16)
        ports = _allocate_ports(agents)
        entry = {
            "token": token,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ports": ports,
        }
        if budget is not None and budget != 0:
            entry["budget"] = budget
        if credentials is not None:
            entry["credentials"] = credentials
        if network_allow is not None:
            entry["network_allow"] = network_allow
        if network_deny is not None:
            entry["network_deny"] = network_deny
        agents[agent_name] = entry
        _save_agents(data)
        _generate_agent_config(agent_name, ports, budget, credentials)

    # Print what changed
    info = agents[agent_name]
    changes = []
    if budget is not None:
        changes.append("budget=unlimited" if budget == 0 else f"budget={budget:.2f}")
    if credentials is not None:
        changes.append(f"credentials={credentials}")
    if network_allow is not None:
        changes.append(f"network-allow={','.join(network_allow)}")
    if network_deny is not None:
        changes.append(f"network-deny={','.join(network_deny)}")
    if is_new:
        print(f"# Created agent '{agent_name}'" + (f" with {', '.join(changes)}" if changes else ""))
    elif changes:
        print(f"# Updated agent '{agent_name}': {', '.join(changes)}")
    else:
        print(f"# Agent '{agent_name}' (no changes)")

    # Print agent config in CLI-flag format (same as 'agents' command)
    agent_budget = info.get("budget")
    spend_data = _load_agent_spend(agent_name)
    spent = spend_data.get("total_spend", 0.0)
    calls = spend_data.get("total_calls", 0)
    budget_flag = f"--budget={agent_budget:.2f}" if agent_budget else "--budget=unlimited"
    allow = info.get("network_allow", [])
    deny = info.get("network_deny", [])
    _q = lambda h: f"'{h}'" if any(c in h for c in '*?[]') else h
    policy_parts = [f"--network-allow={_q(h)}" for h in allow] + [f"--network-deny={_q(h)}" for h in deny]
    policy_str = f"  {' '.join(policy_parts)}" if policy_parts else ""
    print(f"#   {agent_name}  {budget_flag}{policy_str}  spent=${spent:.4f}  ({calls} calls)")

    state = _load_state()
    upstream = state.get("upstream", "")
    actual_port = state.get("port", proxy_port)
    ca_cert = CONFIG_DIR / "ca" / "tls.crt"

    base_url = f"http://{agent_name}:{token}@localhost:{actual_port}"
    plain_url = f"http://localhost:{actual_port}"
    agent_key = f"{agent_name}:{token}"
    print(f"# Run with: eval \"$({sys.argv[0]} agent {agent_name})\"")
    print(f"export OPENAI_API_BASE={base_url}")
    print(f"export OPENAI_API_KEY={agent_key}")
    print(f"export ANTHROPIC_BASE_URL={plain_url}")
    print(f"export ANTHROPIC_AUTH_TOKEN={agent_key}")
    if upstream:
        print(f"export HTTPS_PROXY=http://{agent_name}:{token}@localhost:{actual_port}")
        print(f"export NO_PROXY=localhost,127.0.0.1")
        if ca_cert.exists():
            print(f"export SSL_CERT_FILE={ca_cert}")

    # Container recipe (stderr → visible + copy-pasteable, not captured by `eval`).
    # A container can't reach the host's localhost, so route through
    # host.docker.internal and mount the interception CA.
    hostname = "host.docker.internal"
    ca_in_container = "/etc/rossocortex/ca.crt"
    e = lambda: print(file=sys.stderr)
    p = lambda s: print(s, file=sys.stderr)
    e()
    p(f"# ---- Run an agent container through rossocortex (docker or podman) ----")
    p(f"#   docker run --rm -it \\")
    p(f"#     --add-host={hostname}:host-gateway \\")
    p(f"#     -e ANTHROPIC_BASE_URL=http://{hostname}:{actual_port} \\")
    p(f"#     -e ANTHROPIC_AUTH_TOKEN={agent_key} \\")
    p(f"#     -e OPENAI_API_BASE=http://{hostname}:{actual_port} \\")
    p(f"#     -e OPENAI_API_KEY={agent_key} \\")
    if upstream:
        p(f"#     -e HTTPS_PROXY=http://{agent_key}@{hostname}:{actual_port} \\")
        p(f"#     -e NO_PROXY={hostname},localhost,127.0.0.1 \\")
        if ca_cert.exists():
            p(f"#     -e SSL_CERT_FILE={ca_in_container} \\")
            p(f"#     -v {ca_cert}:{ca_in_container}:ro \\")
    p(f"#     quay.io/aslomnet/agents:test bash")
    p(f"#   (podman: identical flags; host.docker.internal works with 'podman machine')")

    # Stronger isolation: put the agent on an --internal network (no internet at
    # all) and dual-home rossocortex, so the proxy is the ONLY egress. The agent
    # reaches it by container name 'rossocortex' (user-defined net = name DNS).
    if upstream:
        e()
        p(f"# ---- Fully isolated variant (agent has NO direct internet) ----")
        p(f"#   docker network create --internal isolated-net       # once")
        p(f"#   docker network connect isolated-net rossocortex      # dual-home the proxy")
        p(f"#   docker run --rm -it --network isolated-net \\")
        p(f"#     -e HTTP_PROXY=http://{agent_key}@rossocortex:{actual_port} \\")
        p(f"#     -e HTTPS_PROXY=http://{agent_key}@rossocortex:{actual_port} \\")
        p(f"#     -e NO_PROXY=rossocortex \\")
        if ca_cert.exists():
            p(f"#     -e SSL_CERT_FILE={ca_in_container} \\")
            p(f"#     -v {ca_cert}:{ca_in_container}:ro \\")
        p(f"#     -v \"$PWD:/workspace\" \\")
        p(f"#     quay.io/aslomnet/agents:test bash")
        p(f"#   Only this agent's --network-allow hosts are reachable; everything else is denied.")
        p(f"#   Shortcut for all of the above: {os.path.basename(sys.argv[0])} sandbox run {agent_name} -- bash")


def cmd_sandbox_run(agent_name: str, image: str, network: str, workspace: str,
                    command: list[str], proxy_port: int):
    """Print the docker/podman commands that run an agent container fully isolated
    on an --internal network, with its only egress being the rossocortex proxy
    (reached by container name). Prints a copy-pasteable / pipe-to-sh block rather
    than executing, so the exact commands can be reviewed first."""
    import shlex
    q = shlex.quote
    argv0 = os.path.basename(sys.argv[0])

    runtime = _find_container_runtime() or "docker"

    if _is_running() is None:
        print(f"ERROR: rossocortex is not running. Start it first:", file=sys.stderr)
        print(f"  {argv0} start --upstream <LiteLLM-URL>", file=sys.stderr)
        sys.exit(1)

    state = _load_state()
    port = state.get("port", proxy_port)

    agents = _load_agents().get("agents", {})
    if agent_name not in agents:
        print(f"ERROR: agent '{agent_name}' not found. Register it first:", file=sys.stderr)
        print(f"  {argv0} agent {agent_name} --budget=5 --network-allow=<host> ...", file=sys.stderr)
        sys.exit(1)
    agent_key = f"{agent_name}:{agents[agent_name]['token']}"
    ca_cert = CONFIG_DIR / "ca" / "tls.crt"
    ca_in_container = "/etc/rossocortex/ca.crt"

    # Full agent env, adjusted for a container: localhost -> the proxy's container
    # name, and SSL_CERT_FILE points at the CA mounted into the container.
    envs = [
        ("OPENAI_API_BASE", f"http://{CONTAINER_NAME}:{port}"),
        ("OPENAI_API_KEY", agent_key),
        ("ANTHROPIC_BASE_URL", f"http://{CONTAINER_NAME}:{port}"),
        ("ANTHROPIC_AUTH_TOKEN", agent_key),
        ("HTTP_PROXY", f"http://{agent_key}@{CONTAINER_NAME}:{port}"),
        ("HTTPS_PROXY", f"http://{agent_key}@{CONTAINER_NAME}:{port}"),
        ("NO_PROXY", CONTAINER_NAME),
    ]
    if ca_cert.exists():
        envs.append(("SSL_CERT_FILE", ca_in_container))

    # Interactive shell by default (-it); an explicit `-- CMD` runs one-shot.
    run_cmd = command if command else ["bash"]
    tty = "" if command else " -it"

    lines = [f"{runtime} run --rm{tty} --network {q(network)}"]
    lines += [f"-e {k}={q(v)}" for k, v in envs]
    if ca_cert.exists():
        lines.append(f"-v {q(str(ca_cert))}:{ca_in_container}:ro")
    lines.append(f"-v {q(workspace)}:/workspace -w /workspace")
    lines.append(f"{q(image)} {' '.join(q(c) for c in run_cmd)}")
    run_block = " \\\n  ".join(lines)

    print(f"# Isolated sandbox for agent '{agent_name}' — egress ONLY via {CONTAINER_NAME}:{port}", file=sys.stderr)
    print(f"# Review, then run — or pipe to a shell:  {argv0} sandbox run {agent_name} ... | sh", file=sys.stderr)
    # The runnable block goes to stdout (copy-paste or pipe to sh). The idempotent
    # setup steps use '|| true' so re-running is safe.
    print(f"# 1. create the isolated (no-internet) network")
    print(f"{runtime} network create --internal {q(network)} 2>/dev/null || true")
    print(f"# 2. dual-home the rossocortex proxy onto it")
    print(f"{runtime} network connect {q(network)} {CONTAINER_NAME} 2>/dev/null || true")
    print(f"# 3. run the agent container (only its --network-allow hosts are reachable)")
    print(run_block)


def _print_completion_code(shell_name: str, aliases: list[str] | None = None):
    """Output raw completion code suitable for eval."""
    if shell_name == "zsh":
        print('autoload -Uz compinit 2>/dev/null; compinit 2>/dev/null')
        print('_rossoctlx() { local commands="status version start stop log logs agent agents completions"; if (( CURRENT == 2 )); then _describe "command" "(status:Check\\ if\\ running version:Show\\ version start:Start\\ daemon stop:Stop\\ daemon log:Show\\ request\\ log logs:Show\\ request\\ log agent:Manage\\ agents agents:List\\ agents completions:Shell\\ completion\\ setup)"; fi }')
        print('compdef _rossoctlx rossoctlx.py')
        print('compdef _rossoctlx rossoctlx')
        for alias in (aliases or []):
            print(f'compdef _rossoctlx {alias}')
    elif shell_name == "bash":
        print('_rossoctlx() { COMPREPLY=($(compgen -W "status version start stop log logs agent agents completions" -- "${COMP_WORDS[COMP_CWORD]}")); }')
        print('complete -o default -F _rossoctlx rossoctlx.py')
        print('complete -o default -F _rossoctlx rossoctlx')
        for alias in (aliases or []):
            print(f'complete -o default -F _rossoctlx {alias}')
    elif shell_name == "fish":
        for cmd in ("rossoctlx.py", "rossoctlx", *(aliases or [])):
            print(f"complete -c {cmd} -f -n '__fish_use_subcommand' -a 'status version start stop log logs agent agents completions'")


def cmd_completions(eval_mode: bool = False, aliases: list[str] | None = None):
    """Print shell completion setup instructions for the current shell."""
    import os
    shell = os.environ.get("SHELL", "/bin/bash")
    shell_name = Path(shell).name
    me = sys.argv[0]

    if eval_mode:
        _print_completion_code(shell_name, aliases)
        return

    print(f"# Shell completion for rossoctlx ({shell_name})")
    print()

    if shell_name in ("zsh", "bash"):
        rc_file = "~/.zshrc" if shell_name == "zsh" else "~/.bashrc"
        print("# Enable in current shell:")
        print(f'eval "$({me} completions --eval)"')
        print()
        print(f"# Or add to {rc_file} for persistence:")
        print(f'eval "$({me} completions --eval)"')
        print()
        print("# With alias (e.g. alias rx=rossoctlx.py):")
        print(f'eval "$({me} completions --eval --alias rx)"')
    elif shell_name == "fish":
        print("# Enable in current shell:")
        print(f"{me} completions --eval | source")
        print()
        print("# Or add to ~/.config/fish/completions/rossoctlx.fish:")
        print(f"{me} completions --eval | source")
    else:
        print(f"# No completion support for {shell_name}")
        print("# Supported shells: bash, zsh, fish")


def _log_file() -> Path:
    """Resolve log file path (same logic as rossocortex.py CONFIG_DIR)."""
    import os
    config = Path(os.environ.get("ROSSOCORTEX_CONFIG_DIR", Path.home() / ".config" / "rossocortex"))
    return config / "rossocortex.log"


def _print_banner():
    """Print compact status: version, upstream, budget, agents (< 10 lines)."""
    state = _load_state()
    mode = state.get("mode", "?")
    port = state.get("port", "?")
    pid = state.get("pid", "?")
    upstream = state.get("upstream", "?")
    budget = state.get("budget", "?")
    image = state.get("image", "")
    runtime_env = os.environ.get("ROSSOCORTEX_RUNTIME", "")
    runtime_flag = f" --runtime={runtime_env}" if runtime_env else ""
    me = sys.argv[0]

    print(f"rossocortex (pid={pid}, port={port}, mode={mode})")
    if image:
        print(f"  image={image}  upstream={upstream}  budget=${budget}/day")
    else:
        print(f"  upstream={upstream}  budget=${budget}/day")

    data = _load_agents()
    agents = data.get("agents", {})
    if agents:
        parts = []
        for name, info in agents.items():
            spend_data = _load_agent_spend(name)
            spent = spend_data.get("total_spend", 0.0)
            ab = info.get("budget")
            b = f"${ab:.0f}" if ab else "unlimited"
            parts.append(f"{name}(${spent:.2f}/{b})")
        print(f"  agents: {', '.join(parts)}")

    print(f"  Use: {me}{runtime_flag} log -f")


def _ensure_running() -> bool:
    """Ensure rossocortex is running. Start it if not. Returns True if running."""
    pid = _is_running()
    if pid:
        return True

    import subprocess as sp
    runtime = _find_container_runtime()
    if runtime:
        result = sp.run([runtime, "ps", "-q", "-f", f"name={CONTAINER_NAME}"], capture_output=True, text=True)
        if result.stdout.strip():
            return True

    state = _load_state()
    if state.get("control_port"):
        try:
            httpx.get(f"http://localhost:{state['control_port']}/version", timeout=2.0)
            return True
        except httpx.ConnectError:
            pass

    upstream = os.environ.get("ROSSOCORTEX_UPSTREAM") or os.environ.get("ANTHROPIC_BASE_URL") or state.get("upstream") or ""
    if not upstream:
        print("rossocortex is not running and no ROSSOCORTEX_UPSTREAM set — cannot auto-start.", file=sys.stderr)
        print("  Fix: export ROSSOCORTEX_UPSTREAM=https://your-litellm-proxy.example.com", file=sys.stderr)
        return False
    local_dir = os.environ.get("ROSSOCORTEX_CONTAINER_LOCAL_DIR")
    if local_dir:
        print(f"rossocortex is not running — starting (local: {local_dir})...")
        cmd_start(DEFAULT_PROXY_PORT, DEFAULT_PROXY_PORT + 1, upstream, 5.0, False)
    else:
        print("rossocortex is not running — starting (container)...")
        cmd_start_container(DEFAULT_PROXY_PORT, DEFAULT_PROXY_PORT + 1, upstream, 5.0, "quay.io/aslomnet/rosscortex:latest")
    return _is_running() is not None


def cmd_log(follow: bool = False, lines: int = 20, agent_filter: str | None = None):
    """Show rossocortex request log."""
    if not _ensure_running():
        return

    _print_banner()

    log_file = _log_file()
    if not log_file.exists():
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.touch()

    if follow:
        import subprocess as sp
        sys.stdout.flush()
        if log_file.stat().st_size == 0:
            print("(waiting for first log entry...)")
            sys.stdout.flush()
        cmd = ["tail", "-f", str(log_file)]
        if agent_filter:
            print(f"Following (filter: agent={agent_filter})...")
            try:
                proc = sp.Popen(cmd, stdout=sp.PIPE, text=True)
                for line in proc.stdout:
                    if f"agent={agent_filter}" in line:
                        print(line, end="")
            except KeyboardInterrupt:
                proc.terminate()
        else:
            try:
                sp.run(cmd)
            except KeyboardInterrupt:
                pass
        return

    all_lines = log_file.read_text().splitlines()
    if agent_filter:
        all_lines = [l for l in all_lines if f"agent={agent_filter}" in l]
    if not all_lines:
        print("(no log entries yet)")
        return
    for line in all_lines[-lines:]:
        print(line)


def _norm_arch(m: str) -> str:
    m = (m or "").lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "amd64"
    return m


def _daemon_ok(runtime: str) -> bool:
    import subprocess as sp
    try:
        return sp.run([runtime, "info"], capture_output=True, timeout=10).returncode == 0
    except (OSError, sp.TimeoutExpired):
        return False


def _dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor-write-test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def cmd_doctor(args):
    """Offline environment preflight — pass/fail with remediation. Exits non-zero on failure."""
    import platform
    import shutil
    import subprocess as sp

    print("rossoctlx doctor — environment preflight\n")
    results = []  # (ok: True|False|None, name, detail, fix)   None => warning (non-fatal)

    def add(ok, name, detail="", fix=""):
        results.append((ok, name, detail, fix))

    # Python
    add(sys.version_info >= (3, 11), "Python >= 3.11", f"found {sys.version.split()[0]}",
        "install Python 3.11+ (install guide §2)")

    # git — install-time dependency (pip/pipx fetch from a Git repo)
    git = shutil.which("git")
    add(True if git else None, "git on PATH", git or "not found",
        "git is needed to (re)install from the Git repo — install git (install guide §3)")

    # rossoctlx itself resolvable on PATH
    rx = shutil.which("rossoctlx")
    add(True if rx else None, "rossoctlx on PATH", rx or "not found (running via script?)",
        "if installed with pipx: run 'pipx ensurepath' and open a new terminal")

    # container runtime + daemon health
    runtime = _find_container_runtime()
    if runtime:
        up = _daemon_ok(runtime)
        add(up, f"container runtime ({runtime})",
            "daemon responding" if up else "installed but daemon NOT responding",
            "start Docker Desktop, or `sudo systemctl start docker` / `systemctl --user start podman`")
    else:
        add(None if args.local else False, "container runtime (docker/podman)", "none on PATH",
            "install docker or podman for container mode (install guide §6) — or use --local")

    # architecture vs image
    host = _norm_arch(platform.machine())
    img = args.image
    img_arch = None
    if runtime:
        try:
            r = sp.run([runtime, "image", "inspect", img, "--format", "{{.Architecture}}"],
                       capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                img_arch = _norm_arch(r.stdout.strip())
        except (OSError, sp.TimeoutExpired):
            pass
    if img_arch:
        add(img_arch == host, f"image arch matches host ({host})", f"{img} is {img_arch}",
            "build a native image (rossocortex-container/REPRODUCE.md) and pass --image")
    elif img.startswith("quay.io/aslomnet/rosscortex") and host != "arm64":
        add(None, f"image arch vs host ({host})", "default image is linux/arm64-only, not yet pulled",
            f"on {host} build a native image (REPRODUCE.md) and pass --image")

    # credential
    cred = _find_credential()
    add(bool(cred), "LiteLLM/LLM API key", cred[0] if cred else "none found",
        f"set one of {', '.join(CREDENTIAL_NAMES)} (file in {CONFIG_DIR / 'credentials'} or env)")

    # upstream
    upstream = (os.environ.get("ROSSOCORTEX_UPSTREAM") or os.environ.get("ANTHROPIC_BASE_URL")
                or _load_state().get("upstream"))
    add(True if upstream else None, "upstream LLM URL", upstream or "not set",
        "pass --upstream <URL> or export ROSSOCORTEX_UPSTREAM")

    # config dir writable
    add(_dir_writable(CONFIG_DIR), "config dir writable", _config_dir_note(),
        f"ensure {CONFIG_DIR} is writable")

    # default ports
    p_free, c_free = _port_is_free(DEFAULT_PROXY_PORT), _port_is_free(DEFAULT_PROXY_PORT + 1)
    add(True if (p_free and c_free) else None, "default ports free",
        f"proxy {DEFAULT_PROXY_PORT} {'free' if p_free else 'in use'}, "
        f"control {DEFAULT_PROXY_PORT + 1} {'free' if c_free else 'in use'}",
        "start auto-picks free ports if these are taken")

    # native-mode prerequisites (optional)
    if args.local:
        uv = shutil.which("uv")
        add(True if uv else None, "uv on PATH (--local)", uv or "not found",
            "install uv: https://astral.sh/uv")
        localdir = os.environ.get("ROSSOCORTEX_CONTAINER_LOCAL_DIR")
        add(True if localdir else None, "ROSSOCORTEX_CONTAINER_LOCAL_DIR (--local)", localdir or "not set",
            "export ROSSOCORTEX_CONTAINER_LOCAL_DIR=<checkout>/scripts/rossocortex-container")
        add(True if ROSSOCORTEX_SCRIPT.exists() else None, "rossocortex.py present (--local)",
            str(ROSSOCORTEX_SCRIPT) if ROSSOCORTEX_SCRIPT.exists() else "not found",
            "not shipped in a pip install — use a source checkout for --local mode")
    else:
        print("  (native-mode checks skipped; pass --local to include them)\n")

    fails = warns = passes = 0
    for ok, name, detail, fix in results:
        mark = "✓" if ok is True else ("!" if ok is None else "✗")
        line = f"  [{mark}] {name}"
        if detail:
            line += f"  ({detail})"
        print(line)
        if ok is False:
            fails += 1
            if fix:
                print(f"      fix: {fix}")
        elif ok is None:
            warns += 1
            if fix:
                print(f"      note: {fix}")
        else:
            passes += 1

    print(f"\n{passes} passed, {warns} warnings, {fails} failed")
    if fails == 0:
        print("Ready. Next: rossoctlx start --upstream <URL>")
    sys.exit(1 if fails else 0)


def _add_start_args(p):
    """Register the `start` flags on a parser (shared by `start` and `cortex start`)."""
    p.add_argument("--port", type=int, default=DEFAULT_PROXY_PORT, help="Proxy listen port")
    p.add_argument("--control-port", type=int, default=8186, help="Control API port")
    p.add_argument("--upstream", default="", help="Upstream LiteLLM URL")
    p.add_argument("--budget", type=float, default=5.0, help="Global daily budget in USD")
    p.add_argument("--local", action="store_true", help="Run locally (uses ROSSOCORTEX_CONTAINER_LOCAL_DIR or rossocortex-container/)")
    p.add_argument("--no-authbridge", action="store_true", help="Direct mode without AuthBridge (local only)")
    p.add_argument("--image", default="quay.io/aslomnet/rosscortex:latest", help="Container image (default mode)")
    p.add_argument("--log-follow", "-f", action="store_true", dest="log_follow", help="After starting, follow the log (like 'start' then 'log -f')")


def _do_start(args):
    """Run the start flow (shared by `start` and `cortex start`)."""
    local_dir = os.environ.get("ROSSOCORTEX_CONTAINER_LOCAL_DIR", "")
    if args.local:
        if not local_dir:
            print("ERROR: --local requires ROSSOCORTEX_CONTAINER_LOCAL_DIR to be set", file=sys.stderr)
            print(f"  export ROSSOCORTEX_CONTAINER_LOCAL_DIR=/path/to/rossocortex-container", file=sys.stderr)
            sys.exit(1)
        local_path = Path(local_dir)
        missing = []
        if not (local_path / "rossocortex.py").exists():
            missing.append("rossocortex.py")
        if not (local_path / "templates").is_dir():
            missing.append("templates/")
        if missing:
            print(f"ERROR: ROSSOCORTEX_CONTAINER_LOCAL_DIR={local_dir} is missing: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        cmd_start(args.port, args.control_port, args.upstream, args.budget, args.no_authbridge)
    else:
        cmd_start_container(args.port, args.control_port, args.upstream, args.budget, args.image)
    if args.log_follow:
        cmd_log(follow=True, lines=20, agent_filter=None)


def main():
    parser = argparse.ArgumentParser(description="rossoctlx — manage a running rossocortex proxy")
    parser.add_argument("--control-url", default=DEFAULT_CONTROL_URL, help="Rossocortex control API URL")
    parser.add_argument("--runtime", choices=["docker", "podman"], default=None, help="Container runtime (default: auto-detect, or ROSSOCORTEX_RUNTIME env)")
    parser.add_argument("--version", action="version", version=f"rossoctlx {ROSSOCTL_VERSION}", help="Print the client version and exit")

    # Reusable copy of the global flags so subcommands (e.g. `cortex`) can surface
    # them in their own --help and accept them after the subcommand too. SUPPRESS
    # defaults mean omitting them here leaves the top-level parser's value intact.
    global_flags = argparse.ArgumentParser(add_help=False)
    _gf = global_flags.add_argument_group("global options (also accepted before the command)")
    _gf.add_argument("--runtime", choices=["docker", "podman"], default=argparse.SUPPRESS,
                     help="Container runtime (default: auto-detect, or ROSSOCORTEX_RUNTIME env)")
    _gf.add_argument("--control-url", default=argparse.SUPPRESS, help="Rossocortex control API URL")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("version", help="Show version and status of running rossocortex")
    subparsers.add_parser("status", help="Check if rossocortex is running")

    doctor_parser = subparsers.add_parser("doctor", aliases=["preflight", "checks", "requirements", "reqs"], help="Check environment prerequisites (offline pass/fail)")
    doctor_parser.add_argument("--local", action="store_true", help="Also check native (--local) mode prerequisites")
    doctor_parser.add_argument("--image", default="quay.io/aslomnet/rosscortex:latest", help="Container image to arch-check against")

    start_parser = subparsers.add_parser("start", help="Start rossocortex (container by default, --local for native)")
    _add_start_args(start_parser)

    subparsers.add_parser("stop", help="Stop running rossocortex daemon")

    # `cortex` command group: `cortex start`/`cortex stop` are aliases for the
    # top-level `start`/`stop` and run the exact same code paths.
    cortex_parser = subparsers.add_parser("cortex", parents=[global_flags],
                                          help="Manage the rossocortex proxy ('cortex start|stop' == 'start|stop')")
    cortex_sub = cortex_parser.add_subparsers(dest="cortex_cmd")
    _add_start_args(cortex_sub.add_parser("start", parents=[global_flags], help="Alias for 'start'"))
    cortex_sub.add_parser("stop", parents=[global_flags], help="Alias for 'stop'")

    # `sandbox run <agent> [-- CMD...]`: create an --internal network, dual-home
    # rossocortex, and launch the agent container with the proxy as its only egress.
    sandbox_parser = subparsers.add_parser("sandbox", parents=[global_flags],
                                           help="Print commands to run an agent container fully isolated (egress only via rossocortex)")
    sandbox_sub = sandbox_parser.add_subparsers(dest="sandbox_cmd")
    sb_run = sandbox_sub.add_parser("run", parents=[global_flags],
                                    help="Print the docker/podman commands for an isolated agent container (pipe to sh to run)")
    sb_run.add_argument("agent_name", help="Registered agent whose credentials + network policy to use")
    sb_run.add_argument("--image", default="quay.io/aslomnet/agents:test", help="Container image (default: quay.io/aslomnet/agents:test)")
    sb_run.add_argument("--network", default="isolated-net", help="--internal network name (default: isolated-net)")
    sb_run.add_argument("--workspace", default=None, help="Host dir mounted at /workspace (default: current dir)")
    sb_run.add_argument("--proxy-port", type=int, default=DEFAULT_PROXY_PORT, help="Rossocortex proxy port")
    sb_run.add_argument("container_cmd", nargs=argparse.REMAINDER, metavar="-- COMMAND",
                        help="Command to run in the container (after --); default: bash")

    log_parser = subparsers.add_parser("log", aliases=["logs"], help="Show rossocortex request log")
    log_parser.add_argument("-f", "--follow", action="store_true", help="Follow log output (like tail -f)")
    log_parser.add_argument("-n", "--lines", type=int, default=20, help="Number of lines to show (default: 20)")
    log_parser.add_argument("--agent", dest="log_agent", metavar="NAME", help="Filter to specific agent")

    subparsers.add_parser("agents", help="List all registered agents (shortcut for 'agent --list')")
    agent_parser = subparsers.add_parser("agent", help="Create or retrieve agent proxy credentials")
    agent_parser.add_argument("agent_name", nargs="?", help="Agent name to register/retrieve")
    agent_parser.add_argument("--list", action="store_true", help="List all registered agents")
    agent_parser.add_argument("--delete", action="store_true", help="Delete the named agent")
    agent_parser.add_argument("--budget", default=None, help="Daily budget in USD (or 'unlimited')")
    agent_parser.add_argument("--credentials", type=str, default=None, help="Path to agent-specific credentials dir (overrides shared)")
    agent_parser.add_argument("--network-allow", action="append", dest="network_allow", metavar="HOST", help="Allowed upstream hosts (repeatable, replaces existing list)")
    agent_parser.add_argument("--network-deny", action="append", dest="network_deny", metavar="HOST", help="Denied upstream hosts (repeatable, replaces existing list)")
    agent_parser.add_argument("--proxy-port", type=int, default=DEFAULT_PROXY_PORT, help="Rossocortex proxy port")

    comp_parser = subparsers.add_parser("completions", help="Print shell completion setup for current $SHELL")
    comp_parser.add_argument("--eval", action="store_true", dest="eval_mode", help="Output raw completion code for eval")
    comp_parser.add_argument("--alias", action="append", dest="aliases", metavar="NAME", help="Also register completion for this alias (repeatable)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.runtime:
        os.environ["ROSSOCORTEX_RUNTIME"] = args.runtime

    control_url = args.control_url
    if control_url == DEFAULT_CONTROL_URL:
        state = _load_state()
        if state.get("control_port"):
            control_url = f"http://localhost:{state['control_port']}"

    if args.command == "status":
        cmd_status(control_url)
    elif args.command in ("doctor", "preflight", "checks", "requirements", "reqs"):
        cmd_doctor(args)
    elif args.command == "version":
        cmd_version(control_url)
    elif args.command == "start":
        _do_start(args)
    elif args.command == "cortex":
        cortex_cmd = getattr(args, "cortex_cmd", None)
        if cortex_cmd == "start":
            _do_start(args)
        elif cortex_cmd == "stop":
            cmd_stop()
        else:
            print("usage: rossoctlx cortex {start|stop}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "stop":
        cmd_stop()
    elif args.command in ("log", "logs"):
        cmd_log(args.follow, args.lines, args.log_agent)
    elif args.command == "agents":
        cmd_agent_id(None, DEFAULT_PROXY_PORT, True, False, None, None, None, None)
    elif args.command == "agent":
        agent_budget = args.budget
        if agent_budget is not None:
            if agent_budget.lower() == "unlimited":
                agent_budget = 0  # 0 means remove budget cap
            else:
                try:
                    agent_budget = float(agent_budget)
                except ValueError:
                    print(f"ERROR: --budget must be a number or 'unlimited', got '{agent_budget}'", file=sys.stderr)
                    sys.exit(1)
        cmd_agent_id(args.agent_name, args.proxy_port, args.list, args.delete, agent_budget, args.credentials, args.network_allow, args.network_deny)
    elif args.command == "sandbox":
        if getattr(args, "sandbox_cmd", None) != "run":
            print("usage: rossoctlx sandbox run <agent> [--image IMG] [--network NAME] [--workspace DIR] [-- CMD...]", file=sys.stderr)
            sys.exit(1)
        command = list(args.container_cmd or [])
        if command and command[0] == "--":  # argparse REMAINDER keeps the separator
            command = command[1:]
        workspace = args.workspace or os.getcwd()
        cmd_sandbox_run(args.agent_name, args.image, args.network, workspace, command, args.proxy_port)
    elif args.command == "completions":
        cmd_completions(args.eval_mode, args.aliases)


if __name__ == "__main__":
    main()
