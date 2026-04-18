# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Dynamic per-namespace PostgreSQL connection pool manager for sandbox sessions.

Discovers DB connection details from a Kubernetes Secret in each namespace,
with a convention-based fallback. Pools are created lazily and cached.

SSL is disabled at the application level because Istio ambient mesh provides
mTLS for all inter-pod traffic. This avoids SSL negotiation failures that
can occur when ztunnel intercepts the PostgreSQL binary protocol.
"""

import asyncio
import base64
import logging
import os
from typing import Dict, Optional
from urllib.parse import quote_plus

import asyncpg

logger = logging.getLogger(__name__)


def _safe_log(value: object) -> str:
    """Sanitize user input for logging (CWE-117 log injection prevention)."""
    s = str(value) if not isinstance(value, str) else value
    return s.replace("\n", "\\n").replace("\r", "\\r").replace("\x00", "")


# ---------------------------------------------------------------------------
# Module-level pool cache
# ---------------------------------------------------------------------------

_pool_cache: Dict[str, asyncpg.Pool] = {}

# Secret name and expected keys
SESSION_SECRET_NAME = "postgres-sessions-secret"
SECRET_KEYS = ("host", "port", "database", "username", "password")

# Pool creation retry config
_POOL_MAX_RETRIES = 3
_POOL_RETRY_DELAY = 2.0  # seconds


# ---------------------------------------------------------------------------
# Kubernetes secret discovery
# ---------------------------------------------------------------------------


def _load_kube_core_api():
    """Return a CoreV1Api client, loading config once."""
    import kubernetes.client
    import kubernetes.config
    from kubernetes.config import ConfigException

    try:
        if os.getenv("KUBERNETES_SERVICE_HOST"):
            kubernetes.config.load_incluster_config()
        else:
            kubernetes.config.load_kube_config()
    except ConfigException:
        logger.warning("Could not load Kubernetes config; secret discovery will be skipped")
        return None
    return kubernetes.client.CoreV1Api()


def _read_secret(namespace: str) -> Optional[Dict[str, str]]:
    """Read postgres-sessions-secret from *namespace* and return decoded fields."""
    api = _load_kube_core_api()
    if api is None:
        return None
    try:
        secret = api.read_namespaced_secret(name=SESSION_SECRET_NAME, namespace=namespace)
        if not secret.data:
            return None
        decoded = {}
        for key in SECRET_KEYS:
            raw = secret.data.get(key)
            if raw is None:
                return None
            decoded[key] = base64.b64decode(raw).decode("utf-8")
        return decoded
    except Exception:
        return None


def _dsn_for_namespace(namespace: str) -> str:
    """Build a DSN from the namespace secret, falling back to convention."""
    creds = _read_secret(namespace)
    if not creds:
        return _convention_dsn(namespace)
    return (
        f"postgresql://{quote_plus(creds['username'])}:{quote_plus(creds['password'])}"
        f"@{creds['host']}:{creds['port']}/{creds['database']}"
    )


def _convention_dsn(namespace: str) -> str:
    """Convention-based DSN when no secret is available."""
    logger.warning("Using convention-based DB fallback for namespace=%s", _safe_log(namespace))
    return f"postgresql://kagenti:kagenti@postgres-sessions.{namespace}:5432/sessions"


# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------


async def _create_pool(dsn: str) -> asyncpg.Pool:
    """Create an asyncpg pool with retry and SSL disabled for Istio compat."""
    last_error: Optional[Exception] = None
    for attempt in range(1, _POOL_MAX_RETRIES + 1):
        try:
            pool = await asyncpg.create_pool(
                dsn,
                min_size=1,
                max_size=10,
                max_inactive_connection_lifetime=300,
                command_timeout=30,
                # Disable app-level SSL — Istio ambient provides mTLS
                ssl=False,
            )
            return pool
        except (
            asyncpg.InvalidPasswordError,
            asyncpg.InvalidCatalogNameError,
        ):
            # Auth/DB errors won't fix themselves on retry
            raise
        except Exception as exc:
            last_error = exc
            if attempt < _POOL_MAX_RETRIES:
                logger.warning(
                    "DB pool creation failed (attempt %d/%d): %s — retrying in %.0fs",
                    attempt,
                    _POOL_MAX_RETRIES,
                    exc,
                    _POOL_RETRY_DELAY,
                )
                await asyncio.sleep(_POOL_RETRY_DELAY)
            else:
                logger.error(
                    "DB pool creation failed after %d attempts: %s",
                    _POOL_MAX_RETRIES,
                    exc,
                )
    raise last_error  # type: ignore[misc]


async def get_session_pool(namespace: str) -> asyncpg.Pool:
    """Return (or lazily create) the asyncpg pool for *namespace*."""
    pool = _pool_cache.get(namespace)
    if pool is not None:
        if not pool._closed:
            return pool
        # Pool was closed externally — recreate
        logger.warning("DB pool for namespace=%s was closed — recreating", _safe_log(namespace))
        del _pool_cache[namespace]

    dsn = _dsn_for_namespace(namespace)
    logger.info("Creating session DB pool for namespace=%s", _safe_log(namespace))
    pool = await _create_pool(dsn)
    await _ensure_sessions_schema(pool)
    _pool_cache[namespace] = pool
    return pool


async def evict_pool(namespace: str) -> None:
    """Remove a pool from cache (call on connection errors to force recreation)."""
    pool = _pool_cache.pop(namespace, None)
    if pool is not None:
        logger.info("Evicting stale DB pool for namespace=%s", namespace)
        try:
            await pool.close()
        except Exception:
            pass


async def close_all_pools() -> None:
    """Close every cached pool (called on application shutdown)."""
    for ns, pool in list(_pool_cache.items()):
        logger.info("Closing session DB pool for namespace=%s", ns)
        await pool.close()
    _pool_cache.clear()


# ---------------------------------------------------------------------------
# Sessions table schema
# ---------------------------------------------------------------------------

SESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    context_id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL DEFAULT '',
    namespace TEXT NOT NULL DEFAULT '',
    title TEXT DEFAULT '',
    owner TEXT DEFAULT '',
    owner_email TEXT DEFAULT '',
    owner_sub TEXT DEFAULT '',
    visibility TEXT DEFAULT 'private',
    model_override TEXT DEFAULT '',
    budget_max_tokens BIGINT DEFAULT 0,
    budget_max_wall_clock_s INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_message_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sessions_ns_updated ON sessions(namespace, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_owner ON sessions(owner);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_name, namespace);
"""


async def _ensure_sessions_schema(pool: asyncpg.Pool) -> None:
    """Create sessions table if it doesn't exist. Idempotent."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(SESSIONS_SCHEMA)
        logger.info("Sessions schema ensured")
    except Exception as exc:
        logger.warning("Failed to ensure sessions schema: %s", exc)

    # Also ensure events table
    try:
        from app.models.event import EVENTS_SCHEMA

        async with pool.acquire() as conn:
            await conn.execute(EVENTS_SCHEMA)
        logger.info("Events schema ensured")
    except Exception as exc:
        logger.warning("Failed to ensure events schema: %s", exc)


# NOTE: The A2A SDK's DatabaseTaskStore manages the 'tasks' table schema.
# The backend reads from 'tasks' and manages the 'sessions' table above.
