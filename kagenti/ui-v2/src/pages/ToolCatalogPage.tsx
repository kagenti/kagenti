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
  ToolboxIcon,
  PlusCircleIcon,
  EllipsisVIcon,
  ExclamationTriangleIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { Tool } from '@/types';
import { toolService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';

export const ToolCatalogPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [namespace, setNamespace] = useState<string>('team1');
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [toolToDelete, setToolToDelete] = useState<Tool | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  const {
    data: tools = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['tools', namespace],
    queryFn: () => toolService.list(namespace),
    enabled: !!namespace,
  });

  const deleteMutation = useMutation({
    mutationFn: ({ namespace: ns, name }: { namespace: string; name: string }) =>
      toolService.delete(ns, name),
    onSuccess: (_data, variables) => {
      // Optimistically remove the deleted tool from the cache
      queryClient.setQueryData<Tool[]>(
        ['tools', variables.namespace],
        (old) => old?.filter((t) => t.name !== variables.name) ?? []
      );
      // Also invalidate to ensure fresh data from server
      queryClient.invalidateQueries({ queryKey: ['tools', variables.namespace] });
      handleCloseDeleteModal();
    },
  });

  const handleDeleteClick = (tool: Tool) => {
    setToolToDelete(tool);
    setDeleteModalOpen(true);
    setOpenMenuId(null);
  };

  const handleCloseDeleteModal = () => {
    setDeleteModalOpen(false);
    setToolToDelete(null);
    setDeleteConfirmText('');
  };

  const handleDeleteConfirm = () => {
    if (toolToDelete && deleteConfirmText === toolToDelete.name) {
      deleteMutation.mutate({
        namespace: toolToDelete.namespace,
        name: toolToDelete.name,
      });
    }
  };

  const columns = ['Name', 'Description', 'Status', 'Labels', ''];

  const renderStatusBadge = (status: string) => {
    const colorMap: Record<string, 'green' | 'red' | 'blue' | 'orange'> = {
      Ready: 'green',
      'Not Ready': 'red',
      Progressing: 'blue',
      Failed: 'red',
    };
    return <Label color={colorMap[status] || 'orange'}>{status}</Label>;
  };

  const renderLabels = (tool: Tool) => {
    const labels = [];
    if (tool.labels.protocol) {
      labels.push(
        <Label key="protocol" color="blue" isCompact>
          {tool.labels.protocol.toUpperCase()}
        </Label>
      );
    }
    if (tool.labels.framework) {
      labels.push(
        <Label key="framework" color="purple" isCompact>
          {tool.labels.framework}
        </Label>
      );
    }
    if (tool.workloadType) {
      labels.push(
        <Label key="workload" color="grey" isCompact>
          {tool.workloadType}
        </Label>
      );
    }
    return <LabelGroup>{labels}</LabelGroup>;
  };

  const getMenuId = (tool: Tool) => `${tool.namespace}-${tool.name}`;

  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Tool Catalog</Title>
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
                onClick={() => navigate('/tools/import')}
              >
                Import Tool
              </Button>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </PageSection>

      <PageSection>
        {isLoading ? (
          <div className="kagenti-loading-center">
            <Spinner size="lg" aria-label="Loading tools" />
          </div>
        ) : isError ? (
          <EmptyState>
            <EmptyStateHeader
              titleText="Error loading tools"
              icon={<EmptyStateIcon icon={ToolboxIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              {error instanceof Error
                ? error.message
                : 'Unable to fetch tools from the cluster.'}
            </EmptyStateBody>
          </EmptyState>
        ) : tools.length === 0 ? (
          <EmptyState>
            <EmptyStateHeader
              titleText="No tools found"
              icon={<EmptyStateIcon icon={ToolboxIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              No tools found in namespace "{namespace}".
            </EmptyStateBody>
            <EmptyStateFooter>
              <EmptyStateActions>
                <Button
                  variant="primary"
                  onClick={() => navigate('/tools/import')}
                >
                  Import Tool
                </Button>
              </EmptyStateActions>
            </EmptyStateFooter>
          </EmptyState>
        ) : (
          <Table aria-label="Tools table" variant="compact">
            <Thead>
              <Tr>
                {columns.map((col, idx) => (
                  <Th key={col || `col-${idx}`}>{col}</Th>
                ))}
              </Tr>
            </Thead>
            <Tbody>
              {tools.map((tool) => {
                const menuId = getMenuId(tool);
                return (
                  <Tr key={menuId}>
                    <Td dataLabel="Name">
                      <Button
                        variant="link"
                        isInline
                        onClick={() =>
                          navigate(`/tools/${tool.namespace}/${tool.name}`)
                        }
                      >
                        {tool.name}
                      </Button>
                    </Td>
                    <Td dataLabel="Description">
                      {tool.description || 'No description'}
                    </Td>
                    <Td dataLabel="Status">{renderStatusBadge(tool.status)}</Td>
                    <Td dataLabel="Labels">{renderLabels(tool)}</Td>
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
                              navigate(`/tools/${tool.namespace}/${tool.name}`)
                            }
                          >
                            View details
                          </DropdownItem>
                          <DropdownItem
                            key="delete"
                            onClick={() => handleDeleteClick(tool)}
                            isDanger
                          >
                            Delete tool
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
        title="Delete tool?"
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
              deleteConfirmText !== toolToDelete?.name
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
            The tool <strong>{toolToDelete?.name}</strong> will be permanently
            deleted. This action cannot be undone.
          </Text>
          <Text component="small" style={{ marginTop: '16px', display: 'block' }}>
            Type <strong>{toolToDelete?.name}</strong> to confirm deletion:
          </Text>
        </TextContent>
        <TextInput
          id="delete-confirm-input"
          value={deleteConfirmText}
          onChange={(_e, value) => setDeleteConfirmText(value)}
          aria-label="Confirm tool name"
          style={{ marginTop: '8px' }}
        />
      </Modal>
    </>
  );
};
