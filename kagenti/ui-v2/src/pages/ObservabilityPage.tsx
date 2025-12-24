// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import {
  PageSection,
  Title,
  Text,
  TextContent,
  Grid,
  GridItem,
  Card,
  CardTitle,
  CardBody,
  CardFooter,
  Button,
  Divider,
  Alert,
  Skeleton,
} from '@patternfly/react-core';
import {
  ChartLineIcon,
  NetworkIcon,
  ExternalLinkAltIcon,
} from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';

import { configService, API_CONFIG } from '@/services/api';

interface DashboardCardProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  url: string;
  buttonText: string;
  isLoading?: boolean;
}

const DashboardCard: React.FC<DashboardCardProps> = ({
  title,
  description,
  icon,
  url,
  buttonText,
  isLoading,
}) => {
  return (
    <Card isCompact isFullHeight>
      <CardTitle>
        <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {icon}
          {title}
        </span>
      </CardTitle>
      <CardBody>
        <Text component="p">{description}</Text>
        {isLoading ? (
          <Skeleton width="80%" style={{ marginTop: '8px' }} />
        ) : (
          <Text
            component="small"
            style={{ color: '#6a6e73', marginTop: '8px', display: 'block' }}
          >
            {url}
          </Text>
        )}
      </CardBody>
      <CardFooter>
        <Button
          variant="primary"
          component="a"
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          icon={<ExternalLinkAltIcon />}
          iconPosition="end"
          isDisabled={isLoading || !url}
        >
          {buttonText}
        </Button>
      </CardFooter>
    </Card>
  );
};

export const ObservabilityPage: React.FC = () => {
  const { data: dashboards, isLoading, isError } = useQuery({
    queryKey: ['dashboards'],
    queryFn: () => configService.getDashboards(),
  });

  // Fallback URLs using domain config
  const tracesUrl = dashboards?.traces || `http://phoenix.${API_CONFIG.domainName}:8080`;
  const networkUrl = dashboards?.network || `http://kiali.${API_CONFIG.domainName}:8080`;

  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">Observability Dashboard</Title>
          <Text component="p">
            Access various dashboards to monitor the health, performance, traces,
            and network traffic of your deployed agents and tools.
          </Text>
        </TextContent>
      </PageSection>

      <Divider component="div" />

      <PageSection>
        {isError && (
          <Alert
            variant="warning"
            title="Could not load dashboard configuration"
            isInline
            style={{ marginBottom: '16px' }}
          >
            Using default URLs. Some dashboards may not be accessible.
          </Alert>
        )}

        <Grid hasGutter>
          <GridItem md={6}>
            <DashboardCard
              title="Tracing & Performance"
              description="Access detailed trace data for debugging and performance analysis. Monitor LLM calls, latency, and token usage with Phoenix/OpenTelemetry."
              icon={<ChartLineIcon />}
              url={tracesUrl}
              buttonText="Open Phoenix"
              isLoading={isLoading}
            />
          </GridItem>

          <GridItem md={6}>
            <DashboardCard
              title="Network Traffic"
              description="Visualize service interactions, traffic flow, and service mesh health with Kiali. Monitor Istio metrics and network policies."
              icon={<NetworkIcon />}
              url={networkUrl}
              buttonText="Open Kiali"
              isLoading={isLoading}
            />
          </GridItem>
        </Grid>

        <Alert
          variant="info"
          title="Note"
          isInline
          style={{ marginTop: '24px' }}
        >
          Ensure that the observability tools (Phoenix for traces and Kiali for
          service mesh) are properly configured and accessible from your
          environment. Default credentials are typically <code>admin/admin</code>.
        </Alert>
      </PageSection>
    </>
  );
};
