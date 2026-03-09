// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * LoopSummaryBar — single-row summary for an AgentLoopCard.
 *
 * Layout:
 *   StatusIcon  toolCount · tokenCount · status    ModelBadge    duration    [toggle]
 */

import React from 'react';
import { Spinner } from '@patternfly/react-core';
import { CheckCircleIcon, TimesCircleIcon } from '@patternfly/react-icons';
import type { AgentLoop } from '../types/agentLoop';
import { ModelBadge } from './ModelBadge';

interface LoopSummaryBarProps {
  loop: AgentLoop;
  expanded: boolean;
  onToggle: () => void;
}

/** Count all tool calls across every step. */
function countTools(loop: AgentLoop): number {
  return loop.steps.reduce((sum, s) => sum + s.toolCalls.length, 0);
}

/** Sum all tokens across every step and format as "1.2k" or raw number. */
function formatTokens(loop: AgentLoop): string {
  // Prefer budget.tokensUsed, fall back to summing step tokens
  let total = loop.budget.tokensUsed;
  if (!total) {
    total = loop.steps.reduce((sum, s) => sum + s.tokens.prompt + s.tokens.completion, 0);
  }
  if (total >= 1000) return (total / 1000).toFixed(1) + 'k';
  return String(total);
}

/** Format seconds for display (e.g. "12.3s"). */
function formatDuration(seconds: number): string {
  if (seconds < 0.1) return '<0.1s';
  return seconds.toFixed(1) + 's';
}

/** Status icon: spinner for executing, checkmark for done, X for failed. */
const StatusIcon: React.FC<{ status: AgentLoop['status'] }> = ({ status }) => {
  if (status === 'executing' || status === 'planning' || status === 'reflecting') {
    return <Spinner size="sm" aria-label="executing" style={{ marginRight: 6 }} />;
  }
  if (status === 'done') {
    return (
      <CheckCircleIcon
        style={{ color: 'var(--pf-v5-global--success-color--100)', marginRight: 6 }}
      />
    );
  }
  if (status === 'failed') {
    return (
      <TimesCircleIcon
        style={{ color: 'var(--pf-v5-global--danger-color--100)', marginRight: 6 }}
      />
    );
  }
  return null;
};

/** Status text with color. */
function statusLabel(status: AgentLoop['status']): { text: string; color: string } {
  switch (status) {
    case 'planning':   return { text: 'planning',   color: '#6a6e73' };
    case 'executing':  return { text: 'executing',  color: 'var(--pf-v5-global--info-color--100)' };
    case 'reflecting': return { text: 'reflecting', color: '#d97706' };
    case 'done':       return { text: 'done',       color: 'var(--pf-v5-global--success-color--100)' };
    case 'failed':     return { text: 'failed',     color: 'var(--pf-v5-global--danger-color--100)' };
  }
}

export const LoopSummaryBar: React.FC<LoopSummaryBarProps> = ({ loop, expanded, onToggle }) => {
  const tools = countTools(loop);
  const tokens = formatTokens(loop);
  const duration = formatDuration(loop.budget.wallClockS);
  const sl = statusLabel(loop.status);
  const totalTokens = loop.steps.reduce(
    (sum, s) => sum + s.tokens.prompt + s.tokens.completion,
    0,
  );

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        fontSize: '0.85em',
        cursor: 'pointer',
        userSelect: 'none',
      }}
      onClick={onToggle}
    >
      {/* Left: status icon + metrics + status label */}
      <div style={{ display: 'flex', alignItems: 'center', flex: 1, gap: 6 }}>
        <StatusIcon status={loop.status} />
        <span style={{ color: '#6a6e73' }}>
          {tools} tool{tools !== 1 ? 's' : ''}
          {' \u00b7 '}
          {tokens} tokens
          {' \u00b7 '}
        </span>
        <span style={{ color: sl.color, fontWeight: 500 }}>{sl.text}</span>
      </div>

      {/* Right: model badge + duration + toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <ModelBadge model={loop.model} />
        {totalTokens > 0 && (
          <span style={{ color: '#6a6e73', fontSize: '0.9em', fontVariantNumeric: 'tabular-nums' }}>
            {totalTokens.toLocaleString()} tokens
          </span>
        )}
        <span style={{ color: '#6a6e73', fontVariantNumeric: 'tabular-nums' }}>
          {duration}
        </span>
        <span
          style={{
            padding: '2px 8px',
            borderRadius: 4,
            border: '1px solid var(--pf-v5-global--BorderColor--100)',
            fontSize: '0.9em',
            fontWeight: 500,
            color: 'var(--pf-v5-global--Color--200)',
          }}
        >
          {expanded ? '\u25bc' : '\u25b6'} Details
        </span>
      </div>
    </div>
  );
};
