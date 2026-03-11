// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Shared loop-event processing logic for AgentLoop state.
 *
 * Both SSE streaming and history reconstruction use `applyLoopEvent`
 * so that rendering parity is guaranteed. Previously each code path
 * had its own ~150-line event-handling chain, which drifted over time.
 */

import type { AgentLoop, AgentLoopStep, MicroReasoning } from '../types/agentLoop';

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
  /** Alias for current_step — agent may use either field name */
  plan_step?: number;
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
  /** System prompt sent to the LLM */
  system_prompt?: string;
  /** Summarized message list sent to the LLM */
  prompt_messages?: Array<{ role: string; preview: string }>;
  /** Micro-reasoning sub-step index */
  micro_step?: number;
  /** Next action planned after micro-reasoning */
  next_action?: string;
  /** Unique call identifier for pairing tool calls with results */
  call_id?: string;
  /** Explicit status for tool results */
  status?: 'success' | 'error' | 'timeout' | 'pending';
  /** call_id that this micro-reasoning follows */
  after_call_id?: string;
  /** Step selector brief for the executor */
  brief?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Legacy event types emitted alongside the new types for backward compat.
 * Skip these to avoid duplicate steps.
 */
export const LEGACY_TYPES = new Set(['plan', 'plan_step', 'reflection', 'llm_response']);

/** Current ISO timestamp for step creation/update tracking. */
function now(): string { return new Date().toISOString(); }

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
    nodeVisits: 0,
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
  // Normalize: agent may emit plan_step or current_step
  if (le.plan_step != null && le.current_step == null) {
    le.current_step = le.plan_step;
  }
  // Track highest node visit index (global recursion counter)
  if (le.step != null && le.step > loop.nodeVisits) {
    loop = { ...loop, nodeVisits: le.step };
  }
  const eventType = le.type;

  // Skip legacy event types
  if (LEGACY_TYPES.has(eventType)) {
    return loop;
  }

  // Router is an internal node — just update status, no visual step
  if (eventType === 'router') {
    return {
      ...loop,
      status: 'planning',
    };
  }

  if (eventType === 'planner_output') {
    console.log('[loopBuilder] planner_output: system_prompt=', le.system_prompt?.substring(0, 50), 'prompt_messages=', le.prompt_messages?.length);
    const incomingSteps = le.steps || [];
    const isReplan = loop.plan.length > 0;
    const iterNum = le.iteration ?? loop.iteration ?? 0;
    const stepLabel = isReplan ? 'Replan' : 'Plan';
    const nodeTypeVal = isReplan ? 'replanner' as const : 'planner' as const;
    const planContent = le.content || incomingSteps.map((s: string, i: number) => `${i + 1}. ${s}`).join('\n') || undefined;
    // Finalize all running steps — a planner/replanner event means the
    // previous node is done and any pending tool calls should resolve.
    const finalizedSteps = loop.steps.map((s) =>
      s.status === 'running' ? { ...s, status: 'done' as const } : s,
    );
    return {
      ...loop,
      status: 'planning',
      plan: incomingSteps.length > 0 ? incomingSteps : loop.plan,
      replans: isReplan
        ? [...loop.replans, { iteration: iterNum, steps: incomingSteps, model: le.model || loop.model, content: le.content }]
        : loop.replans,
      totalSteps: incomingSteps.length > 0 ? incomingSteps.length : loop.totalSteps,
      currentStep: isReplan ? 0 : loop.currentStep,
      iteration: iterNum,
      model: le.model || loop.model,
      steps: [
        ...finalizedSteps,
        {
          index: loop.steps.length,
          description: `${stepLabel} (iteration ${iterNum + 1}): ${incomingSteps.length} steps`,
          reasoning: planContent,
          systemPrompt: le.system_prompt,
          promptMessages: le.prompt_messages,
          model: le.model || loop.model,
          nodeType: nodeTypeVal,
          tokens: { prompt: le.prompt_tokens || 0, completion: le.completion_tokens || 0 },
          toolCalls: [],
          toolResults: [],
          durationMs: 0,
          createdAt: now(),
          updatedAt: now(),
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
        currentStep: le.current_step ?? loop.currentStep,
        totalSteps: le.total_steps ?? loop.totalSteps,
        model: le.model || loop.model,
      };
    }
    // Update existing step IN PLACE to preserve chronological ordering
    // relative to planner/reflector steps. Don't filter+push (reorders).
    if (existingStep) {
      const updatedStep = {
        ...existingStep,
        planStep: le.current_step ?? existingStep.planStep,
        description: le.description || existingStep.description || '',
        model: le.model || existingStep.model || loop.model,
        reasoning: (le.reasoning as string) || existingStep.reasoning || undefined,
        systemPrompt: le.system_prompt || existingStep.systemPrompt,
        promptMessages: le.prompt_messages || existingStep.promptMessages,
        tokens: { prompt: le.prompt_tokens || existingStep.tokens?.prompt || 0, completion: le.completion_tokens || existingStep.tokens?.completion || 0 },
      };
      return {
        ...loop,
        status: 'executing',
        currentStep: le.current_step ?? loop.currentStep,
        totalSteps: le.total_steps ?? loop.totalSteps,
        model: le.model || loop.model,
        steps: loop.steps.map((s) => s.index === le.step ? updatedStep : s),
      };
    }
    // No existing step — create new one at the end
    return {
      ...loop,
      status: 'executing',
      currentStep: le.current_step ?? loop.currentStep,
      totalSteps: le.total_steps ?? loop.totalSteps,
      model: le.model || loop.model,
      steps: [
        ...loop.steps,
        {
          index: le.step as number,
          planStep: le.current_step,
          description: le.description || '',
          model: le.model || loop.model,
          reasoning: (le.reasoning as string) || undefined,
          systemPrompt: le.system_prompt,
          promptMessages: le.prompt_messages,
          nodeType: 'executor' as const,
          tokens: { prompt: le.prompt_tokens || 0, completion: le.completion_tokens || 0 },
          toolCalls: [],
          toolResults: [],
          microReasonings: [],
          durationMs: 0,
          createdAt: now(),
          updatedAt: now(),
          status: 'running' as const,
        },
      ],
    };
  }

  if (eventType === 'tool_call') {
    const stepIdx = le.step ?? loop.currentStep;
    const steps = [...loop.steps];
    const step = steps.find((s) => s.index === stepIdx);
    if (step) {
      step.toolCalls = [...step.toolCalls, ...(le.tools as AgentLoopStep['toolCalls'] || [{ type: 'tool_call', name: le.name || 'unknown', args: le.args || '', call_id: le.call_id }])];
      step.nodeType = 'executor';
      step.updatedAt = now();
    } else {
      // No matching step — create an implicit executor step
      // Use plan step description if available
      const planStepIdx = le.current_step ?? loop.currentStep;
      const planDesc = loop.plan[planStepIdx] || '';
      steps.push({
        index: stepIdx,
        planStep: planStepIdx,
        description: planDesc || `Tool execution`,
        model: le.model || loop.model,
        nodeType: 'executor' as const,
        tokens: { prompt: 0, completion: 0 },
        toolCalls: (le.tools as AgentLoopStep['toolCalls']) || [{ type: 'tool_call', name: le.name || 'unknown', args: le.args || '', call_id: le.call_id }],
        toolResults: [],
        durationMs: 0,
        createdAt: now(),
        updatedAt: now(),
        status: 'running' as const,
      });
    }
    return { ...loop, steps, model: le.model || loop.model };
  }

  if (eventType === 'tool_result') {
    const stepIdx = le.step ?? loop.currentStep;
    const steps = [...loop.steps];
    const resultName = le.name || 'unknown';

    // Helper: does a step have unmatched tool calls for this result name?
    const hasPendingCall = (s: AgentLoopStep) => {
      const callCount = s.toolCalls.filter((tc) => tc.name === resultName).length;
      const resultCount = s.toolResults.filter((tr) => tr.name === resultName).length;
      return callCount > resultCount;
    };

    // Try to find the step by index first
    let step = steps.find((s) => s.index === stepIdx);

    // If the target step has no pending tool call for this result, search
    // other steps — the result may have arrived after a node transition
    // moved currentStep forward, so it belongs to an earlier step.
    if (!step || !hasPendingCall(step)) {
      const betterStep = steps.find((s) => s.index !== stepIdx && hasPendingCall(s));
      if (betterStep) step = betterStep;
    }

    if (step) {
      step.toolResults = [...step.toolResults, { type: 'tool_result', name: resultName, output: le.output || '', call_id: le.call_id, status: le.status }];
      // Mark step as done only when all tool calls have results
      if (step.toolResults.length >= step.toolCalls.length) {
        step.status = 'done';
      }
      step.nodeType = 'executor';
      step.updatedAt = now();
    } else {
      // No matching step — create an implicit executor step
      const planStepIdx = le.current_step ?? loop.currentStep;
      const planDesc = loop.plan[planStepIdx] || '';
      steps.push({
        index: stepIdx,
        planStep: planStepIdx,
        description: planDesc || 'Tool execution',
        model: le.model || loop.model,
        nodeType: 'executor' as const,
        tokens: { prompt: 0, completion: 0 },
        toolCalls: [],
        toolResults: [{ type: 'tool_result', name: resultName, output: le.output || '', call_id: le.call_id, status: le.status }],
        durationMs: 0,
        createdAt: now(),
        updatedAt: now(),
        status: 'done' as const,
      });
    }
    return { ...loop, steps };
  }

  if (eventType === 'reflector_decision') {
    // Finalize all running executor steps — the node transition means
    // any pending tool calls from the previous node are complete.
    const finalizedSteps = loop.steps.map((s) =>
      s.status === 'running' ? { ...s, status: 'done' as const } : s,
    );
    return {
      ...loop,
      status: 'reflecting',
      reflection: le.assessment || '',
      reflectorDecision: le.decision as 'continue' | 'replan' | 'done' | undefined,
      iteration: le.iteration ?? loop.iteration,
      model: le.model || loop.model,
      steps: [
        ...finalizedSteps,
        {
          index: loop.steps.length,
          description: `Reflection [${le.decision || 'assess'}]: ${(le.assessment || '').substring(0, 80)}`,
          reasoning: le.assessment || '',
          model: le.model || loop.model,
          nodeType: 'reflector' as const,
          eventType: 'reflector_decision',
          tokens: { prompt: le.prompt_tokens || 0, completion: le.completion_tokens || 0 },
          systemPrompt: le.system_prompt,
          promptMessages: le.prompt_messages,
          toolCalls: [],
          toolResults: [],
          durationMs: 0,
          createdAt: now(),
          updatedAt: now(),
          status: 'done' as const,
        },
      ],
    };
  }

  if (eventType === 'step_selector') {
    return {
      ...loop,
      status: 'planning',
      currentStep: le.current_step ?? loop.currentStep,
      steps: [
        ...loop.steps.map((s) => s.status === 'running' ? { ...s, status: 'done' as const } : s),
        {
          index: le.step as number,
          planStep: le.current_step,
          description: le.description || `Advancing to step ${(le.current_step ?? 0) + 1}`,
          reasoning: le.brief || le.description || '',
          model: '',
          nodeType: 'planner' as const,
          tokens: { prompt: 0, completion: 0 },
          toolCalls: [],
          toolResults: [],
          durationMs: 0,
          createdAt: now(),
          updatedAt: now(),
          status: 'done' as const,
        },
      ],
    };
  }

  if (eventType === 'budget' || eventType === 'budget_update') {
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
          reasoning: isLeaked ? '' : rContent,
          model: le.model || loop.model,
          nodeType: 'reporter' as const,
          eventType: 'reporter_output',
          tokens: { prompt: le.prompt_tokens || 0, completion: le.completion_tokens || 0 },
          systemPrompt: le.system_prompt,
          promptMessages: le.prompt_messages,
          toolCalls: [],
          toolResults: [],
          durationMs: 0,
          createdAt: now(),
          updatedAt: now(),
          status: 'done' as const,
        },
      ],
    };
  }

  if (eventType === 'micro_reasoning') {
    const stepIdx = le.step ?? loop.currentStep;
    const steps = [...loop.steps];
    let step = steps.find((s) => s.index === stepIdx);
    if (!step) {
      // Create an implicit executor step if none exists
      step = {
        index: stepIdx,
        description: 'Tool execution',
        model: le.model || loop.model,
        nodeType: 'executor' as const,
        tokens: { prompt: 0, completion: 0 },
        toolCalls: [],
        toolResults: [],
        durationMs: 0,
        createdAt: now(),
        updatedAt: now(),
        status: 'running' as const,
      };
      steps.push(step);
    }
    const mr: MicroReasoning = {
      type: 'micro_reasoning',
      loop_id: le.loop_id,
      step: le.step ?? stepIdx,
      micro_step: le.micro_step ?? 0,
      reasoning: le.reasoning || '',
      next_action: le.next_action || '',
      model: le.model,
      prompt_tokens: le.prompt_tokens,
      completion_tokens: le.completion_tokens,
      system_prompt: le.system_prompt,
      prompt_messages: le.prompt_messages,
      after_call_id: le.after_call_id,
    };
    step.microReasonings = [...(step.microReasonings || []), mr];
    return { ...loop, steps };
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
      // Loop didn't complete — may still be running or was interrupted.
      // Don't set finalAnswer — that would prevent subscribe reconnection.
      // Use failureReason instead for the UI to show.
      if (loop.status !== 'done') {
        loop.status = 'executing';
        loop.failureReason = loop.failureReason || 'Agent loop in progress or was interrupted.';
      }
    }
    // Finalize any steps still marked as running/pending — in a completed or
    // failed loop there should be no spinning indicators.
    for (const step of loop.steps) {
      if (step.status === 'running' || step.status === 'pending') {
        step.status = loop.status === 'done' ? 'done' : 'failed';
      }
    }
    loop.steps.sort((a: AgentLoopStep, b: AgentLoopStep) => a.index - b.index);
  }
  return loops;
}
