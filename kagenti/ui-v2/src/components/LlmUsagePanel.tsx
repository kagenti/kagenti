// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * LlmUsagePanel - Per-model LLM token usage and cost breakdown.
 *
 * Fetches data from the backend token-usage endpoint which proxies
 * LiteLLM spend logs. Displays a table with per-model breakdown
 * and a totals row.
 */

import React, { useEffect, useState } from 'react';
import {
  Card,
  CardBody,
  CardTitle,
  Skeleton,
  EmptyState,
  EmptyStateBody,
} from '@patternfly/react-core';
import { tokenUsageService, type SessionTokenUsage } from '../services/api';

interface LlmUsagePanelProps {
  contextId: string;
  isVisible: boolean;
}

export const LlmUsagePanel: React.FC<LlmUsagePanelProps> = ({
  contextId,
  isVisible,
}) => {
  const [usage, setUsage] = useState<SessionTokenUsage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isVisible || !contextId) return;

    let cancelled = false;
    setUsage(null); // Clear stale data immediately to prevent blip
    setLoading(true);
    setError(null);

    tokenUsageService
      .getSessionTokenUsage(contextId)
      .then((data) => {
        if (!cancelled) setUsage(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || 'Failed to fetch LLM usage');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [contextId, isVisible]);

  const tableStyle: React.CSSProperties = {
    width: '100%',
    fontSize: '0.85em',
    borderCollapse: 'collapse',
  };
  const thStyle: React.CSSProperties = {
    textAlign: 'left',
    padding: '6px 10px',
    borderBottom: '2px solid var(--pf-v5-global--BorderColor--100)',
    fontWeight: 600,
  };
  const tdStyle: React.CSSProperties = {
    padding: '5px 10px',
    borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
    fontVariantNumeric: 'tabular-nums',
  };
  const rightAlign: React.CSSProperties = { ...tdStyle, textAlign: 'right' };

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <Card>
          <CardTitle>LLM Usage</CardTitle>
          <CardBody>
            <Skeleton width="100%" height="24px" style={{ marginBottom: 8 }} />
            <Skeleton width="100%" height="24px" style={{ marginBottom: 8 }} />
            <Skeleton width="80%" height="24px" />
          </CardBody>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 16 }}>
        <Card>
          <CardTitle>LLM Usage</CardTitle>
          <CardBody>
            <EmptyState>
              <EmptyStateBody>
                Failed to load LLM usage data: {error}
              </EmptyStateBody>
            </EmptyState>
          </CardBody>
        </Card>
      </div>
    );
  }

  if (!usage || usage.models.length === 0) {
    return (
      <div style={{ padding: 16 }}>
        <Card>
          <CardTitle>LLM Usage</CardTitle>
          <CardBody>
            <EmptyState>
              <EmptyStateBody>No LLM usage data</EmptyStateBody>
            </EmptyState>
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div
      data-testid="llm-usage-panel"
      style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}
    >
      <Card>
        <CardTitle>LLM Usage</CardTitle>
        <CardBody>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Model</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Prompt Tokens</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Completion Tokens</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Total Tokens</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Calls</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {usage.models.map((m) => (
                <tr key={m.model}>
                  <td style={tdStyle}>{m.model}</td>
                  <td style={rightAlign}>{m.prompt_tokens.toLocaleString()}</td>
                  <td style={rightAlign}>{m.completion_tokens.toLocaleString()}</td>
                  <td style={rightAlign}>{m.total_tokens.toLocaleString()}</td>
                  <td style={rightAlign}>{m.num_calls.toLocaleString()}</td>
                  <td style={rightAlign}>${m.cost.toFixed(4)}</td>
                </tr>
              ))}
              <tr style={{ fontWeight: 600 }}>
                <td style={tdStyle}>Total</td>
                <td style={rightAlign}>
                  {usage.total_prompt_tokens.toLocaleString()}
                </td>
                <td style={rightAlign}>
                  {usage.total_completion_tokens.toLocaleString()}
                </td>
                <td style={rightAlign}>
                  {usage.total_tokens.toLocaleString()}
                </td>
                <td style={rightAlign}>
                  {usage.total_calls.toLocaleString()}
                </td>
                <td style={rightAlign}>
                  ${usage.total_cost.toFixed(4)}
                </td>
              </tr>
            </tbody>
          </table>
        </CardBody>
      </Card>
    </div>
  );
};
