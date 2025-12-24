// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PageSection,
  Title,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
  Button,
  Spinner,
  EmptyState,
  EmptyStateHeader,
  EmptyStateIcon,
  EmptyStateBody,
  EmptyStateFooter,
  EmptyStateActions,
  Label,
  LabelGroup,
} from '@patternfly/react-core';
import {
  Table,
  Thead,
  Tr,
  Th,
  Tbody,
  Td,
} from '@patternfly/react-table';
import { CubesIcon, PlusCircleIcon } from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';

import { Agent } from '@/types';
import { agentService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';

export const AgentCatalogPage: React.FC = () => {
  const navigate = useNavigate();
  const [namespace, setNamespace] = useState<string>('team1');

  const {
    data: agents = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['agents', namespace],
    queryFn: () => agentService.list(namespace),
    enabled: !!namespace,
  });

  const columns = ['Name', 'Description', 'Status', 'Labels', 'Actions'];

  const renderStatusBadge = (status: string) => {
    const isReady = status === 'Ready';
    return (
      <Label color={isReady ? 'green' : 'red'}>{status}</Label>
    );
  };

  const renderLabels = (agent: Agent) => {
    const labels = [];
    if (agent.labels.protocol) {
      labels.push(
        <Label key="protocol" color="blue" isCompact>
          {agent.labels.protocol.toUpperCase()}
        </Label>
      );
    }
    if (agent.labels.framework) {
      labels.push(
        <Label key="framework" color="purple" isCompact>
          {agent.labels.framework}
        </Label>
      );
    }
    return <LabelGroup>{labels}</LabelGroup>;
  };

  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Agent Catalog</Title>
      </PageSection>

      <PageSection variant="light" padding={{ default: 'noPadding' }}>
        <Toolbar>
          <ToolbarContent>
            <ToolbarItem>
              <NamespaceSelector
                namespace={namespace}
                onNamespaceChange={setNamespace}
              />
            </ToolbarItem>
            <ToolbarItem>
              <Button
                variant="primary"
                icon={<PlusCircleIcon />}
                onClick={() => navigate('/agents/import')}
              >
                Import Agent
              </Button>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </PageSection>

      <PageSection>
        {isLoading ? (
          <div className="kagenti-loading-center">
            <Spinner size="lg" aria-label="Loading agents" />
          </div>
        ) : isError ? (
          <EmptyState>
            <EmptyStateHeader
              titleText="Error loading agents"
              icon={<EmptyStateIcon icon={CubesIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              {error instanceof Error
                ? error.message
                : 'Unable to fetch agents from the cluster.'}
            </EmptyStateBody>
          </EmptyState>
        ) : agents.length === 0 ? (
          <EmptyState>
            <EmptyStateHeader
              titleText="No agents found"
              icon={<EmptyStateIcon icon={CubesIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              No agents found in namespace "{namespace}".
            </EmptyStateBody>
            <EmptyStateFooter>
              <EmptyStateActions>
                <Button
                  variant="primary"
                  onClick={() => navigate('/agents/import')}
                >
                  Import Agent
                </Button>
              </EmptyStateActions>
            </EmptyStateFooter>
          </EmptyState>
        ) : (
          <Table aria-label="Agents table" variant="compact">
            <Thead>
              <Tr>
                {columns.map((col) => (
                  <Th key={col}>{col}</Th>
                ))}
              </Tr>
            </Thead>
            <Tbody>
              {agents.map((agent) => (
                <Tr key={`${agent.namespace}-${agent.name}`}>
                  <Td dataLabel="Name">
                    <Button
                      variant="link"
                      isInline
                      onClick={() =>
                        navigate(`/agents/${agent.namespace}/${agent.name}`)
                      }
                    >
                      {agent.name}
                    </Button>
                  </Td>
                  <Td dataLabel="Description">
                    {agent.description || 'No description'}
                  </Td>
                  <Td dataLabel="Status">{renderStatusBadge(agent.status)}</Td>
                  <Td dataLabel="Labels">{renderLabels(agent)}</Td>
                  <Td dataLabel="Actions">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        navigate(`/agents/${agent.namespace}/${agent.name}`)
                      }
                    >
                      View Details
                    </Button>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </PageSection>
    </>
  );
};
