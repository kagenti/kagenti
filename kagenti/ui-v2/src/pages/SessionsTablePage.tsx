// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useMemo } from 'react';
import {
  PageSection,
  Title,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
  SearchInput,
  Button,
  Spinner,
  Alert,
  Label,
  Pagination,
  Modal,
  ModalVariant,
  Switch,
} from '@patternfly/react-core';
import {
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
} from '@patternfly/react-table';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { sandboxService } from '../services/api';
import { NamespaceSelector } from '../components/NamespaceSelector';
import type { TaskSummary } from '../types/sandbox';

function statusLabel(state: string) {
  switch (state) {
    case 'completed':
      return <Label color="green">Completed</Label>;
    case 'working':
    case 'submitted':
      return <Label color="blue">Active</Label>;
    case 'failed':
      return <Label color="red">Failed</Label>;
    case 'canceled':
      return <Label color="orange">Canceled</Label>;
    default:
      return <Label>{state}</Label>;
  }
}

function isRoot(task: TaskSummary): boolean {
  const meta = task.metadata as Record<string, unknown> | null;
  return !meta?.parent_context_id;
}

function agentName(task: TaskSummary): string {
  const meta = task.metadata as Record<string, unknown> | null;
  return (meta?.agent_name as string) || 'sandbox-legion';
}

function sessionName(task: TaskSummary): string {
  const meta = task.metadata as Record<string, unknown> | null;
  if (meta?.title) {
    const t = meta.title as string;
    return t.length > 30 ? t.substring(0, 30) + '...' : t;
  }
  if (meta?.ref) return meta.ref as string;
  return task.context_id.substring(0, 12);
}

function formatTimestamp(task: TaskSummary): string {
  const ts = task.status?.timestamp as string | undefined;
  if (!ts) return '-';
  try {
    return new Date(ts).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '-';
  }
}

export const SessionsTablePage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [namespace, setNamespace] = useState('team1');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(20);
  const [killTarget, setKillTarget] = useState<TaskSummary | null>(null);
  const [rootOnly, setRootOnly] = useState(true);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['sandbox-sessions', namespace, search, page, perPage],
    queryFn: () =>
      sandboxService.listSessions(namespace, {
        limit: 100, // Fetch more so we can filter client-side and count subs
        offset: 0,
        search: search || undefined,
      }),
    enabled: !!namespace,
  });

  const killMutation = useMutation({
    mutationFn: (contextId: string) =>
      sandboxService.killSession(namespace, contextId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['sandbox-sessions', namespace],
      });
      setKillTarget(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (contextId: string) =>
      sandboxService.deleteSession(namespace, contextId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['sandbox-sessions', namespace],
      });
    },
  });

  const allSessions = data?.items ?? [];

  // Count sub-sessions per parent
  const subCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of allSessions) {
      const meta = s.metadata as Record<string, unknown> | null;
      const parentId = meta?.parent_context_id as string | undefined;
      if (parentId) {
        counts.set(parentId, (counts.get(parentId) || 0) + 1);
      }
    }
    return counts;
  }, [allSessions]);

  // Apply root-only filter then paginate client-side
  const filtered = useMemo(
    () => (rootOnly ? allSessions.filter(isRoot) : allSessions),
    [allSessions, rootOnly]
  );
  const total = filtered.length;
  const sessions = filtered.slice((page - 1) * perPage, page * perPage);

  return (
    <PageSection variant="light">
      <Title headingLevel="h1" style={{ marginBottom: 16 }}>
        Sandbox Sessions
      </Title>

      <Toolbar clearAllFilters={() => setSearch('')}>
        <ToolbarContent>
          <ToolbarItem>
            <NamespaceSelector
              namespace={namespace}
              onNamespaceChange={(ns) => {
                setNamespace(ns);
                setPage(1);
              }}
            />
          </ToolbarItem>
          <ToolbarItem>
            <SearchInput
              placeholder="Search by context ID"
              value={search}
              onChange={(_e, value) => {
                setSearch(value);
                setPage(1);
              }}
              onClear={() => {
                setSearch('');
                setPage(1);
              }}
            />
          </ToolbarItem>
          <ToolbarItem>
            <Switch
              id="table-root-only"
              label="Root only"
              labelOff="All sessions"
              isChecked={rootOnly}
              onChange={(_e, checked) => {
                setRootOnly(checked);
                setPage(1);
              }}
              isReversed
            />
          </ToolbarItem>
          <ToolbarItem align={{ default: 'alignRight' }}>
            <Button
              variant="primary"
              onClick={() => navigate('/sandbox')}
            >
              New Session
            </Button>
          </ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      {isLoading && <Spinner size="lg" />}

      {isError && (
        <Alert variant="danger" title="Failed to load sessions" isInline>
          {error instanceof Error ? error.message : 'An error occurred'}
        </Alert>
      )}

      {!isLoading && sessions.length > 0 && (
        <>
          <Table aria-label="Sessions table">
            <Thead>
              <Tr>
                <Th>Session</Th>
                <Th>Agent</Th>
                <Th>Created</Th>
                <Th>Status</Th>
                <Th>Subs</Th>
                <Th>Actions</Th>
              </Tr>
            </Thead>
            <Tbody>
              {sessions.map((session) => {
                const state = session.status?.state ?? 'unknown';
                const subs = subCounts.get(session.context_id) || 0;
                return (
                  <Tr
                    key={session.id}
                    isClickable
                    onRowClick={() =>
                      navigate(
                        `/sandbox?session=${encodeURIComponent(session.context_id)}`
                      )
                    }
                  >
                    <Td dataLabel="Session">{sessionName(session)}</Td>
                    <Td dataLabel="Agent">{agentName(session)}</Td>
                    <Td dataLabel="Created">{formatTimestamp(session)}</Td>
                    <Td dataLabel="Status">{statusLabel(state)}</Td>
                    <Td dataLabel="Subs">
                      {subs > 0 ? (
                        <Label color="blue" isCompact>
                          {subs}
                        </Label>
                      ) : (
                        '-'
                      )}
                    </Td>
                    <Td dataLabel="Actions">
                      {(state === 'working' || state === 'submitted') && (
                        <Button
                          variant="warning"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            setKillTarget(session);
                          }}
                        >
                          Kill
                        </Button>
                      )}
                      {(state === 'completed' ||
                        state === 'failed' ||
                        state === 'canceled') && (
                        <Button
                          variant="link"
                          isDanger
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteMutation.mutate(session.context_id);
                          }}
                          isLoading={deleteMutation.isPending}
                        >
                          Delete
                        </Button>
                      )}
                    </Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>

          <Pagination
            itemCount={total}
            perPage={perPage}
            page={page}
            onSetPage={(_e, p) => setPage(p)}
            onPerPageSelect={(_e, pp) => {
              setPerPage(pp);
              setPage(1);
            }}
          />
        </>
      )}

      {!isLoading && sessions.length === 0 && (
        <Alert variant="info" title="No sessions found" isInline>
          No sandbox sessions in this namespace.
        </Alert>
      )}

      {/* Kill confirmation modal */}
      <Modal
        variant={ModalVariant.small}
        title="Kill Session"
        isOpen={!!killTarget}
        onClose={() => setKillTarget(null)}
        actions={[
          <Button
            key="cancel"
            variant="link"
            onClick={() => setKillTarget(null)}
          >
            Cancel
          </Button>,
          <Button
            key="kill"
            variant="danger"
            isLoading={killMutation.isPending}
            onClick={() =>
              killTarget &&
              killMutation.mutate(killTarget.context_id)
            }
          >
            Kill Session
          </Button>,
        ]}
      >
        Are you sure you want to kill session{' '}
        <strong>{killTarget?.context_id.substring(0, 12)}...</strong>?
      </Modal>
    </PageSection>
  );
};
