// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * StepGraphView — React Flow DAG of per-step execution flow.
 *
 * Builds a directed acyclic graph from AgentLoop data:
 *   planner -> executor(s) -> reflector -> reporter
 * with tool call nodes branching off executors.
 *
 * Multi-message mode: when allLoops is provided, renders all loops
 * sequentially with the last node of message N connecting to the first
 * node of message N+1.
 */

import React, { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import {
  ReactFlow,
  type Node,
  type Edge,
  type NodeMouseHandler,
  Position,
  Background,
  Controls,
  MiniMap,
} from '@xyflow/react';
import dagre from 'dagre';
import type { AgentLoop, AgentLoopStep } from '../types/agentLoop';
import { inferNodeType, type GraphNodeType } from '../utils/loopFormatting';
import { EVENT_CATALOG } from '../utils/loopBuilder';
import { GraphDetailPanel } from './GraphDetailPanel';

import '@xyflow/react/dist/style.css';

// ---------------------------------------------------------------------------
// Styles (extends shared NODE_COLORS with border + tool/thinking types)
// ---------------------------------------------------------------------------

type ExtendedNodeType = GraphNodeType | 'tool' | 'thinking';

const NODE_STYLES: Record<ExtendedNodeType, { bg: string; border: string; color: string }> = {
  planner:   { bg: '#0066cc', border: '#004999', color: '#fff' },
  replanner: { bg: '#0055aa', border: '#003d7a', color: '#fff' },
  executor:  { bg: '#2e7d32', border: '#1b5e20', color: '#fff' },
  reflector: { bg: '#e65100', border: '#bf360c', color: '#fff' },
  reporter:  { bg: '#7b1fa2', border: '#4a148c', color: '#fff' },
  tool:      { bg: '#1a1a2e', border: '#333', color: '#ccc' },
  thinking:  { bg: '#1a1a2e', border: '#b388ff', color: '#b388ff' },
};

// ---------------------------------------------------------------------------
// Category colors (for 'nodes' mode)
// ---------------------------------------------------------------------------

type EventCategory = 'reasoning' | 'execution' | 'tool_output' | 'decision' | 'terminal' | 'meta' | 'interaction';

const CATEGORY_STYLES: Record<EventCategory, { bg: string; border: string; color: string }> = {
  reasoning:   { bg: '#0066cc', border: '#004999', color: '#fff' },
  execution:   { bg: '#2e7d32', border: '#1b5e20', color: '#fff' },
  tool_output: { bg: '#1a1a2e', border: '#333',    color: '#ccc' },
  decision:    { bg: '#e65100', border: '#bf360c', color: '#fff' },
  terminal:    { bg: '#7b1fa2', border: '#4a148c', color: '#fff' },
  meta:        { bg: '#455a64', border: '#37474f', color: '#ccc' },
  interaction: { bg: '#795548', border: '#5d4037', color: '#fff' },
};

/** Human-friendly category labels. */
const CATEGORY_LABELS: Record<EventCategory, string> = {
  reasoning:   'Reasoning',
  execution:   'Execution',
  tool_output: 'Tool Output',
  decision:    'Decision',
  terminal:    'Terminal',
  meta:        'Meta',
  interaction: 'Interaction',
};

/** Look up the category for a step, using its eventType first, then nodeType fallback. */
function stepCategory(step: AgentLoopStep): EventCategory {
  // Try eventType in catalog
  if (step.eventType) {
    const def = EVENT_CATALOG[step.eventType];
    if (def) return def.category as EventCategory;
  }
  // Fallback: map nodeType to category
  const nt = step.nodeType;
  if (nt === 'planner' || nt === 'replanner' || nt === 'executor') return 'reasoning';
  if (nt === 'reflector') return 'decision';
  if (nt === 'reporter') return 'terminal';
  return 'reasoning';
}

// ---------------------------------------------------------------------------
// Dagre layout
// ---------------------------------------------------------------------------

function applyDagreLayout(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', nodesep: 30, ranksep: 50 });

  for (const node of nodes) {
    g.setNode(node.id, { width: node.measured?.width ?? 180, height: node.measured?.height ?? 50 });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const layoutNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    const w = node.measured?.width ?? 180;
    const h = node.measured?.height ?? 50;
    return {
      ...node,
      position: { x: pos.x - w / 2, y: pos.y - h / 2 },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    };
  });

  return { nodes: layoutNodes, edges };
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function statusText(status: AgentLoopStep['status']): string {
  switch (status) {
    case 'done':    return '\u2713';
    case 'running': return '\u25b6';
    case 'failed':  return '\u2717';
    default:        return '\u2022';
  }
}

function toolStatusIcon(status?: string): string {
  switch (status) {
    case 'success': return '\u2713';
    case 'error':   return '\u2717';
    case 'timeout': return '\u23f3';
    default:        return '\u25b6';
  }
}

// ---------------------------------------------------------------------------
// Build graph from a single AgentLoop (with optional prefix for multi-loop)
// ---------------------------------------------------------------------------

function buildLoopGraph(
  loop: AgentLoop,
  prefix: string,
  messageIdx: number | null,
  eventDetail: 'nodes' | 'events',
): { nodes: Node[]; edges: Edge[]; firstNodeId: string | null; lastNodeId: string | null } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  let prevNodeId: string | null = null;
  let firstNodeId: string | null = null;

  if (eventDetail === 'nodes') {
    // ---- Categories mode: merge consecutive same-category steps ----
    interface MergedGroup {
      category: EventCategory;
      steps: AgentLoopStep[];
      firstIndex: number;
    }
    const groups: MergedGroup[] = [];
    for (const step of loop.steps) {
      const cat = stepCategory(step);
      const last = groups[groups.length - 1];
      if (last && last.category === cat) {
        last.steps.push(step);
      } else {
        groups.push({ category: cat, steps: [step], firstIndex: step.index });
      }
    }

    for (let gi = 0; gi < groups.length; gi++) {
      const group = groups[gi];
      const catStyle = CATEGORY_STYLES[group.category];
      const nodeId = `${prefix}cat-${gi}`;
      const count = group.steps.length;
      const anyRunning = group.steps.some((s) => s.status === 'running');

      // Aggregate tokens across merged steps
      const totalTokens = group.steps.reduce((sum, s) => sum + s.tokens.prompt + s.tokens.completion, 0);
      const tokenLabel = totalTokens >= 1000 ? `${(totalTokens / 1000).toFixed(1)}k` : String(totalTokens);

      let label = CATEGORY_LABELS[group.category];
      if (count > 1) label += ` (${count})`;
      if (messageIdx !== null) label = `M${messageIdx + 1}: ${label}`;

      // Representative status — running if any step is running, else last step status
      const repStatus = anyRunning ? 'running' : group.steps[group.steps.length - 1].status;

      nodes.push({
        id: nodeId,
        data: {
          label: (
            <div style={{ textAlign: 'center', fontSize: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 2 }}>{label}</div>
              <div style={{ fontSize: 10, opacity: 0.8 }}>
                {statusText(repStatus)} {totalTokens > 0 ? `${tokenLabel} tokens` : ''}
              </div>
            </div>
          ),
        },
        position: { x: 0, y: 0 },
        style: {
          background: catStyle.bg,
          border: `2px solid ${catStyle.border}`,
          color: catStyle.color,
          borderRadius: 8,
          padding: '8px 12px',
          minWidth: 140,
          cursor: 'pointer',
          ...(anyRunning ? { boxShadow: `0 0 8px ${catStyle.border}` } : {}),
        },
      });

      if (firstNodeId === null) firstNodeId = nodeId;

      if (prevNodeId) {
        edges.push({
          id: `e-${prevNodeId}-${nodeId}`,
          source: prevNodeId,
          target: nodeId,
          animated: anyRunning,
        });
      }

      // Tool call nodes for all steps in the group
      for (const step of group.steps) {
        step.toolCalls.forEach((tc, j) => {
          const toolId = `${prefix}step-${step.index}-tool-${j}`;
          const result = step.toolResults[j];
          const toolStyle = NODE_STYLES.tool;

          nodes.push({
            id: toolId,
            data: {
              label: (
                <div style={{ textAlign: 'center', fontSize: 11 }}>
                  <div style={{ fontWeight: 500 }}>{tc.name || 'tool'}</div>
                  <div style={{ fontSize: 10 }}>{toolStatusIcon(result?.status)}</div>
                </div>
              ),
            },
            position: { x: 0, y: 0 },
            style: {
              background: toolStyle.bg,
              border: `1px solid ${result?.status === 'error' ? 'var(--pf-v5-global--danger-color--100)' : toolStyle.border}`,
              color: toolStyle.color,
              borderRadius: 6,
              padding: '4px 8px',
              fontSize: 11,
              minWidth: 100,
              cursor: 'pointer',
            },
          });

          edges.push({
            id: `e-${nodeId}-${toolId}`,
            source: nodeId,
            target: toolId,
            style: { stroke: '#555' },
          });
        });
      }

      prevNodeId = nodeId;
    }
  } else {
    // ---- Event Types mode: each step is its own node with specific event type label ----
    for (const step of loop.steps) {
      const nt = inferNodeType(step);
      const style = NODE_STYLES[nt];
      const nodeId = `${prefix}step-${step.index}`;

      // Use specific event type as label
      let label: string;
      if (step.eventType) {
        label = step.eventType;
      } else if (nt === 'executor' && step.planStep != null) {
        label = `executor_step (${step.planStep + 1})`;
      } else if (nt === 'reflector') {
        label = `reflector_decision: ${loop.reflectorDecision || ''}`;
      } else if (nt === 'reporter') {
        label = 'reporter_output';
      } else if (nt === 'planner' || nt === 'replanner') {
        label = `${nt === 'replanner' ? 'replanner_output' : 'planner_output'} (${loop.plan.length} steps)`;
      } else {
        label = nt;
      }

      // Prepend message index for multi-message mode
      if (messageIdx !== null) {
        label = `M${messageIdx + 1}: ${label}`;
      }

      const tokens = step.tokens.prompt + step.tokens.completion;
      const tokenLabel = tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : String(tokens);

      nodes.push({
        id: nodeId,
        data: {
          label: (
            <div style={{ textAlign: 'center', fontSize: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 2 }}>{label}</div>
              <div style={{ fontSize: 10, opacity: 0.8 }}>
                {statusText(step.status)} {tokens > 0 ? `${tokenLabel} tokens` : ''}
              </div>
            </div>
          ),
        },
        position: { x: 0, y: 0 },
        style: {
          background: style.bg,
          border: `2px solid ${style.border}`,
          color: style.color,
          borderRadius: 8,
          padding: '8px 12px',
          minWidth: 140,
          cursor: 'pointer',
          ...(step.status === 'running' ? { boxShadow: `0 0 8px ${style.border}` } : {}),
        },
      });

      if (firstNodeId === null) firstNodeId = nodeId;

      if (prevNodeId) {
        const isReplanEdge = nt === 'planner' || nt === 'replanner';
        edges.push({
          id: `e-${prevNodeId}-${nodeId}`,
          source: prevNodeId,
          target: nodeId,
          animated: step.status === 'running',
          style: isReplanEdge ? { strokeDasharray: '5 5', stroke: '#e65100' } : undefined,
          label: isReplanEdge ? 'replan' : undefined,
        });
      }

      // Tool call nodes
      step.toolCalls.forEach((tc, j) => {
        const toolId = `${nodeId}-tool-${j}`;
        const result = step.toolResults[j];
        const toolStyle = NODE_STYLES.tool;

        nodes.push({
          id: toolId,
          data: {
            label: (
              <div style={{ textAlign: 'center', fontSize: 11 }}>
                <div style={{ fontWeight: 500 }}>{tc.name || 'tool'}</div>
                <div style={{ fontSize: 10 }}>{toolStatusIcon(result?.status)}</div>
              </div>
            ),
          },
          position: { x: 0, y: 0 },
          style: {
            background: toolStyle.bg,
            border: `1px solid ${result?.status === 'error' ? 'var(--pf-v5-global--danger-color--100)' : toolStyle.border}`,
            color: toolStyle.color,
            borderRadius: 6,
            padding: '4px 8px',
            fontSize: 11,
            minWidth: 100,
            cursor: 'pointer',
          },
        });

        edges.push({
          id: `e-${nodeId}-${toolId}`,
          source: nodeId,
          target: toolId,
          style: { stroke: '#555' },
        });
      });

      // Thinking sub-nodes (collapsed into a single node per step)
      const thinkings = step.thinkings || [];
      if (thinkings.length > 0) {
        const thinkId = `${nodeId}-think`;
        const thinkStyle = NODE_STYLES.thinking;
        nodes.push({
          id: thinkId,
          data: {
            label: (
              <div style={{ textAlign: 'center', fontSize: 11 }}>
                <div style={{ fontWeight: 500 }}>{thinkings.length} thinking</div>
              </div>
            ),
          },
          position: { x: 0, y: 0 },
          style: {
            background: thinkStyle.bg,
            border: `1px solid ${thinkStyle.border}`,
            color: thinkStyle.color,
            borderRadius: 6,
            padding: '4px 8px',
            minWidth: 80,
            cursor: 'pointer',
          },
        });
        edges.push({
          id: `e-${nodeId}-${thinkId}`,
          source: nodeId,
          target: thinkId,
          style: { stroke: '#b388ff', strokeDasharray: '3 3' },
        });
      }

      prevNodeId = nodeId;
    }
  }

  return { nodes, edges, firstNodeId, lastNodeId: prevNodeId };
}

// ---------------------------------------------------------------------------
// Build multi-message graph: connect last node of loop N to first of N+1
// ---------------------------------------------------------------------------

function buildMultiLoopGraph(loops: AgentLoop[], eventDetail: 'nodes' | 'events'): { nodes: Node[]; edges: Edge[]; totalNodes: number; allNodeIds: string[] } {
  const allNodes: Node[] = [];
  const allEdges: Edge[] = [];
  let prevLastNodeId: string | null = null;
  const isMulti = loops.length > 1;

  for (let i = 0; i < loops.length; i++) {
    const loop = loops[i];
    const prefix = `loop${i}-`;
    const { nodes, edges, firstNodeId, lastNodeId } = buildLoopGraph(
      loop,
      prefix,
      isMulti ? i : null,
      eventDetail,
    );

    allNodes.push(...nodes);
    allEdges.push(...edges);

    // Connect previous loop's last node to this loop's first node
    if (prevLastNodeId && firstNodeId) {
      allEdges.push({
        id: `e-cross-${prevLastNodeId}-${firstNodeId}`,
        source: prevLastNodeId,
        target: firstNodeId,
        animated: false,
        style: { stroke: '#58a6ff', strokeDasharray: '6 3', strokeWidth: 2 },
        label: `msg ${i + 1}`,
        labelStyle: { fill: '#58a6ff', fontSize: 10 },
      });
    }

    prevLastNodeId = lastNodeId;
  }

  // Mark the last node as "active" with a cyan highlight
  if (prevLastNodeId) {
    const lastNode = allNodes.find((n) => n.id === prevLastNodeId);
    if (lastNode && lastNode.style) {
      (lastNode.style as Record<string, unknown>).border = '3px solid #58a6ff';
      (lastNode.style as Record<string, unknown>).boxShadow = '0 0 12px rgba(88, 166, 255, 0.5)';
    }
  }

  return {
    nodes: allNodes,
    edges: allEdges,
    totalNodes: allNodes.length,
    allNodeIds: allNodes.map((n) => n.id),
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface StepGraphViewProps {
  /** Primary loop (backward-compatible). */
  loop: AgentLoop;
  /** All loops in the session for multi-message mode. */
  allLoops?: AgentLoop[];
  /** Event detail level: 'types' shows node categories, 'subtypes' shows individual events. */
  eventDetail?: 'nodes' | 'events';
}

export const StepGraphView: React.FC<StepGraphViewProps> = React.memo(({ loop, allLoops, eventDetail = 'nodes' }) => {
  const loops = useMemo(() => allLoops || [loop], [allLoops, loop]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Clear selection when mode changes (node IDs change between categories/event_types)
  useEffect(() => { setSelectedNodeId(null); }, [eventDetail]);

  const { nodes, edges, totalNodes, allNodeIds } = useMemo(() => {
    const raw = buildMultiLoopGraph(loops, eventDetail);
    const layout = applyDagreLayout(raw.nodes, raw.edges);
    return { ...layout, totalNodes: raw.totalNodes, allNodeIds: raw.allNodeIds };
  }, [loops, eventDetail]);

  const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    setSelectedNodeId(node.id);
  }, []);

  if (loops.every((l) => l.steps.length === 0)) {
    return (
      <div
        data-testid="step-graph-empty"
        style={{
          padding: 20,
          textAlign: 'center',
          color: 'var(--pf-v5-global--Color--200)',
          fontSize: '0.88em',
        }}
      >
        Waiting for agent events...
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      data-testid="step-graph-view"
      style={{
        height: '100%',
        minHeight: Math.min(Math.max(400, totalNodes * 80 + 100), 1200),
        backgroundColor: '#0d1117',
        position: 'relative',
      }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        onNodeClick={onNodeClick}
        panOnDrag
        zoomOnScroll
      >
        <Background color="#333" gap={16} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(node) => {
            const bg = node.style?.background;
            return typeof bg === 'string' ? bg : '#555';
          }}
          maskColor="rgba(0,0,0,0.7)"
        />
      </ReactFlow>

      {/* Detail panel -- slides in from right on node click */}
      {selectedNodeId && (
        <GraphDetailPanel
          loop={loop}
          nodeId={selectedNodeId}
          onClose={() => setSelectedNodeId(null)}
          siblingNodeIds={allNodeIds}
          onNavigate={setSelectedNodeId}
        />
      )}
    </div>
  );
});
StepGraphView.displayName = 'StepGraphView';
