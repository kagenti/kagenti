// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Type definitions for AgentLoop — structured reasoning loop events.
 *
 * When SSE events carry a `loop_id` field, messages are grouped into
 * an AgentLoop and rendered as an expandable AgentLoopCard instead of
 * flat chat bubbles.
 */

/**
 * Discriminated event types emitted by LangGraph nodes.
 * Must stay in sync with ``event_schema.py`` (Python side).
 */
export type NodeEventType =
  | 'planner_output'
  | 'executor_step'
  | 'tool_call'
  | 'tool_result'
  | 'reflector_decision'
  | 'reporter_output'
  | 'budget_update'
  | 'hitl_request'
  | 'micro_reasoning';

/** @deprecated Use {@link NodeEventType} for new code. */
export type NodeType = 'planner' | 'executor' | 'reflector' | 'reporter' | 'replanner';

export interface AgentLoop {
  id: string;                    // loop_id
  status: 'planning' | 'executing' | 'reflecting' | 'done' | 'failed' | 'canceled';
  model: string;
  /** The user message that triggered this loop. */
  userMessage?: string;
  plan: string[];
  replans: Array<{ iteration: number; steps: string[]; model: string; content?: string }>;
  currentStep: number;
  totalSteps: number;
  iteration: number;
  steps: AgentLoopStep[];
  reflection?: string;
  reflectorDecision?: 'continue' | 'replan' | 'done';
  finalAnswer?: string;
  failureReason?: string;
  /** Highest graph node visit index seen (global recursion counter). */
  nodeVisits: number;
  budget: {
    tokensUsed: number;
    tokensBudget: number;
    wallClockS: number;
    maxWallClockS: number;
  };
}

export interface ThinkingIteration {
  type: 'thinking';
  loop_id: string;
  iteration: number;
  total_iterations: number;
  reasoning: string;
  node?: string;
  model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  system_prompt?: string;
  prompt_messages?: Array<{ role: string; preview: string }>;
  bound_tools?: Array<{ name: string; description?: string }>;
  llm_response?: unknown;
}

export interface MicroReasoning {
  type: 'micro_reasoning';
  loop_id: string;
  step: number;
  micro_step: number;
  reasoning: string;
  next_action: string;
  model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  system_prompt?: string;
  prompt_messages?: Array<{ role: string; preview: string }>;
  bound_tools?: Array<{ name: string; description?: string }>;
  after_call_id?: string;
  /** Number of thinking iterations that preceded this micro-reasoning. */
  thinking_count?: number;
}

export interface PromptMessage {
  role: string;
  preview: string;
}

export interface AgentLoopStep {
  index: number;
  description: string;
  model: string;
  tokens: { prompt: number; completion: number };
  toolCalls: Array<{ type: string; name?: string; args?: unknown; tools?: unknown[]; call_id?: string }>;
  toolResults: Array<{ type: string; name?: string; output?: string; call_id?: string; status?: 'success' | 'error' | 'timeout' | 'pending' }>;
  durationMs: number;
  status: 'pending' | 'running' | 'done' | 'failed';
  /** LLM reasoning / chain-of-thought text (optional, model-dependent). */
  reasoning?: string;
  /** System prompt sent to the LLM for this step. */
  systemPrompt?: string;
  /** Full message list sent to the LLM (summarized). */
  promptMessages?: PromptMessage[];
  /** Tool schemas bound to the LLM for this step. */
  boundTools?: Array<{ name: string; description?: string }>;
  /** Granular event type from the graph node. */
  eventType?: NodeEventType;
  /** @deprecated Use {@link eventType} for new code. */
  nodeType?: NodeType;
  /** Plan step index (0-based) — maps to the plan step, not the global step counter. */
  planStep?: number;
  /** Timestamp when this step was first created (ISO string). */
  createdAt?: string;
  /** Timestamp when this step was last updated (ISO string). */
  updatedAt?: string;
  /** Micro-reasoning entries between tool calls within this step. */
  microReasonings?: MicroReasoning[];
  /** Thinking iterations that preceded each micro-reasoning. */
  thinkings?: ThinkingIteration[];
  /** Files touched during the agent loop (reported by the reporter node). */
  filesTouched?: string[];
}
