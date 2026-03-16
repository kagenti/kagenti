// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * TypeScript types for AgentGraphCard — the self-describing graph manifest
 * served at /.well-known/agent-graph-card.json.
 *
 * See docs/plans/2026-03-15-agent-graph-card-design.md for the full spec.
 */

export type EventCategory =
  | 'reasoning'     // planner_output, executor_step, thinking, micro_reasoning
  | 'execution'     // tool_call
  | 'tool_output'   // tool_result
  | 'decision'      // reflector_decision, router_decision
  | 'terminal'      // reporter_output
  | 'meta'          // budget_update, node_transition
  | 'interaction';  // hitl_request

export interface FieldSchema {
  type: string;
  description?: string;
  enum?: string[];
  items?: Record<string, FieldSchema>;
  max_length?: number;
  max_items?: number;
  value?: string; // static value for logic descriptions
}

export interface EventTypeDef {
  category: EventCategory;
  description: string;
  langgraph_nodes: string[];
  has_llm_call: boolean;
  terminal?: boolean;
  fields: Record<string, FieldSchema>;
  debug_fields: Record<string, FieldSchema>;
}

export interface GraphEdge {
  from: string;
  to: string;
  condition: string | null;
  conditional?: boolean;
  description?: string;
}

export interface GraphTopology {
  description?: string;
  entry_node: string;
  terminal_nodes: string[];
  nodes: Record<string, { description: string }>;
  edges: GraphEdge[];
}

export interface AgentGraphCard {
  id: string;
  description: string;
  framework: string;
  version: string;
  event_catalog: Record<string, EventTypeDef>;
  common_event_fields: Record<string, FieldSchema>;
  topology: GraphTopology;
}
