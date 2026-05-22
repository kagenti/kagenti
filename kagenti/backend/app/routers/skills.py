# Copyright 2026 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Skill API endpoints.

Skills are stored as Kubernetes ConfigMaps labeled with `kagenti.io/type=skill`.
"""

import json
import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel

from app.core.auth import require_roles, ROLE_VIEWER, ROLE_OPERATOR
from app.core.constants import (
    SKILL_TYPE_LABEL,
    SKILL_TYPE_VALUE,
    SKILL_CATEGORY_LABEL,
    SKILL_DESCRIPTION_ANNOTATION,
    SKILL_ORIGIN_ANNOTATION,
    SKILL_USAGE_ANNOTATION,
    SKILL_FILE_PATHS_ANNOTATION,
    SKILL_STATUS_READY,
    APP_KUBERNETES_IO_MANAGED_BY,
    APP_KUBERNETES_IO_NAME,
)
from app.services.kubernetes import KubernetesService, get_kubernetes_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/skills", tags=["skills"])


class SkillLabels(BaseModel):
    """Labels for categorizing skills."""

    category: Optional[str] = None
    type: Optional[str] = None


class Skill(BaseModel):
    """Represents a skill stored as a ConfigMap."""

    name: str
    namespace: str
    resourceName: str = ""
    description: str = ""
    status: str = SKILL_STATUS_READY
    labels: SkillLabels = SkillLabels()
    createdAt: Optional[str] = None
    origin: Optional[str] = None
    usageCount: int = 0


class SkillFile(BaseModel):
    """Represents a file in the skill content tree."""

    name: str
    path: str
    content: str
    size: int


class SkillDetail(Skill):
    """Detailed skill information including files."""

    dataKeys: List[str] = []
    annotations: dict = {}
    files: List[SkillFile] = []


class SkillListResponse(BaseModel):
    """Response model for listing skills."""

    items: List[Skill]


class CreateSkillRequest(BaseModel):
    """Request model for creating a new skill."""

    name: str
    namespace: str
    description: Optional[str] = ""
    category: Optional[str] = ""
    url: Optional[str] = None
    files: Optional[dict[str, str]] = None


class CreateSkillResponse(BaseModel):
    """Response model for skill creation."""

    success: bool
    name: str
    namespace: str
    message: str


def _sanitize_k8s_name(name: str) -> str:
    """Sanitize a name to be valid for Kubernetes resource names."""
    out = "".join(c.lower() if c.isalnum() or c in ("-", ".") else "-" for c in name)
    out = out.strip("-.")
    return out or "skill"


def _sanitize_configmap_key(key: str) -> str:
    """Sanitize a file path to be valid for Kubernetes ConfigMap keys.

    ConfigMap keys must match regex: [-._a-zA-Z0-9]+
    We replace forward slashes with dots to maintain path structure readability.
    """
    # Replace forward slashes with dots
    sanitized = key.replace("/", ".")
    # Replace any other invalid characters with underscores
    sanitized = "".join(c if c.isalnum() or c in ("-", ".", "_") else "_" for c in sanitized)
    # Remove leading/trailing dots, dashes, or underscores
    sanitized = sanitized.strip("-._")
    return sanitized or "file"


def _desanitize_configmap_key(key: str, file_paths_map: Optional[dict] = None) -> str:
    """Convert a sanitized ConfigMap key back to its original file path.

    Args:
        key: The sanitized ConfigMap key
        file_paths_map: Optional mapping of sanitized keys to original paths
                       (from SKILL_FILE_PATHS_ANNOTATION)

    Returns:
        The original file path if found in file_paths_map, otherwise uses
        a heuristic to convert dots back to slashes.
    """
    # If we have the original path mapping, use it for perfect fidelity
    if file_paths_map and key in file_paths_map:
        return file_paths_map[key]

    # Fallback heuristic for backward compatibility with existing ConfigMaps
    # that don't have the file-paths annotation
    parts = key.split(".")
    if len(parts) > 2:
        # Likely a path like "scripts.extract_form_structure.py"
        # Convert to "scripts/extract_form_structure.py"
        return (
            "/".join(parts[:-1]) + "." + parts[-1]
            if parts[-1] in ["py", "js", "ts", "md", "txt", "json", "yaml", "yml"]
            else "/".join(parts)
        )
    return key


def _configmap_to_skill(cm) -> Skill:
    """Convert a ConfigMap to a Skill model."""
    md = cm.metadata
    labels = md.labels or {}
    annos = md.annotations or {}
    usage = annos.get(SKILL_USAGE_ANNOTATION, "0")
    try:
        usage_count = int(usage)
    except Exception:
        usage_count = 0
    return Skill(
        name=annos.get("kagenti.io/display-name") or md.name,
        namespace=md.namespace,
        resourceName=md.name,
        description=annos.get(SKILL_DESCRIPTION_ANNOTATION, ""),
        status=SKILL_STATUS_READY,
        labels=SkillLabels(
            category=labels.get(SKILL_CATEGORY_LABEL),
            type=labels.get("kagenti.io/skill-type"),
        ),
        createdAt=(md.creation_timestamp.isoformat() if md.creation_timestamp else None),
        origin=annos.get(SKILL_ORIGIN_ANNOTATION),
        usageCount=usage_count,
    )


def _configmap_to_skill_detail(cm) -> SkillDetail:
    """Convert a ConfigMap to a SkillDetail model."""
    md = cm.metadata
    labels = md.labels or {}
    annos = md.annotations or {}
    usage = annos.get(SKILL_USAGE_ANNOTATION, "0")
    try:
        usage_count = int(usage)
    except Exception:
        usage_count = 0
    data = cm.data or {}

    # Load file paths mapping from annotation if available
    file_paths_map = {}
    file_paths_json = annos.get(SKILL_FILE_PATHS_ANNOTATION)
    if file_paths_json:
        try:
            file_paths_map = json.loads(file_paths_json)
        except Exception:
            pass  # Fall back to heuristic if annotation is malformed

    # Build files list from all data keys, desanitizing the paths
    files = []
    for sanitized_key, content in data.items():
        # Desanitize the key to get the original file path
        file_path = _desanitize_configmap_key(sanitized_key, file_paths_map)
        files.append(
            SkillFile(
                name=file_path.split("/")[-1],  # Extract filename from path
                path=file_path,
                content=content,
                size=len(content.encode("utf-8")),
            )
        )

    return SkillDetail(
        name=annos.get("kagenti.io/display-name") or md.name,
        namespace=md.namespace,
        resourceName=md.name,
        description=annos.get(SKILL_DESCRIPTION_ANNOTATION, ""),
        status=SKILL_STATUS_READY,
        labels=SkillLabels(
            category=labels.get(SKILL_CATEGORY_LABEL),
            type=labels.get("kagenti.io/skill-type"),
        ),
        createdAt=(md.creation_timestamp.isoformat() if md.creation_timestamp else None),
        origin=annos.get(SKILL_ORIGIN_ANNOTATION),
        usageCount=usage_count,
        dataKeys=sorted([_desanitize_configmap_key(k, file_paths_map) for k in data.keys()]),
        annotations=dict(annos),
        files=sorted(files, key=lambda f: f.path),
    )


def _get_cm(kube: KubernetesService, namespace: str, name: str):
    """Get a ConfigMap by name."""
    try:
        return kube.core_api.read_namespaced_config_map(name=name, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404:
            raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
        raise HTTPException(status_code=exc.status or 500, detail=str(exc))


def _patch_annotations(kube: KubernetesService, namespace: str, name: str, annotations: dict):
    """Patch ConfigMap annotations."""
    cm_name = _sanitize_k8s_name(name)
    body = {"metadata": {"annotations": annotations}}
    try:
        kube.core_api.patch_namespaced_config_map(name=cm_name, namespace=namespace, body=body)
    except ApiException as exc:
        raise HTTPException(status_code=exc.status or 500, detail=str(exc))


@router.get(
    "",
    response_model=SkillListResponse,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def list_skills(
    namespace: str = Query(..., description="Namespace to list skills from"),
    q: Optional[str] = Query(
        None, description="Search query (keyword match over name, description, content)"
    ),
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SkillListResponse:
    """List skills (ConfigMaps labeled as skills) in a namespace.

    If `q` is provided, skills are filtered by keyword match against
    the name, description, category, and SKILL.md content.
    """
    try:
        cms = kube.core_api.list_namespaced_config_map(
            namespace=namespace,
            label_selector=f"{SKILL_TYPE_LABEL}={SKILL_TYPE_VALUE}",
        )
    except ApiException as exc:
        logger.error(
            "Failed to list skills in %s: %s",
            namespace.replace("\n", "\\n").replace("\r", "\\r"),
            exc,
        )
        raise HTTPException(status_code=exc.status or 500, detail=str(exc))

    skills_with_content = []
    for cm in cms.items:
        data = cm.data or {}

        # Try to get SKILL.md - check both original and sanitized keys
        content = data.get("SKILL.md", "")
        if not content:
            # Try sanitized key
            sanitized_key = _sanitize_configmap_key("SKILL.md")
            content = data.get(sanitized_key, "")

        skills_with_content.append((_configmap_to_skill(cm), content))

    if q:
        query_terms = [t.lower() for t in re.findall(r"\w+", q) if t]
        if query_terms:
            scored = []
            for skill, content in skills_with_content:
                haystack = " ".join(
                    [
                        skill.name or "",
                        skill.description or "",
                        (skill.labels.category or ""),
                        content or "",
                    ]
                ).lower()
                score = sum(haystack.count(term) for term in query_terms)
                if score > 0:
                    scored.append((score, skill))
            scored.sort(key=lambda x: -x[0])
            return SkillListResponse(items=[s for _, s in scored])

    return SkillListResponse(items=[s for s, _ in skills_with_content])


@router.get(
    "/{namespace}/{name}",
    response_model=SkillDetail,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_skill(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SkillDetail:
    """Get detailed information about a specific skill, including SKILL.md content."""
    cm = _get_cm(kube, namespace, name)
    return _configmap_to_skill_detail(cm)


@router.post(
    "",
    response_model=CreateSkillResponse,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def create_skill(
    request: CreateSkillRequest,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> CreateSkillResponse:
    """Create a new skill from files or URL.

    Supports multiple files via the 'files' parameter (dict of path -> content).
    SKILL.md is mandatory and must be included in the files dictionary.
    """
    display_name = request.name.strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="Skill name is required")

    cm_name = _sanitize_k8s_name(display_name)

    labels = {
        SKILL_TYPE_LABEL: SKILL_TYPE_VALUE,
        APP_KUBERNETES_IO_MANAGED_BY: "kagenti-ui",
        APP_KUBERNETES_IO_NAME: cm_name,
    }
    if request.category:
        labels[SKILL_CATEGORY_LABEL] = _sanitize_k8s_name(request.category)

    annotations = {
        "kagenti.io/display-name": display_name,
        SKILL_USAGE_ANNOTATION: "0",
    }
    if request.description:
        annotations[SKILL_DESCRIPTION_ANNOTATION] = request.description
    if request.url:
        annotations[SKILL_ORIGIN_ANNOTATION] = request.url

    data = {}
    file_paths_map = {}  # Map sanitized keys to original paths

    if request.files:
        # Sanitize file paths for ConfigMap keys and build mapping
        for file_path, content in request.files.items():
            sanitized_key = _sanitize_configmap_key(file_path)
            data[sanitized_key] = content
            file_paths_map[sanitized_key] = file_path

        # Ensure SKILL.md exists (check both original and sanitized versions)
        if "SKILL.md" not in request.files and _sanitize_configmap_key("SKILL.md") not in data:
            raise HTTPException(
                status_code=400, detail="SKILL.md is required in the files dictionary"
            )

        # Store the file paths mapping in an annotation for perfect desanitization
        annotations[SKILL_FILE_PATHS_ANNOTATION] = json.dumps(file_paths_map)
    else:
        raise HTTPException(
            status_code=400, detail="'files' parameter is required with at least SKILL.md"
        )

    body = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": cm_name,
            "namespace": request.namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "data": data,
    }

    try:
        kube.core_api.create_namespaced_config_map(namespace=request.namespace, body=body)
        return CreateSkillResponse(
            success=True,
            name=display_name,
            namespace=request.namespace,
            message=f"Skill '{display_name}' created",
        )
    except ApiException as exc:
        if exc.status == 409:
            raise HTTPException(
                status_code=409,
                detail=f"Skill '{display_name}' already exists in namespace '{request.namespace}'",
            )
        logger.error(
            "Failed to create skill %s: %s",
            display_name.replace("\n", "\\n").replace("\r", "\\r"),
            exc,
        )
        raise HTTPException(status_code=exc.status or 500, detail=str(exc))


@router.post(
    "/{namespace}/{name}/usage",
    response_model=Skill,
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def increment_usage(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> Skill:
    """Increment the usage count for a skill."""
    cm = _get_cm(kube, namespace, name)
    annos = cm.metadata.annotations or {}
    try:
        current = int(annos.get(SKILL_USAGE_ANNOTATION, "0"))
    except Exception:
        current = 0
    _patch_annotations(kube, namespace, name, {SKILL_USAGE_ANNOTATION: str(current + 1)})
    cm = _get_cm(kube, namespace, name)
    return _configmap_to_skill(cm)


@router.get(
    "/{namespace}/{name}/files/{file_path:path}",
    response_model=SkillFile,
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
)
async def get_skill_file(
    namespace: str,
    name: str,
    file_path: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> SkillFile:
    """Get a specific file from a skill."""
    cm = _get_cm(kube, namespace, name)
    data = cm.data or {}
    annos = cm.metadata.annotations or {}

    # Load file paths mapping from annotation if available
    file_paths_map = {}
    file_paths_json = annos.get(SKILL_FILE_PATHS_ANNOTATION)
    if file_paths_json:
        try:
            file_paths_map = json.loads(file_paths_json)
        except Exception:
            pass

    # Try to find the file by sanitized key
    sanitized_key = _sanitize_configmap_key(file_path)

    if sanitized_key not in data:
        raise HTTPException(
            status_code=404, detail=f"File '{file_path}' not found in skill '{name}'"
        )

    content = data[sanitized_key]
    # Use the mapping to get the original path if available
    original_path = file_paths_map.get(sanitized_key, file_path)
    return SkillFile(
        name=original_path.split("/")[-1],
        path=original_path,
        content=content,
        size=len(content.encode("utf-8")),
    )


@router.delete(
    "/{namespace}/{name}",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
)
async def delete_skill(
    namespace: str,
    name: str,
    kube: KubernetesService = Depends(get_kubernetes_service),
) -> dict:
    """Delete a skill (ConfigMap) from the cluster."""
    cm_name = _sanitize_k8s_name(name)
    try:
        kube.core_api.delete_namespaced_config_map(name=cm_name, namespace=namespace)
        return {
            "success": True,
            "message": f"Skill '{name}' deleted successfully",
            "deleted_resources": [f"ConfigMap/{cm_name}"],
        }
    except ApiException as exc:
        if exc.status == 404:
            raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
        logger.error(
            "Failed to delete skill %s: %s",
            name.replace("\n", "\\n").replace("\r", "\\r"),
            exc,
        )
        raise HTTPException(status_code=exc.status or 500, detail=str(exc))
