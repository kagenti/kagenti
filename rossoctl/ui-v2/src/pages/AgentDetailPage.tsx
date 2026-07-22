// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { workloadTypeColor, WORKLOAD_META } from '@/utils/workloadType';
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
  Checkbox,
  Icon,
  Dropdown,
  DropdownList,
  DropdownItem,
  MenuToggle,
  MenuToggleElement,
  TreeView,
} from '@patternfly/react-core';
import type { TreeViewDataItem } from '@patternfly/react-core';
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

import { agentService, authBridgeService, chatService, configService, shipwrightService, ShipwrightBuildInfo, dreamService, skillService } from '@/services/api';
import { AgentChat } from '@/components/AgentChat';
import { useFeatureFlags } from '@/hooks/useFeatureFlags';
import type { PluginConfig } from '@/types';

function pluginsToTreeData(plugins: PluginConfig[]): TreeViewDataItem[] {
  return plugins.map((plugin, idx) => ({
    id: `plugin-${idx}`,
    name: plugin.name,
    defaultExpanded: true,
    children: Object.entries(plugin.config || {}).map(([key, value]) => {
      if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
        return {
          id: `plugin-${idx}-${key}`,
          name: key,
          defaultExpanded: true,
          children: Object.entries(value as Record<string, unknown>).map(([k, v]) => ({
            id: `plugin-${idx}-${key}-${k}`,
            name: <><strong>{k}:</strong> {String(v)}</>,
          })),
        };
      }
      return {
        id: `plugin-${idx}-${key}`,
        name: <><strong>{key}:</strong> {String(value)}</>,
      };
    }),
  }));
}

interface StatusCondition {
  type: string;
  status: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
  last_transition_time?: string; // snake_case from K8s API
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
  streaming?: boolean;
  defaultInputModes?: string[];
  defaultOutputModes?: string[];
  skills?: AgentCardSkill[];
}

export const AgentDetailPage: React.FC = () => {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const features = useFeatureFlags();
  const [activeTab, setActiveTab] = React.useState<string | number>(0);
  const [isAgentCardExpanded, setIsAgentCardExpanded] = React.useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = React.useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = React.useState('');
  const [actionsMenuOpen, setActionsMenuOpen] = React.useState(false);
  const [dreamModalOpen, setDreamModalOpen] = React.useState(false);
  const [dreamResult, setDreamResult] = React.useState<string | null>(null);
  const [dreamRunId, setDreamRunId] = React.useState<string | null>(null);

  // Store URL (from auto-sync config) — used to point users at the store's
  // Plugins page where the required ask-runspace plugin is enabled/configured.
  const autoSyncQuery = useQuery({
    queryKey: ['skill-autosync'],
    queryFn: () => skillService.getAutoSync(),
    enabled: !!features.dreaming && dreamModalOpen,
  });
  const storePluginsUrl = autoSyncQuery.data?.storeUiUrl
    ? `${autoSyncQuery.data.storeUiUrl.replace(/\/$/, '')}/plugins`
    : null;

  // Skill "dreaming" — status + manual trigger (feature-flagged).
  const dreamStatusQuery = useQuery({
    queryKey: ['dream-status', namespace, name],
    queryFn: () => dreamService.status(namespace!, name!),
    enabled: !!features.dreaming && dreamModalOpen && !!namespace && !!name,
  });
  const dreamMutation = useMutation({
    mutationFn: () => dreamService.trigger(namespace!, name!),
    onSuccess: (r) => {
      if (r.status === 'submitted') {
        setDreamResult(
          `Dream submitted — ${r.new_trajectories} new trajectory(ies) (conversations) sent to RunSpace. Optimizing…`
        );
        setDreamRunId(r.run_id || null);
      } else if (r.status === 'no_new_trajectories') {
        setDreamResult('No new trajectories since the last dream — nothing to optimize.');
      } else {
        setDreamResult(`Status: ${r.status}`);
      }
      dreamStatusQuery.refetch();
    },
    onError: (e: unknown) => setDreamResult(`Dream failed: ${e instanceof Error ? e.message : String(e)}`),
  });

  // Poll the RunSpace run until it completes, then show its summary.
  const dreamRunQuery = useQuery({
    queryKey: ['dream-run', namespace, name, dreamRunId],
    queryFn: () => dreamService.runStatus(namespace!, name!, dreamRunId!),
    enabled: !!dreamRunId && dreamModalOpen,
    refetchInterval: (q) => {
      const s = (q.state.data as { status?: string } | undefined)?.status;
      return s && s !== 'pending' ? false : 5000;
    },
  });

  // Auto-dream schedule config (persisted thresholds). Loaded from status,
  // edited in the modal, saved via PUT /thresholds.
  const DREAM_DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
  const [dreamMinTraj, setDreamMinTraj] = React.useState('0');
  const [dreamDays, setDreamDays] = React.useState<string[]>([]);
  const [dreamTime, setDreamTime] = React.useState('');
  const [dreamCfgSaved, setDreamCfgSaved] = React.useState(false);
  React.useEffect(() => {
    const d = dreamStatusQuery.data;
    if (d) {
      setDreamMinTraj(String(d.minNewTrajectories ?? 0));
      setDreamDays(d.scheduleDays ?? []);
      setDreamTime(d.scheduleTime ?? '');
    }
  }, [dreamStatusQuery.data]);
  const dreamCfgMutation = useMutation({
    mutationFn: () =>
      dreamService.setThresholds(namespace!, name!, {
        minNewTrajectories: parseInt(dreamMinTraj || '0', 10),
        minIntervalSeconds: 0,
        scheduleDays: dreamDays,
        scheduleTime: dreamTime,
      }),
    onSuccess: () => {
      setDreamCfgSaved(true);
      dreamStatusQuery.refetch();
      window.setTimeout(() => setDreamCfgSaved(false), 4000);
    },
  });
  const toggleDreamDay = (day: string) =>
    setDreamDays((prev) =>
      prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day]
    );

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
    if (deleteConfirmText.trim() === name) {
      deleteMutation.mutate();
    }
  };

  const { data: agent, isLoading, isError, error } = useQuery({
    queryKey: ['agent', namespace, name],
    queryFn: () => agentService.get(namespace!, name!),
    enabled: !!namespace && !!name,
    retry: 3,
    retryDelay: 2000,
    refetchInterval: (query) => {
      if (!query.state.data) return 5000;
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

  // Check if agent was built with Shipwright (has annotation)
  const shipwrightBuildName = agent?.metadata?.annotations?.['rossoctl.io/shipwright-build'];

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
    retry: 3,
    retryDelay: 2000,
    refetchInterval: (query) => {
      return query.state.data ? false : 5000;
    },
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

  // Fetch dashboard config for domain name
  const { data: dashboardConfig } = useQuery({
    queryKey: ['dashboards'],
    queryFn: () => configService.getDashboards(),
  });

  // Fetch AuthBridge config and status
  // AuthBridge queries are suppressed until the agent is loaded and confirmed to have the sidecar
  const hasAuthBridge = agent?.metadata?.labels?.['rossoctl.io/inject'] === 'enabled';

  const { data: authBridgeConfig, isLoading: isAuthBridgeConfigLoading } = useQuery({
    queryKey: ['authbridge-config', namespace, name],
    queryFn: () => authBridgeService.getConfig(namespace!, name!),
    enabled: !!namespace && !!name && hasAuthBridge && features.authbridgeAPI,
  });

  const { data: authBridgeStats, isLoading: isAuthBridgeStatsLoading } = useQuery({
    queryKey: ['authbridge-status', namespace, name],
    queryFn: () => authBridgeService.getStatus(namespace!, name!),
    enabled: !!namespace && !!name && hasAuthBridge && features.authbridgeAPI,
  });

  if (isLoading) {
    return (
      <PageSection>
        <div className="rossoctl-loading-center">
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
          <div className="rossoctl-loading-center">
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
          <div className="rossoctl-loading-center">
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
    metadata.annotations?.['rossoctl.io/description'] ||
    'No description available';

  // Get workload type
  const workloadType = agent.workloadType || labels['rossoctl.io/workload-type'] || 'deployment';

  // Get replica info for Deployments/StatefulSets
  const replicas = spec.replicas ?? 1;
  const readyReplicas = status.readyReplicas ?? status.ready_replicas ?? 0;
  const availableReplicas = status.availableReplicas ?? status.available_replicas ?? 0;
  // updatedReplicas indicates rolling update progress for StatefulSets
  const updatedReplicas = status.updatedReplicas ?? status.updated_replicas ?? 0;

  const gitSource = spec.source?.git;

  // If route check fails or is loading, default to false (in-cluster URL is safer default)
  const hasRoute = routeStatusData?.hasRoute ?? false;

  // Prefer the real URL from the agent card or derive from the actual Service port.
  // Fall back to convention defaults (8080 external, 8000 in-cluster) when neither is available.
  const servicePort = serviceInfo?.ports?.[0]?.port;
  const domainName = dashboardConfig?.domainName || 'localtest.me';
  const agentUrl = agentCard?.url
    || (hasRoute
      ? `http://${name}.${namespace}.${domainName}:${servicePort || 8080}`
      : `http://${name}.${namespace}.svc.cluster.local:${servicePort || 8000}`);

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
              {(() => {
                const protocols = Object.keys(labels)
                  .filter(k => k.startsWith('protocol.rossoctl.io/'))
                  .map(k => k.replace('protocol.rossoctl.io/', ''));
                if (protocols.length === 0 && labels['rossoctl.io/protocol']) {
                  protocols.push(labels['rossoctl.io/protocol']);
                }
                if (protocols.length === 0) protocols.push('A2A');
                return protocols.map(p => (
                  <FlexItem key={`protocol-${p}`}>
                    <Label color="blue">{p.toUpperCase()}</Label>
                  </FlexItem>
                ));
              })()}
              {features.dreaming && (
                <FlexItem>
                  <Button
                    variant="secondary"
                    onClick={() => { setDreamResult(null); setDreamModalOpen(true); }}
                  >
                    💤 Dream
                  </Button>
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
                          <Label color={workloadTypeColor(workloadType)} isCompact>
                            {workloadType.charAt(0).toUpperCase() + workloadType.slice(1)}
                          </Label>
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      {workloadType === 'sandbox' ? (
                        <DescriptionListGroup>
                          <DescriptionListTerm>Pods</DescriptionListTerm>
                          <DescriptionListDescription>
                            {isReady ? (status.replicas ?? 1) : 0}/{status.replicas ?? 1} ready
                          </DescriptionListDescription>
                        </DescriptionListGroup>
                      ) : workloadType !== 'job' && (
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
                      )}
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
                          <a href={agentUrl} target="_blank" rel="noopener noreferrer">
                            {agentUrl}
                          </a>
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
                                          color={agentCard.streaming ? 'green' : 'gold'}
                                        >
                                          {agentCard.streaming ? 'Enabled' : 'Disabled'}
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
                                <a href={shipwrightBuildStatus.gitUrl} target="_blank" rel="noopener noreferrer">
                                  {shipwrightBuildStatus.gitUrl}
                                </a>
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
                      apiVersion: (WORKLOAD_META[agent.workloadType ?? 'deployment'] ?? WORKLOAD_META.deployment).apiVersion,
                      kind: (WORKLOAD_META[agent.workloadType ?? 'deployment'] ?? WORKLOAD_META.deployment).kind,
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

          {hasAuthBridge && features.authbridgeAPI && <Tab eventKey={4} title={<TabTitleText>AuthBridge</TabTitleText>}>
            <Grid hasGutter style={{ marginTop: '16px' }}>
              <GridItem md={6}>
                <Card>
                  <CardTitle>Config</CardTitle>
                  <CardBody>
                    {isAuthBridgeConfigLoading ? (
                      <Spinner size="md" aria-label="Loading AuthBridge config" />
                    ) : authBridgeConfig ? (
                      <DescriptionList isCompact>
                        {authBridgeConfig.AuthBridge != null && !authBridgeConfig.AuthBridge ? (
                          <DescriptionListGroup>
                            <DescriptionListTerm>Enabled</DescriptionListTerm>
                            <DescriptionListDescription>
                              <Label color="red" isCompact>No</Label>
                            </DescriptionListDescription>
                          </DescriptionListGroup>
                        ) : (
                          <>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Mode</DescriptionListTerm>
                              <DescriptionListDescription>
                                <Label isCompact color="blue">{authBridgeConfig.mode}</Label>
                              </DescriptionListDescription>
                            </DescriptionListGroup>
                            {authBridgeConfig.tls_bridge?.mode === 'enabled' && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>TLS bridge</DescriptionListTerm>
                                <DescriptionListDescription>
                                  <Label isCompact color="green">Active</Label>
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                            {(authBridgeConfig.pipeline?.inbound?.plugins?.length ?? 0) > 0 && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Inbound Plugins</DescriptionListTerm>
                                <DescriptionListDescription>
                                  <TreeView
                                    data={pluginsToTreeData(authBridgeConfig.pipeline!.inbound!.plugins)}
                                    aria-label="AuthBridge inbound plugins"
                                  />
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                            {(authBridgeConfig.pipeline?.outbound?.plugins?.length ?? 0) > 0 && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Outbound Plugins</DescriptionListTerm>
                                <DescriptionListDescription>
                                  <TreeView
                                    data={pluginsToTreeData(authBridgeConfig.pipeline!.outbound!.plugins)}
                                    aria-label="AuthBridge outbound plugins"
                                  />
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                          </>
                        )}
                      </DescriptionList>
                    ) : (
                      <EmptyState>
                        <EmptyStateHeader titleText="No configuration available" headingLevel="h4" />
                      </EmptyState>
                    )}
                  </CardBody>
                </Card>
              </GridItem>
              <GridItem md={6}>
                <Card>
                  <CardTitle>Status</CardTitle>
                  <CardBody>
                    {isAuthBridgeStatsLoading ? (
                      <Spinner size="md" aria-label="Loading AuthBridge status" />
                    ) : authBridgeStats ? (
                      <DescriptionList isCompact>
                        {authBridgeStats.AuthBridge != null && !authBridgeStats.AuthBridge ? (
                          <DescriptionListGroup>
                            <DescriptionListTerm>Enabled</DescriptionListTerm>
                            <DescriptionListDescription>
                              <Label color="red" isCompact>No</Label>
                            </DescriptionListDescription>
                          </DescriptionListGroup>
                        ) : (
                          <>
                            {authBridgeStats.inbound_approvals != null && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Inbound Approvals</DescriptionListTerm>
                                <DescriptionListDescription>
                                  {Object.keys(authBridgeStats.inbound_approvals).length > 0 ? (
                                    <LabelGroup>
                                      {Object.entries(authBridgeStats.inbound_approvals).map(([key, val]) => (
                                        <Label key={key} isCompact color="green">{key}: {val}</Label>
                                      ))}
                                    </LabelGroup>
                                  ) : 'None'}
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                            {authBridgeStats.inbound_denials != null && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Inbound Denials</DescriptionListTerm>
                                <DescriptionListDescription>
                                  {Object.keys(authBridgeStats.inbound_denials).length > 0 ? (
                                    <LabelGroup>
                                      {Object.entries(authBridgeStats.inbound_denials).map(([key, val]) => (
                                        <Label key={key} isCompact color="red">{key}: {val}</Label>
                                      ))}
                                    </LabelGroup>
                                  ) : 'None'}
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                            {authBridgeStats.outbound_approvals != null && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Outbound Approvals</DescriptionListTerm>
                                <DescriptionListDescription>
                                  {Object.keys(authBridgeStats.outbound_approvals).length > 0 ? (
                                    <LabelGroup>
                                      {Object.entries(authBridgeStats.outbound_approvals).map(([key, val]) => (
                                        <Label key={key} isCompact color="green">{key}: {val}</Label>
                                      ))}
                                    </LabelGroup>
                                  ) : 'None'}
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                            {authBridgeStats.outbound_denials != null && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Outbound Denials</DescriptionListTerm>
                                <DescriptionListDescription>
                                  {Object.keys(authBridgeStats.outbound_denials).length > 0 ? (
                                    <LabelGroup>
                                      {Object.entries(authBridgeStats.outbound_denials).map(([key, val]) => (
                                        <Label key={key} isCompact color="red">{key}: {val}</Label>
                                      ))}
                                    </LabelGroup>
                                  ) : 'None'}
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                            {authBridgeStats.outbound_replace_tokens != null && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Outbound Token Replacements</DescriptionListTerm>
                                <DescriptionListDescription>
                                  {Object.keys(authBridgeStats.outbound_replace_tokens).length > 0 ? (
                                    <LabelGroup>
                                      {Object.entries(authBridgeStats.outbound_replace_tokens).map(([key, val]) => (
                                        <Label key={key} isCompact color="blue">{key}: {val}</Label>
                                      ))}
                                    </LabelGroup>
                                  ) : 'None'}
                                </DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                          </>
                        )}
                      </DescriptionList>
                    ) : (
                      <EmptyState>
                        <EmptyStateHeader titleText="No status available" headingLevel="h4" />
                      </EmptyState>
                    )}
                  </CardBody>
                </Card>
              </GridItem>
            </Grid>
          </Tab>}
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
            isDisabled={deleteMutation.isPending || deleteConfirmText.trim() !== name}
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
            This will also delete the associated build resources if they exist.
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

      {/* Skill Dreaming Modal */}
      <Modal
        variant={ModalVariant.medium}
        title="💤 Dream — optimize this agent's skills"
        isOpen={dreamModalOpen}
        onClose={() => { setDreamModalOpen(false); setDreamRunId(null); }}
        actions={[
          <Button
            key="dream"
            variant="primary"
            onClick={() => dreamMutation.mutate()}
            isLoading={dreamMutation.isPending || dreamRunQuery.data?.status === 'pending'}
            isDisabled={
              dreamMutation.isPending ||
              dreamRunQuery.data?.status === 'pending' ||
              dreamStatusQuery.data?.newTrajectories === 0
            }
          >
            Dream now
          </Button>,
          <Button key="close" variant="link" onClick={() => { setDreamModalOpen(false); setDreamRunId(null); }}>
            Close
          </Button>,
        ]}
      >
        <TextContent>
          <Text>
            Reads <strong>{name}</strong>'s new execution trajectories from Phoenix and runs a
            RunSpace optimization session that improves the skills the agent used, writing each
            back to the store as a <strong>new version under the same name</strong> (immutable,
            git-like lineage). Only new (un-dreamed) trajectories are processed.
          </Text>

          {/* Setup / prerequisite guidance for new users. */}
          <Alert
            variant="info"
            isInline
            isPlain
            title="Setup: dreaming runs on the store's ask-runspace plugin"
            style={{ marginTop: '12px' }}
          >
            <Text component="small">
              Dreaming hands the trajectories to the <strong>ask-runspace</strong> plugin in the
              skillberry store — that plugin runs the RunSpace (Claude Code) session and uses the
              store's own model credentials. Enable and configure it (model / API key) on the
              store's{' '}
              {storePluginsUrl ? (
                <a href={storePluginsUrl} target="_blank" rel="noreferrer">
                  Plugins page
                </a>
              ) : (
                <strong>Plugins page</strong>
              )}
              . No API keys are configured here in Rossoctl.
            </Text>
          </Alert>

          {dreamStatusQuery.data && (
            <Text component="small" style={{ marginTop: '12px', display: 'block' }}>
              <strong>{dreamStatusQuery.data.newTrajectories}</strong> new trajectory(ies) to dream on
              {' · '}runs: {dreamStatusQuery.data.dreamedCount}
              {' · '}last dreamed: {dreamStatusQuery.data.lastDreamedAt || 'never'}
            </Text>
          )}
          {dreamResult && (
            <Text style={{ marginTop: '12px', fontWeight: 600 }}>{dreamResult}</Text>
          )}

          {/* Auto-dream schedule config (stored; evaluated by the scheduler iteration). */}
          <ExpandableSection
            toggleText="⏰ Auto-dream schedule"
            style={{ marginTop: '16px' }}
          >
            <Text component="small" style={{ display: 'block', marginBottom: 8 }}>
              Dream automatically instead of clicking manually — when enough new
              trajectories pile up, and/or on fixed weekdays.
            </Text>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <Text component="small">Dream after</Text>
              <TextInput
                aria-label="minimum new trajectories"
                type="number"
                value={dreamMinTraj}
                onChange={(_e, v) => setDreamMinTraj(v)}
                style={{ width: 80 }}
              />
              <Text component="small">new trajectories collected (0 = off)</Text>
            </div>
            <Text component="small" style={{ display: 'block', marginBottom: 6 }}>
              …and/or on these days:
            </Text>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
              {DREAM_DAYS.map((d) => (
                <Checkbox
                  key={d}
                  id={`dream-day-${d}`}
                  label={d.charAt(0).toUpperCase() + d.slice(1)}
                  isChecked={dreamDays.includes(d)}
                  onChange={() => toggleDreamDay(d)}
                />
              ))}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <Text component="small">at</Text>
              <TextInput
                aria-label="schedule time"
                type="time"
                value={dreamTime}
                onChange={(_e, v) => setDreamTime(v)}
                style={{ width: 140 }}
              />
              <Text component="small">(cluster-local, 24h)</Text>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => dreamCfgMutation.mutate()}
              isLoading={dreamCfgMutation.isPending}
            >
              Save schedule
            </Button>
            {dreamCfgSaved && (
              <Text component="small" style={{ marginLeft: 12, color: 'var(--pf-v5-global--success-color--100)' }}>
                ✓ Saved{dreamDays.length > 0 && dreamTime ? ` — dreams ${dreamDays.map(d => d[0].toUpperCase()+d.slice(1)).join(', ')} at ${dreamTime}` : ''}
              </Text>
            )}
          </ExpandableSection>

          {dreamRunId && dreamRunQuery.data?.status === 'pending' && (
            <Text component="small" style={{ marginTop: '8px', display: 'block' }}>
              <Spinner size="sm" /> RunSpace optimizing the skill… (run {dreamRunId})
            </Text>
          )}
          {dreamRunQuery.data?.status === 'ready' && dreamRunQuery.data.summaryMd && (
            <div
              style={{
                marginTop: '16px',
                padding: '16px',
                border: '1px solid var(--pf-v5-global--BorderColor--100)',
                borderRadius: 8,
                maxHeight: 360,
                overflow: 'auto',
                background: 'var(--pf-v5-global--BackgroundColor--200)',
              }}
            >
              <Text component="h4" style={{ marginBottom: 8 }}>RunSpace optimization summary</Text>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {dreamRunQuery.data.summaryMd}
              </ReactMarkdown>
            </div>
          )}
          {dreamRunQuery.data?.status === 'failed' && (
            <Text style={{ marginTop: '8px', color: 'var(--pf-v5-global--danger-color--100)' }}>
              RunSpace run failed — check the store logs.
            </Text>
          )}
        </TextContent>
      </Modal>
    </>
  );
};
