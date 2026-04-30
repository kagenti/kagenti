// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Core type definitions for the Kagenti UI.
 */

// Workload types for agent deployment
export type WorkloadType = 'deployment' | 'statefulset' | 'job' | 'sandbox';

// Agent types
export interface AgentLabels {
  protocol?: string[];
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

/**
 * Deployment status structure from Kubernetes.
 *
 * This interface supports both camelCase and snake_case field names because:
 * - snake_case: Returned by the Kubernetes Python client (used in our backend API)
 * - camelCase: Returned by the raw Kubernetes API (e.g., direct kubectl responses)
 *
 * When consuming this data, prefer using a fallback pattern:
 *   value.readyReplicas || value.ready_replicas
 */
export interface DeploymentStatus {
  replicas?: number;
  readyReplicas?: number;
  ready_replicas?: number;
  availableReplicas?: number;
  available_replicas?: number;
  updatedReplicas?: number;
  updated_replicas?: number;
  conditions?: Array<{
    type: string;
    status: string;
    reason?: string;
    message?: string;
    lastTransitionTime?: string;
    last_transition_time?: string;
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

// Tool workload types
export type ToolWorkloadType = 'deployment' | 'statefulset';

// Tool types
export interface ToolLabels {
  protocol?: string[];
  framework?: string;
  type?: string;
  transport?: string;
}

export interface Tool {
  name: string;
  namespace: string;
  description: string;
  status: 'Ready' | 'Not Ready' | 'Progressing' | 'Failed';
  labels: ToolLabels;
  workloadType?: ToolWorkloadType;
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
    annotations?: Record<string, string>;
    creationTimestamp?: string;
    creation_timestamp?: string;
    uid?: string;
  };
  // Deployment/StatefulSet spec
  spec: {
    description?: string;
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
          persistentVolumeClaim?: { claimName: string };
        }>;
        imagePullSecrets?: Array<{ name: string }>;
      };
    };
    // StatefulSet-specific
    serviceName?: string;
    volumeClaimTemplates?: Array<{
      metadata: { name: string };
      spec: {
        accessModes: string[];
        resources: { requests: { storage: string } };
      };
    }>;
  };
  // Status from backend (string for workloads, object for legacy CRD)
  status?: string | DeploymentStatus | {
    phase?: string;
    conditions?: Array<{
      type: string;
      status: string;
      reason?: string;
      message?: string;
      lastTransitionTime?: string;
      last_transition_time?: string;
    }>;
  };
  // Workload type
  workloadType?: ToolWorkloadType;
  // Associated Service info
  service?: ServiceInfo;
  // Computed ready status from backend
  readyStatus?: 'Ready' | 'Not Ready' | 'Progressing' | 'Failed';
  // MCP tools (populated after connect)
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

// Integration types
export type IntegrationProvider = 'github' | 'gitlab' | 'bitbucket';

export type IntegrationStatus = 'Connected' | 'Error' | 'Pending';

export interface IntegrationWebhook {
  name: string;
  events: string[];
  filters?: {
    branches?: string[];
    actions?: string[];
  };
}

export interface IntegrationSchedule {
  name: string;
  cron: string;
  skill: string;
  agent: string;
  enabled?: boolean;
}

export interface IntegrationAlert {
  name: string;
  source: 'prometheus' | 'pagerduty';
  matchLabels: Record<string, string>;
  agent: string;
}

export interface IntegrationAgentRef {
  name: string;
  namespace: string;
}

export interface Integration {
  name: string;
  namespace: string;
  repository: {
    url: string;
    provider: IntegrationProvider;
    branch: string;
    credentialsSecret?: string;
  };
  agents: IntegrationAgentRef[];
  webhooks: IntegrationWebhook[];
  schedules: IntegrationSchedule[];
  alerts: IntegrationAlert[];
  status: IntegrationStatus;
  webhookUrl?: string;
  lastWebhookEvent?: string;
  lastScheduleRun?: string;
  createdAt?: string;
}

export interface IntegrationDetail extends Integration {
  conditions?: Array<{
    type: string;
    status: string;
    lastTransitionTime?: string;
    message?: string;
  }>;
}

// File browser types
export interface FileEntry {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size?: number;
  modified?: string;
}

export interface FileContent {
  path: string;
  content: string;
  size: number;
  modified: string;
}

// Pod storage / mount stats
export interface MountInfo {
  filesystem: string;
  size: string;
  used: string;
  available: string;
  use_percent: string;
  mount_point: string;
}

export interface PodStorageStats {
  mounts: MountInfo[];
  total_mounts: number;
}

// Skill types
export interface SkillLabels {
  category?: string;
  type?: string;
}

export interface Skill {
  name: string;
  namespace: string;
  resourceName: string;
  description: string;
  status: string;
  labels: SkillLabels;
  createdAt?: string;
  origin?: string;
  usageCount: number;
}

export interface SkillFile {
  name: string;
  path: string;
  content: string;
  size: number;
}

export interface SkillDetail extends Skill {
  dataKeys: string[];
  annotations: Record<string, string>;
  files: SkillFile[];
}

export interface CreateSkillRequest {
  name: string;
  namespace: string;
  description?: string;
  category?: string;
  url?: string;
  files?: Record<string, string>;
}

export interface CreateSkillResponse {
  success: boolean;
  name: string;
  namespace: string;
  message: string;
}

// AuthBridge types
export interface AuthBridgeConfig {
  AuthBridge: boolean | null
  mode: string | null;
  inbound: InboundConfig | null;
  outbound: OutboundConfig | null;
  identity: IdentityConfig | null;
  listener: ListenerConfig | null;
  bypass:   BypassConfig | null;
  routes:   RoutesConfig | null;
  stats:    StatsConfig | null;
}

export interface InboundConfig {
  jwks_url: string;
  issuer:  string;
}

export interface OutboundConfig {
  token_url:      string;
  keycloak_url:   string;
  keycloak_realm: string;
  default_policy: string;
}

export interface IdentityConfig {
  type:             string; // "spiffe", "client-secret", "k8s-sa"
  client_id:         string;
  client_secret:     string;
  client_id_file:     string;
  client_secret_file: string;
  socket_path:       string;
  jwt_svid_path:      string;
  jwt_audience:      string[];
}

export interface ListenerConfig {
  ext_proc_addr:         string;
  ext_authz_addr:        string;
  forward_proxy_addr:    string;
  reverse_proxy_addr:    string;
  reverse_proxy_backend: string;
}

export interface BypassConfig {
  inbound_paths: string[];
}

export interface RoutesConfig {
  file:  string; // path to routes YAML file
  rules: RouteConfig[]
}

export interface RouteConfig {
  host:           string;
  target_audience: string;
  token_scopes:    string;
  token_url:       string;
  passthrough:    boolean;
  action:         string;
}

export interface StatsConfig {
  address: string; // for example, ":9093"
}

export interface AuthBridgeStats {
  AuthBridge: boolean | null;
  inbound_approvals: Record<string, number> | null;
  inbound_denials: Record<string, number> | null;
  outbound_approvals: Record<string, number> | null;
  outbound_denials: Record<string, number> | null;
  outbound_replace_tokens: Record<string, number> | null;
}
