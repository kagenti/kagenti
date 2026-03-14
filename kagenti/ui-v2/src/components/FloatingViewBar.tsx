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

interface FloatingViewBarProps {
  viewMode: ViewMode;
  onChange: (mode: ViewMode) => void;
}

export const FloatingViewBar: React.FC<FloatingViewBarProps> = React.memo(({ viewMode, onChange }) => (
  <div
    data-testid="floating-view-bar"
    style={{
      display: 'flex',
      justifyContent: 'flex-end',
      padding: '6px 8px',
    }}
  >
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
