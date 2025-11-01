# Assisted by watsonx Code Assistant
# Copyright 2025 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import json
import os
import logging
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
import time
import re
from urllib.parse import urlparse, unquote
import shutil

import typer
import yaml
import requests
from jsonschema import ValidationError, validate
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from .progress import ProgressManager, Step

app = typer.Typer(add_completion=False)
console = Console()
logger = logging.getLogger("kinst")


def load_env_file(path: Path) -> Dict[str, str]:
    """Load a simple .env file (KEY=VALUE lines) into a dict.

    Lines starting with # are ignored. Values may be quoted and will be unquoted.
    """
    env: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"failed to read env file {path}: {e}")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        # strip optional surrounding quotes
        if (v.startswith('"') and v.endswith('"')) or (
            v.startswith("'") and v.endswith("'")
        ):
            v = v[1:-1]
        env[k] = v
    return env


def _maybe_path_arg(p: Any) -> Optional[Path]:
    """Normalize a CLI path-like argument that may be a Path, str, or a Typer/OptionInfo default.

    When functions are called directly in tests, Typer keeps OptionInfo objects as default values.
    This helper returns a Path when the value is a Path or str, and None otherwise.
    """
    if p is None:
        return None
    if isinstance(p, Path):
        return p
    if isinstance(p, str):
        return Path(p)
    # unknown (likely Typer OptionInfo) -> treat as not provided
    return None


# support ${VAR} and shell-style defaults ${VAR:-default}
ENV_VAR_RE = re.compile(r"\$\{([A-Za-z0-9_]+)(:-([^}]*))?\}")


def substitute_env_vars(
    obj: Any, env_map: Dict[str, str], allow_missing: bool = False
) -> Any:
    """Recursively substitute ${VAR} occurrences in strings within obj using env_map.

    If `allow_missing` is False (default) raise RuntimeError when a referenced variable is missing.
    If `allow_missing` is True, leave the ${VAR} placeholder unchanged when missing.
    """
    if isinstance(obj, dict):
        return {
            k: substitute_env_vars(v, env_map, allow_missing=allow_missing)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [
            substitute_env_vars(v, env_map, allow_missing=allow_missing) for v in obj
        ]
    if isinstance(obj, str):

        def _repl(m: re.Match) -> str:
            name = m.group(1)
            default = m.group(3)  # may be None
            if name in os.environ:
                return os.environ[name]
            if name in env_map:
                return env_map[name]
            if default is not None:
                return default
            if allow_missing:
                # leave the placeholder unchanged when allowed
                return m.group(0)
            raise RuntimeError(
                f"environment variable '{name}' referenced in values.yaml not set and not provided in env file"
            )

        return ENV_VAR_RE.sub(_repl, obj)
    return obj


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_nodes_from_compobj(comp_obj: dict, val_obj: dict) -> list:
    """Build a flat list of nodes from the `installables` list preserving the
    sequential order in the file. Each node is a dict containing at least:
    type, id, raw (original dict), and index (original position).
    """
    nodes = []
    idx = 0
    for item in comp_obj.get("installables", []):
        ntype = item.get("type")
        nodes.append({"type": ntype, "id": item.get("id"), "raw": item, "index": idx})
        idx += 1
    return nodes


def compute_execution_order(comp_obj: dict, val_obj: dict) -> list:
    """Compute execution order for installables honoring optional `dependsOn` and
    otherwise using file order as the tie-breaker.

    Returns a list of node dicts in execution order. Raises RuntimeError on missing
    dependsOn targets or on dependency cycles.
    """
    nodes = _build_nodes_from_compobj(comp_obj, val_obj)
    # map id -> node
    id_map = {n["id"]: n for n in nodes}

    # adjacency list: dep -> set(dependents)
    adj: Dict[str, set] = {n["id"]: set() for n in nodes}
    indeg: Dict[str, int] = {n["id"]: 0 for n in nodes}

    # Build edges from dependsOn -> node
    for n in nodes:
        raw = n["raw"]
        did = raw.get("dependsOn")
        if not did:
            continue
        # support string or list
        deps = [did] if isinstance(did, str) else list(did)
        for dep in deps:
            if dep not in id_map:
                raise RuntimeError(f"dependsOn references unknown component id: {dep}")
            adj[dep].add(n["id"])
            indeg[n["id"]] += 1

    # Kahn's algorithm: start with zero indegree nodes, prefer lower original index
    zero = [nid for nid, d in indeg.items() if d == 0]
    # sort zero by original index
    zero.sort(key=lambda nid: id_map[nid]["index"]) if zero else None

    result = []
    import collections

    queue = collections.deque(zero)
    while queue:
        cur = queue.popleft()
        result.append(id_map[cur])
        for neigh in sorted(adj[cur], key=lambda nid: id_map[nid]["index"]):
            indeg[neigh] -= 1
            if indeg[neigh] == 0:
                # insert preserving file order relative to other zero-indegree nodes
                # find position to keep queue ordered by index
                inserted = False
                for i, qn in enumerate(queue):
                    if id_map[neigh]["index"] < id_map[qn]["index"]:
                        queue.insert(i, neigh)
                        inserted = True
                        break
                if not inserted:
                    queue.append(neigh)

    if len(result) != len(nodes):
        # cycle detected
        remaining = set(id_map.keys()) - set(n["id"] for n in result)
        raise RuntimeError(
            f"dependency cycle detected among: {', '.join(sorted(remaining))}"
        )

    return result


def resolve_path(values: Dict[str, Any], path: Optional[str]) -> Optional[Any]:
    if not path:
        return None
    node = values
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node


def eval_condition(values: Dict[str, Any], condition: Optional[str]) -> bool:
    if not condition:
        return True
    val = resolve_path(values, condition)
    return bool(val)


def resolve_repo_credentials(
    spec: Optional[dict], values: Dict[str, Any]
) -> Optional[Dict[str, str]]:
    """Resolve repository credentials spec into a concrete credentials dict.

    The `spec` can be either a dict with literal keys (username/password/token)
    or a dict that has usernamePath/passwordPath/tokenPath which are dotted paths
    into the provided `values` mapping. Returns None when no credentials found.
    """
    if not spec or not isinstance(spec, dict):
        return None
    creds: Dict[str, str] = {}
    # direct literals
    if "username" in spec and spec.get("username"):
        creds["username"] = spec.get("username")
    if "password" in spec and spec.get("password"):
        creds["password"] = spec.get("password")
    if "token" in spec and spec.get("token"):
        creds["token"] = spec.get("token")

    # paths into values (higher precedence over empties)
    upath = spec.get("usernamePath") or spec.get("username_path")
    ppath = spec.get("passwordPath") or spec.get("password_path")
    tpath = spec.get("tokenPath") or spec.get("token_path")
    if upath:
        v = resolve_path(values, upath)
        if v:
            creds["username"] = v
    if ppath:
        v = resolve_path(values, ppath)
        if v:
            creds["password"] = v
    if tpath:
        v = resolve_path(values, tpath)
        if v:
            creds["token"] = v

    return creds if creds else None


def run_cmd(
    cmd: Sequence[str], input_data: Optional[bytes] = None, check: bool = True
) -> subprocess.CompletedProcess:
    logger.debug("running command: %s", shlex.join(cmd))
    try:
        proc = subprocess.run(
            cmd, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        logger.debug(
            "exit=%s stdout=%s stderr=%s",
            proc.returncode,
            proc.stdout.decode(errors="ignore"),
            proc.stderr.decode(errors="ignore"),
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"command failed: {shlex.join(cmd)}: {proc.stderr.decode().strip()}"
            )
        return proc
    except FileNotFoundError:
        raise RuntimeError(f"command not found: {cmd[0]}")


def find_git_root() -> Optional[Path]:
    """Return the git repository root (if available) or None."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if proc.returncode == 0:
            return Path(proc.stdout.decode().strip())
    except Exception:
        pass
    return None


def resolve_input_path(p: Path) -> Path:
    """Resolve an input Path: prefer existing path, otherwise try resolving relative to the git repo root.

    This allows callers to pass paths relative to the repository root (useful when running from
    the `kagenti/kinst` subproject but wanting to reference files in the repo root).
    """
    if p.is_absolute():
        return p
    # exists relative to current working directory?
    if p.exists():
        return p
    # try git repo root
    gr = find_git_root()
    if gr:
        candidate = gr / p
        if candidate.exists():
            return candidate
    # fallback to original path (will produce a not-found error later)
    return p


def helm_upgrade_install(
    release: str,
    name: Optional[str],
    repository: Optional[str],
    chart_version: Optional[str],
    values_file: Optional[Path],
    namespace: Optional[str],
    kube_context: Optional[str],
    dry_run: bool,
    wait: bool,
    timeout: Optional[str],
    repo_credentials: Optional[Dict[str, str]] = None,
):
    """Install or upgrade a Helm chart.

    This helper supports several chart source forms:
    - local chart path (absolute or relative path, or file:// URL) -> install from path
    - http(s) tarball URL -> install from URL
    - oci:// registry -> install from OCI reference (repository/name)
    - remote Helm repo URL + chart name -> use --repo <url> <chart-name>

    The function auto-detects when to pass --repo vs a direct install target.
    """
    # Determine whether to pass a direct chart target (path/url/oci) or use --repo
    use_repo_flag = False
    install_target = name or ""

    # Helper to detect local path or file://
    def _is_local_path(s: str) -> bool:
        if not s:
            return False
        if s.startswith("file://"):
            return True
        try:
            p = Path(s)
            return p.exists()
        except Exception:
            return False

    # If repository is an OCI registry, construct an OCI install target
    if repository and repository.startswith("oci://") and name:
        install_target = f"{repository.rstrip('/')}/{name}"
    # If name itself looks like a URL (http/https/oci) or is a local path, install directly
    elif (
        install_target.startswith("http://")
        or install_target.startswith("https://")
        or install_target.startswith("oci://")
        or _is_local_path(install_target)
    ):
        # install_target is already the right value
        pass
    # Otherwise, if repository is provided and looks like an http(s) chart repo, use --repo
    elif repository:
        use_repo_flag = True

    # Build helm command
    cmd = ["helm", "upgrade", "--install", release, install_target]

    if use_repo_flag:
        # pass repo as --repo and keep the install target as chart name
        cmd = [
            "helm",
            "upgrade",
            "--install",
            release,
            install_target,
            "--repo",
            repository,
        ]

    if chart_version:
        cmd += ["--version", chart_version]
    if values_file:
        cmd += ["--values", str(values_file)]
    if namespace:
        cmd += ["--namespace", namespace, "--create-namespace"]
    if kube_context:
        cmd += ["--kube-context", kube_context]
    if dry_run:
        cmd += ["--dry-run"]
    if wait:
        cmd += ["--wait"]
    if timeout:
        cmd += ["--timeout", timeout]

    # If OCI registry, optionally perform a registry login before install
    if repository and repository.startswith("oci://"):
        # registry host is the first path segment after oci://
        host = repository[len("oci://") :].split("/")[0]

        # Resolve credentials: explicit param > env vars
        creds = repo_credentials or {}
        # env var names we accept
        env_user = os.environ.get("KINST_HELM_REGISTRY_USERNAME") or os.environ.get(
            "HELM_REGISTRY_USERNAME"
        )
        env_pass = os.environ.get("KINST_HELM_REGISTRY_PASSWORD") or os.environ.get(
            "HELM_REGISTRY_PASSWORD"
        )
        env_token = os.environ.get("KINST_HELM_REGISTRY_TOKEN") or os.environ.get(
            "HELM_REGISTRY_TOKEN"
        )
        if not creds.get("username") and env_user:
            creds["username"] = env_user
        if not creds.get("password") and env_pass:
            creds["password"] = env_pass
        if not creds.get("token") and env_token:
            creds["token"] = env_token

        # If still missing credentials and running interactively, prompt the user
        if (
            not (creds.get("username") and creds.get("password"))
            and not creds.get("token")
            and console.is_terminal
        ):
            # prompt for username/password
            try:
                user = typer.prompt(f"OCI registry username for {host}")
                pwd = typer.prompt(f"OCI registry password for {host}", hide_input=True)
                creds["username"] = user
                creds["password"] = pwd
            except Exception:
                # if prompt fails, continue without creds
                creds = creds

        if creds.get("username") and creds.get("password"):
            login_cmd = [
                "helm",
                "registry",
                "login",
                host,
                "--username",
                creds["username"],
                "--password",
                creds["password"],
            ]
            try:
                run_cmd(login_cmd)
            except Exception as e:
                # don't block install if login fails; surface a warning
                logger.warning("helm registry login failed for %s: %s", host, e)
        elif creds.get("token"):
            # Some registries accept token as password with special username; try using token as password
            login_cmd = [
                "helm",
                "registry",
                "login",
                host,
                "--username",
                "_token",
                "--password",
                creds["token"],
            ]
            try:
                run_cmd(login_cmd)
            except Exception as e:
                logger.warning(
                    "helm registry login with token failed for %s: %s", host, e
                )

    return run_cmd(cmd)


def helm_uninstall(
    release: str, namespace: Optional[str], kube_context: Optional[str], dry_run: bool
):
    cmd = ["helm", "uninstall", release]
    if namespace:
        cmd += ["--namespace", namespace]
    if kube_context:
        cmd += ["--kube-context", kube_context]
    if dry_run:
        cmd += ["--dry-run"]
    return run_cmd(cmd)


CLUSTER_SCOPED_KINDS = {
    "Namespace",
    "Node",
    "ClusterRole",
    "ClusterRoleBinding",
    "CustomResourceDefinition",
    "MutatingWebhookConfiguration",
    "ValidatingWebhookConfiguration",
    "StorageClass",
    "PersistentVolume",
}


def fetch_remote_yaml(
    url: str, base_dir: Optional[Path] = None, timeout: int = 15
) -> str:
    """Fetch a remote or local YAML.

    Supports:
    - http(s) URLs (fetched via requests)
    - file:/// absolute file URLs
    - relative filesystem paths which are resolved relative to `base_dir` when provided
      (this allows paths relative to the location of the installables.yaml file).
    """
    if not url:
        raise RuntimeError("empty url for kubectl apply")
    logger.debug(
        "fetching url: %s (base_dir=%s)", url, str(base_dir) if base_dir else None
    )

    # file:// absolute URL
    parsed = urlparse(url)
    if parsed.scheme == "file":
        # file URL. Use urllib to handle any percent-encoding and paths.
        path_str = unquote(parsed.path)
        p = Path(path_str)
        # direct absolute path
        if p.exists():
            return p.read_text(encoding="utf-8")
        # if not found and base_dir provided, try resolving the path relative to base_dir
        if base_dir:
            # if the file URL was like file:///manifests/foo -> parsed.path='/manifests/foo'
            # we try base_dir / 'manifests/foo'
            rel = path_str.lstrip("/")
            candidate = (base_dir / rel).resolve()
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        raise RuntimeError(
            f"file not found: {p} (and no relative file found under {base_dir})"
        )

    # http(s) URL
    if url.startswith("http://") or url.startswith("https://"):
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text

    # otherwise treat as filesystem path; prefer resolving relative to base_dir
    p = Path(url)
    # relative path and base_dir provided -> resolve against base_dir
    if not p.is_absolute() and base_dir:
        candidate = (base_dir / p).resolve()
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")

    # fall back to resolving via repo-aware resolver
    candidate = resolve_input_path(p)
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")

    raise RuntimeError(f"could not fetch url or file: {url}")


def inject_namespace_to_yaml(yaml_text: str, namespace: Optional[str]) -> str:
    if not namespace:
        return yaml_text
    docs = list(yaml.safe_load_all(yaml_text))
    out_docs = []
    for doc in docs:
        if not isinstance(doc, dict):
            out_docs.append(doc)
            continue
        kind = doc.get("kind")
        if kind in CLUSTER_SCOPED_KINDS:
            out_docs.append(doc)
            continue
        metadata = doc.setdefault("metadata", {})
        if "namespace" not in metadata:
            metadata["namespace"] = namespace
        out_docs.append(doc)
    return "---\n".join(yaml.safe_dump(d, sort_keys=False) for d in out_docs)


def kubectl_apply(yaml_text: str, kube_context: Optional[str], dry_run: bool):
    cmd = ["kubectl", "apply", "-f", "-"]
    if kube_context:
        cmd += ["--context", kube_context]
    if dry_run:
        cmd += ["--dry-run=client"]
    return run_cmd(cmd, input_data=yaml_text.encode("utf-8"))


def kubectl_delete(
    yaml_text: str,
    kube_context: Optional[str],
    ignore_not_found: bool = True,
    dry_run: bool = False,
):
    cmd = ["kubectl", "delete", "-f", "-"]
    if kube_context:
        cmd += ["--context", kube_context]
    if ignore_not_found:
        cmd += ["--ignore-not-found"]
    if dry_run:
        cmd += ["--dry-run=client"]
    return run_cmd(cmd, input_data=yaml_text.encode("utf-8"))


@app.command()
def plan(
    installables: Path = typer.Option(
        Path("kinst/samples/installables.yaml"),
        "-f",
        "--installables",
        help="installables file",
    ),
    values: Path = typer.Option(
        Path("kinst/samples/values.yaml"), "-v", "--values", help="values file"
    ),
    env_file: Optional[Path] = typer.Option(
        None, "-e", "--env-file", help=".env file to load environment variables from"
    ),
    allow_missing_env: bool = typer.Option(
        False,
        "--allow-missing-env",
        help="Allow unresolved ${VAR} placeholders (leave them unchanged)",
    ),
    schema: Path = typer.Option(
        Path("docs/schema/installables.schema.json"),
        "-s",
        "--schema",
        help="schema file",
    ),
    verbose: bool = False,
):
    """Validate and print a non-destructive plan of installables to apply."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)

    # resolve input paths (allow files relative to repo root)
    installables = resolve_input_path(installables)
    values = resolve_input_path(values)
    schema = resolve_input_path(schema)

    if not installables.exists():
        raise typer.Exit(f"installables file not found: {installables}")
    if not values.exists():
        raise typer.Exit(f"values file not found: {values}")

    # prefer docs/ schema but allow legacy kinst/schema/ for backward compatibility
    if not schema.exists():
        alt = resolve_input_path(Path("kinst/schema/installables.schema.json"))
        if alt.exists():
            schema = alt
        else:
            raise typer.Exit(
                f"schema file not found: {schema} (tried docs/schema and kinst/schema)"
            )

    try:
        schema_obj = json.loads(schema.read_text(encoding="utf-8"))
    except Exception as e:
        raise typer.Exit(f"failed to read schema: {e}")

    try:
        comp_obj = load_yaml(installables) or {}
        val_obj = load_yaml(values) or {}
        # load env file if provided and substitute ${VAR} occurrences
        env_map: Dict[str, str] = {}
        epath = _maybe_path_arg(env_file)
        if epath:
            env_map = load_env_file(resolve_input_path(epath))
        val_obj = substitute_env_vars(val_obj, env_map, allow_missing=allow_missing_env)
        validate(instance=comp_obj, schema=schema_obj)
    except ValidationError as ve:
        console.print(f"[red]installables.yaml validation failed:[/red] {ve.message}")
        raise typer.Exit(code=2)
    except Exception as e:
        raise typer.Exit(f"parse error: {e}")

    # Build plan entries using dependsOn/file-order semantics
    try:
        ordered = compute_execution_order(comp_obj, val_obj)
    except Exception as e:
        console.print(f"[red]failed to compute plan order: {e}[/red]")
        raise typer.Exit(code=2)

    table = Table(title="kinst plan")
    table.add_column("type")
    table.add_column("id")
    table.add_column("target")
    table.add_column("namespace")
    table.add_column("enabled")

    for node in ordered:
        raw = node["raw"]
        if node["type"] == "helm":
            enabled = eval_condition(val_obj, raw.get("condition"))
            ns = resolve_path(val_obj, raw.get("namespace"))
            target = raw.get("release")
            enabled_str = str(enabled)
        elif node["type"] == "kubectl-apply":
            enabled = eval_condition(val_obj, raw.get("condition"))
            ns = resolve_path(val_obj, raw.get("namespace"))
            target = raw.get("url")
            enabled_str = str(enabled)
        elif node["type"] == "kubectl-label":
            enabled = eval_condition(val_obj, raw.get("condition"))
            ns = resolve_path(val_obj, raw.get("namespace"))
            # show labels inline or labelsPath reference
            target = str(raw.get("labels") or raw.get("labelsPath"))
            enabled_str = str(enabled)
        elif node["type"] == "task":
            enabled = eval_condition(val_obj, raw.get("condition"))
            # scriptPath may be a dotted path into values or literal
            sp = raw.get("scriptPath")
            # show command or script path
            target = raw.get("command") or sp
            enabled_str = str(enabled)
        else:
            raise RuntimeError(f"unknown installable type: {node['type']}")
        table.add_row(
            node["type"], str(node.get("id")), str(target), str(ns), enabled_str
        )

    console.print(table)


@app.command()
def show(
    installables: Path = typer.Option(
        Path("kinst/samples/installables.yaml"), "-f", "--installables"
    ),
    values: Path = typer.Option(Path("kinst/samples/values.yaml"), "-v", "--values"),
    env_file: Optional[Path] = typer.Option(
        None, "-e", "--env-file", help=".env file to load environment variables from"
    ),
    allow_missing_env: bool = typer.Option(
        False,
        "--allow-missing-env",
        help="Allow unresolved ${VAR} placeholders (leave them unchanged)",
    ),
    schema: Path = typer.Option(
        Path("docs/schema/installables.schema.json"), "-s", "--schema"
    ),
):
    """Print resolved installables as JSON (non-destructive)."""
    # resolve paths (allow files relative to repo root)
    installables = resolve_input_path(installables)
    values = resolve_input_path(values)
    schema = resolve_input_path(schema)

    # prefer docs/ schema but allow legacy kinst/schema/ for backward compatibility
    if not schema.exists():
        alt = resolve_input_path(Path("kinst/schema/installables.schema.json"))
        if alt.exists():
            schema = alt

    if not installables.exists():
        raise typer.Exit(f"installables file not found: {installables}")
    if not values.exists():
        raise typer.Exit(f"values file not found: {values}")

    comp_obj = load_yaml(installables) or {}
    val_obj = load_yaml(values) or {}
    env_map: Dict[str, str] = {}
    epath = _maybe_path_arg(env_file)
    if epath:
        env_map = load_env_file(resolve_input_path(epath))
    val_obj = substitute_env_vars(val_obj, env_map, allow_missing=allow_missing_env)
    data = {"installables": []}
    for it in comp_obj.get("installables", []):
        enabled = eval_condition(val_obj, it.get("condition"))
        ns = resolve_path(val_obj, it.get("namespace"))
        data["installables"].append(
            {
                "id": it.get("id"),
                "type": it.get("type"),
                "enabled": enabled,
                "namespace": ns,
            }
        )

    console.print_json(data=json.dumps(data))


@app.command()
def apply(
    installables: Path = typer.Option(
        Path("kinst/samples/installables.yaml"), "-f", "--installables"
    ),
    values: Path = typer.Option(Path("kinst/samples/values.yaml"), "-v", "--values"),
    env_file: Optional[Path] = typer.Option(
        None, "-e", "--env-file", help=".env file to load environment variables from"
    ),
    allow_missing_env: bool = typer.Option(
        False,
        "--allow-missing-env",
        help="Allow unresolved ${VAR} placeholders (leave them unchanged)",
    ),
    schema: Path = typer.Option(
        Path("docs/schema/installables.schema.json"), "-s", "--schema"
    ),
    kube_context: Optional[str] = typer.Option(None, "--kube-context"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    wait: bool = typer.Option(False, "--wait"),
    timeout: Optional[str] = typer.Option(None, "--timeout"),
):
    """Apply/Install enabled installables using helm and kubectl.

    This command performs real operations via the `helm` and `kubectl` CLIs. It runs serially.
    """
    # validate inputs
    # resolve input paths (allow files relative to repo root)
    installables = resolve_input_path(installables)
    values = resolve_input_path(values)
    schema = resolve_input_path(schema)

    # prefer docs/ schema but allow legacy kinst/schema/ for backward compatibility
    if not schema.exists():
        alt = resolve_input_path(Path("kinst/schema/installables.schema.json"))
        if alt.exists():
            schema = alt
    if not installables.exists():
        raise typer.Exit(f"installables file not found: {installables}")
    if not values.exists():
        raise typer.Exit(f"values file not found: {values}")
    try:
        schema_obj = json.loads(schema.read_text(encoding="utf-8"))
        comp_obj = load_yaml(installables) or {}
        val_obj = load_yaml(values) or {}
        env_map: Dict[str, str] = {}
        epath = _maybe_path_arg(env_file)
        if epath:
            env_map = load_env_file(resolve_input_path(epath))
        val_obj = substitute_env_vars(val_obj, env_map, allow_missing=allow_missing_env)
        validate(instance=comp_obj, schema=schema_obj)
    except ValidationError as ve:
        console.print(f"[red]installables.yaml validation failed:[/red] {ve.message}")
        raise typer.Exit(code=2)
    except Exception as e:
        raise typer.Exit(f"parse error: {e}")
    # perform charts and templates with progress UI
    start_time = time.monotonic()
    pm = ProgressManager()
    with pm:
        # compute execution order and run nodes accordingly
        try:
            ordered = compute_execution_order(comp_obj, val_obj)
        except Exception as e:
            console.print(f"[red]failed to compute execution order: {e}[/red]")
            raise typer.Exit(code=2)

        for node in ordered:
            raw = node["raw"]
            if node["type"] == "helm":
                enabled = eval_condition(val_obj, raw.get("condition"))
                if not enabled:
                    logger.info("skipping chart (disabled): %s", raw.get("id"))
                    continue
                ns = resolve_path(val_obj, raw.get("namespace"))
                values_path = raw.get("valuesPath")
                temp_values_file = None
                task = pm.add(
                    str(raw.get("id") or raw.get("release")),
                    f"helm upgrade {raw.get('release')}",
                )
                try:
                    with Step(pm, task):
                        if values_path:
                            subtree = resolve_path(val_obj, values_path)
                            if subtree is not None:
                                if not isinstance(subtree, dict):
                                    raise RuntimeError(
                                        f"valuesPath '{values_path}' resolved to non-mapping value: {type(subtree).__name__}"
                                    )
                                tf = tempfile.NamedTemporaryFile(
                                    mode="w", delete=False, suffix=".yaml"
                                )
                                yaml.safe_dump(subtree, tf)
                                tf.flush()
                                temp_values_file = Path(tf.name)
                        logger.info(
                            "installing/upgrading chart %s (release=%s)",
                            raw.get("name"),
                            raw.get("release"),
                        )
                        repo_creds = resolve_repo_credentials(
                            raw.get("repositoryCredentials"), val_obj
                        )
                        # per-installable wait flag overrides CLI-level wait if provided
                        item_wait = (
                            raw.get("wait") if raw.get("wait") is not None else wait
                        )
                        helm_upgrade_install(
                            release=raw.get("release"),
                            name=raw.get("name"),
                            repository=raw.get("repository"),
                            chart_version=raw.get("chartVersion"),
                            values_file=temp_values_file,
                            namespace=ns,
                            kube_context=kube_context,
                            dry_run=dry_run,
                            wait=bool(item_wait),
                            timeout=timeout,
                            repo_credentials=repo_creds,
                        )
                except Exception as e:
                    console.print(
                        f"[red]helm operation failed for {raw.get('id')}: {e}[/red]"
                    )
                    raise typer.Exit(code=3)
                finally:
                    if temp_values_file and temp_values_file.exists():
                        try:
                            temp_values_file.unlink()
                        except Exception:
                            pass
            elif node["type"] == "kubectl-apply":
                # template
                enabled = eval_condition(val_obj, raw.get("condition"))
                if not enabled:
                    logger.info("skipping template (disabled): %s", raw.get("id"))
                    continue
                ns = resolve_path(val_obj, raw.get("namespace"))
                task = pm.add(
                    str(raw.get("id")), f"kubectl apply template {raw.get('id')}"
                )
                try:
                    with Step(pm, task):
                        txt = fetch_remote_yaml(
                            raw.get("url"), base_dir=installables.parent
                        )
                        if raw.get("injectNamespace", False):
                            txt = inject_namespace_to_yaml(txt, ns)
                        logger.info(
                            "applying template %s from %s",
                            raw.get("id"),
                            raw.get("url"),
                        )
                        kubectl_apply(txt, kube_context=kube_context, dry_run=dry_run)
                except Exception as e:
                    console.print(
                        f"[red]template apply failed for {raw.get('id')}: {e}[/red]"
                    )
                    raise typer.Exit(code=4)
            elif node["type"] == "kubectl-label":
                enabled = eval_condition(val_obj, raw.get("condition"))
                if not enabled:
                    logger.info("skipping kubectl-label (disabled): %s", raw.get("id"))
                    continue
                # namespace may be a dotted path into values or a literal
                ns = resolve_path(val_obj, raw.get("namespace")) or raw.get("namespace")
                if not ns:
                    raise RuntimeError(
                        f"kubectl-label requires a namespace for item {raw.get('id')}"
                    )

                # labels can be provided inline or via labelsPath into values
                labels = raw.get("labels")
                if labels is None and raw.get("labelsPath"):
                    labels = resolve_path(val_obj, raw.get("labelsPath"))
                if not labels or not isinstance(labels, dict):
                    raise RuntimeError(
                        f"kubectl-label '{raw.get('id')}' requires 'labels' mapping or a valid 'labelsPath' in values"
                    )

                # build kubectl label command: kubectl label namespace <ns> key1=value1 key2=value2 [--overwrite]
                # Kubernetes label values are strings. Normalize common types (bool -> 'true'/'false')
                def _label_val(x):
                    if isinstance(x, bool):
                        return "true" if x else "false"
                    # None -> empty string
                    if x is None:
                        return ""
                    return str(x)

                args = [f"{k}={_label_val(v)}" for k, v in labels.items()]
                cmd = ["kubectl", "label", "namespace", ns] + args
                # override behavior: default True for backward compatibility
                override = (
                    raw.get("override") if raw.get("override") is not None else True
                )
                if override:
                    cmd += ["--overwrite"]
                if kube_context:
                    cmd += ["--context", kube_context]
                if dry_run:
                    cmd += ["--dry-run=client"]

                task = pm.add(str(raw.get("id")), f"kubectl label namespace {ns}")
                try:
                    with Step(pm, task):
                        logger.info("labeling namespace %s: %s", ns, labels)
                        run_cmd(cmd)
                except Exception as e:
                    console.print(
                        f"[red]kubectl-label failed for {raw.get('id')}: {e}[/red]"
                    )
                    raise typer.Exit(code=7)
            elif node["type"] == "task":
                enabled = eval_condition(val_obj, raw.get("condition"))
                if not enabled:
                    logger.info("skipping task (disabled): %s", raw.get("id"))
                    continue

                # command may be a string (path or program) or a list
                cmd_field = raw.get("command")
                if not cmd_field:
                    raise RuntimeError(
                        f"task requires 'command' for item {raw.get('id')}"
                    )

                # determine command executable
                cmd_list = []
                # allow command to be provided as array or single string
                if isinstance(cmd_field, list):
                    cmd_list = list(cmd_field)
                elif isinstance(cmd_field, str):
                    # if it's a path-like string, prefer resolving to a file
                    candidate_path = Path(cmd_field)
                    resolved_exec = None
                    if candidate_path.is_absolute() and candidate_path.exists():
                        resolved_exec = candidate_path
                    elif not candidate_path.is_absolute():
                        # try relative to installables parent
                        cand = (installables.parent / candidate_path).resolve()
                        if cand.exists():
                            resolved_exec = cand
                        else:
                            # fallback: is it in PATH?
                            which = shutil.which(cmd_field)
                            if which:
                                resolved_exec = Path(which)
                    else:
                        # absolute but missing -> error
                        resolved_exec = None

                    if resolved_exec:
                        cmd_list = [str(resolved_exec)]
                    else:
                        # if not resolved to a file, treat the string as an executable name and let the shell find it
                        cmd_list = [cmd_field]
                else:
                    raise RuntimeError(
                        "task 'command' must be either a string or an array of strings"
                    )

                # args for apply; support legacy 'args' as fallback
                apply_args = (
                    raw.get("applyArgs")
                    if raw.get("applyArgs") is not None
                    else raw.get("args")
                )
                apply_args = apply_args or []
                if not isinstance(apply_args, list):
                    raise RuntimeError("task 'applyArgs' must be an array of strings")

                cmd = cmd_list + apply_args
                if dry_run:
                    logger.info("(dry-run) would run task: %s", shlex.join(cmd))
                else:
                    task = pm.add(str(raw.get("id")), f"run task {cmd_list[0]}")
                    try:
                        with Step(pm, task):
                            logger.info(
                                "running task %s args=%s", cmd_list[0], apply_args
                            )
                            run_cmd(cmd)
                    except Exception as e:
                        console.print(
                            f"[red]task failed for {raw.get('id')}: {e}[/red]"
                        )
                        raise typer.Exit(code=9)
            else:
                raise RuntimeError(f"unknown installable type: {node['type']}")

    # report total elapsed time for the apply operation
    elapsed = time.monotonic() - start_time
    # format as H:MM:SS
    hrs, rem = divmod(int(elapsed), 3600)
    mins, secs = divmod(rem, 60)
    elapsed_str = f"{hrs}:{mins:02d}:{secs:02d}"
    console.print(f"total time.  {elapsed_str}")


@app.command()
def delete(
    installables: Path = typer.Option(
        Path("kinst/samples/installables.yaml"), "-f", "--installables"
    ),
    values: Path = typer.Option(Path("kinst/samples/values.yaml"), "-v", "--values"),
    env_file: Optional[Path] = typer.Option(
        None, "-e", "--env-file", help=".env file to load environment variables from"
    ),
    allow_missing_env: bool = typer.Option(
        False,
        "--allow-missing-env",
        help="Allow unresolved ${VAR} placeholders (leave them unchanged)",
    ),
    schema: Path = typer.Option(
        Path("docs/schema/installables.schema.json"), "-s", "--schema"
    ),
    kube_context: Optional[str] = typer.Option(None, "--kube-context"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    # resolve input paths (allow files relative to repo root)
    installables = resolve_input_path(installables)
    values = resolve_input_path(values)
    schema = resolve_input_path(schema)

    # prefer docs/ schema but allow legacy kinst/schema/ for backward compatibility
    if not schema.exists():
        alt = resolve_input_path(Path("kinst/schema/installables.schema.json"))
        if alt.exists():
            schema = alt
    if not installables.exists():
        raise typer.Exit(f"installables file not found: {installables}")
    if not values.exists():
        raise typer.Exit(f"values file not found: {values}")
    try:
        schema_obj = json.loads(schema.read_text(encoding="utf-8"))
        comp_obj = load_yaml(installables) or {}
        val_obj = load_yaml(values) or {}
        env_map: Dict[str, str] = {}
        epath = _maybe_path_arg(env_file)
        if epath:
            env_map = load_env_file(resolve_input_path(epath))
        val_obj = substitute_env_vars(val_obj, env_map, allow_missing=allow_missing_env)
        validate(instance=comp_obj, schema=schema_obj)
    except ValidationError as ve:
        console.print(f"[red]installables.yaml validation failed:[/red] {ve.message}")
        raise typer.Exit(code=2)
    except Exception as e:
        raise typer.Exit(f"parse error: {e}")

    # delete in reverse of execution order
    pm = ProgressManager()
    with pm:
        try:
            ordered = compute_execution_order(comp_obj, val_obj)
        except Exception as e:
            console.print(f"[red]failed to compute execution order: {e}[/red]")
            raise typer.Exit(code=2)

        # reverse order for deletes
        for node in reversed(ordered):
            raw = node["raw"]
            if node["type"] == "kubectl-label":
                enabled = eval_condition(val_obj, raw.get("condition"))
                if not enabled:
                    logger.info("skipping kubectl-label (disabled): %s", raw.get("id"))
                    continue
                ns = resolve_path(val_obj, raw.get("namespace")) or raw.get("namespace")
                if not ns:
                    raise RuntimeError(
                        f"kubectl-label requires a namespace for item {raw.get('id')}"
                    )

                labels = raw.get("labels")
                if labels is None and raw.get("labelsPath"):
                    labels = resolve_path(val_obj, raw.get("labelsPath"))
                if not labels or not isinstance(labels, dict):
                    raise RuntimeError(
                        f"kubectl-label '{raw.get('id')}' requires 'labels' mapping or a valid 'labelsPath' in values"
                    )

                # build remove label args: key1- key2-
                args = [f"{k}-" for k in labels.keys()]
                cmd = ["kubectl", "label", "namespace", ns] + args
                if kube_context:
                    cmd += ["--context", kube_context]
                if dry_run:
                    cmd += ["--dry-run=client"]

                task = pm.add(
                    str(raw.get("id")), f"kubectl remove labels from namespace {ns}"
                )
                try:
                    with Step(pm, task):
                        logger.info(
                            "removing labels from namespace %s: %s",
                            ns,
                            list(labels.keys()),
                        )
                        run_cmd(cmd)
                except Exception as e:
                    console.print(
                        f"[red]kubectl-label delete failed for {raw.get('id')}: {e}[/red]"
                    )
                    raise typer.Exit(code=8)
                continue
            if node["type"] == "kubectl-apply":
                enabled = eval_condition(val_obj, raw.get("condition"))
                if not enabled:
                    logger.info("skipping template (disabled): %s", raw.get("id"))
                    continue
                ns = resolve_path(val_obj, raw.get("namespace"))
                task = pm.add(
                    str(raw.get("id")), f"kubectl delete template {raw.get('id')}"
                )
                try:
                    with Step(pm, task):
                        txt = fetch_remote_yaml(
                            raw.get("url"), base_dir=installables.parent
                        )
                        if raw.get("injectNamespace", False):
                            txt = inject_namespace_to_yaml(txt, ns)
                        logger.info(
                            "deleting template %s from %s",
                            raw.get("id"),
                            raw.get("url"),
                        )
                        kubectl_delete(
                            txt,
                            kube_context=kube_context,
                            ignore_not_found=True,
                            dry_run=dry_run,
                        )
                except Exception as e:
                    console.print(
                        f"[red]template delete failed for {raw.get('id')}: {e}[/red]"
                    )
                    raise typer.Exit(code=5)
            elif node["type"] == "helm":
                enabled = eval_condition(val_obj, raw.get("condition"))
                if not enabled:
                    logger.info("skipping chart (disabled): %s", raw.get("id"))
                    continue
                ns = resolve_path(val_obj, raw.get("namespace"))
                task = pm.add(
                    str(raw.get("id") or raw.get("release")),
                    f"helm uninstall {raw.get('release')}",
                )
                try:
                    with Step(pm, task):
                        logger.info("uninstalling helm release %s", raw.get("release"))
                        helm_uninstall(
                            release=raw.get("release"),
                            namespace=ns,
                            kube_context=kube_context,
                            dry_run=dry_run,
                        )
                except Exception as e:
                    console.print(
                        f"[red]helm uninstall failed for {raw.get('id')}: {e}[/red]"
                    )
                    raise typer.Exit(code=6)
            elif node["type"] == "task":
                enabled = eval_condition(val_obj, raw.get("condition"))
                if not enabled:
                    logger.info("skipping task (disabled): %s", raw.get("id"))
                    continue

                # only execute delete if deleteArgs is provided
                if raw.get("deleteArgs") is None:
                    logger.info(
                        "no deleteArgs for task %s; skipping delete", raw.get("id")
                    )
                    continue

                cmd_field = raw.get("command")
                if not cmd_field:
                    raise RuntimeError(
                        f"task requires 'command' for item {raw.get('id')}"
                    )

                # build command list similar to apply resolution
                cmd_list = []
                if isinstance(cmd_field, list):
                    cmd_list = list(cmd_field)
                elif isinstance(cmd_field, str):
                    candidate_path = Path(cmd_field)
                    resolved_exec = None
                    if candidate_path.is_absolute() and candidate_path.exists():
                        resolved_exec = candidate_path
                    elif not candidate_path.is_absolute():
                        cand = (installables.parent / candidate_path).resolve()
                        if cand.exists():
                            resolved_exec = cand
                        else:
                            which = shutil.which(cmd_field)
                            if which:
                                resolved_exec = Path(which)
                    if resolved_exec:
                        cmd_list = [str(resolved_exec)]
                    else:
                        cmd_list = [cmd_field]
                else:
                    raise RuntimeError(
                        "task 'command' must be either a string or an array of strings"
                    )

                delete_args = raw.get("deleteArgs") or []
                if not isinstance(delete_args, list):
                    raise RuntimeError("task 'deleteArgs' must be an array of strings")

                cmd = cmd_list + delete_args
                if dry_run:
                    logger.info("(dry-run) would run task delete: %s", shlex.join(cmd))
                else:
                    task = pm.add(str(raw.get("id")), f"run task delete {cmd_list[0]}")
                    try:
                        with Step(pm, task):
                            logger.info(
                                "running task delete %s args=%s",
                                cmd_list[0],
                                delete_args,
                            )
                            run_cmd(cmd)
                    except Exception as e:
                        console.print(
                            f"[red]task delete failed for {raw.get('id')}: {e}[/red]"
                        )
                        raise typer.Exit(code=10)
            else:
                raise RuntimeError(f"unknown installable type: {node['type']}")


if __name__ == "__main__":
    app()
