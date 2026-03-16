// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * TopologyGraphView — React Flow DAG of agent graph topology.
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
// Design tokens / constants
// ---------------------------------------------------------------------------

/** Graph canvas background. */
const COLOR_BG_CANVAS = '#0d1117';
/** Muted text color. */
const COLOR_TEXT_MUTED = '#888';
/** Secondary text color. */
const COLOR_TEXT_SECONDARY = '#ccc';
/** Faint text / tertiary. */
const COLOR_TEXT_TERTIARY = '#666';
/** Label text color on edges. */
const COLOR_LABEL_TEXT = '#aaa';
/** Accent blue for traversed edges, active sidebar entries, etc. */
const COLOR_ACCENT_BLUE = '#58a6ff';
/** Highlight blue for active node glow. */
const COLOR_HIGHLIGHT_BLUE = '#4fc3f7';
/** Border / divider color. */
const COLOR_BORDER = '#555';
/** Dark border / divider. */
const COLOR_BORDER_DARK = '#333';
/** Overlay background for popups, badges, toolbar buttons. */
const COLOR_OVERLAY_BG = 'rgba(30, 30, 50, 0.85)';
/** Popup panel background. */
const COLOR_PANEL_BG = '#1a1a2e';
/** Status green. */
const COLOR_STATUS_OK = '#4caf50';
/** Status red. */
const COLOR_STATUS_FAIL = '#f44336';
/** Status amber. */
const COLOR_STATUS_WARN = '#ff9800';

/** Default fallback for untraversed edges. */
const COLOR_EDGE_INACTIVE = '#444';

/** Sidebar width in pixels. */
const SIDEBAR_WIDTH = 260;
/** Default node width for dagre layout. */
const NODE_WIDTH = 160;
/** Default node height for dagre layout. */
const NODE_HEIGHT = 50;
/** Max edge stroke width. */
const EDGE_STROKE_MAX = 4;
/** Per-traversal stroke growth. */
const EDGE_STROKE_STEP = 0.3;
/** Max characters shown for user message in sidebar. */
const MSG_TRUNCATE = 35;

// Shared inline style for toolbar buttons (sidebar toggle + fullscreen).
const TOOLBAR_BTN_STYLE: React.CSSProperties = {
  background: COLOR_OVERLAY_BG,
  border: `1px solid ${COLOR_BORDER}`,
  color: COLOR_TEXT_SECONDARY,
  borderRadius: 4,
  padding: '4px 8px',
  fontSize: 12,
  cursor: 'pointer',
};

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
    { from: '__start__',      to: 'router',          condition: null, description: 'Entry' },
    { from: 'router',         to: 'planner',         condition: 'plan', description: 'New session' },
    { from: 'router',         to: 'step_selector',   condition: 'resume', description: 'Resume plan' },
    { from: 'planner',        to: 'planner_tools',   condition: 'has_tool_calls', description: 'Read context' },
    { from: 'planner',        to: 'step_selector',   condition: 'no_tool_calls', description: 'Plan ready' },
    { from: 'planner_tools',  to: 'planner',         condition: null, description: 'Return results' },
    { from: 'step_selector',  to: 'executor',        condition: null, description: 'Execute step' },
    { from: 'executor',       to: 'tools',           condition: 'has_tool_calls', description: 'Run tools' },
    { from: 'executor',       to: 'reflector',       condition: 'no_tool_calls', description: 'Step done' },
    { from: 'tools',          to: 'executor',        condition: null, description: 'Return results' },
    { from: 'reflector',      to: 'reflector_tools',  condition: 'has_tool_calls', description: 'Verify' },
    { from: 'reflector',      to: 'reflector_route',  condition: 'no_tool_calls', description: 'Decide' },
    { from: 'reflector_tools', to: 'reflector',       condition: null, description: 'Return results' },
    { from: 'reflector_route', to: 'step_selector',   condition: 'execute', description: 'Continue' },
    { from: 'reflector_route', to: 'planner',         condition: 'replan', description: 'Replan' },
    { from: 'reflector_route', to: 'reporter',        condition: 'done', description: 'All done' },
    { from: 'reporter',       to: '__end__',          condition: null, description: 'Report' },
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

const DEFAULT_NODE_COLORS = { bg: '#37474f', border: '#263238' };

function getNodeColors(nodeId: string): { bg: string; border: string } {
  return TOPO_NODE_COLORS[nodeId] || DEFAULT_NODE_COLORS;
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
    g.setNode(node.id, { width: node.measured?.width ?? NODE_WIDTH, height: node.measured?.height ?? NODE_HEIGHT });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const layoutNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    const w = node.measured?.width ?? NODE_WIDTH;
    const h = node.measured?.height ?? NODE_HEIGHT;
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
        border: `2px solid ${isActive ? COLOR_HIGHLIGHT_BLUE : colors.border}`,
        color: '#fff',
        borderRadius: 8,
        padding: '8px 12px',
        minWidth: 130,
        ...(isActive ? {
          boxShadow: `0 0 12px rgba(79, 195, 247, 0.6)`,
        } : {}),
      },
    });
  }

  // Add topology edges with traversal count labels
  for (const te of topology.edges) {
    const edgeKey = `${te.from}->${te.to}`;
    const traversal = edgeCounts.get(edgeKey);
    const count = traversal?.count || 0;

    // Show description (from graph card) with count, fall back to condition
    const desc = (te as { description?: string }).description;
    let edgeLabel: string | undefined;
    if (count > 0 && desc) {
      edgeLabel = `${desc} (${count})`;
    } else if (count > 0) {
      edgeLabel = `${count}x`;
    } else if (desc) {
      edgeLabel = desc;
    } else if (te.condition) {
      edgeLabel = te.condition;
    }

    edges.push({
      id: `e-${te.from}->${te.to}`,
      source: te.from,
      target: te.to,
      animated: count > 0 && te.to === activeNode,
      label: edgeLabel,
      labelStyle: { fill: COLOR_LABEL_TEXT, fontSize: 10 },
      labelBgStyle: { fill: COLOR_BG_CANVAS, fillOpacity: 0.8 },
      labelBgPadding: [4, 2] as [number, number],
      style: {
        stroke: count > 0 ? COLOR_ACCENT_BLUE : COLOR_EDGE_INACTIVE,
        strokeWidth: count > 0 ? Math.min(1 + count * EDGE_STROKE_STEP, EDGE_STROKE_MAX) : 1,
        ...(te.condition != null && count === 0 ? { strokeDasharray: '4 4' } : {}),
      },
    });
  }

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Message sidebar helpers
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
    case 'done':      return COLOR_STATUS_OK;
    case 'failed':    return COLOR_STATUS_FAIL;
    case 'canceled':  return COLOR_STATUS_WARN;
    default:          return COLOR_ACCENT_BLUE;
  }
}

// ---------------------------------------------------------------------------
// Extracted sub-components
// ---------------------------------------------------------------------------

interface MessageSidebarProps {
  loops: AgentLoop[];
  messageEntries: MessageEntry[];
  selectedLoopId: string | null;
  setSelectedLoopId: (id: string | null) => void;
}

/** Collapsible message list shown on the left in multi-message mode. */
const MessageSidebar: React.FC<MessageSidebarProps> = React.memo(
  ({ loops, messageEntries, selectedLoopId, setSelectedLoopId }) => (
    <>
      {/* Sidebar header */}
      <div style={{
        padding: '8px 10px',
        borderBottom: `1px solid ${COLOR_BORDER_DARK}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: COLOR_TEXT_SECONDARY }}>
          Messages ({loops.length})
        </span>
        <button
          onClick={() => setSelectedLoopId(null)}
          title="Show all messages"
          style={{
            background: selectedLoopId === null ? '#1a3a5c' : 'none',
            border: `1px solid ${COLOR_BORDER}`,
            color: COLOR_TEXT_SECONDARY,
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
              borderLeft: entry.isActive ? `3px solid ${COLOR_ACCENT_BLUE}` : '3px solid transparent',
              transition: 'background-color 0.15s',
            }}
          >
            {/* User prompt summary */}
            <div style={{
              fontSize: 12,
              fontWeight: 500,
              color: COLOR_TEXT_SECONDARY,
              marginBottom: 4,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {idx + 1}. {entry.userMessage.length > MSG_TRUNCATE
                ? entry.userMessage.substring(0, MSG_TRUNCATE) + '...'
                : entry.userMessage}
            </div>
            {/* Status line */}
            <div style={{ fontSize: 11, color: COLOR_TEXT_MUTED, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: statusColor(entry.status) }}>{statusIcon(entry.status)}</span>
              <span>{entry.stepProgress}</span>
              <span>{entry.toolCount} tools</span>
              <span>{entry.tokens} tok</span>
            </div>
          </div>
        ))}
      </div>
    </>
  ),
);
MessageSidebar.displayName = 'MessageSidebar';

// ---------------------------------------------------------------------------

interface EdgeDetailInfo {
  from: string;
  to: string;
  condition: string | null;
  description?: string;
  count: number;
  loopIds: string[];
}

interface EdgeDetailPopupProps {
  info: EdgeDetailInfo;
  loops: AgentLoop[];
  onClose: () => void;
}

/** Popup showing traversal details for a clicked edge. */
const EdgeDetailPopup: React.FC<EdgeDetailPopupProps> = React.memo(({ info, loops, onClose }) => (
  <div
    data-testid="graph-edge-popup"
    style={{
      position: 'absolute',
      bottom: 40,
      right: 8,
      zIndex: 20,
      background: COLOR_PANEL_BG,
      border: `1px solid ${COLOR_BORDER}`,
      borderRadius: 6,
      padding: '10px 14px',
      fontSize: 12,
      color: COLOR_TEXT_SECONDARY,
      maxWidth: 280,
      boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
    }}
  >
    <div style={{ fontWeight: 600, marginBottom: 6 }}>
      {info.from} → {info.to}
    </div>
    {info.condition && (
      <div style={{ fontSize: 11, color: COLOR_TEXT_MUTED, marginBottom: 4 }}>
        Condition: {info.condition}
      </div>
    )}
    {info.description && (
      <div style={{ fontSize: 11, color: COLOR_TEXT_MUTED, marginBottom: 4 }}>
        {info.description}
      </div>
    )}
    <div style={{ fontSize: 11, marginBottom: 2 }}>
      Traversals: <span style={{ color: COLOR_ACCENT_BLUE, fontWeight: 600 }}>{info.count}</span>
    </div>
    {info.loopIds.length > 0 && (
      <div style={{ fontSize: 10, color: COLOR_TEXT_TERTIARY, marginTop: 4 }}>
        Messages: {info.loopIds.map((id) => {
          const idx = loops.findIndex((l) => l.id === id);
          return idx >= 0 ? `#${idx + 1}` : id.substring(0, 6);
        }).join(', ')}
      </div>
    )}
    <button
      onClick={onClose}
      style={{
        position: 'absolute',
        top: 4,
        right: 6,
        background: 'none',
        border: 'none',
        color: COLOR_TEXT_TERTIARY,
        cursor: 'pointer',
        fontSize: 12,
      }}
    >
      {'\u2716'}
    </button>
  </div>
));
EdgeDetailPopup.displayName = 'EdgeDetailPopup';

// ---------------------------------------------------------------------------
// MiniMap node color callback (stable reference)
// ---------------------------------------------------------------------------

function miniMapNodeColor(node: Node): string {
  const bg = node.style?.background;
  return typeof bg === 'string' ? bg : '#555';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface TopologyGraphViewProps {
  /** Single loop (backward-compatible with existing usage). */
  loop: AgentLoop;
  /** Optional: all loops in the session for multi-message mode. */
  allLoops?: AgentLoop[];
  /** Optional: graph card data for topology. Falls back to default sandbox-legion topology. */
  graphCard?: AgentGraphCard;
  /** Event detail level: 'types' shows node categories, 'subtypes' shows individual events. */
  eventDetail?: 'types' | 'subtypes';
}

export const TopologyGraphView: React.FC<TopologyGraphViewProps> = React.memo(({ loop, allLoops, graphCard }) => {
  // Stabilize the loops array so downstream useMemo deps don't churn
  // when allLoops is not provided (avoids creating a new [loop] every render).
  const loops = useMemo(() => allLoops || [loop], [allLoops, loop]);
  const topology = graphCard?.topology || DEFAULT_TOPOLOGY;

  const [sidebarOpen, setSidebarOpen] = useState(loops.length > 1);
  const [selectedLoopId, setSelectedLoopId] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Determine which loop(s) contribute to the graph — memoized to avoid
  // creating a new array reference on every render.
  const activeLoops = useMemo(
    () => (selectedLoopId ? loops.filter((l) => l.id === selectedLoopId) : loops),
    [selectedLoopId, loops],
  );

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

  // Build the topology graph (dagre layout is the expensive part)
  const { nodes, edges } = useMemo(() => {
    const raw = buildTopologyGraph(topology, activeNode, edgeCounts);
    return applyDagreLayout(raw.nodes, raw.edges);
  }, [topology, activeNode, edgeCounts]);

  // Message sidebar entries
  const messageEntries = useMemo(
    () => buildMessageEntries(loops, selectedLoopId),
    [loops, selectedLoopId],
  );

  const onEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    setHoveredEdge((prev) => (prev === edge.id ? null : edge.id));
  }, []);

  const closeEdgePopup = useCallback(() => setHoveredEdge(null), []);

  // Show "waiting" when all loops are empty
  const allEmpty = useMemo(() => loops.every((l) => l.steps.length === 0), [loops]);
  if (allEmpty) {
    return (
      <div
        data-testid="topology-graph-empty"
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

  // Memoize the edge detail info derived from hovered edge ID
  const hoveredEdgeInfo = useMemo<EdgeDetailInfo | null>(() => {
    if (!hoveredEdge) return null;
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
  }, [hoveredEdge, topology.edges, edgeCounts]);

  return (
    <div
      ref={containerRef}
      data-testid="topology-graph-view"
      style={{
        height: 600,
        minHeight: 400,
        backgroundColor: COLOR_BG_CANVAS,
        position: 'relative',
        display: 'flex',
      }}
    >
      {/* Message sidebar (left) — only in multi-message mode */}
      {loops.length > 1 && (
        <div
          data-testid="graph-message-sidebar"
          style={{
            width: sidebarOpen ? SIDEBAR_WIDTH : 0,
            minWidth: sidebarOpen ? SIDEBAR_WIDTH : 0,
            overflow: 'hidden',
            transition: 'width 0.2s, min-width 0.2s',
            borderRight: sidebarOpen ? `1px solid ${COLOR_BORDER_DARK}` : 'none',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
          }}
        >
          <MessageSidebar
            loops={loops}
            messageEntries={messageEntries}
            selectedLoopId={selectedLoopId}
            setSelectedLoopId={setSelectedLoopId}
          />
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
              style={TOOLBAR_BTN_STYLE}
            >
              {sidebarOpen ? '\u25c0 Hide' : '\u25b6 Messages'}
            </button>
          )}
          <button
            data-testid="graph-fullscreen-toggle"
            title="Toggle fullscreen"
            onClick={() => {
              const el = document.querySelector('[data-testid="graph-loop-view"]');
              if (el) {
                if (document.fullscreenElement) {
                  document.exitFullscreen();
                } else {
                  el.requestFullscreen();
                }
              }
            }}
            style={TOOLBAR_BTN_STYLE}
          >
            {'\u26f6'} Fullscreen
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
              border: `1px solid ${COLOR_HIGHLIGHT_BLUE}`,
              color: COLOR_HIGHLIGHT_BLUE,
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
              border: `1px solid ${COLOR_BORDER}`,
              color: COLOR_LABEL_TEXT,
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
          onEdgeClick={onEdgeClick}
          panOnDrag
          zoomOnScroll
        >
          <Background color={COLOR_BORDER_DARK} gap={16} />
          <Controls showInteractive={false} />
          <MiniMap
            nodeColor={miniMapNodeColor}
            maskColor="rgba(0,0,0,0.7)"
          />
        </ReactFlow>

        {/* Edge detail popup */}
        {hoveredEdgeInfo && hoveredEdgeInfo.count > 0 && (
          <EdgeDetailPopup
            info={hoveredEdgeInfo}
            loops={loops}
            onClose={closeEdgePopup}
          />
        )}
      </div>
    </div>
  );
});
TopologyGraphView.displayName = 'TopologyGraphView';
