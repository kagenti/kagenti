// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * DelegationCard — renders delegation events in the chat stream (Session E)
 *
 * Handles three SSE event types from the legion agent:
 * - delegation_start: child session spawned with mode + task
 * - delegation_progress: status update from child
 * - delegation_complete: child finished with result
 *
 * Used by SandboxPage to render delegation cards inline in the chat.
 */

import React from 'react';
import {
  Card,
  CardBody,
  Label,
  Button,
  Split,
  SplitItem,
} from '@patternfly/react-core';
import {
  ExternalLinkAltIcon,
  CodeBranchIcon,
} from '@patternfly/react-icons';
import { useNavigate } from 'react-router-dom';

// ─── Types ───────────────────────────────────────────────────────────────────

export interface DelegationEvent {
  type: 'delegation_start' | 'delegation_progress' | 'delegation_complete';
  child_context_id: string;
  delegation_mode?: string;
  task?: string;
  variant?: string;
  status?: string;
  state?: string;
  final?: boolean;
}

export interface DelegationState {
  childId: string;
  mode: string;
  task: string;
  variant: string;
  status: 'spawning' | 'working' | 'completed' | 'failed';
  result?: string;
}

// ─── Mode colors ─────────────────────────────────────────────────────────────

const MODE_COLORS: Record<string, 'blue' | 'orange' | 'cyan' | 'green' | 'grey'> = {
  'in-process': 'blue',
  'shared-pvc': 'cyan',
  isolated: 'orange',
  sidecar: 'green',
};

const STATUS_COLORS: Record<string, 'blue' | 'green' | 'red' | 'grey'> = {
  spawning: 'blue',
  working: 'blue',
  completed: 'green',
  failed: 'red',
};

// ─── Helper: reduce events into delegation state ─────────────────────────────

export function reduceDelegationEvents(
  events: DelegationEvent[]
): Map<string, DelegationState> {
  const states = new Map<string, DelegationState>();

  for (const event of events) {
    const existing = states.get(event.child_context_id);

    switch (event.type) {
      case 'delegation_start':
        states.set(event.child_context_id, {
          childId: event.child_context_id,
          mode: event.delegation_mode || 'in-process',
          task: event.task || '',
          variant: event.variant || 'sandbox-legion',
          status: 'spawning',
        });
        break;

      case 'delegation_progress':
        if (existing) {
          existing.status = 'working';
        }
        break;

      case 'delegation_complete':
        if (existing) {
          existing.status = event.state === 'COMPLETED' ? 'completed' : 'failed';
        }
        break;
    }
  }

  return states;
}

// ─── Component ───────────────────────────────────────────────────────────────

interface DelegationCardProps {
  delegation: DelegationState;
  result?: string;
}

export const DelegationCard: React.FC<DelegationCardProps> = ({
  delegation,
  result,
}) => {
  const navigate = useNavigate();
  const modeColor = MODE_COLORS[delegation.mode] || 'grey';
  const statusColor = STATUS_COLORS[delegation.status] || 'grey';

  return (
    <Card
      data-testid={`delegation-card-${delegation.childId}`}
      isCompact
      style={{
        marginBottom: 8,
        border: '1px solid #d2d2d2',
        borderRadius: 8,
      }}
    >
      <CardBody style={{ padding: '12px 16px' }}>
        <Split hasGutter>
          <SplitItem>
            <CodeBranchIcon style={{ color: '#666', marginRight: 8 }} />
          </SplitItem>
          <SplitItem isFilled>
            <div style={{ marginBottom: 6 }}>
              <Label
                data-testid="delegation-mode-badge"
                color={modeColor}
                isCompact
                style={{ marginRight: 8 }}
              >
                {delegation.mode}
              </Label>
              <Label color={statusColor} isCompact>
                {delegation.status}
              </Label>
            </div>

            <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
              {delegation.task}
            </div>

            <div style={{ fontSize: 12, color: '#666' }}>
              {delegation.variant} &middot; {delegation.childId}
            </div>

            {result && (
              <div
                style={{
                  marginTop: 8,
                  padding: '6px 10px',
                  background: '#f4f4f4',
                  borderRadius: 4,
                  fontSize: 12,
                  fontFamily: 'var(--pf-v5-global--FontFamily--monospace, monospace)',
                }}
              >
                {result}
              </div>
            )}
          </SplitItem>
          <SplitItem>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <Button
                data-testid="delegation-view-child-link"
                variant="link"
                size="sm"
                icon={<ExternalLinkAltIcon />}
                onClick={() => navigate(`/sandbox?session=${delegation.childId}`)}
              >
                View
              </Button>
              <Button
                data-testid="delegation-view-graph-link"
                variant="link"
                size="sm"
                onClick={() => navigate('/sandbox/graph')}
              >
                Graph
              </Button>
            </div>
          </SplitItem>
        </Split>
      </CardBody>
    </Card>
  );
};
