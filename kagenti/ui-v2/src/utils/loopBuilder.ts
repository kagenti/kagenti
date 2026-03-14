// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Shared loop-event processing logic for AgentLoop state.
 *
 * Both SSE streaming and history reconstruction use `applyLoopEvent`
 * so that rendering parity is guaranteed. Previously each code path
 * had its own ~150-line event-handling chain, which drifted over time.
 */

import type { AgentLoop, AgentLoopStep, MicroReasoning, ThinkingIteration } from '../types/agentLoop';

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** Shape of a loop event coming from the backend (SSE or persisted). */
export interface LoopEvent {
  type: string;
  loop_id: string;
  step?: number;
  event_index?: number;
  /** Graph node visit number — used for UI section grouping */
  node_visit?: number;
  /** Position within a node visit */
  sub_index?: number;
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
  /** Bound tool schemas sent to the LLM */
  bound_tools?: Array<{ name: string; description?: string }>;
  /** call_id that this micro-reasoning follows */
  after_call_id?: string;
  /** Step selector brief for the executor */
  brief?: string;
  /** Thinking iteration: total iterations in this thinking loop */
  total_iterations?: number;
  /** Thinking iteration: node name */
  node?: string;
  /** LLM response data for prompt inspector */
  llm_response?: unknown;
  /** Number of thinking iterations that preceded this micro-reasoning */
  thinking_count?: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Legacy types fully removed — agent no longer emits plan/plan_step/reflection.

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
  // Track highest node visit index (global recursion counter).
  // Prefer event_index (chronological counter) over step (plan step).
  const visitIdx = le.event_index ?? le.step;
  if (visitIdx != null && visitIdx > loop.nodeVisits) {
    loop = { ...loop, nodeVisits: visitIdx };
  }
  const eventType = le.type;

  // Only process known event types — ignore legacy/unknown types from old sessions
  const KNOWN_TYPES = new Set([
    'router', 'planner_output', 'replanner_output', 'executor_step',
    'tool_call', 'tool_result', 'micro_reasoning', 'thinking',
    'reflector_decision', 'reporter_output', 'step_selector',
    'budget', 'budget_update',
  ]);
  if (!KNOWN_TYPES.has(eventType)) {
    return loop;
  }

  // Router is an internal node — just update status, no visual step
  if (eventType === 'router') {
    return {
      ...loop,
      status: 'planning',
    };
  }

  if (eventType === 'planner_output' || eventType === 'replanner_output') {
    console.log(`[loopBuilder] ${eventType}: system_prompt=`, le.system_prompt?.substring(0, 50), 'prompt_messages=', le.prompt_messages?.length);
    const incomingSteps = le.steps || [];
    const isReplan = eventType === 'replanner_output' || loop.plan.length > 0;
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
      // Replan keeps the current step index — does NOT reset to 0
      currentStep: isReplan ? loop.currentStep : loop.currentStep,
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

  // -----------------------------------------------------------------------
  // Group ALL events by node_visit. Each node_visit = one UI section.
  // Tool events (tool_call, tool_result) share the executor's node_visit.
  // -----------------------------------------------------------------------

  /** Find or create a step for this node_visit. */
  const findOrCreateStep = (
    steps: AgentLoopStep[],
    nodeVisit: number,
    defaults: Partial<AgentLoopStep>,
  ): { steps: AgentLoopStep[]; step: AgentLoopStep } => {
    const existing = steps.find((s) => s.index === nodeVisit);
    if (existing) return { steps, step: existing };
    const newStep: AgentLoopStep = {
      index: nodeVisit,
      planStep: defaults.planStep,
      description: defaults.description || '',
      model: defaults.model || loop.model,
      nodeType: defaults.nodeType || 'executor',
      tokens: defaults.tokens || { prompt: 0, completion: 0 },
      toolCalls: [],
      toolResults: [],
      microReasonings: [],
      durationMs: 0,
      createdAt: now(),
      updatedAt: now(),
      status: 'running' as const,
      ...defaults,
    };
    return { steps: [...steps, newStep], step: newStep };
  };

  const nv = le.node_visit ?? le.step ?? loop.steps.length;

  if (eventType === 'executor_step') {
    const { steps, step } = findOrCreateStep(loop.steps, nv, {
      planStep: le.current_step,
      description: le.description || '',
      nodeType: 'executor',
      reasoning: le.reasoning as string | undefined,
      systemPrompt: le.system_prompt,
      promptMessages: le.prompt_messages,
      boundTools: le.bound_tools,
      tokens: { prompt: le.prompt_tokens || 0, completion: le.completion_tokens || 0 },
    });
    // Update fields on existing step
    step.planStep = le.current_step ?? step.planStep;
    step.description = le.description || step.description;
    step.model = le.model || step.model || loop.model;
    step.boundTools = le.bound_tools || step.boundTools;
    step.reasoning = (le.reasoning as string) || step.reasoning;
    step.systemPrompt = le.system_prompt || step.systemPrompt;
    step.promptMessages = le.prompt_messages || step.promptMessages;
    step.tokens = { prompt: le.prompt_tokens || step.tokens?.prompt || 0, completion: le.completion_tokens || step.tokens?.completion || 0 };
    step.nodeType = 'executor';
    step.updatedAt = now();
    return {
      ...loop,
      status: 'executing',
      currentStep: le.current_step ?? loop.currentStep,
      totalSteps: le.total_steps ?? loop.totalSteps,
      model: le.model || loop.model,
      steps,
    };
  }

  if (eventType === 'tool_call') {
    const { steps, step } = findOrCreateStep(loop.steps, nv, {
      planStep: le.current_step ?? loop.currentStep,
      description: loop.plan[le.current_step ?? loop.currentStep] || 'Tool execution',
      nodeType: 'executor',
    });
    step.toolCalls = [...step.toolCalls, ...(le.tools as AgentLoopStep['toolCalls'] || [{ type: 'tool_call', name: le.name || 'unknown', args: le.args || '', call_id: le.call_id }])];
    step.nodeType = 'executor';
    step.updatedAt = now();
    return { ...loop, steps, model: le.model || loop.model };
  }

  if (eventType === 'tool_result') {
    // Tool results share the executor's node_visit — find by node_visit first
    const { steps, step } = findOrCreateStep(loop.steps, nv, {
      planStep: le.current_step ?? loop.currentStep,
      nodeType: 'executor',
    });
    const resultName = le.name || 'unknown';
    step.toolResults = [...step.toolResults, { type: 'tool_result', name: resultName, output: le.output || '', call_id: le.call_id, status: le.status }];
    if (step.toolResults.length >= step.toolCalls.length && step.toolCalls.length > 0) {
      step.status = 'done';
    }
    step.updatedAt = now();
    return { ...loop, steps };
  }

  if (eventType === 'reflector_decision') {
    const finalizedSteps = loop.steps.map((s) =>
      s.status === 'running' ? { ...s, status: 'done' as const } : s,
    );
    const { steps } = findOrCreateStep(finalizedSteps, nv, {
      description: `Reflection [${le.decision || 'assess'}]: ${(le.assessment || '').substring(0, 80)}`,
      reasoning: le.assessment || '',
      model: le.model || loop.model,
      nodeType: 'reflector',
      eventType: 'reflector_decision',
      tokens: { prompt: le.prompt_tokens || 0, completion: le.completion_tokens || 0 },
      systemPrompt: le.system_prompt,
      promptMessages: le.prompt_messages,
      status: 'done' as const,
    });
    return {
      ...loop,
      status: 'reflecting',
      reflection: le.assessment || '',
      reflectorDecision: le.decision as 'continue' | 'replan' | 'done' | undefined,
      iteration: le.iteration ?? loop.iteration,
      model: le.model || loop.model,
      steps,
    };
  }

  if (eventType === 'step_selector') {
    const finalizedSteps = loop.steps.map((s) =>
      s.status === 'running' ? { ...s, status: 'done' as const } : s,
    );
    const { steps } = findOrCreateStep(finalizedSteps, nv, {
      planStep: le.current_step,
      description: le.description || `Advancing to step ${(le.current_step ?? 0) + 1}`,
      reasoning: le.brief || le.description || '',
      nodeType: 'planner',
      status: 'done' as const,
    });
    return {
      ...loop,
      status: 'planning',
      currentStep: le.current_step ?? loop.currentStep,
      steps,
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

  if (eventType === 'thinking') {
    const { steps, step } = findOrCreateStep(loop.steps, nv, {
      planStep: le.current_step ?? loop.currentStep,
      description: 'Tool execution',
      nodeType: 'executor',
    });
    const ti: ThinkingIteration = {
      type: 'thinking',
      loop_id: le.loop_id,
      iteration: le.iteration ?? 1,
      total_iterations: le.total_iterations ?? 1,
      reasoning: le.reasoning || '',
      node: le.node,
      model: le.model,
      prompt_tokens: le.prompt_tokens,
      completion_tokens: le.completion_tokens,
      system_prompt: le.system_prompt,
      prompt_messages: le.prompt_messages,
      bound_tools: le.bound_tools,
      llm_response: le.llm_response,
    };
    step.thinkings = [...(step.thinkings || []), ti];
    return { ...loop, steps };
  }

  if (eventType === 'micro_reasoning') {
    const { steps, step } = findOrCreateStep(loop.steps, nv, {
      planStep: le.current_step ?? loop.currentStep,
      description: 'Tool execution',
      nodeType: 'executor',
    });
    const mr: MicroReasoning = {
      type: 'micro_reasoning',
      loop_id: le.loop_id,
      step: le.step ?? nv,
      micro_step: le.micro_step ?? 0,
      reasoning: le.reasoning || '',
      next_action: le.next_action || '',
      model: le.model,
      prompt_tokens: le.prompt_tokens,
      completion_tokens: le.completion_tokens,
      system_prompt: le.system_prompt,
      prompt_messages: le.prompt_messages,
      bound_tools: le.bound_tools,
      after_call_id: le.after_call_id,
      thinking_count: le.thinking_count,
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
  // Sort events by event_index for correct chronological ordering.
  // Events from DB may arrive out of order (gaps from SSE disconnect).
  const sorted = [...events].sort((a, b) => (a.event_index ?? 0) - (b.event_index ?? 0));
  const loops = new Map<string, AgentLoop>();
  for (const evt of sorted) {
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
