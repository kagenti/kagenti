// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * AgentLoopCard — collapsed agent turn card for reasoning loops.
 *
 * Each agent response is ONE card:
 * - Final answer (markdown) always visible at top
 * - "Show reasoning" toggle expands LoopSummaryBar + LoopDetail
 * - During streaming: expanded (live progress). After completion: collapsed.
 * - On history reload: all collapsed.
 */

import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { RobotIcon } from '@patternfly/react-icons';
import type { AgentLoop } from '../types/agentLoop';
import { LoopSummaryBar } from './LoopSummaryBar';
import { LoopDetail } from './LoopDetail';

/** Check if the loop failed due to recursion limit (not a real error). */
function isRecursionLimitHit(loop: AgentLoop): boolean {
  if (loop.status !== 'failed') return false;
  const reason = (loop.failureReason || '').toLowerCase();
  return reason.includes('recursion') || reason.includes('recursion_limit');
}

interface AgentLoopCardProps {
  loop: AgentLoop;
  isStreaming?: boolean;
  namespace?: string;
  agentName?: string;
  markdownComponents?: Record<string, React.ComponentType<unknown>>;
}

/** Map loop status to a border color. */
function borderColor(status: AgentLoop['status']): string {
  switch (status) {
    case 'executing':  return 'var(--pf-v5-global--info-color--100)';
    case 'done':       return 'var(--pf-v5-global--success-color--100)';
    case 'failed':     return 'var(--pf-v5-global--danger-color--100)';
    case 'canceled':   return '#d97706';
    case 'planning':   return '#6a6e73';
    case 'reflecting': return '#d97706';
  }
}

export const AgentLoopCard: React.FC<AgentLoopCardProps> = ({ loop, isStreaming = false }) => {
  const [expanded, setExpanded] = useState(false);
  const wasStreaming = useRef(false);

  // Auto-expand during streaming, auto-collapse only when loop completes with an answer
  useEffect(() => {
    if (isStreaming) {
      setExpanded(true);
      wasStreaming.current = true;
    } else if (wasStreaming.current) {
      // Streaming stopped — only collapse if loop has a final answer (success).
      // Keep expanded for failed/executing loops so the user can see what happened.
      if (loop.status === 'done' && loop.finalAnswer) {
        setExpanded(false);
      }
      wasStreaming.current = false;
    }
  }, [isStreaming]);

  return (
    <div
      className="agent-loop-card"
      data-testid="agent-loop-card"
      style={{
        display: 'flex',
        gap: 10,
        padding: '10px 14px',
        marginBottom: 4,
        borderRadius: 8,
        border: `1px solid ${isRecursionLimitHit(loop) ? '#d97706' : borderColor(loop.status)}`,
        backgroundColor: 'var(--pf-v5-global--BackgroundColor--100)',
      }}
    >
      {/* Avatar */}
      <div
        style={{
          flexShrink: 0,
          width: 32,
          height: 32,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'var(--pf-v5-global--success-color--100)',
          color: '#fff',
          fontSize: 14,
        }}
      >
        <RobotIcon />
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* User message that triggered this loop */}
        {loop.userMessage && (
          <div style={{
            fontSize: '0.88em', marginBottom: 8, padding: '6px 10px',
            backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
            borderRadius: 4, color: 'var(--pf-v5-global--Color--100)',
          }}>
            <strong style={{ marginRight: 6 }}>User:</strong>
            {loop.userMessage}
          </div>
        )}
        {/* Failure reason — show prominently when loop failed */}
        {loop.status === 'failed' && !loop.finalAnswer && (
          isRecursionLimitHit(loop) ? (
            <div style={{
              fontSize: '0.88em', marginBottom: 8, padding: '8px 12px',
              backgroundColor: '#d97706',
              color: '#fff', borderRadius: 4,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <span>
                <strong>Recursion limit reached</strong>
                {loop.failureReason && <span> — {loop.failureReason}</span>}
              </span>
            </div>
          ) : (
            <div style={{
              fontSize: '0.88em', marginBottom: 8, padding: '8px 12px',
              backgroundColor: 'var(--pf-v5-global--danger-color--100, #c9190b)',
              color: '#fff', borderRadius: 4,
            }}>
              <strong>Failed</strong>
              {loop.failureReason && <span> — {loop.failureReason}</span>}
              {!loop.failureReason && loop.steps.length > 0 && (() => {
                const lastStep = [...loop.steps].reverse().find(s =>
                  s.eventType === 'reflector_decision' || s.nodeType === 'reflector'
                );
                const reason = lastStep?.reasoning || lastStep?.description;
                return reason ? <span> — {reason.substring(0, 300)}</span> : null;
              })()}
            </div>
          )
        )}

        {/* Final answer — always visible */}
        {loop.finalAnswer && (() => {
          const filtered = loop.finalAnswer
            .split('\n')
            .filter((line) => !(line.includes('Step completed') && line.includes('all requested tool calls')))
            .join('\n')
            .trim();
          return filtered ? (
            <div className="sandbox-markdown" style={{ fontSize: '0.92em', marginBottom: 8 }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {filtered}
              </ReactMarkdown>
            </div>
          ) : null;
        })()}

        {/* Reasoning toggle */}
        <div
          onClick={() => setExpanded((prev) => !prev)}
          data-testid="reasoning-toggle"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '2px 8px',
            borderRadius: 4,
            border: '1px solid var(--pf-v5-global--BorderColor--100)',
            fontSize: '0.8em',
            fontWeight: 500,
            color: 'var(--pf-v5-global--Color--200)',
            cursor: 'pointer',
            userSelect: 'none',
            marginBottom: expanded ? 8 : 0,
          }}
        >
          {expanded ? '\u25bc' : '\u25b6'} {loop.totalSteps || loop.plan.length || loop.steps.length} step{(loop.totalSteps || loop.plan.length || loop.steps.length) !== 1 ? 's' : ''}{loop.nodeVisits > 0 ? ` · [${loop.nodeVisits}]` : ''}
        </div>

        {/* Expanded reasoning details */}
        {expanded && (
          <div style={{ marginTop: 4 }}>
            <LoopSummaryBar
              loop={loop}
              expanded={expanded}
              onToggle={() => setExpanded((prev) => !prev)}
            />
            <LoopDetail loop={loop} />
          </div>
        )}
      </div>
    </div>
  );
};
