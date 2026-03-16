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

import React, { useMemo, useState, useCallback, useRef } from 'react';
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
): { nodes: Node[]; edges: Edge[]; firstNodeId: string | null; lastNodeId: string | null } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  let prevNodeId: string | null = null;
  let firstNodeId: string | null = null;

  for (const step of loop.steps) {
    const nt = inferNodeType(step);
    const style = NODE_STYLES[nt];
    const nodeId = `${prefix}step-${step.index}`;

    let label: string = nt;
    if (nt === 'executor' && step.planStep != null) {
      label = `Step ${step.planStep + 1}`;
    } else if (nt === 'reflector') {
      label = `Reflector: ${loop.reflectorDecision || ''}`;
    } else if (nt === 'reporter') {
      label = 'Reporter';
    } else if (nt === 'planner' || nt === 'replanner') {
      label = `${nt} (${loop.plan.length} steps)`;
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

  return { nodes, edges, firstNodeId, lastNodeId: prevNodeId };
}

// ---------------------------------------------------------------------------
// Build multi-message graph: connect last node of loop N to first of N+1
// ---------------------------------------------------------------------------

function buildMultiLoopGraph(loops: AgentLoop[]): { nodes: Node[]; edges: Edge[]; totalNodes: number; allNodeIds: string[] } {
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
  eventDetail?: 'types' | 'subtypes';
}

export const StepGraphView: React.FC<StepGraphViewProps> = React.memo(({ loop, allLoops }) => {
  const loops = useMemo(() => allLoops || [loop], [allLoops, loop]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const { nodes, edges, totalNodes, allNodeIds } = useMemo(() => {
    const raw = buildMultiLoopGraph(loops);
    const layout = applyDagreLayout(raw.nodes, raw.edges);
    return { ...layout, totalNodes: raw.totalNodes, allNodeIds: raw.allNodeIds };
  }, [loops]);

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
        height: Math.min(Math.max(400, totalNodes * 80 + 100), 1200),
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
