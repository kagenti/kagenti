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
import { ToolboxIcon, PlusCircleIcon } from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';

import { Tool } from '@/types';
import { toolService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';

export const ToolCatalogPage: React.FC = () => {
  const navigate = useNavigate();
  const [namespace, setNamespace] = useState<string>('team1');

  const {
    data: tools = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['tools', namespace],
    queryFn: () => toolService.list(namespace),
    enabled: !!namespace,
  });

  const columns = ['Name', 'Description', 'Status', 'Labels', 'Actions'];

  const renderStatusBadge = (status: string) => {
    const isReady = status === 'Ready';
    return <Label color={isReady ? 'green' : 'red'}>{status}</Label>;
  };

  const renderLabels = (tool: Tool) => {
    const labels = [];
    if (tool.labels.protocol) {
      labels.push(
        <Label key="protocol" color="blue" isCompact>
          {tool.labels.protocol.toUpperCase()}
        </Label>
      );
    }
    if (tool.labels.framework) {
      labels.push(
        <Label key="framework" color="purple" isCompact>
          {tool.labels.framework}
        </Label>
      );
    }
    return <LabelGroup>{labels}</LabelGroup>;
  };

  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Tool Catalog</Title>
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
                onClick={() => navigate('/tools/import')}
              >
                Import Tool
              </Button>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </PageSection>

      <PageSection>
        {isLoading ? (
          <div className="kagenti-loading-center">
            <Spinner size="lg" aria-label="Loading tools" />
          </div>
        ) : isError ? (
          <EmptyState>
            <EmptyStateHeader
              titleText="Error loading tools"
              icon={<EmptyStateIcon icon={ToolboxIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              {error instanceof Error
                ? error.message
                : 'Unable to fetch tools from the cluster.'}
            </EmptyStateBody>
          </EmptyState>
        ) : tools.length === 0 ? (
          <EmptyState>
            <EmptyStateHeader
              titleText="No tools found"
              icon={<EmptyStateIcon icon={ToolboxIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              No tools found in namespace "{namespace}".
            </EmptyStateBody>
            <EmptyStateFooter>
              <EmptyStateActions>
                <Button
                  variant="primary"
                  onClick={() => navigate('/tools/import')}
                >
                  Import Tool
                </Button>
              </EmptyStateActions>
            </EmptyStateFooter>
          </EmptyState>
        ) : (
          <Table aria-label="Tools table" variant="compact">
            <Thead>
              <Tr>
                {columns.map((col) => (
                  <Th key={col}>{col}</Th>
                ))}
              </Tr>
            </Thead>
            <Tbody>
              {tools.map((tool) => (
                <Tr key={`${tool.namespace}-${tool.name}`}>
                  <Td dataLabel="Name">
                    <Button
                      variant="link"
                      isInline
                      onClick={() =>
                        navigate(`/tools/${tool.namespace}/${tool.name}`)
                      }
                    >
                      {tool.name}
                    </Button>
                  </Td>
                  <Td dataLabel="Description">
                    {tool.description || 'No description'}
                  </Td>
                  <Td dataLabel="Status">{renderStatusBadge(tool.status)}</Td>
                  <Td dataLabel="Labels">{renderLabels(tool)}</Td>
                  <Td dataLabel="Actions">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        navigate(`/tools/${tool.namespace}/${tool.name}`)
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
