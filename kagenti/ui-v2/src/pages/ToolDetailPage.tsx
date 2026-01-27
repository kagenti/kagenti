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
  Card,
  CardTitle,
  CardBody,
  Tabs,
  Tab,
  TabTitleText,
  Alert,
  Grid,
  GridItem,
  ClipboardCopy,
  Split,
  SplitItem,
  Flex,
  FlexItem,
  ExpandableSection,
  Modal,
  ModalVariant,
  Form,
  FormGroup,
  TextInput,
  Switch,
  FormHelperText,
  HelperText,
  HelperTextItem,
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
  PlayIcon,
  ExternalLinkAltIcon,
  ExclamationTriangleIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import yaml from 'js-yaml';

import { toolService, configService } from '@/services/api';

interface StatusCondition {
  type: string;
  status: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
}

interface MCPToolInfo {
  name: string;
  description?: string;
  input_schema?: JSONSchema;
}

interface JSONSchema {
  type?: string;
  properties?: Record<string, JSONSchemaProperty>;
  required?: string[];
}

interface JSONSchemaProperty {
  type?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
}

interface InvokeResult {
  content?: Array<{ type: string; text?: string; data?: unknown; value?: string }>;
  isError?: boolean;
}

export const ToolDetailPage: React.FC = () => {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = React.useState<string | number>(0);
  const [expandedTools, setExpandedTools] = React.useState<Record<string, boolean>>({});
  const [deleteModalOpen, setDeleteModalOpen] = React.useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = React.useState('');
  const [actionsMenuOpen, setActionsMenuOpen] = React.useState(false);

  const deleteMutation = useMutation({
    mutationFn: () => toolService.delete(namespace!, name!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      navigate('/tools');
    },
  });

  const handleCloseDeleteModal = () => {
    setDeleteModalOpen(false);
    setDeleteConfirmText('');
  };

  const handleDeleteConfirm = () => {
    if (deleteConfirmText === name) {
      deleteMutation.mutate();
    }
  };

  // Invoke tool state
  const [invokeModalOpen, setInvokeModalOpen] = React.useState(false);
  const [selectedTool, setSelectedTool] = React.useState<MCPToolInfo | null>(null);
  const [toolArgs, setToolArgs] = React.useState<Record<string, unknown>>({});
  const [invokeResult, setInvokeResult] = React.useState<InvokeResult | null>(null);

  const { data: tool, isLoading, isError, error } = useQuery({
    queryKey: ['tool', namespace, name],
    queryFn: () => toolService.get(namespace!, name!),
    enabled: !!namespace && !!name,
    refetchInterval: (query) => {
      // Poll every 5 seconds if tool is not ready
      const readyStatus = query.state.data?.readyStatus || '';
      return readyStatus === 'Ready' ? false : 5000;
    },
  });

  const connectMutation = useMutation({
    mutationFn: () => toolService.connect(namespace!, name!),
  });

  // Fetch dashboard config for MCP Inspector URL
  const { data: dashboardConfig } = useQuery({
    queryKey: ['dashboards'],
    queryFn: () => configService.getDashboards(),
  });

  // Check if an HTTPRoute/Route exists for this tool
  const { data: routeStatusData } = useQuery({
    queryKey: ['tool-route-status', namespace, name],
    queryFn: async () => {
      try {
        return await toolService.getRouteStatus(namespace!, name!);
      } catch (error) {
        console.warn('Failed to check route status:', error);
        return { hasRoute: false };
      }
    },
    enabled: !!namespace && !!name,
    retry: false,
    staleTime: 30000, // Cache for 30 seconds
  });

  const invokeMutation = useMutation({
    mutationFn: ({ toolName, args }: { toolName: string; args: Record<string, unknown> }) =>
      toolService.invoke(namespace!, name!, toolName, args),
    onSuccess: (data) => {
      setInvokeResult(data.result as InvokeResult);
    },
  });

  // Open invoke modal for a specific tool
  const openInvokeModal = (mcpTool: MCPToolInfo) => {
    setSelectedTool(mcpTool);
    setInvokeResult(null);
    // Initialize args with default values from schema
    const initialArgs: Record<string, unknown> = {};
    if (mcpTool.input_schema?.properties) {
      Object.entries(mcpTool.input_schema.properties).forEach(([key, prop]) => {
        if (prop.default !== undefined) {
          initialArgs[key] = prop.default;
        } else if (prop.type === 'boolean') {
          initialArgs[key] = false;
        } else if (prop.type === 'number' || prop.type === 'integer') {
          initialArgs[key] = 0;
        } else {
          initialArgs[key] = '';
        }
      });
    }
    setToolArgs(initialArgs);
    setInvokeModalOpen(true);
  };

  // Close invoke modal
  const closeInvokeModal = () => {
    setInvokeModalOpen(false);
    setSelectedTool(null);
    setToolArgs({});
    invokeMutation.reset();
  };

  // Handle tool invocation
  const handleInvoke = () => {
    if (selectedTool) {
      invokeMutation.mutate({ toolName: selectedTool.name, args: toolArgs });
    }
  };

  // Update a single argument value
  const updateArg = (key: string, value: unknown) => {
    setToolArgs((prev) => ({ ...prev, [key]: value }));
  };

  if (isLoading) {
    return (
      <PageSection>
        <div className="kagenti-loading-center">
          <Spinner size="lg" aria-label="Loading tool details" />
        </div>
      </PageSection>
    );
  }

  if (isError || !tool) {
    return (
      <PageSection>
        <EmptyState>
          <EmptyStateHeader
            titleText="Tool not found"
            icon={<EmptyStateIcon icon={ToolboxIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>
            {error instanceof Error
              ? error.message
              : `Could not load tool "${name}" in namespace "${namespace}".`}
          </EmptyStateBody>
          <Button variant="primary" onClick={() => navigate('/tools')}>
            Back to Tool Catalog
          </Button>
        </EmptyState>
      </PageSection>
    );
  }

  const metadata = tool.metadata || {};
  const spec = tool.spec || {};
  const rawStatus = tool.status || {};
  const labels = metadata.labels || {};
  const annotations = metadata.annotations || {};

  // Extract conditions from raw Deployment/StatefulSet status
  const statusObj = typeof rawStatus === 'object' && rawStatus !== null ? rawStatus : {};
  const conditions: StatusCondition[] = (statusObj as Record<string, unknown>).conditions as StatusCondition[] || [];

  // Use computed readyStatus from backend
  const readyStatus = tool.readyStatus || 'Not Ready';
  const isReady = readyStatus === 'Ready';

  // If route check fails or is loading, default to false (in-cluster URL is safer default)
  const hasRoute = routeStatusData?.hasRoute ?? false;

  // Determine the appropriate URL based on route existence
  // External URL: http://{name}.{namespace}.{domainName}:8080 (via HTTPRoute)
  // In-cluster URL: http://{name}-mcp.{namespace}.svc.cluster.local:8000
  const domainName = dashboardConfig?.domainName || 'localtest.me';
  const toolExternalUrl = hasRoute
    ? `http://${name}.${namespace}.${domainName}:8080`
    : `http://${name}-mcp.${namespace}.svc.cluster.local:8000`;

  // In-cluster URL for MCP server (used by MCP Inspector which runs in-cluster)
  // Service naming: {name}-mcp on port 8000
  const mcpInClusterUrl = `http://${name}-mcp.${namespace}.svc.cluster.local:8000/mcp`;

  // Construct MCP Inspector URL with pre-configured server
  // MCP Inspector runs in-cluster, so it needs the in-cluster URL
  const getMcpInspectorUrl = () => {
    if (!dashboardConfig?.mcpInspector) return null;
    const encodedServerUrl = encodeURIComponent(mcpInClusterUrl);
    return `${dashboardConfig.mcpInspector}?serverUrl=${encodedServerUrl}&transport=streamable-http`;
  };

  const toggleToolExpanded = (toolName: string) => {
    setExpandedTools((prev) => ({
      ...prev,
      [toolName]: !prev[toolName],
    }));
  };

  const mcpTools: MCPToolInfo[] = connectMutation.data?.tools || [];

  return (
    <>
      <PageSection variant="light">
        <Breadcrumb>
          <BreadcrumbItem
            to="/tools"
            onClick={(e) => {
              e.preventDefault();
              navigate('/tools');
            }}
          >
            Tool Catalog
          </BreadcrumbItem>
          <BreadcrumbItem isActive>{name}</BreadcrumbItem>
        </Breadcrumb>
        <Split hasGutter style={{ marginTop: '16px' }}>
          <SplitItem>
            <Title headingLevel="h1">{name}</Title>
          </SplitItem>
          <SplitItem>
            <Label color={
              readyStatus === 'Ready' ? 'green'
                : readyStatus === 'Progressing' ? 'blue'
                : readyStatus === 'Failed' ? 'red'
                : 'orange'
            }>
              {readyStatus}
            </Label>
          </SplitItem>
          <SplitItem isFilled />
          <SplitItem>
            <Flex>
              <FlexItem>
                <Label color="blue">
                  {labels['kagenti.io/protocol']?.toUpperCase() || 'MCP'}
                </Label>
              </FlexItem>
              {tool.workloadType && (
                <FlexItem>
                  <Label color="grey">
                    {tool.workloadType === 'statefulset' ? 'StatefulSet' : 'Deployment'}
                  </Label>
                </FlexItem>
              )}
              <FlexItem>
                <Dropdown
                  isOpen={actionsMenuOpen}
                  onSelect={() => setActionsMenuOpen(false)}
                  onOpenChange={(isOpen) => setActionsMenuOpen(isOpen)}
                  toggle={(toggleRef: React.Ref<MenuToggleElement>) => (
                    <MenuToggle
                      ref={toggleRef}
                      onClick={() => setActionsMenuOpen(!actionsMenuOpen)}
                      isExpanded={actionsMenuOpen}
                    >
                      Actions
                    </MenuToggle>
                  )}
                  popperProps={{ position: 'right' }}
                >
                  <DropdownList>
                    <DropdownItem
                      key="delete"
                      onClick={() => {
                        setActionsMenuOpen(false);
                        setDeleteModalOpen(true);
                      }}
                      isDanger
                    >
                      Delete tool
                    </DropdownItem>
                  </DropdownList>
                </Dropdown>
              </FlexItem>
            </Flex>
          </SplitItem>
        </Split>
      </PageSection>

      <PageSection>
        <Tabs
          activeKey={activeTab}
          onSelect={(_e, key) => setActiveTab(key)}
          aria-label="Tool details tabs"
        >
          <Tab eventKey={0} title={<TabTitleText>Details</TabTitleText>}>
            <Grid hasGutter style={{ marginTop: '16px' }}>
              <GridItem md={6}>
                <Card>
                  <CardTitle>Tool Information</CardTitle>
                  <CardBody>
                    <DescriptionList isCompact>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Name</DescriptionListTerm>
                        <DescriptionListDescription>
                          {metadata.name}
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Namespace</DescriptionListTerm>
                        <DescriptionListDescription>
                          {metadata.namespace}
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Description</DescriptionListTerm>
                        <DescriptionListDescription>
                          {annotations['kagenti.io/description'] || spec.description || 'No description available'}
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Workload Type</DescriptionListTerm>
                        <DescriptionListDescription>
                          <Label color="grey" isCompact>
                            {tool.workloadType === 'statefulset' ? 'StatefulSet' : 'Deployment'}
                          </Label>
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Replicas</DescriptionListTerm>
                        <DescriptionListDescription>
                          {(() => {
                            const desired = spec.replicas ?? 1;
                            const ready = (statusObj as Record<string, unknown>).readyReplicas
                              || (statusObj as Record<string, unknown>).ready_replicas
                              || 0;
                            return `${ready}/${desired}`;
                          })()}
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Created</DescriptionListTerm>
                        <DescriptionListDescription>
                          {(metadata.creationTimestamp || metadata.creation_timestamp)
                            ? new Date(metadata.creationTimestamp || metadata.creation_timestamp!).toLocaleString()
                            : 'N/A'}
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      <DescriptionListGroup>
                        <DescriptionListTerm>UID</DescriptionListTerm>
                        <DescriptionListDescription>
                          <code style={{ fontSize: '0.85em' }}>
                            {metadata.uid || 'N/A'}
                          </code>
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                    </DescriptionList>
                  </CardBody>
                </Card>
              </GridItem>

              <GridItem md={6}>
                <Card style={{ marginBottom: '16px' }}>
                  <CardTitle>Endpoint</CardTitle>
                  <CardBody>
                    <DescriptionList isCompact>
                      <DescriptionListGroup>
                        <DescriptionListTerm>MCP Server URL</DescriptionListTerm>
                        <DescriptionListDescription>
                          <ClipboardCopy isReadOnly hoverTip="Copy" clickTip="Copied">
                            {toolExternalUrl}
                          </ClipboardCopy>
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                    </DescriptionList>
                  </CardBody>
                </Card>

                {tool.service && (
                  <Card>
                    <CardTitle>Service</CardTitle>
                    <CardBody>
                      <DescriptionList isCompact>
                        <DescriptionListGroup>
                          <DescriptionListTerm>Service Name</DescriptionListTerm>
                          <DescriptionListDescription>
                            {tool.service.name}
                          </DescriptionListDescription>
                        </DescriptionListGroup>
                        {tool.service.type && (
                          <DescriptionListGroup>
                            <DescriptionListTerm>Type</DescriptionListTerm>
                            <DescriptionListDescription>
                              {tool.service.type}
                            </DescriptionListDescription>
                          </DescriptionListGroup>
                        )}
                        {tool.service.clusterIP && (
                          <DescriptionListGroup>
                            <DescriptionListTerm>Cluster IP</DescriptionListTerm>
                            <DescriptionListDescription>
                              {tool.service.clusterIP}
                            </DescriptionListDescription>
                          </DescriptionListGroup>
                        )}
                        {tool.service.ports && tool.service.ports.length > 0 && (
                          <DescriptionListGroup>
                            <DescriptionListTerm>Ports</DescriptionListTerm>
                            <DescriptionListDescription>
                              {tool.service.ports.map((port) => (
                                <Label key={port.name || port.port} isCompact style={{ marginRight: '4px' }}>
                                  {port.name ? `${port.name}: ` : ''}{port.port}{port.targetPort ? ` → ${port.targetPort}` : ''}/{port.protocol || 'TCP'}
                                </Label>
                              ))}
                            </DescriptionListDescription>
                          </DescriptionListGroup>
                        )}
                      </DescriptionList>
                    </CardBody>
                  </Card>
                )}
              </GridItem>
            </Grid>
          </Tab>

          <Tab eventKey={1} title={<TabTitleText>Status</TabTitleText>}>
            <Card style={{ marginTop: '16px' }}>
              <CardTitle>Status Conditions</CardTitle>
              <CardBody>
                {conditions.length === 0 ? (
                  <Alert variant="info" title="No status conditions available" isInline />
                ) : (
                  <Table aria-label="Status conditions" variant="compact">
                    <Thead>
                      <Tr>
                        <Th>Type</Th>
                        <Th>Status</Th>
                        <Th>Reason</Th>
                        <Th>Message</Th>
                        <Th>Last Transition</Th>
                      </Tr>
                    </Thead>
                    <Tbody>
                      {conditions.map((condition, index) => (
                        <Tr key={`${condition.type}-${index}`}>
                          <Td dataLabel="Type">{condition.type}</Td>
                          <Td dataLabel="Status">
                            <Label
                              color={condition.status === 'True' ? 'green' : 'red'}
                              isCompact
                            >
                              {condition.status}
                            </Label>
                          </Td>
                          <Td dataLabel="Reason">{condition.reason || '-'}</Td>
                          <Td dataLabel="Message">
                            {condition.message || '-'}
                          </Td>
                          <Td dataLabel="Last Transition">
                            {(condition.lastTransitionTime || (condition as unknown as Record<string, unknown>).last_transition_time)
                              ? new Date(
                                  (condition.lastTransitionTime || (condition as unknown as Record<string, unknown>).last_transition_time) as string
                                ).toLocaleString()
                              : '-'}
                          </Td>
                        </Tr>
                      ))}
                    </Tbody>
                  </Table>
                )}
              </CardBody>
            </Card>
          </Tab>

          <Tab eventKey={2} title={<TabTitleText>MCP Tools</TabTitleText>}>
            <Card style={{ marginTop: '16px' }}>
              <CardTitle>
                <Split hasGutter>
                  <SplitItem>Available MCP Tools</SplitItem>
                  <SplitItem isFilled />
                  <SplitItem>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => connectMutation.mutate()}
                      isLoading={connectMutation.isPending}
                      isDisabled={!isReady}
                    >
                      {connectMutation.isPending ? 'Connecting...' : 'Connect & List Tools'}
                    </Button>
                  </SplitItem>
                </Split>
              </CardTitle>
              <CardBody>
                {!isReady ? (
                  <Alert variant="warning" title="Tool not ready" isInline>
                    The MCP server must be ready before you can list available tools.
                  </Alert>
                ) : connectMutation.isError ? (
                  <Alert variant="danger" title="Connection failed" isInline>
                    {connectMutation.error instanceof Error
                      ? connectMutation.error.message
                      : 'Failed to connect to MCP server'}
                  </Alert>
                ) : mcpTools.length === 0 ? (
                  <Alert variant="info" title="No tools loaded" isInline>
                    Click "Connect & List Tools" to discover available MCP tools from this server.
                  </Alert>
                ) : (
                  <div>
                    {mcpTools.map((mcpTool) => (
                      <ExpandableSection
                        key={mcpTool.name}
                        toggleText={mcpTool.name}
                        isExpanded={expandedTools[mcpTool.name] || false}
                        onToggle={() => toggleToolExpanded(mcpTool.name)}
                        style={{ marginBottom: '8px' }}
                      >
                        <Card isFlat>
                          <CardBody>
                            <DescriptionList isCompact>
                              <DescriptionListGroup>
                                <DescriptionListTerm>Description</DescriptionListTerm>
                                <DescriptionListDescription>
                                  {mcpTool.description || 'No description'}
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                              {mcpTool.input_schema && (
                                <DescriptionListGroup>
                                  <DescriptionListTerm>Input Schema</DescriptionListTerm>
                                  <DescriptionListDescription>
                                    <pre
                                      style={{
                                        backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
                                        padding: '8px',
                                        borderRadius: '4px',
                                        fontSize: '0.8em',
                                        overflow: 'auto',
                                        maxHeight: '200px',
                                      }}
                                    >
                                      {JSON.stringify(mcpTool.input_schema, null, 2)}
                                    </pre>
                                  </DescriptionListDescription>
                                </DescriptionListGroup>
                              )}
                            </DescriptionList>
                            <Button
                              variant="secondary"
                              size="sm"
                              style={{ marginTop: '12px' }}
                              icon={<PlayIcon />}
                              onClick={() => openInvokeModal(mcpTool)}
                            >
                              Invoke Tool
                            </Button>
                          </CardBody>
                        </Card>
                      </ExpandableSection>
                    ))}
                  </div>
                )}
              </CardBody>
            </Card>
          </Tab>

          <Tab eventKey={3} title={<TabTitleText>MCP Inspector</TabTitleText>}>
            <Card style={{ marginTop: '16px' }}>
              <CardTitle>Launch MCP Inspector</CardTitle>
              <CardBody>
                <p style={{ marginBottom: '16px' }}>
                  Open the MCP Inspector to interactively explore and test this MCP server.
                  The inspector will be pre-configured to connect to this tool's MCP endpoint.
                </p>

                <DescriptionList isCompact style={{ marginBottom: '24px' }}>
                  <DescriptionListGroup>
                    <DescriptionListTerm>MCP Server URL (in-cluster)</DescriptionListTerm>
                    <DescriptionListDescription>
                      <ClipboardCopy isReadOnly hoverTip="Copy" clickTip="Copied">
                        {mcpInClusterUrl}
                      </ClipboardCopy>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Transport</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="blue" isCompact>streamable-http</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>

                {!isReady ? (
                  <Alert variant="warning" title="Tool not ready" isInline>
                    The MCP server must be running before you can connect with the inspector.
                  </Alert>
                ) : getMcpInspectorUrl() ? (
                  <Button
                    variant="primary"
                    icon={<ExternalLinkAltIcon />}
                    iconPosition="end"
                    component="a"
                    href={getMcpInspectorUrl()!}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open MCP Inspector
                  </Button>
                ) : (
                  <Alert variant="info" title="MCP Inspector not configured" isInline>
                    The MCP Inspector URL is not available. Please check your configuration.
                  </Alert>
                )}

                {dashboardConfig?.mcpInspector && (
                  <p style={{ marginTop: '16px', fontSize: '0.85em', color: 'var(--pf-v5-global--Color--200)' }}>
                    MCP Inspector: <a href={dashboardConfig.mcpInspector} target="_blank" rel="noopener noreferrer">{dashboardConfig.mcpInspector}</a>
                  </p>
                )}
              </CardBody>
            </Card>
          </Tab>

          <Tab eventKey={4} title={<TabTitleText>YAML</TabTitleText>}>
            <Card style={{ marginTop: '16px' }}>
              <CardBody>
                <pre
                  style={{
                    backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
                    padding: '16px',
                    borderRadius: '4px',
                    overflow: 'auto',
                    maxHeight: '500px',
                    fontSize: '0.85em',
                  }}
                >
                  {yaml.dump(
                    {
                      apiVersion: 'apps/v1',
                      kind: tool.workloadType === 'statefulset' ? 'StatefulSet' : 'Deployment',
                      metadata: {
                        ...tool.metadata,
                        managedFields: undefined,
                      },
                      spec: tool.spec,
                      status: tool.status,
                    },
                    { noRefs: true, lineWidth: -1 }
                  )}
                </pre>
              </CardBody>
            </Card>
          </Tab>
        </Tabs>
      </PageSection>

      {/* Invoke Tool Modal */}
      <Modal
        variant={ModalVariant.medium}
        title={`Invoke: ${selectedTool?.name || ''}`}
        isOpen={invokeModalOpen}
        onClose={closeInvokeModal}
        actions={[
          <Button
            key="invoke"
            variant="primary"
            onClick={handleInvoke}
            isLoading={invokeMutation.isPending}
            isDisabled={invokeMutation.isPending}
            icon={<PlayIcon />}
          >
            {invokeMutation.isPending ? 'Invoking...' : 'Invoke'}
          </Button>,
          <Button key="cancel" variant="link" onClick={closeInvokeModal}>
            Close
          </Button>,
        ]}
      >
        {selectedTool && (
          <>
            {selectedTool.description && (
              <p style={{ marginBottom: '16px', color: 'var(--pf-v5-global--Color--200)' }}>
                {selectedTool.description}
              </p>
            )}

            <Form>
              {selectedTool.input_schema?.properties &&
              Object.keys(selectedTool.input_schema.properties).length > 0 ? (
                Object.entries(selectedTool.input_schema.properties).map(([key, prop]) => {
                  const isRequired = selectedTool.input_schema?.required?.includes(key);
                  const propType = prop.type || 'string';

                  return (
                    <FormGroup
                      key={key}
                      label={key}
                      isRequired={isRequired}
                      fieldId={`arg-${key}`}
                    >
                      {propType === 'boolean' ? (
                        <Switch
                          id={`arg-${key}`}
                          isChecked={toolArgs[key] as boolean}
                          onChange={(_e, checked) => updateArg(key, checked)}
                          label="true"
                          labelOff="false"
                        />
                      ) : propType === 'number' || propType === 'integer' ? (
                        <TextInput
                          id={`arg-${key}`}
                          type="number"
                          value={String(toolArgs[key] || '')}
                          onChange={(_e, val) => updateArg(key, val ? Number(val) : 0)}
                        />
                      ) : prop.enum ? (
                        <TextInput
                          id={`arg-${key}`}
                          value={String(toolArgs[key] || '')}
                          onChange={(_e, val) => updateArg(key, val)}
                          placeholder={`Options: ${prop.enum.join(', ')}`}
                        />
                      ) : (
                        <TextInput
                          id={`arg-${key}`}
                          value={String(toolArgs[key] || '')}
                          onChange={(_e, val) => updateArg(key, val)}
                        />
                      )}
                      {prop.description && (
                        <FormHelperText>
                          <HelperText>
                            <HelperTextItem>{prop.description}</HelperTextItem>
                          </HelperText>
                        </FormHelperText>
                      )}
                    </FormGroup>
                  );
                })
              ) : (
                <Alert variant="info" title="No arguments required" isInline>
                  This tool does not require any input arguments.
                </Alert>
              )}
            </Form>

            {/* Error display */}
            {invokeMutation.isError && (
              <Alert
                variant="danger"
                title="Invocation failed"
                isInline
                style={{ marginTop: '16px' }}
              >
                {invokeMutation.error instanceof Error
                  ? invokeMutation.error.message
                  : 'An unexpected error occurred'}
              </Alert>
            )}

            {/* Result display */}
            {invokeResult && (
              <div style={{ marginTop: '16px' }}>
                <Title headingLevel="h4" size="md" style={{ marginBottom: '8px' }}>
                  Result
                </Title>
                {invokeResult.isError && (
                  <Alert variant="warning" title="Tool returned an error" isInline isPlain />
                )}
                <pre
                  style={{
                    backgroundColor: invokeResult.isError
                      ? 'var(--pf-v5-global--danger-color--100)'
                      : 'var(--pf-v5-global--BackgroundColor--200)',
                    color: invokeResult.isError ? '#fff' : 'inherit',
                    padding: '12px',
                    borderRadius: '4px',
                    overflow: 'auto',
                    maxHeight: '300px',
                    fontSize: '0.85em',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {invokeResult.content?.map((item) => {
                    if (item.type === 'text' && item.text) {
                      return item.text;
                    }
                    if (item.type === 'data' && item.data) {
                      return JSON.stringify(item.data, null, 2);
                    }
                    if (item.value) {
                      return item.value;
                    }
                    return JSON.stringify(item, null, 2);
                  }).join('\n') || JSON.stringify(invokeResult, null, 2)}
                </pre>
              </div>
            )}
          </>
        )}
      </Modal>

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
            isDisabled={deleteMutation.isPending || deleteConfirmText !== name}
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
            The tool <strong>{name}</strong> will be permanently deleted.
            This action cannot be undone.
          </Text>
          <Text component="small" style={{ marginTop: '16px', display: 'block' }}>
            Type <strong>{name}</strong> to confirm deletion:
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
