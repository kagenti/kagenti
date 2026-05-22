// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  PageSection,
  Title,
  Breadcrumb,
  BreadcrumbItem,
  Spinner,
  EmptyState,
  EmptyStateHeader,
  EmptyStateIcon,
  EmptyStateBody,
  Button,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Label,
  LabelGroup,
  Card,
  CardTitle,
  CardBody,
  Tabs,
  Tab,
  TabTitleText,
  Split,
  SplitItem,
  Flex,
  FlexItem,
  Text,
  TextContent,
  Modal,
  ModalVariant,
  TextInput,
  Icon,
  Switch,
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
  ExternalLinkAltIcon,
  ExclamationTriangleIcon,
  PluggedIcon,
  ClockIcon,
  BellIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { integrationService } from '@/services/api';

export const IntegrationDetailPage: React.FC = () => {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = React.useState<number>(0);
  const [deleteModalOpen, setDeleteModalOpen] = React.useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = React.useState('');
  const [testingConnection, setTestingConnection] = React.useState(false);
  const [testResult, setTestResult] = React.useState<{ success: boolean; message: string } | null>(null);

  // Fetch integration detail
  const {
    data: integration,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['integration', namespace, name],
    queryFn: () => integrationService.get(namespace!, name!),
    enabled: !!namespace && !!name,
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: () => integrationService.delete(namespace!, name!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] });
      navigate('/integrations');
    },
  });

  // Test connection handler
  const handleTestConnection = async () => {
    if (!namespace || !name) return;
    setTestingConnection(true);
    setTestResult(null);
    try {
      const result = await integrationService.testConnection(namespace, name);
      setTestResult(result);
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : 'Connection test failed',
      });
    } finally {
      setTestingConnection(false);
    }
  };

  const handleDeleteConfirm = () => {
    if (deleteConfirmText === name) {
      deleteMutation.mutate();
    }
  };

  const handleCloseDeleteModal = () => {
    setDeleteModalOpen(false);
    setDeleteConfirmText('');
  };

  // Helper: render status badge
  const renderStatusBadge = (status: string) => {
    let color: 'green' | 'blue' | 'red' = 'red';
    if (status === 'Connected') {
      color = 'green';
    } else if (status === 'Pending') {
      color = 'blue';
    }
    return <Label color={color}>{status}</Label>;
  };

  // Helper: render provider label
  const renderProviderLabel = (provider: string) => {
    let color: 'blue' | 'orange' | 'purple' = 'blue';
    if (provider === 'gitlab') {
      color = 'orange';
    } else if (provider === 'bitbucket') {
      color = 'purple';
    }
    return <Label color={color}>{provider}</Label>;
  };

  // Strip protocol from URL for display
  const stripProtocol = (url: string) => url.replace(/^https?:\/\//, '');

  // Format date
  const formatDate = (dateStr?: string) => {
    if (!dateStr) return 'N/A';
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  };

  // Loading state
  if (isLoading) {
    return (
      <PageSection>
        <div className="kagenti-loading-center">
          <Spinner size="lg" aria-label="Loading integration details" />
        </div>
      </PageSection>
    );
  }

  // Error state
  if (isError || !integration) {
    return (
      <PageSection>
        <EmptyState>
          <EmptyStateHeader
            titleText="Integration not found"
            icon={<EmptyStateIcon icon={CodeBranchIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>
            {error instanceof Error
              ? error.message
              : `Unable to load integration "${name}" in namespace "${namespace}".`}
          </EmptyStateBody>
          <Button variant="primary" onClick={() => navigate('/integrations')}>
            Back to Integrations
          </Button>
        </EmptyState>
      </PageSection>
    );
  }

  // Overview tab
  const renderOverviewTab = () => (
    <Card>
      <CardTitle>Details</CardTitle>
      <CardBody>
        <DescriptionList isHorizontal>
          <DescriptionListGroup>
            <DescriptionListTerm>Repository URL</DescriptionListTerm>
            <DescriptionListDescription>
              <a
                href={integration.repository.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {stripProtocol(integration.repository.url)}{' '}
                <ExternalLinkAltIcon />
              </a>
            </DescriptionListDescription>
          </DescriptionListGroup>

          <DescriptionListGroup>
            <DescriptionListTerm>Provider</DescriptionListTerm>
            <DescriptionListDescription>
              {renderProviderLabel(integration.repository.provider)}
            </DescriptionListDescription>
          </DescriptionListGroup>

          <DescriptionListGroup>
            <DescriptionListTerm>Branch</DescriptionListTerm>
            <DescriptionListDescription>
              <Label icon={<CodeBranchIcon />} isCompact>
                {integration.repository.branch}
              </Label>
            </DescriptionListDescription>
          </DescriptionListGroup>

          <DescriptionListGroup>
            <DescriptionListTerm>Credentials Secret</DescriptionListTerm>
            <DescriptionListDescription>
              {integration.repository.credentialsSecret || 'None'}
            </DescriptionListDescription>
          </DescriptionListGroup>

          <DescriptionListGroup>
            <DescriptionListTerm>Namespace</DescriptionListTerm>
            <DescriptionListDescription>
              <Label isCompact>{integration.namespace}</Label>
            </DescriptionListDescription>
          </DescriptionListGroup>

          <DescriptionListGroup>
            <DescriptionListTerm>Created At</DescriptionListTerm>
            <DescriptionListDescription>
              {formatDate(integration.createdAt)}
            </DescriptionListDescription>
          </DescriptionListGroup>

          {integration.webhookUrl && (
            <DescriptionListGroup>
              <DescriptionListTerm>Webhook URL</DescriptionListTerm>
              <DescriptionListDescription>
                <a href={integration.webhookUrl} target="_blank" rel="noopener noreferrer">
                  {integration.webhookUrl}
                </a>
              </DescriptionListDescription>
            </DescriptionListGroup>
          )}

          {integration.lastWebhookEvent && (
            <DescriptionListGroup>
              <DescriptionListTerm>Last Webhook Event</DescriptionListTerm>
              <DescriptionListDescription>
                {formatDate(integration.lastWebhookEvent)}
              </DescriptionListDescription>
            </DescriptionListGroup>
          )}

          {integration.lastScheduleRun && (
            <DescriptionListGroup>
              <DescriptionListTerm>Last Schedule Run</DescriptionListTerm>
              <DescriptionListDescription>
                {formatDate(integration.lastScheduleRun)}
              </DescriptionListDescription>
            </DescriptionListGroup>
          )}
        </DescriptionList>
      </CardBody>

      {/* Agents section */}
      <CardTitle>Agents</CardTitle>
      <CardBody>
        {integration.agents.length === 0 ? (
          <Text component="small">No agents assigned to this integration.</Text>
        ) : (
          <LabelGroup>
            {integration.agents.map((agent) => (
              <Label
                key={`${agent.namespace}-${agent.name}`}
                color="cyan"
                onClick={() =>
                  navigate(`/agents/${agent.namespace}/${agent.name}`)
                }
                style={{ cursor: 'pointer' }}
              >
                {agent.name}
              </Label>
            ))}
          </LabelGroup>
        )}
      </CardBody>

      {/* Conditions section */}
      {integration.conditions && integration.conditions.length > 0 && (
        <>
          <CardTitle>Conditions</CardTitle>
          <CardBody>
            <Table aria-label="Integration conditions" variant="compact">
              <Thead>
                <Tr>
                  <Th>Type</Th>
                  <Th>Status</Th>
                  <Th>Message</Th>
                  <Th>Last Transition</Th>
                </Tr>
              </Thead>
              <Tbody>
                {integration.conditions.map((condition, idx) => (
                  <Tr key={idx}>
                    <Td dataLabel="Type">{condition.type}</Td>
                    <Td dataLabel="Status">
                      <Label
                        color={condition.status === 'True' ? 'green' : 'red'}
                        isCompact
                      >
                        {condition.status}
                      </Label>
                    </Td>
                    <Td dataLabel="Message">{condition.message || '-'}</Td>
                    <Td dataLabel="Last Transition">
                      {formatDate(condition.lastTransitionTime)}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </CardBody>
        </>
      )}

      {/* Test connection result */}
      {testResult && (
        <CardBody>
          <Label color={testResult.success ? 'green' : 'red'}>
            {testResult.message}
          </Label>
        </CardBody>
      )}
    </Card>
  );

  // Webhooks tab
  const renderWebhooksTab = () => {
    if (integration.webhooks.length === 0) {
      return (
        <EmptyState>
          <EmptyStateHeader
            titleText="No webhooks configured"
            icon={<EmptyStateIcon icon={PluggedIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>
            No webhook configurations found for this integration. Configure
            webhooks to trigger agent actions on repository events such as push,
            pull request, or issue creation.
          </EmptyStateBody>
        </EmptyState>
      );
    }

    return (
      <Table aria-label="Webhooks table" variant="compact">
        <Thead>
          <Tr>
            <Th>Name</Th>
            <Th>Events</Th>
            <Th>Branch Filters</Th>
          </Tr>
        </Thead>
        <Tbody>
          {integration.webhooks.map((webhook) => (
            <Tr key={webhook.name}>
              <Td dataLabel="Name">{webhook.name}</Td>
              <Td dataLabel="Events">
                <LabelGroup>
                  {webhook.events.map((event) => (
                    <Label key={event} isCompact color="blue">
                      {event}
                    </Label>
                  ))}
                </LabelGroup>
              </Td>
              <Td dataLabel="Branch Filters">
                {webhook.filters?.branches && webhook.filters.branches.length > 0 ? (
                  <LabelGroup>
                    {webhook.filters.branches.map((branch) => (
                      <Label key={branch} isCompact icon={<CodeBranchIcon />}>
                        {branch}
                      </Label>
                    ))}
                  </LabelGroup>
                ) : (
                  <Text component="small">All branches</Text>
                )}
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    );
  };

  // Schedules tab
  const renderSchedulesTab = () => {
    if (integration.schedules.length === 0) {
      return (
        <EmptyState>
          <EmptyStateHeader
            titleText="No schedules configured"
            icon={<EmptyStateIcon icon={ClockIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>
            No schedule configurations found for this integration. Set up
            cron-based schedules to run agent skills on a recurring basis.
          </EmptyStateBody>
        </EmptyState>
      );
    }

    return (
      <Table aria-label="Schedules table" variant="compact">
        <Thead>
          <Tr>
            <Th>Name</Th>
            <Th>Cron</Th>
            <Th>Skill</Th>
            <Th>Agent</Th>
            <Th>Enabled</Th>
          </Tr>
        </Thead>
        <Tbody>
          {integration.schedules.map((schedule) => (
            <Tr key={schedule.name}>
              <Td dataLabel="Name">{schedule.name}</Td>
              <Td dataLabel="Cron">
                <code>{schedule.cron}</code>
              </Td>
              <Td dataLabel="Skill">
                <Label isCompact>{schedule.skill}</Label>
              </Td>
              <Td dataLabel="Agent">
                <Label
                  color="cyan"
                  isCompact
                  onClick={() =>
                    navigate(`/agents/${namespace}/${schedule.agent}`)
                  }
                  style={{ cursor: 'pointer' }}
                >
                  {schedule.agent}
                </Label>
              </Td>
              <Td dataLabel="Enabled">
                <Switch
                  id={`schedule-${schedule.name}-toggle`}
                  isChecked={schedule.enabled !== false}
                  isDisabled
                  aria-label={`Schedule ${schedule.name} enabled status`}
                />
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    );
  };

  // Alerts tab
  const renderAlertsTab = () => {
    if (integration.alerts.length === 0) {
      return (
        <EmptyState>
          <EmptyStateHeader
            titleText="No alerts configured"
            icon={<EmptyStateIcon icon={BellIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>
            No alert routing configurations found for this integration. Connect
            Prometheus or PagerDuty alerts to trigger agent-based remediation
            workflows.
          </EmptyStateBody>
        </EmptyState>
      );
    }

    return (
      <Table aria-label="Alerts table" variant="compact">
        <Thead>
          <Tr>
            <Th>Name</Th>
            <Th>Source</Th>
            <Th>Match Labels</Th>
            <Th>Agent</Th>
          </Tr>
        </Thead>
        <Tbody>
          {integration.alerts.map((alert) => (
            <Tr key={alert.name}>
              <Td dataLabel="Name">{alert.name}</Td>
              <Td dataLabel="Source">
                <Label
                  isCompact
                  color={alert.source === 'prometheus' ? 'orange' : 'purple'}
                >
                  {alert.source}
                </Label>
              </Td>
              <Td dataLabel="Match Labels">
                <LabelGroup>
                  {Object.entries(alert.matchLabels).map(([key, value]) => (
                    <Label key={key} isCompact>
                      {key}={value}
                    </Label>
                  ))}
                </LabelGroup>
              </Td>
              <Td dataLabel="Agent">
                <Label
                  color="cyan"
                  isCompact
                  onClick={() =>
                    navigate(`/agents/${namespace}/${alert.agent}`)
                  }
                  style={{ cursor: 'pointer' }}
                >
                  {alert.agent}
                </Label>
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    );
  };

  return (
    <>
      {/* Breadcrumb */}
      <PageSection variant="light" type="breadcrumb">
        <Breadcrumb>
          <BreadcrumbItem
            to="/integrations"
            onClick={(e) => {
              e.preventDefault();
              navigate('/integrations');
            }}
          >
            Integrations
          </BreadcrumbItem>
          <BreadcrumbItem isActive>{name}</BreadcrumbItem>
        </Breadcrumb>
      </PageSection>

      {/* Header */}
      <PageSection variant="light">
        <Split hasGutter>
          <SplitItem isFilled>
            <Flex
              alignItems={{ default: 'alignItemsCenter' }}
              spaceItems={{ default: 'spaceItemsMd' }}
            >
              <FlexItem>
                <Title headingLevel="h1">{integration.name}</Title>
              </FlexItem>
              <FlexItem>{renderStatusBadge(integration.status)}</FlexItem>
              <FlexItem>
                {renderProviderLabel(integration.repository.provider)}
              </FlexItem>
            </Flex>
          </SplitItem>
          <SplitItem>
            <Flex spaceItems={{ default: 'spaceItemsSm' }}>
              <FlexItem>
                <Button
                  variant="secondary"
                  onClick={handleTestConnection}
                  isLoading={testingConnection}
                  isDisabled={testingConnection}
                >
                  Test Connection
                </Button>
              </FlexItem>
              <FlexItem>
                <Button
                  variant="danger"
                  onClick={() => setDeleteModalOpen(true)}
                >
                  Delete
                </Button>
              </FlexItem>
            </Flex>
          </SplitItem>
        </Split>
      </PageSection>

      {/* Tabs */}
      <PageSection>
        <Tabs
          activeKey={activeTab}
          onSelect={(_event, tabIndex) => setActiveTab(tabIndex as number)}
          aria-label="Integration detail tabs"
        >
          <Tab eventKey={0} title={<TabTitleText>Overview</TabTitleText>}>
            {renderOverviewTab()}
          </Tab>
          <Tab
            eventKey={1}
            title={
              <TabTitleText>
                Webhooks
                {integration.webhooks.length > 0
                  ? ` (${integration.webhooks.length})`
                  : ''}
              </TabTitleText>
            }
          >
            {renderWebhooksTab()}
          </Tab>
          <Tab
            eventKey={2}
            title={
              <TabTitleText>
                Schedules
                {integration.schedules.length > 0
                  ? ` (${integration.schedules.length})`
                  : ''}
              </TabTitleText>
            }
          >
            {renderSchedulesTab()}
          </Tab>
          <Tab
            eventKey={3}
            title={
              <TabTitleText>
                Alerts
                {integration.alerts.length > 0
                  ? ` (${integration.alerts.length})`
                  : ''}
              </TabTitleText>
            }
          >
            {renderAlertsTab()}
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
              deleteMutation.isPending || deleteConfirmText !== name
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
            The integration <strong>{name}</strong> will be permanently deleted.
            This will also remove all associated webhooks, schedules, and alert
            configurations.
          </Text>
          <Text component="small" style={{ marginTop: '16px', display: 'block' }}>
            Type <strong>{name}</strong> to confirm deletion:
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
