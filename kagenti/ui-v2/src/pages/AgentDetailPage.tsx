// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { copyToClipboard } from '../utils/clipboard';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
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
  Alert,
  Grid,
  GridItem,
  ClipboardCopy,
  Split,
  SplitItem,
  Flex,
  FlexItem,
  ExpandableSection,
  Text,
  TextContent,
  TextVariants,
  List,
  ListItem,
  Modal,
  ModalVariant,
  TextInput,
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
  ExternalLinkAltIcon,
  ExclamationTriangleIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import yaml from 'js-yaml';

import { agentService, chatService, shipwrightService, ShipwrightBuildInfo } from '@/services/api';
import { AgentChat } from '@/components/AgentChat';

interface StatusCondition {
  type: string;
  status: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
  last_transition_time?: string; // snake_case from K8s API
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

interface AgentCardSkill {
  id: string;
  name: string;
  description?: string;
  examples?: string[];
  tags?: string[];
}

interface AgentCard {
  name: string;
  description?: string;
  version: string;
  url: string;
  protocolVersion?: string;
  preferredTransport?: string;
  capabilities?: {
    streaming?: boolean;
  };
  defaultInputModes?: string[];
  defaultOutputModes?: string[];
  skills?: AgentCardSkill[];
}

export const AgentDetailPage: React.FC = () => {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = React.useState<string | number>(0);
  const [isAgentCardExpanded, setIsAgentCardExpanded] = React.useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = React.useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = React.useState('');
  const [actionsMenuOpen, setActionsMenuOpen] = React.useState(false);

  const deleteMutation = useMutation({
    mutationFn: () => agentService.delete(namespace!, name!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] });
      navigate('/agents');
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

  const { data: agent, isLoading, isError, error } = useQuery({
    queryKey: ['agent', namespace, name],
    queryFn: () => agentService.get(namespace!, name!),
    enabled: !!namespace && !!name,
    refetchInterval: (query) => {
      // Poll every 5 seconds if agent is not ready
      // Use readyStatus from backend (handles Deployment, StatefulSet, Job)
      // For Jobs: stop polling once Completed or Failed, but continue for Running
      const readyStatus = query.state.data?.readyStatus;
      const isStable = readyStatus === 'Ready' || readyStatus === 'Completed' || readyStatus === 'Failed';
      return isStable ? false : 5000;
    },
  });

  // Check for Shipwright Build if agent is not found
  // This handles the case where a build is in progress but Agent CRD doesn't exist yet
  const { data: shipwrightBuildInfo, isLoading: isShipwrightBuildLoading } = useQuery({
    queryKey: ['shipwrightBuildInfo', namespace, name],
    queryFn: () => shipwrightService.getBuildInfo(namespace!, name!),
    enabled: !!namespace && !!name && isError && !isLoading,
    retry: false, // Don't retry if build doesn't exist
  });

  // Redirect to build page if a Shipwright Build exists but Agent doesn't
  React.useEffect(() => {
    if (isError && !isLoading && shipwrightBuildInfo && shipwrightBuildInfo.buildRegistered) {
      navigate(`/agents/${namespace}/${name}/build`, { replace: true });
    }
  }, [isError, isLoading, shipwrightBuildInfo, namespace, name, navigate]);

  // Check if agent was built from source (has buildRef for AgentBuild)
  const buildRefName = agent?.spec?.imageSource?.buildRef?.name;

  // Check if agent was built with Shipwright (has annotation)
  const shipwrightBuildName = agent?.metadata?.annotations?.['kagenti.io/shipwright-build'];

  // Fetch AgentBuild status if agent has a buildRef
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

  // Fetch Shipwright build info if agent has shipwright annotation
  const { data: shipwrightBuildStatus, isLoading: isShipwrightBuildStatusLoading } = useQuery<ShipwrightBuildInfo>({
    queryKey: ['shipwrightBuildStatus', namespace, shipwrightBuildName],
    queryFn: () => shipwrightService.getBuildInfo(namespace!, shipwrightBuildName!),
    enabled: !!namespace && !!shipwrightBuildName && !!agent,
  });

  // Check if agent is ready to fetch agent card
  // Use readyStatus from backend (handles Deployment, StatefulSet, Job)
  // All workload types now use consistent status values: Ready, Progressing, Not Ready, Failed
  const agentReadyStatus = agent?.readyStatus;
  const isAgentReady = agentReadyStatus === 'Ready' || agentReadyStatus === 'Progressing';

  // Fetch agent card if agent is ready
  const { data: agentCard, isLoading: isAgentCardLoading } = useQuery<AgentCard>({
    queryKey: ['agentCard', namespace, name],
    queryFn: () => chatService.getAgentCard(namespace!, name!),
    enabled: !!namespace && !!name && isAgentReady,
  });

  // Check if an HTTPRoute/Route exists for this agent
  const { data: routeStatusData } = useQuery({
    queryKey: ['agent-route-status', namespace, name],
    queryFn: async () => {
      try {
        return await agentService.getRouteStatus(namespace!, name!);
      } catch (error) {
        console.warn('Failed to check route status:', error);
        return { hasRoute: false };
      }
    },
    enabled: !!namespace && !!name,
    retry: false,
    staleTime: 30000, // Cache for 30 seconds
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
    // Show loading while checking for Shipwright build
    if (isShipwrightBuildLoading) {
      return (
        <PageSection>
          <div className="kagenti-loading-center">
            <Spinner size="lg" aria-label="Checking for build..." />
          </div>
        </PageSection>
      );
    }

    // If a Shipwright build exists, the useEffect will redirect
    // Show empty state only if no build exists
    if (shipwrightBuildInfo?.buildRegistered) {
      return (
        <PageSection>
          <div className="kagenti-loading-center">
            <Spinner size="lg" aria-label="Redirecting to build page..." />
          </div>
        </PageSection>
      );
    }

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

  // Use computed readyStatus from backend (handles Deployment, StatefulSet, Job)
  // Fallback to checking conditions for backward compatibility
  const readyStatus = agent.readyStatus;
  // All workload types now use consistent status values: Ready, Progressing, Not Ready, Failed
  const isRunningOrReady = readyStatus === 'Ready' || readyStatus === 'Progressing';
  const isReady = isRunningOrReady || conditions.some(
    (c) => (c.type === 'Ready' || c.type === 'Available') && c.status === 'True'
  );

  // Get service info (new for Deployment-based agents)
  const serviceInfo = agent.service;

  // Get description from spec (legacy Agent CRD) or annotations (Deployment)
  const description =
    spec.description ||
    metadata.annotations?.['kagenti.io/description'] ||
    'No description available';

  // Get workload type
  const workloadType = agent.workloadType || labels['kagenti.io/workload-type'] || 'deployment';

  // Get replica info for Deployments/StatefulSets
  const replicas = spec.replicas ?? 1;
  const readyReplicas = status.readyReplicas ?? status.ready_replicas ?? 0;
  const availableReplicas = status.availableReplicas ?? status.available_replicas ?? 0;
  // updatedReplicas indicates rolling update progress for StatefulSets
  const updatedReplicas = status.updatedReplicas ?? status.updated_replicas ?? 0;

  const gitSource = spec.source?.git;

  // If route check fails or is loading, default to false (in-cluster URL is safer default)
  const hasRoute = routeStatusData?.hasRoute ?? false;

  // Determine the appropriate URL based on route existence
  // External URL: http://{name}.{namespace}.localtest.me:8080 (via HTTPRoute)
  // In-cluster URL: http://{name}.{namespace}.svc.cluster.local:8000
  const agentUrl = hasRoute
    ? `http://${name}.${namespace}.localtest.me:8080`
    : `http://${name}.${namespace}.svc.cluster.local:8000`;

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
              {readyStatus || (isReady ? 'Ready' : 'Not Ready')}
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
                      Delete agent
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
                          {description}
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Workload Type</DescriptionListTerm>
                        <DescriptionListDescription>
                          <Label color={workloadType === 'job' ? 'orange' : workloadType === 'statefulset' ? 'gold' : 'grey'} isCompact>
                            {workloadType.charAt(0).toUpperCase() + workloadType.slice(1)}
                          </Label>
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Replicas</DescriptionListTerm>
                        <DescriptionListDescription>
                          {readyReplicas}/{replicas} ready
                          {availableReplicas > 0 && ` (${availableReplicas} available)`}
                          {workloadType === 'statefulset' && updatedReplicas < replicas && (
                            <Label color="blue" isCompact style={{ marginLeft: 8 }}>
                              {updatedReplicas}/{replicas} updated
                            </Label>
                          )}
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
                          <ClipboardCopy isReadOnly hoverTip="Copy" clickTip="Copied" onCopy={copyToClipboard}>
                            {agentUrl}
                          </ClipboardCopy>
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      {serviceInfo && (
                        <>
                          <DescriptionListGroup>
                            <DescriptionListTerm>Service</DescriptionListTerm>
                            <DescriptionListDescription>
                              {serviceInfo.name} ({serviceInfo.type || 'ClusterIP'})
                            </DescriptionListDescription>
                          </DescriptionListGroup>
                          <DescriptionListGroup>
                            <DescriptionListTerm>Cluster IP</DescriptionListTerm>
                            <DescriptionListDescription>
                              <code>{serviceInfo.clusterIP || 'N/A'}</code>
                            </DescriptionListDescription>
                          </DescriptionListGroup>
                          {serviceInfo.ports && serviceInfo.ports.length > 0 && (
                            <DescriptionListGroup>
                              <DescriptionListTerm>Ports</DescriptionListTerm>
                              <DescriptionListDescription>
                                <LabelGroup>
                                  {serviceInfo.ports.map((port, idx) => (
                                    <Label key={idx} isCompact>
                                      {port.name ? `${port.name}: ` : ''}
                                      {port.port}→{port.targetPort}
                                    </Label>
                                  ))}
                                </LabelGroup>
                              </DescriptionListDescription>
                            </DescriptionListGroup>
                          )}
                        </>
                      )}
                    </DescriptionList>
                  </CardBody>
                </Card>
              </GridItem>

              {/* Agent Card - Expandable section with formatted content */}
              <GridItem md={12}>
                <Card>
                  <CardTitle>Agent Card</CardTitle>
                  <CardBody>
                    {!isReady ? (
                      <Alert variant="info" title="Agent not ready" isInline>
                        The agent card will be available once the agent is running.
                      </Alert>
                    ) : isAgentCardLoading ? (
                      <Spinner size="md" aria-label="Loading agent card" />
                    ) : agentCard ? (
                      <>
                        <ExpandableSection
                          toggleText={isAgentCardExpanded ? 'Hide Agent Card Details' : 'Show Agent Card Details'}
                          isExpanded={isAgentCardExpanded}
                          onToggle={() => setIsAgentCardExpanded(!isAgentCardExpanded)}
                        >
                          <Grid hasGutter style={{ marginTop: '16px' }}>
                            {/* Basic Information */}
                            <GridItem md={6}>
                              <Card isFlat>
                                <CardTitle>Basic Information</CardTitle>
                                <CardBody>
                                  <DescriptionList isCompact>
                                    <DescriptionListGroup>
                                      <DescriptionListTerm>Name</DescriptionListTerm>
                                      <DescriptionListDescription>
                                        {agentCard.name}
                                      </DescriptionListDescription>
                                    </DescriptionListGroup>
                                    <DescriptionListGroup>
                                      <DescriptionListTerm>Version</DescriptionListTerm>
                                      <DescriptionListDescription>
                                        <Label isCompact>{agentCard.version}</Label>
                                      </DescriptionListDescription>
                                    </DescriptionListGroup>
                                    {agentCard.protocolVersion && (
                                      <DescriptionListGroup>
                                        <DescriptionListTerm>Protocol Version</DescriptionListTerm>
                                        <DescriptionListDescription>
                                          {agentCard.protocolVersion}
                                        </DescriptionListDescription>
                                      </DescriptionListGroup>
                                    )}
                                    {agentCard.preferredTransport && (
                                      <DescriptionListGroup>
                                        <DescriptionListTerm>Transport</DescriptionListTerm>
                                        <DescriptionListDescription>
                                          <Label isCompact color="blue">
                                            {agentCard.preferredTransport}
                                          </Label>
                                        </DescriptionListDescription>
                                      </DescriptionListGroup>
                                    )}
                                    <DescriptionListGroup>
                                      <DescriptionListTerm>URL</DescriptionListTerm>
                                      <DescriptionListDescription>
                                        <code style={{ fontSize: '0.85em' }}>{agentCard.url}</code>
                                      </DescriptionListDescription>
                                    </DescriptionListGroup>
                                  </DescriptionList>
                                </CardBody>
                              </Card>
                            </GridItem>

                            {/* Capabilities */}
                            <GridItem md={6}>
                              <Card isFlat>
                                <CardTitle>Capabilities</CardTitle>
                                <CardBody>
                                  <DescriptionList isCompact>
                                    <DescriptionListGroup>
                                      <DescriptionListTerm>Streaming</DescriptionListTerm>
                                      <DescriptionListDescription>
                                        <Label
                                          isCompact
                                          color={agentCard.capabilities?.streaming ? 'green' : 'gold'}
                                        >
                                          {agentCard.capabilities?.streaming ? 'Enabled' : 'Disabled'}
                                        </Label>
                                      </DescriptionListDescription>
                                    </DescriptionListGroup>
                                    {agentCard.defaultInputModes && agentCard.defaultInputModes.length > 0 && (
                                      <DescriptionListGroup>
                                        <DescriptionListTerm>Input Modes</DescriptionListTerm>
                                        <DescriptionListDescription>
                                          <LabelGroup>
                                            {agentCard.defaultInputModes.map((mode) => (
                                              <Label key={mode} isCompact color="blue">
                                                {mode}
                                              </Label>
                                            ))}
                                          </LabelGroup>
                                        </DescriptionListDescription>
                                      </DescriptionListGroup>
                                    )}
                                    {agentCard.defaultOutputModes && agentCard.defaultOutputModes.length > 0 && (
                                      <DescriptionListGroup>
                                        <DescriptionListTerm>Output Modes</DescriptionListTerm>
                                        <DescriptionListDescription>
                                          <LabelGroup>
                                            {agentCard.defaultOutputModes.map((mode) => (
                                              <Label key={mode} isCompact color="purple">
                                                {mode}
                                              </Label>
                                            ))}
                                          </LabelGroup>
                                        </DescriptionListDescription>
                                      </DescriptionListGroup>
                                    )}
                                  </DescriptionList>
                                </CardBody>
                              </Card>
                            </GridItem>

                            {/* Description */}
                            {agentCard.description && (
                              <GridItem md={12}>
                                <Card isFlat>
                                  <CardTitle>Description</CardTitle>
                                  <CardBody>
                                    <TextContent style={{ lineHeight: '1.6' }}>
                                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                        {agentCard.description}
                                      </ReactMarkdown>
                                    </TextContent>
                                  </CardBody>
                                </Card>
                              </GridItem>
                            )}

                            {/* Skills */}
                            {agentCard.skills && agentCard.skills.length > 0 && (
                              <GridItem md={12}>
                                <Card isFlat>
                                  <CardTitle>Skills</CardTitle>
                                  <CardBody>
                                    {agentCard.skills.map((skill) => (
                                      <Card key={skill.id} isFlat style={{ marginBottom: '12px' }}>
                                        <CardBody>
                                          <Flex>
                                            <FlexItem>
                                              <Text component={TextVariants.h4}>{skill.name}</Text>
                                            </FlexItem>
                                            {skill.tags && skill.tags.length > 0 && (
                                              <FlexItem>
                                                <LabelGroup>
                                                  {skill.tags.map((tag) => (
                                                    <Label key={tag} isCompact color="cyan">
                                                      {tag}
                                                    </Label>
                                                  ))}
                                                </LabelGroup>
                                              </FlexItem>
                                            )}
                                          </Flex>
                                          {skill.description && (
                                            <div style={{ marginTop: '8px', lineHeight: '1.6' }}>
                                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                {skill.description}
                                              </ReactMarkdown>
                                            </div>
                                          )}
                                          {skill.examples && skill.examples.length > 0 && (
                                            <div style={{ marginTop: '12px' }}>
                                              <Text component={TextVariants.small}>
                                                <strong>Examples:</strong>
                                              </Text>
                                              <List isPlain style={{ marginTop: '4px' }}>
                                                {skill.examples.map((example, idx) => (
                                                  <ListItem key={idx}>
                                                    <code style={{ fontSize: '0.85em' }}>{example}</code>
                                                  </ListItem>
                                                ))}
                                              </List>
                                            </div>
                                          )}
                                        </CardBody>
                                      </Card>
                                    ))}
                                  </CardBody>
                                </Card>
                              </GridItem>
                            )}
                          </Grid>
                        </ExpandableSection>
                      </>
                    ) : (
                      <Alert variant="warning" title="Agent card not available" isInline>
                        Could not fetch the agent card. The agent may not be responding.
                      </Alert>
                    )}
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


            </Grid>
          </Tab>

          <Tab eventKey={1} title={<TabTitleText>Status</TabTitleText>}>
            <Grid hasGutter style={{ marginTop: '16px' }}>
              {/* Agent Runtime Status */}
              <GridItem md={12}>
                <Card>
                  <CardTitle>Agent Status</CardTitle>
                  <CardBody>
                    {conditions.length === 0 ? (
                      <Alert variant="info" title="No status conditions available" isInline />
                    ) : (
                      <Table aria-label="Agent status conditions" variant="compact">
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
                                {(condition.lastTransitionTime || condition.last_transition_time)
                                  ? new Date((condition.lastTransitionTime || condition.last_transition_time) as string).toLocaleString()
                                  : '-'}
                              </Td>
                            </Tr>
                          ))}
                        </Tbody>
                      </Table>
                    )}
                  </CardBody>
                </Card>
              </GridItem>

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
                              <DescriptionListTerm>Build Name</DescriptionListTerm>
                              <DescriptionListDescription>
                                {buildStatus.name}
                              </DescriptionListDescription>
                            </DescriptionListGroup>
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

              {/* Shipwright Build Status - shown when agent was built with Shipwright */}
              {shipwrightBuildName && (
                <GridItem md={12}>
                  <Card>
                    <CardTitle>Shipwright Build Status</CardTitle>
                    <CardBody>
                      {isShipwrightBuildStatusLoading ? (
                        <Spinner size="md" aria-label="Loading Shipwright build status" />
                      ) : shipwrightBuildStatus ? (
                        <>
                          <DescriptionList isCompact isHorizontal>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Build Name</DescriptionListTerm>
                              <DescriptionListDescription>
                                {shipwrightBuildStatus.name}
                              </DescriptionListDescription>
                            </DescriptionListGroup>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Build Registered</DescriptionListTerm>
                              <DescriptionListDescription>
                                <Label
                                  color={shipwrightBuildStatus.buildRegistered ? 'green' : 'red'}
                                  isCompact
                                >
                                  {shipwrightBuildStatus.buildRegistered ? 'Yes' : 'No'}
                                </Label>
                              </DescriptionListDescription>
                            </DescriptionListGroup>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Build Strategy</DescriptionListTerm>
                              <DescriptionListDescription>
                                <Label isCompact color="blue">{shipwrightBuildStatus.strategy}</Label>
                              </DescriptionListDescription>
                            </DescriptionListGroup>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Output Image</DescriptionListTerm>
                              <DescriptionListDescription>
                                <code style={{ fontSize: '0.85em' }}>
                                  {shipwrightBuildStatus.outputImage}
                                </code>
                              </DescriptionListDescription>
                            </DescriptionListGroup>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Git URL</DescriptionListTerm>
                              <DescriptionListDescription>
                                <code style={{ fontSize: '0.85em' }}>
                                  {shipwrightBuildStatus.gitUrl}
                                </code>
                              </DescriptionListDescription>
                            </DescriptionListGroup>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Git Revision</DescriptionListTerm>
                              <DescriptionListDescription>
                                {shipwrightBuildStatus.gitRevision}
                              </DescriptionListDescription>
                            </DescriptionListGroup>
                            {shipwrightBuildStatus.contextDir && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Context Directory</DescriptionListTerm>
                                <DescriptionListDescription>
                                  {shipwrightBuildStatus.contextDir}
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                          </DescriptionList>

                          {/* BuildRun Status */}
                          {shipwrightBuildStatus.hasBuildRun && (
                            <>
                              <Title headingLevel="h4" size="md" style={{ marginTop: '24px', marginBottom: '16px' }}>
                                Latest BuildRun
                              </Title>
                              <DescriptionList isCompact isHorizontal>
                                <DescriptionListGroup>
                                  <DescriptionListTerm>BuildRun Name</DescriptionListTerm>
                                  <DescriptionListDescription>
                                    {shipwrightBuildStatus.buildRunName}
                                  </DescriptionListDescription>
                                </DescriptionListGroup>
                                <DescriptionListGroup>
                                  <DescriptionListTerm>Phase</DescriptionListTerm>
                                  <DescriptionListDescription>
                                    <Label
                                      color={
                                        shipwrightBuildStatus.buildRunPhase === 'Succeeded'
                                          ? 'green'
                                          : shipwrightBuildStatus.buildRunPhase === 'Failed'
                                            ? 'red'
                                            : 'blue'
                                      }
                                    >
                                      {shipwrightBuildStatus.buildRunPhase}
                                    </Label>
                                  </DescriptionListDescription>
                                </DescriptionListGroup>
                                {shipwrightBuildStatus.buildRunStartTime && (
                                  <DescriptionListGroup>
                                    <DescriptionListTerm>Started</DescriptionListTerm>
                                    <DescriptionListDescription>
                                      {new Date(shipwrightBuildStatus.buildRunStartTime).toLocaleString()}
                                    </DescriptionListDescription>
                                  </DescriptionListGroup>
                                )}
                                {shipwrightBuildStatus.buildRunCompletionTime && (
                                  <DescriptionListGroup>
                                    <DescriptionListTerm>Completed</DescriptionListTerm>
                                    <DescriptionListDescription>
                                      {new Date(shipwrightBuildStatus.buildRunCompletionTime).toLocaleString()}
                                    </DescriptionListDescription>
                                  </DescriptionListGroup>
                                )}
                                {shipwrightBuildStatus.buildRunOutputImage && (
                                  <DescriptionListGroup>
                                    <DescriptionListTerm>Output Image</DescriptionListTerm>
                                    <DescriptionListDescription>
                                      <code style={{ fontSize: '0.85em' }}>
                                        {shipwrightBuildStatus.buildRunOutputImage}
                                        {shipwrightBuildStatus.buildRunOutputDigest && (
                                          <>@{shipwrightBuildStatus.buildRunOutputDigest.substring(0, 20)}...</>
                                        )}
                                      </code>
                                    </DescriptionListDescription>
                                  </DescriptionListGroup>
                                )}
                                {shipwrightBuildStatus.buildRunPhase === 'Failed' && shipwrightBuildStatus.buildRunFailureMessage && (
                                  <DescriptionListGroup>
                                    <DescriptionListTerm>Error</DescriptionListTerm>
                                    <DescriptionListDescription>
                                      <Alert variant="danger" isInline isPlain title={shipwrightBuildStatus.buildRunFailureMessage} />
                                    </DescriptionListDescription>
                                  </DescriptionListGroup>
                                )}
                              </DescriptionList>
                            </>
                          )}
                        </>
                      ) : (
                        <Alert
                          variant="info"
                          title="Shipwright build information not available"
                          isInline
                        />
                      )}
                    </CardBody>
                  </Card>
                </GridItem>
              )}
            </Grid>
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
                  {yaml.dump(
                    {
                      apiVersion: agent.workloadType === 'statefulset' ? 'apps/v1' : agent.workloadType === 'job' ? 'batch/v1' : 'apps/v1',
                      kind: agent.workloadType === 'statefulset' ? 'StatefulSet' : agent.workloadType === 'job' ? 'Job' : 'Deployment',
                      metadata: {
                        ...agent.metadata,
                        managedFields: undefined,
                      },
                      spec: agent.spec,
                      status: agent.status,
                    },
                    { noRefs: true, lineWidth: -1 }
                  )}
                </pre>
              </CardBody>
            </Card>
          </Tab>
        </Tabs>
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
            The agent <strong>{name}</strong> will be permanently deleted.
            This will also delete the associated AgentBuild if one exists.
          </Text>
          <Text component="small" style={{ marginTop: '16px', display: 'block' }}>
            Type <strong>{name}</strong> to confirm deletion:
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
