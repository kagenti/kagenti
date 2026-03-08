// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useEffect } from 'react';
import {
  Card,
  CardTitle,
  CardBody,
  Label,
  Skeleton,
} from '@patternfly/react-core';
import { sandboxService } from '../services/api';

interface ChildSession {
  context_id: string;
  agent_name: string;
  title: string;
  state: string;
  timestamp: string;
}

interface SubSessionsPanelProps {
  contextId: string;
  namespace: string;
  onNavigateToSession: (contextId: string, agentName: string) => void;
}

const statusColor = (state: string): 'green' | 'blue' | 'red' | 'grey' => {
  switch (state) {
    case 'completed': return 'green';
    case 'working': return 'blue';
    case 'failed': return 'red';
    default: return 'grey';
  }
};

export const SubSessionsPanel: React.FC<SubSessionsPanelProps> = ({
  contextId,
  namespace,
  onNavigateToSession,
}) => {
  const [children, setChildren] = useState<ChildSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    sandboxService
      .getChildSessions(namespace, contextId)
      .then((result) => {
        if (!cancelled) {
          setChildren(result);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err?.message || 'Failed to load child sessions');
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [namespace, contextId]);

  if (loading) {
    return (
      <Card style={{ flex: 1 }}>
        <CardTitle>Sub-sessions</CardTitle>
        <CardBody>
          <Skeleton width="100%" height="32px" style={{ marginBottom: 8 }} />
          <Skeleton width="80%" height="32px" style={{ marginBottom: 8 }} />
          <Skeleton width="60%" height="32px" />
        </CardBody>
      </Card>
    );
  }

  if (error) {
    return (
      <Card style={{ flex: 1 }}>
        <CardTitle>Sub-sessions</CardTitle>
        <CardBody>
          <div style={{ color: 'var(--pf-v5-global--danger-color--100)' }}>{error}</div>
        </CardBody>
      </Card>
    );
  }

  if (children.length === 0) {
    return (
      <Card style={{ flex: 1 }}>
        <CardTitle>Sub-sessions</CardTitle>
        <CardBody>
          <div style={{ textAlign: 'center', padding: 24, color: 'var(--pf-v5-global--Color--200)' }}>
            No child sessions
          </div>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card style={{ flex: 1, overflow: 'hidden' }}>
      <CardTitle>Sub-sessions ({children.length})</CardTitle>
      <CardBody style={{ overflowY: 'auto', padding: 0 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9em' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--pf-v5-global--BorderColor--100)', textAlign: 'left' }}>
              <th style={{ padding: '8px 12px' }}>Agent</th>
              <th style={{ padding: '8px 12px' }}>Title</th>
              <th style={{ padding: '8px 12px' }}>Status</th>
              <th style={{ padding: '8px 12px' }}>Time</th>
            </tr>
          </thead>
          <tbody>
            {children.map((child) => (
              <tr
                key={child.context_id}
                onClick={() => onNavigateToSession(child.context_id, child.agent_name)}
                style={{
                  cursor: 'pointer',
                  borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--pf-v5-global--BackgroundColor--200)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.backgroundColor = '';
                }}
              >
                <td style={{ padding: '8px 12px', fontWeight: 500 }}>{child.agent_name}</td>
                <td style={{ padding: '8px 12px' }}>{child.title}</td>
                <td style={{ padding: '8px 12px' }}>
                  <Label isCompact color={statusColor(child.state)}>{child.state}</Label>
                </td>
                <td style={{ padding: '8px 12px', fontSize: '0.85em', color: 'var(--pf-v5-global--Color--200)' }}>
                  {child.timestamp ? new Date(child.timestamp).toLocaleString() : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  );
};

/** Returns the number of child sessions (for badge display). */
export const useChildSessionCount = (namespace: string, contextId: string | null): number => {
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (!contextId) { setCount(0); return; }
    sandboxService
      .getChildSessions(namespace, contextId)
      .then((result) => setCount(result.length))
      .catch(() => setCount(0));
  }, [namespace, contextId]);
  return count;
};
