// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * API client for paginated event and task retrieval.
 *
 * Uses the /api/v1/sandbox/{ns}/events and /api/v1/sandbox/{ns}/tasks/paginated
 * endpoints introduced by the event persistor backend.
 */

import { API_CONFIG } from './api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EventRecord {
  id: number;
  context_id: string;
  task_id: string;
  event_index: number;
  event_type: string;
  event_category: string | null;
  langgraph_node: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface PaginatedEvents {
  events: EventRecord[];
  has_more: boolean;
  next_index: number;
}

export interface TaskSummary {
  task_id: string;
  user_message: string;
  status: string;
  step_count: number;
  created_at: string | null;
  agent_name: string;
}

export interface PaginatedTasks {
  tasks: TaskSummary[];
  has_more: boolean;
}

export interface SandboxDefaults {
  name: string;
  repo: string;
  branch: string;
  context_dir: string;
  dockerfile: string;
  base_agent: string;
  model: string;
  namespace: string;
  enable_persistence: boolean;
  isolation_mode: string;
  workspace_size: string;
  workspace_storage: string;
  secctx: boolean;
  landlock: boolean;
  proxy: boolean;
  proxy_domains: string | null;
  managed_lifecycle: boolean;
  ttl_hours: number;
  non_root: boolean;
  drop_caps: boolean;
  read_only_root: boolean;
  proxy_allowlist: string;
  github_pat: string | null;
  github_pat_secret_name: string | null;
  llm_api_key: string | null;
  llm_key_source: string;
  llm_secret_name: string;
  allowed_models: string[] | null;
  model_planner: string;
  model_executor: string;
  model_reflector: string;
  model_reporter: string;
  model_thinking: string;
  model_micro_reasoning: string;
  skill_packs: string[];
  force_tool_choice: boolean;
  text_tool_parsing: boolean;
  debug_prompts: boolean;
  enable_tracing: boolean;
  max_iterations: number;
  max_tokens: number;
  max_tool_calls_per_step: number;
  max_think_act_cycles: number;
  thinking_iteration_budget: number;
  max_parallel_tool_calls: number;
  max_wall_clock_s: number;
  hitl_interval: number;
  recursion_limit: number;
  agent_memory_limit: string | null;
  agent_cpu_limit: string | null;
  proxy_memory_limit: string | null;
  proxy_cpu_limit: string | null;
  // Cluster-level defaults
  default_llm_model: string;
  default_llm_secret: string;
  default_llm_secret_key: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Token getter (reuse from api.ts)
// ---------------------------------------------------------------------------

let _tokenGetter: (() => Promise<string | null>) | null = null;

/** Set by AuthContext — same pattern as api.ts */
export function setEventServiceTokenGetter(getter: () => Promise<string | null>): void {
  _tokenGetter = getter;
}

async function authedFetch<T>(url: string): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (_tokenGetter) {
    try {
      const token = await _tokenGetter();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    } catch { /* skip */ }
  }
  const response = await fetch(url, { headers });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `API error: ${response.status}`);
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

export const eventService = {
  /**
   * Get paginated tasks for a session context.
   */
  async getTasks(
    namespace: string,
    contextId: string,
    limit: number = 5,
    beforeId?: string,
  ): Promise<PaginatedTasks> {
    const qs = new URLSearchParams();
    qs.set('context_id', contextId);
    qs.set('limit', String(limit));
    if (beforeId) qs.set('before_id', beforeId);
    return authedFetch<PaginatedTasks>(
      `${API_CONFIG.baseUrl}/sandbox/${encodeURIComponent(namespace)}/tasks/paginated?${qs}`,
    );
  },

  /**
   * Get paginated events for a session/task.
   */
  async getEvents(
    namespace: string,
    contextId: string,
    taskId: string,
    fromIndex: number = 0,
    limit: number = 100,
  ): Promise<PaginatedEvents> {
    const qs = new URLSearchParams();
    qs.set('context_id', contextId);
    qs.set('task_id', taskId);
    qs.set('from_index', String(fromIndex));
    qs.set('limit', String(limit));
    return authedFetch<PaginatedEvents>(
      `${API_CONFIG.baseUrl}/sandbox/${encodeURIComponent(namespace)}/events?${qs}`,
    );
  },

  /**
   * Get backend sandbox defaults.
   */
  async getDefaults(): Promise<SandboxDefaults> {
    return authedFetch<SandboxDefaults>(
      `${API_CONFIG.baseUrl}/sandbox/defaults`,
    );
  },
};
