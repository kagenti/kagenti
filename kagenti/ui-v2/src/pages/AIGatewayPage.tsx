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
  Grid,
  GridItem,
} from '@patternfly/react-core';
import {
  CloudIcon,
  KeyIcon,
  RouteIcon,
} from '@patternfly/react-icons';

export const AIGatewayPage: React.FC = () => {
  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">AI Gateway</Title>
          <Text component="p">
            The AI Gateway manages LLM provider connections, API key rotation, request routing,
            and provides a unified interface for accessing multiple AI model providers.
          </Text>
        </TextContent>
      </PageSection>

      <PageSection variant="light">
        <Alert variant="info" title="Coming Soon" isInline>
          AI Gateway management is under development. This page will provide capabilities for
          managing LLM provider configurations, API keys, rate limiting, and request routing.
        </Alert>
      </PageSection>

      <Divider component="div" />

      <PageSection>
        <Grid hasGutter>
          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <CloudIcon />
                  LLM Providers
                </span>
              </CardTitle>
              <CardBody>
                <DescriptionList isCompact>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Configured Providers</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">Not configured</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Default Provider</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">—</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>
                <Text component="p" style={{ marginTop: '16px', color: '#6a6e73' }}>
                  Configure connections to OpenAI, Anthropic, Azure OpenAI, IBM watsonx, and other LLM providers.
                </Text>
              </CardBody>
            </Card>
          </GridItem>

          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <KeyIcon />
                  API Key Management
                </span>
              </CardTitle>
              <CardBody>
                <DescriptionList isCompact>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Stored Keys</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">—</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Key Rotation</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">Disabled</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>
                <Text component="p" style={{ marginTop: '16px', color: '#6a6e73' }}>
                  Securely manage and rotate API keys for LLM providers using Kubernetes secrets.
                </Text>
              </CardBody>
            </Card>
          </GridItem>

          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <RouteIcon />
                  Request Routing
                </span>
              </CardTitle>
              <CardBody>
                <DescriptionList isCompact>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Routing Rules</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">None configured</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Load Balancing</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">Disabled</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>
                <Text component="p" style={{ marginTop: '16px', color: '#6a6e73' }}>
                  Configure intelligent routing between LLM providers based on cost, latency, or model capabilities.
                </Text>
              </CardBody>
            </Card>
          </GridItem>
        </Grid>
      </PageSection>
    </>
  );
};
