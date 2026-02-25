# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Dynamic per-namespace PostgreSQL connection pool manager for sandbox sessions.

Discovers DB connection details from a Kubernetes Secret in each namespace,
with a convention-based fallback. Pools are created lazily and cached.
"""

import base64
import logging
import os
from typing import Dict, Optional

import asyncpg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level pool cache
# ---------------------------------------------------------------------------

_pool_cache: Dict[str, asyncpg.Pool] = {}

# Secret name and expected keys
SESSION_SECRET_NAME = "postgres-sessions-secret"
SECRET_KEYS = ("host", "port", "database", "username", "password")


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
    except Exception as exc:
        logger.debug("Secret %s not found in %s: %s", SESSION_SECRET_NAME, namespace, exc)
        return None


def _dsn_for_namespace(namespace: str) -> str:
    """Build a DSN from the namespace secret, falling back to convention."""
    creds = _read_secret(namespace)
    if creds:
        return (
            f"postgresql://{creds['username']}:{creds['password']}"
            f"@{creds['host']}:{creds['port']}/{creds['database']}"
        )
    # Convention-based fallback
    return f"postgresql://kagenti:kagenti@postgres-sessions.{namespace}:5432/sessions"


# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------


async def get_session_pool(namespace: str) -> asyncpg.Pool:
    """Return (or lazily create) the asyncpg pool for *namespace*."""
    if namespace in _pool_cache:
        return _pool_cache[namespace]

    dsn = _dsn_for_namespace(namespace)
    logger.info("Creating session DB pool for namespace=%s", namespace)
    pool = await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=10,
        max_inactive_connection_lifetime=300,
    )
    _pool_cache[namespace] = pool
    return pool


async def close_all_pools() -> None:
    """Close every cached pool (called on application shutdown)."""
    for ns, pool in list(_pool_cache.items()):
        logger.info("Closing session DB pool for namespace=%s", ns)
        await pool.close()
    _pool_cache.clear()


# NOTE: Schema management is handled by the A2A SDK's DatabaseTaskStore.
# The backend only reads from the SDK-managed 'tasks' table.
# No ensure_schema() is needed — the SDK creates tables on agent startup.
