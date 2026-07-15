// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import {
  Progress,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Flex,
  FlexItem,
} from '@patternfly/react-core';
import { getProgressInfo, getStatusIcon } from './BuildProgressView';
import { mapGenerationStatusToPhase } from '@/utils/simulation';
import type { GenerationStatus } from '@/services/api';

interface GenerationProgressViewProps {
  status: GenerationStatus;
  reason?: string;
  mcpUrl?: string;
  elapsedSeconds?: number;
}

export const GenerationProgressView: React.FC<GenerationProgressViewProps> = ({
  status,
  reason,
  mcpUrl,
  elapsedSeconds,
}) => {
  const phase = mapGenerationStatusToPhase(status);
  const progress = getProgressInfo(phase, elapsedSeconds ?? 0);

  // getProgressInfo's label is written for Shipwright builds ("Building...", "Build
  // Succeeded"/"Build Failed") — swap in generation-appropriate wording here instead of
  // reusing progress.label, while still relying on getProgressInfo for value/variant.
  const progressTitle =
    status === 'Ready'
      ? 'Generation complete'
      : status === 'Failed'
        ? 'Generation failed'
        : status === 'Error'
          ? 'Runtime error'
          : 'Generating tool…';

  return (
    <>
      <Flex alignItems={{ default: 'alignItemsCenter' }} style={{ marginBottom: '12px' }}>
        <FlexItem>{getStatusIcon(phase)}</FlexItem>
        <FlexItem>Generation status: {status}</FlexItem>
      </Flex>
      <Progress value={progress.value} title={progressTitle} variant={progress.variant} />
      <DescriptionList style={{ marginTop: '16px' }}>
        <DescriptionListGroup>
          <DescriptionListTerm>Status</DescriptionListTerm>
          <DescriptionListDescription>{status}</DescriptionListDescription>
        </DescriptionListGroup>
        {reason && (
          <DescriptionListGroup>
            <DescriptionListTerm>
              {status === 'Error' ? 'Runtime error' : 'Failure reason'}
            </DescriptionListTerm>
            <DescriptionListDescription>{reason}</DescriptionListDescription>
          </DescriptionListGroup>
        )}
        {mcpUrl && (
          <DescriptionListGroup>
            <DescriptionListTerm>MCP URL</DescriptionListTerm>
            <DescriptionListDescription>{mcpUrl}</DescriptionListDescription>
          </DescriptionListGroup>
        )}
      </DescriptionList>
    </>
  );
};
