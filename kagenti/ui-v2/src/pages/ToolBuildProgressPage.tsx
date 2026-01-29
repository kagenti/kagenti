// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useEffect, useState } from 'react';
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
  Alert,
  Progress,
  ProgressMeasureLocation,
  ProgressVariant,
  Split,
  SplitItem,
  Flex,
  FlexItem,
  Text,
  TextContent,
  ClipboardCopy,
  Divider,
} from '@patternfly/react-core';
import {
  CubesIcon,
  CheckCircleIcon,
  ExclamationCircleIcon,
  InProgressIcon,
  ClockIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { toolShipwrightService, ToolShipwrightBuildInfo } from '@/services/api';

// Polling interval in milliseconds
const POLL_INTERVAL = 5000;

export const ToolBuildProgressPage: React.FC = () => {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isAutoFinalizing, setIsAutoFinalizing] = useState(false);

  // Query for build info with polling
  const {
    data: buildInfo,
    isLoading,
    error,
    refetch,
  } = useQuery<ToolShipwrightBuildInfo>({
    queryKey: ['toolShipwrightBuildInfo', namespace, name],
    queryFn: () => toolShipwrightService.getBuildInfo(namespace!, name!),
    enabled: !!namespace && !!name,
    refetchInterval: (query) => {
      // Stop polling if build succeeded or failed
      const data = query.state.data;
      if (data?.buildRunPhase === 'Succeeded' || data?.buildRunPhase === 'Failed') {
        return false;
      }
      return POLL_INTERVAL;
    },
  });

  // Mutation for finalizing the build
  const finalizeMutation = useMutation({
    mutationFn: () => toolShipwrightService.finalizeBuild(namespace!, name!, {
      workloadType: buildInfo?.toolConfig?.workloadType,
      persistentStorage: buildInfo?.toolConfig?.persistentStorage,
    }),
    onSuccess: () => {
      // Invalidate queries and navigate to tool detail page
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      navigate(`/tools/${namespace}/${name}`);
    },
    onError: () => {
      setIsAutoFinalizing(false);
    },
  });

  // Mutation for triggering a new build
  const retryMutation = useMutation({
    mutationFn: () => toolShipwrightService.triggerBuildRun(namespace!, name!),
    onSuccess: () => {
      refetch();
    },
  });

  // Auto-finalize when build succeeds
  useEffect(() => {
    if (buildInfo?.buildRunPhase === 'Succeeded' && !isAutoFinalizing && !finalizeMutation.isPending) {
      setIsAutoFinalizing(true);
      finalizeMutation.mutate();
    }
  }, [buildInfo?.buildRunPhase, isAutoFinalizing, finalizeMutation]);

  if (!namespace || !name) {
    return (
      <PageSection>
        <EmptyState>
          <EmptyStateHeader
            titleText="Invalid Parameters"
            headingLevel="h1"
            icon={<EmptyStateIcon icon={CubesIcon} />}
          />
          <EmptyStateBody>Missing namespace or name parameter.</EmptyStateBody>
        </EmptyState>
      </PageSection>
    );
  }

  if (isLoading) {
    return (
      <PageSection>
        <Flex justifyContent={{ default: 'justifyContentCenter' }}>
          <FlexItem>
            <Spinner size="xl" />
          </FlexItem>
        </Flex>
      </PageSection>
    );
  }

  if (error) {
    const errorMessage = error instanceof Error ? error.message : 'Failed to load build information';
    return (
      <PageSection>
        <Alert variant="danger" title="Error loading build">
          {errorMessage}
        </Alert>
        <Button variant="link" onClick={() => navigate('/tools')}>
          Back to Tools
        </Button>
      </PageSection>
    );
  }

  if (!buildInfo) {
    return (
      <PageSection>
        <EmptyState>
          <EmptyStateHeader
            titleText="Build Not Found"
            headingLevel="h1"
            icon={<EmptyStateIcon icon={CubesIcon} />}
          />
          <EmptyStateBody>
            No Shipwright Build found for "{name}" in namespace "{namespace}".
          </EmptyStateBody>
          <Button variant="link" onClick={() => navigate('/tools')}>
            Back to Tools
          </Button>
        </EmptyState>
      </PageSection>
    );
  }

  // Calculate progress based on phase
  const getProgressInfo = () => {
    switch (buildInfo.buildRunPhase) {
      case 'Pending':
        return { value: 10, variant: undefined, label: 'Pending...' };
      case 'Running':
        return { value: 50, variant: undefined, label: 'Building...' };
      case 'Succeeded':
        return { value: 100, variant: ProgressVariant.success, label: 'Build Succeeded' };
      case 'Failed':
        return { value: 100, variant: ProgressVariant.danger, label: 'Build Failed' };
      default:
        return { value: 0, variant: undefined, label: 'Waiting for BuildRun...' };
    }
  };

  const progressInfo = getProgressInfo();

  // Get status icon
  const getStatusIcon = () => {
    switch (buildInfo.buildRunPhase) {
      case 'Succeeded':
        return <CheckCircleIcon color="var(--pf-v5-global--success-color--100)" />;
      case 'Failed':
        return <ExclamationCircleIcon color="var(--pf-v5-global--danger-color--100)" />;
      case 'Running':
        return <InProgressIcon color="var(--pf-v5-global--info-color--100)" />;
      case 'Pending':
        return <ClockIcon color="var(--pf-v5-global--warning-color--100)" />;
      default:
        return <ClockIcon />;
    }
  };

  // Format duration
  const formatDuration = (startTime?: string, endTime?: string) => {
    if (!startTime) return '-';
    const start = new Date(startTime);
    const end = endTime ? new Date(endTime) : new Date();
    const seconds = Math.floor((end.getTime() - start.getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
  };

  return (
    <>
      <PageSection variant="light">
        <Breadcrumb>
          <BreadcrumbItem to="/tools">Tools</BreadcrumbItem>
          <BreadcrumbItem to={`/tools?namespace=${namespace}`}>{namespace}</BreadcrumbItem>
          <BreadcrumbItem isActive>{name}</BreadcrumbItem>
          <BreadcrumbItem isActive>Build</BreadcrumbItem>
        </Breadcrumb>
        <Split hasGutter style={{ marginTop: '16px' }}>
          <SplitItem isFilled>
            <Title headingLevel="h1">
              <Flex alignItems={{ default: 'alignItemsCenter' }}>
                <FlexItem>{getStatusIcon()}</FlexItem>
                <FlexItem>Building: {name}</FlexItem>
              </Flex>
            </Title>
          </SplitItem>
          <SplitItem>
            <Label color={buildInfo.buildRunPhase === 'Succeeded' ? 'green' : buildInfo.buildRunPhase === 'Failed' ? 'red' : 'blue'}>
              {buildInfo.buildRunPhase || 'Initializing'}
            </Label>
          </SplitItem>
        </Split>
      </PageSection>

      <PageSection>
        {/* Auto-finalize status */}
        {isAutoFinalizing && (
          <Alert
            variant="info"
            title="Creating Tool"
            isInline
            style={{ marginBottom: '16px' }}
          >
            <Flex alignItems={{ default: 'alignItemsCenter' }}>
              <FlexItem>
                <Spinner size="md" />
              </FlexItem>
              <FlexItem>Build succeeded! Creating the tool deployment...</FlexItem>
            </Flex>
          </Alert>
        )}

        {/* Finalize error */}
        {finalizeMutation.isError && (
          <Alert
            variant="danger"
            title="Failed to create Tool"
            isInline
            style={{ marginBottom: '16px' }}
          >
            {finalizeMutation.error instanceof Error
              ? finalizeMutation.error.message
              : 'An unexpected error occurred'}
            <Button
              variant="link"
              onClick={() => finalizeMutation.mutate()}
              style={{ marginLeft: '16px' }}
            >
              Retry
            </Button>
          </Alert>
        )}

        {/* Build Progress Card */}
        <Card style={{ marginBottom: '24px' }}>
          <CardTitle>Build Progress</CardTitle>
          <CardBody>
            <Progress
              value={progressInfo.value}
              title={progressInfo.label}
              variant={progressInfo.variant}
              measureLocation={ProgressMeasureLocation.top}
            />

            <DescriptionList style={{ marginTop: '24px' }}>
              <DescriptionListGroup>
                <DescriptionListTerm>Build Strategy</DescriptionListTerm>
                <DescriptionListDescription>{buildInfo.strategy}</DescriptionListDescription>
              </DescriptionListGroup>
              {buildInfo.buildRunName && (
                <DescriptionListGroup>
                  <DescriptionListTerm>BuildRun</DescriptionListTerm>
                  <DescriptionListDescription>{buildInfo.buildRunName}</DescriptionListDescription>
                </DescriptionListGroup>
              )}
              <DescriptionListGroup>
                <DescriptionListTerm>Duration</DescriptionListTerm>
                <DescriptionListDescription>
                  {formatDuration(buildInfo.buildRunStartTime, buildInfo.buildRunCompletionTime)}
                </DescriptionListDescription>
              </DescriptionListGroup>
              {buildInfo.buildRunPhase === 'Failed' && buildInfo.buildRunFailureMessage && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Error</DescriptionListTerm>
                  <DescriptionListDescription>
                    <Alert variant="danger" isInline isPlain title={buildInfo.buildRunFailureMessage} />
                  </DescriptionListDescription>
                </DescriptionListGroup>
              )}
            </DescriptionList>

            {/* Retry button for failed builds */}
            {buildInfo.buildRunPhase === 'Failed' && (
              <Button
                variant="primary"
                onClick={() => retryMutation.mutate()}
                isLoading={retryMutation.isPending}
                style={{ marginTop: '16px' }}
              >
                Retry Build
              </Button>
            )}
          </CardBody>
        </Card>

        {/* Source Configuration Card */}
        <Card style={{ marginBottom: '24px' }}>
          <CardTitle>Source Configuration</CardTitle>
          <CardBody>
            <DescriptionList>
              <DescriptionListGroup>
                <DescriptionListTerm>Git URL</DescriptionListTerm>
                <DescriptionListDescription>
                  <ClipboardCopy isReadOnly hoverTip="Copy" clickTip="Copied">
                    {buildInfo.gitUrl}
                  </ClipboardCopy>
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Revision</DescriptionListTerm>
                <DescriptionListDescription>{buildInfo.gitRevision}</DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Context Directory</DescriptionListTerm>
                <DescriptionListDescription>{buildInfo.contextDir || '.'}</DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Output Image</DescriptionListTerm>
                <DescriptionListDescription>
                  <ClipboardCopy isReadOnly hoverTip="Copy" clickTip="Copied">
                    {buildInfo.outputImage}
                  </ClipboardCopy>
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>
          </CardBody>
        </Card>

        {/* Tool Configuration Card */}
        {buildInfo.toolConfig && (
          <Card>
            <CardTitle>Tool Configuration</CardTitle>
            <CardBody>
              <TextContent style={{ marginBottom: '16px' }}>
                <Text>
                  The following configuration will be applied when the tool workload is created:
                </Text>
              </TextContent>
              <DescriptionList>
                <DescriptionListGroup>
                  <DescriptionListTerm>Workload Type</DescriptionListTerm>
                  <DescriptionListDescription>
                    <Label color="grey">
                      {buildInfo.toolConfig.workloadType === 'statefulset' ? 'StatefulSet' : 'Deployment'}
                    </Label>
                  </DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>Protocol</DescriptionListTerm>
                  <DescriptionListDescription>
                    <Label color="blue">{buildInfo.toolConfig.protocol}</Label>
                  </DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>Framework</DescriptionListTerm>
                  <DescriptionListDescription>
                    <Label color="purple">{buildInfo.toolConfig.framework}</Label>
                  </DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>External Access</DescriptionListTerm>
                  <DescriptionListDescription>
                    {buildInfo.toolConfig.createHttpRoute ? (
                      <Label color="green">HTTPRoute will be created</Label>
                    ) : (
                      <Label color="grey">No external access</Label>
                    )}
                  </DescriptionListDescription>
                </DescriptionListGroup>
                {buildInfo.toolConfig.persistentStorage?.enabled && (
                  <DescriptionListGroup>
                    <DescriptionListTerm>Persistent Storage</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="blue">{buildInfo.toolConfig.persistentStorage.size}</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                )}
                {buildInfo.toolConfig.envVars && buildInfo.toolConfig.envVars.length > 0 && (
                  <DescriptionListGroup>
                    <DescriptionListTerm>Environment Variables</DescriptionListTerm>
                    <DescriptionListDescription>
                      {buildInfo.toolConfig.envVars.length} variable(s) configured
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                )}
                {buildInfo.toolConfig.servicePorts && buildInfo.toolConfig.servicePorts.length > 0 && (
                  <DescriptionListGroup>
                    <DescriptionListTerm>Service Ports</DescriptionListTerm>
                    <DescriptionListDescription>
                      {buildInfo.toolConfig.servicePorts.map((port) => (
                        <Label key={port.name} style={{ marginRight: '4px' }}>
                          {port.name}: {port.port} → {port.targetPort}
                        </Label>
                      ))}
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                )}
              </DescriptionList>
            </CardBody>
          </Card>
        )}

        <Divider style={{ margin: '24px 0' }} />

        {/* Back button */}
        <Button variant="link" onClick={() => navigate('/tools')}>
          Back to Tools
        </Button>
      </PageSection>
    </>
  );
};
