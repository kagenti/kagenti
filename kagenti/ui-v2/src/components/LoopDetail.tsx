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

const PromptBlock: React.FC<{ systemPrompt?: string; promptMessages?: PromptMessage[] }> = ({ systemPrompt, promptMessages }) => {
  const [expanded, setExpanded] = useState(false);
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
      <div style={{ fontWeight: 600, cursor: 'pointer', userSelect: 'none' }} onClick={() => setExpanded(!expanded)}>
        {expanded ? '\u25bc' : '\u25b6'} Prompt <span style={{ fontWeight: 400, color: 'var(--pf-v5-global--Color--200)', fontSize: '0.85em' }}>({preview})</span>
      </div>
      {expanded && (
        <div style={{ marginTop: 6 }}>
          {systemPrompt && (
            <NestedCollapsible label="System Prompt" preview={systemPrompt.substring(0, 60).replace(/\n/g, ' ')}>
              <pre style={{ margin: '4px 0', padding: 8, backgroundColor: 'var(--pf-v5-global--BackgroundColor--dark-300)', color: 'var(--pf-v5-global--Color--light-100)', borderRadius: 4, fontSize: '0.85em', overflow: 'auto', maxHeight: 400, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {systemPrompt}
              </pre>
            </NestedCollapsible>
          )}
          {promptMessages && promptMessages.length > 0 && (
            <NestedCollapsible label={`Messages (${msgCount})`} preview={`${msgCount} messages: ${promptMessages.map(m => m.role).join(', ').substring(0, 40)}`}>
              {promptMessages.map((msg, i) => (
                <div key={i} style={{ margin: '2px 0', padding: '4px 8px', borderLeft: `2px solid ${msg.role === 'system' ? '#475569' : msg.role === 'tool' ? '#2e7d32' : '#0066cc'}`, fontSize: '0.85em' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.8em', color: 'var(--pf-v5-global--Color--200)' }}>{msg.role}</span>
                  <span style={{ marginLeft: 6, color: 'var(--pf-v5-global--Color--100)' }}>{msg.preview.substring(0, 150)}{msg.preview.length > 150 ? '...' : ''}</span>
                </div>
              ))}
            </NestedCollapsible>
          )}
        </div>
      )}
    </div>
  );
};

const NestedCollapsible: React.FC<{ label: string; preview: string; children: React.ReactNode }> = ({ label, preview, children }) => {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ margin: '4px 0' }}>
      <div style={{ fontWeight: 500, cursor: 'pointer', userSelect: 'none', fontSize: '0.9em' }} onClick={() => setOpen(!open)}>
        {open ? '\u25bc' : '\u25b6'} {label} <span style={{ fontWeight: 400, color: 'var(--pf-v5-global--Color--200)', fontSize: '0.85em' }}>{!open ? preview : ''}</span>
      </div>
      {open && children}
    </div>
  );
};

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

const ToolResultBlock: React.FC<{ result: AgentLoopStep['toolResults'][number] }> = ({ result }) => {
  const [expanded, setExpanded] = useState(false);

  const preview = toolOutputPreview(result.output);
  const hasError = isToolResultError(result.output);
  return (
    <div
      style={{
        margin: '4px 0',
        padding: '6px 10px',
        borderLeft: `3px solid ${hasError ? 'var(--pf-v5-global--danger-color--100)' : 'var(--pf-v5-global--success-color--100)'}`,
        backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
        borderRadius: '0 4px 4px 0',
        fontSize: '0.85em',
        cursor: 'pointer',
      }}
      onClick={() => setExpanded(!expanded)}
    >
      <div style={{ fontWeight: 600 }}>
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

const StepSection: React.FC<{ step: AgentLoopStep; total: number; loopModel?: string; onOpenInspector?: (title: string, data: Partial<AgentLoopStep> | MicroReasoning) => void }> = ({ step, total, loopModel, onOpenInspector }) => {
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
        Step {step.index + 1}{total > 0 ? `/${total}` : ''}: {step.description}
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
      <PromptBlock systemPrompt={step.systemPrompt} promptMessages={step.promptMessages} />

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
          let matchedResult = step.toolResults[i] && !usedResults.has(i) ? step.toolResults[i] : undefined;
          let matchedIdx = matchedResult ? i : -1;
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
                    </span>
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
        <StepSection key={step.index} step={step} total={loop.totalSteps} loopModel={loop.model} onOpenInspector={openInspector} />
      ))}

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
