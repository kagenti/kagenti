// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * SessionStatsPanel — token usage, context window, timing, and tool call
 * statistics for an agent session.
 *
 * Data sourced from AgentLoop objects collected during SSE streaming.
 */

import React from 'react';
import { Card, CardBody, CardTitle, Progress } from '@patternfly/react-core';
import type { AgentLoop } from '../types/agentLoop';

interface Message {
  role: string;
  timestamp: Date;
  content: string;
}

interface SessionStatsPanelProps {
  agentLoops: Map<string, AgentLoop>;
  messages: Message[];
  modelContextLimit?: number;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(0);
  return `${m}m ${s}s`;
}

export const SessionStatsPanel: React.FC<SessionStatsPanelProps> = ({
  agentLoops,
  messages,
  modelContextLimit = 131072,
}) => {
  const loops = Array.from(agentLoops.values());

  // ── Token Usage ──
  const tokenRows = loops.flatMap((loop) =>
    loop.steps
      .filter((s) => s.tokens.prompt > 0 || s.tokens.completion > 0)
      .map((step, i) => ({
        turn: `${loop.id.slice(0, 6)}/${i + 1}`,
        prompt: step.tokens.prompt,
        completion: step.tokens.completion,
        total: step.tokens.prompt + step.tokens.completion,
      }))
  );
  const totalPrompt = tokenRows.reduce((s, r) => s + r.prompt, 0);
  const totalCompletion = tokenRows.reduce((s, r) => s + r.completion, 0);
  const totalTokens = totalPrompt + totalCompletion;

  // ── Context Window ──
  const contextPct = modelContextLimit > 0 ? (totalTokens / modelContextLimit) * 100 : 0;
  const contextVariant =
    contextPct > 80 ? 'danger' as const : contextPct > 50 ? 'warning' as const : undefined;

  // ── Timing ──
  const sessionStart = messages.length > 0 ? messages[0].timestamp : null;
  const sessionEnd = messages.length > 0 ? messages[messages.length - 1].timestamp : null;
  const sessionDurationS = sessionStart && sessionEnd
    ? (sessionEnd.getTime() - sessionStart.getTime()) / 1000
    : 0;

  // ── Tool Calls ──
  const toolMap = new Map<string, { calls: number; results: number }>();
  for (const loop of loops) {
    for (const step of loop.steps) {
      for (const tc of step.toolCalls) {
        const name = tc.name || tc.type || 'unknown';
        const entry = toolMap.get(name) || { calls: 0, results: 0 };
        entry.calls++;
        toolMap.set(name, entry);
      }
      for (const tr of step.toolResults) {
        const name = tr.name || tr.type || 'unknown';
        const entry = toolMap.get(name) || { calls: 0, results: 0 };
        entry.results++;
        toolMap.set(name, entry);
      }
    }
  }
  const toolRows = Array.from(toolMap.entries()).map(([name, stats]) => ({
    name,
    ...stats,
  }));

  const noData = loops.length === 0;

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

  return (
    <div data-testid="session-stats-panel" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {noData && (
        <Card>
          <CardBody>
            <p style={{ color: 'var(--pf-v5-global--Color--200)', textAlign: 'center' }}>
              No reasoning loop data yet. Send a message to the agent to see statistics.
            </p>
          </CardBody>
        </Card>
      )}

      {/* Token Usage */}
      <Card>
        <CardTitle>Token Usage</CardTitle>
        <CardBody>
          {tokenRows.length > 0 ? (
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Turn</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Prompt</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Completion</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Total</th>
                </tr>
              </thead>
              <tbody>
                {tokenRows.map((r, i) => (
                  <tr key={i}>
                    <td style={tdStyle}>{r.turn}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{r.prompt.toLocaleString()}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{r.completion.toLocaleString()}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{r.total.toLocaleString()}</td>
                  </tr>
                ))}
                <tr style={{ fontWeight: 600 }}>
                  <td style={tdStyle}>Total</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{totalPrompt.toLocaleString()}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{totalCompletion.toLocaleString()}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{totalTokens.toLocaleString()}</td>
                </tr>
              </tbody>
            </table>
          ) : (
            <p style={{ color: 'var(--pf-v5-global--Color--200)' }}>No token data available.</p>
          )}
        </CardBody>
      </Card>

      {/* Context Window */}
      <Card>
        <CardTitle>Context Window</CardTitle>
        <CardBody>
          <Progress
            value={Math.min(contextPct, 100)}
            title={`${totalTokens.toLocaleString()} / ${modelContextLimit.toLocaleString()} tokens (${contextPct.toFixed(1)}%)`}
            variant={contextVariant}
            measureLocation="outside"
          />
        </CardBody>
      </Card>

      {/* Timing */}
      <Card>
        <CardTitle>Timing</CardTitle>
        <CardBody>
          <table style={tableStyle}>
            <tbody>
              <tr>
                <td style={{ ...tdStyle, fontWeight: 600 }}>Session Duration</td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>
                  {sessionDurationS > 0 ? formatDuration(sessionDurationS) : '—'}
                </td>
              </tr>
              {loops.map((loop) => (
                <tr key={loop.id}>
                  <td style={tdStyle}>Loop {loop.id.slice(0, 6)}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {formatDuration(loop.budget.wallClockS)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardBody>
      </Card>

      {/* Tool Calls */}
      <Card>
        <CardTitle>Tool Calls</CardTitle>
        <CardBody>
          {toolRows.length > 0 ? (
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Tool</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Calls</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Results</th>
                </tr>
              </thead>
              <tbody>
                {toolRows.map((r) => (
                  <tr key={r.name}>
                    <td style={tdStyle}>{r.name}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{r.calls}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{r.results}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p style={{ color: 'var(--pf-v5-global--Color--200)' }}>No tool calls recorded.</p>
          )}
        </CardBody>
      </Card>
    </div>
  );
};
