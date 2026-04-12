// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Type definitions for the Sandbox Legion management UI.
 *
 * These types map to the A2A SDK's DatabaseTaskStore schema.
 * The backend reads from the SDK-managed 'tasks' table.
 */

export interface TaskStatus {
  state: string;
  message?: {
    role?: string;
    parts?: Array<{ kind: string; text?: string }>;
    messageId?: string;
  };
  timestamp?: string;
}

export interface TaskSummary {
  id: string;
  context_id: string;
  kind: string;
  status: TaskStatus;
  metadata: Record<string, unknown> | null;
}

export interface TaskDetail extends TaskSummary {
  artifacts: Array<{
    parts: Array<{ kind: string; text?: string }>;
    name?: string;
  }> | null;
  history: Array<{
    role: string;
    parts: Array<{ kind: string; text?: string }>;
    messageId?: string;
  }> | null;
}

export interface TaskListResponse {
  items: TaskSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface HistoryMessage {
  role: string;
  parts: Array<{ kind: string; text?: string }>;
  messageId?: string;
  _index?: number;
}

export interface HistoryPage {
  messages: HistoryMessage[];
  total: number;
  has_more: boolean;
  loop_events?: Array<Record<string, unknown>>;
  task_state?: string;
  last_updated?: string;
}

export interface SandboxAgentInfo {
  name: string;
  namespace: string;
  status: 'ready' | 'pending' | 'error';
  replicas: string;
  session_count: number;
  active_sessions: number;
  image: string;
  created: string | null;
}
