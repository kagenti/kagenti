// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PageSection,
  Title,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
  Button,
  Spinner,
  EmptyState,
  EmptyStateHeader,
  EmptyStateIcon,
  EmptyStateBody,
  Label,
  Modal,
  ModalVariant,
  TextInput,
  Text,
  TextContent,
  Icon,
  Dropdown,
  DropdownList,
  DropdownItem,
  MenuToggle,
  MenuToggleElement,
  ToggleGroup,
  ToggleGroupItem,
} from '@patternfly/react-core';
import {
  Table,
  Thead,
  Tr,
  Th,
  Tbody,
  Td,
} from '@patternfly/react-table';
import {
  ListIcon,
  EllipsisVIcon,
  ExclamationTriangleIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { sandboxService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';
import type { TaskSummary } from '@/types/sandbox';

// NOTE: We use the sandboxService.listSessions() which returns TaskListResponse
// The session metadata contains: parent_context_id, session_type, passover_from, passover_to

type SessionType = 'all' | 'root' | 'child' | 'passover';

export const SessionsTablePage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [namespace, setNamespace] = useState<string>('team1');
  const [typeFilter, setTypeFilter] = useState<SessionType>('all');
  const [searchText, setSearchText] = useState('');
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [sessionToDelete, setSessionToDelete] = useState<TaskSummary | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  const {
    data: sessionsResponse,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['sessions', namespace],
    queryFn: () => sandboxService.listSessions(namespace),
    enabled: !!namespace,
  });

  const sessions = sessionsResponse?.items ?? [];

  // Filter by session type and search text
  const filteredSessions = sessions.filter((s) => {
    // Type filter
    if (typeFilter !== 'all') {
      const sessionType = (s.metadata?.session_type as string) || 'root';
      if (sessionType !== typeFilter) return false;
    }
    // Search by context ID
    if (searchText.trim()) {
      const contextId = (s.context_id || s.id || '').toLowerCase();
      if (!contextId.includes(searchText.trim().toLowerCase())) return false;
    }
    return true;
  });

  const deleteMutation = useMutation({
    mutationFn: ({ contextId }: { contextId: string }) =>
      sandboxService.deleteSession(namespace, contextId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions', namespace] });
      handleCloseDeleteModal();
    },
  });

  const handleDeleteClick = (session: TaskSummary) => {
    setSessionToDelete(session);
    setDeleteModalOpen(true);
    setOpenMenuId(null);
  };

  const handleCloseDeleteModal = () => {
    setDeleteModalOpen(false);
    setSessionToDelete(null);
    setDeleteConfirmText('');
  };

  const handleDeleteConfirm = () => {
    if (sessionToDelete) {
      const contextId = sessionToDelete.context_id || sessionToDelete.id || '';
      if (contextId && deleteConfirmText === contextId.slice(0, 8)) {
        deleteMutation.mutate({ contextId });
      }
    }
  };

  const truncateId = (id: string) => id ? id.slice(0, 8) + '...' : '';

  const getSessionType = (session: TaskSummary): string => {
    return (session.metadata?.session_type as string) || 'root';
  };

  const renderTypeBadge = (session: TaskSummary) => {
    const type = getSessionType(session);
    const colors: Record<string, 'blue' | 'cyan' | 'purple' | 'grey'> = {
      root: 'blue',
      child: 'cyan',
      passover: 'purple',
    };
    return <Label color={colors[type] || 'grey'} isCompact>{type}</Label>;
  };

  const renderStatusBadge = (session: TaskSummary) => {
    const state = session.status?.state || 'unknown';
    let color: 'green' | 'blue' | 'red' | 'grey' = 'grey';
    let label = state;
    if (state === 'working' || state === 'running') {
      color = 'green';
      label = 'Running';
    } else if (state === 'completed') {
      color = 'blue';
      label = 'Completed';
    } else if (state === 'failed' || state === 'error') {
      color = 'red';
      label = 'Failed';
    } else if (state === 'input-required') {
      color = 'green';
      label = 'Awaiting Input';
    }
    return <Label color={color}>{label}</Label>;
  };

  const columns = ['Session ID', 'Title', 'Type', 'Parent', 'Status', 'Created', ''];

  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Sessions</Title>
      </PageSection>

      <PageSection variant="light" padding={{ default: 'noPadding' }}>
        <Toolbar>
          <ToolbarContent>
            <ToolbarItem>
              <NamespaceSelector
                namespace={namespace}
                onNamespaceChange={setNamespace}
              />
            </ToolbarItem>
            <ToolbarItem>
              <TextInput
                type="search"
                aria-label="Search by context ID"
                placeholder="Search by context ID"
                value={searchText}
                onChange={(_e, value) => setSearchText(value)}
              />
            </ToolbarItem>
            <ToolbarItem>
              <ToggleGroup aria-label="Session type filter">
                {(['all', 'root', 'child', 'passover'] as SessionType[]).map((t) => (
                  <ToggleGroupItem
                    key={t}
                    text={t.charAt(0).toUpperCase() + t.slice(1)}
                    buttonId={`filter-${t}`}
                    isSelected={typeFilter === t}
                    onChange={() => setTypeFilter(t)}
                  />
                ))}
              </ToggleGroup>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </PageSection>

      <PageSection>
        {isLoading ? (
          <div className="kagenti-loading-center">
            <Spinner size="lg" aria-label="Loading sessions" />
          </div>
        ) : isError ? (
          <EmptyState>
            <EmptyStateHeader
              titleText="Error loading sessions"
              icon={<EmptyStateIcon icon={ListIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              {error instanceof Error
                ? error.message
                : 'Unable to fetch sessions.'}
            </EmptyStateBody>
          </EmptyState>
        ) : filteredSessions.length === 0 ? (
          <EmptyState>
            <EmptyStateHeader
              titleText="No sessions found"
              icon={<EmptyStateIcon icon={ListIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              {typeFilter !== 'all'
                ? `No ${typeFilter} sessions found in namespace "${namespace}".`
                : `No sessions found in namespace "${namespace}".`}
            </EmptyStateBody>
          </EmptyState>
        ) : (
          <Table aria-label="Sessions table" variant="compact">
            <Thead>
              <Tr>
                {columns.map((col, idx) => (
                  <Th key={col || `col-${idx}`}>{col}</Th>
                ))}
              </Tr>
            </Thead>
            <Tbody>
              {filteredSessions.map((session) => {
                const contextId = session.context_id || session.id || '';
                const parentId = session.metadata?.parent_context_id as string | undefined;
                const title = (session.metadata?.title as string) || (session.metadata?.agent_variant as string) || 'Untitled';
                const createdAt = (session.metadata?.created_at as string) || session.status?.timestamp;

                return (
                  <Tr key={contextId}>
                    <Td dataLabel="Session ID">
                      <Button
                        variant="link"
                        isInline
                        onClick={() => navigate(`/sandbox?session=${contextId}`)}
                      >
                        {truncateId(contextId)}
                      </Button>
                    </Td>
                    <Td dataLabel="Title">{title}</Td>
                    <Td dataLabel="Type">{renderTypeBadge(session)}</Td>
                    <Td dataLabel="Parent">
                      {parentId ? (
                        <Button
                          variant="link"
                          isInline
                          onClick={() => navigate(`/sandbox?session=${parentId}`)}
                        >
                          {truncateId(parentId)}
                        </Button>
                      ) : (
                        '\u2014'
                      )}
                    </Td>
                    <Td dataLabel="Status">{renderStatusBadge(session)}</Td>
                    <Td dataLabel="Created">
                      {createdAt
                        ? new Date(createdAt).toLocaleString()
                        : '\u2014'}
                    </Td>
                    <Td isActionCell>
                      <Dropdown
                        isOpen={openMenuId === contextId}
                        onSelect={() => setOpenMenuId(null)}
                        onOpenChange={(isOpen) =>
                          setOpenMenuId(isOpen ? contextId : null)
                        }
                        toggle={(toggleRef: React.Ref<MenuToggleElement>) => (
                          <MenuToggle
                            ref={toggleRef}
                            aria-label="Actions menu"
                            variant="plain"
                            onClick={() =>
                              setOpenMenuId(
                                openMenuId === contextId ? null : contextId
                              )
                            }
                            isExpanded={openMenuId === contextId}
                          >
                            <EllipsisVIcon />
                          </MenuToggle>
                        )}
                        popperProps={{ position: 'right' }}
                      >
                        <DropdownList>
                          <DropdownItem
                            key="view"
                            onClick={() =>
                              navigate(`/sandbox?session=${contextId}`)
                            }
                          >
                            View session
                          </DropdownItem>
                          <DropdownItem
                            key="delete"
                            onClick={() => handleDeleteClick(session)}
                            isDanger
                          >
                            Delete session
                          </DropdownItem>
                        </DropdownList>
                      </Dropdown>
                    </Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>
        )}
      </PageSection>

      <Modal
        variant={ModalVariant.small}
        titleIconVariant="warning"
        title="Delete session?"
        isOpen={deleteModalOpen}
        onClose={handleCloseDeleteModal}
        actions={[
          <Button
            key="delete"
            variant="danger"
            onClick={handleDeleteConfirm}
            isLoading={deleteMutation.isPending}
            isDisabled={
              deleteMutation.isPending ||
              !sessionToDelete ||
              deleteConfirmText !== (sessionToDelete?.context_id || sessionToDelete?.id || '').slice(0, 8)
            }
          >
            Delete
          </Button>,
          <Button
            key="cancel"
            variant="link"
            onClick={handleCloseDeleteModal}
          >
            Cancel
          </Button>,
        ]}
      >
        <TextContent>
          <Text>
            <Icon status="warning" style={{ marginRight: '8px' }}>
              <ExclamationTriangleIcon />
            </Icon>
            Session <strong>{truncateId(sessionToDelete?.context_id || sessionToDelete?.id || '')}</strong>{' '}
            will be permanently deleted.
          </Text>
          <Text component="small" style={{ marginTop: '16px', display: 'block' }}>
            Type the first 8 characters of the session ID to confirm:
          </Text>
        </TextContent>
        <TextInput
          id="delete-confirm-input"
          value={deleteConfirmText}
          onChange={(_e, value) => setDeleteConfirmText(value)}
          aria-label="Confirm session ID"
          style={{ marginTop: '8px' }}
        />
      </Modal>
    </>
  );
};
