// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Types for agent graph-card topology data.
 *
 * A graph card describes the static structure of a LangGraph agent:
 * its nodes, edges, and event catalog.
 */

// ---------------------------------------------------------------------------
// Event catalog
// ---------------------------------------------------------------------------

/** The seven stable event categories used by loop event processing. */
export type EventCategory =
  | 'reasoning'
  | 'execution'
  | 'tool_output'
  | 'decision'
  | 'terminal'
  | 'meta'
  | 'interaction';

/** Definition of a single event type in the catalog. */
export interface EventTypeDef {
  category: EventCategory;
  description: string;
}

// ---------------------------------------------------------------------------
// Graph topology
// ---------------------------------------------------------------------------

export interface GraphNode {
  description: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  condition: string | null;
  description?: string;
}

export interface GraphTopology {
  description: string;
  entry_node: string;
  terminal_nodes: string[];
  nodes: Record<string, GraphNode>;
  edges: GraphEdge[];
}

// ---------------------------------------------------------------------------
// Agent graph card
// ---------------------------------------------------------------------------

export interface AgentGraphCard {
  id: string;
  description: string;
  framework: string;
  version: string;
  event_catalog: Record<string, EventTypeDef>;
  common_event_fields: Record<string, unknown>;
  topology: GraphTopology;
}
