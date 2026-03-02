# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Sandbox File Browser API — list directories and read files from sandbox agent pods.

Uses Kubernetes pod exec to run commands inside running sandbox pods,
providing a file browser experience in the UI.
"""

import logging
import posixpath
from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from kubernetes.client import ApiException
from kubernetes.stream import stream as k8s_stream
from pydantic import BaseModel

from app.core.auth import ROLE_VIEWER, require_roles
from app.services.kubernetes import KubernetesService, get_kubernetes_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB
WORKSPACE_ROOT = "/workspace"

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class FileEntry(BaseModel):
    """Single entry in a directory listing."""

    name: str
    path: str  # absolute path inside the pod
    is_dir: bool
    size: int  # bytes
    modified: str  # ISO-8601 timestamp string


class DirectoryListing(BaseModel):
    """Response when the requested path is a directory."""

    path: str
    entries: List[FileEntry]


class FileContent(BaseModel):
    """Response when the requested path is a regular file."""

    path: str
    content: str
    size: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_path(path: str) -> str:
    """
    Validate and normalise the requested filesystem path.

    Raises HTTPException(400) if the path contains traversal sequences or
    does not start with ``/workspace``.
    """
    # Normalise the path (collapse //, resolve . but NOT ..)
    normalised = posixpath.normpath(path)

    # Reject any component that is ".."
    if ".." in normalised.split("/"):
        raise HTTPException(
            status_code=400,
            detail="Path traversal ('..') is not allowed.",
        )

    # Must be rooted under /workspace
    if not normalised.startswith(WORKSPACE_ROOT):
        raise HTTPException(
            status_code=400,
            detail=f"Path must start with {WORKSPACE_ROOT}.",
        )

    return normalised


def _find_pod(
    kube: KubernetesService,
    namespace: str,
    agent_name: str,
) -> str:
    """
    Find the first Running pod for the given agent.

    Pods are selected by label ``app={agent_name}``.

    Returns:
        The pod name.

    Raises:
        HTTPException(404) if no running pod is found.
    """
    try:
        pods = kube.core_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"app={agent_name}",
        )
    except ApiException as exc:
        logger.error("K8s error listing pods for %s/%s: %s", namespace, agent_name, exc)
        raise HTTPException(status_code=502, detail="Failed to list pods.") from exc

    for pod in pods.items:
        if pod.status and pod.status.phase == "Running":
            return pod.metadata.name

    raise HTTPException(
        status_code=404,
        detail=f"No running pod found for agent '{agent_name}' in namespace '{namespace}'.",
    )


def _exec_in_pod(
    kube: KubernetesService,
    namespace: str,
    pod_name: str,
    command: List[str],
) -> str:
    """
    Execute a command inside a pod and return the combined stdout/stderr.

    Uses ``kubernetes.stream.stream()`` for websocket-based exec.

    Raises:
        HTTPException(502) on K8s API errors.
    """
    try:
        result = k8s_stream(
            kube.core_api.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        return result
    except ApiException as exc:
        logger.error(
            "K8s exec error in %s/%s: %s",
            namespace,
            pod_name,
            exc,
        )
        raise HTTPException(status_code=502, detail="Failed to exec in pod.") from exc


def _parse_ls_output(raw: str, base_path: str) -> List[FileEntry]:
    """
    Parse output of ``ls -la --time-style=full-iso`` into :class:`FileEntry` objects.

    Expected line format (space-separated, 9 fields minimum)::

        -rw-r--r-- 1 root root  1234 2025-06-01 12:34:56.000000000 +0000 filename

    Skips the ``total`` header line and the ``.`` / ``..`` entries.
    """
    entries: List[FileEntry] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("total"):
            continue

        parts = line.split(None, 8)
        if len(parts) < 9:
            continue

        permissions = parts[0]
        try:
            size = int(parts[4])
        except (ValueError, IndexError):
            size = 0

        # Date + time + tz -> parts[5], parts[6], parts[7]
        modified = f"{parts[5]}T{parts[6]}{parts[7]}"  # e.g. 2025-06-01T12:34:56.000000000+0000

        name = parts[8]
        if name in (".", ".."):
            continue

        is_dir = permissions.startswith("d")
        entry_path = posixpath.join(base_path, name)

        entries.append(
            FileEntry(
                name=name,
                path=entry_path,
                is_dir=is_dir,
                size=size,
                modified=modified,
            )
        )

    return entries


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/sandbox",
    tags=["sandbox-files"],
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)


@router.get(
    "/{namespace}/files/{agent_name}",
    response_model=Union[DirectoryListing, FileContent],
    summary="Browse files in a sandbox agent pod",
)
async def get_sandbox_files(
    namespace: str,
    agent_name: str,
    path: str = Query(default=WORKSPACE_ROOT, description="Absolute path inside the pod"),
    kube: KubernetesService = Depends(get_kubernetes_service),
):
    """
    If *path* is a directory, return a :class:`DirectoryListing`.
    If *path* is a regular file, return its :class:`FileContent` (up to 1 MB).

    The path must be under ``/workspace`` — traversal via ``..`` is rejected.
    """
    safe_path = _sanitize_path(path)
    pod_name = _find_pod(kube, namespace, agent_name)

    # ---- Determine whether path is a file or directory ----
    # stat --format=%F|%s|%Y -> "regular file|1234|1717200000"  or  "directory|4096|..."
    stat_output = _exec_in_pod(
        kube,
        namespace,
        pod_name,
        ["stat", "--format=%F|%s|%Y", safe_path],
    ).strip()

    if not stat_output:
        raise HTTPException(status_code=404, detail=f"Path not found: {safe_path}")

    # stat may produce an error message (e.g. "No such file or directory")
    if "|" not in stat_output:
        raise HTTPException(status_code=404, detail=f"Path not found: {safe_path}")

    parts = stat_output.split("|", 2)
    file_type = parts[0].strip().lower()
    try:
        file_size = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        file_size = 0

    # ---- Directory listing ----
    if "directory" in file_type:
        ls_output = _exec_in_pod(
            kube,
            namespace,
            pod_name,
            ["ls", "-la", "--time-style=full-iso", safe_path],
        )
        entries = _parse_ls_output(ls_output, safe_path)
        return DirectoryListing(path=safe_path, entries=entries)

    # ---- Regular file ----
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({file_size} bytes). Maximum is {MAX_FILE_SIZE} bytes.",
        )

    content = _exec_in_pod(
        kube,
        namespace,
        pod_name,
        ["cat", safe_path],
    )

    return FileContent(path=safe_path, content=content, size=file_size)
