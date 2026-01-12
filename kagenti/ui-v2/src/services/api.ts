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
  }): Promise<{ name: string; status: string }> {
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
    containerImage: string;
    protocol: string;
    framework: string;
    envVars?: Array<{ name: string; value: string }>;
    imagePullSecret?: string;
    servicePorts?: Array<{
      name: string;
      port: number;
      targetPort: number;
      protocol: string;
    }>;
    // HTTPRoute/Route creation
    createHttpRoute?: boolean;
  }): Promise<{ name: string; status: string }> {
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
