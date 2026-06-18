import React, { useState } from 'react';
import {
  Card,
  CardBody,
  CardTitle,
  Gallery,
  GalleryItem,
  Label,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Spinner,
  EmptyState,
  EmptyStateBody,
  EmptyStateHeader,
  EmptyStateIcon,
  Title,
  Text,
  TextContent,
} from '@patternfly/react-core';
import { CubesIcon } from '@patternfly/react-icons';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { agentService, namespaceService } from '@/services/api';
import type { Agent } from '@/types';

function statusColor(status: string): 'green' | 'red' | 'orange' | 'grey' {
  switch (status) {
    case 'Ready':
      return 'green';
    case 'Not Ready':
      return 'red';
    case 'Progressing':
      return 'orange';
    default:
      return 'grey';
  }
}

export const AgentListPage: React.FC = () => {
  const [namespace, setNamespace] = useState('');
  const navigate = useNavigate();

  const nsQuery = useQuery({
    queryKey: ['namespaces'],
    queryFn: () => namespaceService.list(),
  });

  // Auto-select first namespace
  React.useEffect(() => {
    if (!namespace && nsQuery.data && nsQuery.data.length > 0) {
      setNamespace(nsQuery.data[0]);
    }
  }, [namespace, nsQuery.data]);

  const agentQuery = useQuery({
    queryKey: ['agents', namespace],
    queryFn: () => agentService.list(namespace),
    enabled: !!namespace,
  });

  return (
    <div>
      <div style={{ marginBottom: '24px' }}>
        <Title headingLevel="h1" size="2xl">
          Select an Agent
        </Title>
        <TextContent style={{ marginTop: '8px' }}>
          <Text>Choose an agent to send a task to.</Text>
        </TextContent>
      </div>

      <FormGroup label="Namespace" fieldId="namespace-select" style={{ maxWidth: '300px', marginBottom: '24px' }}>
        <FormSelect
          id="namespace-select"
          value={namespace}
          onChange={(_event, value) => setNamespace(value)}
          isDisabled={nsQuery.isLoading}
        >
          {nsQuery.isLoading && (
            <FormSelectOption key="loading" value="" label="Loading..." isDisabled />
          )}
          {nsQuery.data?.map((ns) => (
            <FormSelectOption key={ns} value={ns} label={ns} />
          ))}
        </FormSelect>
      </FormGroup>

      {agentQuery.isLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '48px' }}>
          <Spinner size="xl" />
        </div>
      )}

      {agentQuery.data && agentQuery.data.length === 0 && (
        <EmptyState>
          <EmptyStateHeader
            titleText="No Agents Found"
            icon={<EmptyStateIcon icon={CubesIcon} />}
            headingLevel="h2"
          />
          <EmptyStateBody>
            No agents are deployed in the <strong>{namespace}</strong> namespace.
          </EmptyStateBody>
        </EmptyState>
      )}

      {agentQuery.data && agentQuery.data.length > 0 && (
        <Gallery hasGutter minWidths={{ default: '300px' }}>
          {agentQuery.data.map((agent: Agent) => (
            <GalleryItem key={`${agent.namespace}/${agent.name}`}>
              <Card
                isClickable
                isSelectable
                onClick={() => navigate(`/chat/${agent.namespace}/${agent.name}`)}
                style={{ cursor: 'pointer' }}
              >
                <CardTitle>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <span>{agent.name}</span>
                    <Label color={statusColor(agent.status)}>{agent.status}</Label>
                  </div>
                </CardTitle>
                <CardBody>
                  <TextContent>
                    <Text component="small" style={{ color: '#6a6e73' }}>
                      {agent.namespace}
                      {agent.labels?.framework ? ` / ${agent.labels.framework}` : ''}
                    </Text>
                    <Text>{agent.description || 'No description available'}</Text>
                  </TextContent>
                </CardBody>
              </Card>
            </GalleryItem>
          ))}
        </Gallery>
      )}
    </div>
  );
};
