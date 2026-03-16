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
import { EVENT_CATALOG } from '../utils/loopBuilder';
import { GraphDetailPanel } from './GraphDetailPanel';

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
// Category / event type badge colors
// ---------------------------------------------------------------------------

const CATEGORY_BADGE_COLORS: Record<string, string> = {
  reasoning:   '#58a6ff',
  execution:   '#4caf50',
  tool_output: '#888',
  decision:    '#ff9800',
  terminal:    '#ce93d8',
  meta:        '#78909c',
  interaction: '#a1887f',
};

/**
 * Static mapping from topology node name to its PRIMARY category.
 * Used in 'nodes' mode to color-code nodes by role.
 */
const TOPO_NODE_CATEGORY: Record<string, string> = {
  router:          'decision',
  planner:         'reasoning',
  planner_tools:   'execution',
  step_selector:   'decision',
  executor:        'reasoning',
  tools:           'execution',
  reflector:       'decision',
  reflector_tools: 'execution',
  reflector_route: 'decision',
  reporter:        'terminal',
};

/** Category-based node colors for the topology view (categories mode). */
const CATEGORY_NODE_COLORS: Record<string, { bg: string; border: string }> = {
  reasoning:   { bg: '#0d3868', border: '#58a6ff' },
  execution:   { bg: '#1b4332', border: '#4caf50' },
  tool_output: { bg: '#1a1a2e', border: '#888' },
  decision:    { bg: '#4a2800', border: '#ff9800' },
  terminal:    { bg: '#3a1050', border: '#ce93d8' },
  meta:        { bg: '#263238', border: '#78909c' },
  interaction: { bg: '#3e2723', border: '#a1887f' },
};

/**
 * Build a default event catalog from EVENT_CATALOG (loopBuilder) + topology,
 * mapping event types to the topology nodes they belong to via stepToTopoNode.
 * This is used when no graphCard is provided.
 */
function buildDefaultEventNodeMap(): Record<string, string[]> {
  // event type -> topology nodes (derived from the stepToTopoNode mapping)
  return {
    planner_output:     ['planner'],
    replanner_output:   ['planner'],
    executor_step:      ['step_selector', 'executor'],
    thinking:           ['executor'],
    micro_reasoning:    ['executor'],
    tool_call:          ['tools', 'planner_tools', 'reflector_tools'],
    tool_result:        ['tools', 'planner_tools', 'reflector_tools'],
    reflector_decision: ['reflector', 'reflector_route'],
    router:             ['router'],
    step_selector:      ['step_selector'],
    reporter_output:    ['reporter'],
    budget:             [],
    budget_update:      [],
  };
}

/**
 * Count event types per topology node from loops.
 * Returns a map: topoNodeId -> { eventType: count }
 */
function countEventsPerTopoNode(
  loops: AgentLoop[],
): Map<string, Map<string, number>> {
  const result = new Map<string, Map<string, number>>();

  for (const loop of loops) {
    for (const step of loop.steps) {
      const topoNode = stepToTopoNode(step);
      if (!topoNode) continue;
      const eventType = step.eventType || step.nodeType || 'unknown';
      if (!result.has(topoNode)) result.set(topoNode, new Map());
      const nodeMap = result.get(topoNode)!;
      nodeMap.set(eventType, (nodeMap.get(eventType) || 0) + 1);
    }
  }

  return result;
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
  eventDetail: 'nodes' | 'events',
  eventCounts: Map<string, Map<string, number>>,
  eventCatalog: Record<string, { category: string; description: string }>,
  eventNodeMap: Record<string, string[]>,
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

  // Pre-compute per-node event info for badges
  // For 'nodes' mode: collect unique categories for each topo node, with total event counts
  // For 'events' mode: collect event type names that map to each topo node
  const nodeCategoryInfo = new Map<string, { category: string; count: number }[]>();
  const nodeEventTypeInfo = new Map<string, string[]>();

  if (eventDetail === 'nodes') {
    // Aggregate observed event types into categories per topology node
    for (const [topoNodeId, evtMap] of eventCounts) {
      const catCounts = new Map<string, number>();
      for (const [evtType, count] of evtMap) {
        const def = eventCatalog[evtType];
        const cat = def?.category || 'meta';
        catCounts.set(cat, (catCounts.get(cat) || 0) + count);
      }
      nodeCategoryInfo.set(
        topoNodeId,
        [...catCounts.entries()]
          .map(([category, count]) => ({ category, count }))
          .sort((a, b) => b.count - a.count),
      );
    }
  } else {
    // Map event types to topology nodes using eventNodeMap
    for (const [evtType, topoNodes] of Object.entries(eventNodeMap)) {
      for (const topoNode of topoNodes) {
        if (!nodeEventTypeInfo.has(topoNode)) nodeEventTypeInfo.set(topoNode, []);
        const list = nodeEventTypeInfo.get(topoNode)!;
        if (!list.includes(evtType)) list.push(evtType);
      }
    }
  }

  // Add topology nodes
  for (const [nodeId, nodeDef] of Object.entries(topology.nodes)) {
    const isActive = nodeId === activeNode;

    // In categories mode: color-code by primary category
    // In event_types mode: use default topology node colors
    let colors: { bg: string; border: string };
    let badgeContent: React.ReactNode = null;

    if (eventDetail === 'nodes') {
      const primaryCat = TOPO_NODE_CATEGORY[nodeId];
      colors = primaryCat ? (CATEGORY_NODE_COLORS[primaryCat] || getNodeColors(nodeId)) : getNodeColors(nodeId);

      // Show category badge with count
      const cats = nodeCategoryInfo.get(nodeId);
      if (cats && cats.length > 0) {
        badgeContent = (
          <div style={{ display: 'flex', gap: 3, justifyContent: 'center', flexWrap: 'wrap', marginTop: 3 }}>
            {cats.map((c) => (
              <span
                key={c.category}
                style={{
                  fontSize: 9,
                  padding: '1px 5px',
                  borderRadius: 8,
                  backgroundColor: CATEGORY_BADGE_COLORS[c.category] || '#555',
                  color: '#fff',
                  fontWeight: 600,
                  lineHeight: '14px',
                }}
              >
                {c.category} {c.count}
              </span>
            ))}
          </div>
        );
      } else if (primaryCat) {
        // No observed events yet, still show the category label
        badgeContent = (
          <div style={{ marginTop: 3, fontSize: 9, color: CATEGORY_BADGE_COLORS[primaryCat] || '#888', fontWeight: 600, textTransform: 'uppercase' as const }}>
            {primaryCat}
          </div>
        );
      }
    } else {
      // event_types mode: default node colors, show event type labels below description
      colors = getNodeColors(nodeId);
      const evtTypes = nodeEventTypeInfo.get(nodeId);
      if (evtTypes && evtTypes.length > 0) {
        const observed = eventCounts.get(nodeId);
        badgeContent = (
          <div style={{ marginTop: 4, fontSize: 10, color: '#aaa', lineHeight: '16px' }}>
            {evtTypes.map((et) => {
              const count = observed?.get(et) || 0;
              return (
                <div key={et} style={{
                  color: count > 0 ? COLOR_ACCENT_BLUE : COLOR_TEXT_TERTIARY,
                  fontWeight: count > 0 ? 600 : 400,
                }}>
                  {et}{count > 0 ? ` (${count})` : ''}
                </div>
              );
            })}
          </div>
        );
      }
    }

    nodes.push({
      id: nodeId,
      data: {
        label: (
          <div style={{ textAlign: 'center', fontSize: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>{nodeId}</div>
            <div style={{ fontSize: 10, opacity: 0.7 }}>{nodeDef.description}</div>
            {badgeContent}
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
        cursor: 'pointer',
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
  eventDetail?: 'nodes' | 'events';
}

export const TopologyGraphView: React.FC<TopologyGraphViewProps> = React.memo(({ loop, allLoops, graphCard, eventDetail = 'nodes' }) => {
  // Stabilize the loops array so downstream useMemo deps don't churn
  // when allLoops is not provided (avoids creating a new [loop] every render).
  const loops = useMemo(() => allLoops || [loop], [allLoops, loop]);
  const topology = graphCard?.topology || DEFAULT_TOPOLOGY;

  const [sidebarOpen, setSidebarOpen] = useState(loops.length > 1);
  const [selectedLoopId, setSelectedLoopId] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
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

  // Count events per topology node from active loops
  const eventCounts = useMemo(
    () => countEventsPerTopoNode(activeLoops),
    [activeLoops],
  );

  // Build event catalog and node map (from graphCard or defaults)
  const eventCatalogMemo = useMemo(() => {
    if (graphCard?.event_catalog) {
      // Convert EventTypeDef to the subset we need
      const catalog: Record<string, { category: string; description: string }> = {};
      for (const [key, def] of Object.entries(graphCard.event_catalog)) {
        catalog[key] = { category: def.category, description: def.description };
      }
      return catalog;
    }
    return EVENT_CATALOG;
  }, [graphCard]);

  const eventNodeMap = useMemo(() => {
    if (graphCard?.event_catalog) {
      const map: Record<string, string[]> = {};
      for (const [evtType, def] of Object.entries(graphCard.event_catalog)) {
        map[evtType] = def.langgraph_nodes;
      }
      return map;
    }
    return buildDefaultEventNodeMap();
  }, [graphCard]);

  // Build the topology graph (dagre layout is the expensive part)
  const { nodes, edges } = useMemo(() => {
    const raw = buildTopologyGraph(topology, activeNode, edgeCounts, eventDetail, eventCounts, eventCatalogMemo, eventNodeMap);
    return applyDagreLayout(raw.nodes, raw.edges);
  }, [topology, activeNode, edgeCounts, eventDetail, eventCounts, eventCatalogMemo, eventNodeMap]);

  // Message sidebar entries
  const messageEntries = useMemo(
    () => buildMessageEntries(loops, selectedLoopId),
    [loops, selectedLoopId],
  );

  const onEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    setHoveredEdge((prev) => (prev === edge.id ? null : edge.id));
  }, []);

  const closeEdgePopup = useCallback(() => setHoveredEdge(null), []);

  const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    // Don't open detail panel for pseudo-nodes
    if (node.id === '__start__' || node.id === '__end__') return;
    setSelectedNodeId(node.id);
  }, []);

  // All topology node IDs for sibling navigation in detail panel
  const topoNodeIds = useMemo(() => Object.keys(topology.nodes), [topology.nodes]);

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
        height: '100%',
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
          {/* Fullscreen button is in the wrapper (GraphLoopView) toggle bar */}
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
          onNodeClick={onNodeClick}
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

        {/* Detail panel for clicked topology node */}
        {selectedNodeId && (
          <GraphDetailPanel
            loop={activeLoops[activeLoops.length - 1] || loop}
            nodeId={selectedNodeId}
            onClose={() => setSelectedNodeId(null)}
            siblingNodeIds={topoNodeIds}
            onNavigate={setSelectedNodeId}
          />
        )}
      </div>
    </div>
  );
});
TopologyGraphView.displayName = 'TopologyGraphView';
