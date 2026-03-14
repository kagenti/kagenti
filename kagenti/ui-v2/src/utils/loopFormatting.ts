// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Shared formatting and counting utilities for AgentLoop rendering.
 *
 * Used by LoopSummaryBar, SimpleLoopCard, and other loop renderers
 * to avoid duplicating reduce/format logic.
 */

import type { AgentLoop, AgentLoopStep } from '../types/agentLoop';

/** Count all tool calls across every step. */
export function countTools(loop: AgentLoop): number {
  return loop.steps.reduce((sum, s) => sum + s.toolCalls.length, 0);
}

/** Sum tokens from steps AND their micro-reasoning sub-calls. */
export function sumAllTokens(loop: AgentLoop): number {
  return loop.steps.reduce((sum, s) => {
    let stepTotal = s.tokens.prompt + s.tokens.completion;
    for (const mr of s.microReasonings || []) {
      stepTotal += (mr.prompt_tokens || 0) + (mr.completion_tokens || 0);
    }
    return sum + stepTotal;
  }, 0);
}

/** Format token count, preferring budget.tokensUsed, with "1.2k" notation. */
export function formatTokens(loop: AgentLoop): string {
  const total = loop.budget.tokensUsed || sumAllTokens(loop);
  if (total >= 1000) return (total / 1000).toFixed(1) + 'k';
  return String(total);
}

/** Format seconds for display (e.g. "12.3s" or "2m 30s"). */
export function formatDuration(seconds: number): string {
  if (seconds < 0.1) return '<0.1s';
  if (seconds < 60) return seconds.toFixed(1) + 's';
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

/** Filter noise lines from final answer text. */
export function filterFinalAnswer(text: string): string {
  return text
    .split('\n')
    .filter((line) => !(line.includes('Step completed') && line.includes('all requested tool calls')))
    .join('\n')
    .trim();
}

/** Infer the graph node type from step content when not explicitly set. */
export type GraphNodeType = 'planner' | 'replanner' | 'executor' | 'reflector' | 'reporter';

export function inferNodeType(step: AgentLoopStep): GraphNodeType {
  if (step.nodeType === 'replanner') return 'replanner';
  if (step.nodeType === 'reporter' || step.eventType === 'reporter_output') return 'reporter';
  if (step.nodeType === 'reflector' || step.eventType === 'reflector_decision') return 'reflector';
  if (step.nodeType === 'planner') return 'planner';
  return 'executor';
}

/** Color mapping for graph node types. */
export const NODE_COLORS: Record<GraphNodeType, { bg: string; label: string }> = {
  planner:    { bg: '#0066cc', label: 'planner' },
  replanner:  { bg: '#0055aa', label: 'replanner' },
  executor:   { bg: '#2e7d32', label: 'executor' },
  reflector:  { bg: '#e65100', label: 'reflector' },
  reporter:   { bg: '#7b1fa2', label: 'reporter' },
};
