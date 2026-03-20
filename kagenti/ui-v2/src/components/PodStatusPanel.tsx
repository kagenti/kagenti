// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useMemo, useCallback } from 'react';
import {
  ExpandableSection,
  Progress,
  ProgressMeasureLocation,
  ProgressVariant,
  Spinner,
} from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import {
  getPodStatus,
  getPodMetrics,
  getPodEvents,
  type PodInfo,
  type PodMetrics,
  type ContainerMetrics,
  type PodEventDetail,
} from '../services/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 7000;

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

/** Pick a PatternFly Progress variant based on usage percentage. */
function progressVariant(pct: number): ProgressVariant | undefined {
  if (pct > 90) return ProgressVariant.danger;
  if (pct > 70) return ProgressVariant.warning;
  return undefined; // default (green/blue)
}

/** Format bytes to a human-readable string. */
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'Ki', 'Mi', 'Gi', 'Ti'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / Math.pow(1024, i);
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[i]}`;
}

/** Format millicores to human readable. */
function formatCpu(mc: number): string {
  if (mc >= 1000) return `${(mc / 1000).toFixed(1)} cores`;
  return `${Math.round(mc)}m`;
}

/** Format a relative time string from an ISO timestamp. */
function timeAgo(timestamp: string): string {
  if (!timestamp) return '';
  const diff = Date.now() - new Date(timestamp).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface PodStatusPanelProps {
  namespace: string;
  agentName: string;
}

// ---------------------------------------------------------------------------
// Per-pod metrics section (lazy-loaded when expanded)
// ---------------------------------------------------------------------------

interface PodMetricsBarsProps {
  namespace: string;
  agentName: string;
  podName: string;
}

const PodMetricsBars: React.FC<PodMetricsBarsProps> = React.memo(
  ({ namespace, agentName, podName }) => {
    const { data: metricsData } = useQuery({
      queryKey: ['podMetrics', namespace, agentName],
      queryFn: () => getPodMetrics(namespace, agentName),
      refetchInterval: POLL_INTERVAL_MS,
      staleTime: 5000,
    });

    // Find metrics for this specific pod
    const podMetrics: PodMetrics | undefined = useMemo(
      () => metricsData?.pods?.find((p) => p.pod_name === podName),
      [metricsData, podName],
    );

    if (!podMetrics || podMetrics.containers.length === 0) {
      return (
        <div style={{ color: '#888', fontSize: 12, padding: '4px 0' }}>
          No metrics available (metrics-server may not be installed)
        </div>
      );
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {podMetrics.containers.map((cm: ContainerMetrics) => {
          const cpuPct =
            cm.cpu_limit_mc > 0
              ? Math.min(100, (cm.cpu_usage_mc / cm.cpu_limit_mc) * 100)
              : 0;
          const memPct =
            cm.memory_limit_bytes > 0
              ? Math.min(
                  100,
                  (cm.memory_usage_bytes / cm.memory_limit_bytes) * 100,
                )
              : 0;

          return (
            <div key={cm.name} style={{ marginBottom: 4 }}>
              {podMetrics.containers.length > 1 && (
                <div
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    marginBottom: 4,
                    color: '#555',
                  }}
                >
                  {cm.name}
                </div>
              )}
              <Progress
                title="CPU"
                value={Math.round(cpuPct)}
                label={
                  cm.cpu_limit_mc > 0
                    ? `${formatCpu(cm.cpu_usage_mc)} / ${formatCpu(cm.cpu_limit_mc)} (${Math.round(cpuPct)}%)`
                    : `${formatCpu(cm.cpu_usage_mc)} (no limit)`
                }
                measureLocation={ProgressMeasureLocation.outside}
                variant={progressVariant(cpuPct)}
                style={{ marginBottom: 8 }}
              />
              <Progress
                title="Memory"
                value={Math.round(memPct)}
                label={
                  cm.memory_limit_bytes > 0
                    ? `${formatBytes(cm.memory_usage_bytes)} / ${formatBytes(cm.memory_limit_bytes)} (${Math.round(memPct)}%)`
                    : `${formatBytes(cm.memory_usage_bytes)} (no limit)`
                }
                measureLocation={ProgressMeasureLocation.outside}
                variant={progressVariant(memPct)}
              />
            </div>
          );
        })}
      </div>
    );
  },
);
PodMetricsBars.displayName = 'PodMetricsBars';

// ---------------------------------------------------------------------------
// Per-pod events section (lazy-loaded when expanded)
// ---------------------------------------------------------------------------

interface PodEventsTableProps {
  namespace: string;
  agentName: string;
  podName: string;
}

const PodEventsTable: React.FC<PodEventsTableProps> = React.memo(
  ({ namespace, agentName, podName }) => {
    const { data: eventsData } = useQuery({
      queryKey: ['podEvents', namespace, agentName],
      queryFn: () => getPodEvents(namespace, agentName),
      refetchInterval: POLL_INTERVAL_MS,
      staleTime: 5000,
    });

    const podEvents: PodEventDetail[] = useMemo(
      () =>
        (eventsData?.events || []).filter(
          (e: PodEventDetail) => e.pod_name === podName,
        ),
      [eventsData, podName],
    );

    if (podEvents.length === 0) {
      return (
        <div style={{ color: '#888', fontSize: 12, padding: '4px 0' }}>
          No events
        </div>
      );
    }

    return (
      <table
        style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}
      >
        <thead>
          <tr
            style={{
              borderBottom:
                '1px solid var(--pf-v5-global--BorderColor--100)',
            }}
          >
            <th
              style={{ textAlign: 'left', padding: '4px 8px', color: '#888' }}
            >
              Time
            </th>
            <th
              style={{ textAlign: 'left', padding: '4px 8px', color: '#888' }}
            >
              Type
            </th>
            <th
              style={{ textAlign: 'left', padding: '4px 8px', color: '#888' }}
            >
              Reason
            </th>
            <th
              style={{ textAlign: 'left', padding: '4px 8px', color: '#888' }}
            >
              Message
            </th>
            <th
              style={{
                textAlign: 'right',
                padding: '4px 8px',
                color: '#888',
              }}
            >
              #
            </th>
          </tr>
        </thead>
        <tbody>
          {podEvents.slice(0, 30).map((evt: PodEventDetail, i: number) => (
            <tr
              key={i}
              style={{
                borderBottom:
                  '1px solid var(--pf-v5-global--BorderColor--100)',
              }}
            >
              <td
                style={{
                  padding: '4px 8px',
                  color: '#888',
                  whiteSpace: 'nowrap',
                }}
              >
                {timeAgo(evt.timestamp)}
              </td>
              <td
                style={{
                  padding: '4px 8px',
                  color:
                    evt.type === 'Warning'
                      ? 'var(--pf-v5-global--danger-color--100)'
                      : '#888',
                  fontWeight: evt.type === 'Warning' ? 600 : 400,
                }}
              >
                {evt.type}
              </td>
              <td style={{ padding: '4px 8px' }}>{evt.reason}</td>
              <td
                style={{
                  padding: '4px 8px',
                  maxWidth: 400,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {evt.message}
              </td>
              <td
                style={{
                  padding: '4px 8px',
                  textAlign: 'right',
                  color: '#888',
                }}
              >
                {evt.count}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  },
);
PodEventsTable.displayName = 'PodEventsTable';

// ---------------------------------------------------------------------------
// Single pod row (memoized)
// ---------------------------------------------------------------------------

interface PodRowProps {
  pod: PodInfo;
  namespace: string;
  agentName: string;
  isExpanded: boolean;
  onToggle: (key: string) => void;
}

const PodRow: React.FC<PodRowProps> = React.memo(
  ({ pod, namespace, agentName, isExpanded, onToggle }) => {
    const key = pod.pod_name || pod.deployment;
    const hasWarning = pod.restarts > 0 || pod.status !== 'Running';
    const displayName =
      pod.component === 'agent' ? pod.deployment : pod.component;

    return (
      <div
        style={{
          border: `1px solid ${hasWarning ? 'var(--pf-v5-global--danger-color--100)' : 'var(--pf-v5-global--BorderColor--100)'}`,
          borderRadius: 6,
          overflow: 'hidden',
        }}
      >
        <ExpandableSection
          toggleText={displayName}
          isExpanded={isExpanded}
          onToggle={() => onToggle(key)}
          displaySize="lg"
        >
          {/* Only render expensive children when expanded (lazy) */}
          {isExpanded && (
            <div
              style={{
                padding: '8px 14px',
                fontSize: 12,
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
              }}
            >
              {pod.pod_name && (
                <div style={{ color: '#888' }}>Pod: {pod.pod_name}</div>
              )}

              {/* Warning banner */}
              {pod.last_restart_reason && (
                <div
                  style={{
                    padding: '6px 10px',
                    fontSize: 12,
                    borderRadius: 4,
                    backgroundColor: 'var(--pf-v5-global--danger-color--100)',
                    color: '#fff',
                  }}
                >
                  Last restart: {pod.last_restart_reason}
                  {pod.restarts > 1 && ` (${pod.restarts} times)`}
                </div>
              )}

              {/* Metrics: CPU + Memory progress bars */}
              {pod.pod_name && (
                <div>
                  <div
                    style={{
                      fontWeight: 600,
                      marginBottom: 8,
                      fontSize: 13,
                    }}
                  >
                    Resource Usage
                  </div>
                  <PodMetricsBars
                    namespace={namespace}
                    agentName={agentName}
                    podName={pod.pod_name}
                  />
                </div>
              )}

              {/* Events table */}
              {pod.pod_name && (
                <div>
                  <div
                    style={{
                      fontWeight: 600,
                      marginBottom: 8,
                      fontSize: 13,
                    }}
                  >
                    Events
                  </div>
                  <PodEventsTable
                    namespace={namespace}
                    agentName={agentName}
                    podName={pod.pod_name}
                  />
                </div>
              )}
            </div>
          )}
        </ExpandableSection>

        {/* Header summary line (always visible, outside expandable) */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '4px 14px 8px',
            fontSize: 12,
            color: '#888',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span
              style={{
                fontSize: 11,
                padding: '2px 8px',
                borderRadius: 10,
                backgroundColor: statusColor(pod.status) + '22',
                color: statusColor(pod.status),
                fontWeight: 600,
              }}
            >
              {pod.status}
            </span>
            {pod.restarts > 0 && (
              <span
                style={{ color: 'var(--pf-v5-global--danger-color--100)' }}
              >
                {pod.restarts} restart{pod.restarts !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <span>
              {pod.ready_replicas}/{pod.replicas} ready
            </span>
            {pod.resources.limits.memory && (
              <span>
                {pod.resources.limits.memory} / {pod.resources.limits.cpu}
              </span>
            )}
          </div>
        </div>
      </div>
    );
  },
);
PodRow.displayName = 'PodRow';

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export const PodStatusPanel: React.FC<PodStatusPanelProps> = ({
  namespace,
  agentName,
}) => {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Pod status query with 7s polling — this component is only mounted when
  // the Pod tab is active (SandboxPage conditionally renders it), so polling
  // automatically stops when the tab is inactive.
  const {
    data: podData,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['podStatus', namespace, agentName],
    queryFn: () => getPodStatus(namespace, agentName),
    refetchInterval: POLL_INTERVAL_MS,
    enabled: !!namespace && !!agentName,
    staleTime: 5000,
  });

  const pods = podData?.pods || [];

  const toggleExpand = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  if (isLoading) {
    return (
      <div
        style={{ display: 'flex', justifyContent: 'center', padding: 40 }}
      >
        <Spinner size="lg" />
      </div>
    );
  }

  if (isError) {
    return (
      <div
        style={{
          padding: 16,
          color: 'var(--pf-v5-global--danger-color--100)',
        }}
      >
        Error:{' '}
        {error instanceof Error ? error.message : 'Failed to fetch pod status'}
      </div>
    );
  }

  if (pods.length === 0) {
    return (
      <div style={{ padding: 16, color: '#888' }}>
        No pods found for {agentName}
      </div>
    );
  }

  return (
    <div
      style={{
        padding: '12px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      {pods.map((pod) => {
        const key = pod.pod_name || pod.deployment;
        return (
          <PodRow
            key={key}
            pod={pod}
            namespace={namespace}
            agentName={agentName}
            isExpanded={expanded.has(key)}
            onToggle={toggleExpand}
          />
        );
      })}
    </div>
  );
};
