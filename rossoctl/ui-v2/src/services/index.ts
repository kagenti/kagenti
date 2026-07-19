// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

export {
  API_CONFIG,
  namespaceService,
  agentService,
  toolService,
  configService,
  shipwrightService,
  toolShipwrightService,
  type ToolShipwrightBuildInfo,
} from './api';

// Export shared Shipwright types and utilities
export {
  type ResourceType,
  type ShipwrightBuildConfig,
  type ClusterBuildStrategy,
  type BuildStatusCondition,
  type ShipwrightBuildStatus,
  type BuildRunPhase,
  type ShipwrightBuildRunStatus,
  type ResourceConfigFromBuild,
  type ShipwrightBuildInfo,
  type AgentShipwrightBuildInfo,
  type TriggerBuildRunResponse,
  type FinalizeBuildResponse,
  type FinalizeBuildRequest,
  isBuildInProgress,
  isBuildComplete,
  isBuildSucceeded,
  isBuildFailed,
  getBuildStatusMessage,
  getBuildStatusVariant,
  toGenericBuildInfo,
  toAgentBuildInfo,
} from './shipwright';
