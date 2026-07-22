#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""Rossocortex Budget Proxy — credential injection + daily spend enforcement.

Sits between clients (Claude, dummy_agent.py) and a LiteLLM gateway.
Injects API key from credentials dir, tracks x-litellm-response-cost,
and rejects requests when daily budget is exceeded.

Modes:
  Direct (default): Python HTTP proxy forwards to upstream LiteLLM.
  AuthBridge (--authbridge): Starts authbridge-proxy as subprocess for TLS
    interception. Requests route through AuthBridge which handles credential
    injection via placeholder-resolve plugin. Budget tracking still done here.

Env vars:
    ROSSOCORTEX_DAILY_BUDGET  — Daily budget in USD (default: 5.00)
    ROSSOCORTEX_UPSTREAM      — LiteLLM proxy URL (or --upstream flag)
    ROSSOCORTEX_PORT          — Listen port (default: 8180)
    ROSSOCORTEX_CREDENTIALS   — Credentials dir (default: ~/.config/rossocortex/credentials)
    ROSSOCORTEX_SPEND_FILE    — Spend ledger path (default: ~/.config/rossocortex/spend.json)

Usage (direct mode):
    ./rossocortex.py --budget 5.00 --upstream https://ete-litellm.ai-models.vpc-int.res.ibm.com

Usage (authbridge mode):
    ./rossocortex.py --budget 5.00 --authbridge --upstream https://ete-litellm.ai-models.vpc-int.res.ibm.com

Then point your client at this proxy:
    OPENAI_API_BASE=http://localhost:8180 OPENAI_API_KEY=passthrough ./dummy_agent.py
"""
from __future__ import annotations

import argparse
import atexit
import base64
import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

ROSSOCORTEX_VERSION = "0.2.2"  # keep in sync with rossoctlx CLI (scripts/pyproject.toml)
DEFAULT_PORT = 8180
DEFAULT_CONTROL_PORT = 8181
DEFAULT_BUDGET = 5.00
AUTHBRIDGE_PORT = 3130
SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_INFO_PATH = SCRIPT_DIR / "BUILD_INFO.json"
_xdg_config = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
CONFIG_DIR = Path(os.environ.get("ROSSOCORTEX_CONFIG_DIR", str(Path(_xdg_config) / "rossocortex")))
CREDENTIALS_DIR = Path(os.environ.get("ROSSOCORTEX_CREDENTIALS", CONFIG_DIR / "credentials"))
SPEND_FILE = Path(os.environ.get("ROSSOCORTEX_SPEND_FILE", CONFIG_DIR / "spend.json"))
AGENTS_FILE = CONFIG_DIR / "agents.json"

_spend_lock = threading.Lock()
LOG_FILE = CONFIG_DIR / "rossocortex.log"
LOG_MAX_DAYS = 10
_log_last_date: str = ""


def _rotate_log_if_needed():
    """Rotate log file daily. Keeps up to LOG_MAX_DAYS old files."""
    global _log_last_date
    today = _today_utc()
    if _log_last_date == today:
        return
    _log_last_date = today
    if not LOG_FILE.exists():
        return
    try:
        first_line = ""
        with open(LOG_FILE) as f:
            first_line = f.readline()
        if first_line and not first_line.startswith(today):
            rotated = LOG_FILE.with_suffix(f".{first_line[:10]}.log")
            LOG_FILE.rename(rotated)
            old_logs = sorted(LOG_FILE.parent.glob("rossocortex.*.log"), reverse=True)
            for old in old_logs[LOG_MAX_DAYS:]:
                old.unlink(missing_ok=True)
    except OSError:
        pass


def _log_request(agent: str, method: str, path: str, status: int, cost: float = 0.0, model: str = "", credential_injected: bool = False, denied_reason: str = ""):
    """Append a structured log line for the request."""
    _rotate_log_if_needed()
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    parts = [ts, f"agent={agent}", f"{method} {path}", f"status={status}"]
    if model:
        parts.append(f"model={model}")
    if cost > 0:
        parts.append(f"cost=${cost:.6f}")
    if credential_injected:
        parts.append("cred=injected")
    if denied_reason:
        parts.append(f"denied={denied_reason}")
    line = "  ".join(parts) + "\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except OSError:
        pass


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_spend() -> dict:
    if not SPEND_FILE.exists():
        return {"date": _today_utc(), "total_spend": 0.0, "total_calls": 0, "calls": []}
    data = json.loads(SPEND_FILE.read_text())
    if data.get("date") != _today_utc():
        return {"date": _today_utc(), "total_spend": 0.0, "total_calls": 0, "calls": []}
    return data


def _save_spend(data: dict):
    SPEND_FILE.parent.mkdir(parents=True, exist_ok=True)
    SPEND_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _record_cost(cost: float, model: str = "", agent: str = "anonymous"):
    with _spend_lock:
        data = _load_spend()
        data["total_spend"] += cost
        data["total_calls"] += 1
        data["calls"].append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model,
            "cost": cost,
            "agent": agent,
        })
        _save_spend(data)
    if agent not in ("anonymous", "unknown"):
        _record_agent_cost(agent, cost, model)


def _agent_spend_file(agent_name: str) -> Path:
    return CONFIG_DIR / f"spend-{agent_name}.json"


def _load_agent_spend(agent_name: str) -> dict:
    path = _agent_spend_file(agent_name)
    if not path.exists():
        return {"date": _today_utc(), "total_spend": 0.0, "total_calls": 0, "calls": []}
    data = json.loads(path.read_text())
    if data.get("date") != _today_utc():
        return {"date": _today_utc(), "total_spend": 0.0, "total_calls": 0, "calls": []}
    return data


def _save_agent_spend(agent_name: str, data: dict):
    path = _agent_spend_file(agent_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _record_agent_cost(agent_name: str, cost: float, model: str = ""):
    with _spend_lock:
        data = _load_agent_spend(agent_name)
        data["total_spend"] += cost
        data["total_calls"] += 1
        data["calls"].append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model,
            "cost": cost,
        })
        _save_agent_spend(agent_name, data)


def _get_agent_daily_spend(agent_name: str) -> float:
    with _spend_lock:
        data = _load_agent_spend(agent_name)
        return data["total_spend"]


def _get_agent_budget(agent_name: str) -> float | None:
    agents = _load_agents_registry()
    agent = agents.get(agent_name, {})
    budget = agent.get("budget")
    return float(budget) if budget else None


def _get_daily_spend() -> float:
    with _spend_lock:
        data = _load_spend()
        return data["total_spend"]


def _load_credential() -> str | None:
    # Check files first, then env vars. Order: LiteLLM-specific, then ANTHROPIC_AUTH_TOKEN (often the LiteLLM virtual key), then others.
    search_order = ("LITELLM_API_KEY", "ROSSOCORTEX_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    for name in search_order:
        cred_file = CREDENTIALS_DIR / name
        if cred_file.exists():
            return cred_file.read_text().strip()
    for name in search_order:
        val = os.environ.get(name)
        if val:
            return val
    return None


def _extract_model_from_body(body: bytes) -> str:
    try:
        data = json.loads(body)
        return data.get("model", "")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""


def _load_agents_registry() -> dict:
    if not AGENTS_FILE.exists():
        return {}
    try:
        data = json.loads(AGENTS_FILE.read_text())
        return data.get("agents", {})
    except (json.JSONDecodeError, OSError):
        return {}


def _extract_agent_identity(auth_header: str | None, api_key_header: str | None = None, proxy_auth_header: str | None = None) -> str:
    """Extract agent name from auth headers.

    Checks (in order):
    1. Proxy-Authorization: Basic <base64(name:token)> — from HTTPS_PROXY userinfo
    2. Authorization: Basic <base64(name:token)> — from URL userinfo (httpx/curl)
    3. Authorization: Bearer name:token — direct agent key
    4. x-api-key: name:token — Claude Code style
    """
    if proxy_auth_header and proxy_auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(proxy_auth_header[6:]).decode("utf-8")
            if ":" in decoded:
                return _verify_agent_token(decoded)
        except (ValueError, UnicodeDecodeError):
            pass

    if auth_header:
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                if ":" in decoded:
                    return _verify_agent_token(decoded)
            except (ValueError, UnicodeDecodeError):
                pass
        elif auth_header.startswith("Bearer "):
            val = auth_header[7:]
            if ":" in val and not val.startswith("sk-"):
                return _verify_agent_token(val)

    if api_key_header and ":" in api_key_header and not api_key_header.startswith("sk-"):
        return _verify_agent_token(api_key_header)

    return "anonymous"


def _verify_agent_token(name_token: str) -> str:
    """Verify name:token against agents registry. Returns agent name or 'unknown'."""
    try:
        agent_name, token = name_token.split(":", 1)
        agents = _load_agents_registry()
        if agent_name in agents and agents[agent_name].get("token") == token:
            return agent_name
        if agent_name and not agents:
            return agent_name
        return "unknown"
    except ValueError:
        return "anonymous"


def _check_network_policy(agent_name: str, target_host: str) -> str | None:
    """Check if agent is allowed to access target_host. Returns error message or None."""
    agents = _load_agents_registry()
    agent = agents.get(agent_name)
    if not agent:
        return None

    deny_list = agent.get("network_deny", [])
    allow_list = agent.get("network_allow", [])

    if not deny_list and not allow_list:
        return None

    from fnmatch import fnmatch
    host = target_host.split(":")[0].lower()

    for pattern in deny_list:
        if fnmatch(host, pattern.lower()):
            return f"host '{host}' is denied by network policy (matches deny pattern '{pattern}')"

    if allow_list:
        for pattern in allow_list:
            if fnmatch(host, pattern.lower()):
                return None
        return f"host '{host}' is not in the allow list for agent '{agent_name}'"

    return None


class BudgetProxyHandler(BaseHTTPRequestHandler):
    upstream: str
    daily_budget: float
    credential: str | None
    authbridge_proxy: str | None  # e.g. "http://localhost:3128"
    ssl_cert_file: str | None  # CA bundle for AuthBridge TLS interception
    upstream_insecure: bool = False  # ROSSOCORTEX_UPSTREAM_INSECURE — skip TLS verify to upstream

    def log_message(self, format, *args):
        spend = _get_daily_spend()
        sys.stderr.write(f"[rossocortex] {format % args}  [${spend:.4f}/${self.daily_budget:.2f}]\n")

    def _send_budget_error(self, agent: str = "", agent_spend: float = 0.0, agent_budget: float = 0.0):
        global_spend = _get_daily_spend()
        if agent and agent_budget > 0:
            msg = f"Rossocortex ExceededTokenBudget: agent '{agent}' daily spend ${agent_spend:.4f} exceeds budget ${agent_budget:.2f}. Reset at midnight UTC."
        else:
            msg = f"Rossocortex ExceededTokenBudget: daily spend ${global_spend:.4f} exceeds budget ${self.daily_budget:.2f}. Reset at midnight UTC."
        error_body = json.dumps({
            "error": {
                "message": msg,
                "type": "budget_exceeded",
                "param": None,
                "code": "429",
            }
        }).encode()
        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(error_body)))
        self.send_header("X-Rossocortex-Daily-Spend", f"{global_spend:.6f}")
        self.send_header("X-Rossocortex-Daily-Budget", f"{self.daily_budget:.2f}")
        if agent:
            self.send_header("X-Rossocortex-Agent", agent)
        self.end_headers()
        self.wfile.write(error_body)

    def do_CONNECT(self):
        """Handle HTTPS_PROXY CONNECT tunnels — enforce agent identity before tunneling."""
        agent = _extract_agent_identity(
            self.headers.get("Authorization"),
            self.headers.get("x-api-key"),
            self.headers.get("Proxy-Authorization"),
        )
        if agent in ("anonymous", "unknown"):
            _log_request(agent, "CONNECT", self.path, 407, denied_reason="unidentified_agent")
            self.send_response(407)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Proxy authentication required. Use HTTPS_PROXY=http://agent:token@host:port\n")
            return

        host, _, port = self.path.partition(":")
        port = int(port) if port else 443

        policy_error = _check_network_policy(agent, host)
        if policy_error:
            _log_request(agent, "CONNECT", self.path, 403, denied_reason=f"network_policy:{host}")
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Rossocortex NetworkPolicy: {policy_error}\n".encode())
            return

        _log_request(agent, "CONNECT", self.path, 200)
        import socket
        try:
            upstream = socket.create_connection((host, port), timeout=10)
        except OSError as e:
            _log_request(agent, "CONNECT", self.path, 502, denied_reason=f"connect_failed:{e}")
            self.send_response(502)
            self.end_headers()
            return

        self.send_response(200, "Connection Established")
        self.end_headers()

        import select
        client_conn = self.connection
        try:
            while True:
                rlist, _, _ = select.select([client_conn, upstream], [], [], 60)
                if not rlist:
                    break
                for sock in rlist:
                    data = sock.recv(65536)
                    if not data:
                        raise ConnectionError
                    if sock is client_conn:
                        upstream.sendall(data)
                    else:
                        client_conn.sendall(data)
        except (ConnectionError, OSError):
            pass
        finally:
            upstream.close()

    def do_GET(self):
        self._proxy_request("GET")

    def do_POST(self):
        self._proxy_request("POST")

    def do_PUT(self):
        self._proxy_request("PUT")

    def do_DELETE(self):
        self._proxy_request("DELETE")

    def do_PATCH(self):
        self._proxy_request("PATCH")

    def do_OPTIONS(self):
        self._proxy_request("OPTIONS")

    def _proxy_request(self, method: str):
        current_spend = _get_daily_spend()
        if current_spend >= self.daily_budget:
            _log_request("global", method, self.path, 429, denied_reason="budget_exceeded")
            self._send_budget_error()
            return

        agent = _extract_agent_identity(
            self.headers.get("Authorization"),
            self.headers.get("x-api-key"),
            self.headers.get("Proxy-Authorization"),
        )

        if agent in ("anonymous", "unknown"):
            _log_request(agent, method, self.path, 401, denied_reason="unidentified_agent")
            error_body = json.dumps({
                "error": {
                    "message": "Rossocortex: agent identity required. Use agent_name:token as API key (see: rossoctlx.py agent <name>).",
                    "type": "auth_error",
                    "param": None,
                    "code": "401",
                }
            }).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(error_body)))
            self.end_headers()
            self.wfile.write(error_body)
            return

        if True:
            agent_budget = _get_agent_budget(agent)
            if agent_budget is not None:
                agent_spend = _get_agent_daily_spend(agent)
                if agent_spend >= agent_budget:
                    _log_request(agent, method, self.path, 429, denied_reason="agent_budget_exceeded")
                    self._send_budget_error(agent, agent_spend, agent_budget)
                    return

            # LLM calls arrive on localhost and are forwarded to the configured
            # upstream — that IS the proxy's purpose, so the upstream is always
            # allowed and not subject to the per-agent network policy. The policy
            # governs only arbitrary *other* hosts (e.g. a plain-HTTP request
            # proxied to a non-upstream Host); the CONNECT path enforces it for
            # HTTPS tunnels.
            req_host = self.headers.get("Host", "").split(":")[0]
            policy_error = None
            if req_host not in ("localhost", "127.0.0.1", ""):
                policy_error = _check_network_policy(agent, req_host)
            if policy_error:
                _log_request(agent, method, self.path, 403, denied_reason=f"network_policy:{req_host}")
                error_body = json.dumps({
                    "error": {
                        "message": f"Rossocortex NetworkPolicy: {policy_error}",
                        "type": "network_policy_denied",
                        "param": None,
                        "code": "403",
                    }
                }).encode()
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(error_body)))
                self.send_header("X-Rossocortex-Agent", agent)
                self.end_headers()
                self.wfile.write(error_body)
                return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        model = _extract_model_from_body(body) if body else ""

        headers = {}
        for key in self.headers:
            if key.lower() in ("host", "content-length", "transfer-encoding", "authorization", "proxy-authorization"):
                continue
            headers[key] = self.headers[key]

        if self.credential:
            headers["Authorization"] = f"Bearer {self.credential}"

        url = f"{self.upstream}{self.path}"

        try:
            client_kwargs = {"timeout": 120.0, "follow_redirects": True}
            agent_proxy = None
            if agent not in ("anonymous", "unknown"):
                agent_proxy = _ensure_authbridge_for_agent(agent)
            proxy = agent_proxy or self.authbridge_proxy
            if proxy:
                client_kwargs["proxy"] = proxy
            # TLS verification for the hop rossocortex controls. When
            # ROSSOCORTEX_UPSTREAM_INSECURE is set, the upstream is internal/
            # self-signed: AuthBridge owns+MITMs it via tls_bridge.upstream_insecure
            # when its bridge handshake succeeds; but the bridge can fall back to
            # passthrough (then rossocortex sees the real self-signed cert), so we
            # also skip verification here as the safety net. Otherwise trust the
            # AuthBridge MITM CA bundle (combined-ca).
            if self.upstream_insecure:
                client_kwargs["verify"] = False
            elif self.ssl_cert_file:
                client_kwargs["verify"] = self.ssl_cert_file
            with httpx.Client(**client_kwargs) as client:
                resp = client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    content=body if body else None,
                )
        except httpx.HTTPError as e:
            _log_request(agent, method, self.path, 502, denied_reason=f"upstream_error:{e}")
            error_body = json.dumps({"error": {"message": f"Rossocortex upstream error: {e}", "type": "proxy_error", "code": "502"}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(error_body)))
            self.end_headers()
            self.wfile.write(error_body)
            return

        cost_header = resp.headers.get("x-litellm-response-cost")
        cost = 0.0
        if cost_header:
            try:
                cost = float(cost_header)
                _record_cost(cost, model, agent)
            except ValueError:
                pass

        _log_request(agent, method, self.path, resp.status_code, cost=cost, model=model, credential_injected=bool(self.credential))

        self.send_response(resp.status_code)
        skip_headers = {"transfer-encoding", "content-encoding", "content-length"}
        for key, value in resp.headers.items():
            if key.lower() in skip_headers:
                continue
            self.send_header(key, value)

        new_spend = _get_daily_spend()
        self.send_header("X-Rossocortex-Daily-Spend", f"{new_spend:.6f}")
        self.send_header("X-Rossocortex-Daily-Budget", f"{self.daily_budget:.2f}")
        if cost > 0:
            self.send_header("X-Rossocortex-Request-Cost", f"{cost:.6f}")

        response_body = resp.content
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)


class ControlHandler(BaseHTTPRequestHandler):
    proxy_state: dict

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/version":
            self._handle_version()
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "not found"}).encode())

    def _handle_version(self):
        state = self.proxy_state
        spend_data = _load_spend()

        authbridge_info = None
        if state.get("mode") == "authbridge":
            build_info = None
            if BUILD_INFO_PATH.exists():
                build_info = json.loads(BUILD_INFO_PATH.read_text())
            plugins = _get_loaded_plugins(state.get("authbridge_config"))
            binary = AUTHBRIDGE_BINARY
            authbridge_info = {
                "binary": str(binary) if binary else None,
                "commit": build_info.get("authbridge_commit") if build_info else None,
                "branch": build_info.get("authbridge_branch") if build_info else None,
                "repo": build_info.get("authbridge_repo") if build_info else None,
                "go_version": build_info.get("go_version") if build_info else None,
                "built_at": build_info.get("built_at") if build_info else None,
                "platform": build_info.get("platform") if build_info else None,
                "plugins": plugins,
            }

        response = {
            "rossocortex_version": ROSSOCORTEX_VERSION,
            "mode": state.get("mode", "direct"),
            "authbridge": authbridge_info,
            "budget": {
                "daily_limit": state.get("daily_budget", DEFAULT_BUDGET),
                "spent_today": spend_data.get("total_spend", 0.0),
                "calls_today": spend_data.get("total_calls", 0),
            },
            "upstream": state.get("upstream", ""),
            "port": state.get("port", DEFAULT_PORT),
            "control_port": state.get("control_port", DEFAULT_CONTROL_PORT),
            "pid": os.getpid(),
        }

        body = json.dumps(response, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _get_loaded_plugins(config_path: str | None) -> list[str]:
    if not config_path:
        return []
    path = Path(config_path)
    if not path.exists():
        return []
    try:
        import yaml
    except ImportError:
        pass
    try:
        text = path.read_text()
        plugins = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- name:"):
                name = stripped.removeprefix("- name:").strip().strip('"').strip("'")
                plugins.append(name)
        return plugins
    except Exception:
        return []


_local_binary = SCRIPT_DIR / "bin" / "authbridge-proxy"
_system_binary = Path("/usr/local/bin/authbridge-proxy")
AUTHBRIDGE_BINARY = _local_binary if _local_binary.exists() else _system_binary
AGENTS_DIR = CONFIG_DIR / "agents"

_authbridge_procs: dict[str, subprocess.Popen] = {}
_authbridge_lock = threading.Lock()


def _localize_agent_config(config_path: Path) -> Path | None:
    """Rewrite a per-agent AuthBridge config whose paths point at a different
    config-dir (e.g. host paths, when the config was generated on the host but is
    consumed in the container). Detects the config root from `ca_dir` and remaps
    it to CONFIG_DIR. Returns a localized config path, or None on failure."""
    import re
    try:
        text = config_path.read_text()
        m = re.search(r"ca_dir:\s*(\S+)", text)
        if not m:
            return config_path
        ca_dir = m.group(1)
        host_root = ca_dir[:-3] if ca_dir.endswith("/ca") else str(Path(ca_dir).parent)
        localized = text if host_root == str(CONFIG_DIR) else text.replace(host_root, str(CONFIG_DIR))

        # Make the container's runtime ROSSOCORTEX_UPSTREAM_INSECURE authoritative:
        # so AuthBridge itself owns the upstream TLS (MITM + re-originate) for a
        # self-signed upstream, rather than falling back to passthrough.
        insecure = os.environ.get("ROSSOCORTEX_UPSTREAM_INSECURE", "").lower() in ("1", "true", "yes")
        want = f"upstream_insecure: {'true' if insecure else 'false'}"
        if re.search(r"^\s*upstream_insecure:.*$", localized, flags=re.M):
            localized = re.sub(r"(?m)^(\s*)upstream_insecure:.*$", lambda mm: f"{mm.group(1)}{want}", localized)
        else:
            # Insert right after the ca_dir line (inside the tls_bridge block).
            localized = re.sub(r"(?m)^(\s*)ca_dir:.*$", lambda mm: f"{mm.group(0)}\n{mm.group(1)}{want}", localized, count=1)

        if localized == text:
            return config_path  # nothing to change
        out = config_path.parent / "config.container.yaml"
        out.write_text(localized)
        sys.stderr.write(f"[rossocortex] Localized agent config (paths -> {CONFIG_DIR}, upstream_insecure={insecure})\n")
        return out
    except OSError as e:
        sys.stderr.write(f"[rossocortex] Could not localize agent config: {e}\n")
        return None


def _ensure_authbridge_for_agent(agent_name: str) -> str | None:
    """Spawn authbridge for agent on demand. Returns forward-proxy URL or None."""
    agents = _load_agents_registry()
    agent = agents.get(agent_name)
    if not agent or "ports" not in agent:
        return None

    ports = agent["ports"]
    forward_port = ports["forward"]

    with _authbridge_lock:
        proc = _authbridge_procs.get(agent_name)
        if proc and proc.poll() is None:
            return f"http://localhost:{forward_port}"

        config_path = AGENTS_DIR / agent_name / "config.yaml"
        if not config_path.exists():
            sys.stderr.write(f"[rossocortex] No config for agent '{agent_name}' at {config_path}\n")
            return None

        # The per-agent config may have been generated on the HOST with host
        # absolute paths (e.g. /Users/.../.config/rossocortex/...). Inside the
        # container the config dir is mounted at CONFIG_DIR (/etc/rossocortex), so
        # those paths don't resolve and AuthBridge's CA init fails. Rewrite any
        # stale config-dir prefix to CONFIG_DIR before spawning.
        localized = _localize_agent_config(config_path)
        if localized is not None:
            config_path = localized

        if not AUTHBRIDGE_BINARY.exists():
            sys.stderr.write(f"[rossocortex] authbridge-proxy binary not found\n")
            return None

        sys.stderr.write(f"[rossocortex] Spawning authbridge for agent '{agent_name}' (forward-proxy=:{forward_port})\n")
        proc = subprocess.Popen(
            [str(AUTHBRIDGE_BINARY), "--config", str(config_path)],
            stdout=subprocess.DEVNULL,
            stderr=sys.stderr,
        )
        _authbridge_procs[agent_name] = proc

        import time
        time.sleep(2)
        if proc.poll() is not None:
            sys.stderr.write(f"[rossocortex] AuthBridge for '{agent_name}' exited immediately (code {proc.returncode})\n")
            del _authbridge_procs[agent_name]
            return None

        return f"http://localhost:{forward_port}"


def _shutdown_all_authbridges():
    """Kill all spawned authbridge processes."""
    for name, proc in _authbridge_procs.items():
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
    for name, proc in _authbridge_procs.items():
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    _authbridge_procs.clear()


def _find_free_port_from(start: int) -> int:
    """Find a free port starting from `start`."""
    import socket
    for candidate in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", candidate)) != 0:
                return candidate
    return start


def _generate_config(config_path: Path, budget: float) -> int:
    """Always regenerate authbridge config.yaml with current CONFIG_DIR paths and free ports.
    Returns the authbridge forward-proxy port."""
    ca_dir = CONFIG_DIR / "ca"
    creds_dir = CREDENTIALS_DIR
    spend_file = CONFIG_DIR / "spend-authbridge.json"

    forward_port = _find_free_port_from(AUTHBRIDGE_PORT)
    reverse_port = _find_free_port_from(forward_port + 1)
    transparent_port = _find_free_port_from(reverse_port + 1)
    stats_port = _find_free_port_from(transparent_port + 1)
    session_port = _find_free_port_from(stats_port + 1)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(f"""mode: proxy-sidecar

listener:
  reverse_proxy_addr: ":{reverse_port}"
  forward_proxy_addr: "0.0.0.0:{forward_port}"
  transparent_proxy_addr: ":{transparent_port}"
  reverse_proxy_backend: "http://127.0.0.1:1"
  session_api_addr: ":{session_port}"

tls_bridge:
  mode: enabled
  ca_dir: {ca_dir}
  ports: [443]

session:
  enabled: true

stats:
  address: ":{stats_port}"

pipeline:
  outbound:
    plugins:
      - name: placeholder-resolve
        config:
          source: secret_dir
          secret_dir: {creds_dir}
      - name: inference-parser
      - name: mcp-parser
  inbound:
    plugins:
      - name: litellm-budget-track
        config:
          spend_file: {spend_file}
          max_budget: {budget}
""")
    return forward_port


def _start_authbridge(config_path: Path) -> subprocess.Popen:
    if not AUTHBRIDGE_BINARY.exists():
        print("ERROR: authbridge-proxy binary not found.", file=sys.stderr)
        print(f"  Expected: {AUTHBRIDGE_BINARY}", file=sys.stderr)
        print(f"  Run: uv run python authbridge_wrapper.py build", file=sys.stderr)
        sys.exit(1)
    if not config_path.exists():
        print(f"ERROR: AuthBridge config not found at {config_path}", file=sys.stderr)
        print(f"  Run: uv run python authbridge_wrapper.py init --budget <amount>", file=sys.stderr)
        sys.exit(1)
    proc = subprocess.Popen(
        [str(AUTHBRIDGE_BINARY), "--config", str(config_path)],
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    return proc


def main():
    parser = argparse.ArgumentParser(description="Rossocortex Budget Proxy")
    parser.add_argument("--budget", type=float, default=float(os.environ.get("ROSSOCORTEX_DAILY_BUDGET", DEFAULT_BUDGET)), help="Daily budget in USD")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ROSSOCORTEX_PORT", DEFAULT_PORT)), help="Listen port")
    parser.add_argument("--upstream", default=os.environ.get("ROSSOCORTEX_UPSTREAM") or os.environ.get("ANTHROPIC_BASE_URL") or os.environ.get("OPENAI_API_BASE", ""), help="Upstream LiteLLM URL")
    parser.add_argument("--control-port", type=int, default=int(os.environ.get("ROSSOCORTEX_CONTROL_PORT", DEFAULT_CONTROL_PORT)), help="Control API port")
    parser.add_argument("--authbridge", action="store_true", default=True, help="Route requests through AuthBridge (default)")
    parser.add_argument("--no-authbridge", dest="authbridge", action="store_false", help="Direct mode: Python HTTP proxy without AuthBridge")
    parser.add_argument("--authbridge-config", type=str, default=str(CONFIG_DIR / "config.yaml"), help="AuthBridge config.yaml path")
    parser.add_argument("--authbridge-port", type=int, default=AUTHBRIDGE_PORT, help="AuthBridge forward proxy port")
    args = parser.parse_args()

    authbridge_proc = None

    if args.authbridge:
        if not args.upstream:
            print("ERROR: Set --upstream or ROSSOCORTEX_UPSTREAM or ANTHROPIC_BASE_URL", file=sys.stderr)
            sys.exit(1)
        config_path = Path(args.authbridge_config)
        ab_port = _generate_config(config_path, args.budget)
        args.authbridge_port = ab_port
        print("Starting AuthBridge subprocess...", file=sys.stderr)
        authbridge_proc = _start_authbridge(config_path)
        import time
        time.sleep(2)
        if authbridge_proc.poll() is not None:
            print(f"ERROR: AuthBridge exited immediately (code {authbridge_proc.returncode})", file=sys.stderr)
            sys.exit(1)
        upstream = args.upstream.rstrip("/")
        print(f"  AuthBridge running (pid={authbridge_proc.pid}, forward-proxy=:{args.authbridge_port})")
        print(f"  Clients using HTTPS_PROXY=http://localhost:{args.authbridge_port} get TLS interception + plugins.")
        print(f"  Budget proxy routes through AuthBridge forward-proxy to {upstream}")
    else:
        if not args.upstream:
            print("ERROR: Set --upstream or ROSSOCORTEX_UPSTREAM or ANTHROPIC_BASE_URL", file=sys.stderr)
            sys.exit(1)
        upstream = args.upstream.rstrip("/")

    credential = _load_credential()

    if not credential:
        print("ERROR: No credential found. Cannot start without an API key.", file=sys.stderr)
        print(f"  Checked files: {CREDENTIALS_DIR}/LITELLM_API_KEY, ROSSOCORTEX_API_KEY, OPENAI_API_KEY, ...", file=sys.stderr)
        print(f"  Checked env:   LITELLM_API_KEY, ROSSOCORTEX_API_KEY, OPENAI_API_KEY, ANTHROPIC_AUTH_TOKEN", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"  The key must be a LiteLLM virtual key (registered on the proxy), NOT a raw provider key.", file=sys.stderr)
        print(f"  Fix: export LITELLM_API_KEY=sk-...", file=sys.stderr)
        print(f"   or: echo 'sk-...' > {CREDENTIALS_DIR}/LITELLM_API_KEY", file=sys.stderr)
        sys.exit(1)

    current_spend = _get_daily_spend()

    print(f"Rossocortex Budget Proxy")
    print(f"  Mode:       {'authbridge' if args.authbridge else 'direct'}")
    print(f"  Listen:     http://localhost:{args.port}")
    print(f"  Upstream:   {upstream}")
    print(f"  Budget:     ${args.budget:.2f}/day")
    print(f"  Spent today: ${current_spend:.4f}")
    cred_display = f"loaded ({credential[:7]}...{credential[-4:]})" if credential else "NONE"
    print(f"  Credential: {cred_display}")
    print(f"  Spend file: {SPEND_FILE}")
    print(f"")
    print(f"Point your client at this proxy:")
    print(f"  export OPENAI_API_BASE=http://localhost:{args.port}")
    print(f"  export OPENAI_API_KEY=passthrough")
    if args.authbridge:
        ca_cert = CONFIG_DIR / "ca" / "tls.crt"
        print(f"")
        print(f"Or use AuthBridge forward proxy directly (TLS interception):")
        print(f"  export HTTPS_PROXY=http://localhost:{args.authbridge_port}")
        print(f"  export SSL_CERT_FILE={CONFIG_DIR / 'ca' / 'combined-ca.pem'}")
    print(f"---")

    BudgetProxyHandler.upstream = upstream
    BudgetProxyHandler.daily_budget = args.budget
    BudgetProxyHandler.credential = credential
    BudgetProxyHandler.upstream_insecure = os.environ.get("ROSSOCORTEX_UPSTREAM_INSECURE", "").lower() in ("1", "true", "yes")
    if BudgetProxyHandler.upstream_insecure:
        print(f"  ⚠ ROSSOCORTEX_UPSTREAM_INSECURE=1 — TLS verification to the upstream is DISABLED")
    if args.authbridge:
        ca_combined = CONFIG_DIR / "ca" / "combined-ca.pem"
        BudgetProxyHandler.authbridge_proxy = f"http://localhost:{args.authbridge_port}"
        BudgetProxyHandler.ssl_cert_file = str(ca_combined) if ca_combined.exists() else str(CONFIG_DIR / "ca" / "tls.crt")
    else:
        BudgetProxyHandler.authbridge_proxy = None
        BudgetProxyHandler.ssl_cert_file = None

    # Start control API server in background thread
    ControlHandler.proxy_state = {
        "mode": "authbridge" if args.authbridge else "direct",
        "upstream": upstream,
        "port": args.port,
        "control_port": args.control_port,
        "daily_budget": args.budget,
        "authbridge_config": args.authbridge_config if args.authbridge else None,
    }
    control_server = HTTPServer(("0.0.0.0", args.control_port), ControlHandler)
    control_thread = threading.Thread(target=control_server.serve_forever, daemon=True)
    control_thread.start()
    print(f"  Control API: http://localhost:{args.control_port}/version")

    def _cleanup():
        _shutdown_all_authbridges()
        if authbridge_proc and authbridge_proc.poll() is None:
            authbridge_proc.send_signal(signal.SIGTERM)
            try:
                authbridge_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                authbridge_proc.kill()

    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    server = HTTPServer(("0.0.0.0", args.port), BudgetProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
        control_server.shutdown()


if __name__ == "__main__":
    main()
