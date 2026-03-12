// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useEffect, useCallback } from 'react';
import { Spinner } from '@patternfly/react-core';
import { getPodStatus, type PodInfo } from '../services/api';

const STATUS_COLORS: Record<string, string> = {
  Running: '#2ea44f',
  CrashLoopBackOff: '#cf222e',
  OOMKilled: '#cf222e',
  Error: '#cf222e',
  Pending: '#bf8700',
  Waiting: '#bf8700',
  Terminated: '#6e7781',
  Unknown: '#6e7781',
};

function statusColor(status: string): string {
  return STATUS_COLORS[status] || '#6e7781';
}

interface PodStatusPanelProps {
  namespace: string;
  agentName: string;
}

export const PodStatusPanel: React.FC<PodStatusPanelProps> = ({ namespace, agentName }) => {
  const [pods, setPods] = useState<PodInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const fetchStatus = useCallback(async () => {
    if (!namespace || !agentName) return;
    try {
      const data = await getPodStatus(namespace, agentName);
      setPods(data.pods || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch pod status');
    } finally {
      setLoading(false);
    }
  }, [namespace, agentName]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const toggleExpand = (key: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
        <Spinner size="lg" />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 16, color: 'var(--pf-v5-global--danger-color--100)' }}>
        Error: {error}
      </div>
    );
  }

  if (pods.length === 0) {
    return <div style={{ padding: 16, color: '#888' }}>No pods found for {agentName}</div>;
  }

  return (
    <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
      {pods.map((pod) => {
        const key = pod.deployment;
        const isExpanded = expanded.has(key);
        const hasWarning = pod.restarts > 0 || pod.status !== 'Running';

        return (
          <div
            key={key}
            style={{
              border: `1px solid ${hasWarning ? 'var(--pf-v5-global--danger-color--100)' : 'var(--pf-v5-global--BorderColor--100)'}`,
              borderRadius: 6,
              overflow: 'hidden',
            }}
          >
            {/* Header */}
            <div
              onClick={() => toggleExpand(key)}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '10px 14px', cursor: 'pointer',
                backgroundColor: 'var(--pf-v5-global--BackgroundColor--100)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 12, color: '#888' }}>{isExpanded ? '\u25BC' : '\u25B6'}</span>
                <span style={{ fontWeight: 600, fontSize: 14 }}>
                  {pod.component === 'agent' ? pod.deployment : pod.component}
                </span>
                <span style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 10,
                  backgroundColor: statusColor(pod.status) + '22',
                  color: statusColor(pod.status), fontWeight: 600,
                }}>
                  {pod.status}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 12, color: '#888' }}>
                {pod.restarts > 0 && (
                  <span style={{ color: 'var(--pf-v5-global--danger-color--100)' }}>
                    {pod.restarts} restart{pod.restarts !== 1 ? 's' : ''}
                  </span>
                )}
                <span>{pod.ready_replicas}/{pod.replicas} ready</span>
                {pod.resources.limits.memory && (
                  <span>{pod.resources.limits.memory} / {pod.resources.limits.cpu}</span>
                )}
              </div>
            </div>

            {/* Warning banner */}
            {pod.last_restart_reason && (
              <div style={{
                padding: '6px 14px', fontSize: 12,
                backgroundColor: 'var(--pf-v5-global--danger-color--100)',
                color: '#fff',
              }}>
                Last restart: {pod.last_restart_reason}
                {pod.restarts > 1 && ` (${pod.restarts} times)`}
              </div>
            )}

            {/* Expanded: events table */}
            {isExpanded && (
              <div style={{ padding: '8px 14px', fontSize: 12 }}>
                {pod.pod_name && (
                  <div style={{ color: '#888', marginBottom: 8 }}>Pod: {pod.pod_name}</div>
                )}
                {pod.events.length === 0 ? (
                  <div style={{ color: '#888' }}>No events</div>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)' }}>
                        <th style={{ textAlign: 'left', padding: '4px 8px', color: '#888' }}>Type</th>
                        <th style={{ textAlign: 'left', padding: '4px 8px', color: '#888' }}>Reason</th>
                        <th style={{ textAlign: 'left', padding: '4px 8px', color: '#888' }}>Message</th>
                        <th style={{ textAlign: 'right', padding: '4px 8px', color: '#888' }}>#</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pod.events.slice(0, 20).map((evt, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)' }}>
                          <td style={{
                            padding: '4px 8px',
                            color: evt.type === 'Warning' ? 'var(--pf-v5-global--danger-color--100)' : '#888',
                          }}>
                            {evt.type}
                          </td>
                          <td style={{ padding: '4px 8px' }}>{evt.reason}</td>
                          <td style={{ padding: '4px 8px', maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {evt.message}
                          </td>
                          <td style={{ padding: '4px 8px', textAlign: 'right', color: '#888' }}>{evt.count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
