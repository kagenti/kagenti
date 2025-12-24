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
  FilterIcon,
  ClockIcon,
  ShieldAltIcon,
} from '@patternfly/react-icons';

export const GatewayPoliciesPage: React.FC = () => {
  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">Gateway Policies</Title>
          <Text component="p">
            Define and manage policies that control traffic flow, rate limiting, authentication,
            and authorization for the MCP and AI gateways.
          </Text>
        </TextContent>
      </PageSection>

      <PageSection variant="light">
        <Alert variant="info" title="Coming Soon" isInline>
          Policy management is under development. This page will allow you to configure
          rate limiting, access control, and traffic shaping policies.
        </Alert>
      </PageSection>

      <Divider component="div" />

      <PageSection>
        <Grid hasGutter>
          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <ClockIcon />
                  Rate Limiting
                </span>
              </CardTitle>
              <CardBody>
                <DescriptionList isCompact>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Global Rate Limit</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">Not configured</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Per-Agent Limits</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">None</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>
                <Text component="p" style={{ marginTop: '16px', color: '#6a6e73' }}>
                  Configure rate limits to protect backend services and manage resource consumption.
                </Text>
              </CardBody>
            </Card>
          </GridItem>

          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <ShieldAltIcon />
                  Access Control
                </span>
              </CardTitle>
              <CardBody>
                <DescriptionList isCompact>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Authentication</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="blue">OAuth2/OIDC</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Authorization Policies</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">None configured</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>
                <Text component="p" style={{ marginTop: '16px', color: '#6a6e73' }}>
                  Define which users, roles, or services can access specific agents and tools.
                </Text>
              </CardBody>
            </Card>
          </GridItem>

          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <FilterIcon />
                  Traffic Policies
                </span>
              </CardTitle>
              <CardBody>
                <DescriptionList isCompact>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Retry Policy</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">Default</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Timeout Policy</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">Default</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Circuit Breaker</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color="gold">Disabled</Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>
                <Text component="p" style={{ marginTop: '16px', color: '#6a6e73' }}>
                  Configure traffic management policies for resilient service communication.
                </Text>
              </CardBody>
            </Card>
          </GridItem>
        </Grid>
      </PageSection>
    </>
  );
};
