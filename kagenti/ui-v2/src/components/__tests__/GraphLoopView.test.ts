// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Unit tests for GraphLoopView data flow logic.
 *
 * GraphLoopView is a wrapper component that toggles between StepGraphView
 * and TopologyGraphView. Since we cannot render React components in a
 * node-only test environment, we test the data transformation layer that
 * feeds into both child views.
 *
 * These tests verify:
 *   - Multi-message loop array handling (the loops memo)
 *   - Empty loop detection (allEmpty guard)
 *   - The pure functions from both child components work correctly
 *     with the same data that GraphLoopView would pass through
 */

import { describe, it, expect } from 'vitest';
import type { AgentLoop, AgentLoopStep } from '../../types/agentLoop';
import type { AgentGraphCard, GraphTopology } from '../../types/graphCard';
import { buildMultiLoopGraph } from '../StepGraphView';
import {
  computeEdgeCounts,
  getActiveTopoNode,
  countEventsPerTopoNode,
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

function makeGraphCard(overrides: Partial<AgentGraphCard> = {}): AgentGraphCard {
  return {
    id: 'test-agent',
    description: 'Test agent for unit tests',
    framework: 'langgraph',
    version: '1.0.0',
    event_catalog: {},
    common_event_fields: {},
    topology: DEFAULT_TOPOLOGY,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Multi-message loop array handling
// ---------------------------------------------------------------------------

describe('multi-message loop array handling', () => {
  it('GraphLoopView uses allLoops when provided, or wraps single loop', () => {
    // Simulate the useMemo: allLoops || [loop]
    const singleLoop = makeLoop({ id: 'single' });
    const allLoops = [
      makeLoop({ id: 'loop-1' }),
      makeLoop({ id: 'loop-2' }),
      makeLoop({ id: 'loop-3' }),
    ];

    // When allLoops is provided
    const resolvedWithAll = allLoops || [singleLoop];
    expect(resolvedWithAll).toHaveLength(3);
    expect(resolvedWithAll[0].id).toBe('loop-1');

    // When allLoops is undefined
    const noLoops = undefined as AgentLoop[] | undefined;
    const resolvedWithSingle = noLoops || [singleLoop];
    expect(resolvedWithSingle).toHaveLength(1);
    expect(resolvedWithSingle[0].id).toBe('single');
  });
});

// ---------------------------------------------------------------------------
// Empty loop detection
// ---------------------------------------------------------------------------

describe('empty loop detection (allEmpty guard)', () => {
  it('detects all loops are empty', () => {
    const loops = [
      makeLoop({ steps: [] }),
      makeLoop({ steps: [] }),
    ];
    const allEmpty = loops.every(l => l.steps.length === 0);
    expect(allEmpty).toBe(true);
  });

  it('detects at least one loop has steps', () => {
    const loops = [
      makeLoop({ steps: [] }),
      makeLoop({ steps: [makeStep()] }),
    ];
    const allEmpty = loops.every(l => l.steps.length === 0);
    expect(allEmpty).toBe(false);
  });

  it('single loop with steps is not empty', () => {
    const loops = [makeLoop({ steps: [makeStep()] })];
    const allEmpty = loops.every(l => l.steps.length === 0);
    expect(allEmpty).toBe(false);
  });

  it('no loops at all means empty', () => {
    const loops: AgentLoop[] = [];
    const allEmpty = loops.every(l => l.steps.length === 0);
    expect(allEmpty).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Mode switching data flow
// ---------------------------------------------------------------------------

describe('mode switching data flow', () => {
  const testLoops = [
    makeLoop({
      id: 'loop-1',
      steps: [
        makeStep({ index: 0, nodeType: 'planner', eventType: 'planner_output' }),
        makeStep({ index: 1, nodeType: 'executor', eventType: 'executor_step' }),
        makeStep({ index: 2, nodeType: 'reflector', eventType: 'reflector_decision' }),
        makeStep({ index: 3, nodeType: 'reporter', eventType: 'reporter_output' }),
      ],
    }),
  ];

  describe('Step Graph mode', () => {
    it('nodes mode groups consecutive same-nodeType steps', () => {
      const result = buildMultiLoopGraph(testLoops, 'nodes');
      // 4 different nodeTypes = 4 groups in nodes mode
      const catNodes = result.nodes.filter(n => n.id.includes('cat-'));
      expect(catNodes).toHaveLength(4);
    });

    it('events mode creates one node per step', () => {
      const result = buildMultiLoopGraph(testLoops, 'events');
      // 4 steps = 4 nodes in events mode
      const stepNodes = result.nodes.filter(n => n.id.includes('step-'));
      expect(stepNodes).toHaveLength(4);
    });

    it('nodes and events modes produce different numbers of nodes for merged steps', () => {
      const loopsWithMerge = [
        makeLoop({
          steps: [
            makeStep({ index: 0, nodeType: 'executor' }),
            makeStep({ index: 1, nodeType: 'executor' }),
            makeStep({ index: 2, nodeType: 'executor' }),
          ],
        }),
      ];
      const nodesResult = buildMultiLoopGraph(loopsWithMerge, 'nodes');
      const eventsResult = buildMultiLoopGraph(loopsWithMerge, 'events');
      // Nodes mode: 1 merged group
      const catNodes = nodesResult.nodes.filter(n => n.id.includes('cat-'));
      expect(catNodes).toHaveLength(1);
      // Events mode: 3 individual nodes
      const stepNodes = eventsResult.nodes.filter(n => n.id.includes('step-'));
      expect(stepNodes).toHaveLength(3);
    });
  });

  describe('Topology mode', () => {
    it('active node detection works for executing loop', () => {
      const executingLoop = makeLoop({
        status: 'executing',
        steps: [
          makeStep({ index: 0, eventType: 'executor_step', nodeType: 'executor', status: 'running' }),
        ],
      });
      const activeNode = getActiveTopoNode(executingLoop);
      expect(activeNode).toBe('step_selector');
    });

    it('edge counts accumulate for multi-message topology', () => {
      const multiLoops = [
        makeLoop({
          id: 'l1',
          status: 'done',
          finalAnswer: 'done',
          steps: [
            makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
            makeStep({ index: 1, eventType: 'reporter_output', nodeType: 'reporter' }),
          ],
        }),
        makeLoop({
          id: 'l2',
          status: 'done',
          finalAnswer: 'done',
          steps: [
            makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
            makeStep({ index: 1, eventType: 'reporter_output', nodeType: 'reporter' }),
          ],
        }),
      ];
      const counts = computeEdgeCounts(multiLoops, DEFAULT_TOPOLOGY.edges);
      // Both loops start: __start__->router = 2
      expect(counts.get('__start__->router')!.count).toBe(2);
      // Both loops end: reporter->__end__ = 2
      expect(counts.get('reporter->__end__')!.count).toBe(2);
    });

    it('event counts map to correct topology nodes', () => {
      const eventCounts = countEventsPerTopoNode(testLoops);
      // planner_output -> 'planner' topo node
      expect(eventCounts.get('planner')?.get('planner_output')).toBe(1);
      // executor_step -> 'step_selector' topo node
      expect(eventCounts.get('step_selector')?.get('executor_step')).toBe(1);
      // reflector_decision -> 'reflector' topo node
      expect(eventCounts.get('reflector')?.get('reflector_decision')).toBe(1);
      // reporter_output -> 'reporter' topo node
      expect(eventCounts.get('reporter')?.get('reporter_output')).toBe(1);
    });
  });
});

// ---------------------------------------------------------------------------
// Props data: graphCard topology fallback
// ---------------------------------------------------------------------------

describe('graphCard topology fallback', () => {
  it('uses default topology when graphCard is undefined', () => {
    const graphCard = undefined as AgentGraphCard | undefined;
    const topology = graphCard?.topology || DEFAULT_TOPOLOGY;
    expect(topology.entry_node).toBe('router');
    expect(Object.keys(topology.nodes)).toContain('executor');
  });

  it('uses graphCard topology when provided', () => {
    const customTopology: GraphTopology = {
      entry_node: 'custom_router',
      terminal_nodes: ['__end__'],
      nodes: {
        custom_router: { description: 'Custom router' },
        worker: { description: 'Worker node' },
      },
      edges: [
        { from: '__start__', to: 'custom_router', condition: null },
        { from: 'custom_router', to: 'worker', condition: null },
        { from: 'worker', to: '__end__', condition: null },
      ],
    };
    const graphCard = makeGraphCard({ topology: customTopology });
    const topology = graphCard?.topology || DEFAULT_TOPOLOGY;
    expect(topology.entry_node).toBe('custom_router');
    expect(Object.keys(topology.nodes)).toContain('worker');
    expect(Object.keys(topology.nodes)).not.toContain('executor');
  });
});

// ---------------------------------------------------------------------------
// End-to-end data flow: full agent session
// ---------------------------------------------------------------------------

describe('full agent session data flow', () => {
  it('handles a complete agent session with plan, execute, reflect, report', () => {
    const loop = makeLoop({
      id: 'session-1',
      status: 'done',
      finalAnswer: 'Task completed successfully.',
      plan: ['Read the file', 'Analyze content', 'Write report'],
      totalSteps: 3,
      steps: [
        makeStep({
          index: 0,
          nodeType: 'planner',
          eventType: 'planner_output',
          status: 'done',
          tokens: { prompt: 500, completion: 200 },
        }),
        makeStep({
          index: 1,
          nodeType: 'executor',
          eventType: 'executor_step',
          status: 'done',
          tokens: { prompt: 300, completion: 100 },
          toolCalls: [{ type: 'tool_call', name: 'read_file', args: { path: 'test.py' } }],
          toolResults: [{ type: 'tool_result', name: 'read_file', output: 'content', status: 'success' }],
        }),
        makeStep({
          index: 2,
          nodeType: 'executor',
          eventType: 'executor_step',
          status: 'done',
          tokens: { prompt: 400, completion: 150 },
        }),
        makeStep({
          index: 3,
          nodeType: 'reflector',
          eventType: 'reflector_decision',
          status: 'done',
          tokens: { prompt: 200, completion: 50 },
        }),
        makeStep({
          index: 4,
          nodeType: 'reporter',
          eventType: 'reporter_output',
          status: 'done',
          tokens: { prompt: 100, completion: 300 },
        }),
      ],
    });

    // Step Graph: nodes mode
    const nodesGraph = buildMultiLoopGraph([loop], 'nodes');
    // Groups: planner(1), executor(2 merged), reflector(1), reporter(1) = 4 groups
    // Plus 1 tool call node from step index 1
    const catNodes = nodesGraph.nodes.filter(n => n.id.includes('cat-'));
    expect(catNodes).toHaveLength(4);
    const toolNodes = nodesGraph.nodes.filter(n => n.id.includes('tool-'));
    expect(toolNodes).toHaveLength(1);

    // Step Graph: events mode
    const eventsGraph = buildMultiLoopGraph([loop], 'events');
    const stepNodes = eventsGraph.nodes.filter(n => n.id.includes('step-') && !n.id.includes('tool'));
    expect(stepNodes).toHaveLength(5);

    // Topology: edge counts
    const edgeCounts = computeEdgeCounts([loop], DEFAULT_TOPOLOGY.edges);
    expect(edgeCounts.get('__start__->router')!.count).toBe(1);
    expect(edgeCounts.get('reporter->__end__')!.count).toBe(1);

    // Topology: event counts
    const eventCounts = countEventsPerTopoNode([loop]);
    expect(eventCounts.get('planner')?.get('planner_output')).toBe(1);
    expect(eventCounts.get('step_selector')?.get('executor_step')).toBe(2);
    expect(eventCounts.get('reflector')?.get('reflector_decision')).toBe(1);
    expect(eventCounts.get('reporter')?.get('reporter_output')).toBe(1);

    // Active node: done loop has no active node
    expect(getActiveTopoNode(loop)).toBeNull();
  });
});
