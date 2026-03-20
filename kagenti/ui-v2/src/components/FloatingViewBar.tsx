// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * FloatingViewBar — floating toggle for chat view modes.
 *
 * Renders a PatternFly ToggleGroup in the top-right of the chat area
 * with three modes: Simple, Advanced, Graph.
 */

import React from 'react';
import { ToggleGroup, ToggleGroupItem } from '@patternfly/react-core';

export type ViewMode = 'simple' | 'advanced' | 'graph';

const VALID_VIEW_MODES = new Set<string>(['simple', 'advanced', 'graph']);

export function isValidViewMode(val: string | null): val is ViewMode {
  return val != null && VALID_VIEW_MODES.has(val);
}

interface BudgetInfo {
  tokensUsed: number;
  tokensBudget: number;
  wallClockS: number;
  maxWallClockS: number;
}

interface FloatingViewBarProps {
  viewMode: ViewMode;
  onChange: (mode: ViewMode) => void;
  budget?: BudgetInfo | null;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatTime(s: number): string {
  if (s >= 3600) return `${(s / 3600).toFixed(1)}h`;
  if (s >= 60) return `${Math.floor(s / 60)}m${Math.floor(s % 60)}s`;
  return `${Math.floor(s)}s`;
}

function barColor(pct: number): string {
  if (pct > 90) return 'var(--pf-v5-global--danger-color--100)';
  if (pct > 70) return 'var(--pf-v5-global--warning-color--100)';
  return 'var(--pf-v5-global--success-color--100)';
}

export const FloatingViewBar: React.FC<FloatingViewBarProps> = React.memo(({ viewMode, onChange, budget }) => (
  <div
    data-testid="floating-view-bar"
    style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '6px 8px',
      gap: 12,
    }}
  >
    {/* Budget bars (left side) */}
    {budget && budget.tokensBudget > 0 && (
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 11, color: '#6a6e73' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span>Tokens</span>
          <div style={{ width: 60, height: 6, backgroundColor: '#333', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{
              width: `${Math.min(100, (budget.tokensUsed / budget.tokensBudget) * 100)}%`,
              height: '100%',
              backgroundColor: barColor((budget.tokensUsed / budget.tokensBudget) * 100),
              borderRadius: 3,
            }} />
          </div>
          <span>{formatTokens(budget.tokensUsed)}/{formatTokens(budget.tokensBudget)}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span>Time</span>
          <div style={{ width: 40, height: 6, backgroundColor: '#333', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{
              width: `${Math.min(100, (budget.wallClockS / budget.maxWallClockS) * 100)}%`,
              height: '100%',
              backgroundColor: barColor((budget.wallClockS / budget.maxWallClockS) * 100),
              borderRadius: 3,
            }} />
          </div>
          <span>{formatTime(budget.wallClockS)}/{formatTime(budget.maxWallClockS)}</span>
        </div>
      </div>
    )}

    <ToggleGroup aria-label="Chat view mode">
      <ToggleGroupItem
        text="Simple"
        buttonId="view-simple"
        isSelected={viewMode === 'simple'}
        onChange={() => onChange('simple')}
      />
      <ToggleGroupItem
        text="Advanced"
        buttonId="view-advanced"
        isSelected={viewMode === 'advanced'}
        onChange={() => onChange('advanced')}
      />
      <ToggleGroupItem
        text="Graph"
        buttonId="view-graph"
        isSelected={viewMode === 'graph'}
        onChange={() => onChange('graph')}
      />
    </ToggleGroup>
  </div>
));

export type { BudgetInfo };
