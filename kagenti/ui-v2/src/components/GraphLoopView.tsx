// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * GraphLoopView — React Flow DAG of agent graph topology.
 *
 * Two rendering modes:
 *   1. Single-loop (legacy): renders topology for one AgentLoop
 *   2. Multi-message: renders topology with accumulated edge counts across
 *      all loops, with a collapsible message sidebar on the left.
 *
 * The DAG is built from GraphTopology (graph card) edges, not from the
 * step sequence. Live node highlighting uses the latest step's inferred
 * node type / eventType to determine which topology node is active.
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
import type { AgentLoop } from '../types/agentLoop';
import type { AgentGraphCard, GraphTopology, GraphEdge as TopologyEdge } from '../types/graphCard';
import { countTools, formatTokens, formatDuration } from '../utils/loopFormatting';

import '@xyflow/react/dist/style.css';

// ---------------------------------------------------------------------------
// Default graph card topology (sandbox-legion, used as fallback)
// ---------------------------------------------------------------------------

const DEFAULT_TOPOLOGY: GraphTopology = {
  entry_node: 'router',
  terminal_nodes: ['__end__'],
  nodes: {
    router:          { description: 'Routes to planning or resume' },
    planner:         { description: 'Creates execution plan' },
    planner_tools:   { description: 'Planner tool calls' },
    step_selector:   { description: 'Selects next step' },
    executor:        { description: 'Executes step using tools' },
    tools:           { description: 'Executor tool calls' },
    reflector:       { description: 'Evaluates results' },
    reflector_tools: { description: 'Reflector verification' },
    reflector_route: { description: 'Reflector routing' },
    reporter:        { description: 'Final summary' },
  },
  edges: [
    { from: '__start__',      to: 'router',          condition: null },
    { from: 'router',         to: 'planner',         condition: 'plan' },
    { from: 'router',         to: 'step_selector',   condition: 'resume' },
    { from: 'planner',        to: 'planner_tools',   condition: 'has_tool_calls' },
    { from: 'planner',        to: 'step_selector',   condition: 'no_tool_calls' },
    { from: 'planner_tools',  to: 'planner',         condition: null },
    { from: 'step_selector',  to: 'executor',        condition: null },
    { from: 'executor',       to: 'tools',           condition: 'has_tool_calls' },
    { from: 'executor',       to: 'reflector',       condition: 'no_tool_calls' },
    { from: 'tools',          to: 'executor',        condition: null },
    { from: 'reflector',      to: 'reflector_tools',  condition: 'has_tool_calls' },
    { from: 'reflector',      to: 'reflector_route',  condition: 'no_tool_calls' },
    { from: 'reflector_tools', to: 'reflector',       condition: null },
    { from: 'reflector_route', to: 'step_selector',   condition: 'execute' },
    { from: 'reflector_route', to: 'planner',         condition: 'replan' },
    { from: 'reflector_route', to: 'reporter',        condition: 'done' },
    { from: 'reporter',       to: '__end__',          condition: null },
  ],
};

// ---------------------------------------------------------------------------
// Node color scheme by topology role
// ---------------------------------------------------------------------------

const TOPO_NODE_COLORS: Record<string, { bg: string; border: string }> = {
  __start__:       { bg: '#333',    border: '#555' },
  __end__:         { bg: '#333',    border: '#555' },
  router:          { bg: '#455a64', border: '#37474f' },
  planner:         { bg: '#0066cc', border: '#004999' },
  planner_tools:   { bg: '#1a1a2e', border: '#333' },
  step_selector:   { bg: '#1565c0', border: '#0d47a1' },
  executor:        { bg: '#2e7d32', border: '#1b5e20' },
  tools:           { bg: '#1a1a2e', border: '#333' },
  reflector:       { bg: '#e65100', border: '#bf360c' },
  reflector_tools: { bg: '#1a1a2e', border: '#333' },
  reflector_route: { bg: '#795548', border: '#5d4037' },
  reporter:        { bg: '#7b1fa2', border: '#4a148c' },
};

function getNodeColors(nodeId: string): { bg: string; border: string } {
  return TOPO_NODE_COLORS[nodeId] || { bg: '#37474f', border: '#263238' };
}

// ---------------------------------------------------------------------------
// Map AgentLoop steps to topology node names
// ---------------------------------------------------------------------------

/** Map step eventType/nodeType to the topology node name. */
function stepToTopoNode(step: { eventType?: string; nodeType?: string }): string | null {
  const nt = step.nodeType;
  const et = step.eventType;
  if (et === 'planner_output') return 'planner';
  if (et === 'executor_step') return 'step_selector';
  if (et === 'tool_call' || et === 'tool_result') return 'tools';
  if (et === 'reflector_decision') return 'reflector';
  if (et === 'reporter_output') return 'reporter';
  if (et === 'micro_reasoning') return 'executor';
  if (nt === 'planner' || nt === 'replanner') return 'planner';
  if (nt === 'executor') return 'executor';
  if (nt === 'reflector') return 'reflector';
  if (nt === 'reporter') return 'reporter';
  return null;
}

// ---------------------------------------------------------------------------
// Compute edge traversal counts from loops
// ---------------------------------------------------------------------------

interface EdgeTraversalInfo {
  count: number;
  loopIds: string[];
}

/**
 * For each topology edge, count how many times it was traversed based on
 * the sequence of topology nodes visited across all loops.
 */
function computeEdgeCounts(
  loops: AgentLoop[],
  topoEdges: TopologyEdge[],
): Map<string, EdgeTraversalInfo> {
  const edgeKey = (from: string, to: string) => `${from}->${to}`;
  const counts = new Map<string, EdgeTraversalInfo>();

  // Initialize all edges
  for (const te of topoEdges) {
    counts.set(edgeKey(te.from, te.to), { count: 0, loopIds: [] });
  }

  for (const loop of loops) {
    // Build the sequence of topology nodes visited in this loop
    const nodeSeq: string[] = [];
    for (const step of loop.steps) {
      const topoNode = stepToTopoNode(step);
      if (topoNode && (nodeSeq.length === 0 || nodeSeq[nodeSeq.length - 1] !== topoNode)) {
        nodeSeq.push(topoNode);
      }
    }

    // Prepend __start__ -> first node, append last node -> __end__ (if loop done)
    if (nodeSeq.length > 0) {
      // __start__ -> router is always the first edge
      const startKey = edgeKey('__start__', 'router');
      const startInfo = counts.get(startKey);
      if (startInfo) {
        startInfo.count++;
        startInfo.loopIds.push(loop.id);
      }

      // Count sequential transitions
      for (let i = 0; i < nodeSeq.length - 1; i++) {
        const key = edgeKey(nodeSeq[i], nodeSeq[i + 1]);
        const info = counts.get(key);
        if (info) {
          info.count++;
          if (!info.loopIds.includes(loop.id)) {
            info.loopIds.push(loop.id);
          }
        }
      }

      // If loop is done, add edge to __end__
      if (loop.status === 'done' && loop.finalAnswer) {
        const lastNode = nodeSeq[nodeSeq.length - 1];
        const endKey = edgeKey(lastNode, '__end__');
        const endInfo = counts.get(endKey);
        if (endInfo) {
          endInfo.count++;
          endInfo.loopIds.push(loop.id);
        }
      }
    }
  }

  return counts;
}

// ---------------------------------------------------------------------------
// Determine active (highlighted) topology node
// ---------------------------------------------------------------------------

function getActiveTopoNode(loop: AgentLoop): string | null {
  if (loop.steps.length === 0) return null;
  const lastStep = loop.steps[loop.steps.length - 1];
  if (lastStep.status !== 'running' && loop.status !== 'executing' && loop.status !== 'planning' && loop.status !== 'reflecting') {
    return null; // No active node if loop is done
  }
  return stepToTopoNode(lastStep);
}

// ---------------------------------------------------------------------------
// Dagre layout for topology
// ---------------------------------------------------------------------------

function applyDagreLayout(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', nodesep: 40, ranksep: 60 });

  for (const node of nodes) {
    g.setNode(node.id, { width: node.measured?.width ?? 160, height: node.measured?.height ?? 50 });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const layoutNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    const w = node.measured?.width ?? 160;
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
// Build topology DAG nodes and edges
// ---------------------------------------------------------------------------

function buildTopologyGraph(
  topology: GraphTopology,
  activeNode: string | null,
  edgeCounts: Map<string, EdgeTraversalInfo>,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Add __start__ and __end__ pseudo-nodes
  const pseudoNodes = ['__start__', '__end__'];
  for (const pn of pseudoNodes) {
    const colors = getNodeColors(pn);
    nodes.push({
      id: pn,
      data: {
        label: (
          <div style={{ textAlign: 'center', fontSize: 11, fontStyle: 'italic' }}>
            {pn === '__start__' ? 'START' : 'END'}
          </div>
        ),
      },
      position: { x: 0, y: 0 },
      style: {
        background: colors.bg,
        border: `1px solid ${colors.border}`,
        color: '#999',
        borderRadius: 20,
        padding: '4px 12px',
        minWidth: 60,
      },
    });
  }

  // Add topology nodes
  for (const [nodeId, nodeDef] of Object.entries(topology.nodes)) {
    const colors = getNodeColors(nodeId);
    const isActive = nodeId === activeNode;

    nodes.push({
      id: nodeId,
      data: {
        label: (
          <div style={{ textAlign: 'center', fontSize: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>{nodeId}</div>
            <div style={{ fontSize: 10, opacity: 0.7 }}>{nodeDef.description}</div>
          </div>
        ),
      },
      position: { x: 0, y: 0 },
      style: {
        background: colors.bg,
        border: `2px solid ${isActive ? '#4fc3f7' : colors.border}`,
        color: '#fff',
        borderRadius: 8,
        padding: '8px 12px',
        minWidth: 130,
        ...(isActive ? {
          boxShadow: '0 0 12px rgba(79, 195, 247, 0.6)',
        } : {}),
      },
    });
  }

  // Add topology edges with traversal count labels
  for (const te of topology.edges) {
    const edgeKey = `${te.from}->${te.to}`;
    const traversal = edgeCounts.get(edgeKey);
    const count = traversal?.count || 0;
    const isConditional = te.condition != null;

    let edgeLabel: string | undefined;
    if (count > 0 && te.condition) {
      edgeLabel = `${te.condition} (${count})`;
    } else if (count > 0) {
      edgeLabel = `${count}`;
    } else if (te.condition) {
      edgeLabel = te.condition;
    }

    edges.push({
      id: `e-${te.from}->${te.to}`,
      source: te.from,
      target: te.to,
      animated: count > 0 && te.to === activeNode,
      label: edgeLabel,
      labelStyle: { fill: '#aaa', fontSize: 10 },
      labelBgStyle: { fill: '#0d1117', fillOpacity: 0.8 },
      labelBgPadding: [4, 2] as [number, number],
      style: {
        stroke: count > 0 ? '#58a6ff' : '#444',
        strokeWidth: count > 0 ? Math.min(1 + count * 0.3, 4) : 1,
        ...(isConditional && count === 0 ? { strokeDasharray: '4 4' } : {}),
      },
    });
  }

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Message sidebar entry
// ---------------------------------------------------------------------------

interface MessageEntry {
  loopId: string;
  userMessage: string;
  status: string;
  stepProgress: string;
  toolCount: number;
  tokens: string;
  duration: string;
  isActive: boolean;
}

function buildMessageEntries(loops: AgentLoop[], selectedLoopId: string | null): MessageEntry[] {
  return loops.map((loop) => {
    const stepStr = loop.status === 'done' || loop.status === 'failed'
      ? `${loop.totalSteps} steps`
      : `step ${loop.currentStep + 1}/${loop.totalSteps || '?'}`;

    return {
      loopId: loop.id,
      userMessage: loop.userMessage || loop.id.substring(0, 8),
      status: loop.status,
      stepProgress: stepStr,
      toolCount: countTools(loop),
      tokens: formatTokens(loop),
      duration: formatDuration(loop.budget.wallClockS),
      isActive: selectedLoopId === loop.id || (selectedLoopId === null && loop === loops[loops.length - 1]),
    };
  });
}

function statusIcon(status: string): string {
  switch (status) {
    case 'done':      return '\u2713';
    case 'failed':    return '\u2717';
    case 'canceled':  return '\u2718';
    default:          return '\u25b6';
  }
}

function statusColor(status: string): string {
  switch (status) {
    case 'done':      return '#4caf50';
    case 'failed':    return '#f44336';
    case 'canceled':  return '#ff9800';
    default:          return '#58a6ff';
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface GraphLoopViewProps {
  /** Single loop (backward-compatible with existing usage). */
  loop: AgentLoop;
  /** Optional: all loops in the session for multi-message mode. */
  allLoops?: AgentLoop[];
  /** Optional: graph card data for topology. Falls back to default sandbox-legion topology. */
  graphCard?: AgentGraphCard;
}

export const GraphLoopView: React.FC<GraphLoopViewProps> = React.memo(({ loop, allLoops, graphCard }) => {
  const loops = allLoops || [loop];
  const topology = graphCard?.topology || DEFAULT_TOPOLOGY;

  const [fullscreen, setFullscreen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(loops.length > 1);
  const [selectedLoopId, setSelectedLoopId] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Determine which loop(s) contribute to the graph
  const activeLoops = selectedLoopId
    ? loops.filter((l) => l.id === selectedLoopId)
    : loops;

  // Compute edge traversal counts
  const edgeCounts = useMemo(
    () => computeEdgeCounts(activeLoops, topology.edges),
    [activeLoops, topology.edges],
  );

  // Determine the active (highlighted) topology node from the latest active loop
  const activeNode = useMemo(() => {
    const latest = activeLoops[activeLoops.length - 1];
    return latest ? getActiveTopoNode(latest) : null;
  }, [activeLoops]);

  // Build the topology graph
  const { nodes, edges } = useMemo(() => {
    const raw = buildTopologyGraph(topology, activeNode, edgeCounts);
    return applyDagreLayout(raw.nodes, raw.edges);
  }, [topology, activeNode, edgeCounts]);

  // Message sidebar entries
  const messageEntries = useMemo(
    () => buildMessageEntries(loops, selectedLoopId),
    [loops, selectedLoopId],
  );

  const onNodeClick: NodeMouseHandler = useCallback((_event, _node) => {
    // Future: could show node detail panel. For now, no-op.
  }, []);

  const onEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    setHoveredEdge((prev) => (prev === edge.id ? null : edge.id));
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (!fullscreen && containerRef.current) {
      containerRef.current.requestFullscreen?.().catch(() => {
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

  // Show "waiting" when all loops are empty
  const allEmpty = loops.every((l) => l.steps.length === 0);
  if (allEmpty) {
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

  // Edge popup detail
  const hoveredEdgeInfo = hoveredEdge ? (() => {
    // Edge ID format: "e-{from}->{to}"
    const withoutPrefix = hoveredEdge.substring(2); // remove "e-"
    const arrowIdx = withoutPrefix.indexOf('->');
    if (arrowIdx < 0) return null;
    const from = withoutPrefix.substring(0, arrowIdx);
    const to = withoutPrefix.substring(arrowIdx + 2);
    const te = topology.edges.find((e) => e.from === from && e.to === to);
    const key = `${from}->${to}`;
    const info = edgeCounts.get(key);
    if (!te || !info) return null;
    return { from, to, condition: te.condition, description: te.description, count: info.count, loopIds: info.loopIds };
  })() : null;

  const sidebarWidth = 260;

  return (
    <div
      ref={containerRef}
      data-testid="graph-loop-view"
      style={{
        height: fullscreen ? '100vh' : 600,
        border: fullscreen ? 'none' : '1px solid var(--pf-v5-global--BorderColor--100)',
        borderRadius: fullscreen ? 0 : 8,
        marginBottom: fullscreen ? 0 : 4,
        backgroundColor: '#0d1117',
        position: 'relative',
        display: 'flex',
      }}
    >
      {/* Message sidebar (left) — only in multi-message mode */}
      {loops.length > 1 && (
        <div
          data-testid="graph-message-sidebar"
          style={{
            width: sidebarOpen ? sidebarWidth : 0,
            minWidth: sidebarOpen ? sidebarWidth : 0,
            overflow: 'hidden',
            transition: 'width 0.2s, min-width 0.2s',
            borderRight: sidebarOpen ? '1px solid #333' : 'none',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
          }}
        >
          {/* Sidebar header */}
          <div style={{
            padding: '8px 10px',
            borderBottom: '1px solid #333',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexShrink: 0,
          }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: '#ccc' }}>
              Messages ({loops.length})
            </span>
            <button
              onClick={() => setSelectedLoopId(null)}
              title="Show all messages"
              style={{
                background: selectedLoopId === null ? '#1a3a5c' : 'none',
                border: '1px solid #555',
                color: '#ccc',
                borderRadius: 3,
                padding: '2px 6px',
                fontSize: 10,
                cursor: 'pointer',
              }}
            >
              All
            </button>
          </div>

          {/* Message list */}
          <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
            {messageEntries.map((entry, idx) => (
              <div
                key={entry.loopId}
                data-testid={`graph-msg-entry-${idx}`}
                onClick={() => setSelectedLoopId(entry.isActive && selectedLoopId !== null ? null : entry.loopId)}
                style={{
                  padding: '8px 10px',
                  cursor: 'pointer',
                  backgroundColor: entry.isActive ? 'rgba(88, 166, 255, 0.1)' : 'transparent',
                  borderLeft: entry.isActive ? '3px solid #58a6ff' : '3px solid transparent',
                  transition: 'background-color 0.15s',
                }}
              >
                {/* User prompt summary */}
                <div style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: '#ccc',
                  marginBottom: 4,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {idx + 1}. {entry.userMessage.length > 35
                    ? entry.userMessage.substring(0, 35) + '...'
                    : entry.userMessage}
                </div>
                {/* Status line */}
                <div style={{ fontSize: 11, color: '#888', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ color: statusColor(entry.status) }}>{statusIcon(entry.status)}</span>
                  <span>{entry.stepProgress}</span>
                  <span>{entry.toolCount} tools</span>
                  <span>{entry.tokens} tok</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Main graph area */}
      <div style={{ flex: 1, position: 'relative' }}>
        {/* Toolbar: sidebar toggle + fullscreen */}
        <div style={{
          position: 'absolute',
          top: 8,
          right: 8,
          zIndex: 10,
          display: 'flex',
          gap: 4,
        }}>
          {loops.length > 1 && (
            <button
              data-testid="graph-sidebar-toggle"
              title={sidebarOpen ? 'Hide message sidebar' : 'Show message sidebar'}
              onClick={() => setSidebarOpen((p) => !p)}
              style={{
                background: 'rgba(30, 30, 50, 0.85)',
                border: '1px solid #555',
                color: '#ccc',
                borderRadius: 4,
                padding: '4px 8px',
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              {sidebarOpen ? '\u25c0 Hide' : '\u25b6 Messages'}
            </button>
          )}
          <button
            data-testid="graph-fullscreen-btn"
            title={fullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen graph view'}
            onClick={toggleFullscreen}
            style={{
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
        </div>

        {/* Active node indicator badge */}
        {activeNode && (
          <div
            data-testid="graph-active-node-badge"
            style={{
              position: 'absolute',
              top: 8,
              left: 8,
              zIndex: 10,
              background: 'rgba(30, 30, 50, 0.9)',
              border: '1px solid #4fc3f7',
              color: '#4fc3f7',
              borderRadius: 4,
              padding: '4px 10px',
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            Active: {activeNode}
          </div>
        )}

        {/* Loop info when viewing specific message */}
        {selectedLoopId && (
          <div
            data-testid="graph-selected-loop-info"
            style={{
              position: 'absolute',
              bottom: 8,
              left: 8,
              zIndex: 10,
              background: 'rgba(30, 30, 50, 0.9)',
              border: '1px solid #555',
              color: '#aaa',
              borderRadius: 4,
              padding: '4px 10px',
              fontSize: 11,
            }}
          >
            Showing: Message {loops.findIndex((l) => l.id === selectedLoopId) + 1} of {loops.length}
          </div>
        )}

        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          onNodeClick={onNodeClick}
          onEdgeClick={onEdgeClick}
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

        {/* Edge detail popup */}
        {hoveredEdgeInfo && hoveredEdgeInfo.count > 0 && (
          <div
            data-testid="graph-edge-popup"
            style={{
              position: 'absolute',
              bottom: 40,
              right: 8,
              zIndex: 20,
              background: '#1a1a2e',
              border: '1px solid #555',
              borderRadius: 6,
              padding: '10px 14px',
              fontSize: 12,
              color: '#ccc',
              maxWidth: 280,
              boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 6 }}>
              {hoveredEdgeInfo.from} → {hoveredEdgeInfo.to}
            </div>
            {hoveredEdgeInfo.condition && (
              <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>
                Condition: {hoveredEdgeInfo.condition}
              </div>
            )}
            {hoveredEdgeInfo.description && (
              <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>
                {hoveredEdgeInfo.description}
              </div>
            )}
            <div style={{ fontSize: 11, marginBottom: 2 }}>
              Traversals: <span style={{ color: '#58a6ff', fontWeight: 600 }}>{hoveredEdgeInfo.count}</span>
            </div>
            {hoveredEdgeInfo.loopIds.length > 0 && (
              <div style={{ fontSize: 10, color: '#666', marginTop: 4 }}>
                Messages: {hoveredEdgeInfo.loopIds.map((id) => {
                  const idx = loops.findIndex((l) => l.id === id);
                  return idx >= 0 ? `#${idx + 1}` : id.substring(0, 6);
                }).join(', ')}
              </div>
            )}
            <button
              onClick={() => setHoveredEdge(null)}
              style={{
                position: 'absolute',
                top: 4,
                right: 6,
                background: 'none',
                border: 'none',
                color: '#666',
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              \u2716
            </button>
          </div>
        )}
      </div>
    </div>
  );
});
