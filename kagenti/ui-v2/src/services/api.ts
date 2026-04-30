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
  Integration,
  IntegrationDetail,
  IntegrationProvider,
  IntegrationAgentRef,
  IntegrationWebhook,
  IntegrationSchedule,
  IntegrationAlert,
  FileEntry,
  FileContent,
  PodStorageStats,
  Skill,
  SkillDetail,
  SkillFile,
  CreateSkillRequest,
  CreateSkillResponse,
  AuthBridgeConfig,
  AuthBridgeStats,
} from '@/types';

// API configuration
export const API_CONFIG = {
  baseUrl: '/api/v1',
  domainName: 'localtest.me',
};

// Token getter function - set by AuthContext
let tokenGetter: (() => Promise<string | null>) | null = null;

// Force-refresh function - set by AuthContext to bypass token cache
let tokenForceRefresher: (() => Promise<string | null>) | null = null;

/**
 * Set the token getter function. Called by AuthContext on initialization.
 */
export function setTokenGetter(getter: () => Promise<string | null>): void {
  tokenGetter = getter;
}

/**
 * Set the force-refresh function. Called by AuthContext on initialization.
 * Used to get a fresh token on 401 responses (issue #1009).
 */
export function setTokenForceRefresher(refresher: () => Promise<string | null>): void {
  tokenForceRefresher = refresher;
}

/**
 * Error class that preserves the HTTP status code from API responses.
 */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/**
 * Generic fetch wrapper with error handling, optional authentication,
 * and automatic token refresh on 401 responses.
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

  // On 401, try once with a force-refreshed token (issue #1009)
  if (response.status === 401 && !skipAuth && tokenForceRefresher) {
    try {
      const freshToken = await tokenForceRefresher();
      if (freshToken) {
        const retryHeaders: HeadersInit = {
          ...headers,
          Authorization: `Bearer ${freshToken}`,
        };
        const retryResponse = await fetch(url, {
          ...options,
          headers: retryHeaders,
        });
        if (!retryResponse.ok) {
          const errorData = await retryResponse.json().catch(() => ({}));
          throw new Error(
            errorData.detail || `API error: ${retryResponse.status} ${retryResponse.statusText}`
          );
        }
        return retryResponse.json();
      }
    } catch (retryError) {
      // If retry also fails, fall through to the original error
      if (retryError instanceof Error && retryError.message.startsWith('API error:')) {
        throw retryError;
      }
      console.warn('Token refresh retry failed:', retryError);
    }
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new ApiError(
      errorData.detail || `API error: ${response.status} ${response.statusText}`,
      response.status
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
    workloadType?: 'deployment' | 'statefulset' | 'job' | 'sandbox';
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
    // AuthBridge sidecar injection
    authBridgeEnabled?: boolean;
    // SPIRE identity
    spireEnabled?: boolean;
    // Per-sidecar injection controls
    envoyProxyInject?: boolean;
    spiffeHelperInject?: boolean;
    clientRegistrationInject?: boolean;
    outboundRoutes?: Array<{ host: string; target_audience: string; token_scopes: string }>;
    outboundPortsExclude?: string;
    inboundPortsExclude?: string;
    defaultOutboundPolicy?: string;
    shipwrightConfig?: ShipwrightBuildConfig;
  }): Promise<{ success: boolean; name: string; namespace: string; message: string }> {
    return apiFetch('/agents', {
      method: 'POST',
      body: JSON.stringify(data),
    });
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
      authBridgeEnabled?: boolean;
      envoyProxyInject?: boolean;
      spiffeHelperInject?: boolean;
      clientRegistrationInject?: boolean;
      outboundRoutes?: Array<{ host: string; target_audience: string; token_scopes: string }>;
    outboundPortsExclude?: string;
    inboundPortsExclude?: string;
    defaultOutboundPolicy?: string;
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
    // Workload type
    workloadType?: 'deployment' | 'statefulset';
    // Persistent storage (for StatefulSet)
    persistentStorage?: { enabled: boolean; size: string };
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
    // AuthBridge sidecar injection
    authBridgeEnabled?: boolean;
    // SPIRE identity
    spireEnabled?: boolean;
    // Per-sidecar injection controls
    envoyProxyInject?: boolean;
    spiffeHelperInject?: boolean;
    clientRegistrationInject?: boolean;
    outboundRoutes?: Array<{ host: string; target_audience: string; token_scopes: string }>;
    outboundPortsExclude?: string;
    inboundPortsExclude?: string;
    defaultOutboundPolicy?: string;
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
    workloadType?: 'deployment' | 'statefulset';
    persistentStorage?: { enabled: boolean; size: string };
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
   * Finalize a Shipwright build by creating the Deployment/StatefulSet + Service
   */
  async finalizeBuild(
    namespace: string,
    name: string,
    data: {
      protocol?: string;
      framework?: string;
      workloadType?: 'deployment' | 'statefulset';
      persistentStorage?: { enabled: boolean; size: string };
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
      authBridgeEnabled?: boolean;
      envoyProxyInject?: boolean;
      spiffeHelperInject?: boolean;
      clientRegistrationInject?: boolean;
      outboundRoutes?: Array<{ host: string; target_audience: string; token_scopes: string }>;
    outboundPortsExclude?: string;
    inboundPortsExclude?: string;
    defaultOutboundPolicy?: string;
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
  mlflow: string;
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
 * Session Graph types and service (Session E)
 */
export interface GraphNode {
  id: string;
  agent: string;
  status: 'running' | 'completed' | 'failed' | 'pending';
  mode: 'root' | 'in-process' | 'shared-pvc' | 'isolated' | 'sidecar';
  tier: string;
  started_at: string | null;
  duration_ms: number;
  task_summary: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  mode: 'in-process' | 'shared-pvc' | 'isolated' | 'sidecar';
  task: string;
}

export interface SessionGraphData {
  root: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export const sessionGraphService = {
  async getGraph(
    namespace: string,
    contextId: string
  ): Promise<SessionGraphData> {
    return apiFetch(
      `/chat/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/graph`
    );
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
    try {
      return await apiFetch(
        `/chat/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/agent-card`
      );
    } catch {
      // Fallback: sandbox endpoint (direct port 8000, no AuthBridge retry)
      return apiFetch(
        `/sandbox/${encodeURIComponent(namespace)}/agent-card/${encodeURIComponent(name)}`
      );
    }
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

// ---------------------------------------------------------------------------
// Sandbox Legion session management
// ---------------------------------------------------------------------------

import type { TaskListResponse, TaskDetail, HistoryPage, SandboxAgentInfo } from '@/types/sandbox';

export const sandboxService = {
  async listSessions(
    namespace: string,
    params?: { limit?: number; offset?: number; search?: string; agent_name?: string }
  ): Promise<TaskListResponse> {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    if (params?.search) qs.set('search', params.search);
    if (params?.agent_name) qs.set('agent_name', params.agent_name);
    const query = qs.toString() ? `?${qs.toString()}` : '';
    return apiFetch(`/sandbox/${encodeURIComponent(namespace)}/sessions${query}`);
  },

  async getSession(namespace: string, contextId: string): Promise<TaskDetail> {
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}`
    );
  },

  async deleteSession(namespace: string, contextId: string): Promise<void> {
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}`,
      { method: 'DELETE' }
    );
  },

  async killSession(namespace: string, contextId: string): Promise<TaskDetail> {
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/kill`,
      { method: 'POST' }
    );
  },

  async approveSession(
    namespace: string,
    contextId: string
  ): Promise<{ status: string; context_id: string }> {
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/approve`,
      { method: 'POST' }
    );
  },

  async denySession(
    namespace: string,
    contextId: string
  ): Promise<{ status: string; context_id: string }> {
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/deny`,
      { method: 'POST' }
    );
  },

  async renameSession(
    namespace: string,
    contextId: string,
    title: string
  ): Promise<{ title: string }> {
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/rename`,
      {
        method: 'PUT',
        body: JSON.stringify({ title }),
      }
    );
  },

  async setVisibility(
    namespace: string,
    contextId: string,
    visibility: 'private' | 'namespace'
  ): Promise<{ visibility: string }> {
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/visibility`,
      {
        method: 'PUT',
        body: JSON.stringify({ visibility }),
      }
    );
  },

  async getHistory(
    namespace: string,
    contextId: string,
    params?: { limit?: number; before?: number; skip_events?: boolean; events_since?: number }
  ): Promise<HistoryPage> {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.before !== undefined) qs.set('before', String(params.before));
    if (params?.skip_events) qs.set('skip_events', 'true');
    if (params?.events_since !== undefined) qs.set('events_since', String(params.events_since));
    const query = qs.toString() ? `?${qs.toString()}` : '';
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/history${query}`
    );
  },

  /** Return the URL for the SSE streaming chat endpoint. */
  getStreamUrl(namespace: string): string {
    return `${API_CONFIG.baseUrl}/sandbox/${encodeURIComponent(namespace)}/chat/stream`;
  },

  async listAgents(namespace: string): Promise<SandboxAgentInfo[]> {
    return apiFetch<SandboxAgentInfo[]>(
      `/sandbox/${encodeURIComponent(namespace)}/agents`
    );
  },

  /** Fetch the A2A agent card for a sandbox agent (proxied via sandbox router). */
  async getAgentCard(
    namespace: string,
    agentName: string
  ): Promise<{
    name: string;
    description?: string;
    version?: string;
    capabilities?: { streaming?: boolean };
    skills?: Array<{ id: string; name: string; description?: string }>;
    model?: string;
  }> {
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/agent-card/${encodeURIComponent(agentName)}`
    );
  },

  async createSandbox(
    namespace: string,
    data: {
      name: string;
      repo: string;
      branch?: string;
      context_dir?: string;
      dockerfile?: string;
      variant?: string;
      base_agent?: string;
      model?: string;
      namespace?: string;
      enable_persistence?: boolean;
      isolation_mode?: string;
      workspace_size?: string;
      proxy_allowlist?: string;
      // Composable security layers
      secctx?: boolean;
      landlock?: boolean;
      proxy?: boolean;
      proxy_domains?: string;
      // Credentials
      github_pat?: string;
      github_pat_secret_name?: string;
      llm_api_key?: string;
      llm_key_source?: string;
      llm_secret_name?: string;
    }
  ): Promise<{ status: string; message: string; agent_url?: string; security_warnings?: string[] }> {
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/create`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  async getConfig(namespace: string, name: string): Promise<Record<string, unknown>> {
    return apiFetch(`/sandbox/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/config`);
  },

  async updateSandbox(
    namespace: string,
    name: string,
    data: Record<string, unknown>
  ): Promise<{ status: string; message: string; rebuild_required?: boolean }> {
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`,
      {
        method: 'PUT',
        body: JSON.stringify(data),
      }
    );
  },

  async getChildSessions(namespace: string, contextId: string): Promise<Array<{
    context_id: string;
    agent_name: string;
    title: string;
    state: string;
    timestamp: string;
  }>> {
    const response = await apiFetch<{items: Array<Record<string, unknown>>}>(
      `/sandbox/${encodeURIComponent(namespace)}/sessions?limit=100`
    );
    return (response.items || [])
      .filter((s: Record<string, unknown>) => {
        const meta = s.metadata as Record<string, unknown> | undefined;
        return meta?.parent_context_id === contextId;
      })
      .map((s: Record<string, unknown>) => {
        const meta = s.metadata as Record<string, unknown> | undefined;
        const status = s.status as Record<string, unknown> | undefined;
        const cid = (s.context_id || s.id) as string;
        return {
          context_id: cid,
          agent_name: (meta?.agent_name as string) || 'unknown',
          title: (meta?.title as string) || cid?.substring(0, 8) || 'Untitled',
          state: (status?.state as string) || 'unknown',
          timestamp: (status?.timestamp as string) || '',
        };
      });
  },
};

/**
 * Integration service for managing repository integrations
 */
export const integrationService = {
  async list(namespace: string): Promise<Integration[]> {
    const response = await apiFetch<ApiListResponse<Integration>>(
      `/integrations?namespace=${encodeURIComponent(namespace)}`
    );
    return response.items;
  },

  async get(namespace: string, name: string): Promise<IntegrationDetail> {
    return apiFetch<IntegrationDetail>(
      `/integrations/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`
    );
  },

  async create(data: {
    name: string;
    namespace: string;
    repository: {
      url: string;
      provider: IntegrationProvider;
      branch: string;
      credentialsSecret?: string;
    };
    agents: IntegrationAgentRef[];
    webhooks?: IntegrationWebhook[];
    schedules?: IntegrationSchedule[];
    alerts?: IntegrationAlert[];
  }): Promise<{ success: boolean; name: string; namespace: string; message: string }> {
    return apiFetch('/integrations', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async update(
    namespace: string,
    name: string,
    data: Partial<{
      agents: IntegrationAgentRef[];
      webhooks: IntegrationWebhook[];
      schedules: IntegrationSchedule[];
      alerts: IntegrationAlert[];
    }>
  ): Promise<{ success: boolean; message: string }> {
    return apiFetch(
      `/integrations/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`,
      {
        method: 'PUT',
        body: JSON.stringify(data),
      }
    );
  },

  async delete(namespace: string, name: string): Promise<{ success: boolean; message: string }> {
    return apiFetch(
      `/integrations/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`,
      { method: 'DELETE' }
    );
  },

  async testConnection(
    namespace: string,
    name: string
  ): Promise<{ success: boolean; message: string }> {
    return apiFetch(
      `/integrations/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/test`,
      { method: 'POST' }
    );
  },
};

/**
 * Sandbox file service for browsing agent sandbox files
 */
export const sandboxFileService = {
  async listDirectory(
    namespace: string,
    agentName: string,
    path: string,
    contextId?: string
  ): Promise<{ entries: FileEntry[] }> {
    // When contextId is provided, use the context-scoped endpoint
    // which browses /workspace/{contextId}/ and path is relative to that root
    if (contextId) {
      return apiFetch(
        `/sandbox/${encodeURIComponent(namespace)}/files/${encodeURIComponent(agentName)}/${encodeURIComponent(contextId)}?path=${encodeURIComponent(path)}`
      );
    }
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/files/${encodeURIComponent(agentName)}/list?path=${encodeURIComponent(path)}`
    );
  },

  async getFileContent(
    namespace: string,
    agentName: string,
    filePath: string,
    contextId?: string
  ): Promise<FileContent> {
    if (contextId) {
      return apiFetch(
        `/sandbox/${encodeURIComponent(namespace)}/files/${encodeURIComponent(agentName)}/${encodeURIComponent(contextId)}?path=${encodeURIComponent(filePath)}`
      );
    }
    return apiFetch(
      `/sandbox/${encodeURIComponent(namespace)}/files/${encodeURIComponent(agentName)}/content?path=${encodeURIComponent(filePath)}`
    );
  },

  async getStorageStats(
    namespace: string,
    agentName: string
  ): Promise<PodStorageStats> {
    return apiFetch<PodStorageStats>(
      `/sandbox/${encodeURIComponent(namespace)}/stats/${encodeURIComponent(agentName)}`
    );
  },
};

// ---------------------------------------------------------------------------
// LiteLLM Token Usage analytics
// ---------------------------------------------------------------------------

export interface ModelUsage {
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  num_calls: number;
  cost: number;
}

export interface SessionTokenUsage {
  context_id: string;
  models: ModelUsage[];
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_calls: number;
  total_cost: number;
}

export interface SessionTreeUsage {
  context_id: string;
  own_usage: SessionTokenUsage;
  children: SessionTokenUsage[];
  aggregate: SessionTokenUsage;
}

export const tokenUsageService = {
  async getSessionTokenUsage(contextId: string): Promise<SessionTokenUsage> {
    return apiFetch<SessionTokenUsage>(
      `/token-usage/sessions/${encodeURIComponent(contextId)}`
    );
  },

  async getSessionTreeUsage(
    contextId: string,
    namespace?: string
  ): Promise<SessionTreeUsage> {
    const qs = namespace ? `?namespace=${encodeURIComponent(namespace)}` : '';
    return apiFetch<SessionTreeUsage>(
      `/token-usage/sessions/${encodeURIComponent(contextId)}/tree${qs}`
    );
  },
};

/**
 * Sidecar agent service for managing session sidecars
 */
export interface SidecarInfo {
  context_id: string;
  sidecar_type: string;
  parent_context_id: string;
  enabled: boolean;
  auto_approve: boolean;
  config: Record<string, unknown>;
  observation_count: number;
  pending_count: number;
}

export interface SidecarObservation {
  id: string;
  sidecar_type: string;
  timestamp: number;
  message: string;
  severity: string;
  requires_approval: boolean;
}

export const sidecarService = {
  async list(namespace: string, contextId: string): Promise<SidecarInfo[]> {
    return apiFetch(`/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/sidecars`);
  },

  async enable(namespace: string, contextId: string, sidecarType: string, config?: { auto_approve?: boolean; config?: Record<string, unknown> }): Promise<SidecarInfo> {
    return apiFetch(`/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/sidecars/${encodeURIComponent(sidecarType)}/enable`, {
      method: 'POST',
      body: JSON.stringify(config || {}),
    });
  },

  async disable(namespace: string, contextId: string, sidecarType: string): Promise<{ status: string }> {
    return apiFetch(`/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/sidecars/${encodeURIComponent(sidecarType)}/disable`, {
      method: 'POST',
    });
  },

  async updateConfig(namespace: string, contextId: string, sidecarType: string, config: Record<string, unknown>): Promise<SidecarInfo> {
    return apiFetch(`/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/sidecars/${encodeURIComponent(sidecarType)}/config`, {
      method: 'PUT',
      body: JSON.stringify(config),
    });
  },

  async reset(namespace: string, contextId: string, sidecarType: string): Promise<{ status: string }> {
    return apiFetch(`/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/sidecars/${encodeURIComponent(sidecarType)}/reset`, {
      method: 'POST',
    });
  },

  async approve(namespace: string, contextId: string, sidecarType: string, msgId: string): Promise<{ status: string }> {
    return apiFetch(`/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/sidecars/${encodeURIComponent(sidecarType)}/approve/${encodeURIComponent(msgId)}`, {
      method: 'POST',
    });
  },

  async deny(namespace: string, contextId: string, sidecarType: string, msgId: string): Promise<{ status: string }> {
    return apiFetch(`/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/sidecars/${encodeURIComponent(sidecarType)}/deny/${encodeURIComponent(msgId)}`, {
      method: 'POST',
    });
  },

  observationUrl(namespace: string, contextId: string, sidecarType: string): string {
    return `/api/v1/sandbox/${encodeURIComponent(namespace)}/sessions/${encodeURIComponent(contextId)}/sidecars/${encodeURIComponent(sidecarType)}/observations`;
  },
};

/**
 * Sandbox trigger service for managing automated triggers
 */
export const triggerService = {
  async create(data: {
    type: 'cron' | 'webhook' | 'alert';
    skill?: string;
    schedule?: string;
    event?: string;
    repo?: string;
    branch?: string;
    pr_number?: number;
    alert?: string;
    cluster?: string;
    severity?: string;
    namespace?: string;
    ttl_hours?: number;
  }): Promise<{ sandbox_claim: string; namespace: string }> {
    return apiFetch('/sandbox/trigger', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};

/**
 * Graph card service for fetching agent topology data.
 * Falls back to hardcoded sandbox-legion topology when the endpoint is unavailable.
 */
import type { AgentGraphCard } from '@/types/graphCard';

const SANDBOX_LEGION_GRAPH_CARD: AgentGraphCard = {
  id: 'sandbox-legion-v1',
  description: 'Plan-Execute-Reflect loop with tool execution',
  framework: 'langgraph',
  version: '1.0.0',
  event_catalog: {},
  common_event_fields: {},
  topology: {
    description: 'LangGraph graph structure for sandbox-legion agent',
    entry_node: 'router',
    terminal_nodes: ['__end__'],
    nodes: {
      router:          { description: 'Routes to planning or resume based on session state' },
      planner:         { description: 'Creates numbered execution plan' },
      planner_tools:   { description: 'Executes planner tool calls' },
      step_selector:   { description: 'Selects next step, writes focused brief' },
      executor:        { description: 'Executes current step using tools' },
      tools:           { description: 'Executes executor tool calls' },
      reflector:       { description: 'Evaluates results, decides next action' },
      reflector_tools: { description: 'Executes reflector verification reads' },
      reflector_route: { description: 'Pass-through for reflector routing' },
      reporter:        { description: 'Generates final summary report' },
    },
    edges: [
      { from: '__start__',      to: 'router',          condition: null },
      { from: 'router',         to: 'planner',         condition: 'plan',           description: 'New session or replan' },
      { from: 'router',         to: 'step_selector',   condition: 'resume',         description: 'Resume existing plan' },
      { from: 'planner',        to: 'planner_tools',   condition: 'has_tool_calls' },
      { from: 'planner',        to: 'step_selector',   condition: 'no_tool_calls',  description: 'Plan complete' },
      { from: 'planner_tools',  to: 'planner',         condition: null },
      { from: 'step_selector',  to: 'executor',        condition: null },
      { from: 'executor',       to: 'tools',           condition: 'has_tool_calls' },
      { from: 'executor',       to: 'reflector',       condition: 'no_tool_calls',  description: 'Step done' },
      { from: 'tools',          to: 'executor',         condition: null },
      { from: 'reflector',      to: 'reflector_tools',  condition: 'has_tool_calls' },
      { from: 'reflector',      to: 'reflector_route',  condition: 'no_tool_calls' },
      { from: 'reflector_tools', to: 'reflector',       condition: null },
      { from: 'reflector_route', to: 'step_selector',   condition: 'execute',       description: 'Continue/retry' },
      { from: 'reflector_route', to: 'planner',         condition: 'replan' },
      { from: 'reflector_route', to: 'reporter',        condition: 'done' },
      { from: 'reporter',       to: '__end__',          condition: null },
    ],
  },
};

export const graphCardService = {
  /**
   * Fetch the agent graph card. Falls back to hardcoded sandbox-legion topology
   * when the endpoint is unavailable.
   */
  async fetchGraphCard(
    namespace: string,
    agentName: string
  ): Promise<AgentGraphCard> {
    try {
      return await apiFetch<AgentGraphCard>(
        `/chat/${encodeURIComponent(namespace)}/${encodeURIComponent(agentName)}/graph-card`
      );
    } catch {
      // Fallback: return hardcoded sandbox-legion topology
      return SANDBOX_LEGION_GRAPH_CARD;
    }
  },
};

/**
 * Models service for fetching available LLM models from LiteLLM
 */
export const modelsService = {
  async getAvailableModels(): Promise<Array<{id: string}>> {
    return apiFetch<Array<{id: string}>>('/models');
  },
  async getAgentModels(namespace: string, agentName: string): Promise<Array<{id: string}>> {
    return apiFetch<Array<{id: string}>>(`/llm/agent-models/${encodeURIComponent(namespace)}/${encodeURIComponent(agentName)}`);
  },
};

/**
 * Pod status types and API
 */
export interface PodEvent {
  type: string;
  reason: string;
  message: string;
  timestamp: string;
  count: number;
}

export interface PodInfo {
  component: string;
  deployment: string;
  replicas: number;
  ready_replicas: number;
  pod_name: string | null;
  status: string;
  restarts: number;
  last_restart_reason: string | null;
  resources: {
    requests: { cpu: string; memory: string };
    limits: { cpu: string; memory: string };
  };
  events: PodEvent[];
}

export async function getPodStatus(namespace: string, agentName: string): Promise<{ pods: PodInfo[] }> {
  return apiFetch(`/sandbox/${encodeURIComponent(namespace)}/agents/${encodeURIComponent(agentName)}/pod-status`);
}

/**
 * Pod metrics types and API (metrics-server data)
 */
export interface ContainerMetrics {
  name: string;
  cpu_usage_mc: number;
  cpu_limit_mc: number;
  cpu_usage_raw: string;
  memory_usage_bytes: number;
  memory_limit_bytes: number;
  memory_usage_raw: string;
}

export interface PodMetrics {
  component: string;
  pod_name: string;
  limits_cpu: string;
  limits_memory: string;
  containers: ContainerMetrics[];
}

export interface PodEventDetail {
  pod_name: string;
  component: string;
  type: string;
  reason: string;
  message: string;
  timestamp: string;
  count: number;
}

export async function getPodMetrics(
  namespace: string,
  agentName: string,
): Promise<{ pods: PodMetrics[] }> {
  return apiFetch(
    `/sandbox/${encodeURIComponent(namespace)}/pods/${encodeURIComponent(agentName)}/metrics`,
  );
}

export async function getPodEvents(
  namespace: string,
  agentName: string,
): Promise<{ events: PodEventDetail[] }> {
  return apiFetch(
    `/sandbox/${encodeURIComponent(namespace)}/pods/${encodeURIComponent(agentName)}/events`,
  );
}

/**
 * Skill service
 */
export const skillService = {
  async list(namespace: string, query?: string): Promise<Skill[]> {
    const params = new URLSearchParams({ namespace });
    if (query) {
      params.append('q', query);
    }
    const response = await apiFetch<ApiListResponse<Skill>>(`/skills?${params.toString()}`);
    return response.items;
  },

  async get(namespace: string, name: string): Promise<SkillDetail> {
    return apiFetch(`/skills/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`);
  },

  async getFile(namespace: string, name: string, filePath: string): Promise<SkillFile> {
    return apiFetch(
      `/skills/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/files/${encodeURIComponent(filePath)}`
    );
  },

  async create(data: CreateSkillRequest): Promise<CreateSkillResponse> {
    return apiFetch('/skills', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async incrementUsage(namespace: string, name: string): Promise<Skill> {
    return apiFetch(
      `/skills/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/usage`,
      {
        method: 'POST',
      }
    );
  },

  async delete(namespace: string, name: string): Promise<{ success: boolean; message: string }> {
    return apiFetch(
      `/skills/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`,
      {
        method: 'DELETE',
      }
    );
  },
};

export const authBridgeService = {
  async getConfig(namespace: string, name: string): Promise<AuthBridgeConfig> {
    return apiFetch(`/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/identity-config`);
  },

  async getStatus(namespace: string, name: string): Promise<AuthBridgeStats> {
    return apiFetch(`/agents/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/identity-status`);
  },
};

