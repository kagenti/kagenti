// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import { useNavigate } from 'react-router-dom';
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
  Flex,
  FlexItem,
  Label,
  Skeleton,
} from '@patternfly/react-core';
import {
  CubesIcon,
  ToolboxIcon,
  ChartLineIcon,
  CogIcon,
  ArrowRightIcon,
  CheckCircleIcon,
  PlusCircleIcon,
} from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';

import { agentService, toolService, namespaceService } from '@/services/api';
import { useAuth } from '@/contexts/AuthContext';

interface QuickLinkCardProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  path: string;
  buttonText: string;
  count?: number;
  isLoading?: boolean;
}

const QuickLinkCard: React.FC<QuickLinkCardProps> = ({
  title,
  description,
  icon,
  path,
  buttonText,
  count,
  isLoading,
}) => {
  const navigate = useNavigate();

  return (
    <Card isCompact isFullHeight>
      <CardTitle>
        <Flex justifyContent={{ default: 'justifyContentSpaceBetween' }}>
          <FlexItem>
            <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {icon}
              {title}
            </span>
          </FlexItem>
          {count !== undefined && (
            <FlexItem>
              {isLoading ? (
                <Skeleton width="30px" />
              ) : (
                <Label color="blue" isCompact>
                  {count}
                </Label>
              )}
            </FlexItem>
          )}
        </Flex>
      </CardTitle>
      <CardBody>{description}</CardBody>
      <CardFooter>
        <Button
          variant="link"
          onClick={() => navigate(path)}
          icon={<ArrowRightIcon />}
          iconPosition="end"
        >
          {buttonText}
        </Button>
      </CardFooter>
    </Card>
  );
};

interface StatCardProps {
  title: string;
  value: string | number;
  icon: React.ReactNode;
  color: string;
  isLoading?: boolean;
}

const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  icon,
  color,
  isLoading,
}) => {
  return (
    <Card isCompact>
      <CardBody>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapMd' }}>
          <FlexItem>
            <div
              style={{
                backgroundColor: color,
                borderRadius: '8px',
                padding: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {icon}
            </div>
          </FlexItem>
          <FlexItem>
            <Text component="p" style={{ color: '#6a6e73', fontSize: '0.85em', margin: 0 }}>
              {title}
            </Text>
            {isLoading ? (
              <Skeleton width="60px" height="28px" />
            ) : (
              <Text component="p" style={{ fontSize: '1.5em', fontWeight: 600, margin: 0 }}>
                {value}
              </Text>
            )}
          </FlexItem>
        </Flex>
      </CardBody>
    </Card>
  );
};

export const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const { user, isAuthenticated } = useAuth();

  // Fetch namespaces first
  const { data: namespaces = [] } = useQuery({
    queryKey: ['namespaces'],
    queryFn: () => namespaceService.list(true),
  });

  // Fetch agents from first namespace (for demo stats)
  const defaultNamespace = namespaces[0] || 'team1';
  const { data: agents = [], isLoading: agentsLoading } = useQuery({
    queryKey: ['agents', defaultNamespace],
    queryFn: () => agentService.list(defaultNamespace),
    enabled: namespaces.length > 0,
  });

  // Fetch tools from first namespace
  const { data: tools = [], isLoading: toolsLoading } = useQuery({
    queryKey: ['tools', defaultNamespace],
    queryFn: () => toolService.list(defaultNamespace),
    enabled: namespaces.length > 0,
  });

  const readyAgents = agents.filter((a) => a.status === 'Ready').length;
  const readyTools = tools.filter((t) => t.status === 'Ready').length;

  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1" size="2xl">
            Welcome to the Cloud Native Agent Platform
          </Title>
          <Text component="p">
            {isAuthenticated && user
              ? `Hello, ${user.username}! `
              : ''}
            Manage, deploy, and observe your AI agents and tools with ease.
          </Text>
        </TextContent>
      </PageSection>

      <Divider component="div" />

      <PageSection>
        {/* Statistics Overview */}
        <Grid hasGutter style={{ marginBottom: '24px' }}>
          <GridItem md={6} lg={3}>
            <StatCard
              title="Total Agents"
              value={agents.length}
              icon={<CubesIcon style={{ color: 'white', fontSize: '1.5em' }} />}
              color="#0066cc"
              isLoading={agentsLoading}
            />
          </GridItem>
          <GridItem md={6} lg={3}>
            <StatCard
              title="Ready Agents"
              value={readyAgents}
              icon={<CheckCircleIcon style={{ color: 'white', fontSize: '1.5em' }} />}
              color="#3e8635"
              isLoading={agentsLoading}
            />
          </GridItem>
          <GridItem md={6} lg={3}>
            <StatCard
              title="Ready Tools"
              value={readyTools}
              icon={<ToolboxIcon style={{ color: 'white', fontSize: '1.5em' }} />}
              color="#6753ac"
              isLoading={toolsLoading}
            />
          </GridItem>
          <GridItem md={6} lg={3}>
            <StatCard
              title="Namespaces"
              value={namespaces.length}
              icon={<CogIcon style={{ color: 'white', fontSize: '1.5em' }} />}
              color="#f0ab00"
              isLoading={false}
            />
          </GridItem>
        </Grid>

        <TextContent style={{ marginBottom: '16px' }}>
          <Title headingLevel="h2" size="xl">
            Quick Actions
          </Title>
        </TextContent>

        <Grid hasGutter>
          <GridItem md={6} lg={3}>
            <QuickLinkCard
              title="Agent Catalog"
              description="Browse, interact with, and manage your deployed AI agents."
              icon={<CubesIcon />}
              path="/agents"
              buttonText="View Agents"
              count={agents.length}
              isLoading={agentsLoading}
            />
          </GridItem>
          <GridItem md={6} lg={3}>
            <QuickLinkCard
              title="Tool Catalog"
              description="Discover and manage MCP tools available to your agents."
              icon={<ToolboxIcon />}
              path="/tools"
              buttonText="View Tools"
              count={tools.length}
              isLoading={toolsLoading}
            />
          </GridItem>
          <GridItem md={6} lg={3}>
            <QuickLinkCard
              title="Observability"
              description="Access dashboards to monitor performance, traces, and network traffic."
              icon={<ChartLineIcon />}
              path="/observability"
              buttonText="View Dashboards"
            />
          </GridItem>
          <GridItem md={6} lg={3}>
            <QuickLinkCard
              title="Administration"
              description="Manage identity, authorization, and platform settings."
              icon={<CogIcon />}
              path="/admin"
              buttonText="Open Admin"
            />
          </GridItem>
        </Grid>

        {/* Quick Import Buttons */}
        <Flex gap={{ default: 'gapMd' }} style={{ marginTop: '24px' }}>
          <FlexItem>
            <Button
              variant="primary"
              icon={<PlusCircleIcon />}
              onClick={() => navigate('/agents/import')}
            >
              Import New Agent
            </Button>
          </FlexItem>
          <FlexItem>
            <Button
              variant="primary"
              icon={<PlusCircleIcon />}
              onClick={() => navigate('/tools/import')}
            >
              Import New Tool
            </Button>
          </FlexItem>
        </Flex>

        <Alert
          variant="info"
          title="Getting Started"
          isInline
          style={{ marginTop: '24px' }}
        >
          <p>
            New to Kagenti? Start by importing an agent from the examples repository,
            then chat with it to see it in action. Use the observability dashboards
            to monitor traces and network traffic.
          </p>
        </Alert>
      </PageSection>
    </>
  );
};
