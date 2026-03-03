// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useMemo } from 'react';
import {
  Button,
  SearchInput,
  Spinner,
  Label,
  Switch,
  Title,
  Tooltip,
} from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { sandboxService } from '../services/api';
import type { TaskSummary } from '../types/sandbox';

interface SessionSidebarProps {
  namespace: string;
  activeContextId?: string;
  onSelectSession: (contextId: string) => void;
  selectedAgentName?: string;
}

/** Extract agent name from metadata or fall back to "sandbox-legion". */
function agentName(task: TaskSummary): string {
  const meta = task.metadata as Record<string, unknown> | null;
  return (meta?.agent_name as string) || 'sandbox-legion';
}

/** Extract display name: custom title, PR/issue ref, or context ID prefix. */
function sessionName(task: TaskSummary): string {
  const meta = task.metadata as Record<string, unknown> | null;
  if (meta?.title) return meta.title as string;
  if (meta?.ref) return meta.ref as string; // e.g., "#123" or "PR-45"
  return task.context_id.substring(0, 8);
}

/** Format a timestamp into compact relative or absolute time. */
function formatTime(task: TaskSummary): string {
  const ts = task.status?.timestamp as string | undefined;
  if (!ts) return '';
  try {
    const d = new Date(ts);
    const now = Date.now();
    const diffMs = now - d.getTime();
    if (diffMs < 60_000) return 'just now';
    if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)}m ago`;
    if (diffMs < 86_400_000) return `${Math.floor(diffMs / 3_600_000)}h ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

function stateColor(state: string): 'blue' | 'green' | 'red' | 'orange' | 'grey' {
  switch (state) {
    case 'working':
    case 'submitted':
      return 'blue';
    case 'completed':
      return 'green';
    case 'failed':
      return 'red';
    case 'canceled':
      return 'orange';
    default:
      return 'grey';
  }
}

function stateLabel(state: string): string {
  switch (state) {
    case 'working':
      return 'Active';
    case 'submitted':
      return 'Queued';
    case 'completed':
      return 'Done';
    case 'failed':
      return 'Failed';
    case 'canceled':
      return 'Canceled';
    default:
      return state;
  }
}

/** Is a session a root session (no parent)? */
function isRoot(task: TaskSummary): boolean {
  const meta = task.metadata as Record<string, unknown> | null;
  return !meta?.parent_context_id;
}

/** Count sub-sessions for a given parent context_id. */
function subSessionCount(
  sessions: TaskSummary[],
  parentContextId: string
): number {
  return sessions.filter((s) => {
    const meta = s.metadata as Record<string, unknown> | null;
    return meta?.parent_context_id === parentContextId;
  }).length;
}

/** Build a plain-text tooltip string for session hover preview. */
function sessionTooltip(task: TaskSummary, childCount: number): string {
  const state = task.status?.state ?? 'unknown';
  const ts = task.status?.timestamp as string | undefined;
  const created = ts ? new Date(ts).toLocaleString() : 'Unknown';
  const meta = task.metadata as Record<string, unknown> | null;
  const lines = [
    `Agent: ${agentName(task)}`,
    `Created: ${created}`,
    `Status: ${stateLabel(state)}`,
    `ID: ${task.context_id.substring(0, 12)}`,
  ];
  if (childCount > 0) lines.push(`Sub-sessions: ${childCount}`);
  if (typeof meta?.ref === 'string') lines.push(`Ref: ${meta.ref}`);
  return lines.join('\n');
}

export const SessionSidebar: React.FC<SessionSidebarProps> = ({
  namespace,
  activeContextId,
  onSelectSession,
  selectedAgentName,
}) => {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [rootOnly, setRootOnly] = useState(true);

  const { data, isLoading } = useQuery({
    queryKey: ['sandbox-sessions', namespace, search, selectedAgentName],
    queryFn: () =>
      sandboxService.listSessions(namespace, {
        limit: 20,
        search: search || undefined,
        agent_name: selectedAgentName || undefined,
      }),
    enabled: !!namespace,
    refetchInterval: 5000,
  });

  const allSessions = data?.items ?? [];

  const displaySessions = useMemo(
    () => (rootOnly ? allSessions.filter(isRoot) : allSessions),
    [allSessions, rootOnly]
  );

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        padding: '8px',
        overflow: 'hidden',
      }}
    >
      <Title headingLevel="h3" size="md" style={{ marginBottom: 8 }}>
        Sessions
      </Title>

      <SearchInput
        placeholder="Search sessions"
        value={search}
        onChange={(_e, value) => setSearch(value)}
        onClear={() => setSearch('')}
        style={{ marginBottom: 4 }}
      />

      <div style={{ marginBottom: 8 }}>
        <Switch
          id="root-only-toggle"
          label="Root only"
          labelOff="All sessions"
          isChecked={rootOnly}
          onChange={(_e, checked) => setRootOnly(checked)}
          isReversed
        />
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {isLoading && <Spinner size="md" />}
        {!isLoading && displaySessions.length === 0 && (
          <div
            style={{
              padding: 16,
              color: 'var(--pf-v5-global--Color--200)',
            }}
          >
            No sessions yet
          </div>
        )}
        {!isLoading &&
          displaySessions.map((session) => {
            const state = session.status?.state ?? 'unknown';
            const isActive = session.context_id === activeContextId;
            const childCount = subSessionCount(
              allSessions,
              session.context_id
            );

            return (
              <Tooltip
                key={session.context_id}
                position="right"
                content={
                  <span style={{ whiteSpace: 'pre-line' }}>
                    {sessionTooltip(session, childCount)}
                  </span>
                }
                entryDelay={400}
              >
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelectSession(session.context_id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter')
                      onSelectSession(session.context_id);
                  }}
                  style={{
                    padding: '6px 8px',
                    marginBottom: 2,
                    borderRadius: 4,
                    cursor: 'pointer',
                    backgroundColor: isActive
                      ? 'var(--pf-v5-global--active-color--100)'
                      : 'transparent',
                    color: isActive
                      ? '#fff'
                      : 'var(--pf-v5-global--Color--100)',
                  }}
                >
                  {/* Row 1: agent name + time */}
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      fontSize: '0.8em',
                      opacity: 0.7,
                      marginBottom: 2,
                    }}
                  >
                    <span>{agentName(session)}</span>
                    <span>{formatTime(session)}</span>
                  </div>
                  {/* Row 2: session name + status */}
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <span
                      style={{
                        fontWeight: 500,
                        fontSize: '0.9em',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        flex: 1,
                        minWidth: 0,
                      }}
                    >
                      {sessionName(session)}
                    </span>
                    <Label
                      color={stateColor(state)}
                      isCompact
                      style={{ fontSize: '0.75em' }}
                    >
                      {stateLabel(state)}
                    </Label>
                  </div>
                  {/* Row 3: sub-session indicator */}
                  {childCount > 0 && (
                    <div
                      style={{
                        fontSize: '0.75em',
                        opacity: 0.6,
                        marginTop: 2,
                      }}
                    >
                      {childCount} sub-session{childCount > 1 ? 's' : ''}
                    </div>
                  )}
                </div>
              </Tooltip>
            );
          })}
      </div>

      <div
        style={{
          borderTop: '1px solid var(--pf-v5-global--BorderColor--100)',
          paddingTop: 8,
        }}
      >
        <Button
          variant="link"
          isBlock
          onClick={() => navigate('/sandbox/sessions')}
          style={{ marginBottom: 4 }}
        >
          View All Sessions
        </Button>
        <Button
          variant="primary"
          isBlock
          onClick={() => onSelectSession('')}
          style={{ marginBottom: 4 }}
        >
          + New Session
        </Button>
        <Button
          variant="secondary"
          isBlock
          onClick={() => navigate('/sandbox/create')}
        >
          + Import Agent
        </Button>
      </div>
    </div>
  );
};
