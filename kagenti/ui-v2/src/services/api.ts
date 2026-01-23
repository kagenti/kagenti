// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * API service layer for communicating with the Kagenti backend.
 */

import type {
  Agent,
  AgentDetail,
  Tool,
  ToolDetail,
  ApiListResponse,
} from '@/types';

// API configuration
export const API_CONFIG = {
  baseUrl: '/api/v1',
  domainName: 'localtest.me',
};

// Token getter function - set by AuthContext
let tokenGetter: (() => Promise<string | null>) | null = null;

/**
 * Set the token getter function. Called by AuthContext on initialization.
 */
export function setTokenGetter(getter: () => Promise<string | null>): void {
  tokenGetter = getter;
}

/**
 * Generic fetch wrapper with error handling and optional authentication
 */
async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {},
  skipAuth: boolean = false
): Promise<T> {
  const url = `${API_CONFIG.baseUrl}${endpoint}`;

  // Build headers with optional Authorization
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  // Add Authorization header if token getter is set and we're not skipping auth
  if (!skipAuth && tokenGetter) {
    try {
      const token = await tokenGetter();
      if (token) {
        (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
      }
    } catch (error) {
      console.warn('Failed to get auth token:', error);
    }
  }

  const response = await fetch(url, {
    headers,
    ...options,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `API error: ${response.status} ${response.statusText}`
    );
  }

  return response.json();
}

/**
 * Namespace service
 */
export const namespaceService = {
  async list(enabledOnly: boolean = true): Promise<string[]> {
    const params = new URLSearchParams();
    if (enabledOnly) {
      params.set('enabled_only', 'true');
    }
    const response = await apiFetch<{ namespaces: string[] }>(
      `/namespaces?${params}`
    );
    return response.namespaces;
  },
};

/**
 * Agent service
 */
export const agentService = {
  async list(namespace: string): Promise<Agent[]> {
    const response = await apiFetch<ApiListResponse<Agent>>(
      `/agents?namespace=${encodeURIComponent(namespace)}`
    );
    return response.items;
  },

  async get(namespace: string, name: string): Promise<AgentDetail> {
    return apiFetch<AgentDetail>(
      `/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`
    );
  },

  async delete(namespace: string, name: string): Promise<{ success: boolean; message: string }> {
    return apiFetch(
      `/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`,
      { method: 'DELETE' }
    );
  },

  async getRouteStatus(namespace: string, name: string): Promise<{ hasRoute: boolean }> {
    return apiFetch<{ hasRoute: boolean }>(
      `/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/route-status`
    );
  },

  async create(data: {
    name: string;
    namespace: string;
    gitUrl: string;
    gitPath: string;
    gitBranch: string;
    imageTag: string;
    protocol: string;
    framework: string;
    envVars?: Array<{
      name: string;
      value?: string;
      valueFrom?: {
        secretKeyRef?: { name: string; key: string };
        configMapKeyRef?: { name: string; key: string };
      };
    }>;
    // Workload type
    workloadType?: 'deployment' | 'statefulset' | 'job';
    // New fields for deployment method
    deploymentMethod?: 'source' | 'image';
    // Build from source fields
    registryUrl?: string;
    registrySecret?: string;
    startCommand?: string;
    // Deploy from image fields
    containerImage?: string;
    imagePullSecret?: string;
    // Pod configuration
    servicePorts?: Array<{
      name: string;
      port: number;
      targetPort: number;
      protocol: string;
    }>;
    // HTTPRoute/Route creation
    createHttpRoute?: boolean;
    // Shipwright build configuration
    useShipwright?: boolean;
    shipwrightConfig?: ShipwrightBuildConfig;
  }): Promise<{ success: boolean; name: string; namespace: string; message: string }> {
    return apiFetch('/agents', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async getBuildStatus(
    namespace: string,
    name: string
  ): Promise<{
    name: string;
    namespace: string;
    phase: string;
    conditions: Array<{
      type: string;
      status: string;
      reason?: string;
      message?: string;
      lastTransitionTime?: string;
    }>;
    image?: string;
    imageTag?: string;
    startTime?: string;
    completionTime?: string;
  }> {
    return apiFetch(
      `/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/build`
    );
  },

  async parseEnvFile(content: string): Promise<{
    envVars: Array<{
      name: string;
      value?: string;
      valueFrom?: {
        secretKeyRef?: { name: string; key: string };
        configMapKeyRef?: { name: string; key: string };
      };
    }>;
    warnings?: string[];
  }> {
    return apiFetch('/agents/parse-env', {
      method: 'POST',
      body: JSON.stringify({ content }),
    });
  },

  async fetchEnvFromUrl(url: string): Promise<{
    content: string;
    url: string;
  }> {
    return apiFetch('/agents/fetch-env-url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
  },
};

/**
 * Shipwright build types
 */
export interface ShipwrightBuildConfig {
  buildStrategy: string;
  dockerfile: string;
  buildArgs?: string[];
  buildTimeout: string;
}

export interface ClusterBuildStrategy {
  name: string;
  description?: string;
}

export interface ShipwrightBuildStatus {
  name: string;
  namespace: string;
  registered: boolean;
  reason?: string;
  message?: string;
}

export interface ShipwrightBuildRunStatus {
  name: string;
  namespace: string;
  buildName: string;
  phase: 'Pending' | 'Running' | 'Succeeded' | 'Failed';
  startTime?: string;
  completionTime?: string;
  outputImage?: string;
  outputDigest?: string;
  failureMessage?: string;
  conditions: Array<{
    type: string;
    status: string;
    reason?: string;
    message?: string;
    lastTransitionTime?: string;
  }>;
}

export interface AgentConfigFromBuild {
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

export interface ShipwrightBuildInfo {
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
  buildRunPhase?: 'Pending' | 'Running' | 'Succeeded' | 'Failed';
  buildRunStartTime?: string;
  buildRunCompletionTime?: string;
  buildRunOutputImage?: string;
  buildRunOutputDigest?: string;
  buildRunFailureMessage?: string;

  // Agent configuration from annotations
  agentConfig?: AgentConfigFromBuild;
}

/**
 * Shipwright build service
 */
export const shipwrightService = {
  /**
   * List available ClusterBuildStrategies
   */
  async listBuildStrategies(): Promise<ClusterBuildStrategy[]> {
    const response = await apiFetch<{ strategies: ClusterBuildStrategy[] }>(
      '/agents/build-strategies'
    );
    return response.strategies;
  },

  /**
   * Get Shipwright Build status
   */
  async getBuildStatus(namespace: string, name: string): Promise<ShipwrightBuildStatus> {
    return apiFetch<ShipwrightBuildStatus>(
      `/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/shipwright-build`
    );
  },

  /**
   * Get latest Shipwright BuildRun status
   */
  async getBuildRunStatus(namespace: string, name: string): Promise<ShipwrightBuildRunStatus> {
    return apiFetch<ShipwrightBuildRunStatus>(
      `/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/shipwright-buildrun`
    );
  },

  /**
   * Get full Shipwright Build info including agent config and BuildRun status
   */
  async getBuildInfo(namespace: string, name: string): Promise<ShipwrightBuildInfo> {
    return apiFetch<ShipwrightBuildInfo>(
      `/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/shipwright-build-info`
    );
  },

  /**
   * Trigger a new BuildRun for an existing Build
   */
  async triggerBuildRun(
    namespace: string,
    name: string
  ): Promise<{ success: boolean; buildRunName: string; message: string }> {
    return apiFetch(
      `/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/shipwright-buildrun`,
      { method: 'POST' }
    );
  },

  /**
   * Finalize a Shipwright build by creating the Agent
   */
  async finalizeBuild(
    namespace: string,
    name: string,
    data: {
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
  ): Promise<{ success: boolean; name: string; namespace: string; message: string }> {
    return apiFetch(
      `/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/finalize-shipwright-build`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },
};

/**
 * Tool service
 */
export const toolService = {
  async list(namespace: string): Promise<Tool[]> {
    const response = await apiFetch<ApiListResponse<Tool>>(
      `/tools?namespace=${encodeURIComponent(namespace)}`
    );
    return response.items;
  },

  async get(namespace: string, name: string): Promise<ToolDetail> {
    return apiFetch<ToolDetail>(
      `/tools/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`
    );
  },

  async delete(namespace: string, name: string): Promise<{ success: boolean; message: string }> {
    return apiFetch(
      `/tools/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`,
      { method: 'DELETE' }
    );
  },

  async getRouteStatus(namespace: string, name: string): Promise<{ hasRoute: boolean }> {
    return apiFetch<{ hasRoute: boolean }>(
      `/tools/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/route-status`
    );
  },

  async create(data: {
    name: string;
    namespace: string;
    protocol: string;
    framework: string;
    envVars?: Array<{ name: string; value: string }>;
    servicePorts?: Array<{
      name: string;
      port: number;
      targetPort: number;
      protocol: string;
    }>;
    // Deployment method
    deploymentMethod?: 'image' | 'source';
    // Image deployment fields
    containerImage?: string;
    imagePullSecret?: string;
    // Source build fields
    gitUrl?: string;
    gitRevision?: string;
    contextDir?: string;
    registryUrl?: string;
    registrySecret?: string;
    imageTag?: string;
    shipwrightConfig?: ShipwrightBuildConfig;
    // HTTPRoute/Route creation
    createHttpRoute?: boolean;
  }): Promise<{ success: boolean; name: string; namespace: string; message: string }> {
    return apiFetch('/tools', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async connect(
    namespace: string,
    name: string
  ): Promise<{ tools: Array<{ name: string; description?: string; input_schema?: object }> }> {
    return apiFetch(
      `/tools/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/connect`,
      { method: 'POST' }
    );
  },

  async invoke(
    namespace: string,
    name: string,
    toolName: string,
    args: Record<string, unknown>
  ): Promise<{ result: unknown }> {
    return apiFetch(
      `/tools/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/invoke`,
      {
        method: 'POST',
        body: JSON.stringify({ tool_name: toolName, arguments: args }),
      }
    );
  },
};

/**
 * Tool Shipwright build info (similar to agent build info but for tools)
 */
export interface ToolShipwrightBuildInfo {
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
  buildRunPhase?: 'Pending' | 'Running' | 'Succeeded' | 'Failed';
  buildRunStartTime?: string;
  buildRunCompletionTime?: string;
  buildRunOutputImage?: string;
  buildRunOutputDigest?: string;
  buildRunFailureMessage?: string;

  // Tool configuration from annotations
  toolConfig?: {
    protocol: string;
    framework: string;
    createHttpRoute: boolean;
    registrySecret?: string;
    envVars?: Array<{ name: string; value: string }>;
    servicePorts?: Array<{
      name: string;
      port: number;
      targetPort: number;
      protocol: string;
    }>;
  };
}

/**
 * Tool Shipwright build service
 */
export const toolShipwrightService = {
  /**
   * Get full Shipwright Build info including tool config and BuildRun status
   */
  async getBuildInfo(namespace: string, name: string): Promise<ToolShipwrightBuildInfo> {
    return apiFetch<ToolShipwrightBuildInfo>(
      `/tools/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/shipwright-build-info`
    );
  },

  /**
   * Trigger a new BuildRun for an existing Build
   */
  async triggerBuildRun(
    namespace: string,
    name: string
  ): Promise<{ success: boolean; buildRunName: string; message: string }> {
    return apiFetch(
      `/tools/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/shipwright-buildrun`,
      { method: 'POST' }
    );
  },

  /**
   * Finalize a Shipwright build by creating the MCPServer
   */
  async finalizeBuild(
    namespace: string,
    name: string,
    data: {
      protocol?: string;
      framework?: string;
      envVars?: Array<{ name: string; value: string }>;
      servicePorts?: Array<{
        name: string;
        port: number;
        targetPort: number;
        protocol: string;
      }>;
      createHttpRoute?: boolean;
      imagePullSecret?: string;
    }
  ): Promise<{ success: boolean; name: string; namespace: string; message: string }> {
    return apiFetch(
      `/tools/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/finalize-shipwright-build`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },
};

/**
 * Dashboard configuration response from backend
 */
export interface DashboardConfig {
  traces: string;
  network: string;
  mcpInspector: string;
  mcpProxy: string;
  keycloakConsole: string;
  domainName: string;
}

/**
 * Config service
 */
export const configService = {
  async getDashboards(): Promise<DashboardConfig> {
    return apiFetch('/config/dashboards');
  },
};

/**
 * Chat service for A2A agent communication
 */
export const chatService = {
  async getAgentCard(
    namespace: string,
    name: string
  ): Promise<{
    name: string;
    description?: string;
    version: string;
    url: string;
    streaming: boolean;
    skills: Array<{
      id: string;
      name: string;
      description?: string;
      examples?: string[];
    }>;
  }> {
    return apiFetch(
      `/chat/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/agent-card`
    );
  },

  async sendMessage(
    namespace: string,
    name: string,
    message: string,
    sessionId?: string
  ): Promise<{
    content: string;
    session_id: string;
    is_complete: boolean;
  }> {
    return apiFetch(
      `/chat/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/send`,
      {
        method: 'POST',
        body: JSON.stringify({
          message,
          session_id: sessionId,
        }),
      }
    );
  },
};
