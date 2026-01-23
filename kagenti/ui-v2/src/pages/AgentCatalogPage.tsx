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
  EmptyStateFooter,
  EmptyStateActions,
  Label,
  LabelGroup,
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
  CubesIcon,
  PlusCircleIcon,
  EllipsisVIcon,
  ExclamationTriangleIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { Agent } from '@/types';
import { agentService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';

export const AgentCatalogPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [namespace, setNamespace] = useState<string>('team1');
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [agentToDelete, setAgentToDelete] = useState<Agent | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  const {
    data: agents = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['agents', namespace],
    queryFn: () => agentService.list(namespace),
    enabled: !!namespace,
  });

  const deleteMutation = useMutation({
    mutationFn: ({ namespace: ns, name }: { namespace: string; name: string }) =>
      agentService.delete(ns, name),
    onSuccess: (_data, variables) => {
      // Optimistically remove the deleted agent from the cache
      queryClient.setQueryData<Agent[]>(
        ['agents', variables.namespace],
        (old) => old?.filter((a) => a.name !== variables.name) ?? []
      );
      // Also invalidate to ensure fresh data from server
      queryClient.invalidateQueries({ queryKey: ['agents', variables.namespace] });
      handleCloseDeleteModal();
    },
  });

  const handleDeleteClick = (agent: Agent) => {
    setAgentToDelete(agent);
    setDeleteModalOpen(true);
    setOpenMenuId(null);
  };

  const handleCloseDeleteModal = () => {
    setDeleteModalOpen(false);
    setAgentToDelete(null);
    setDeleteConfirmText('');
  };

  const handleDeleteConfirm = () => {
    if (agentToDelete && deleteConfirmText === agentToDelete.name) {
      deleteMutation.mutate({
        namespace: agentToDelete.namespace,
        name: agentToDelete.name,
      });
    }
  };

  const columns = ['Name', 'Description', 'Status', 'Labels', 'Workload', ''];

  const renderWorkloadType = (workloadType: string | undefined) => {
    const type = workloadType || 'deployment';
    const label = type.charAt(0).toUpperCase() + type.slice(1);
    let color: 'grey' | 'orange' | 'gold' = 'grey';
    if (type === 'job') {
      color = 'orange';
    } else if (type === 'statefulset') {
      color = 'gold';
    }
    return <Label color={color} isCompact>{label}</Label>;
  };

  const renderStatusBadge = (status: string) => {
    let color: 'green' | 'red' | 'blue' | 'cyan' = 'red';
    if (status === 'Ready' || status === 'Completed' || status === 'Running') {
      color = 'green';
    } else if (status === 'Progressing' || status === 'Pending') {
      color = 'blue';
    }
    return <Label color={color}>{status}</Label>;
  };

  const renderLabels = (agent: Agent) => {
    const labels = [];
    if (agent.labels.protocol) {
      labels.push(
        <Label key="protocol" color="blue" isCompact>
          {agent.labels.protocol.toUpperCase()}
        </Label>
      );
    }
    if (agent.labels.framework) {
      labels.push(
        <Label key="framework" color="purple" isCompact>
          {agent.labels.framework}
        </Label>
      );
    }
    return <LabelGroup>{labels}</LabelGroup>;
  };

  const getMenuId = (agent: Agent) => `${agent.namespace}-${agent.name}`;

  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Agent Catalog</Title>
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
              <Button
                variant="primary"
                icon={<PlusCircleIcon />}
                onClick={() => navigate('/agents/import')}
              >
                Import Agent
              </Button>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </PageSection>

      <PageSection>
        {isLoading ? (
          <div className="kagenti-loading-center">
            <Spinner size="lg" aria-label="Loading agents" />
          </div>
        ) : isError ? (
          <EmptyState>
            <EmptyStateHeader
              titleText="Error loading agents"
              icon={<EmptyStateIcon icon={CubesIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              {error instanceof Error
                ? error.message
                : 'Unable to fetch agents from the cluster.'}
            </EmptyStateBody>
          </EmptyState>
        ) : agents.length === 0 ? (
          <EmptyState>
            <EmptyStateHeader
              titleText="No agents found"
              icon={<EmptyStateIcon icon={CubesIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              No agents found in namespace "{namespace}".
            </EmptyStateBody>
            <EmptyStateFooter>
              <EmptyStateActions>
                <Button
                  variant="primary"
                  onClick={() => navigate('/agents/import')}
                >
                  Import Agent
                </Button>
              </EmptyStateActions>
            </EmptyStateFooter>
          </EmptyState>
        ) : (
          <Table aria-label="Agents table" variant="compact">
            <Thead>
              <Tr>
                {columns.map((col, idx) => (
                  <Th key={col || `col-${idx}`}>{col}</Th>
                ))}
              </Tr>
            </Thead>
            <Tbody>
              {agents.map((agent) => {
                const menuId = getMenuId(agent);
                return (
                  <Tr key={menuId}>
                    <Td dataLabel="Name">
                      <Button
                        variant="link"
                        isInline
                        onClick={() =>
                          navigate(`/agents/${agent.namespace}/${agent.name}`)
                        }
                      >
                        {agent.name}
                      </Button>
                    </Td>
                    <Td dataLabel="Description">
                      {agent.description || 'No description'}
                    </Td>
                    <Td dataLabel="Status">{renderStatusBadge(agent.status)}</Td>
                    <Td dataLabel="Labels">{renderLabels(agent)}</Td>
                    <Td dataLabel="Workload">{renderWorkloadType(agent.workloadType)}</Td>
                    <Td isActionCell>
                      <Dropdown
                        isOpen={openMenuId === menuId}
                        onSelect={() => setOpenMenuId(null)}
                        onOpenChange={(isOpen) => setOpenMenuId(isOpen ? menuId : null)}
                        toggle={(toggleRef: React.Ref<MenuToggleElement>) => (
                          <MenuToggle
                            ref={toggleRef}
                            aria-label="Actions menu"
                            variant="plain"
                            onClick={() =>
                              setOpenMenuId(openMenuId === menuId ? null : menuId)
                            }
                            isExpanded={openMenuId === menuId}
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
                              navigate(`/agents/${agent.namespace}/${agent.name}`)
                            }
                          >
                            View details
                          </DropdownItem>
                          <DropdownItem
                            key="delete"
                            onClick={() => handleDeleteClick(agent)}
                            isDanger
                          >
                            Delete agent
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

      {/* Delete Warning Modal */}
      <Modal
        variant={ModalVariant.small}
        titleIconVariant="warning"
        title="Delete agent?"
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
              deleteConfirmText !== agentToDelete?.name
            }
          >
            Delete
          </Button>,
          <Button
            key="cancel"
            variant="link"
            onClick={handleCloseDeleteModal}
            isDisabled={deleteMutation.isPending}
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
            The agent <strong>{agentToDelete?.name}</strong> will be permanently
            deleted. This will also delete the associated Deployment, Service,
            and any Shipwright builds if they exist.
          </Text>
          <Text component="small" style={{ marginTop: '16px', display: 'block' }}>
            Type <strong>{agentToDelete?.name}</strong> to confirm deletion:
          </Text>
        </TextContent>
        <TextInput
          id="delete-confirm-input"
          value={deleteConfirmText}
          onChange={(_e, value) => setDeleteConfirmText(value)}
          aria-label="Confirm agent name"
          style={{ marginTop: '8px' }}
        />
      </Modal>
    </>
  );
};
