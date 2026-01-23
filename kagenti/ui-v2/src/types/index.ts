// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Core type definitions for the Kagenti UI.
 */

// Workload types for agent deployment
export type WorkloadType = 'deployment' | 'statefulset' | 'job';

// Agent types
export interface AgentLabels {
  protocol?: string;
  framework?: string;
  type?: string;
  workloadType?: WorkloadType;
}

export interface Agent {
  name: string;
  namespace: string;
  description: string;
  status: 'Ready' | 'Not Ready' | 'Progressing';
  labels: AgentLabels;
  workloadType?: WorkloadType;
  createdAt?: string;
}

// Deployment status structure (from Kubernetes)
// Note: K8s Python client returns snake_case, while raw API returns camelCase
export interface DeploymentStatus {
  replicas?: number;
  readyReplicas?: number;
  ready_replicas?: number; // snake_case from K8s Python client
  availableReplicas?: number;
  available_replicas?: number; // snake_case from K8s Python client
  updatedReplicas?: number;
  updated_replicas?: number; // snake_case from K8s Python client
  conditions?: Array<{
    type: string;
    status: string;
    reason?: string;
    message?: string;
    lastTransitionTime?: string;
    last_transition_time?: string; // snake_case from K8s API
  }>;
}

// Service info returned with agent details
export interface ServiceInfo {
  name: string;
  type?: string;
  clusterIP?: string;
  ports?: Array<{
    name?: string;
    port: number;
    targetPort?: number | string;
    protocol?: string;
  }>;
}

// Container spec in Deployment
export interface ContainerSpec {
  name: string;
  image: string;
  imagePullPolicy?: string;
  env?: Array<{
    name: string;
    value?: string;
    valueFrom?: {
      secretKeyRef?: { name: string; key: string };
      configMapKeyRef?: { name: string; key: string };
    };
  }>;
  ports?: Array<{
    name?: string;
    containerPort: number;
    protocol?: string;
  }>;
  resources?: {
    limits?: { cpu?: string; memory?: string };
    requests?: { cpu?: string; memory?: string };
  };
}

export interface AgentDetail {
  metadata: {
    name: string;
    namespace: string;
    labels: Record<string, string>;
    annotations?: Record<string, string>;
    creationTimestamp: string;
    uid: string;
  };
  // Deployment spec structure
  spec: {
    replicas?: number;
    selector?: {
      matchLabels?: Record<string, string>;
    };
    template?: {
      metadata?: {
        labels?: Record<string, string>;
      };
      spec?: {
        containers?: ContainerSpec[];
        volumes?: Array<{
          name: string;
          emptyDir?: Record<string, unknown>;
          configMap?: { name: string };
          secret?: { secretName: string };
        }>;
        imagePullSecrets?: Array<{ name: string }>;
      };
    };
    // Legacy Agent CRD fields (for backward compatibility)
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
  status?: DeploymentStatus;
  // Service info (new)
  service?: ServiceInfo;
  // Workload type (new)
  workloadType?: WorkloadType;
  // Computed ready status from backend (handles Deployment, StatefulSet, Job)
  readyStatus?: 'Ready' | 'Not Ready' | 'Progressing' | 'Completed' | 'Failed' | 'Running' | 'Pending' | 'Unknown';
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
    phase?: string;
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
