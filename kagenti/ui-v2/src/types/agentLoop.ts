// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Type definitions for AgentLoop — structured reasoning loop events.
 *
 * When SSE events carry a `loop_id` field, messages are grouped into
 * an AgentLoop and rendered as an expandable AgentLoopCard instead of
 * flat chat bubbles.
 */

export interface AgentLoop {
  id: string;                    // loop_id
  status: 'planning' | 'executing' | 'reflecting' | 'done' | 'failed';
  model: string;
  plan: string[];
  currentStep: number;
  totalSteps: number;
  iteration: number;
  steps: AgentLoopStep[];
  reflection?: string;
  finalAnswer?: string;
  budget: {
    tokensUsed: number;
    tokensBudget: number;
    wallClockS: number;
    maxWallClockS: number;
  };
}

export type NodeType = 'planner' | 'executor' | 'reflector' | 'reporter';

export interface AgentLoopStep {
  index: number;
  description: string;
  model: string;
  tokens: { prompt: number; completion: number };
  toolCalls: Array<{ type: string; name?: string; args?: unknown; tools?: unknown[] }>;
  toolResults: Array<{ type: string; name?: string; output?: string }>;
  durationMs: number;
  status: 'pending' | 'running' | 'done' | 'failed';
  nodeType?: NodeType;
}
