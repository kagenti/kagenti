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
} from '@patternfly/react-core';
import {
  Table,
  Thead,
  Tr,
  Th,
  Tbody,
  Td,
} from '@patternfly/react-table';
import { CubesIcon, ExternalLinkAltIcon } from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';

import { agentService } from '@/services/api';
import { AgentChat } from '@/components/AgentChat';

interface StatusCondition {
  type: string;
  status: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
}

interface BuildStatus {
  name: string;
  namespace: string;
  phase: string;
  conditions: StatusCondition[];
  image?: string;
  imageTag?: string;
  startTime?: string;
  completionTime?: string;
}

export const AgentDetailPage: React.FC = () => {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = React.useState<string | number>(0);

  const { data: agent, isLoading, isError, error } = useQuery({
    queryKey: ['agent', namespace, name],
    queryFn: () => agentService.get(namespace!, name!),
    enabled: !!namespace && !!name,
  });

  // Check if agent was built from source (has buildRef)
  const buildRefName = agent?.spec?.imageSource?.buildRef?.name;

  // Fetch build status if agent has a buildRef
  const { data: buildStatus, isLoading: isBuildStatusLoading } = useQuery<BuildStatus>({
    queryKey: ['agentBuild', namespace, buildRefName],
    queryFn: () => agentService.getBuildStatus(namespace!, buildRefName!),
    enabled: !!namespace && !!buildRefName,
    refetchInterval: (data) => {
      // Poll every 5 seconds if build is still in progress
      if (data?.state?.data?.phase && !['Completed', 'Failed'].includes(data.state.data.phase)) {
        return 5000;
      }
      return false;
    },
  });

  if (isLoading) {
    return (
      <PageSection>
        <div className="kagenti-loading-center">
          <Spinner size="lg" aria-label="Loading agent details" />
        </div>
      </PageSection>
    );
  }

  if (isError || !agent) {
    return (
      <PageSection>
        <EmptyState>
          <EmptyStateHeader
            titleText="Agent not found"
            icon={<EmptyStateIcon icon={CubesIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>
            {error instanceof Error
              ? error.message
              : `Could not load agent "${name}" in namespace "${namespace}".`}
          </EmptyStateBody>
          <Button variant="primary" onClick={() => navigate('/agents')}>
            Back to Agent Catalog
          </Button>
        </EmptyState>
      </PageSection>
    );
  }

  const metadata = agent.metadata || {};
  const spec = agent.spec || {};
  const status = agent.status || {};
  const labels = metadata.labels || {};
  const conditions: StatusCondition[] = status.conditions || [];

  const isReady = conditions.some(
    (c) => c.type === 'Ready' && c.status === 'True'
  );

  const gitSource = spec.source?.git;
  // Agent URL for off-cluster access (namespace is not included in URL)
  const agentUrl = `http://${name}.localtest.me:8080`;

  return (
    <>
      <PageSection variant="light">
        <Breadcrumb>
          <BreadcrumbItem
            to="/agents"
            onClick={(e) => {
              e.preventDefault();
              navigate('/agents');
            }}
          >
            Agent Catalog
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
                  {labels['kagenti.io/protocol']?.toUpperCase() || 'A2A'}
                </Label>
              </FlexItem>
              {labels['kagenti.io/framework'] && (
                <FlexItem>
                  <Label color="purple">{labels['kagenti.io/framework']}</Label>
                </FlexItem>
              )}
            </Flex>
          </SplitItem>
        </Split>
      </PageSection>

      <PageSection>
        <Tabs
          activeKey={activeTab}
          onSelect={(_e, key) => setActiveTab(key)}
          aria-label="Agent details tabs"
        >
          <Tab eventKey={0} title={<TabTitleText>Details</TabTitleText>}>
            <Grid hasGutter style={{ marginTop: '16px' }}>
              <GridItem md={6}>
                <Card>
                  <CardTitle>Agent Information</CardTitle>
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
                        <DescriptionListTerm>Agent URL</DescriptionListTerm>
                        <DescriptionListDescription>
                          <ClipboardCopy isReadOnly hoverTip="Copy" clickTip="Copied">
                            {agentUrl}
                          </ClipboardCopy>
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Agent Card</DescriptionListTerm>
                        <DescriptionListDescription>
                          <Button
                            variant="link"
                            isInline
                            icon={<ExternalLinkAltIcon />}
                            iconPosition="end"
                            component="a"
                            href={`${agentUrl}/.well-known/agent.json`}
                            target="_blank"
                          >
                            View Agent Card
                          </Button>
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                    </DescriptionList>
                  </CardBody>
                </Card>
              </GridItem>

              {gitSource && (
                <GridItem md={12}>
                  <Card>
                    <CardTitle>Source</CardTitle>
                    <CardBody>
                      <DescriptionList isCompact isHorizontal>
                        <DescriptionListGroup>
                          <DescriptionListTerm>Git URL</DescriptionListTerm>
                          <DescriptionListDescription>
                            <Button
                              variant="link"
                              isInline
                              icon={<ExternalLinkAltIcon />}
                              iconPosition="end"
                              component="a"
                              href={gitSource.url}
                              target="_blank"
                            >
                              {gitSource.url}
                            </Button>
                          </DescriptionListDescription>
                        </DescriptionListGroup>
                        <DescriptionListGroup>
                          <DescriptionListTerm>Path</DescriptionListTerm>
                          <DescriptionListDescription>
                            <code>{gitSource.path || '/'}</code>
                          </DescriptionListDescription>
                        </DescriptionListGroup>
                        <DescriptionListGroup>
                          <DescriptionListTerm>Branch</DescriptionListTerm>
                          <DescriptionListDescription>
                            <code>{gitSource.branch || 'main'}</code>
                          </DescriptionListDescription>
                        </DescriptionListGroup>
                        {spec.image?.tag && (
                          <DescriptionListGroup>
                            <DescriptionListTerm>Image Tag</DescriptionListTerm>
                            <DescriptionListDescription>
                              <Label isCompact>{spec.image.tag}</Label>
                            </DescriptionListDescription>
                          </DescriptionListGroup>
                        )}
                      </DescriptionList>
                    </CardBody>
                  </Card>
                </GridItem>
              )}

              {/* Build Status - shown when agent was built from source */}
              {buildRefName && (
                <GridItem md={12}>
                  <Card>
                    <CardTitle>Build Status</CardTitle>
                    <CardBody>
                      {isBuildStatusLoading ? (
                        <Spinner size="md" aria-label="Loading build status" />
                      ) : buildStatus ? (
                        <>
                          <DescriptionList isCompact isHorizontal>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Phase</DescriptionListTerm>
                              <DescriptionListDescription>
                                <Label
                                  color={
                                    buildStatus.phase === 'Completed'
                                      ? 'green'
                                      : buildStatus.phase === 'Failed'
                                        ? 'red'
                                        : 'blue'
                                  }
                                >
                                  {buildStatus.phase}
                                </Label>
                              </DescriptionListDescription>
                            </DescriptionListGroup>
                            {buildStatus.image && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Image</DescriptionListTerm>
                                <DescriptionListDescription>
                                  <code>
                                    {buildStatus.image}
                                    {buildStatus.imageTag && `:${buildStatus.imageTag}`}
                                  </code>
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                            {buildStatus.startTime && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Started</DescriptionListTerm>
                                <DescriptionListDescription>
                                  {new Date(buildStatus.startTime).toLocaleString()}
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                            {buildStatus.completionTime && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Completed</DescriptionListTerm>
                                <DescriptionListDescription>
                                  {new Date(buildStatus.completionTime).toLocaleString()}
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                          </DescriptionList>
                          {buildStatus.conditions.length > 0 && (
                            <Table
                              aria-label="Build conditions"
                              variant="compact"
                              style={{ marginTop: '16px' }}
                            >
                              <Thead>
                                <Tr>
                                  <Th>Type</Th>
                                  <Th>Status</Th>
                                  <Th>Reason</Th>
                                  <Th>Message</Th>
                                </Tr>
                              </Thead>
                              <Tbody>
                                {buildStatus.conditions.map((cond, idx) => (
                                  <Tr key={`${cond.type}-${idx}`}>
                                    <Td dataLabel="Type">{cond.type}</Td>
                                    <Td dataLabel="Status">
                                      <Label
                                        color={cond.status === 'True' ? 'green' : 'red'}
                                        isCompact
                                      >
                                        {cond.status}
                                      </Label>
                                    </Td>
                                    <Td dataLabel="Reason">{cond.reason || '-'}</Td>
                                    <Td dataLabel="Message">{cond.message || '-'}</Td>
                                  </Tr>
                                ))}
                              </Tbody>
                            </Table>
                          )}
                        </>
                      ) : (
                        <Alert
                          variant="info"
                          title="Build information not available"
                          isInline
                        />
                      )}
                    </CardBody>
                  </Card>
                </GridItem>
              )}
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

          <Tab eventKey={2} title={<TabTitleText>Chat</TabTitleText>}>
            <div style={{ marginTop: '16px' }}>
              {isReady ? (
                <AgentChat namespace={namespace!} name={name!} />
              ) : (
                <Card>
                  <CardBody>
                    <Alert
                      variant="warning"
                      title="Agent not ready"
                      isInline
                    >
                      The agent must be in Ready state before you can chat with it.
                    </Alert>
                  </CardBody>
                </Card>
              )}
            </div>
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
                  {JSON.stringify(agent, null, 2)}
                </pre>
              </CardBody>
            </Card>
          </Tab>
        </Tabs>
      </PageSection>
    </>
  );
};
