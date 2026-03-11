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
  status: 'planning' | 'executing' | 'reflecting' | 'done' | 'failed';
  model: string;
  plan: string[];
  replans: Array<{ iteration: number; steps: string[]; model: string; content?: string }>;
  currentStep: number;
  totalSteps: number;
  iteration: number;
  steps: AgentLoopStep[];
  reflection?: string;
  reflectorDecision?: 'continue' | 'replan' | 'done';
  finalAnswer?: string;
  budget: {
    tokensUsed: number;
    tokensBudget: number;
    wallClockS: number;
    maxWallClockS: number;
  };
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
  toolCalls: Array<{ type: string; name?: string; args?: unknown; tools?: unknown[] }>;
  toolResults: Array<{ type: string; name?: string; output?: string }>;
  durationMs: number;
  status: 'pending' | 'running' | 'done' | 'failed';
  /** LLM reasoning / chain-of-thought text (optional, model-dependent). */
  reasoning?: string;
  /** System prompt sent to the LLM for this step. */
  systemPrompt?: string;
  /** Full message list sent to the LLM (summarized). */
  promptMessages?: PromptMessage[];
  /** Granular event type from the graph node. */
  eventType?: NodeEventType;
  /** @deprecated Use {@link eventType} for new code. */
  nodeType?: NodeType;
  /** Micro-reasoning entries between tool calls within this step. */
  microReasonings?: MicroReasoning[];
}
