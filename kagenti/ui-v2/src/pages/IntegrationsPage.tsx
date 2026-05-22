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
  Tabs,
  Tab,
  TabTitleText,
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
  CodeBranchIcon,
  PlusCircleIcon,
  EllipsisVIcon,
  ExclamationTriangleIcon,
  BellIcon,
  ClockIcon,
  PluggedIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import type { Integration } from '@/types';
import { integrationService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';

export const IntegrationsPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [namespace, setNamespace] = useState<string>('team1');
  const [activeTabKey, setActiveTabKey] = useState<number>(0);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [integrationToDelete, setIntegrationToDelete] = useState<Integration | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  const {
    data: integrations = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['integrations', namespace],
    queryFn: () => integrationService.list(namespace),
    enabled: !!namespace,
  });

  const deleteMutation = useMutation({
    mutationFn: ({ namespace: ns, name }: { namespace: string; name: string }) =>
      integrationService.delete(ns, name),
    onSuccess: (_data, variables) => {
      queryClient.setQueryData<Integration[]>(
        ['integrations', variables.namespace],
        (old) => old?.filter((i) => i.name !== variables.name) ?? []
      );
      queryClient.invalidateQueries({ queryKey: ['integrations', variables.namespace] });
      handleCloseDeleteModal();
    },
  });

  const handleDeleteClick = (integration: Integration) => {
    setIntegrationToDelete(integration);
    setDeleteModalOpen(true);
    setOpenMenuId(null);
  };

  const handleCloseDeleteModal = () => {
    setDeleteModalOpen(false);
    setIntegrationToDelete(null);
    setDeleteConfirmText('');
  };

  const handleDeleteConfirm = () => {
    if (integrationToDelete && deleteConfirmText === integrationToDelete.name) {
      deleteMutation.mutate({
        namespace: integrationToDelete.namespace,
        name: integrationToDelete.name,
      });
    }
  };

  // Compute tab counts
  const totalWebhooks = integrations.reduce((sum, i) => sum + i.webhooks.length, 0);
  const totalSchedules = integrations.reduce((sum, i) => sum + i.schedules.length, 0);
  const totalAlerts = integrations.reduce((sum, i) => sum + i.alerts.length, 0);

  const columns = ['Name', 'Repository', 'Provider', 'Agents', 'Webhooks', 'Schedules', 'Status', ''];

  const stripProtocol = (url: string) => url.replace(/^https?:\/\//, '');

  const renderStatusBadge = (status: string) => {
    let color: 'green' | 'blue' | 'red' = 'red';
    if (status === 'Connected') {
      color = 'green';
    } else if (status === 'Pending') {
      color = 'blue';
    }
    return <Label color={color}>{status}</Label>;
  };

  const renderProviderLabel = (provider: string) => {
    let color: 'blue' | 'orange' | 'purple' = 'blue';
    if (provider === 'gitlab') {
      color = 'orange';
    } else if (provider === 'bitbucket') {
      color = 'purple';
    }
    return <Label color={color} isCompact>{provider}</Label>;
  };

  const renderAgentChips = (agents: Integration['agents']) => {
    if (agents.length === 0) return <Text component="small">None</Text>;
    return (
      <LabelGroup>
        {agents.map((agent) => (
          <Label key={`${agent.namespace}-${agent.name}`} color="cyan" isCompact>
            {agent.name}
          </Label>
        ))}
      </LabelGroup>
    );
  };

  const getMenuId = (integration: Integration) => `${integration.namespace}-${integration.name}`;

  const renderRepositoriesTab = () => {
    if (isLoading) {
      return (
        <div className="kagenti-loading-center">
          <Spinner size="lg" aria-label="Loading integrations" />
        </div>
      );
    }

    if (isError) {
      return (
        <EmptyState>
          <EmptyStateHeader
            titleText="Error loading integrations"
            icon={<EmptyStateIcon icon={CodeBranchIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>
            {error instanceof Error
              ? error.message
              : 'Unable to fetch integrations from the cluster.'}
          </EmptyStateBody>
        </EmptyState>
      );
    }

    if (integrations.length === 0) {
      return (
        <EmptyState>
          <EmptyStateHeader
            titleText="No integrations found"
            icon={<EmptyStateIcon icon={CodeBranchIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>
            No integrations found in namespace &quot;{namespace}&quot;.
          </EmptyStateBody>
          <EmptyStateFooter>
            <EmptyStateActions>
              <Button
                variant="primary"
                onClick={() => navigate('/integrations/add')}
              >
                Add Integration
              </Button>
            </EmptyStateActions>
          </EmptyStateFooter>
        </EmptyState>
      );
    }

    return (
      <Table aria-label="Integrations table" variant="compact">
        <Thead>
          <Tr>
            {columns.map((col, idx) => (
              <Th key={col || `col-${idx}`}>{col}</Th>
            ))}
          </Tr>
        </Thead>
        <Tbody>
          {integrations.map((integration) => {
            const menuId = getMenuId(integration);
            return (
              <Tr key={menuId}>
                <Td dataLabel="Name">
                  <Button
                    variant="link"
                    isInline
                    onClick={() =>
                      navigate(`/integrations/${integration.namespace}/${integration.name}`)
                    }
                  >
                    {integration.name}
                  </Button>
                </Td>
                <Td dataLabel="Repository">
                  <a
                    href={integration.repository.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {stripProtocol(integration.repository.url)}
                  </a>
                </Td>
                <Td dataLabel="Provider">
                  {renderProviderLabel(integration.repository.provider)}
                </Td>
                <Td dataLabel="Agents">
                  {renderAgentChips(integration.agents)}
                </Td>
                <Td dataLabel="Webhooks">{integration.webhooks.length}</Td>
                <Td dataLabel="Schedules">{integration.schedules.length}</Td>
                <Td dataLabel="Status">
                  {renderStatusBadge(integration.status)}
                </Td>
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
                          navigate(`/integrations/${integration.namespace}/${integration.name}`)
                        }
                      >
                        View details
                      </DropdownItem>
                      <DropdownItem
                        key="delete"
                        onClick={() => handleDeleteClick(integration)}
                        isDanger
                      >
                        Delete integration
                      </DropdownItem>
                    </DropdownList>
                  </Dropdown>
                </Td>
              </Tr>
            );
          })}
        </Tbody>
      </Table>
    );
  };

  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Integrations</Title>
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
                onClick={() => navigate('/integrations/add')}
              >
                Add Integration
              </Button>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </PageSection>

      <PageSection>
        <Tabs
          activeKey={activeTabKey}
          onSelect={(_event, tabIndex) => setActiveTabKey(tabIndex as number)}
          aria-label="Integration tabs"
        >
          <Tab
            eventKey={0}
            title={
              <TabTitleText>
                Repositories{integrations.length > 0 ? ` (${integrations.length})` : ''}
              </TabTitleText>
            }
          >
            {renderRepositoriesTab()}
          </Tab>
          <Tab
            eventKey={1}
            title={
              <TabTitleText>
                Webhooks{totalWebhooks > 0 ? ` (${totalWebhooks})` : ''}
              </TabTitleText>
            }
          >
            <EmptyState>
              <EmptyStateHeader
                titleText="Webhooks"
                icon={<EmptyStateIcon icon={PluggedIcon} />}
                headingLevel="h4"
              />
              <EmptyStateBody>
                Webhook configuration will be available here. Configure webhooks to trigger
                agent actions on repository events such as push, pull request, or issue creation.
              </EmptyStateBody>
            </EmptyState>
          </Tab>
          <Tab
            eventKey={2}
            title={
              <TabTitleText>
                Schedules{totalSchedules > 0 ? ` (${totalSchedules})` : ''}
              </TabTitleText>
            }
          >
            <EmptyState>
              <EmptyStateHeader
                titleText="Schedules"
                icon={<EmptyStateIcon icon={ClockIcon} />}
                headingLevel="h4"
              />
              <EmptyStateBody>
                Schedule configuration will be available here. Set up cron-based schedules
                to run agent skills on a recurring basis.
              </EmptyStateBody>
            </EmptyState>
          </Tab>
          <Tab
            eventKey={3}
            title={
              <TabTitleText>
                Alerts{totalAlerts > 0 ? ` (${totalAlerts})` : ''}
              </TabTitleText>
            }
          >
            <EmptyState>
              <EmptyStateHeader
                titleText="Alerts"
                icon={<EmptyStateIcon icon={BellIcon} />}
                headingLevel="h4"
              />
              <EmptyStateBody>
                Alert routing configuration will be available here. Connect Prometheus or
                PagerDuty alerts to trigger agent-based remediation workflows.
              </EmptyStateBody>
            </EmptyState>
          </Tab>
        </Tabs>
      </PageSection>

      {/* Delete Warning Modal */}
      <Modal
        variant={ModalVariant.small}
        titleIconVariant="warning"
        title="Delete integration?"
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
              deleteConfirmText !== integrationToDelete?.name
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
            The integration <strong>{integrationToDelete?.name}</strong> will be permanently
            deleted. This will also remove all associated webhooks, schedules, and alert
            configurations.
          </Text>
          <Text component="small" style={{ marginTop: '16px', display: 'block' }}>
            Type <strong>{integrationToDelete?.name}</strong> to confirm deletion:
          </Text>
        </TextContent>
        <TextInput
          id="delete-confirm-input"
          value={deleteConfirmText}
          onChange={(_e, value) => setDeleteConfirmText(value)}
          aria-label="Confirm integration name"
          style={{ marginTop: '8px' }}
        />
      </Modal>
    </>
  );
};
