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
import type { AgentLoop, AgentLoopStep, NodeType } from '../types/agentLoop';

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

/** One-line preview of tool output */
function toolOutputPreview(output: string | undefined): string {
  if (!output) return '(no output)';
  const first = output.split('\n')[0].substring(0, 80);
  const hasError = /error|fail|denied|stderr/i.test(first);
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
  const hasError = /error|fail|denied|stderr/i.test(result.output || '');
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

const StepSection: React.FC<{ step: AgentLoopStep; total: number; loopModel?: string }> = ({ step, total, loopModel }) => {
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
      </div>

      {/* Prompt — system prompt + messages sent to LLM */}
      <PromptBlock systemPrompt={step.systemPrompt} promptMessages={step.promptMessages} />

      {/* Reasoning / LLM response (expandable for all node types) */}
      {step.reasoning && <ReasoningBlock reasoning={step.reasoning} />}
      {!step.reasoning && step.description && step.description.length > 60 && (
        <ReasoningBlock reasoning={step.description} />
      )}

      {/* Tool calls paired with results — call followed by its result */}
      {step.toolCalls.map((tc, i) => {
        const matchedResult = step.toolResults[i] ||
          step.toolResults.find((tr) => tr.name === tc.name && !step.toolCalls.slice(0, i).some((prev) => prev.name === tr.name));
        const hasResult = !!matchedResult;
        const resultError = hasResult && /error|fail|denied|stderr/i.test(matchedResult?.output || '');
        return (
          <div key={`tool-pair-${i}`} style={{ marginLeft: 4, borderLeft: '1px solid var(--pf-v5-global--BorderColor--100)', paddingLeft: 8 }}>
            <ToolCallBlock call={tc} hasResult={hasResult} resultError={resultError} />
            {matchedResult && <ToolResultBlock result={matchedResult} />}
          </div>
        );
      })}
      {/* Orphan results (no matching call) */}
      {step.toolResults.slice(step.toolCalls.length).map((tr, i) => (
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
        <StepSection key={step.index} step={step} total={loop.totalSteps} loopModel={loop.model} />
      ))}
    </div>
  );
};
