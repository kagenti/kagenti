// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import { Label, Spinner, Title, Tooltip } from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import { sandboxService } from '../services/api';
import type { SandboxAgentInfo } from '../types/sandbox';

interface SandboxAgentsPanelProps {
  namespace: string;
  /** Currently selected/active agent name. */
  selectedAgent?: string;
  /** Called when user clicks an agent to switch. */
  onSelectAgent?: (agentName: string) => void;
}

function statusDotColor(status: SandboxAgentInfo['status']): string {
  switch (status) {
    case 'ready':
      return 'var(--pf-v5-global--success-color--100)';
    case 'pending':
      return 'var(--pf-v5-global--warning-color--100)';
    case 'error':
      return 'var(--pf-v5-global--danger-color--100)';
    default:
      return 'var(--pf-v5-global--Color--200)';
  }
}

function sessionText(agent: SandboxAgentInfo): string {
  const parts: string[] = [];
  parts.push(`${agent.session_count} session${agent.session_count !== 1 ? 's' : ''}`);
  if (agent.active_sessions > 0) {
    parts.push(`${agent.active_sessions} active`);
  }
  return parts.join(' (') + (agent.active_sessions > 0 ? ')' : '');
}

function tooltipContent(agent: SandboxAgentInfo): string {
  const lines = [
    `Status: ${agent.status}`,
    `Replicas: ${agent.replicas}`,
    `Image: ${agent.image || 'unknown'}`,
  ];
  if (agent.created) {
    lines.push(`Created: ${new Date(agent.created).toLocaleString()}`);
  }
  return lines.join('\n');
}

export const SandboxAgentsPanel: React.FC<SandboxAgentsPanelProps> = ({
  namespace,
  selectedAgent,
  onSelectAgent,
}) => {
  const { data: agents, isLoading } = useQuery({
    queryKey: ['sandbox-agents', namespace],
    queryFn: () => sandboxService.listAgents(namespace),
    enabled: !!namespace,
    refetchInterval: 15000,
  });

  // Always show all agents — highlight the selected one
  const displayAgents = agents;

  return (
    <div
      style={{
        borderTop: '1px solid var(--pf-v5-global--BorderColor--100)',
        padding: 8,
      }}
    >
      <Title headingLevel="h4" size="md" style={{ marginBottom: 6 }}>
        Sandboxes
      </Title>

      {isLoading && <Spinner size="sm" />}

      {!isLoading && (!displayAgents || displayAgents.length === 0) && (
        <div
          style={{
            fontSize: '0.82em',
            color: 'var(--pf-v5-global--Color--200)',
            padding: '4px 0',
          }}
        >
          No sandbox agents
        </div>
      )}

      {!isLoading &&
        displayAgents?.map((agent) => {
          const isActive = agent.name === selectedAgent;
          return (
            <Tooltip
              key={agent.name}
              position="right"
              content={
                <span style={{ whiteSpace: 'pre-line' }}>
                  {tooltipContent(agent)}
                </span>
              }
              entryDelay={400}
            >
              <div
                role="button"
                tabIndex={0}
                onClick={() => onSelectAgent?.(agent.name)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') onSelectAgent?.(agent.name);
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '4px 6px',
                  marginBottom: 2,
                  borderRadius: 4,
                  cursor: onSelectAgent ? 'pointer' : 'default',
                  fontSize: '0.85em',
                  backgroundColor: isActive
                    ? 'var(--pf-v5-global--active-color--100)'
                    : 'transparent',
                  color: isActive
                    ? '#fff'
                    : 'var(--pf-v5-global--Color--100)',
                }}
              >
                {/* Status dot */}
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    backgroundColor: isActive ? '#fff' : statusDotColor(agent.status),
                    flexShrink: 0,
                  }}
                />

                {/* Name + session info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 500,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {agent.name}
                  </div>
                  <div
                    style={{
                      fontSize: '0.85em',
                      opacity: isActive ? 0.8 : 1,
                      color: isActive ? '#fff' : 'var(--pf-v5-global--Color--200)',
                    }}
                  >
                    {sessionText(agent)}
                  </div>
                </div>

                {/* Replicas label */}
                <Label
                  isCompact
                  color={agent.status === 'ready' ? 'green' : agent.status === 'error' ? 'red' : 'orange'}
                  style={{ fontSize: '0.75em', flexShrink: 0 }}
                >
                  {agent.replicas}
                </Label>
              </div>
            </Tooltip>
          );
        })}

    </div>
  );
};
