// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Session Graph DAG Visualization (Session E)
 *
 * Renders a directed acyclic graph of session delegation trees using React Flow.
 * Each node represents a session (root or child), and edges represent delegation
 * relationships with mode-specific styling.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  PageSection,
  Title,
  Spinner,
  Alert,
} from '@patternfly/react-core';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type EdgeProps,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  BaseEdge,
  getBezierPath,
} from '@xyflow/react';
import dagre from 'dagre';
import '@xyflow/react/dist/style.css';

import { sessionGraphService, type GraphNode, type GraphEdge } from '../services/api';

/** Node data shape for React Flow — must be Record<string, unknown> compatible */
type SessionNodeData = GraphNode & Record<string, unknown>;

type SessionNode = Node<SessionNodeData>;
type SessionEdge = Edge<{ mode: string; task: string }>;

// ─── Constants ───────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  running: '#2196F3',   // blue
  completed: '#4CAF50', // green
  failed: '#F44336',    // red
  pending: '#9E9E9E',   // gray
};

const STATUS_LABELS: Record<string, string> = {
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  pending: 'Pending',
};

const MODE_EDGE_STYLES: Record<string, { stroke: string; strokeDasharray?: string; strokeWidth: number }> = {
  'in-process': { stroke: '#666', strokeWidth: 1.5 },
  'shared-pvc': { stroke: '#2980b9', strokeDasharray: '8 4', strokeWidth: 2 },
  isolated: { stroke: '#e67e22', strokeWidth: 3 },
  sidecar: { stroke: '#27ae60', strokeDasharray: '3 3', strokeWidth: 1.5 },
};

const NODE_WIDTH = 240;
const NODE_HEIGHT = 130;

// ─── Layout ──────────────────────────────────────────────────────────────────

function layoutGraph(
  graphNodes: GraphNode[],
  graphEdges: GraphEdge[]
): { nodes: SessionNode[]; edges: SessionEdge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', nodesep: 80, ranksep: 120 });

  graphNodes.forEach((n) => {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  });

  graphEdges.forEach((e) => {
    g.setEdge(e.from, e.to);
  });

  dagre.layout(g);

  const nodes: SessionNode[] = graphNodes.map((n) => {
    const pos = g.node(n.id);
    return {
      id: n.id,
      type: 'sessionNode',
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: { ...n } as SessionNodeData,
    };
  });

  const edges: SessionEdge[] = graphEdges.map((e) => {
    const style = MODE_EDGE_STYLES[e.mode] || MODE_EDGE_STYLES['in-process'];
    return {
      id: `${e.from}-${e.to}`,
      source: e.from,
      target: e.to,
      type: 'delegation',
      label: e.task.length > 40 ? e.task.slice(0, 37) + '...' : e.task,
      style,
      data: { mode: e.mode, task: e.task },
    };
  });

  return { nodes, edges };
}

// ─── Custom Node ─────────────────────────────────────────────────────────────

function SessionNodeComponent({ data }: { data: SessionNodeData }) {
  const node = data;
  const statusColor = STATUS_COLORS[node.status] || STATUS_COLORS.pending;
  const statusLabel = STATUS_LABELS[node.status] || node.status;

  const durationStr = node.duration_ms > 0
    ? node.duration_ms >= 60000
      ? `${Math.round(node.duration_ms / 60000)}m`
      : `${Math.round(node.duration_ms / 1000)}s`
    : '';

  return (
    <div
      data-testid={`graph-node-${node.id}`}
      style={{
        background: '#fff',
        border: `2px solid ${statusColor}`,
        borderRadius: 8,
        padding: '10px 14px',
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT - 20,
        fontSize: 12,
        fontFamily: 'var(--pf-v5-global--FontFamily--monospace, monospace)',
        cursor: 'pointer',
      }}
    >
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />

      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>
        {node.agent}
      </div>

      <div style={{ color: '#666', marginBottom: 4 }}>{node.id}</div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span
          data-testid="node-status-badge"
          data-status={node.status}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '2px 8px',
            borderRadius: 10,
            fontSize: 11,
            fontWeight: 500,
            color: '#fff',
            background: statusColor,
          }}
        >
          {statusLabel}
        </span>
        {durationStr && (
          <span style={{ color: '#999', fontSize: 11 }}>{durationStr}</span>
        )}
      </div>

      <div style={{ color: '#555', fontSize: 11 }}>{node.mode}</div>

      {node.task_summary && (
        <div
          style={{
            color: '#333',
            fontSize: 11,
            marginTop: 4,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={node.task_summary}
        >
          {node.task_summary}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  );
}

const nodeTypes = { sessionNode: SessionNodeComponent };

// ─── Custom Edge ─────────────────────────────────────────────────────────────

function DelegationEdgeComponent(props: EdgeProps) {
  const { id, sourceX, sourceY, targetX, targetY, data, style } = props;
  const mode = (data as { mode?: string })?.mode || 'in-process';

  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
  });

  return (
    <g
      data-testid={`graph-edge-${id}`}
      data-mode={mode}
    >
      <BaseEdge path={edgePath} style={style} />
    </g>
  );
}

const edgeTypes = { delegation: DelegationEdgeComponent };

// ─── Legend ──────────────────────────────────────────────────────────────────

function GraphLegend() {
  return (
    <div
      data-testid="graph-legend"
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 16,
        padding: '8px 16px',
        background: '#f8f8f8',
        borderRadius: 6,
        fontSize: 12,
        marginBottom: 12,
      }}
    >
      {/* Status indicators */}
      {Object.entries(STATUS_COLORS).map(([status, color]) => (
        <span key={status} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: color,
              display: 'inline-block',
            }}
          />
          {STATUS_LABELS[status]}
        </span>
      ))}

      <span style={{ borderLeft: '1px solid #ccc', paddingLeft: 16 }} />

      {/* Edge mode styles */}
      {Object.entries(MODE_EDGE_STYLES).map(([mode, style]) => (
        <span key={mode} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <svg width="24" height="12">
            <line
              x1="0"
              y1="6"
              x2="24"
              y2="6"
              stroke={style.stroke}
              strokeWidth={style.strokeWidth}
              strokeDasharray={style.strokeDasharray || 'none'}
            />
          </svg>
          {mode}
        </span>
      ))}
    </div>
  );
}

// ─── Page Component ──────────────────────────────────────────────────────────

export const SessionGraphPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const namespace = searchParams.get('namespace') || 'team1';
  const contextId = searchParams.get('contextId') || searchParams.get('session') || '';

  const [nodes, setNodes, onNodesChange] = useNodesState<SessionNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<SessionEdge>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch graph data
  useEffect(() => {
    if (!contextId) {
      setLoading(false);
      setError('No session context ID provided. Navigate from a session to view its graph.');
      return;
    }

    const fetchGraph = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await sessionGraphService.getGraph(namespace, contextId);
        const layout = layoutGraph(data.nodes, data.edges);
        setNodes(layout.nodes);
        setEdges(layout.edges);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load session graph');
      } finally {
        setLoading(false);
      }
    };

    fetchGraph();
  }, [namespace, contextId, setNodes, setEdges]);

  // Click node to navigate to session chat
  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: SessionNode) => {
      navigate(`/sandbox?session=${node.id}`);
    },
    [navigate]
  );

  // Memoize types to prevent re-renders
  const memoizedNodeTypes = useMemo(() => nodeTypes, []);
  const memoizedEdgeTypes = useMemo(() => edgeTypes, []);

  if (loading) {
    return (
      <PageSection>
        <Spinner aria-label="Loading session graph" />
      </PageSection>
    );
  }

  return (
    <PageSection>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: 16 }}>
        Session Graph
      </Title>

      {error && (
        <Alert variant="warning" title="Graph Error" style={{ marginBottom: 12 }}>
          {error}
        </Alert>
      )}

      <GraphLegend />

      <div style={{ width: '100%', height: 'calc(100vh - 220px)', border: '1px solid #d2d2d2', borderRadius: 6 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          nodeTypes={memoizedNodeTypes}
          edgeTypes={memoizedEdgeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </PageSection>
  );
};
