// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * GraphLoopView — wrapper with subtab toggle between Step Graph, Topology,
 * and Event Flow views.
 *
 * All sub-views render multi-message data across all loops in the session.
 * The wrapper provides:
 *   - A compact toggle bar to switch between views
 *   - A multi-message sidebar with load-more pagination
 *   - selectedLoopId filtering passed to all graph views
 */

import React, { useMemo, useState } from 'react';
import { StepGraphView } from './StepGraphView';
import { TopologyGraphView } from './TopologyGraphView';
import { EventSubtypeGraphView } from './EventSubtypeGraphView';
import type { AgentLoop } from '../types/agentLoop';
import type { AgentGraphCard } from '../types/graphCard';

type GraphSubView = 'steps' | 'topology' | 'eventflow';
/** Node display mode:
 *  'nodes' = color-coded by role (planning, execution, evaluation, output)
 *  'events' = show event types each node emits (planner_output, tool_call, etc.) */
type EventDetail = 'nodes' | 'events';

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

// ---------------------------------------------------------------------------
// Message sidebar sub-component with load-more pagination
// ---------------------------------------------------------------------------

interface MessageSidebarProps {
  loops: AgentLoop[];
  selectedLoopId: string | null;
  setSelectedLoopId: (id: string | null) => void;
  visibleCount: number;
  setVisibleCount: React.Dispatch<React.SetStateAction<number>>;
}

function statusIcon(status: string): string {
  switch (status) {
    case 'done':     return '\u2713';
    case 'failed':   return '\u2717';
    case 'canceled': return '\u2718';
    default:         return '\u25b6';
  }
}

function statusColor(status: string): string {
  switch (status) {
    case 'done':     return '#4caf50';
    case 'failed':   return '#f44336';
    case 'canceled': return '#ff9800';
    default:         return '#58a6ff';
  }
}

const MessageSidebarPanel: React.FC<MessageSidebarProps> = React.memo(
  ({ loops, selectedLoopId, setSelectedLoopId, visibleCount, setVisibleCount }) => {
    const visibleLoops = loops.slice(-visibleCount);
    const hasMore = loops.length > visibleCount;
    const remaining = loops.length - visibleCount;

    return (
      <div
        data-testid="graph-message-sidebar"
        style={{
          width: 220,
          minWidth: 220,
          borderRight: '1px solid #333',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div style={{
          padding: '8px 10px',
          borderBottom: '1px solid #333',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#ccc' }}>
            Messages ({loops.length})
          </span>
          <button
            data-testid="graph-sidebar-show-all"
            onClick={() => setSelectedLoopId(null)}
            title="Show all messages"
            style={{
              background: selectedLoopId === null ? '#1a3a5c' : 'none',
              border: '1px solid #555',
              color: '#ccc',
              borderRadius: 3,
              padding: '2px 6px',
              fontSize: 10,
              cursor: 'pointer',
            }}
          >
            All
          </button>
        </div>

        {/* Message list with load-more */}
        <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
          {hasMore && (
            <button
              data-testid="graph-sidebar-load-more"
              onClick={() => setVisibleCount((c) => c + 5)}
              style={{
                display: 'block',
                width: '100%',
                padding: '6px 10px',
                fontSize: 11,
                color: '#58a6ff',
                background: 'rgba(88, 166, 255, 0.08)',
                border: 'none',
                borderBottom: '1px solid #333',
                cursor: 'pointer',
                textAlign: 'center',
              }}
            >
              Load 5 more ({remaining > 0 ? remaining : 0} remaining)
            </button>
          )}

          {visibleLoops.map((loop, idx) => {
            const globalIdx = loops.length - visibleCount + idx;
            const isSelected = loop.id === selectedLoopId;
            const userMsg = loop.userMessage || loop.id.substring(0, 8);

            return (
              <div
                key={loop.id}
                data-testid={`graph-msg-entry-${globalIdx >= 0 ? globalIdx : idx}`}
                onClick={() => setSelectedLoopId(isSelected ? null : loop.id)}
                style={{
                  padding: '8px 10px',
                  cursor: 'pointer',
                  backgroundColor: isSelected ? 'rgba(88, 166, 255, 0.1)' : 'transparent',
                  borderLeft: isSelected ? '3px solid #58a6ff' : '3px solid transparent',
                  transition: 'background-color 0.15s',
                }}
              >
                <div style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: '#ccc',
                  marginBottom: 4,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {(globalIdx >= 0 ? globalIdx : idx) + 1}. {userMsg.length > 35
                    ? userMsg.substring(0, 35) + '...'
                    : userMsg}
                </div>
                <div style={{ fontSize: 11, color: '#888', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ color: statusColor(loop.status) }}>{statusIcon(loop.status)}</span>
                  <span>{loop.steps.length} steps</span>
                  <span>{loop.status}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  },
);
MessageSidebarPanel.displayName = 'MessageSidebarPanel';

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const GraphLoopView: React.FC<GraphLoopViewProps> = React.memo(({ loop, allLoops, graphCard }) => {
  const [subView, setSubView] = useState<GraphSubView>('steps');
  const [eventDetail, setEventDetail] = useState<EventDetail>('nodes');
  const [selectedLoopId, setSelectedLoopId] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(5);

  // Stabilize loops array
  const loops = useMemo(() => allLoops || [loop], [allLoops, loop]);

  // Filter loops by selection for Step Graph and Topology views
  const filteredLoops = useMemo(
    () => selectedLoopId ? loops.filter((l) => l.id === selectedLoopId) : loops,
    [selectedLoopId, loops],
  );

  // The "primary" loop for backward-compatible props
  const primaryLoop = useMemo(
    () => (selectedLoopId ? filteredLoops[0] || loop : loop),
    [selectedLoopId, filteredLoops, loop],
  );

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

  // Whether to show the message sidebar (multiple messages available)
  const showSidebar = loops.length > 1;

  return (
    <div
      data-testid="graph-loop-view"
      style={{
        border: '1px solid var(--pf-v5-global--BorderColor--100, #d2d2d2)',
        borderRadius: 8,
        marginBottom: 4,
        overflow: 'hidden',
        backgroundColor: '#0d1117',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 400,
      }}
      // Fullscreen: fill entire viewport
      ref={(el) => {
        if (el) {
          const update = () => {
            el.style.height = document.fullscreenElement === el ? '100vh' : 'auto';
          };
          el.onfullscreenchange = update;
        }
      }}
    >
      {/* Subtab toggle bar + fullscreen */}
      <div style={{ ...TOGGLE_BAR_STYLE, justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 8 }}>
          {/* View toggle: Step Graph / Topology / Event Flow */}
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
              }}
            >
              Topology
            </button>
            <button
              data-testid="graph-toggle-eventflow"
              onClick={() => setSubView('eventflow')}
              style={{
                ...toggleBtnStyle(subView === 'eventflow'),
                borderLeft: 'none',
                borderTopRightRadius: 4,
                borderBottomRightRadius: 4,
              }}
            >
              Event Flow
            </button>
          </div>
          {/* Event detail toggle: Nodes / Events (only for Step Graph and Topology) */}
          {subView !== 'eventflow' && (
            <div style={{ display: 'flex', gap: 0 }}>
              <button
                data-testid="graph-toggle-types"
                onClick={() => setEventDetail('nodes')}
                style={{
                  ...toggleBtnStyle(eventDetail === 'nodes'),
                  borderTopLeftRadius: 4,
                  borderBottomLeftRadius: 4,
                  fontSize: 11,
                }}
              >
                Nodes
              </button>
              <button
                data-testid="graph-toggle-subtypes"
                onClick={() => setEventDetail('events')}
                style={{
                  ...toggleBtnStyle(eventDetail === 'events'),
                  borderLeft: 'none',
                  borderTopRightRadius: 4,
                  borderBottomRightRadius: 4,
                  fontSize: 11,
                }}
              >
                Events
              </button>
            </div>
          )}
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
          style={{
            padding: '4px 14px',
            fontSize: 11,
            fontWeight: 500,
            color: '#58a6ff',
            background: 'rgba(88, 166, 255, 0.08)',
            border: '1px solid #58a6ff',
            borderRadius: 4,
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
        >
          &#x26F6; Fullscreen
        </button>
      </div>

      {/* Main content: sidebar + graph view */}
      <div style={{ flex: 1, minHeight: 400, position: 'relative', display: 'flex' }}>
        {/* Message sidebar with load-more pagination */}
        {showSidebar && (
          <MessageSidebarPanel
            loops={loops}
            selectedLoopId={selectedLoopId}
            setSelectedLoopId={setSelectedLoopId}
            visibleCount={visibleCount}
            setVisibleCount={setVisibleCount}
          />
        )}

        {/* Active sub-view */}
        <div style={{ flex: 1, position: 'relative' }}>
          {subView === 'steps' && (
            <StepGraphView loop={primaryLoop} allLoops={filteredLoops} eventDetail={eventDetail} />
          )}
          {subView === 'topology' && (
            <TopologyGraphView loop={primaryLoop} allLoops={filteredLoops} graphCard={graphCard} eventDetail={eventDetail} />
          )}
          {subView === 'eventflow' && (
            <EventSubtypeGraphView allLoops={loops} selectedLoopId={selectedLoopId} />
          )}
        </div>
      </div>
    </div>
  );
});
GraphLoopView.displayName = 'GraphLoopView';
