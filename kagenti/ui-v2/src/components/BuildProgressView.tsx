// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Shared BuildProgressView component for displaying Shipwright build progress.
 *
 * This component can be used by both agent and tool pages to show:
 * - Build progress with phase indicator
 * - Source configuration details
 * - Resource configuration (agent/tool specific)
 * - Auto-finalize behavior on success
 */

import React from 'react';
import {
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
  Flex,
  FlexItem,
  Text,
  TextContent,
  ClipboardCopy,
  Button,
  Spinner,
} from '@patternfly/react-core';
import {
  CheckCircleIcon,
  ExclamationCircleIcon,
  InProgressIcon,
  ClockIcon,
} from '@patternfly/react-icons';

import type {
  ResourceType,
  BuildRunPhase,
  ResourceConfigFromBuild,
} from '@/services/shipwright';

/**
 * Build info subset needed by this component.
 * Compatible with both ShipwrightBuildInfo and AgentShipwrightBuildInfo.
 */
export interface BuildProgressBuildInfo {
  name: string;
  namespace: string;
  buildRegistered: boolean;
  buildReason?: string;
  buildMessage?: string;
  outputImage: string;
  strategy: string;
  gitUrl: string;
  gitRevision: string;
  contextDir: string;

  hasBuildRun: boolean;
  buildRunName?: string;
  buildRunPhase?: BuildRunPhase;
  buildRunStartTime?: string;
  buildRunCompletionTime?: string;
  buildRunOutputImage?: string;
  buildRunOutputDigest?: string;
  buildRunFailureMessage?: string;

  // Generic resource config (or agentConfig for backwards compatibility)
  resourceConfig?: ResourceConfigFromBuild;
  agentConfig?: ResourceConfigFromBuild;
}

export interface BuildProgressViewProps {
  /** The build info to display */
  buildInfo: BuildProgressBuildInfo;

  /** Type of resource being built */
  resourceType: ResourceType;

  /** Whether auto-finalization is in progress */
  isAutoFinalizing?: boolean;

  /** Error from finalization attempt */
  finalizeError?: Error | null;

  /** Whether a retry build is pending */
  isRetryPending?: boolean;

  /** Callback to retry the build */
  onRetryBuild?: () => void;

  /** Callback to retry finalization */
  onRetryFinalize?: () => void;
}

/**
 * Get progress info based on build phase
 */
function getProgressInfo(phase?: BuildRunPhase) {
  switch (phase) {
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
}

/**
 * Get status icon based on build phase
 */
function getStatusIcon(phase?: BuildRunPhase) {
  switch (phase) {
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
}

/**
 * Format duration between two timestamps
 */
function formatDuration(startTime?: string, endTime?: string): string {
  if (!startTime) return '-';
  const start = new Date(startTime);
  const end = endTime ? new Date(endTime) : new Date();
  const seconds = Math.floor((end.getTime() - start.getTime()) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}

/**
 * Get the resource label based on type
 */
function getResourceLabel(resourceType: ResourceType): string {
  return resourceType === 'agent' ? 'Agent' : 'Tool';
}

/**
 * Shared build progress view component.
 */
export const BuildProgressView: React.FC<BuildProgressViewProps> = ({
  buildInfo,
  resourceType,
  isAutoFinalizing = false,
  finalizeError = null,
  isRetryPending = false,
  onRetryBuild,
  onRetryFinalize,
}) => {
  const progressInfo = getProgressInfo(buildInfo.buildRunPhase);
  const resourceLabel = getResourceLabel(resourceType);

  // Get config from either resourceConfig or agentConfig (for backwards compatibility)
  const resourceConfig = buildInfo.resourceConfig || buildInfo.agentConfig;

  return (
    <>
      {/* Auto-finalize status */}
      {isAutoFinalizing && (
        <Alert
          variant="info"
          title={`Creating ${resourceLabel}`}
          isInline
          style={{ marginBottom: '16px' }}
        >
          <Flex alignItems={{ default: 'alignItemsCenter' }}>
            <FlexItem>
              <Spinner size="md" />
            </FlexItem>
            <FlexItem>Build succeeded! Creating the {resourceLabel} deployment...</FlexItem>
          </Flex>
        </Alert>
      )}

      {/* Finalize error */}
      {finalizeError && (
        <Alert
          variant="danger"
          title={`Failed to create ${resourceLabel}`}
          isInline
          style={{ marginBottom: '16px' }}
        >
          {finalizeError.message}
          {onRetryFinalize && (
            <Button
              variant="link"
              onClick={onRetryFinalize}
              style={{ marginLeft: '16px' }}
            >
              Retry
            </Button>
          )}
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
          {buildInfo.buildRunPhase === 'Failed' && onRetryBuild && (
            <Button
              variant="primary"
              onClick={onRetryBuild}
              isLoading={isRetryPending}
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
                <a href={buildInfo.gitUrl} target="_blank" rel="noopener noreferrer">
                  {buildInfo.gitUrl}
                </a>
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

      {/* Resource Configuration Card */}
      {resourceConfig && (
        <Card>
          <CardTitle>{resourceLabel} Configuration</CardTitle>
          <CardBody>
            <TextContent style={{ marginBottom: '16px' }}>
              <Text>
                The following configuration will be applied when the {resourceLabel} is created:
              </Text>
            </TextContent>
            <DescriptionList>
              <DescriptionListGroup>
                <DescriptionListTerm>Protocol</DescriptionListTerm>
                <DescriptionListDescription>
                  <Label color="blue">{resourceConfig.protocol}</Label>
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Framework</DescriptionListTerm>
                <DescriptionListDescription>
                  <Label color="purple">{resourceConfig.framework}</Label>
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>External Access</DescriptionListTerm>
                <DescriptionListDescription>
                  {resourceConfig.createHttpRoute ? (
                    <Label color="green">HTTPRoute will be created</Label>
                  ) : (
                    <Label color="grey">No external access</Label>
                  )}
                </DescriptionListDescription>
              </DescriptionListGroup>
              {resourceConfig.envVars && resourceConfig.envVars.length > 0 && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Environment Variables</DescriptionListTerm>
                  <DescriptionListDescription>
                    {resourceConfig.envVars.length} variable(s) configured
                  </DescriptionListDescription>
                </DescriptionListGroup>
              )}
              {resourceConfig.servicePorts && resourceConfig.servicePorts.length > 0 && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Service Ports</DescriptionListTerm>
                  <DescriptionListDescription>
                    {resourceConfig.servicePorts.map((port) => (
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
    </>
  );
};

/**
 * Export helper functions for use by pages
 */
export { getStatusIcon, formatDuration, getProgressInfo };
