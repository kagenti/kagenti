// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { describe, it, expect } from 'vitest';
import { applyLoopEvent, buildAgentLoops, createDefaultAgentLoop, type LoopEvent } from './loopBuilder';

describe('buildAgentLoops', () => {
  it('sorts events by event_index before processing', () => {
    // Events arrive out of order (simulating DB query without ORDER BY)
    const events: LoopEvent[] = [
      { type: 'planner_output', loop_id: 'L1', event_index: 1, steps: ['Step 1', 'Step 2'] },
      { type: 'executor_step', loop_id: 'L1', event_index: 3, step: 1, description: 'Doing step 1' },
      { type: 'step_selector', loop_id: 'L1', event_index: 2, current_step: 0 },
      { type: 'reporter_output', loop_id: 'L1', event_index: 5, content: 'Done' },
      { type: 'reflector_decision', loop_id: 'L1', event_index: 4, decision: 'done', done: true },
    ];

    const loops = buildAgentLoops(events);
    const loop = loops.get('L1')!;

    // Loop should be marked as done (reporter present)
    expect(loop.status).toBe('done');
    // nodeVisits should reflect the highest event_index
    expect(loop.nodeVisits).toBe(5);
  });

  it('handles events with null event_index', () => {
    const events: LoopEvent[] = [
      { type: 'planner_output', loop_id: 'L2', steps: ['A'] },
      { type: 'executor_step', loop_id: 'L2', step: 1, description: 'Working' },
      { type: 'reporter_output', loop_id: 'L2', content: 'Final' },
    ];

    const loops = buildAgentLoops(events);
    const loop = loops.get('L2')!;
    expect(loop.status).toBe('done');
    expect(loop.plan).toContain('A');
  });
});

describe('applyLoopEvent', () => {
  it('tracks nodeVisits from event_index', () => {
    let loop = createDefaultAgentLoop('L1');
    loop = applyLoopEvent(loop, {
      type: 'executor_step',
      loop_id: 'L1',
      event_index: 5,
      step: 1,
      description: 'test',
    });
    expect(loop.nodeVisits).toBe(5);
  });

  it('prefers event_index over step for nodeVisits', () => {
    let loop = createDefaultAgentLoop('L1');
    loop = applyLoopEvent(loop, {
      type: 'executor_step',
      loop_id: 'L1',
      event_index: 10,
      step: 2,
      description: 'test',
    });
    // Should use event_index (10) not step (2)
    expect(loop.nodeVisits).toBe(10);
  });

  it('falls back to step when event_index is missing', () => {
    let loop = createDefaultAgentLoop('L1');
    loop = applyLoopEvent(loop, {
      type: 'executor_step',
      loop_id: 'L1',
      step: 3,
      description: 'test',
    });
    expect(loop.nodeVisits).toBe(3);
  });

  it('pairs tool_call and tool_result by call_id', () => {
    let loop = createDefaultAgentLoop('L1');
    // Apply tool call — when no tools array, fallback creates entry with call_id
    loop = applyLoopEvent(loop, {
      type: 'tool_call',
      loop_id: 'L1',
      call_id: 'tc_abc',
      name: 'shell',
      args: { command: 'ls' },
      event_index: 1,
      node_visit: 1,
    });
    // Apply tool result with matching call_id and same node_visit
    loop = applyLoopEvent(loop, {
      type: 'tool_result',
      loop_id: 'L1',
      call_id: 'tc_abc',
      name: 'shell',
      output: 'file1.txt',
      event_index: 2,
      node_visit: 1,
    });

    // Find the step with the tool call
    const step = loop.steps.find(s => s.toolCalls.length > 0);
    expect(step).toBeDefined();
    expect(step!.toolCalls[0].call_id).toBe('tc_abc');
    expect(step!.toolResults[0].call_id).toBe('tc_abc');
  });
});
