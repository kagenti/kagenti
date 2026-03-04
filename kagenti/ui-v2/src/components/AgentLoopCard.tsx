// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * AgentLoopCard — expandable card for agent reasoning loops.
 *
 * Replaces flat message rendering when SSE events carry a `loop_id` field.
 *
 * Layout:
 * - Collapsed: LoopSummaryBar + final answer (always visible)
 * - Expanded:  LoopSummaryBar + LoopDetail + final answer
 * - Streaming: auto-expanded to show live progress
 */

import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { AgentLoop } from '../types/agentLoop';
import { LoopSummaryBar } from './LoopSummaryBar';
import { LoopDetail } from './LoopDetail';

interface AgentLoopCardProps {
  loop: AgentLoop;
  isStreaming?: boolean;
}

/** Map loop status to a border color. */
function borderColor(status: AgentLoop['status']): string {
  switch (status) {
    case 'executing':  return 'var(--pf-v5-global--info-color--100)';
    case 'done':       return 'var(--pf-v5-global--success-color--100)';
    case 'failed':     return 'var(--pf-v5-global--danger-color--100)';
    case 'planning':   return '#6a6e73';
    case 'reflecting': return '#d97706';
  }
}

export const AgentLoopCard: React.FC<AgentLoopCardProps> = ({ loop, isStreaming = false }) => {
  const [expanded, setExpanded] = useState(false);

  // Auto-expand during streaming so the user sees live progress
  useEffect(() => {
    if (isStreaming) {
      setExpanded(true);
    }
  }, [isStreaming]);

  return (
    <div
      className="agent-loop-card"
      style={{
        border: `1px solid ${borderColor(loop.status)}`,
        borderRadius: 8,
        marginBottom: 8,
        padding: '10px 14px',
      }}
    >
      <LoopSummaryBar
        loop={loop}
        expanded={expanded}
        onToggle={() => setExpanded((prev) => !prev)}
      />

      {expanded && <LoopDetail loop={loop} />}

      {loop.finalAnswer && (
        <div
          className="sandbox-markdown"
          style={{ fontSize: '0.92em', marginTop: 10 }}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {loop.finalAnswer}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
};
