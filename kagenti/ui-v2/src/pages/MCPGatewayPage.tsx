// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import {
  PageSection,
  Title,
  Text,
  TextContent,
  Card,
  CardTitle,
  CardBody,
  Divider,
  Alert,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Label,
  Skeleton,
  Button,
  Grid,
  GridItem,
  CardFooter,
} from '@patternfly/react-core';
import {
  PluggedIcon,
  ExternalLinkAltIcon,
  CubesIcon,
  OutlinedClockIcon,
} from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';

import { API_CONFIG } from '@/services/api';

export const MCPGatewayPage: React.FC = () => {
  // Placeholder query - will be replaced with actual API call
  const { isLoading } = useQuery({
    queryKey: ['mcp-gateway-status'],
    queryFn: async () => {
      // Placeholder - return mock data for now
      return { status: 'running', tools: 12, uptime: '5d 12h' };
    },
    enabled: false, // Disabled until API is ready
  });

  const mcpInspectorUrl = `http://mcp-inspector.${API_CONFIG.domainName}:8080`;

  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">MCP Gateway</Title>
          <Text component="p">
            The MCP Gateway provides a unified entry point for all Model Context Protocol (MCP) tools
            deployed in the platform. It handles tool discovery, routing, and protocol translation.
          </Text>
        </TextContent>
      </PageSection>

      <PageSection variant="light">
        <Alert variant="info" title="Feature Preview" isInline>
          This page is under active development. Full management capabilities will be available in a future release.
        </Alert>
      </PageSection>

      <Divider component="div" />

      <PageSection>
        <Grid hasGutter>
          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <PluggedIcon />
                  Gateway Status
                </span>
              </CardTitle>
              <CardBody>
                {isLoading ? (
                  <>
                    <Skeleton width="60%" style={{ marginBottom: '8px' }} />
                    <Skeleton width="80%" style={{ marginBottom: '8px' }} />
                    <Skeleton width="50%" />
                  </>
                ) : (
                  <DescriptionList isCompact>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Status</DescriptionListTerm>
                      <DescriptionListDescription>
                        <Label color="green">Running</Label>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Namespace</DescriptionListTerm>
                      <DescriptionListDescription>
                        <code>gateway-system</code>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Protocol</DescriptionListTerm>
                      <DescriptionListDescription>
                        MCP (Streamable HTTP)
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                  </DescriptionList>
                )}
              </CardBody>
            </Card>
          </GridItem>

          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <CubesIcon />
                  Gateway Metrics
                </span>
              </CardTitle>
              <CardBody>
                <DescriptionList isCompact>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Registered Tools</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="blue">—</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Active Connections</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="blue">—</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Uptime</DescriptionListTerm>
                    <DescriptionListDescription>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <OutlinedClockIcon /> —
                      </span>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>
              </CardBody>
            </Card>
          </GridItem>

          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>MCP Inspector</CardTitle>
              <CardBody>
                <Text component="p">
                  Browse and test MCP tools registered with the gateway using the MCP Inspector interface.
                </Text>
                <Text
                  component="small"
                  style={{ color: '#6a6e73', marginTop: '8px', display: 'block' }}
                >
                  {mcpInspectorUrl}
                </Text>
              </CardBody>
              <CardFooter>
                <Button
                  variant="primary"
                  component="a"
                  href={mcpInspectorUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  icon={<ExternalLinkAltIcon />}
                  iconPosition="end"
                >
                  Open MCP Inspector
                </Button>
              </CardFooter>
            </Card>
          </GridItem>
        </Grid>
      </PageSection>
    </>
  );
};
