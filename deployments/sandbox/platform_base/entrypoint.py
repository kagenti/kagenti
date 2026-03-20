"""Platform-owned A2A agent entrypoint.

Loads an agent module via the AGENT_MODULE environment variable and wires
it together with platform services (workspace, permissions, sources, TOFU,
task store).  The agent module must export:

    build_executor(workspace_manager, permission_checker, sources_config, **kwargs)
        -> AgentExecutor

    get_agent_card(host, port)
        -> AgentCard
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
from pathlib import Path

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from starlette.routing import Route

try:
    from a2a.server.tasks import DatabaseTaskStore

    _HAS_SQL_STORE = True
except ImportError:
    _HAS_SQL_STORE = False

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TOFU (Trust-On-First-Use) verification
# ---------------------------------------------------------------------------

_TOFU_HASH_FILE = ".tofu-hashes.json"
_TOFU_TRACKED_FILES = ("CLAUDE.md", "sources.json", "settings.json")


def _hash_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compute_tofu_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in _TOFU_TRACKED_FILES:
        digest = _hash_file(root / name)
        if digest is not None:
            hashes[name] = digest
    return hashes


def tofu_verify(root: Path) -> None:
    """Run TOFU verification on startup.

    Logs warnings on mismatch but does NOT block startup.
    """
    hash_file = Path("/tmp") / _TOFU_HASH_FILE
    current_hashes = _compute_tofu_hashes(root)

    if not current_hashes:
        logger.info("TOFU: no tracked files found in %s; skipping.", root)
        return

    if hash_file.is_file():
        try:
            with open(hash_file, encoding="utf-8") as fh:
                stored_hashes = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("TOFU: could not read %s: %s", hash_file, exc)
            stored_hashes = {}

        changed = [
            n
            for n, d in current_hashes.items()
            if stored_hashes.get(n) not in (None, d)
        ]
        added = [n for n in current_hashes if n not in stored_hashes]
        removed = [n for n in stored_hashes if n not in current_hashes]

        if changed or added or removed:
            logger.warning(
                "TOFU: integrity mismatch! changed=%s, added=%s, removed=%s",
                changed,
                added,
                removed,
            )
            with open(hash_file, "w", encoding="utf-8") as fh:
                json.dump(current_hashes, fh, indent=2)
        else:
            logger.info("TOFU: all tracked files match stored hashes.")
    else:
        logger.info(
            "TOFU: first run -- storing hashes for %s", list(current_hashes.keys())
        )
        with open(hash_file, "w", encoding="utf-8") as fh:
            json.dump(current_hashes, fh, indent=2)


# ---------------------------------------------------------------------------
# Task store factory
# ---------------------------------------------------------------------------


def create_task_store():
    """Create TaskStore from TASK_STORE_DB_URL env var (PostgreSQL or in-memory)."""
    db_url = os.environ.get("TASK_STORE_DB_URL", "")
    if db_url and _HAS_SQL_STORE:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(
            db_url,
            pool_size=5,
            max_overflow=3,
            pool_recycle=300,
            pool_pre_ping=True,
        )
        store = DatabaseTaskStore(engine)
        logger.info("Using PostgreSQL TaskStore: %s", db_url.split("@")[-1])
        return store

    logger.info("Using InMemoryTaskStore (set TASK_STORE_DB_URL for persistence)")
    return InMemoryTaskStore()


# ---------------------------------------------------------------------------
# JSON config loader
# ---------------------------------------------------------------------------


def load_json(filename: str, search_paths: list[Path] | None = None) -> dict:
    """Load a JSON file, searching multiple paths.

    Parameters
    ----------
    filename:
        Name of the JSON file (e.g. ``settings.json``).
    search_paths:
        Directories to search. Defaults to CWD and /app.
    """
    if search_paths is None:
        search_paths = [Path.cwd(), Path("/app")]

    for base in search_paths:
        path = base / filename
        if path.is_file():
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)

    raise FileNotFoundError(f"{filename} not found in {search_paths}")


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Load AGENT_MODULE and start the A2A server."""
    module_name = os.environ.get("AGENT_MODULE")
    if not module_name:
        raise RuntimeError(
            "AGENT_MODULE environment variable is required. "
            "Set it to the Python module path of your agent "
            "(e.g. 'sandbox_agent.graph' or 'opencode_agent.wrapper')."
        )

    logger.info("Loading agent module: %s", module_name)
    agent_module = importlib.import_module(module_name)

    # Validate the module exports the required functions
    for attr in ("build_executor", "get_agent_card"):
        if not hasattr(agent_module, attr):
            raise RuntimeError(
                f"Agent module '{module_name}' must export '{attr}()'. "
                f"See platform_base/entrypoint.py docstring for the contract."
            )

    # Load platform config files
    from platform_base.workspace import WorkspaceManager
    from platform_base.permissions import PermissionChecker
    from platform_base.sources import SourcesConfig

    config_root = Path(os.environ.get("CONFIG_ROOT", "/app"))

    settings = load_json("settings.json", [config_root, Path.cwd()])
    sources_data = load_json("sources.json", [config_root, Path.cwd()])

    permission_checker = PermissionChecker(settings)
    sources_config = SourcesConfig.from_dict(sources_data)

    workspace_root = os.environ.get("WORKSPACE_ROOT", "/workspace")
    agent_name = os.environ.get("AGENT_NAME", "sandbox-agent")
    ttl_days = int(os.environ.get("CONTEXT_TTL_DAYS", "7"))

    workspace_manager = WorkspaceManager(
        workspace_root=workspace_root,
        agent_name=agent_name,
        ttl_days=ttl_days,
    )

    # Clean up expired workspaces on startup
    cleaned = workspace_manager.cleanup_expired()
    if cleaned:
        logger.info("Cleaned up %d expired workspaces: %s", len(cleaned), cleaned)

    # TOFU verification
    tofu_verify(config_root)

    # Build agent executor via the plugin contract
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    executor = agent_module.build_executor(
        workspace_manager=workspace_manager,
        permission_checker=permission_checker,
        sources_config=sources_config,
    )

    agent_card = agent_module.get_agent_card(host=host, port=port)

    # Create A2A server
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=create_task_store(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    app = server.build()

    # Add well-known agent card route
    app.routes.insert(
        0,
        Route(
            "/.well-known/agent-card.json",
            server._handle_get_agent_card,
            methods=["GET"],
            name="agent_card_well_known",
        ),
    )

    logger.info(
        "Starting A2A server on %s:%d with agent module '%s'", host, port, module_name
    )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
