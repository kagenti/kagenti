// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * LoopDetail — expandable detail section for an AgentLoopCard.
 *
 * Renders:
 * - Plan section: numbered list of plan steps, current step highlighted
 * - Step sections: header, tool calls, tool results for each completed step
 * - Reflection section: assessment + decision (if present)
 */

import React, { useState } from 'react';
import { Spinner } from '@patternfly/react-core';
import { CheckCircleIcon, TimesCircleIcon } from '@patternfly/react-icons';
import type { AgentLoop, AgentLoopStep, MicroReasoning, NodeType } from '../types/agentLoop';
import PromptInspector from './PromptInspector';

// ---------------------------------------------------------------------------
// Graph node badge
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<NodeType, { bg: string; label: string }> = {
  planner:    { bg: '#0066cc', label: 'planner' },
  replanner:  { bg: '#0055aa', label: 'replanner' },
  executor:   { bg: '#2e7d32', label: 'executor' },
  reflector:  { bg: '#e65100', label: 'reflector' },
  reporter:   { bg: '#7b1fa2', label: 'reporter' },
};

/** Infer the graph node type from step content when not explicitly set. */
function inferNodeType(step: AgentLoopStep): NodeType {
  if (step.nodeType) return step.nodeType;
  if (step.toolCalls.length > 0 || step.toolResults.length > 0) return 'executor';
  return 'planner';
}

const NodeBadge: React.FC<{ nodeType: NodeType }> = ({ nodeType }) => {
  const info = NODE_COLORS[nodeType];
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '1px 6px',
        borderRadius: 3,
        fontSize: '0.78em',
        fontWeight: 600,
        color: '#fff',
        backgroundColor: info.bg,
        marginRight: 6,
        lineHeight: 1.5,
        verticalAlign: 'middle',
      }}
    >
      {info.label}
    </span>
  );
};

interface LoopDetailProps {
  loop: AgentLoop;
}

// ---------------------------------------------------------------------------
// Plan section
// ---------------------------------------------------------------------------

const PlanSection: React.FC<{ plan: string[]; currentStep: number; loopDone: boolean }> = ({ plan, currentStep, loopDone }) => {
  if (plan.length === 0) return null;

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontWeight: 600, fontSize: '0.85em', marginBottom: 6, color: 'var(--pf-v5-global--Color--100)' }}>
        <NodeBadge nodeType="planner" />
        Plan ({plan.length} step{plan.length !== 1 ? 's' : ''})
      </div>
      <ol style={{ margin: 0, paddingLeft: 22, fontSize: '0.83em', lineHeight: 1.7 }}>
        {plan.map((step, i) => {
          const isCurrent = i === currentStep;
          const isDone = loopDone || i < currentStep;
          return (
            <li
              key={i}
              style={{
                fontWeight: isCurrent && !loopDone ? 600 : 400,
                color: isDone
                  ? 'var(--pf-v5-global--success-color--100)'
                  : isCurrent
                    ? 'var(--pf-v5-global--info-color--100)'
                    : 'var(--pf-v5-global--Color--200)',
              }}
            >
              {step}
              {isCurrent && !loopDone && (
                <Spinner size="sm" aria-label="current step" style={{ marginLeft: 6 }} />
              )}
              {isDone && (
                <CheckCircleIcon style={{ color: 'var(--pf-v5-global--success-color--100)', marginLeft: 6, fontSize: '0.85em' }} />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Prompt block (expandable — shows system prompt + message history)
// ---------------------------------------------------------------------------

interface PromptMessage { role: string; preview: string }

const PromptBlock: React.FC<{ systemPrompt?: string; promptMessages?: PromptMessage[]; onOpenInspector?: (title: string, data: Partial<AgentLoopStep>) => void }> = ({ systemPrompt, promptMessages, onOpenInspector }) => {
  const [expanded, setExpanded] = useState(false);
  console.log('[PromptBlock] systemPrompt:', !!systemPrompt, 'msgs:', promptMessages?.length);
  if (!systemPrompt && (!promptMessages || promptMessages.length === 0)) return null;

  const msgCount = promptMessages?.length || 0;
  const preview = systemPrompt
    ? `${systemPrompt.substring(0, 80).replace(/\n/g, ' ')}...`
    : `${msgCount} messages`;

  return (
    <div
      style={{
        margin: '4px 0',
        padding: '6px 10px',
        borderLeft: '3px solid #475569',
        backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
        borderRadius: '0 4px 4px 0',
        fontSize: '0.85em',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontWeight: 600, cursor: 'pointer', userSelect: 'none' }} onClick={() => setExpanded(!expanded)}>
          {expanded ? '\u25bc' : '\u25b6'} Prompt <span style={{ fontWeight: 400, color: 'var(--pf-v5-global--Color--200)', fontSize: '0.85em' }}>({preview})</span>
        </div>
        {onOpenInspector && (
          <button
            onClick={(e) => { e.stopPropagation(); onOpenInspector('Prompt Details', { systemPrompt, promptMessages } as Partial<AgentLoopStep>); }}
            style={{ background: 'none', border: '1px solid #555', color: '#888', fontSize: '11px', padding: '2px 6px', borderRadius: '3px', cursor: 'pointer' }}
          >
            Fullscreen
          </button>
        )}
      </div>
      {expanded && (
        <div style={{ marginTop: 6 }}>
          {systemPrompt && (
            <pre style={{ margin: '4px 0', padding: 8, backgroundColor: 'var(--pf-v5-global--BackgroundColor--dark-300)', color: 'var(--pf-v5-global--Color--light-100)', borderRadius: 4, fontSize: '0.85em', overflow: 'auto', maxHeight: 300, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {systemPrompt}
            </pre>
          )}
          {promptMessages && promptMessages.length > 0 && promptMessages.map((msg, i) => (
            <div key={i} style={{ margin: '2px 0', padding: '4px 8px', borderLeft: `2px solid ${msg.role === 'system' ? '#475569' : msg.role === 'tool' ? '#2e7d32' : '#0066cc'}`, fontSize: '0.85em' }}>
              <span style={{ fontWeight: 600, fontSize: '0.8em', color: 'var(--pf-v5-global--Color--200)' }}>{msg.role}</span>
              <pre style={{ margin: '4px 0 0', padding: 6, backgroundColor: 'var(--pf-v5-global--BackgroundColor--dark-300)', color: 'var(--pf-v5-global--Color--light-100)', borderRadius: 4, fontSize: '0.85em', overflow: 'auto', maxHeight: 200, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {msg.preview}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// NestedCollapsible removed — PromptBlock now opens PromptInspector popup

// ---------------------------------------------------------------------------
// Reasoning block (expandable, like ToolCallBlock)
// ---------------------------------------------------------------------------

const ReasoningBlock: React.FC<{ reasoning: string }> = ({ reasoning }) => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      style={{
        margin: '4px 0',
        padding: '6px 10px',
        borderLeft: '3px solid #7c3aed',
        backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
        borderRadius: '0 4px 4px 0',
        fontSize: '0.85em',
        cursor: 'pointer',
      }}
      onClick={() => setExpanded(!expanded)}
    >
      <div style={{ fontWeight: 600 }}>
        {expanded ? '\u25bc' : '\u25b6'} Reasoning
      </div>
      {expanded && (
        <pre
          style={{
            margin: '4px 0',
            padding: 8,
            backgroundColor: 'var(--pf-v5-global--BackgroundColor--dark-300)',
            color: 'var(--pf-v5-global--Color--light-100)',
            borderRadius: 4,
            fontSize: '0.9em',
            overflow: 'auto',
            maxHeight: 300,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {reasoning}
        </pre>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Tool call / result rendering (matches SandboxPage ToolCallStep pattern)
// ---------------------------------------------------------------------------

/** One-line preview of tool args */
function toolArgsPreview(args: unknown): string {
  if (!args) return '';
  const s = typeof args === 'string' ? args : JSON.stringify(args);
  return s.replace(/[\n\r]+/g, ' ').substring(0, 80);
}

/**
 * Determine whether a tool result represents a failure.
 *
 * Many successful commands (git, curl, wget) write progress/info to stderr,
 * so the presence of "STDERR:" alone does NOT indicate failure.
 *
 * Strategy:
 * 1. If an explicit exit code is found (e.g. "exit code: 0"), use that.
 * 2. If no exit code, look for real error indicators (but NOT "stderr" by itself).
 * 3. Default to success (not failed) — let the content speak for itself.
 */
function isToolResultError(output: string | undefined): boolean {
  if (!output) return false;

  // Check for explicit exit code patterns (case-insensitive)
  const exitCodeMatch = output.match(/exit[\s_-]*code[:\s]+(\d+)/i)
    || output.match(/exited[\s]+with[\s]+(\d+)/i)
    || output.match(/return[\s_-]*code[:\s]+(\d+)/i);
  if (exitCodeMatch) {
    return exitCodeMatch[1] !== '0';
  }

  // No exit code found — check for real error indicators
  // Exclude "stderr" as a keyword; many successful commands use stderr for progress
  return /\b(error|fail(ed|ure)?|denied|permission denied|not found|traceback|exception)\b/i.test(output);
}

/** One-line preview of tool output */
function toolOutputPreview(output: string | undefined): string {
  if (!output) return '(no output)';
  const first = output.split('\n')[0].substring(0, 80);
  const hasError = isToolResultError(output);
  return hasError ? `\u274c ${first}` : first;
}

const ToolCallBlock: React.FC<{ call: AgentLoopStep['toolCalls'][number]; hasResult?: boolean; resultError?: boolean }> = ({ call, hasResult, resultError }) => {
  const [expanded, setExpanded] = useState(false);

  const label = call.name || 'unknown';
  const preview = toolArgsPreview(call.args);
  const pending = hasResult === false;
  return (
    <div
      style={{
        margin: '4px 0',
        padding: '6px 10px',
        borderLeft: `3px solid ${resultError ? 'var(--pf-v5-global--danger-color--100)' : pending ? 'var(--pf-v5-global--warning-color--100)' : 'var(--pf-v5-global--info-color--100)'}`,
        backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
        borderRadius: '0 4px 4px 0',
        fontSize: '0.85em',
        cursor: 'pointer',
      }}
      onClick={() => setExpanded(!expanded)}
    >
      <div style={{ fontWeight: 600, display: 'flex', alignItems: 'center' }}>
        {expanded ? '\u25bc' : '\u25b6'} Tool Call: {label}
        {pending && <Spinner size="sm" aria-label="running" style={{ marginLeft: 6 }} />}
        {hasResult && !resultError && <CheckCircleIcon style={{ color: 'var(--pf-v5-global--success-color--100)', marginLeft: 6, fontSize: '0.9em' }} />}
        {resultError && <TimesCircleIcon style={{ color: 'var(--pf-v5-global--danger-color--100)', marginLeft: 6, fontSize: '0.9em' }} />}
        {!expanded && preview && (
          <span style={{ fontWeight: 400, color: 'var(--pf-v5-global--Color--200)', marginLeft: 8, fontSize: '0.9em' }}>
            {preview}{preview.length >= 80 ? '...' : ''}
          </span>
        )}
      </div>
      {expanded && (
        <pre
          style={{
            margin: '4px 0',
            padding: 8,
            backgroundColor: 'var(--pf-v5-global--BackgroundColor--dark-300)',
            color: 'var(--pf-v5-global--Color--light-100)',
            borderRadius: 4,
            fontSize: '0.9em',
            overflow: 'auto',
          }}
        >
          {label}({typeof call.args === 'string' ? call.args : JSON.stringify(call.args, null, 2)})
        </pre>
      )}
    </div>
  );
};

const statusIcon = (status?: string) => {
  switch (status) {
    case 'error': return '\u274c';
    case 'timeout': return '\u23f3';
    case 'success': return '\u2713';
    default: return '\u25b6';
  }
};

const ToolResultBlock: React.FC<{ result: AgentLoopStep['toolResults'][number] }> = ({ result }) => {
  const [expanded, setExpanded] = useState(false);

  const preview = toolOutputPreview(result.output);
  const hasError = result.status === 'error' || isToolResultError(result.output);
  return (
    <div
      style={{
        margin: '4px 0',
        padding: '6px 10px',
        borderLeft: `3px solid ${hasError ? 'var(--pf-v5-global--danger-color--100)' : 'var(--pf-v5-global--success-color--100)'}`,
        backgroundColor: hasError ? 'rgba(201, 25, 11, 0.08)' : 'var(--pf-v5-global--BackgroundColor--200)',
        borderRadius: '0 4px 4px 0',
        fontSize: '0.85em',
        cursor: 'pointer',
      }}
      onClick={() => setExpanded(!expanded)}
    >
      <div style={{ fontWeight: 600 }}>
        <span style={{ marginRight: 4 }}>{statusIcon(result.status)}</span>
        {expanded ? '\u25bc' : '\u25b6'} Result: {result.name || 'unknown'}
        {!expanded && (
          <span style={{ fontWeight: 400, color: hasError ? 'var(--pf-v5-global--danger-color--100)' : 'var(--pf-v5-global--Color--200)', marginLeft: 8, fontSize: '0.9em' }}>
            {preview}
          </span>
        )}
      </div>
      {expanded && (
        <pre
          style={{
            margin: '4px 0',
            padding: 8,
            backgroundColor: 'var(--pf-v5-global--BackgroundColor--dark-300)',
            color: 'var(--pf-v5-global--Color--light-100)',
            borderRadius: 4,
            fontSize: '0.9em',
            overflow: 'auto',
            maxHeight: 200,
          }}
        >
          {result.output || '(no output)'}
        </pre>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Step section
// ---------------------------------------------------------------------------

const StepStatusIcon: React.FC<{ status: AgentLoopStep['status'] }> = ({ status }) => {
  if (status === 'running') {
    return <Spinner size="sm" aria-label="running" style={{ marginLeft: 6 }} />;
  }
  if (status === 'done') {
    return (
      <CheckCircleIcon
        style={{ color: 'var(--pf-v5-global--success-color--100)', marginLeft: 6, fontSize: '0.9em' }}
      />
    );
  }
  if (status === 'failed') {
    return (
      <TimesCircleIcon
        style={{ color: 'var(--pf-v5-global--danger-color--100)', marginLeft: 6, fontSize: '0.9em' }}
      />
    );
  }
  return null;
};

function formatStepTokens(step: AgentLoopStep): string {
  const total = step.tokens.prompt + step.tokens.completion;
  if (total >= 1000) return (total / 1000).toFixed(1) + 'k';
  return String(total);
}

const StepSection: React.FC<{ step: AgentLoopStep; total: number; loopCurrentStep?: number; loopModel?: string; onOpenInspector?: (title: string, data: Partial<AgentLoopStep> | MicroReasoning) => void }> = ({ step, total, loopCurrentStep, loopModel, onOpenInspector }) => {
  const showModelBadge = step.model && step.model !== loopModel;

  return (
    <div style={{ marginBottom: 10 }}>
      {/* Step header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          fontSize: '0.84em',
          fontWeight: 600,
          color: 'var(--pf-v5-global--Color--100)',
          marginBottom: 4,
          flexWrap: 'wrap',
        }}
      >
        <NodeBadge nodeType={inferNodeType(step)} />
        {(() => {
          const nt = inferNodeType(step);
          if (nt === 'planner' || nt === 'replanner') return step.description;
          if (nt === 'reflector') return step.description;
          if (nt === 'reporter') return 'Final answer';
          // Executor: Step X [N] where X=plan step, N=global node visit
          const planStep = step.planStep ?? loopCurrentStep;
          const visitNum = step.index != null ? `[${step.index}]` : '';
          const stepLabel = planStep != null
            ? `Step ${planStep + 1}${total > 0 ? `/${total}` : ''} ${visitNum}`.trim()
            : visitNum || '';
          // Strip redundant "Step N:" prefix from description (agent may include it)
          let desc = step.description || '';
          desc = desc.replace(/^Step\s+\d+[:/]?\s*/i, '').trim();
          if (desc === 'Tool execution') desc = '';
          if (stepLabel && desc) return `${stepLabel}: ${desc}`;
          if (stepLabel) return stepLabel;
          return desc || 'Executing';
        })()}
        {showModelBadge && (
          <span
            style={{
              display: 'inline-block',
              padding: '1px 5px',
              borderRadius: 3,
              fontSize: '0.75em',
              fontWeight: 500,
              color: 'var(--pf-v5-global--Color--200)',
              backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
              border: '1px solid var(--pf-v5-global--BorderColor--100)',
              marginLeft: 6,
              verticalAlign: 'middle',
            }}
          >
            {step.model}
          </span>
        )}
        {step.tokens.prompt + step.tokens.completion > 0 && (
          <span style={{ fontWeight: 400, fontSize: '0.78em', color: 'var(--pf-v5-global--Color--200)', marginLeft: 8 }}>
            &middot; {formatStepTokens(step)} tokens
          </span>
        )}
        {step.updatedAt && (
          <span
            title={`Created: ${step.createdAt || '?'}\nUpdated: ${step.updatedAt}`}
            style={{ fontWeight: 400, fontSize: '0.78em', color: 'var(--pf-v5-global--Color--200)', marginLeft: 8 }}
          >
            &middot; {new Date(step.updatedAt).toLocaleTimeString()}
          </span>
        )}
        <StepStatusIcon status={step.status} />
        {onOpenInspector && (step.systemPrompt || step.promptMessages) && (
          <button
            onClick={() => onOpenInspector(`${step.eventType || step.nodeType || 'Step'} ${step.index}`, step)}
            style={{
              background: 'none', border: '1px solid #555', color: '#888',
              fontSize: '11px', padding: '2px 6px', borderRadius: '3px',
              cursor: 'pointer', marginLeft: '8px',
            }}
            title="View full prompt and response"
          >
            Prompt
          </button>
        )}
      </div>

      {/* Prompt — system prompt + messages sent to LLM */}
      <PromptBlock systemPrompt={step.systemPrompt} promptMessages={step.promptMessages} onOpenInspector={onOpenInspector} />

      {/* Reasoning / LLM response (expandable for all node types) */}
      {step.reasoning && <ReasoningBlock reasoning={step.reasoning} />}
      {!step.reasoning && step.description && step.description.length > 60 && (
        <ReasoningBlock reasoning={step.description} />
      )}

      {/* Tool calls paired with results, interleaved with micro-reasoning.
          Micro-reasoning N appears AFTER tool pair N (chronological order):
          tool_call[0] → result[0] → micro_reasoning[0] → tool_call[1] → result[1] → micro_reasoning[1] ...
      */}
      {(() => {
        const usedResults = new Set<number>();
        const mrs = step.microReasonings || [];
        return step.toolCalls.map((tc, i) => {
          // First try call_id match
          let matchedResult = step.toolResults.find(
            (tr, idx) => !usedResults.has(idx) && tr.call_id && tr.call_id === tc.call_id
          );
          let matchedIdx = matchedResult ? step.toolResults.indexOf(matchedResult) : -1;

          // Fall back to positional, then name-based
          if (!matchedResult) {
            matchedResult = step.toolResults[i] && !usedResults.has(i) ? step.toolResults[i] : undefined;
            matchedIdx = matchedResult ? i : -1;
          }
          if (!matchedResult) {
            matchedIdx = step.toolResults.findIndex(
              (tr, idx) => !usedResults.has(idx) && tr.name === tc.name,
            );
            matchedResult = matchedIdx >= 0 ? step.toolResults[matchedIdx] : undefined;
          }
          if (matchedResult && matchedIdx >= 0) usedResults.add(matchedIdx);

          const hasResult = !!matchedResult || step.status === 'done' || step.status === 'failed';
          const resultError = !!matchedResult && isToolResultError(matchedResult?.output);
          // Find micro-reasoning that follows this tool pair (micro_step matches tool index)
          const mr = mrs.find(m => m.micro_step === i + 1) || mrs[i];
          return (
            <React.Fragment key={`tool-group-${i}`}>
              <div style={{ marginLeft: 4, borderLeft: '1px solid var(--pf-v5-global--BorderColor--100)', paddingLeft: 8 }}>
                <ToolCallBlock call={tc} hasResult={hasResult} resultError={resultError} />
                {matchedResult && <ToolResultBlock result={matchedResult} />}
              </div>
              {mr && (
                <div style={{
                  margin: '8px 0', padding: '8px 12px',
                  backgroundColor: '#1a1a2e', borderRadius: '4px',
                  borderLeft: '3px solid #58a6ff', fontSize: '13px',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ color: '#58a6ff', fontWeight: 'bold', fontSize: '12px' }}>
                      Micro-reasoning {(mr.micro_step || i + 1)}
                      {(mr.prompt_tokens || mr.completion_tokens) && (
                        <span style={{ color: '#888', fontWeight: 'normal', marginLeft: '8px', fontSize: '11px' }}>
                          · {((mr.prompt_tokens || 0) + (mr.completion_tokens || 0)).toLocaleString()} tokens
                        </span>
                      )}
                    </span>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                      {mr.model && (
                        <span style={{ fontSize: '11px', color: '#666' }}>{mr.model}</span>
                      )}
                      {onOpenInspector && (
                        <button
                          onClick={() => onOpenInspector(`Micro-reasoning ${mr.micro_step || i + 1}`, mr)}
                          style={{
                            background: 'none', border: '1px solid #555', color: '#888',
                            fontSize: '11px', padding: '2px 6px', borderRadius: '3px', cursor: 'pointer',
                          }}
                        >
                          Prompt
                        </button>
                      )}
                    </div>
                  </div>
                  {mr.reasoning && (
                    <p style={{ margin: '4px 0 0', color: '#ccc', whiteSpace: 'pre-wrap' }}>
                      {mr.reasoning.substring(0, 500)}{mr.reasoning.length > 500 ? '...' : ''}
                    </p>
                  )}
                </div>
              )}
            </React.Fragment>
          );
        });
      })()}
      {/* Orphan results (no matching call) */}
      {step.toolResults.filter((_tr, idx) => idx >= step.toolCalls.length).map((tr, i) => (
        <ToolResultBlock key={`orphan-result-${i}`} result={tr} />
      ))}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Replan section (expandable, shows revised plans after reflector triggers replan)
// ---------------------------------------------------------------------------

const ReplanSection: React.FC<{ replans: AgentLoop['replans'] }> = ({ replans }) => {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  if (!replans || replans.length === 0) return null;

  return (
    <>
      {replans.map((rp, idx) => (
        <div key={idx} style={{ marginBottom: 8 }}>
          <div
            style={{ fontWeight: 600, fontSize: '0.85em', marginBottom: 4, color: 'var(--pf-v5-global--Color--100)', cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
          >
            <NodeBadge nodeType="replanner" />
            {expandedIdx === idx ? '\u25BC' : '\u25B6'} Replan (iteration {rp.iteration + 1}): {rp.steps.length} step{rp.steps.length !== 1 ? 's' : ''}
          </div>
          {expandedIdx === idx && (
            <ol style={{ margin: 0, paddingLeft: 22, fontSize: '0.83em', lineHeight: 1.7 }}>
              {rp.steps.map((step, i) => (
                <li key={i} style={{ color: 'var(--pf-v5-global--Color--200)' }}>{step}</li>
              ))}
            </ol>
          )}
        </div>
      ))}
    </>
  );
};

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export const LoopDetail: React.FC<LoopDetailProps> = ({ loop }) => {
  const [inspectorData, setInspectorData] = useState<{
    isOpen: boolean;
    title: string;
    systemPrompt?: string;
    promptMessages?: Array<{ role: string; preview: string }>;
    response?: string;
    model?: string;
    promptTokens?: number;
    completionTokens?: number;
  } | null>(null);

  const openInspector = (title: string, data: Partial<AgentLoopStep> | MicroReasoning) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const d = data as any;
    const isMicro = d.type === 'micro_reasoning';
    setInspectorData({
      isOpen: true,
      title,
      systemPrompt: isMicro ? d.system_prompt : d.systemPrompt,
      promptMessages: isMicro ? d.prompt_messages : d.promptMessages,
      response: d.reasoning || d.assessment || d.content || '',
      model: d.model,
      promptTokens: isMicro ? d.prompt_tokens : d.tokens?.prompt,
      completionTokens: isMicro ? d.completion_tokens : d.tokens?.completion,
    });
  };

  return (
    <div
      style={{
        borderTop: '1px solid var(--pf-v5-global--BorderColor--100)',
        marginTop: 10,
        paddingTop: 10,
      }}
    >
      <PlanSection plan={loop.plan} currentStep={loop.currentStep} loopDone={loop.status === 'done'} />
      <ReplanSection replans={loop.replans} />

      {loop.steps.map((step) => (
        <StepSection key={step.index} step={step} total={loop.totalSteps} loopCurrentStep={loop.currentStep} loopModel={loop.model} onOpenInspector={openInspector} />
      ))}

      {/* Streaming indicator — shows when agent is still working */}
      {(loop.status === 'executing' || loop.status === 'planning' || loop.status === 'reflecting') && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 12px', marginTop: 4,
          borderLeft: '3px solid var(--pf-v5-global--info-color--100)',
          backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
          borderRadius: '0 4px 4px 0', fontSize: '0.85em',
          color: 'var(--pf-v5-global--Color--200)',
        }}>
          <span style={{
            display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
            backgroundColor: 'var(--pf-v5-global--info-color--100)',
            animation: 'pulse 1.5s ease-in-out infinite',
          }} />
          Agent is {loop.status === 'planning' ? 'planning' : loop.status === 'reflecting' ? 'reflecting' : 'working'}...
          {loop.budget?.tokensUsed ? ` (${(loop.budget.tokensUsed / 1000).toFixed(1)}K tokens)` : ''}
          <style>{`@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }`}</style>
        </div>
      )}

      {inspectorData && (
        <PromptInspector
          isOpen={inspectorData.isOpen}
          onClose={() => setInspectorData(null)}
          title={inspectorData.title}
          systemPrompt={inspectorData.systemPrompt}
          promptMessages={inspectorData.promptMessages}
          response={inspectorData.response}
          model={inspectorData.model}
          promptTokens={inspectorData.promptTokens}
          completionTokens={inspectorData.completionTokens}
        />
      )}
    </div>
  );
};
