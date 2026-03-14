// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * GraphLoopView — React Flow DAG of an AgentLoop execution flow.
 *
 * Builds a directed acyclic graph from AgentLoop data:
 *   planner -> executor(s) -> reflector -> reporter
 * with tool call nodes branching off executors.
 */

import React, { useMemo, useState, useCallback, useRef } from 'react';
import {
  ReactFlow,
  type Node,
  type Edge,
  Position,
  Background,
  Controls,
  MiniMap,
} from '@xyflow/react';
import dagre from 'dagre';
import type { AgentLoop, AgentLoopStep } from '../types/agentLoop';
import { inferNodeType, type GraphNodeType } from '../utils/loopFormatting';

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
// Build graph from AgentLoop
// ---------------------------------------------------------------------------

function buildGraph(loop: AgentLoop): { nodes: Node[]; edges: Edge[]; totalNodes: number } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  let prevNodeId: string | null = null;

  for (const step of loop.steps) {
    const nt = inferNodeType(step);
    const style = NODE_STYLES[nt];
    const nodeId = `step-${step.index}`;

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
        ...(step.status === 'running' ? { boxShadow: `0 0 8px ${style.border}` } : {}),
      },
    });

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

  return { nodes, edges, totalNodes: nodes.length };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface GraphLoopViewProps {
  loop: AgentLoop;
}

export const GraphLoopView: React.FC<GraphLoopViewProps> = React.memo(({ loop }) => {
  const [fullscreen, setFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const { nodes, edges, totalNodes } = useMemo(() => {
    const raw = buildGraph(loop);
    const layout = applyDagreLayout(raw.nodes, raw.edges);
    return { ...layout, totalNodes: raw.totalNodes };
  }, [loop]);

  const toggleFullscreen = useCallback(() => {
    if (!fullscreen && containerRef.current) {
      containerRef.current.requestFullscreen?.().catch(() => {
        // Fallback: just use CSS fullscreen
        setFullscreen(true);
      });
      setFullscreen(true);
    } else if (document.fullscreenElement) {
      document.exitFullscreen?.();
      setFullscreen(false);
    } else {
      setFullscreen(false);
    }
  }, [fullscreen]);

  // Listen for ESC exiting fullscreen via browser API
  React.useEffect(() => {
    const handler = () => {
      if (!document.fullscreenElement) setFullscreen(false);
    };
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  if (loop.steps.length === 0) {
    return (
      <div
        data-testid="graph-loop-empty"
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
      data-testid="graph-loop-view"
      style={{
        height: fullscreen ? '100vh' : Math.min(Math.max(400, totalNodes * 80 + 100), 1200),
        border: fullscreen ? 'none' : '1px solid var(--pf-v5-global--BorderColor--100)',
        borderRadius: fullscreen ? 0 : 8,
        marginBottom: fullscreen ? 0 : 4,
        backgroundColor: '#0d1117',
        position: 'relative',
      }}
    >
      {/* Fullscreen toggle button */}
      <button
        data-testid="graph-fullscreen-btn"
        title={fullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen graph view'}
        onClick={toggleFullscreen}
        style={{
          position: 'absolute',
          top: 8,
          right: 8,
          zIndex: 10,
          background: 'rgba(30, 30, 50, 0.85)',
          border: '1px solid #555',
          color: '#ccc',
          borderRadius: 4,
          padding: '4px 8px',
          fontSize: 12,
          cursor: 'pointer',
        }}
      >
        {fullscreen ? '\u2716 Exit' : '\u26F6 Fullscreen'}
      </button>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
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
    </div>
  );
});
