// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Sandboxes Page — Lists deployed sandbox agent pods/deployments
 * with their associated sessions and resource status.
 */

import React, { useState } from 'react';
import {
  PageSection,
  Title,
  Card,
  CardBody,
  CardTitle,
  Label,
  Spinner,
  Alert,
  Split,
  SplitItem,
  Button,
  ExpandableSection,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
} from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { sandboxService } from '../services/api';
import { NamespaceSelector } from '../components/NamespaceSelector';
import type { SandboxAgentInfo, TaskSummary } from '../types/sandbox';

function statusColor(
  status: string
): 'green' | 'gold' | 'red' | 'grey' {
  switch (status) {
    case 'ready':
      return 'green';
    case 'pending':
      return 'gold';
    case 'error':
      return 'red';
    default:
      return 'grey';
  }
}

function sessionStateColor(state: string): 'blue' | 'green' | 'red' | 'orange' | 'grey' {
  switch (state) {
    case 'working':
    case 'submitted':
      return 'blue';
    case 'completed':
      return 'green';
    case 'failed':
      return 'red';
    case 'canceled':
      return 'orange';
    default:
      return 'grey';
  }
}

/** Single sandbox agent card with expandable session list. */
const SandboxAgentCard: React.FC<{
  agent: SandboxAgentInfo;
  sessions: TaskSummary[];
  namespace: string;
}> = ({ agent, sessions }) => {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(agent.active_sessions > 0);

  const agentSessions = sessions.filter((s) => {
    const meta = s.metadata as Record<string, unknown> | null;
    const agentName = (meta?.agent_name as string) || 'sandbox-legion';
    return agentName === agent.name;
  });

  return (
    <Card isCompact style={{ marginBottom: 12 }}>
      <CardTitle>
        <Split hasGutter>
          <SplitItem>
            <Label color={statusColor(agent.status)} isCompact>
              {agent.status}
            </Label>
          </SplitItem>
          <SplitItem isFilled>
            <strong>{agent.name}</strong>
          </SplitItem>
          <SplitItem>
            <Label isCompact>
              {agent.replicas} replicas
            </Label>
          </SplitItem>
          <SplitItem>
            <Label color="blue" isCompact>
              {agent.session_count} sessions
            </Label>
          </SplitItem>
          {agent.active_sessions > 0 && (
            <SplitItem>
              <Label color="gold" isCompact>
                {agent.active_sessions} active
              </Label>
            </SplitItem>
          )}
        </Split>
      </CardTitle>
      <CardBody>
        <DescriptionList isCompact isHorizontal>
          <DescriptionListGroup>
            <DescriptionListTerm>Image</DescriptionListTerm>
            <DescriptionListDescription>
              <code style={{ fontSize: '0.85em' }}>
                {agent.image.length > 60
                  ? '...' + agent.image.slice(-57)
                  : agent.image}
              </code>
            </DescriptionListDescription>
          </DescriptionListGroup>
          <DescriptionListGroup>
            <DescriptionListTerm>Created</DescriptionListTerm>
            <DescriptionListDescription>
              {agent.created
                ? new Date(agent.created).toLocaleString()
                : 'Unknown'}
            </DescriptionListDescription>
          </DescriptionListGroup>
          <DescriptionListGroup>
            <DescriptionListTerm>Namespace</DescriptionListTerm>
            <DescriptionListDescription>
              {agent.namespace}
            </DescriptionListDescription>
          </DescriptionListGroup>
        </DescriptionList>

        {agentSessions.length > 0 && (
          <ExpandableSection
            toggleText={`${expanded ? 'Hide' : 'Show'} ${agentSessions.length} session${agentSessions.length !== 1 ? 's' : ''}`}
            isExpanded={expanded}
            onToggle={(_e, isExp) => setExpanded(isExp)}
            style={{ marginTop: 8 }}
          >
            <div style={{ maxHeight: 200, overflowY: 'auto' }}>
              {agentSessions.map((session) => {
                const state = session.status?.state ?? 'unknown';
                const meta = session.metadata as Record<string, unknown> | null;
                const title = (meta?.title as string) || session.context_id.substring(0, 12);
                return (
                  <div
                    key={session.id}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '4px 8px',
                      borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
                      cursor: 'pointer',
                    }}
                    onClick={() =>
                      navigate(
                        `/sandbox?session=${encodeURIComponent(session.context_id)}`
                      )
                    }
                  >
                    <span style={{ fontSize: '0.9em' }}>
                      {title.length > 40
                        ? title.substring(0, 40) + '...'
                        : title}
                    </span>
                    <Label
                      color={sessionStateColor(state)}
                      isCompact
                    >
                      {state}
                    </Label>
                  </div>
                );
              })}
            </div>
          </ExpandableSection>
        )}

        <div style={{ marginTop: 8 }}>
          <Button
            variant="link"
            size="sm"
            onClick={() => navigate(`/sandbox?agent=${agent.name}`)}
          >
            Chat with {agent.name}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
};

export const SandboxesPage: React.FC = () => {
  const navigate = useNavigate();
  const [namespace, setNamespace] = useState('team1');

  const { data: agents, isLoading: agentsLoading, isError: agentsError } = useQuery({
    queryKey: ['sandbox-agents', namespace],
    queryFn: () => sandboxService.listAgents(namespace),
    enabled: !!namespace,
    refetchInterval: 15000,
  });

  const { data: sessionsData } = useQuery({
    queryKey: ['sandbox-sessions', namespace, '', 1, 100],
    queryFn: () =>
      sandboxService.listSessions(namespace, { limit: 100 }),
    enabled: !!namespace,
  });

  const sessions = sessionsData?.items ?? [];

  return (
    <PageSection variant="light">
      <Split hasGutter style={{ marginBottom: 16 }}>
        <SplitItem>
          <Title headingLevel="h1">Sandboxes</Title>
        </SplitItem>
        <SplitItem isFilled />
        <SplitItem>
          <NamespaceSelector
            namespace={namespace}
            onNamespaceChange={setNamespace}
          />
        </SplitItem>
        <SplitItem>
          <Button
            variant="primary"
            onClick={() => navigate('/sandbox/create')}
          >
            + Import Agent
          </Button>
        </SplitItem>
      </Split>

      {agentsLoading && <Spinner size="lg" />}

      {agentsError && (
        <Alert variant="danger" title="Failed to load sandboxes" isInline>
          Could not reach the sandbox agents API.
        </Alert>
      )}

      {!agentsLoading && agents && agents.length === 0 && (
        <Alert variant="info" title="No sandboxes deployed" isInline>
          No sandbox agents found in namespace {namespace}.{' '}
          <Button
            variant="link"
            isInline
            onClick={() => navigate('/sandbox/create')}
          >
            Import an agent
          </Button>{' '}
          to get started.
        </Alert>
      )}

      {!agentsLoading &&
        agents &&
        agents.map((agent) => (
          <SandboxAgentCard
            key={agent.name}
            agent={agent}
            sessions={sessions}
            namespace={namespace}
          />
        ))}
    </PageSection>
  );
};
