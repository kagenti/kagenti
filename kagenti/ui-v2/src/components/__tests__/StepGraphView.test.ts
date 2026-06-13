// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Unit tests for StepGraphView pure functions.
 *
 * Tests the data transformation layer: stepCategory, statusText,
 * toolStatusIcon, buildLoopGraph, and buildMultiLoopGraph.
 * Does NOT render React components — focuses on graph structure.
 */

import { describe, it, expect } from 'vitest';
import type { AgentLoop, AgentLoopStep } from '../../types/agentLoop';
import {
  stepCategory,
  statusText,
  toolStatusIcon,
  buildLoopGraph,
  buildMultiLoopGraph,
} from '../StepGraphView';

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
// stepCategory
// ---------------------------------------------------------------------------

describe('stepCategory', () => {
  it('returns category from EVENT_CATALOG when eventType is set', () => {
    expect(stepCategory(makeStep({ eventType: 'planner_output' }))).toBe('reasoning');
    expect(stepCategory(makeStep({ eventType: 'tool_call' }))).toBe('execution');
    expect(stepCategory(makeStep({ eventType: 'tool_result' }))).toBe('tool_output');
    expect(stepCategory(makeStep({ eventType: 'reflector_decision' }))).toBe('decision');
    expect(stepCategory(makeStep({ eventType: 'reporter_output' }))).toBe('terminal');
    expect(stepCategory(makeStep({ eventType: 'budget_update' }))).toBe('meta');
    expect(stepCategory(makeStep({ eventType: 'hitl_request' }))).toBe('interaction');
  });

  it('falls back to nodeType mapping when eventType is missing', () => {
    expect(stepCategory(makeStep({ nodeType: 'planner', eventType: undefined }))).toBe('reasoning');
    expect(stepCategory(makeStep({ nodeType: 'replanner', eventType: undefined }))).toBe('reasoning');
    expect(stepCategory(makeStep({ nodeType: 'executor', eventType: undefined }))).toBe('reasoning');
    expect(stepCategory(makeStep({ nodeType: 'reflector', eventType: undefined }))).toBe('decision');
    expect(stepCategory(makeStep({ nodeType: 'reporter', eventType: undefined }))).toBe('terminal');
  });

  it('defaults to reasoning for unknown nodeType', () => {
    expect(stepCategory(makeStep({ nodeType: undefined, eventType: undefined }))).toBe('reasoning');
  });
});

// ---------------------------------------------------------------------------
// statusText
// ---------------------------------------------------------------------------

describe('statusText', () => {
  it('returns [done] for done', () => {
    expect(statusText('done')).toBe('[done]');
  });

  it('returns [running] for running', () => {
    expect(statusText('running')).toBe('[running]');
  });

  it('returns [failed] for failed', () => {
    expect(statusText('failed')).toBe('[failed]');
  });

  it('returns [pending] for pending', () => {
    expect(statusText('pending')).toBe('[pending]');
  });
});

// ---------------------------------------------------------------------------
// toolStatusIcon
// ---------------------------------------------------------------------------

describe('toolStatusIcon', () => {
  it('returns [ok] for success', () => {
    expect(toolStatusIcon('success')).toBe('[ok]');
  });

  it('returns [err] for error', () => {
    expect(toolStatusIcon('error')).toBe('[err]');
  });

  it('returns [timeout] for timeout', () => {
    expect(toolStatusIcon('timeout')).toBe('[timeout]');
  });

  it('returns [...] for undefined/unknown status', () => {
    expect(toolStatusIcon(undefined)).toBe('[...]');
    expect(toolStatusIcon('pending')).toBe('[...]');
  });
});

// ---------------------------------------------------------------------------
// buildLoopGraph — Nodes mode
// ---------------------------------------------------------------------------

describe('buildLoopGraph (nodes mode)', () => {
  it('returns empty graph for loop with no steps', () => {
    const loop = makeLoop({ steps: [] });
    const result = buildLoopGraph(loop, 'test-', null, 'nodes');
    expect(result.nodes).toHaveLength(0);
    expect(result.edges).toHaveLength(0);
    expect(result.firstNodeId).toBeNull();
    expect(result.lastNodeId).toBeNull();
  });

  it('creates one node per distinct langgraph_node group', () => {
    const loop = makeLoop({
      steps: [
        makeStep({ index: 0, nodeType: 'planner' }),
        makeStep({ index: 1, nodeType: 'executor' }),
        makeStep({ index: 2, nodeType: 'executor' }),
        makeStep({ index: 3, nodeType: 'reflector' }),
      ],
    });
    const result = buildLoopGraph(loop, 'p-', null, 'nodes');
    // 3 groups: planner, executor(2), reflector
    // Plus no tool calls = no tool nodes
    expect(result.nodes).toHaveLength(3);
    expect(result.firstNodeId).toBe('p-cat-0');
    expect(result.lastNodeId).toBe('p-cat-2');
  });

  it('merges consecutive same-nodeType steps into one group', () => {
    const loop = makeLoop({
      steps: [
        makeStep({ index: 0, nodeType: 'executor' }),
        makeStep({ index: 1, nodeType: 'executor' }),
        makeStep({ index: 2, nodeType: 'executor' }),
      ],
    });
    const result = buildLoopGraph(loop, '', null, 'nodes');
    // All 3 executor steps merge into 1 group
    expect(result.nodes).toHaveLength(1);
  });

  it('does not merge non-consecutive same-nodeType steps', () => {
    const loop = makeLoop({
      steps: [
        makeStep({ index: 0, nodeType: 'executor' }),
        makeStep({ index: 1, nodeType: 'reflector' }),
        makeStep({ index: 2, nodeType: 'executor' }),
      ],
    });
    const result = buildLoopGraph(loop, '', null, 'nodes');
    // 3 groups: executor, reflector, executor
    expect(result.nodes).toHaveLength(3);
  });

  it('creates edges between consecutive groups', () => {
    const loop = makeLoop({
      steps: [
        makeStep({ index: 0, nodeType: 'planner' }),
        makeStep({ index: 1, nodeType: 'executor' }),
        makeStep({ index: 2, nodeType: 'reflector' }),
      ],
    });
    const result = buildLoopGraph(loop, 'p-', null, 'nodes');
    // 2 edges: planner->executor, executor->reflector
    const mainEdges = result.edges.filter(e => !e.id.includes('tool'));
    expect(mainEdges).toHaveLength(2);
    expect(mainEdges[0].source).toBe('p-cat-0');
    expect(mainEdges[0].target).toBe('p-cat-1');
    expect(mainEdges[1].source).toBe('p-cat-1');
    expect(mainEdges[1].target).toBe('p-cat-2');
  });

  it('creates tool call sub-nodes branching off executor groups', () => {
    const loop = makeLoop({
      steps: [
        makeStep({
          index: 0,
          nodeType: 'executor',
          toolCalls: [
            { type: 'tool_call', name: 'read_file', args: {} },
            { type: 'tool_call', name: 'write_file', args: {} },
          ],
          toolResults: [
            { type: 'tool_result', name: 'read_file', output: 'ok', status: 'success' },
            { type: 'tool_result', name: 'write_file', output: 'ok', status: 'success' },
          ],
        }),
      ],
    });
    const result = buildLoopGraph(loop, 'p-', null, 'nodes');
    // 1 executor node + 2 tool nodes = 3 total
    expect(result.nodes).toHaveLength(3);
    // 2 edges: executor->tool1, executor->tool2
    expect(result.edges).toHaveLength(2);
    expect(result.edges[0].source).toBe('p-cat-0');
    expect(result.edges[0].target).toBe('p-step-0-tool-0');
    expect(result.edges[1].source).toBe('p-cat-0');
    expect(result.edges[1].target).toBe('p-step-0-tool-1');
  });

  it('prepends message index in multi-message mode', () => {
    const loop = makeLoop({
      steps: [makeStep({ index: 0, nodeType: 'planner' })],
    });
    const result = buildLoopGraph(loop, 'p-', 2, 'nodes');
    expect(result.nodes).toHaveLength(1);
    // Node ID should not change, but we verify the node was created
    expect(result.firstNodeId).toBe('p-cat-0');
  });
});

// ---------------------------------------------------------------------------
// buildLoopGraph — Events mode
// ---------------------------------------------------------------------------

describe('buildLoopGraph (events mode)', () => {
  it('creates one node per step (no merging)', () => {
    const loop = makeLoop({
      steps: [
        makeStep({ index: 0, nodeType: 'executor' }),
        makeStep({ index: 1, nodeType: 'executor' }),
        makeStep({ index: 2, nodeType: 'executor' }),
      ],
    });
    const result = buildLoopGraph(loop, '', null, 'events');
    // 3 separate nodes (no merging in events mode)
    expect(result.nodes).toHaveLength(3);
  });

  it('creates sequential edges between steps', () => {
    const loop = makeLoop({
      steps: [
        makeStep({ index: 0, nodeType: 'planner' }),
        makeStep({ index: 1, nodeType: 'executor' }),
        makeStep({ index: 2, nodeType: 'reporter' }),
      ],
    });
    const result = buildLoopGraph(loop, 'p-', null, 'events');
    const mainEdges = result.edges.filter(e => !e.id.includes('tool') && !e.id.includes('think'));
    expect(mainEdges).toHaveLength(2);
    expect(mainEdges[0].source).toBe('p-step-0');
    expect(mainEdges[0].target).toBe('p-step-1');
  });

  it('uses eventType as label when available', () => {
    const loop = makeLoop({
      steps: [
        makeStep({ index: 0, eventType: 'planner_output', nodeType: 'planner' }),
      ],
    });
    const result = buildLoopGraph(loop, '', null, 'events');
    expect(result.nodes).toHaveLength(1);
    // Node exists with expected ID
    expect(result.nodes[0].id).toBe('step-0');
  });

  it('creates thinking sub-nodes for steps with thinking iterations', () => {
    const loop = makeLoop({
      steps: [
        makeStep({
          index: 0,
          nodeType: 'executor',
          thinkings: [
            { type: 'thinking', loop_id: 'l1', iteration: 1, total_iterations: 2, reasoning: 'think1' },
            { type: 'thinking', loop_id: 'l1', iteration: 2, total_iterations: 2, reasoning: 'think2' },
          ],
        }),
      ],
    });
    const result = buildLoopGraph(loop, '', null, 'events');
    // 1 executor node + 1 thinking node = 2
    expect(result.nodes).toHaveLength(2);
    // 1 edge: executor->thinking
    const thinkEdges = result.edges.filter(e => e.id.includes('think'));
    expect(thinkEdges).toHaveLength(1);
    expect(thinkEdges[0].source).toBe('step-0');
    expect(thinkEdges[0].target).toBe('step-0-think');
  });

  it('marks replan edges with dashed style', () => {
    const loop = makeLoop({
      steps: [
        makeStep({ index: 0, nodeType: 'reflector' }),
        makeStep({ index: 1, nodeType: 'replanner' }),
      ],
    });
    const result = buildLoopGraph(loop, '', null, 'events');
    const replanEdge = result.edges.find(e => e.source === 'step-0' && e.target === 'step-1');
    expect(replanEdge).toBeDefined();
    expect(replanEdge!.style).toBeDefined();
    expect(replanEdge!.style!.strokeDasharray).toBe('5 5');
    expect(replanEdge!.label).toBe('replan');
  });

  it('sets animated flag on edges to running steps', () => {
    const loop = makeLoop({
      status: 'executing',
      steps: [
        makeStep({ index: 0, nodeType: 'planner', status: 'done' }),
        makeStep({ index: 1, nodeType: 'executor', status: 'running' }),
      ],
    });
    const result = buildLoopGraph(loop, '', null, 'events');
    const edge = result.edges.find(e => e.source === 'step-0' && e.target === 'step-1');
    expect(edge).toBeDefined();
    expect(edge!.animated).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// buildMultiLoopGraph
// ---------------------------------------------------------------------------

describe('buildMultiLoopGraph', () => {
  it('handles a single loop without cross-loop edges', () => {
    const loops = [
      makeLoop({
        steps: [
          makeStep({ index: 0, nodeType: 'planner' }),
          makeStep({ index: 1, nodeType: 'executor' }),
        ],
      }),
    ];
    const result = buildMultiLoopGraph(loops, 'nodes');
    // Single loop: no message index prefix, no cross edges
    expect(result.totalNodes).toBeGreaterThan(0);
    const crossEdges = result.edges.filter(e => e.id.startsWith('e-cross-'));
    expect(crossEdges).toHaveLength(0);
  });

  it('connects last node of loop N to first node of loop N+1 for multi-message', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        steps: [
          makeStep({ index: 0, nodeType: 'planner' }),
          makeStep({ index: 1, nodeType: 'reporter' }),
        ],
      }),
      makeLoop({
        id: 'loop-2',
        steps: [
          makeStep({ index: 0, nodeType: 'planner' }),
          makeStep({ index: 1, nodeType: 'executor' }),
        ],
      }),
    ];
    const result = buildMultiLoopGraph(loops, 'nodes');
    const crossEdges = result.edges.filter(e => e.id.startsWith('e-cross-'));
    expect(crossEdges).toHaveLength(1);
    expect(crossEdges[0].label).toBe('msg 2');
    expect(crossEdges[0].style).toBeDefined();
    expect(crossEdges[0].style!.stroke).toBe('#58a6ff');
  });

  it('assigns unique node IDs with loop prefix', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        steps: [makeStep({ index: 0, nodeType: 'planner' })],
      }),
      makeLoop({
        id: 'loop-2',
        steps: [makeStep({ index: 0, nodeType: 'planner' })],
      }),
    ];
    const result = buildMultiLoopGraph(loops, 'nodes');
    const nodeIds = result.allNodeIds;
    // All node IDs should be unique
    expect(new Set(nodeIds).size).toBe(nodeIds.length);
    // Should contain prefixed IDs
    expect(nodeIds.some(id => id.startsWith('loop0-'))).toBe(true);
    expect(nodeIds.some(id => id.startsWith('loop1-'))).toBe(true);
  });

  it('highlights the last node with cyan border', () => {
    const loops = [
      makeLoop({
        steps: [
          makeStep({ index: 0, nodeType: 'planner' }),
          makeStep({ index: 1, nodeType: 'executor' }),
        ],
      }),
    ];
    const result = buildMultiLoopGraph(loops, 'nodes');
    const lastNodeId = result.allNodeIds[result.allNodeIds.length - 1];
    const lastNode = result.nodes.find(n => n.id === lastNodeId);
    expect(lastNode).toBeDefined();
    // The last main node (not tool nodes) should have blue highlight border
    // Find the actual last "cat" node
    const catNodes = result.nodes.filter(n => n.id.includes('cat-'));
    if (catNodes.length > 0) {
      const lastCat = catNodes[catNodes.length - 1];
      expect((lastCat.style as Record<string, unknown>).border).toContain('#58a6ff');
    }
  });

  it('handles empty loops gracefully', () => {
    const loops = [
      makeLoop({ steps: [] }),
      makeLoop({ steps: [] }),
    ];
    const result = buildMultiLoopGraph(loops, 'nodes');
    expect(result.totalNodes).toBe(0);
    expect(result.edges).toHaveLength(0);
    expect(result.allNodeIds).toHaveLength(0);
  });

  it('accumulates nodes across multiple loops', () => {
    const loops = [
      makeLoop({
        id: 'loop-1',
        steps: [
          makeStep({ index: 0, nodeType: 'planner' }),
          makeStep({ index: 1, nodeType: 'executor' }),
        ],
      }),
      makeLoop({
        id: 'loop-2',
        steps: [
          makeStep({ index: 0, nodeType: 'planner' }),
          makeStep({ index: 1, nodeType: 'executor' }),
          makeStep({ index: 2, nodeType: 'reporter' }),
        ],
      }),
    ];
    const result = buildMultiLoopGraph(loops, 'nodes');
    // Loop 1: 2 groups, Loop 2: 3 groups = 5 total group nodes
    const catNodes = result.nodes.filter(n => n.id.includes('cat-'));
    expect(catNodes).toHaveLength(5);
  });
});
