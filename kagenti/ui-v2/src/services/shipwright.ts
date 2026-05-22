// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Shared Shipwright build service.
 *
 * This module provides types and utilities for Shipwright builds that are used
 * by both agent and tool pages. It enables code reuse for build status tracking,
 * BuildRun management, and build finalization.
 */

/**
 * Resource type for builds
 */
export type ResourceType = 'agent' | 'tool';

/**
 * Shipwright build configuration
 */
export interface ShipwrightBuildConfig {
  buildStrategy: string;
  dockerfile: string;
  buildArgs?: string[];
  buildTimeout: string;
}

/**
 * ClusterBuildStrategy information
 */
export interface ClusterBuildStrategy {
  name: string;
  description?: string;
}

/**
 * Build status condition
 */
export interface BuildStatusCondition {
  type: string;
  status: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
}

/**
 * Shipwright Build status
 */
export interface ShipwrightBuildStatus {
  name: string;
  namespace: string;
  registered: boolean;
  reason?: string;
  message?: string;
}

/**
 * BuildRun phase
 */
export type BuildRunPhase = 'Pending' | 'Running' | 'Succeeded' | 'Failed';

/**
 * Shipwright BuildRun status
 */
export interface ShipwrightBuildRunStatus {
  name: string;
  namespace: string;
  buildName: string;
  phase: BuildRunPhase;
  startTime?: string;
  completionTime?: string;
  outputImage?: string;
  outputDigest?: string;
  failureMessage?: string;
  conditions: BuildStatusCondition[];
}

/**
 * Resource configuration stored in Build annotations.
 * This is generic and works for both agents and tools.
 */
export interface ResourceConfigFromBuild {
  protocol: string;
  framework: string;
  createHttpRoute: boolean;
  registrySecret?: string;
  envVars?: Array<{
    name: string;
    value?: string;
    valueFrom?: {
      secretKeyRef?: { name: string; key: string };
      configMapKeyRef?: { name: string; key: string };
    };
  }>;
  servicePorts?: Array<{
    name: string;
    port: number;
    targetPort: number;
    protocol: string;
  }>;
}

/**
 * Full Shipwright Build information including resource config and BuildRun status.
 * This is a generic type that works for both agents and tools.
 */
export interface ShipwrightBuildInfo {
  // Build info
  name: string;
  namespace: string;
  resourceType: ResourceType;
  buildRegistered: boolean;
  buildReason?: string;
  buildMessage?: string;
  outputImage: string;
  strategy: string;
  gitUrl: string;
  gitRevision: string;
  contextDir: string;

  // Latest BuildRun info
  hasBuildRun: boolean;
  buildRunName?: string;
  buildRunPhase?: BuildRunPhase;
  buildRunStartTime?: string;
  buildRunCompletionTime?: string;
  buildRunOutputImage?: string;
  buildRunOutputDigest?: string;
  buildRunFailureMessage?: string;

  // Resource configuration from annotations (generic)
  resourceConfig?: ResourceConfigFromBuild;
}

/**
 * Agent-specific build info response (for backwards compatibility).
 * Uses agentConfig instead of resourceConfig.
 */
export interface AgentShipwrightBuildInfo {
  // Build info
  name: string;
  namespace: string;
  buildRegistered: boolean;
  buildReason?: string;
  buildMessage?: string;
  outputImage: string;
  strategy: string;
  gitUrl: string;
  gitRevision: string;
  contextDir: string;

  // Latest BuildRun info
  hasBuildRun: boolean;
  buildRunName?: string;
  buildRunPhase?: BuildRunPhase;
  buildRunStartTime?: string;
  buildRunCompletionTime?: string;
  buildRunOutputImage?: string;
  buildRunOutputDigest?: string;
  buildRunFailureMessage?: string;

  // Agent configuration from annotations (agent-specific for backwards compatibility)
  agentConfig?: ResourceConfigFromBuild;
}

/**
 * Trigger BuildRun response
 */
export interface TriggerBuildRunResponse {
  success: boolean;
  buildRunName: string;
  namespace: string;
  buildName: string;
  message: string;
}

/**
 * Finalize build response
 */
export interface FinalizeBuildResponse {
  success: boolean;
  name: string;
  namespace: string;
  message: string;
}

/**
 * Finalize build request data
 */
export interface FinalizeBuildRequest {
  protocol?: string;
  framework?: string;
  envVars?: Array<{
    name: string;
    value?: string;
    valueFrom?: {
      secretKeyRef?: { name: string; key: string };
      configMapKeyRef?: { name: string; key: string };
    };
  }>;
  servicePorts?: Array<{
    name: string;
    port: number;
    targetPort: number;
    protocol: string;
  }>;
  createHttpRoute?: boolean;
  imagePullSecret?: string;
}

/**
 * Helper function to determine if a build is in progress
 */
export function isBuildInProgress(phase?: BuildRunPhase): boolean {
  return phase === 'Pending' || phase === 'Running';
}

/**
 * Helper function to determine if a build has completed (success or failure)
 */
export function isBuildComplete(phase?: BuildRunPhase): boolean {
  return phase === 'Succeeded' || phase === 'Failed';
}

/**
 * Helper function to determine if a build succeeded
 */
export function isBuildSucceeded(phase?: BuildRunPhase): boolean {
  return phase === 'Succeeded';
}

/**
 * Helper function to determine if a build failed
 */
export function isBuildFailed(phase?: BuildRunPhase): boolean {
  return phase === 'Failed';
}

/**
 * Helper function to get a human-readable build status message
 */
export function getBuildStatusMessage(buildInfo: ShipwrightBuildInfo | AgentShipwrightBuildInfo): string {
  if (!buildInfo.buildRegistered) {
    return buildInfo.buildMessage || 'Build not registered';
  }

  if (!buildInfo.hasBuildRun) {
    return 'No build run started';
  }

  switch (buildInfo.buildRunPhase) {
    case 'Pending':
      return 'Build pending...';
    case 'Running':
      return 'Build in progress...';
    case 'Succeeded':
      return 'Build completed successfully';
    case 'Failed':
      return buildInfo.buildRunFailureMessage || 'Build failed';
    default:
      return 'Unknown build status';
  }
}

/**
 * Helper function to get a status color/variant for PatternFly components
 */
export function getBuildStatusVariant(
  phase?: BuildRunPhase
): 'success' | 'warning' | 'danger' | 'info' | 'default' {
  switch (phase) {
    case 'Succeeded':
      return 'success';
    case 'Failed':
      return 'danger';
    case 'Running':
      return 'info';
    case 'Pending':
      return 'warning';
    default:
      return 'default';
  }
}

/**
 * Convert AgentShipwrightBuildInfo to generic ShipwrightBuildInfo
 */
export function toGenericBuildInfo(agentBuildInfo: AgentShipwrightBuildInfo): ShipwrightBuildInfo {
  return {
    ...agentBuildInfo,
    resourceType: 'agent',
    resourceConfig: agentBuildInfo.agentConfig,
  };
}

/**
 * Convert generic ShipwrightBuildInfo to AgentShipwrightBuildInfo (for backwards compatibility)
 */
export function toAgentBuildInfo(buildInfo: ShipwrightBuildInfo): AgentShipwrightBuildInfo {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { resourceType, resourceConfig, ...rest } = buildInfo;
  return {
    ...rest,
    agentConfig: resourceConfig,
  };
}
