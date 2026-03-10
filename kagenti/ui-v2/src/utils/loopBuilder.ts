// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Shared loop-event processing logic for AgentLoop state.
 *
 * Both SSE streaming and history reconstruction use `applyLoopEvent`
 * so that rendering parity is guaranteed. Previously each code path
 * had its own ~150-line event-handling chain, which drifted over time.
 */

import type { AgentLoop, AgentLoopStep } from '../types/agentLoop';

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** Shape of a loop event coming from the backend (SSE or persisted). */
export interface LoopEvent {
  type: string;
  loop_id: string;
  step?: number;
  total_steps?: number;
  steps?: string[];
  description?: string;
  reasoning?: string;
  content?: string;
  assessment?: string;
  decision?: string;
  model?: string;
  iteration?: number;
  done?: boolean;
  current_step?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  tools?: Array<{ type?: string; name?: string; args?: unknown; tools?: unknown[] }>;
  name?: string;
  output?: string;
  args?: unknown;
  tokens_used?: number;
  tokens_budget?: number;
  wall_clock_s?: number;
  max_wall_clock_s?: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Legacy event types emitted alongside the new types for backward compat.
 * Skip these to avoid duplicate steps.
 */
export const LEGACY_TYPES = new Set(['plan', 'plan_step', 'reflection', 'llm_response']);

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/** Create a fresh AgentLoop with sensible defaults. */
export function createDefaultAgentLoop(loopId: string): AgentLoop {
  return {
    id: loopId,
    status: 'planning',
    model: '',
    plan: [],
    replans: [],
    currentStep: 0,
    totalSteps: 0,
    iteration: 0,
    steps: [],
    budget: { tokensUsed: 0, tokensBudget: 0, wallClockS: 0, maxWallClockS: 0 },
  };
}

// ---------------------------------------------------------------------------
// Core reducer
// ---------------------------------------------------------------------------

/**
 * Pure function that applies a single loop event to an AgentLoop,
 * returning the updated loop (new object — safe for React state).
 *
 * This is the **canonical** implementation used by both SSE streaming
 * and history reconstruction.
 */
export function applyLoopEvent(loop: AgentLoop, le: LoopEvent): AgentLoop {
  const eventType = le.type;

  // Skip legacy event types
  if (LEGACY_TYPES.has(eventType)) {
    return loop;
  }

  if (eventType === 'planner_output') {
    const incomingSteps = le.steps || [];
    const isReplan = loop.plan.length > 0;
    const iterNum = le.iteration ?? loop.iteration ?? 0;
    const stepLabel = isReplan ? 'Replan' : 'Plan';
    const nodeTypeVal = isReplan ? 'replanner' as const : 'planner' as const;
    const planContent = le.content || incomingSteps.map((s: string, i: number) => `${i + 1}. ${s}`).join('\n') || undefined;
    return {
      ...loop,
      status: 'planning',
      plan: isReplan ? loop.plan : incomingSteps,
      replans: isReplan
        ? [...loop.replans, { iteration: iterNum, steps: incomingSteps, model: le.model || loop.model, content: le.content }]
        : loop.replans,
      totalSteps: isReplan ? loop.totalSteps : incomingSteps.length,
      iteration: iterNum,
      model: le.model || loop.model,
      steps: [
        ...loop.steps,
        {
          index: loop.steps.length,
          description: `${stepLabel} (iteration ${iterNum + 1}): ${incomingSteps.length} steps`,
          reasoning: planContent,
          model: le.model || loop.model,
          nodeType: nodeTypeVal,
          tokens: { prompt: le.prompt_tokens || 0, completion: le.completion_tokens || 0 },
          toolCalls: [],
          toolResults: [],
          durationMs: 0,
          status: 'done' as const,
        },
      ],
    };
  }

  if (eventType === 'executor_step') {
    const newDesc = ((le.description as string) || '').trim();
    const existingStep = loop.steps.find((s) => s.index === le.step);
    // If incoming event has empty description and existing step has content, keep existing
    if (!newDesc && existingStep && existingStep.description?.trim()) {
      return {
        ...loop,
        status: 'executing',
        currentStep: le.step ?? loop.currentStep,
        totalSteps: le.total_steps ?? loop.totalSteps,
        model: le.model || loop.model,
      };
    }
    return {
      ...loop,
      status: 'executing',
      currentStep: le.step ?? loop.currentStep,
      totalSteps: le.total_steps ?? loop.totalSteps,
      model: le.model || loop.model,
      steps: [
        ...loop.steps.filter((s) => s.index !== le.step),
        {
          index: le.step as number,
          description: le.description || existingStep?.description || '',
          model: le.model || loop.model,
          reasoning: (le.reasoning as string) || existingStep?.reasoning || undefined,
          nodeType: 'executor' as const,
          tokens: { prompt: le.prompt_tokens || existingStep?.tokens?.prompt || 0, completion: le.completion_tokens || existingStep?.tokens?.completion || 0 },
          // Merge tool data from existing step (tool_call/tool_result events may have arrived first)
          toolCalls: existingStep?.toolCalls || [],
          toolResults: existingStep?.toolResults || [],
          durationMs: 0,
          status: existingStep?.status || ('running' as const),
        },
      ],
    };
  }

  if (eventType === 'tool_call') {
    const stepIdx = le.step ?? loop.currentStep;
    const steps = [...loop.steps];
    const step = steps.find((s) => s.index === stepIdx);
    if (step) {
      step.toolCalls = [...step.toolCalls, ...(le.tools as AgentLoopStep['toolCalls'] || [{ type: 'tool_call', name: le.name || 'unknown', args: le.args || '' }])];
      step.nodeType = 'executor';
    } else {
      // No matching step — create an implicit executor step
      steps.push({
        index: stepIdx,
        description: 'Tool execution',
        model: le.model || loop.model,
        nodeType: 'executor' as const,
        tokens: { prompt: 0, completion: 0 },
        toolCalls: (le.tools as AgentLoopStep['toolCalls']) || [{ type: 'tool_call', name: le.name || 'unknown', args: le.args || '' }],
        toolResults: [],
        durationMs: 0,
        status: 'running' as const,
      });
    }
    return { ...loop, steps, model: le.model || loop.model };
  }

  if (eventType === 'tool_result') {
    const stepIdx = le.step ?? loop.currentStep;
    const steps = [...loop.steps];
    const step = steps.find((s) => s.index === stepIdx);
    if (step) {
      step.toolResults = [...step.toolResults, { type: 'tool_result', name: le.name || 'unknown', output: le.output || '' }];
      step.status = 'done';
      step.nodeType = 'executor';
    } else {
      // No matching step — create an implicit executor step
      steps.push({
        index: stepIdx,
        description: 'Tool execution',
        model: le.model || loop.model,
        nodeType: 'executor' as const,
        tokens: { prompt: 0, completion: 0 },
        toolCalls: [],
        toolResults: [{ type: 'tool_result', name: le.name || 'unknown', output: le.output || '' }],
        durationMs: 0,
        status: 'done' as const,
      });
    }
    return { ...loop, steps };
  }

  if (eventType === 'reflector_decision') {
    return {
      ...loop,
      status: 'reflecting',
      reflection: le.assessment || '',
      reflectorDecision: le.decision as 'continue' | 'replan' | 'done' | undefined,
      iteration: le.iteration ?? loop.iteration,
      model: le.model || loop.model,
      steps: [
        ...loop.steps,
        {
          index: loop.steps.length,
          description: `Reflection [${le.decision || 'assess'}]: ${(le.assessment || '').substring(0, 80)}`,
          model: le.model || loop.model,
          nodeType: 'reflector' as const,
          tokens: { prompt: le.prompt_tokens || 0, completion: le.completion_tokens || 0 },
          toolCalls: [],
          toolResults: [],
          durationMs: 0,
          status: 'done' as const,
        },
      ],
    };
  }

  if (eventType === 'budget') {
    return {
      ...loop,
      budget: {
        tokensUsed: le.tokens_used ?? loop.budget.tokensUsed,
        tokensBudget: le.tokens_budget ?? loop.budget.tokensBudget,
        wallClockS: le.wall_clock_s ?? loop.budget.wallClockS,
        maxWallClockS: le.max_wall_clock_s ?? loop.budget.maxWallClockS,
      },
    };
  }

  if (eventType === 'reporter_output') {
    // Filter leaked reflector decisions ("continue"/"replan"/"done")
    const rContent = le.content || '';
    const isLeaked = /^(continue|replan|done|hitl)\s*$/i.test(String(rContent).trim());
    return {
      ...loop,
      status: 'done',
      finalAnswer: isLeaked ? '' : rContent,
      model: le.model || loop.model,
      // Mark all running steps as done + add reporter step
      steps: [
        ...loop.steps.map((s) => s.status === 'running' ? { ...s, status: 'done' as const } : s),
        {
          index: loop.steps.length,
          description: isLeaked ? 'Final answer (no content)' : 'Final answer',
          model: le.model || loop.model,
          nodeType: 'reporter' as const,
          tokens: { prompt: le.prompt_tokens || 0, completion: le.completion_tokens || 0 },
          toolCalls: [],
          toolResults: [],
          durationMs: 0,
          status: 'done' as const,
        },
      ],
    };
  }

  // Unknown event type — return loop unchanged
  console.warn(`[loopBuilder] Unknown loop event type: "${eventType}"`);
  return loop;
}

// ---------------------------------------------------------------------------
// Batch builder (history reconstruction)
// ---------------------------------------------------------------------------

/**
 * Replay a sequence of persisted loop events to reconstruct all AgentLoops.
 * Used by `loadInitialHistory` to rebuild loop cards from stored events.
 */
export function buildAgentLoops(events: LoopEvent[]): Map<string, AgentLoop> {
  const loops = new Map<string, AgentLoop>();
  for (const evt of events) {
    const loopId = evt.loop_id;
    if (!loopId) continue;
    const prev = loops.get(loopId) || createDefaultAgentLoop(loopId);
    loops.set(loopId, applyLoopEvent(prev, evt));
  }
  // Mark loops as done or failed based on whether they completed
  for (const [, loop] of loops) {
    const hasReporter = loop.steps.some((s) => s.nodeType === 'reporter');
    if (hasReporter) {
      loop.status = 'done';
    } else {
      // Loop didn't complete — stream was likely interrupted
      loop.status = 'failed';
      if (!loop.finalAnswer) {
        loop.finalAnswer = 'Agent loop was interrupted before completion.';
      }
    }
    loop.steps.sort((a: AgentLoopStep, b: AgentLoopStep) => a.index - b.index);
  }
  return loops;
}
