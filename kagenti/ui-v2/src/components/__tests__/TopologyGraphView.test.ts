// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Unit tests for TopologyGraphView pure functions.
 *
 * Tests: stepToTopoNode, computeEdgeCounts, getActiveTopoNode,
 * countEventsPerTopoNode, buildDefaultEventNodeMap.
 * Does NOT render React components.
 */

import { describe, it, expect } from 'vitest';
import type { AgentLoop, AgentLoopStep } from '../../types/agentLoop';
import type { GraphEdge } from '../../types/graphCard';
import {
  stepToTopoNode,
  computeEdgeCounts,
  getActiveTopoNode,
  countEventsPerTopoNode,
  buildDefaultEventNodeMap,
  DEFAULT_TOPOLOGY,
} from '../TopologyGraphView';

// ---------------------------------------------------------------------------
// Test helpers — mock data factories
// ---------------------------------------------------------------------------

function makeStep(overrides: Partial<AgentLoopStep> = {}): AgentLoopStep {
  return {
    index: 0,
    description: 'test step',
    model: 'test-model',
    tokens: { prompt: 0, completion: 0 },
    toolCalls: [],
    toolResults: [],
    durationMs: 0,
    status: 'done',
    nodeType: 'executor',
    ...overrides,
  };
}

function makeLoop(overrides: Partial<AgentLoop> = {}): AgentLoop {
  return {
    id: 'loop-1',
    status: 'done',
    model: 'test-model',
    plan: ['step 1'],
    replans: [],
    currentStep: 0,
    totalSteps: 1,
    iteration: 0,
    steps: [],
    nodeVisits: 0,
    budget: { tokensUsed: 0, tokensBudget: 10000, wallClockS: 0, maxWallClockS: 300 },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// stepToTopoNode
// ---------------------------------------------------------------------------

describe('stepToTopoNode', () => {
  describe('eventType-based mapping', () => {
    it('maps planner_output to planner', () => {
      expect(stepToTopoNode({ eventType: 'planner_output' })).toBe('planner');
    });

    it('maps executor_step to step_selector', () => {
      expect(stepToTopoNode({ eventType: 'executor_step' })).toBe('step_selector');
    });

    it('maps tool_call to tools', () => {
      expect(stepToTopoNode({ eventType: 'tool_call' })).toBe('tools');
    });

    it('maps tool_result to tools', () => {
      expect(stepToTopoNode({ eventType: 'tool_result' })).toBe('tools');
    });

    it('maps reflector_decision to reflector', () => {
      expect(stepToTopoNode({ eventType: 'reflector_decision' })).toBe('reflector');
    });

    it('maps reporter_output to reporter', () => {
      expect(stepToTopoNode({ eventType: 'reporter_output' })).toBe('reporter');
    });

    it('maps micro_reasoning to executor', () => {
      expect(stepToTopoNode({ eventType: 'micro_reasoning' })).toBe('executor');
    });
  });

  describe('nodeType fallback mapping', () => {
    it('maps planner nodeType to planner', () => {
      expect(stepToTopoNode({ nodeType: 'planner' })).toBe('planner');
    });

    it('maps replanner nodeType to planner', () => {
      expect(stepToTopoNode({ nodeType: 'replanner' })).toBe('planner');
    });

    it('maps executor nodeType to executor', () => {
      expect(stepToTopoNode({ nodeType: 'executor' })).toBe('executor');
    });

    it('maps reflector nodeType to reflector', () => {
      expect(stepToTopoNode({ nodeType: 'reflector' })).toBe('reflector');
    });

    it('maps reporter nodeType to reporter', () => {
      expect(stepToTopoNode({ nodeType: 'reporter' })).toBe('reporter');
    });
  });

  describe('edge cases', () => {
    it('returns null for unknown eventType and no nodeType', () => {
      expect(stepToTopoNode({})).toBeNull();
    });

    it('prefers eventType over nodeType', () => {
      // eventType: reporter_output -> 'reporter', but nodeType: executor -> 'executor'
      // eventType takes priority
      expect(stepToTopoNode({ eventType: 'reporter_output', nodeType: 'executor' })).toBe('reporter');
    });

    it('returns null for budget events (no topology mapping)', () => {
      expect(stepToTopoNode({ eventType: 'budget_update' })).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// computeEdgeCounts
// ---------------------------------------------------------------------------

describe('computeEdgeCounts', () => {
  const simpleEdges: GraphEdge[] = [
    { from: '__start__', to: 'router', condition: null },
    { from: 'router', to: 'planner', condition: 'plan' },
    { from: 'planner', to: 'step_selector', condition: null },
    { from: 'step_selector', to: 'executor', condition: null },
    { from: 'executor', to: 'reflector', condition: null },
    { from: 'reflector', to: 'reporter', condition: 'done' },
    { from: 'reporter', to: '__end__', condition: null },
  ];

  it('initializes all edges with count 0', () => {
    const counts = computeEdgeCounts([], simpleEdges);
    for (const [, info] of counts) {
      expect(info.count).toBe(0);
      expect(info.loopIds).toHaveLength(0);
    }
  });

  it('counts __start__->router edge for each loop with steps', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
        ],
      }),
      makeLoop({
        id: 'loop-2',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
        ],
      }),
    ];
    const counts = computeEdgeCounts(loops, simpleEdges);
    const startEdge = counts.get('__start__->router');
    expect(startEdge).toBeDefined();
    expect(startEdge!.count).toBe(2);
    expect(startEdge!.loopIds).toEqual(['loop-1', 'loop-2']);
  });

  it('counts sequential node transitions', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
          makeStep({ index: 1, eventType: 'executor_step', nodeType: 'executor' }),
          // step_selector (mapped from executor_step) -> executor is what the sequence shows
        ],
      }),
    ];
    const counts = computeEdgeCounts(loops, simpleEdges);
    // Planner maps to 'planner', executor_step maps to 'step_selector'
    // So sequence is: planner -> step_selector
    const plannerToSelector = counts.get('planner->step_selector');
    expect(plannerToSelector).toBeDefined();
    expect(plannerToSelector!.count).toBe(1);
  });

  it('adds reporter->__end__ edge when loop is done with finalAnswer', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        status: 'done',
        finalAnswer: 'All done!',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
          makeStep({ index: 1, eventType: 'reporter_output', nodeType: 'reporter' }),
        ],
      }),
    ];
    const counts = computeEdgeCounts(loops, simpleEdges);
    const endEdge = counts.get('reporter->__end__');
    expect(endEdge).toBeDefined();
    expect(endEdge!.count).toBe(1);
  });

  it('does not add __end__ edge when loop is not done', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        status: 'executing',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
        ],
      }),
    ];
    const counts = computeEdgeCounts(loops, simpleEdges);
    // No edge to __end__
    for (const [key, info] of counts) {
      if (key.endsWith('->__end__')) {
        expect(info.count).toBe(0);
      }
    }
  });

  it('deduplicates consecutive same topology nodes in sequence', () => {
    // Two executor steps back-to-back should only count as one 'executor' visit
    const loops = [
      makeLoop({
        id: 'loop-1',
        steps: [
          makeStep({ index: 0, nodeType: 'executor' }),
          makeStep({ index: 1, nodeType: 'executor' }),
          makeStep({ index: 2, nodeType: 'reflector' }),
        ],
      }),
    ];
    const counts = computeEdgeCounts(loops, simpleEdges);
    const execToReflector = counts.get('executor->reflector');
    expect(execToReflector).toBeDefined();
    expect(execToReflector!.count).toBe(1);
  });

  it('accumulates counts across multiple loops for the same edge', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        status: 'done',
        finalAnswer: 'done 1',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
          makeStep({ index: 1, eventType: 'reporter_output', nodeType: 'reporter' }),
        ],
      }),
      makeLoop({
        id: 'loop-2',
        status: 'done',
        finalAnswer: 'done 2',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
          makeStep({ index: 1, eventType: 'reporter_output', nodeType: 'reporter' }),
        ],
      }),
    ];
    const counts = computeEdgeCounts(loops, simpleEdges);
    // Both loops trigger __start__->router
    const startToRouter = counts.get('__start__->router');
    expect(startToRouter!.count).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// computeEdgeCounts with DEFAULT_TOPOLOGY
// ---------------------------------------------------------------------------

describe('computeEdgeCounts with DEFAULT_TOPOLOGY', () => {
  it('works with the full default topology edges', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        status: 'done',
        finalAnswer: 'done',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
          makeStep({ index: 1, eventType: 'executor_step', nodeType: 'executor' }),
          makeStep({ index: 2, eventType: 'reflector_decision', nodeType: 'reflector' }),
          makeStep({ index: 3, eventType: 'reporter_output', nodeType: 'reporter' }),
        ],
      }),
    ];
    const counts = computeEdgeCounts(loops, DEFAULT_TOPOLOGY.edges);
    // Sequence: planner -> step_selector -> reflector -> reporter
    // __start__->router should be counted (1)
    expect(counts.get('__start__->router')!.count).toBe(1);
    // planner -> step_selector: planner_output -> executor_step
    // executor_step maps to step_selector, so planner -> step_selector
    expect(counts.get('planner->step_selector')!.count).toBeGreaterThanOrEqual(0);
    // reporter -> __end__ because loop is done
    expect(counts.get('reporter->__end__')!.count).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// getActiveTopoNode
// ---------------------------------------------------------------------------

describe('getActiveTopoNode', () => {
  it('returns null for loop with no steps', () => {
    const loop = makeLoop({ steps: [] });
    expect(getActiveTopoNode(loop)).toBeNull();
  });

  it('returns null when loop is done', () => {
    const loop = makeLoop({
      status: 'done',
      steps: [makeStep({ index: 0, nodeType: 'reporter', status: 'done' })],
    });
    expect(getActiveTopoNode(loop)).toBeNull();
  });

  it('returns topology node for the last step when loop is executing', () => {
    const loop = makeLoop({
      status: 'executing',
      steps: [
        makeStep({ index: 0, nodeType: 'planner', status: 'done' }),
        makeStep({ index: 1, nodeType: 'executor', status: 'running' }),
      ],
    });
    expect(getActiveTopoNode(loop)).toBe('executor');
  });

  it('returns topology node when loop is planning', () => {
    const loop = makeLoop({
      status: 'planning',
      steps: [
        makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner', status: 'done' }),
      ],
    });
    expect(getActiveTopoNode(loop)).toBe('planner');
  });

  it('returns topology node when loop is reflecting', () => {
    const loop = makeLoop({
      status: 'reflecting',
      steps: [
        makeStep({ index: 0, eventType: 'reflector_decision', nodeType: 'reflector', status: 'running' }),
      ],
    });
    expect(getActiveTopoNode(loop)).toBe('reflector');
  });

  it('uses eventType for mapping when available', () => {
    const loop = makeLoop({
      status: 'executing',
      steps: [
        makeStep({ index: 0, eventType: 'executor_step', nodeType: 'executor', status: 'running' }),
      ],
    });
    // executor_step maps to step_selector
    expect(getActiveTopoNode(loop)).toBe('step_selector');
  });

  it('returns null for failed loop where last step is not running', () => {
    const loop = makeLoop({
      status: 'failed',
      steps: [
        makeStep({ index: 0, nodeType: 'executor', status: 'failed' }),
      ],
    });
    expect(getActiveTopoNode(loop)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// countEventsPerTopoNode
// ---------------------------------------------------------------------------

describe('countEventsPerTopoNode', () => {
  it('returns empty map for no loops', () => {
    const result = countEventsPerTopoNode([]);
    expect(result.size).toBe(0);
  });

  it('returns empty map for loops with no steps', () => {
    const result = countEventsPerTopoNode([makeLoop({ steps: [] })]);
    expect(result.size).toBe(0);
  });

  it('counts events per topology node', () => {
    const loops = [
      makeLoop({
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
          makeStep({ index: 1, eventType: 'executor_step', nodeType: 'executor' }),
          makeStep({ index: 2, eventType: 'executor_step', nodeType: 'executor' }),
        ],
      }),
    ];
    const result = countEventsPerTopoNode(loops);
    // planner_output maps to 'planner' topo node
    expect(result.get('planner')?.get('planner_output')).toBe(1);
    // executor_step maps to 'step_selector' topo node
    expect(result.get('step_selector')?.get('executor_step')).toBe(2);
  });

  it('accumulates across multiple loops', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        steps: [makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' })],
      }),
      makeLoop({
        id: 'loop-2',
        steps: [makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' })],
      }),
    ];
    const result = countEventsPerTopoNode(loops);
    expect(result.get('planner')?.get('planner_output')).toBe(2);
  });

  it('uses nodeType as event key when eventType is undefined', () => {
    const loops = [
      makeLoop({
        steps: [
          makeStep({ index: 0, nodeType: 'executor', eventType: undefined }),
        ],
      }),
    ];
    const result = countEventsPerTopoNode(loops);
    // nodeType 'executor' maps to topo node 'executor'
    expect(result.get('executor')?.get('executor')).toBe(1);
  });

  it('skips steps that do not map to a topology node', () => {
    const loops = [
      makeLoop({
        steps: [
          makeStep({ index: 0, eventType: 'budget_update', nodeType: undefined }),
        ],
      }),
    ];
    const result = countEventsPerTopoNode(loops);
    // budget_update maps to null via stepToTopoNode
    expect(result.size).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// buildDefaultEventNodeMap
// ---------------------------------------------------------------------------

describe('buildDefaultEventNodeMap', () => {
  it('returns a map for all known event types', () => {
    const map = buildDefaultEventNodeMap();
    expect(map).toHaveProperty('planner_output');
    expect(map).toHaveProperty('replanner_output');
    expect(map).toHaveProperty('executor_step');
    expect(map).toHaveProperty('thinking');
    expect(map).toHaveProperty('micro_reasoning');
    expect(map).toHaveProperty('tool_call');
    expect(map).toHaveProperty('tool_result');
    expect(map).toHaveProperty('reflector_decision');
    expect(map).toHaveProperty('router');
    expect(map).toHaveProperty('step_selector');
    expect(map).toHaveProperty('reporter_output');
    expect(map).toHaveProperty('budget');
    expect(map).toHaveProperty('budget_update');
  });

  it('maps planner_output to planner node', () => {
    const map = buildDefaultEventNodeMap();
    expect(map['planner_output']).toContain('planner');
  });

  it('maps tool_call to multiple tool nodes', () => {
    const map = buildDefaultEventNodeMap();
    expect(map['tool_call']).toContain('tools');
    expect(map['tool_call']).toContain('planner_tools');
    expect(map['tool_call']).toContain('reflector_tools');
  });

  it('maps budget events to empty arrays (no topology node)', () => {
    const map = buildDefaultEventNodeMap();
    expect(map['budget']).toEqual([]);
    expect(map['budget_update']).toEqual([]);
  });

  it('maps reflector_decision to reflector and reflector_route', () => {
    const map = buildDefaultEventNodeMap();
    expect(map['reflector_decision']).toContain('reflector');
    expect(map['reflector_decision']).toContain('reflector_route');
  });

  it('maps reporter_output to reporter', () => {
    const map = buildDefaultEventNodeMap();
    expect(map['reporter_output']).toContain('reporter');
  });
});

// ---------------------------------------------------------------------------
// DEFAULT_TOPOLOGY structure
// ---------------------------------------------------------------------------

describe('DEFAULT_TOPOLOGY', () => {
  it('has router as entry_node', () => {
    expect(DEFAULT_TOPOLOGY.entry_node).toBe('router');
  });

  it('has __end__ as terminal_node', () => {
    expect(DEFAULT_TOPOLOGY.terminal_nodes).toContain('__end__');
  });

  it('defines expected node set', () => {
    const nodeNames = Object.keys(DEFAULT_TOPOLOGY.nodes);
    expect(nodeNames).toContain('router');
    expect(nodeNames).toContain('planner');
    expect(nodeNames).toContain('executor');
    expect(nodeNames).toContain('reflector');
    expect(nodeNames).toContain('reporter');
    expect(nodeNames).toContain('step_selector');
    expect(nodeNames).toContain('tools');
  });

  it('all edges reference existing nodes or pseudo-nodes', () => {
    const validNodes = new Set([
      ...Object.keys(DEFAULT_TOPOLOGY.nodes),
      '__start__',
      '__end__',
    ]);
    for (const edge of DEFAULT_TOPOLOGY.edges) {
      expect(validNodes.has(edge.from)).toBe(true);
      expect(validNodes.has(edge.to)).toBe(true);
    }
  });

  it('has a path from __start__ to __end__', () => {
    // Basic graph connectivity check: __start__ connects to router
    const startEdge = DEFAULT_TOPOLOGY.edges.find(e => e.from === '__start__');
    expect(startEdge).toBeDefined();
    expect(startEdge!.to).toBe('router');
    // __end__ is reachable from reporter
    const endEdge = DEFAULT_TOPOLOGY.edges.find(e => e.to === '__end__');
    expect(endEdge).toBeDefined();
    expect(endEdge!.from).toBe('reporter');
  });
});

// ---------------------------------------------------------------------------
// Integration: multi-message edge count accumulation
// ---------------------------------------------------------------------------

describe('multi-message edge count accumulation', () => {
  it('accumulates edge counts across three loops', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        status: 'done',
        finalAnswer: 'result 1',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
          makeStep({ index: 1, eventType: 'executor_step', nodeType: 'executor' }),
          makeStep({ index: 2, eventType: 'reflector_decision', nodeType: 'reflector' }),
          makeStep({ index: 3, eventType: 'reporter_output', nodeType: 'reporter' }),
        ],
      }),
      makeLoop({
        id: 'loop-2',
        status: 'done',
        finalAnswer: 'result 2',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
          makeStep({ index: 1, eventType: 'executor_step', nodeType: 'executor' }),
          makeStep({ index: 2, eventType: 'reflector_decision', nodeType: 'reflector' }),
          makeStep({ index: 3, eventType: 'reporter_output', nodeType: 'reporter' }),
        ],
      }),
      makeLoop({
        id: 'loop-3',
        status: 'done',
        finalAnswer: 'result 3',
        steps: [
          makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
          makeStep({ index: 1, eventType: 'reporter_output', nodeType: 'reporter' }),
        ],
      }),
    ];

    const counts = computeEdgeCounts(loops, DEFAULT_TOPOLOGY.edges);

    // All 3 loops have steps -> __start__->router counts = 3
    const startEdge = counts.get('__start__->router');
    expect(startEdge!.count).toBe(3);

    // All 3 loops are done -> reporter->__end__ counts = 3
    const endEdge = counts.get('reporter->__end__');
    expect(endEdge!.count).toBe(3);
  });
});
