// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useMemo } from 'react';
import {
  Button,
  SearchInput,
  Spinner,
  TreeView,
  TreeViewDataItem,
} from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { sandboxService } from '../services/api';
import type { TaskSummary } from '../types/sandbox';

interface SessionSidebarProps {
  namespace: string;
  activeContextId?: string;
  onSelectSession: (contextId: string) => void;
}

function stateIcon(state: string): string {
  switch (state) {
    case 'working':
    case 'submitted':
      return '\u{1F7E1}'; // yellow circle
    case 'completed':
      return '\u26AA'; // white circle
    case 'failed':
    case 'canceled':
      return '\u{1F534}'; // red circle
    default:
      return '\u{1F7E2}'; // green circle
  }
}

function sessionLabel(task: TaskSummary): string {
  const state = task.status?.state ?? 'unknown';
  const shortId = task.context_id.substring(0, 8);
  // Use title from metadata if available
  const meta = task.metadata as Record<string, unknown> | null;
  const title = meta?.title as string | undefined;
  if (title) {
    const truncated = title.length > 18 ? title.substring(0, 18) + '...' : title;
    return `${stateIcon(state)} ${truncated}`;
  }
  return `${stateIcon(state)} ${shortId}`;
}

/**
 * Build a tree from flat session list.
 *
 * Parent sessions have metadata.parent_context_id === undefined.
 * Sub-sessions have metadata.parent_context_id pointing to a parent.
 *
 * If no parent-child relationships exist, all sessions are top-level.
 * Each parent is expandable to show its sub-sessions for quick-jump.
 */
function buildTree(sessions: TaskSummary[]): TreeViewDataItem[] {
  const parentMap = new Map<string, TaskSummary[]>();
  const topLevel: TaskSummary[] = [];

  for (const s of sessions) {
    const meta = s.metadata as Record<string, unknown> | null;
    const parentId = meta?.parent_context_id as string | undefined;
    if (parentId) {
      const children = parentMap.get(parentId) || [];
      children.push(s);
      parentMap.set(parentId, children);
    } else {
      topLevel.push(s);
    }
  }

  return topLevel.map((parent) => {
    const children = parentMap.get(parent.context_id) || [];
    const item: TreeViewDataItem = {
      name: sessionLabel(parent),
      id: parent.context_id,
      defaultExpanded: children.length > 0,
    };
    if (children.length > 0) {
      item.children = children.map((child) => ({
        name: sessionLabel(child),
        id: child.context_id,
      }));
    }
    return item;
  });
}

export const SessionSidebar: React.FC<SessionSidebarProps> = ({
  namespace,
  activeContextId,
  onSelectSession,
}) => {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['sandbox-sessions', namespace, search],
    queryFn: () =>
      sandboxService.listSessions(namespace, {
        limit: 20,
        search: search || undefined,
      }),
    enabled: !!namespace,
    refetchInterval: 10000,
  });

  const sessions = data?.items ?? [];
  const treeData = useMemo(() => buildTree(sessions), [sessions]);

  // Find active item in tree (could be at top level or nested)
  const findActive = (items: TreeViewDataItem[]): TreeViewDataItem[] => {
    const result: TreeViewDataItem[] = [];
    for (const item of items) {
      if (item.id === activeContextId) result.push(item);
      if (item.children) {
        result.push(...findActive(item.children));
      }
    }
    return result;
  };

  return (
    <div
      style={{
        width: 260,
        borderRight: '1px solid var(--pf-v5-global--BorderColor--100)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        padding: '8px',
      }}
    >
      <SearchInput
        placeholder="Search sessions"
        value={search}
        onChange={(_e, value) => setSearch(value)}
        onClear={() => setSearch('')}
        style={{ marginBottom: 8 }}
      />

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {isLoading && <Spinner size="md" />}
        {!isLoading && sessions.length === 0 && (
          <div style={{ padding: 16, color: 'var(--pf-v5-global--Color--200)' }}>
            No sessions yet
          </div>
        )}
        {!isLoading && sessions.length > 0 && (
          <TreeView
            data={treeData}
            activeItems={activeContextId ? findActive(treeData) : []}
            onSelect={(_e, item) => {
              if (item.id) onSelectSession(item.id as string);
            }}
          />
        )}
      </div>

      <div style={{ borderTop: '1px solid var(--pf-v5-global--BorderColor--100)', paddingTop: 8 }}>
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
        >
          + New Session
        </Button>
      </div>
    </div>
  );
};
