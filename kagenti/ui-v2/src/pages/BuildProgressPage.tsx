// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useEffect, useMemo, useState } from 'react';
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
  Label,
  Split,
  SplitItem,
  Flex,
  FlexItem,
  Divider,
  Alert,
} from '@patternfly/react-core';
import { CubesIcon } from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { shipwrightService, ShipwrightBuildInfo } from '@/services/api';
import { BuildProgressView, getStatusIcon } from '@/components';

// Polling interval in milliseconds
const POLL_INTERVAL = 5000;

export const BuildProgressPage: React.FC = () => {
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
  } = useQuery<ShipwrightBuildInfo>({
    queryKey: ['shipwrightBuildInfo', namespace, name],
    queryFn: () => shipwrightService.getBuildInfo(namespace!, name!),
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
    mutationFn: () => shipwrightService.finalizeBuild(namespace!, name!, {}),
    onSuccess: () => {
      // Invalidate queries and navigate to agent detail page
      queryClient.invalidateQueries({ queryKey: ['agents'] });
      navigate(`/agents/${namespace}/${name}`);
    },
    onError: () => {
      setIsAutoFinalizing(false);
    },
  });

  // Mutation for triggering a new build
  const retryMutation = useMutation({
    mutationFn: () => shipwrightService.triggerBuildRun(namespace!, name!),
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

  const finalizeError = useMemo(
    () => finalizeMutation.isError
      ? (finalizeMutation.error instanceof Error
          ? finalizeMutation.error
          : new Error('An unexpected error occurred'))
      : null,
    [finalizeMutation.isError, finalizeMutation.error]
  );

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
        <Button variant="link" onClick={() => navigate('/agents')}>
          Back to Agents
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
          <Button variant="link" onClick={() => navigate('/agents')}>
            Back to Agents
          </Button>
        </EmptyState>
      </PageSection>
    );
  }

  return (
    <>
      <PageSection variant="light">
        <Breadcrumb>
          <BreadcrumbItem to="/agents">Agents</BreadcrumbItem>
          <BreadcrumbItem to={`/agents?namespace=${namespace}`}>{namespace}</BreadcrumbItem>
          <BreadcrumbItem isActive>{name}</BreadcrumbItem>
          <BreadcrumbItem isActive>Build</BreadcrumbItem>
        </Breadcrumb>
        <Split hasGutter style={{ marginTop: '16px' }}>
          <SplitItem isFilled>
            <Title headingLevel="h1">
              <Flex alignItems={{ default: 'alignItemsCenter' }}>
                <FlexItem>{getStatusIcon(buildInfo.buildRunPhase)}</FlexItem>
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
        <BuildProgressView
          buildInfo={buildInfo}
          resourceType="agent"
          isAutoFinalizing={isAutoFinalizing}
          finalizeError={finalizeError}
          isRetryPending={retryMutation.isPending}
          onRetryBuild={() => retryMutation.mutate()}
          onRetryFinalize={() => finalizeMutation.mutate()}
        />

        <Divider style={{ margin: '24px 0' }} />

        {/* Back button */}
        <Button variant="link" onClick={() => navigate('/agents')}>
          Back to Agents
        </Button>
      </PageSection>
    </>
  );
};
