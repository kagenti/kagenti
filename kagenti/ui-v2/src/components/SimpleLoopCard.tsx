// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * SimpleLoopCard — clean, end-user-friendly view of an AgentLoop.
 *
 * Shows: final answer (markdown) + collapsible summary bar.
 * Expanding the summary reveals a plan checklist with step status icons.
 */

import React, { useState, useMemo } from 'react';
import { Spinner } from '@patternfly/react-core';
import { CheckCircleIcon, TimesCircleIcon, RobotIcon } from '@patternfly/react-icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { AgentLoop } from '../types/agentLoop';
import { countTools, sumAllTokens, formatDuration, filterFinalAnswer } from '../utils/loopFormatting';

function stepIcon(loop: AgentLoop, stepIdx: number): React.ReactNode {
  const isDone = loop.status === 'done' || stepIdx < loop.currentStep;
  const isCurrent = stepIdx === loop.currentStep && loop.status !== 'done';
  const isFailed = loop.status === 'failed' && stepIdx === loop.currentStep;

  if (isFailed) return <TimesCircleIcon style={{ color: 'var(--pf-v5-global--danger-color--100)', marginRight: 4, fontSize: '0.9em' }} />;
  if (isDone) return <CheckCircleIcon style={{ color: 'var(--pf-v5-global--success-color--100)', marginRight: 4, fontSize: '0.9em' }} />;
  if (isCurrent) return <Spinner size="sm" aria-label="running" style={{ marginRight: 4 }} />;
  return <span style={{ marginRight: 4, color: '#6a6e73' }}>-</span>;
}

interface SimpleLoopCardProps {
  loop: AgentLoop;
}

export const SimpleLoopCard: React.FC<SimpleLoopCardProps> = React.memo(({ loop }) => {
  const [expanded, setExpanded] = useState(false);
  const tools = useMemo(() => countTools(loop), [loop]);
  const tokens = useMemo(() => loop.budget.tokensUsed || sumAllTokens(loop), [loop]);
  const duration = formatDuration(loop.budget.wallClockS);
  const isActive = loop.status === 'executing' || loop.status === 'planning' || loop.status === 'reflecting';

  const filteredAnswer = useMemo(() => {
    if (!loop.finalAnswer) return null;
    const text = filterFinalAnswer(loop.finalAnswer);
    return text || null;
  }, [loop.finalAnswer]);

  return (
    <div
      data-testid="simple-loop-card"
      style={{
        display: 'flex',
        gap: 10,
        padding: '10px 14px',
        marginBottom: 4,
        borderRadius: 8,
        border: `1px solid ${loop.status === 'done' ? 'var(--pf-v5-global--success-color--100)' : loop.status === 'failed' ? 'var(--pf-v5-global--danger-color--100)' : 'var(--pf-v5-global--BorderColor--100)'}`,
        backgroundColor: 'var(--pf-v5-global--BackgroundColor--100)',
      }}
    >
      {/* Avatar */}
      <div
        style={{
          flexShrink: 0, width: 32, height: 32, borderRadius: '50%',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          backgroundColor: 'var(--pf-v5-global--success-color--100)', color: '#fff', fontSize: 14,
        }}
      >
        <RobotIcon />
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Failure banner */}
        {loop.status === 'failed' && !loop.finalAnswer && (
          <div style={{
            fontSize: '0.88em', marginBottom: 8, padding: '8px 12px',
            backgroundColor: 'var(--pf-v5-global--danger-color--100, #c9190b)',
            color: '#fff', borderRadius: 4,
          }}>
            <strong>Failed</strong>
            {loop.failureReason && <span> — {loop.failureReason}</span>}
          </div>
        )}

        {/* Final answer */}
        {filteredAnswer && (
          <div className="sandbox-markdown" style={{ fontSize: '0.92em', marginBottom: 8 }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{filteredAnswer}</ReactMarkdown>
          </div>
        )}

        {/* In-progress indicator */}
        {isActive && !loop.finalAnswer && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: '0.88em', color: 'var(--pf-v5-global--Color--200)' }}>
            <Spinner size="sm" aria-label="working" />
            Agent is {loop.status}...
          </div>
        )}

        {/* Summary bar */}
        <div
          data-testid="simple-summary-bar"
          onClick={() => setExpanded(!expanded)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '6px 10px',
            borderRadius: 4,
            backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
            fontSize: '0.82em',
            color: 'var(--pf-v5-global--Color--200)',
            cursor: 'pointer',
            userSelect: 'none',
          }}
        >
          <span style={{ fontSize: '0.9em', width: 14, textAlign: 'center' }}>
            {expanded ? '[-]' : '[+]'}
          </span>
          {isActive && <Spinner size="sm" aria-label="running" />}
          {loop.status === 'done' && <CheckCircleIcon style={{ color: 'var(--pf-v5-global--success-color--100)', fontSize: '0.9em' }} />}
          {loop.status === 'failed' && <TimesCircleIcon style={{ color: 'var(--pf-v5-global--danger-color--100)', fontSize: '0.9em' }} />}
          <span>
            {loop.plan.length} step{loop.plan.length !== 1 ? 's' : ''}
            {' | '}
            {tools} tool call{tools !== 1 ? 's' : ''}
            {' | '}
            {duration}
            {tokens > 0 && <>{' | '}{tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : tokens} tokens</>}
          </span>
        </div>

        {/* Expanded: plan checklist */}
        {expanded && loop.plan.length > 0 && (
          <ol style={{
            margin: '6px 0 0',
            paddingLeft: 22,
            fontSize: '0.82em',
            lineHeight: 1.8,
            listStyleType: 'none',
          }}>
            {loop.plan.map((step, i) => {
              const isDone = loop.status === 'done' || i < loop.currentStep;
              const isCurrent = i === loop.currentStep && loop.status !== 'done';
              return (
                <li key={i} style={{
                  display: 'flex',
                  alignItems: 'center',
                  color: isDone ? 'var(--pf-v5-global--success-color--100)' : isCurrent ? 'var(--pf-v5-global--info-color--100)' : 'var(--pf-v5-global--Color--200)',
                  fontWeight: isCurrent ? 600 : 400,
                }}>
                  {stepIcon(loop, i)}
                  <span>{i + 1}. {step}</span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
});
