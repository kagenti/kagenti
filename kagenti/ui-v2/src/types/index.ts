// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Core type definitions for the Kagenti UI.
 */

// Agent types
export interface AgentLabels {
  protocol?: string;
  framework?: string;
  type?: string;
}

export interface Agent {
  name: string;
  namespace: string;
  description: string;
  status: 'Ready' | 'Not Ready';
  labels: AgentLabels;
  createdAt?: string;
}

export interface AgentDetail {
  metadata: {
    name: string;
    namespace: string;
    labels: Record<string, string>;
    creationTimestamp: string;
    uid: string;
  };
  spec: {
    description?: string;
    source?: {
      git?: {
        url: string;
        path: string;
        branch?: string;
      };
    };
    image?: {
      tag?: string;
    };
    imageSource?: {
      image?: string;
      buildRef?: {
        name: string;
      };
    };
  };
  status?: {
    conditions?: Array<{
      type: string;
      status: string;
      reason?: string;
      message?: string;
      lastTransitionTime?: string;
    }>;
  };
}

// Tool types
export interface ToolLabels {
  protocol?: string;
  framework?: string;
  type?: string;
}

export interface Tool {
  name: string;
  namespace: string;
  description: string;
  status: 'Ready' | 'Not Ready';
  labels: ToolLabels;
  createdAt?: string;
}

export interface MCPTool {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

export interface ToolDetail {
  metadata: {
    name: string;
    namespace: string;
    labels: Record<string, string>;
    creationTimestamp: string;
    uid: string;
  };
  spec: {
    description?: string;
    source?: {
      git?: {
        url: string;
        path: string;
        branch?: string;
      };
    };
  };
  status?: {
    conditions?: Array<{
      type: string;
      status: string;
      reason?: string;
      message?: string;
    }>;
  };
  mcpTools?: MCPTool[];
}

// Environment variable types
export interface EnvVarDirect {
  name: string;
  value: string;
}

export interface EnvVarFromSource {
  name: string;
  sourceName: string;
  sourceKey: string;
}

export interface EnvVarFieldRef {
  name: string;
  fieldPath: string;
}

export interface EnvironmentVariables {
  direct: EnvVarDirect[];
  configmap: EnvVarFromSource[];
  secret: EnvVarFromSource[];
  fieldref: EnvVarFieldRef[];
  resourcefield: Array<{ name: string; resource: string }>;
  error?: string;
}

// Chat types
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

// API response types
export interface ApiListResponse<T> {
  items: T[];
}

export interface ApiErrorResponse {
  detail: string;
}

// Import form types
export interface ImportFormData {
  name: string;
  namespace: string;
  gitUrl: string;
  gitPath: string;
  gitBranch: string;
  imageTag: string;
  protocol: string;
  framework: string;
  envVars?: Array<{ name: string; value: string }>;
}

// Dashboard config types
export interface DashboardConfig {
  traces: string;
  network: string;
  mcpInspector: string;
}

// Auth types
export interface User {
  username: string;
  email?: string;
  roles?: string[];
}
