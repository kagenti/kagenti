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
} from '@patternfly/react-core';
import {
  Table,
  Thead,
  Tr,
  Th,
  Tbody,
  Td,
} from '@patternfly/react-table';
import { ToolboxIcon } from '@patternfly/react-icons';
import { useQuery, useMutation } from '@tanstack/react-query';

import { toolService } from '@/services/api';

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
  input_schema?: object;
}

export const ToolDetailPage: React.FC = () => {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = React.useState<string | number>(0);
  const [expandedTools, setExpandedTools] = React.useState<Record<string, boolean>>({});

  const { data: tool, isLoading, isError, error } = useQuery({
    queryKey: ['tool', namespace, name],
    queryFn: () => toolService.get(namespace!, name!),
    enabled: !!namespace && !!name,
  });

  const connectMutation = useMutation({
    mutationFn: () => toolService.connect(namespace!, name!),
  });

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
  const status = tool.status || {};
  const labels = metadata.labels || {};
  const conditions: StatusCondition[] = status.conditions || [];

  const isReady = conditions.some(
    (c) => c.type === 'Ready' && c.status === 'True'
  );

  const toolUrl = `http://${name}.${namespace}.localtest.me:8080`;

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
            <Label color={isReady ? 'green' : 'red'}>
              {isReady ? 'Ready' : 'Not Ready'}
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
                          {spec.description || 'No description available'}
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Created</DescriptionListTerm>
                        <DescriptionListDescription>
                          {metadata.creationTimestamp
                            ? new Date(metadata.creationTimestamp).toLocaleString()
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
                <Card>
                  <CardTitle>Endpoint</CardTitle>
                  <CardBody>
                    <DescriptionList isCompact>
                      <DescriptionListGroup>
                        <DescriptionListTerm>MCP Server URL</DescriptionListTerm>
                        <DescriptionListDescription>
                          <ClipboardCopy isReadOnly hoverTip="Copy" clickTip="Copied">
                            {toolUrl}
                          </ClipboardCopy>
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                    </DescriptionList>
                  </CardBody>
                </Card>
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
                            {condition.lastTransitionTime
                              ? new Date(condition.lastTransitionTime).toLocaleString()
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
                              isDisabled
                            >
                              Invoke Tool (Coming Soon)
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

          <Tab eventKey={3} title={<TabTitleText>YAML</TabTitleText>}>
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
                  {JSON.stringify(tool, null, 2)}
                </pre>
              </CardBody>
            </Card>
          </Tab>
        </Tabs>
      </PageSection>
    </>
  );
};
