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
  planner:   { bg: '#0066cc', label: 'planner' },
  executor:  { bg: '#2e7d32', label: 'executor' },
  reflector: { bg: '#e65100', label: 'reflector' },
  reporter:  { bg: '#7b1fa2', label: 'reporter' },
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
// Reasoning block (expandable, like ToolCallBlock)
// ---------------------------------------------------------------------------

const ReasoningBlock: React.FC<{ reasoning: string }> = ({ reasoning }) => {
  const [expanded, setExpanded] = useState(true);

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

const ToolCallBlock: React.FC<{ call: AgentLoopStep['toolCalls'][number] }> = ({ call }) => {
  const [expanded, setExpanded] = useState(true);

  const label = call.name || 'unknown';
  return (
    <div
      style={{
        margin: '4px 0',
        padding: '6px 10px',
        borderLeft: '3px solid var(--pf-v5-global--info-color--100)',
        backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
        borderRadius: '0 4px 4px 0',
        fontSize: '0.85em',
        cursor: 'pointer',
      }}
      onClick={() => setExpanded(!expanded)}
    >
      <div style={{ fontWeight: 600 }}>
        {expanded ? '\u25bc' : '\u25b6'} Tool Call: {label}
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
  const [expanded, setExpanded] = useState(true);

  return (
    <div
      style={{
        margin: '4px 0',
        padding: '6px 10px',
        borderLeft: '3px solid var(--pf-v5-global--success-color--100)',
        backgroundColor: 'var(--pf-v5-global--BackgroundColor--200)',
        borderRadius: '0 4px 4px 0',
        fontSize: '0.85em',
        cursor: 'pointer',
      }}
      onClick={() => setExpanded(!expanded)}
    >
      <div style={{ fontWeight: 600 }}>
        {expanded ? '\u25bc' : '\u25b6'} Result: {result.name || 'unknown'}
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

      {/* Reasoning / description content (expandable for all node types) */}
      {step.reasoning && <ReasoningBlock reasoning={step.reasoning} />}
      {!step.reasoning && step.description && step.description.length > 60 && (
        <ReasoningBlock reasoning={step.description} />
      )}

      {/* Tool calls */}
      {step.toolCalls.map((tc, i) => (
        <ToolCallBlock key={`call-${i}`} call={tc} />
      ))}

      {/* Tool results */}
      {step.toolResults.map((tr, i) => (
        <ToolResultBlock key={`result-${i}`} result={tr} />
      ))}
    </div>
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

      {loop.steps.map((step) => (
        <StepSection key={step.index} step={step} total={loop.totalSteps} loopModel={loop.model} />
      ))}
    </div>
  );
};
