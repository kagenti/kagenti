# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""
Shared Pydantic models for Shipwright builds.

These models are used by both agent and tool routers for Shipwright build operations.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.core.constants import (
    SHIPWRIGHT_STRATEGY_INSECURE,
    SHIPWRIGHT_DEFAULT_DOCKERFILE,
    SHIPWRIGHT_DEFAULT_TIMEOUT,
)


class ResourceType(str, Enum):
    """Type of resource being built."""

    AGENT = "agent"
    TOOL = "tool"


class ShipwrightBuildConfig(BaseModel):
    """Configuration for Shipwright builds (shared by agents and tools)."""

    # buildStrategy defaults to None to allow automatic selection based on registry type
    # (internal registries use insecure push, external use secure)
    buildStrategy: Optional[str] = None
    dockerfile: str = SHIPWRIGHT_DEFAULT_DOCKERFILE
    buildArgs: Optional[List[str]] = None  # KEY=VALUE format
    buildTimeout: str = SHIPWRIGHT_DEFAULT_TIMEOUT


class BuildSourceConfig(BaseModel):
    """Git source configuration for builds."""

    gitUrl: str
    gitRevision: str = "main"
    contextDir: str = "."
    gitSecretName: str = "github-shipwright-secret"


class BuildOutputConfig(BaseModel):
    """Output image configuration for builds."""

    registry: str
    imageName: str
    imageTag: str = "latest"
    pushSecretName: Optional[str] = None


class BuildStatusCondition(BaseModel):
    """Build status condition."""

    type: str
    status: str
    reason: Optional[str] = None
    message: Optional[str] = None
    lastTransitionTime: Optional[str] = None


class ClusterBuildStrategyInfo(BaseModel):
    """Information about a ClusterBuildStrategy."""

    name: str
    description: Optional[str] = None


class ClusterBuildStrategiesResponse(BaseModel):
    """Response containing available ClusterBuildStrategies."""

    strategies: List[ClusterBuildStrategyInfo]


class ShipwrightBuildStatusResponse(BaseModel):
    """Response containing Shipwright Build status information."""

    name: str
    namespace: str
    registered: bool
    reason: Optional[str] = None
    message: Optional[str] = None


class ShipwrightBuildRunStatusResponse(BaseModel):
    """Response containing Shipwright BuildRun status information."""

    name: str
    namespace: str
    buildName: str
    phase: str  # Pending, Running, Succeeded, Failed
    startTime: Optional[str] = None
    completionTime: Optional[str] = None
    outputImage: Optional[str] = None
    outputDigest: Optional[str] = None
    failureMessage: Optional[str] = None
    conditions: List[BuildStatusCondition]


class ResourceConfigFromBuild(BaseModel):
    """Resource configuration stored in Build annotations (generic for agent/tool)."""

    protocol: str = "a2a"
    framework: str = "LangGraph"
    createHttpRoute: bool = False
    registrySecret: Optional[str] = None
    envVars: Optional[List[Dict[str, Any]]] = None
    servicePorts: Optional[List[Dict[str, Any]]] = None


class ShipwrightBuildInfoResponse(BaseModel):
    """Full Shipwright Build information including resource config and latest BuildRun status.

    This model is shared between agents and tools. The resourceType field indicates
    which type of resource this build is for.
    """

    # Build info
    name: str
    namespace: str
    resourceType: str  # "agent" or "tool"
    buildRegistered: bool
    buildReason: Optional[str] = None
    buildMessage: Optional[str] = None
    outputImage: str
    strategy: str
    gitUrl: str
    gitRevision: str
    contextDir: str

    # Latest BuildRun info (if any)
    hasBuildRun: bool = False
    buildRunName: Optional[str] = None
    buildRunPhase: Optional[str] = None  # Pending, Running, Succeeded, Failed
    buildRunStartTime: Optional[str] = None
    buildRunCompletionTime: Optional[str] = None
    buildRunOutputImage: Optional[str] = None
    buildRunOutputDigest: Optional[str] = None
    buildRunFailureMessage: Optional[str] = None

    # Resource configuration from annotations (generic dict for flexibility)
    resourceConfig: Optional[Dict[str, Any]] = None
