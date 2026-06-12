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
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Label,
  Skeleton,
  Checkbox,
  Split,
  SplitItem,
} from '@patternfly/react-core';
import {
  KeyIcon,
  CogIcon,
  ExternalLinkAltIcon,
  UserIcon,
  ShieldAltIcon,
} from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';

import { useAuth } from '@/contexts';
import { configService } from '@/services/api';
import type { ComponentStatus } from '@/services/api';
import { useFeatureFlags, type FeatureFlags } from '@/hooks/useFeatureFlags';

const POLL_INTERVAL_MS = 15_000;

// Auth status API service
async function getAuthStatus(): Promise<{
  enabled: boolean;
  authenticated: boolean;
  keycloak_url?: string;
  realm?: string;
  client_id?: string;
}> {
  const response = await fetch('/api/v1/auth/status');
  if (!response.ok) {
    throw new Error('Failed to fetch auth status');
  }
  return response.json();
}

const STATUS_COLOR: Record<ComponentStatus['status'], 'green' | 'gold' | 'grey'> = {
  Ready: 'green',
  Degraded: 'gold',
  Missing: 'grey',
  Unknown: 'grey',
};

type DisplayedFlag = Exclude<keyof FeatureFlags, 'admin'>;

const FLAG_LABELS: Record<DisplayedFlag, string> = {
  builds: 'Builds (Shipwright)',
  sandbox: 'Sandbox',
  integrations: 'Integrations',
  triggers: 'Triggers',
  agentSandbox: 'Agent Sandbox',
  skills: 'Skills',
  authbridgeAPI: 'AuthBridge API',
  externalSkills: 'External Skills',
};

const PlatformStatusCard: React.FC = () => {
  const flags = useFeatureFlags();

  const { data: platformStatus, isLoading } = useQuery({
    queryKey: ['platform-status'],
    queryFn: () => configService.getPlatformStatus(),
    refetchInterval: POLL_INTERVAL_MS,
  });

  return (
    <Card isFullHeight>
      <CardTitle>
        <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <CogIcon />
          Platform Status
        </span>
      </CardTitle>
      <CardBody>
        {isLoading ? (
          <>
            <Skeleton width="80%" style={{ marginBottom: '8px' }} />
            <Skeleton width="60%" style={{ marginBottom: '8px' }} />
            <Skeleton width="70%" />
          </>
        ) : (
          <>
            <Split hasGutter>
              <SplitItem isFilled>
                <Text component="small" style={{ fontWeight: 600, marginBottom: '8px', display: 'block' }}>
                  Components
                </Text>
                <DescriptionList isCompact isHorizontal>
                  {(platformStatus?.components ?? []).map((c) => (
                    <DescriptionListGroup key={c.name}>
                      <DescriptionListTerm>{c.name}</DescriptionListTerm>
                      <DescriptionListDescription>
                        <Label color={STATUS_COLOR[c.status]} isCompact>
                          {c.status}
                        </Label>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                  ))}
                </DescriptionList>
              </SplitItem>

              <SplitItem isFilled>
                <Text component="small" style={{ fontWeight: 600, marginBottom: '8px', display: 'block' }}>
                  Feature Flags
                </Text>
                {(Object.keys(FLAG_LABELS) as DisplayedFlag[]).map((key) => (
                  <Checkbox
                    key={key}
                    id={`flag-${key}`}
                    label={FLAG_LABELS[key]}
                    isChecked={flags[key]}
                    isDisabled
                    style={{ marginBottom: '4px' }}
                  />
                ))}
              </SplitItem>
            </Split>

            <Divider component="div" style={{ margin: '12px 0' }} />

            <Text component="small" style={{ fontWeight: 600, marginBottom: '8px', display: 'block' }}>
              Registry &amp; Build
            </Text>
            <DescriptionList isCompact isHorizontal style={{ '--pf-v5-c-description-list--m-horizontal__term--width': '11rem' } as React.CSSProperties}>
              <DescriptionListGroup>
                <DescriptionListTerm style={{ whiteSpace: 'nowrap' }}>ClusterBuildStrategy</DescriptionListTerm>
                <DescriptionListDescription>
                  <Label
                    color={platformStatus?.registry.clusterBuildStrategyPresent ? 'green' : 'grey'}
                    isCompact
                  >
                    {platformStatus?.registry.clusterBuildStrategyPresent ? 'Present' : 'Missing'}
                  </Label>
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Registry endpoint</DescriptionListTerm>
                <DescriptionListDescription>
                  <code>{platformStatus?.registry.registryEndpoint ?? '—'}</code>
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>
          </>
        )}
      </CardBody>
    </Card>
  );
};

export const AdminPage: React.FC = () => {
  const { user, isAuthenticated, isEnabled } = useAuth();
  const featureFlags = useFeatureFlags();

  const { data: authStatus, isLoading } = useQuery({
    queryKey: ['auth-status'],
    queryFn: getAuthStatus,
  });

  // Fetch dashboard config for Keycloak console URL
  const { data: dashboardConfig } = useQuery({
    queryKey: ['dashboards'],
    queryFn: () => configService.getDashboards(),
  });

  // Build Keycloak admin console URL from dashboard config or auth status
  const keycloakBaseUrl = authStatus?.keycloak_url || dashboardConfig?.keycloakConsole?.replace(/\/admin\/.*$/, '') || '';
  const realm = authStatus?.realm || 'kagenti';
  // Prefer keycloakConsole from config (which comes from ConfigMap), fallback to constructed URL
  const keycloakAdminUrl = dashboardConfig?.keycloakConsole || `${keycloakBaseUrl}/admin/${realm}/console/`;

  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">Administration & Identity Management</Title>
          <Text component="p">
            This section provides access to administrative functions, including
            identity and access management via the Keycloak console.
          </Text>
        </TextContent>
      </PageSection>

      <PageSection variant="light">
        <Alert variant="info" title="Admin Role" isInline>
          As an administrator, you manage multiple personas across the platform.
          Learn about all user types in our{' '}
          <a
            href="https://github.com/kagenti/kagenti/blob/main/PERSONAS_AND_ROLES.md#2-operatoradministrator-personas"
            target="_blank"
            rel="noopener noreferrer"
          >
            Personas and Roles Documentation
          </a>
          .
        </Alert>
      </PageSection>

      <Divider component="div" />

      <PageSection>
        <Grid hasGutter>
          {/* Current User Info */}
          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <UserIcon />
                  Current Session
                </span>
              </CardTitle>
              <CardBody>
                <DescriptionList isCompact>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Authentication</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color={isEnabled ? 'blue' : 'grey'}>
                        {isEnabled ? 'Enabled' : 'Disabled'}
                      </Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Status</DescriptionListTerm>
                    <DescriptionListDescription>
                      <Label color={isAuthenticated ? 'green' : 'orange'}>
                        {isAuthenticated ? 'Authenticated' : 'Guest'}
                      </Label>
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                  {user && (
                    <>
                      <DescriptionListGroup>
                        <DescriptionListTerm>Username</DescriptionListTerm>
                        <DescriptionListDescription>
                          {user.username}
                        </DescriptionListDescription>
                      </DescriptionListGroup>
                      {user.email && (
                        <DescriptionListGroup>
                          <DescriptionListTerm>Email</DescriptionListTerm>
                          <DescriptionListDescription>
                            {user.email}
                          </DescriptionListDescription>
                        </DescriptionListGroup>
                      )}
                      {user.roles && user.roles.length > 0 && (
                        <DescriptionListGroup>
                          <DescriptionListTerm>Roles</DescriptionListTerm>
                          <DescriptionListDescription>
                            {user.roles.map((role) => (
                              <Label key={role} isCompact style={{ marginRight: '4px' }}>
                                {role}
                              </Label>
                            ))}
                          </DescriptionListDescription>
                        </DescriptionListGroup>
                      )}
                    </>
                  )}
                </DescriptionList>
              </CardBody>
            </Card>
          </GridItem>

          {/* Auth Configuration */}
          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <ShieldAltIcon />
                  Authentication Configuration
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
                      <DescriptionListTerm>Provider</DescriptionListTerm>
                      <DescriptionListDescription>
                        Keycloak
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Realm</DescriptionListTerm>
                      <DescriptionListDescription>
                        <code>{realm}</code>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Client ID</DescriptionListTerm>
                      <DescriptionListDescription>
                        <code>{authStatus?.client_id || 'kagenti-ui'}</code>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Server URL</DescriptionListTerm>
                      <DescriptionListDescription>
                        <a href={keycloakBaseUrl} target="_blank" rel="noopener noreferrer">
                          {keycloakBaseUrl}
                        </a>
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                  </DescriptionList>
                )}
              </CardBody>
            </Card>
          </GridItem>

          {/* Keycloak Admin Console */}
          <GridItem md={6}>
            <Card isFullHeight>
              <CardTitle>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <KeyIcon />
                  Identity Management (Keycloak)
                </span>
              </CardTitle>
              <CardBody>
                <Text component="p">
                  Manage users, roles, client configurations, and authentication
                  policies for the Cloud Native Agent Platform.
                </Text>
                <Text
                  component="small"
                  style={{
                    color: '#6a6e73',
                    marginTop: '8px',
                    display: 'block',
                  }}
                >
                  {keycloakAdminUrl}
                </Text>
              </CardBody>
              <CardFooter>
                <Button
                  variant="primary"
                  component="a"
                  href={keycloakAdminUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  icon={<ExternalLinkAltIcon />}
                  iconPosition="end"
                >
                  Open Keycloak Console
                </Button>
              </CardFooter>
            </Card>
          </GridItem>

          {/* Platform Status */}
          {featureFlags.admin && (
            <GridItem md={6}>
              <PlatformStatusCard />
            </GridItem>
          )}
        </Grid>
      </PageSection>
    </>
  );
};
