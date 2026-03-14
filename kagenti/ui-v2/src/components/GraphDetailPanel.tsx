// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * GraphDetailPanel — sliding detail panel for graph node drill-down.
 *
 * Supports:
 * - Breadcrumb navigation (click any crumb to go back)
 * - Left/right arrow navigation between sibling nodes
 * - Nested drill-down: step → tool → result, step → thinking iteration
 * - Keyboard: ArrowLeft/Right for siblings, Escape to close
 */

import React, { useState, useEffect, useCallback } from 'react';
import { CheckCircleIcon, TimesCircleIcon } from '@patternfly/react-icons';
import { Spinner } from '@patternfly/react-core';
import type { AgentLoop, AgentLoopStep, ThinkingIteration, MicroReasoning } from '../types/agentLoop';
import { inferNodeType } from '../utils/loopFormatting';

// ---------------------------------------------------------------------------
// Navigation types
// ---------------------------------------------------------------------------

interface NavEntry {
  /** Node type for rendering */
  type: 'step' | 'tool' | 'tool-result' | 'thinking' | 'thinking-iter' | 'micro';
  /** Label shown in breadcrumb */
  label: string;
  /** Step index in loop.steps */
  stepIndex: number;
  /** Sub-item index (tool index, thinking iteration index) */
  subIndex?: number;
}

interface GraphDetailPanelProps {
  loop: AgentLoop;
  /** Initial node ID from the graph click */
  nodeId: string;
  onClose: () => void;
  /** All node IDs at the same level for arrow navigation */
  siblingNodeIds: string[];
  /** Callback when user navigates to a sibling */
  onNavigate: (nodeId: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseNodeId(nodeId: string): NavEntry | null {
  // step-{index}-tool-{j}
  const toolMatch = nodeId.match(/^step-(\d+)-tool-(\d+)$/);
  if (toolMatch) {
    return { type: 'tool', label: `Tool ${parseInt(toolMatch[2]) + 1}`, stepIndex: parseInt(toolMatch[1]), subIndex: parseInt(toolMatch[2]) };
  }
  // step-{index}-think
  const thinkMatch = nodeId.match(/^step-(\d+)-think$/);
  if (thinkMatch) {
    return { type: 'thinking', label: 'Thinking', stepIndex: parseInt(thinkMatch[1]) };
  }
  // step-{index}
  const stepMatch = nodeId.match(/^step-(\d+)$/);
  if (stepMatch) {
    return { type: 'step', label: `Step ${parseInt(stepMatch[1])}`, stepIndex: parseInt(stepMatch[1]) };
  }
  return null;
}

function findStep(loop: AgentLoop, stepIndex: number): AgentLoopStep | undefined {
  return loop.steps.find((s) => s.index === stepIndex);
}

function statusColor(status?: string): string {
  switch (status) {
    case 'done': case 'success': return 'var(--pf-v5-global--success-color--100)';
    case 'failed': case 'error': return 'var(--pf-v5-global--danger-color--100)';
    case 'running': return 'var(--pf-v5-global--info-color--100)';
    default: return '#6a6e73';
  }
}

// ---------------------------------------------------------------------------
// Detail renderers
// ---------------------------------------------------------------------------

const StepDetail: React.FC<{ step: AgentLoopStep; loop: AgentLoop; onDrillDown: (entry: NavEntry) => void }> = ({ step, loop, onDrillDown }) => {
  const nt = inferNodeType(step);

  return (
    <div style={{ fontSize: 13 }}>
      {/* Status + type header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{
          padding: '2px 8px', borderRadius: 4, fontSize: 12, fontWeight: 600,
          color: '#fff', backgroundColor: nt === 'executor' ? '#2e7d32' : nt === 'planner' ? '#0066cc' : nt === 'reflector' ? '#e65100' : '#7b1fa2',
        }}>
          {nt}
        </span>
        {step.status === 'done' && <CheckCircleIcon style={{ color: 'var(--pf-v5-global--success-color--100)' }} />}
        {step.status === 'failed' && <TimesCircleIcon style={{ color: 'var(--pf-v5-global--danger-color--100)' }} />}
        {step.status === 'running' && <Spinner size="sm" aria-label="running" />}
        {step.model && <span style={{ fontSize: 11, color: '#888' }}>{step.model}</span>}
      </div>

      {/* Description */}
      {step.description && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>Description</div>
          <div style={{ color: '#ccc' }}>{step.description}</div>
        </div>
      )}

      {/* Plan (for planner nodes) */}
      {nt === 'planner' && loop.plan.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>Plan ({loop.plan.length} steps)</div>
          <ol style={{ margin: 0, paddingLeft: 18, color: '#ccc', lineHeight: 1.6 }}>
            {loop.plan.map((p, i) => (
              <li key={i} style={{ color: i < loop.currentStep ? 'var(--pf-v5-global--success-color--100)' : '#ccc' }}>{p}</li>
            ))}
          </ol>
        </div>
      )}

      {/* Reasoning */}
      {step.reasoning && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>Reasoning</div>
          <pre style={{ margin: 0, padding: 8, backgroundColor: '#12122a', borderRadius: 4, color: '#bbb', fontSize: 12, overflow: 'auto', maxHeight: 200, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {step.reasoning}
          </pre>
        </div>
      )}

      {/* Tokens */}
      {(step.tokens.prompt + step.tokens.completion > 0) && (
        <div style={{ marginBottom: 12, fontSize: 12, color: '#888' }}>
          Tokens: {step.tokens.prompt.toLocaleString()} prompt + {step.tokens.completion.toLocaleString()} completion = {(step.tokens.prompt + step.tokens.completion).toLocaleString()} total
        </div>
      )}

      {/* Clickable sub-items: Tool calls */}
      {step.toolCalls.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>Tool Calls ({step.toolCalls.length})</div>
          {step.toolCalls.map((tc, j) => {
            const result = step.toolResults[j];
            return (
              <div
                key={j}
                onClick={() => onDrillDown({ type: 'tool', label: tc.name || `Tool ${j + 1}`, stepIndex: step.index, subIndex: j })}
                style={{
                  padding: '6px 10px', marginBottom: 4, borderRadius: 4,
                  backgroundColor: '#1a1a2e', border: '1px solid #333',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
                }}
              >
                <span style={{ color: statusColor(result?.status), fontSize: 14 }}>
                  {result?.status === 'success' ? '\u2713' : result?.status === 'error' ? '\u2717' : '\u25b6'}
                </span>
                <span style={{ color: '#ccc', fontWeight: 500, fontSize: 12 }}>{tc.name || 'unknown'}</span>
                <span style={{ marginLeft: 'auto', color: '#666', fontSize: 11 }}>\u25b6</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Clickable sub-items: Thinking iterations */}
      {(step.thinkings || []).length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: '#b388ff', marginBottom: 6 }}>Thinking ({step.thinkings!.length} iterations)</div>
          {step.thinkings!.map((t, j) => (
            <div
              key={j}
              onClick={() => onDrillDown({ type: 'thinking-iter', label: `Thinking ${t.iteration}`, stepIndex: step.index, subIndex: j })}
              style={{
                padding: '6px 10px', marginBottom: 4, borderRadius: 4,
                backgroundColor: '#1a1a2e', border: '1px solid rgba(179,136,255,0.3)',
                cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
              }}
            >
              <span style={{ color: '#b388ff', fontSize: 12, fontWeight: 500 }}>Iteration {t.iteration}</span>
              <span style={{ color: '#888', fontSize: 11 }}>{((t.prompt_tokens || 0) + (t.completion_tokens || 0)).toLocaleString()} tokens</span>
              <span style={{ marginLeft: 'auto', color: '#666', fontSize: 11 }}>\u25b6</span>
            </div>
          ))}
        </div>
      )}

      {/* Clickable sub-items: Micro-reasoning */}
      {(step.microReasonings || []).length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: '#58a6ff', marginBottom: 6 }}>Micro-reasoning ({step.microReasonings!.length})</div>
          {step.microReasonings!.map((mr, j) => (
            <div
              key={j}
              onClick={() => onDrillDown({ type: 'micro', label: `Micro ${mr.micro_step || j + 1}`, stepIndex: step.index, subIndex: j })}
              style={{
                padding: '6px 10px', marginBottom: 4, borderRadius: 4,
                backgroundColor: '#1a1a2e', border: '1px solid rgba(88,166,255,0.3)',
                cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
              }}
            >
              <span style={{ color: '#58a6ff', fontSize: 12, fontWeight: 500 }}>Step {mr.micro_step || j + 1}</span>
              <span style={{ color: '#888', fontSize: 11 }}>{mr.next_action}</span>
              <span style={{ marginLeft: 'auto', color: '#666', fontSize: 11 }}>\u25b6</span>
            </div>
          ))}
        </div>
      )}

      {/* Prompt info */}
      {step.systemPrompt && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>System Prompt</div>
          <pre style={{ margin: 0, padding: 8, backgroundColor: '#12122a', borderRadius: 4, color: '#999', fontSize: 11, overflow: 'auto', maxHeight: 150, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {step.systemPrompt.substring(0, 500)}{step.systemPrompt.length > 500 ? '...' : ''}
          </pre>
        </div>
      )}
    </div>
  );
};

const ToolDetail: React.FC<{ step: AgentLoopStep; toolIndex: number; onDrillDown: (entry: NavEntry) => void }> = ({ step, toolIndex, onDrillDown }) => {
  const tc = step.toolCalls[toolIndex];
  const result = step.toolResults[toolIndex];
  if (!tc) return <div style={{ color: '#888' }}>Tool not found</div>;

  return (
    <div style={{ fontSize: 13 }}>
      {/* Tool name + status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontWeight: 600, color: '#ccc', fontSize: 14 }}>{tc.name || 'unknown'}</span>
        {result && (
          <span style={{ color: statusColor(result.status) }}>
            {result.status === 'success' ? '\u2713 success' : result.status === 'error' ? '\u2717 error' : result.status || 'pending'}
          </span>
        )}
      </div>

      {/* Arguments */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>Arguments</div>
        <pre style={{ margin: 0, padding: 8, backgroundColor: '#12122a', borderRadius: 4, color: '#bbb', fontSize: 12, overflow: 'auto', maxHeight: 200, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {typeof tc.args === 'string' ? tc.args : JSON.stringify(tc.args, null, 2)}
        </pre>
      </div>

      {/* Result — clickable for drill-down */}
      {result && (
        <div
          onClick={() => onDrillDown({ type: 'tool-result', label: `Result: ${tc.name}`, stepIndex: step.index, subIndex: toolIndex })}
          style={{ marginBottom: 12, cursor: 'pointer' }}
        >
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
            Result <span style={{ color: '#666' }}>\u25b6</span>
          </div>
          <pre style={{
            margin: 0, padding: 8, borderRadius: 4, fontSize: 12, overflow: 'auto', maxHeight: 200,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            backgroundColor: result.status === 'error' ? 'rgba(201,25,11,0.1)' : '#12122a',
            color: result.status === 'error' ? '#ff6b6b' : '#bbb',
            border: `1px solid ${result.status === 'error' ? 'rgba(201,25,11,0.3)' : 'transparent'}`,
          }}>
            {(result.output || '(no output)').substring(0, 500)}{(result.output || '').length > 500 ? '...' : ''}
          </pre>
        </div>
      )}
    </div>
  );
};

const ToolResultDetail: React.FC<{ step: AgentLoopStep; toolIndex: number }> = ({ step, toolIndex }) => {
  const result = step.toolResults[toolIndex];
  if (!result) return <div style={{ color: '#888' }}>Result not found</div>;

  return (
    <div style={{ fontSize: 13 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontWeight: 600, color: '#ccc', fontSize: 14 }}>{result.name || 'Result'}</span>
        <span style={{ color: statusColor(result.status) }}>{result.status || 'unknown'}</span>
      </div>
      <pre style={{
        margin: 0, padding: 10, borderRadius: 4, fontSize: 12, overflow: 'auto',
        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        backgroundColor: result.status === 'error' ? 'rgba(201,25,11,0.1)' : '#12122a',
        color: result.status === 'error' ? '#ff6b6b' : '#bbb',
      }}>
        {result.output || '(no output)'}
      </pre>
    </div>
  );
};

const ThinkingDetail: React.FC<{ thinkings: ThinkingIteration[]; onDrillDown: (entry: NavEntry) => void; stepIndex: number }> = ({ thinkings, onDrillDown, stepIndex }) => (
  <div style={{ fontSize: 13 }}>
    <div style={{ marginBottom: 8, color: '#b388ff', fontWeight: 600 }}>{thinkings.length} Thinking Iterations</div>
    {thinkings.map((t, j) => (
      <div
        key={j}
        onClick={() => onDrillDown({ type: 'thinking-iter', label: `Thinking ${t.iteration}`, stepIndex, subIndex: j })}
        style={{
          padding: '8px 12px', marginBottom: 6, borderRadius: 4,
          backgroundColor: '#12122a', border: '1px solid rgba(179,136,255,0.3)',
          cursor: 'pointer',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
          <span style={{ color: '#b388ff', fontWeight: 500, fontSize: 12 }}>Iteration {t.iteration}</span>
          <span style={{ color: '#888', fontSize: 11 }}>{((t.prompt_tokens || 0) + (t.completion_tokens || 0)).toLocaleString()} tokens \u25b6</span>
        </div>
        <div style={{ color: '#999', fontSize: 12 }}>{(t.reasoning || '').substring(0, 120)}{(t.reasoning || '').length > 120 ? '...' : ''}</div>
      </div>
    ))}
  </div>
);

const ThinkingIterDetail: React.FC<{ thinking: ThinkingIteration }> = ({ thinking }) => (
  <div style={{ fontSize: 13 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
      <span style={{ color: '#b388ff', fontWeight: 600 }}>Thinking {thinking.iteration}/{thinking.total_iterations}</span>
      {thinking.model && <span style={{ color: '#888', fontSize: 11 }}>{thinking.model}</span>}
    </div>
    {(thinking.prompt_tokens || thinking.completion_tokens) && (
      <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>
        {(thinking.prompt_tokens || 0).toLocaleString()} prompt + {(thinking.completion_tokens || 0).toLocaleString()} completion tokens
      </div>
    )}
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>Reasoning</div>
      <pre style={{ margin: 0, padding: 8, backgroundColor: '#12122a', borderRadius: 4, color: '#bbb', fontSize: 12, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {thinking.reasoning || '(empty)'}
      </pre>
    </div>
    {thinking.system_prompt && (
      <div>
        <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>System Prompt</div>
        <pre style={{ margin: 0, padding: 8, backgroundColor: '#12122a', borderRadius: 4, color: '#999', fontSize: 11, overflow: 'auto', maxHeight: 150, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {thinking.system_prompt.substring(0, 500)}{thinking.system_prompt.length > 500 ? '...' : ''}
        </pre>
      </div>
    )}
  </div>
);

const MicroDetail: React.FC<{ micro: MicroReasoning }> = ({ micro }) => (
  <div style={{ fontSize: 13 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
      <span style={{ color: '#58a6ff', fontWeight: 600 }}>Micro-reasoning {micro.micro_step}</span>
      {micro.model && <span style={{ color: '#888', fontSize: 11 }}>{micro.model}</span>}
    </div>
    {micro.next_action && (
      <div style={{ marginBottom: 8, fontSize: 12 }}>
        <span style={{ color: '#888' }}>Next action: </span>
        <span style={{ color: '#ccc' }}>{micro.next_action}</span>
      </div>
    )}
    {(micro.prompt_tokens || micro.completion_tokens) && (
      <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>
        {(micro.prompt_tokens || 0).toLocaleString()} prompt + {(micro.completion_tokens || 0).toLocaleString()} completion tokens
      </div>
    )}
    <div>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>Reasoning</div>
      <pre style={{ margin: 0, padding: 8, backgroundColor: '#12122a', borderRadius: 4, color: '#bbb', fontSize: 12, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {micro.reasoning || '(empty)'}
      </pre>
    </div>
  </div>
);

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export const GraphDetailPanel: React.FC<GraphDetailPanelProps> = ({ loop, nodeId, onClose, siblingNodeIds, onNavigate }) => {
  const [navStack, setNavStack] = useState<NavEntry[]>(() => {
    const entry = parseNodeId(nodeId);
    return entry ? [entry] : [];
  });

  // Reset stack when nodeId changes (sibling navigation)
  useEffect(() => {
    const entry = parseNodeId(nodeId);
    if (entry) setNavStack([entry]);
  }, [nodeId]);

  const currentEntry = navStack[navStack.length - 1];
  const currentStep = currentEntry ? findStep(loop, currentEntry.stepIndex) : undefined;

  // Sibling navigation
  const currentSiblingIdx = siblingNodeIds.indexOf(nodeId);
  const canGoLeft = currentSiblingIdx > 0;
  const canGoRight = currentSiblingIdx < siblingNodeIds.length - 1;

  const goLeft = useCallback(() => {
    if (canGoLeft) onNavigate(siblingNodeIds[currentSiblingIdx - 1]);
  }, [canGoLeft, currentSiblingIdx, siblingNodeIds, onNavigate]);

  const goRight = useCallback(() => {
    if (canGoRight) onNavigate(siblingNodeIds[currentSiblingIdx + 1]);
  }, [canGoRight, currentSiblingIdx, siblingNodeIds, onNavigate]);

  // Drill down into sub-items
  const drillDown = useCallback((entry: NavEntry) => {
    setNavStack((prev) => [...prev, entry]);
  }, []);

  // Navigate to breadcrumb level
  const goToBreadcrumb = useCallback((depth: number) => {
    setNavStack((prev) => prev.slice(0, depth + 1));
  }, []);

  // Keyboard: arrows for siblings, escape to close/go back
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft' && !e.altKey) { e.preventDefault(); goLeft(); }
      else if (e.key === 'ArrowRight' && !e.altKey) { e.preventDefault(); goRight(); }
      else if (e.key === 'Escape') {
        e.preventDefault();
        if (navStack.length > 1) {
          setNavStack((prev) => prev.slice(0, -1));
        } else {
          onClose();
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [goLeft, goRight, navStack.length, onClose]);

  if (!currentEntry || !currentStep) return null;

  // Build label for the current step
  const nt = inferNodeType(currentStep);
  const rootLabel = nt === 'executor' && currentStep.planStep != null
    ? `Step ${currentStep.planStep + 1}`
    : nt;

  return (
    <div
      data-testid="graph-detail-panel"
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        width: 380,
        height: '100%',
        backgroundColor: '#0d1117',
        borderLeft: '1px solid #333',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 20,
        boxShadow: '-4px 0 16px rgba(0,0,0,0.5)',
      }}
    >
      {/* Header: breadcrumb + close + arrows */}
      <div style={{
        padding: '8px 12px',
        borderBottom: '1px solid #333',
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        flexShrink: 0,
      }}>
        {/* Arrow left */}
        <button
          onClick={goLeft}
          disabled={!canGoLeft}
          title="Previous node (ArrowLeft)"
          style={{
            background: 'none', border: 'none', color: canGoLeft ? '#ccc' : '#444',
            fontSize: 16, cursor: canGoLeft ? 'pointer' : 'default', padding: '2px 6px',
          }}
        >
          \u25c0
        </button>

        {/* Breadcrumb */}
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 4, overflow: 'hidden', fontSize: 12 }}>
          {navStack.map((entry, i) => (
            <React.Fragment key={i}>
              {i > 0 && <span style={{ color: '#555' }}>\u203a</span>}
              <span
                onClick={i < navStack.length - 1 ? () => goToBreadcrumb(i) : undefined}
                style={{
                  color: i === navStack.length - 1 ? '#fff' : '#58a6ff',
                  cursor: i < navStack.length - 1 ? 'pointer' : 'default',
                  fontWeight: i === navStack.length - 1 ? 600 : 400,
                  whiteSpace: 'nowrap',
                }}
              >
                {i === 0 ? rootLabel : entry.label}
              </span>
            </React.Fragment>
          ))}
        </div>

        {/* Arrow right */}
        <button
          onClick={goRight}
          disabled={!canGoRight}
          title="Next node (ArrowRight)"
          style={{
            background: 'none', border: 'none', color: canGoRight ? '#ccc' : '#444',
            fontSize: 16, cursor: canGoRight ? 'pointer' : 'default', padding: '2px 6px',
          }}
        >
          \u25b6
        </button>

        {/* Close */}
        <button
          onClick={onClose}
          title="Close (Esc)"
          style={{
            background: 'none', border: '1px solid #555', color: '#ccc',
            fontSize: 12, cursor: 'pointer', padding: '2px 8px', borderRadius: 3,
          }}
        >
          \u2716
        </button>
      </div>

      {/* Sibling position indicator */}
      {siblingNodeIds.length > 1 && (
        <div style={{ padding: '4px 12px', fontSize: 11, color: '#666', borderBottom: '1px solid #222' }}>
          {currentSiblingIdx + 1} / {siblingNodeIds.length}
        </div>
      )}

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', padding: '12px' }}>
        {currentEntry.type === 'step' && (
          <StepDetail step={currentStep} loop={loop} onDrillDown={drillDown} />
        )}
        {currentEntry.type === 'tool' && currentEntry.subIndex != null && (
          <ToolDetail step={currentStep} toolIndex={currentEntry.subIndex} onDrillDown={drillDown} />
        )}
        {currentEntry.type === 'tool-result' && currentEntry.subIndex != null && (
          <ToolResultDetail step={currentStep} toolIndex={currentEntry.subIndex} />
        )}
        {currentEntry.type === 'thinking' && currentStep.thinkings && (
          <ThinkingDetail thinkings={currentStep.thinkings} onDrillDown={drillDown} stepIndex={currentStep.index} />
        )}
        {currentEntry.type === 'thinking-iter' && currentEntry.subIndex != null && currentStep.thinkings && (
          <ThinkingIterDetail thinking={currentStep.thinkings[currentEntry.subIndex]} />
        )}
        {currentEntry.type === 'micro' && currentEntry.subIndex != null && currentStep.microReasonings && (
          <MicroDetail micro={currentStep.microReasonings[currentEntry.subIndex]} />
        )}
      </div>
    </div>
  );
};
