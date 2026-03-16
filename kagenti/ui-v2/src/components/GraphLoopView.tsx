// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * GraphLoopView — wrapper with subtab toggle between Step Graph and Topology views.
 *
 * Both sub-views render multi-message data across all loops in the session.
 * The wrapper provides a compact toggle bar to switch between views.
 */

import React, { useMemo, useState } from 'react';
import { StepGraphView } from './StepGraphView';
import { TopologyGraphView } from './TopologyGraphView';
import type { AgentLoop } from '../types/agentLoop';
import type { AgentGraphCard } from '../types/graphCard';

type GraphSubView = 'steps' | 'topology';

export interface GraphLoopViewProps {
  /** Primary loop (backward-compatible). */
  loop: AgentLoop;
  /** All loops in the session for multi-message mode. */
  allLoops?: AgentLoop[];
  /** Optional graph card for topology view. */
  graphCard?: AgentGraphCard;
}

const TOGGLE_BAR_STYLE: React.CSSProperties = {
  display: 'flex',
  gap: 0,
  padding: '6px 12px',
  borderBottom: '1px solid var(--pf-v5-global--BorderColor--100, #d2d2d2)',
  backgroundColor: '#0d1117',
};

function toggleBtnStyle(active: boolean): React.CSSProperties {
  return {
    padding: '4px 14px',
    fontSize: 12,
    fontWeight: active ? 600 : 400,
    color: active ? '#58a6ff' : '#888',
    background: active ? 'rgba(88, 166, 255, 0.1)' : 'transparent',
    border: `1px solid ${active ? '#58a6ff' : '#444'}`,
    borderRadius: 0,
    cursor: 'pointer',
    transition: 'all 0.15s',
  };
}

export const GraphLoopView: React.FC<GraphLoopViewProps> = React.memo(({ loop, allLoops, graphCard }) => {
  const [subView, setSubView] = useState<GraphSubView>('steps');

  // Stabilize loops array
  const loops = useMemo(() => allLoops || [loop], [allLoops, loop]);

  // Show "waiting" when all loops are empty
  const allEmpty = useMemo(() => loops.every((l) => l.steps.length === 0), [loops]);
  if (allEmpty) {
    return (
      <div
        data-testid="graph-loop-empty"
        style={{
          padding: 20,
          textAlign: 'center',
          color: 'var(--pf-v5-global--Color--200)',
          fontSize: '0.88em',
        }}
      >
        Waiting for agent events...
      </div>
    );
  }

  return (
    <div
      data-testid="graph-loop-view"
      style={{
        border: '1px solid var(--pf-v5-global--BorderColor--100, #d2d2d2)',
        borderRadius: 8,
        marginBottom: 4,
        overflow: 'hidden',
        backgroundColor: '#0d1117',
      }}
    >
      {/* Subtab toggle bar + fullscreen */}
      <div style={{ ...TOGGLE_BAR_STYLE, justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 0 }}>
          <button
            data-testid="graph-toggle-steps"
            onClick={() => setSubView('steps')}
            style={{
              ...toggleBtnStyle(subView === 'steps'),
              borderTopLeftRadius: 4,
              borderBottomLeftRadius: 4,
            }}
          >
            Step Graph
          </button>
          <button
            data-testid="graph-toggle-topology"
            onClick={() => setSubView('topology')}
            style={{
              ...toggleBtnStyle(subView === 'topology'),
              borderLeft: 'none',
              borderTopRightRadius: 4,
              borderBottomRightRadius: 4,
            }}
          >
            Topology
          </button>
        </div>
        <button
          data-testid="graph-fullscreen-toggle"
          onClick={() => {
            const el = document.querySelector('[data-testid="graph-loop-view"]');
            if (el) {
              if (document.fullscreenElement) document.exitFullscreen();
              else el.requestFullscreen();
            }
          }}
          style={{ ...toggleBtnStyle(false), borderRadius: 4, fontSize: 11 }}
        >
          &#x26F6; Fullscreen
        </button>
      </div>

      {/* Active sub-view */}
      {subView === 'steps' && (
        <StepGraphView loop={loop} allLoops={loops} />
      )}
      {subView === 'topology' && (
        <TopologyGraphView loop={loop} allLoops={loops} graphCard={graphCard} />
      )}
    </div>
  );
});
GraphLoopView.displayName = 'GraphLoopView';
