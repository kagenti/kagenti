// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, Navigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  PageSection,
  Title,
  Split,
  SplitItem,
  Label,
  Spinner,
  Alert,
  Button,
  Flex,
  FlexItem,
} from '@patternfly/react-core';
import {
  simulationService,
  GenerationStatusResponse,
} from '@/services/api';
import { useFeatureFlags } from '@/hooks/useFeatureFlags';
import { GenerationProgressView } from '@/components/GenerationProgressView';
import { getStatusIcon } from '@/components/BuildProgressView';
import { isGenerationTerminal, mapGenerationStatusToPhase } from '@/utils/simulation';

const POLL_INTERVAL = 5000;

export const ToolGenerationProgressPage: React.FC = () => {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const features = useFeatureFlags();
  const [elapsed, setElapsed] = useState(0);

  const { data, isLoading, error } = useQuery<GenerationStatusResponse>({
    queryKey: ['simGenerationStatus', namespace, name],
    queryFn: () => simulationService.getGenerationStatus(namespace!, name!),
    enabled: !!namespace && !!name && features.simulatedTools,
    refetchInterval: (query) => {
      const d = query.state.data;
      if (d && isGenerationTerminal(d.status)) {
        return false;
      }
      return POLL_INTERVAL;
    },
  });

  // Tick an elapsed counter while still generating, for the animated progress bar.
  useEffect(() => {
    if (data && isGenerationTerminal(data.status)) {
      return;
    }
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
    // This effect only reads data.status (to decide whether to keep ticking); keying on the
    // whole `data` object would tear down and recreate the interval on every 5s poll response,
    // even when the status hasn't changed, so the narrower dependency here is intentional.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.status]);

  // On Ready, refresh the catalog and go to the tool detail page.
  useEffect(() => {
    if (data?.status === 'Ready') {
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      navigate(`/tools/${namespace}/${name}`);
    }
  }, [data?.status, namespace, name, navigate, queryClient]);

  if (!features.simulatedTools) {
    return <Navigate to="/tools" replace />;
  }

  return (
    <PageSection>
      <Split hasGutter>
        <SplitItem isFilled>
          <Title headingLevel="h1">
            <Flex alignItems={{ default: 'alignItemsCenter' }}>
              <FlexItem>{getStatusIcon(mapGenerationStatusToPhase(data?.status ?? 'Generating'))}</FlexItem>
              <FlexItem>Generating simulated tool: {name}</FlexItem>
            </Flex>
          </Title>
        </SplitItem>
        <SplitItem>
          <Label
            color={
              data?.status === 'Ready'
                ? 'green'
                : data?.status === 'Failed' || data?.status === 'Error'
                  ? 'red'
                  : 'blue'
            }
          >
            {data?.status ?? 'Initializing'}
          </Label>
        </SplitItem>
      </Split>

      {isLoading && <Spinner style={{ marginTop: '16px' }} />}

      {error && (
        <Alert variant="danger" title="Failed to load generation status" style={{ marginTop: '16px' }}>
          {(error as Error).message}
        </Alert>
      )}

      {data && (
        <div style={{ marginTop: '16px' }}>
          <GenerationProgressView
            status={data.status}
            reason={data.reason}
            mcpUrl={data.mcpUrl}
            elapsedSeconds={elapsed}
          />
          {(data.status === 'Failed' || data.status === 'Error') && (
            <Button
              variant="link"
              onClick={() => navigate('/tools')}
              style={{ marginTop: '16px' }}
            >
              Back to tool catalog
            </Button>
          )}
        </div>
      )}
    </PageSection>
  );
};
