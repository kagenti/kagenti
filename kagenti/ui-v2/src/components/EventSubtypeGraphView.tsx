// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * EventSubtypeGraphView — ReactFlow DAG where each node is an event subtype.
 *
 * Builds a directed graph from the actual runtime event sequence:
 *   - 14 event subtypes as nodes (router, planner_output, executor_step, ...)
 *   - Edges represent observed sequential transitions with pass counts
 *   - Nodes colored by category (reasoning, execution, tool, decision, terminal, meta, interaction)
 *   - Active node pulses during streaming (reuses graph-animations.css)
 *
 * Supports "selected message" filtering: when a loop is selected,
 * only that loop's traversal is shown; otherwise all loops are accumulated.
 */

import React, { useMemo, useState, useCallback, useEffect, useRef } from 'react';
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
import { EVENT_CATALOG } from '../utils/loopBuilder';

import '@xyflow/react/dist/style.css';

// ---------------------------------------------------------------------------
// Category color scheme
// ---------------------------------------------------------------------------

type EventCategory = 'reasoning' | 'execution' | 'tool_output' | 'decision' | 'terminal' | 'meta' | 'interaction';

const CATEGORY_COLORS: Record<EventCategory, { bg: string; border: string; text: string }> = {
  reasoning:   { bg: '#0d3868', border: '#3b82f6', text: '#93c5fd' },
  execution:   { bg: '#1b4332', border: '#4caf50', text: '#a7f3d0' },
  tool_output: { bg: '#1a1a2e', border: '#f97316', text: '#fdba74' },
  decision:    { bg: '#4a2800', border: '#eab308', text: '#fde68a' },
  terminal:    { bg: '#3a1050', border: '#a855f7', text: '#d8b4fe' },
  meta:        { bg: '#263238', border: '#78909c', text: '#b0bec5' },
  interaction: { bg: '#3e2723', border: '#26a69a', text: '#80cbc4' },
};

// ---------------------------------------------------------------------------
// Build subtype graph from runtime event sequences
// ---------------------------------------------------------------------------

interface SubtypeGraphData {
  edges: Map<string, Map<string, number>>;   // from -> to -> count
  nodeHits: Map<string, number>;              // eventType -> hit count
}

function buildSubtypeGraph(loops: AgentLoop[]): SubtypeGraphData {
  const edges = new Map<string, Map<string, number>>();
  const nodeHits = new Map<string, number>();

  for (const loop of loops) {
    let prevType: string | null = null;
    for (const step of loop.steps) {
      const eventType = step.eventType || step.nodeType || 'unknown';
      nodeHits.set(eventType, (nodeHits.get(eventType) || 0) + 1);
      if (prevType && prevType !== eventType) {
        if (!edges.has(prevType)) edges.set(prevType, new Map());
        const fromEdges = edges.get(prevType)!;
        fromEdges.set(eventType, (fromEdges.get(eventType) || 0) + 1);
      }
      prevType = eventType;
    }
  }
  return { edges, nodeHits };
}

// ---------------------------------------------------------------------------
// Dagre layout
// ---------------------------------------------------------------------------

function applyDagreLayout(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', nodesep: 50, ranksep: 70 });

  for (const node of nodes) {
    g.setNode(node.id, { width: node.measured?.width ?? 180, height: node.measured?.height ?? 60 });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const layoutNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    const w = node.measured?.width ?? 180;
    const h = node.measured?.height ?? 60;
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
// Build ReactFlow nodes and edges from SubtypeGraphData
// ---------------------------------------------------------------------------

function buildReactFlowGraph(
  data: SubtypeGraphData,
  animActiveNodeId: string | null,
  animVisitedNodes: Set<string>,
  animActiveEdge: { from: string; to: string } | null,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Create nodes for each observed event type
  for (const [eventType, hitCount] of data.nodeHits) {
    const catalogEntry = EVENT_CATALOG[eventType];
    const category = (catalogEntry?.category || 'meta') as EventCategory;
    const colors = CATEGORY_COLORS[category] || CATEGORY_COLORS.meta;
    const description = catalogEntry?.description || '';

    // Animation CSS class
    let className = '';
    if (eventType === animActiveNodeId) {
      className = 'graph-node-active';
    } else if (animVisitedNodes.has(eventType)) {
      className = 'graph-node-visited';
    } else if (animActiveNodeId) {
      className = 'graph-node-inactive';
    }

    nodes.push({
      id: eventType,
      data: {
        label: (
          <div style={{ textAlign: 'center', fontSize: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 2, color: colors.text }}>
              {eventType}
            </div>
            <div style={{ fontSize: 11, fontWeight: 700, color: colors.border }}>
              {hitCount}x
            </div>
            {description && (
              <div style={{ fontSize: 9, opacity: 0.6, marginTop: 2 }}>{description}</div>
            )}
            <div style={{
              fontSize: 8,
              marginTop: 3,
              padding: '1px 6px',
              borderRadius: 8,
              backgroundColor: colors.border,
              color: '#fff',
              display: 'inline-block',
              fontWeight: 600,
              textTransform: 'uppercase' as const,
            }}>
              {category}
            </div>
          </div>
        ),
      },
      position: { x: 0, y: 0 },
      className,
      style: {
        background: colors.bg,
        border: `2px solid ${colors.border}`,
        color: '#e6edf3',
        borderRadius: 8,
        padding: '8px 12px',
        minWidth: 150,
        cursor: 'pointer',
      },
    });
  }

  // Create edges from observed transitions
  for (const [fromType, toMap] of data.edges) {
    for (const [toType, count] of toMap) {
      if (!data.nodeHits.has(fromType) || !data.nodeHits.has(toType)) continue;

      const thickness = Math.min(1 + count * 0.3, 4);

      // Animation CSS class
      let className = '';
      if (animActiveEdge?.from === fromType && animActiveEdge?.to === toType) {
        className = 'graph-edge-active';
      } else if (animVisitedNodes.has(fromType) && (animVisitedNodes.has(toType) || toType === animActiveNodeId)) {
        className = 'graph-edge-visited';
      }

      edges.push({
        id: `evt-${fromType}-${toType}`,
        source: fromType,
        target: toType,
        label: count > 1 ? `${count}x` : undefined,
        labelStyle: { fill: '#8b949e', fontSize: 10 },
        labelBgStyle: { fill: '#0d1117', fillOpacity: 0.8 },
        labelBgPadding: [4, 2] as [number, number],
        className,
        style: {
          stroke: '#58a6ff',
          strokeWidth: thickness,
        },
        animated: count > 5,
      });
    }
  }

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// MiniMap node color callback
// ---------------------------------------------------------------------------

function miniMapNodeColor(node: Node): string {
  const bg = node.style?.background;
  return typeof bg === 'string' ? bg : '#555';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface EventSubtypeGraphViewProps {
  /** All loops in the session. */
  allLoops: AgentLoop[];
  /** Selected loop ID for filtering (null = show all). */
  selectedLoopId: string | null;
}

export const EventSubtypeGraphView: React.FC<EventSubtypeGraphViewProps> = React.memo(
  ({ allLoops, selectedLoopId }) => {
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

    // --- Streaming animation state ---
    const lastProcessedCountRef = useRef(0);
    const [animActiveNodeId, setAnimActiveNodeId] = useState<string | null>(null);
    const [animActiveEdge, setAnimActiveEdge] = useState<{ from: string; to: string } | null>(null);
    const [animVisitedNodes, setAnimVisitedNodes] = useState<Set<string>>(new Set());

    // Reset animation when selectedLoopId changes
    useEffect(() => {
      lastProcessedCountRef.current = 0;
      setAnimActiveNodeId(null);
      setAnimActiveEdge(null);
      setAnimVisitedNodes(new Set());
    }, [selectedLoopId]);

    // Filter loops by selection
    const displayedLoops = useMemo(
      () => selectedLoopId ? allLoops.filter((l) => l.id === selectedLoopId) : allLoops,
      [selectedLoopId, allLoops],
    );

    // Build subtype graph data
    const graphData = useMemo(() => buildSubtypeGraph(displayedLoops), [displayedLoops]);

    // Track streaming progress
    const totalStepCount = useMemo(
      () => displayedLoops.reduce((sum, l) => sum + l.steps.length, 0),
      [displayedLoops],
    );

    useEffect(() => {
      if (totalStepCount <= lastProcessedCountRef.current) return;

      const currentLoop = displayedLoops[displayedLoops.length - 1];
      if (!currentLoop?.steps?.length) return;

      const lastStep = currentLoop.steps[currentLoop.steps.length - 1];
      const newActiveId = lastStep.eventType || lastStep.nodeType || null;

      if (newActiveId && newActiveId !== animActiveNodeId) {
        if (animActiveNodeId) {
          setAnimVisitedNodes((prev) => new Set([...prev, animActiveNodeId]));
          setAnimActiveEdge({ from: animActiveNodeId, to: newActiveId });
        }
        setAnimActiveNodeId(newActiveId);
      }

      lastProcessedCountRef.current = totalStepCount;
    }, [totalStepCount, displayedLoops, animActiveNodeId]);

    // Build and layout the graph
    const { nodes, edges } = useMemo(() => {
      const raw = buildReactFlowGraph(graphData, animActiveNodeId, animVisitedNodes, animActiveEdge);
      if (raw.nodes.length === 0) return { nodes: [], edges: [] };
      return applyDagreLayout(raw.nodes, raw.edges);
    }, [graphData, animActiveNodeId, animVisitedNodes, animActiveEdge]);

    const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
      setSelectedNodeId((prev) => (prev === node.id ? null : node.id));
    }, []);

    // Empty state
    if (displayedLoops.every((l) => l.steps.length === 0) || nodes.length === 0) {
      return (
        <div
          data-testid="event-subtype-graph-empty"
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

    // Selected node detail
    const selectedInfo = selectedNodeId ? {
      eventType: selectedNodeId,
      hits: graphData.nodeHits.get(selectedNodeId) || 0,
      category: (EVENT_CATALOG[selectedNodeId]?.category || 'meta') as EventCategory,
      description: EVENT_CATALOG[selectedNodeId]?.description || '',
      outgoingEdges: [...(graphData.edges.get(selectedNodeId)?.entries() || [])],
      incomingEdges: [...graphData.edges.entries()]
        .flatMap(([from, toMap]) => {
          const count = toMap.get(selectedNodeId);
          return count ? [{ from, count }] : [];
        }),
    } : null;

    return (
      <div
        data-testid="event-subtype-graph-view"
        style={{
          height: '100%',
          minHeight: 400,
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
            nodeColor={miniMapNodeColor}
            maskColor="rgba(0,0,0,0.7)"
          />
        </ReactFlow>

        {/* Node detail popup */}
        {selectedInfo && (
          <div
            data-testid="event-subtype-detail"
            style={{
              position: 'absolute',
              top: 8,
              right: 8,
              zIndex: 20,
              background: '#1a1a2e',
              border: `1px solid ${CATEGORY_COLORS[selectedInfo.category].border}`,
              borderRadius: 6,
              padding: '12px 16px',
              fontSize: 12,
              color: '#ccc',
              maxWidth: 300,
              boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6, color: CATEGORY_COLORS[selectedInfo.category].text }}>
              {selectedInfo.eventType}
            </div>
            <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
              {selectedInfo.description}
            </div>
            <div style={{ marginBottom: 4 }}>
              Hits: <span style={{ color: '#58a6ff', fontWeight: 600 }}>{selectedInfo.hits}</span>
            </div>
            <div style={{ marginBottom: 4 }}>
              Category: <span style={{
                padding: '1px 6px',
                borderRadius: 8,
                backgroundColor: CATEGORY_COLORS[selectedInfo.category].border,
                color: '#fff',
                fontSize: 10,
                fontWeight: 600,
              }}>{selectedInfo.category}</span>
            </div>
            {selectedInfo.outgoingEdges.length > 0 && (
              <div style={{ marginTop: 8, fontSize: 11 }}>
                <div style={{ fontWeight: 600, marginBottom: 2, color: '#aaa' }}>Flows to:</div>
                {selectedInfo.outgoingEdges.map(([to, count]) => (
                  <div key={to} style={{ color: '#8b949e', paddingLeft: 8 }}>
                    {to} ({count}x)
                  </div>
                ))}
              </div>
            )}
            {selectedInfo.incomingEdges.length > 0 && (
              <div style={{ marginTop: 8, fontSize: 11 }}>
                <div style={{ fontWeight: 600, marginBottom: 2, color: '#aaa' }}>Flows from:</div>
                {selectedInfo.incomingEdges.map(({ from, count }) => (
                  <div key={from} style={{ color: '#8b949e', paddingLeft: 8 }}>
                    {from} ({count}x)
                  </div>
                ))}
              </div>
            )}
            <button
              onClick={() => setSelectedNodeId(null)}
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
              X
            </button>
          </div>
        )}
      </div>
    );
  },
);
EventSubtypeGraphView.displayName = 'EventSubtypeGraphView';
