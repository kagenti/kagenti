// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * SessionStatsPanel — session overview, timing, and tool call statistics.
 *
 * Data sourced from both the messages array (always available) and
 * AgentLoop objects (available when the reasoning loop SSE pipeline is active).
 */

import React from 'react';
import { Card, CardBody, CardTitle, Progress } from '@patternfly/react-core';
import type { AgentLoop } from '../types/agentLoop';

interface Message {
  role: string;
  timestamp: Date;
  content: string;
  toolData?: { type: string; name?: string; tools?: Array<{ name: string }> };
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

  // ── Message Stats (always available) ──
  const userMsgCount = messages.filter((m) => m.role === 'user').length;
  // Count assistant responses from both flat messages AND agent loops
  // (loop mode skips adding to messages array — content is in agentLoops)
  const flatAssistantCount = messages.filter(
    (m) => m.role === 'assistant' && m.content?.trim() && !m.toolData
  ).length;
  // Count loops that completed (status 'done') as assistant responses,
  // even if finalAnswer was filtered/empty (e.g. leaked decision token).
  const loopAnswerCount = loops.filter(
    (l) => l.status === 'done' || l.finalAnswer?.trim()
  ).length;
  const assistantMsgCount = flatAssistantCount + loopAnswerCount;

  // ── Tool calls from messages (fallback when no loop data) ──
  const msgToolMap = new Map<string, { calls: number; results: number }>();
  for (const msg of messages) {
    if (!msg.toolData) continue;
    if (msg.toolData.type === 'tool_call') {
      const names = msg.toolData.tools?.map((t) => t.name) || [msg.toolData.name || 'unknown'];
      for (const name of names) {
        const entry = msgToolMap.get(name) || { calls: 0, results: 0 };
        entry.calls++;
        msgToolMap.set(name, entry);
      }
    } else if (msg.toolData.type === 'tool_result') {
      const name = msg.toolData.name || 'unknown';
      const entry = msgToolMap.get(name) || { calls: 0, results: 0 };
      entry.results++;
      msgToolMap.set(name, entry);
    }
  }

  // ── Token Usage (from loops only) ──
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
    contextPct > 80 ? ('danger' as const) : contextPct > 50 ? ('warning' as const) : undefined;

  // ── Timing ──
  const sessionStart = messages.length > 0 ? messages[0].timestamp : null;
  const sessionEnd = messages.length > 0 ? messages[messages.length - 1].timestamp : null;
  const sessionDurationS =
    sessionStart && sessionEnd
      ? (sessionEnd.getTime() - sessionStart.getTime()) / 1000
      : 0;

  // ── Tool Calls (prefer loop data, fall back to message data) ──
  const loopToolMap = new Map<string, { calls: number; results: number }>();
  for (const loop of loops) {
    for (const step of loop.steps) {
      for (const tc of step.toolCalls) {
        const name = tc.name || tc.type || 'unknown';
        const entry = loopToolMap.get(name) || { calls: 0, results: 0 };
        entry.calls++;
        loopToolMap.set(name, entry);
      }
      for (const tr of step.toolResults) {
        const name = tr.name || tr.type || 'unknown';
        const entry = loopToolMap.get(name) || { calls: 0, results: 0 };
        entry.results++;
        loopToolMap.set(name, entry);
      }
    }
  }
  const toolSource = loopToolMap.size > 0 ? loopToolMap : msgToolMap;
  const toolRows = Array.from(toolSource.entries()).map(([name, stats]) => ({
    name,
    ...stats,
  }));

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
    <div
      data-testid="session-stats-panel"
      style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}
    >
      {/* Session Overview — always shows something */}
      <Card>
        <CardTitle>Session Overview</CardTitle>
        <CardBody>
          <table style={tableStyle}>
            <tbody>
              <tr>
                <td style={{ ...tdStyle, fontWeight: 600 }}>Messages</td>
                <td style={{ ...tdStyle, textAlign: 'right' }} data-testid="stats-messages">
                  <span data-testid="stats-user-msg-count">{userMsgCount}</span> user / <span data-testid="stats-assistant-msg-count">{assistantMsgCount}</span> assistant
                </td>
              </tr>
              <tr>
                <td style={{ ...tdStyle, fontWeight: 600 }}>Tool Calls</td>
                <td style={{ ...tdStyle, textAlign: 'right' }} data-testid="stats-tool-calls">
                  {toolRows.reduce((s, r) => s + r.calls, 0)}
                </td>
              </tr>
              <tr>
                <td style={{ ...tdStyle, fontWeight: 600 }}>Session Duration</td>
                <td style={{ ...tdStyle, textAlign: 'right' }}>
                  {sessionDurationS > 0 ? formatDuration(sessionDurationS) : '—'}
                </td>
              </tr>
              {loops.length > 0 && (
                <tr>
                  <td style={{ ...tdStyle, fontWeight: 600 }}>Reasoning Loops</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }} data-testid="stats-loop-count">{loops.length}</td>
                </tr>
              )}
            </tbody>
          </table>
        </CardBody>
      </Card>

      {/* Token Usage — only when loop data available */}
      {tokenRows.length > 0 && (
        <Card>
          <CardTitle>Token Usage</CardTitle>
          <CardBody>
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
                    <td style={{ ...tdStyle, textAlign: 'right' }}>
                      {r.completion.toLocaleString()}
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{r.total.toLocaleString()}</td>
                  </tr>
                ))}
                <tr style={{ fontWeight: 600 }} data-testid="stats-token-totals">
                  <td style={tdStyle}>Total</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }} data-testid="stats-total-prompt">
                    {totalPrompt.toLocaleString()}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }} data-testid="stats-total-completion">
                    {totalCompletion.toLocaleString()}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }} data-testid="stats-total-tokens">
                    {totalTokens.toLocaleString()}
                  </td>
                </tr>
              </tbody>
            </table>
          </CardBody>
        </Card>
      )}

      {/* Context Window — only when token data available */}
      {totalTokens > 0 && (
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
      )}

      {/* Tool Calls — from loops or messages */}
      {toolRows.length > 0 && (
        <Card>
          <CardTitle>Tool Calls</CardTitle>
          <CardBody>
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
          </CardBody>
        </Card>
      )}

      {/* Timing per loop — only when loop data available */}
      {loops.length > 0 && (
        <Card>
          <CardTitle>Loop Timing</CardTitle>
          <CardBody>
            <table style={tableStyle}>
              <tbody>
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
      )}
    </div>
  );
};
