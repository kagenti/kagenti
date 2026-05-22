// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Button,
  Switch,
  Label,
  Spinner,
  Tooltip,
  TextInput,
  Progress,
  ProgressMeasureLocation,
  ProgressVariant,
} from '@patternfly/react-core';
import {
  CheckCircleIcon,
  ExclamationTriangleIcon,
  ExclamationCircleIcon,
  SyncAltIcon,
  EyeIcon,
  ChartBarIcon,
  OutlinedQuestionCircleIcon,
} from '@patternfly/react-icons';
import { sidecarService, type SidecarObservation } from '../services/api';
import { useAuth } from '@/contexts/AuthContext';

// ---------------------------------------------------------------------------
// Sidecar descriptions and config metadata
// ---------------------------------------------------------------------------

interface ConfigField {
  key: string;
  label: string;
  help: string;
  type: 'number';
  defaultValue: number;
}

interface SidecarMeta {
  name: string;
  shortName: string;
  description: string;
  configFields: ConfigField[];
  icon: React.ReactNode;
}

const SIDECAR_META: Record<string, SidecarMeta> = {
  looper: {
    name: 'Looper',
    shortName: 'Looper',
    description:
      'Auto-continue agent. When the agent finishes a turn, Looper sends a "continue" message to keep it working. ' +
      'Tracks iterations and stops at the limit so the agent does not run forever.',
    configFields: [
      {
        key: 'counter_limit',
        label: 'Max iterations',
        help: 'How many times Looper will auto-continue the agent before stopping and asking you to decide.',
        type: 'number',
        defaultValue: 5,
      },
      {
        key: 'interval_seconds',
        label: 'Check interval (sec)',
        help: 'How often Looper checks whether the agent has finished a turn. Lower = faster reaction, higher = less overhead.',
        type: 'number',
        defaultValue: 10,
      },
    ],
    icon: <SyncAltIcon style={{ color: 'var(--pf-v5-global--info-color--100)' }} />,
  },
  hallucination_observer: {
    name: 'Hallucination Observer',
    shortName: 'Hallucination',
    description:
      'Watches tool outputs for fabricated file paths and "No such file" errors. ' +
      'Alerts you when the agent references files that do not exist in the workspace.',
    configFields: [],
    icon: <EyeIcon style={{ color: 'var(--pf-v5-global--warning-color--100)' }} />,
  },
  context_guardian: {
    name: 'Context Guardian',
    shortName: 'Context',
    description:
      'Tracks how much context the agent is consuming. Warns when token usage crosses thresholds ' +
      'so you can intervene before the context window fills up.',
    configFields: [
      {
        key: 'warn_threshold_pct',
        label: 'Warning at (%)',
        help: 'Emit a warning observation when estimated context usage crosses this percentage.',
        type: 'number',
        defaultValue: 60,
      },
      {
        key: 'critical_threshold_pct',
        label: 'Critical at (%)',
        help: 'Emit a critical alert (with approval prompt) when context usage crosses this percentage.',
        type: 'number',
        defaultValue: 80,
      },
    ],
    icon: <ChartBarIcon style={{ color: 'var(--pf-v5-global--palette--purple-400, #6753ac)' }} />,
  },
};

// ---------------------------------------------------------------------------
// Tooltip helper
// ---------------------------------------------------------------------------

const HelpTip: React.FC<{ text: string }> = ({ text }) => (
  <Tooltip content={text}>
    <OutlinedQuestionCircleIcon
      style={{
        color: 'var(--pf-v5-global--Color--200)',
        cursor: 'help',
        marginLeft: 4,
        fontSize: '0.85em',
      }}
    />
  </Tooltip>
);

// ---------------------------------------------------------------------------
// Parse current iteration from observations for Looper
// ---------------------------------------------------------------------------

function parseLooperIteration(observations: SidecarObservation[]): number {
  // Walk backwards to find the latest "Iteration X/Y" message
  for (let i = observations.length - 1; i >= 0; i--) {
    const msg = observations[i].message;
    const match = msg.match(/Iteration\s+(\d+)/i);
    if (match) {
      return parseInt(match[1], 10);
    }
  }
  return 0;
}

// ---------------------------------------------------------------------------
// SidecarCard — one card per sidecar in the right panel
// ---------------------------------------------------------------------------

interface SidecarCardProps {
  namespace: string;
  contextId: string;
  sidecarType: string;
  enabled: boolean;
  autoApprove: boolean;
  config: Record<string, unknown>;
  observationCount: number;
  pendingCount: number;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onToggleEnable: (enabled: boolean) => void;
  onToggleAutoApprove: (auto: boolean) => void;
  onConfigChange: (key: string, value: unknown) => void;
  onReset: () => void;
}

export const SidecarCard: React.FC<SidecarCardProps> = ({
  namespace,
  contextId,
  sidecarType,
  enabled,
  autoApprove,
  config,
  observationCount,
  pendingCount,
  isExpanded,
  onToggleExpand,
  onToggleEnable,
  onToggleAutoApprove,
  onConfigChange,
  onReset,
}) => {
  const [observations, setObservations] = useState<SidecarObservation[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { getToken } = useAuth();

  const meta = SIDECAR_META[sidecarType] || {
    name: sidecarType,
    shortName: sidecarType,
    description: 'Sidecar agent',
    configFields: [],
    icon: <SyncAltIcon />,
  };

  // SSE observation stream via fetch + ReadableStream (supports auth headers)
  useEffect(() => {
    if (!enabled || !contextId) {
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;

    const connectSSE = async () => {
      try {
        const token = await getToken();
        const headers: Record<string, string> = {
          'Accept': 'text/event-stream',
        };
        if (token) {
          headers['Authorization'] = `Bearer ${token}`;
        }

        const url = sidecarService.observationUrl(namespace, contextId, sidecarType);
        const response = await fetch(url, {
          headers,
          signal: controller.signal,
        });

        if (!response.ok) {
          console.error(`Sidecar SSE error: ${response.status}`);
          return;
        }

        const reader = response.body?.getReader();
        if (!reader) return;

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          // Keep the last incomplete line in the buffer
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6).trim();
              if (!data || data === '[DONE]') continue;
              try {
                const obs: SidecarObservation = JSON.parse(data);
                setObservations((prev) => [...prev, obs]);
              } catch {
                // ignore malformed data
              }
            }
          }
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          // Expected on cleanup
          return;
        }
        console.error('Sidecar SSE connection error:', err);
      }
    };

    connectSSE();

    return () => {
      controller.abort();
      abortRef.current = null;
    };
  }, [enabled, contextId, namespace, sidecarType, getToken]);

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [observations]);

  const handleApprove = async (obsId: string) => {
    await sidecarService.approve(namespace, contextId, sidecarType, obsId);
    setObservations((prev) =>
      prev.map((o) => (o.id === obsId ? { ...o, requires_approval: false } : o))
    );
  };

  const handleDeny = async (obsId: string) => {
    await sidecarService.deny(namespace, contextId, sidecarType, obsId);
    setObservations((prev) => prev.filter((o) => o.id !== obsId));
  };

  // Looper iteration tracking
  const counterLimit = (config.counter_limit as number) ?? 5;
  const currentIteration = useMemo(() => parseLooperIteration(observations), [observations]);
  const iterationPct = counterLimit > 0 ? Math.round((currentIteration / counterLimit) * 100) : 0;

  // ---- Compact metric for the collapsed row ----
  const compactMetric = () => {
    if (sidecarType === 'looper' && enabled) {
      return (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontSize: '0.8em',
            fontFamily: 'monospace',
            color: 'var(--pf-v5-global--Color--100)',
          }}
        >
          <span>{currentIteration}/{counterLimit}</span>
          <span
            style={{
              display: 'inline-block',
              width: 32,
              height: 6,
              borderRadius: 3,
              backgroundColor: 'var(--pf-v5-global--BorderColor--100)',
              overflow: 'hidden',
              position: 'relative',
            }}
          >
            <span
              style={{
                display: 'block',
                height: '100%',
                width: `${iterationPct}%`,
                borderRadius: 3,
                backgroundColor: 'var(--pf-v5-global--success-color--100)',
                transition: 'width 0.3s ease',
              }}
            />
          </span>
        </span>
      );
    }

    // For non-looper sidecars, show observation count
    return (
      <span
        style={{
          fontSize: '0.8em',
          fontFamily: 'monospace',
          color: 'var(--pf-v5-global--Color--200)',
        }}
      >
        {observationCount} obs
      </span>
    );
  };

  // ---- Status dot ----
  const statusDot = (
    <span
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        backgroundColor: enabled
          ? 'var(--pf-v5-global--success-color--100)'
          : 'var(--pf-v5-global--Color--200)',
        flexShrink: 0,
      }}
    />
  );

  return (
    <div
      data-testid={`sidecar-card-${sidecarType}`}
      style={{
        border: '1px solid var(--pf-v5-global--BorderColor--100)',
        borderRadius: 6,
        marginBottom: 4,
        backgroundColor: enabled
          ? 'var(--pf-v5-global--BackgroundColor--100)'
          : 'var(--pf-v5-global--BackgroundColor--200)',
        transition: 'background-color 0.15s ease',
      }}
    >
      {/* Compact row — always visible */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 8px',
          cursor: 'pointer',
          borderRadius: isExpanded ? '6px 6px 0 0' : 6,
          transition: 'background-color 0.1s ease',
        }}
        onClick={onToggleExpand}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLDivElement).style.backgroundColor =
            'var(--pf-v5-global--BackgroundColor--200)';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLDivElement).style.backgroundColor = 'transparent';
        }}
      >
        {/* Icon */}
        <span style={{ fontSize: '0.95em', flexShrink: 0, display: 'flex', alignItems: 'center' }}>
          {meta.icon}
        </span>

        {/* Name */}
        <span style={{ fontWeight: 600, fontSize: '0.85em', flex: 1, whiteSpace: 'nowrap' }}>
          {meta.shortName}
        </span>

        {/* Metric */}
        {compactMetric()}

        {/* Status dot */}
        <Tooltip content={enabled ? 'Active' : 'Disabled'}>
          <span style={{ display: 'flex', alignItems: 'center' }}>{statusDot}</span>
        </Tooltip>

        {/* Pending badge */}
        {pendingCount > 0 && (
          <Label data-testid="sidecar-hitl-badge" color="orange" isCompact>
            {pendingCount}
          </Label>
        )}

        {/* Expand arrow */}
        <span
          style={{
            fontSize: '0.75em',
            color: 'var(--pf-v5-global--Color--200)',
            flexShrink: 0,
            transition: 'transform 0.15s ease',
            transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
          }}
        >
          &#9656;
        </span>
      </div>

      {/* Expanded body */}
      {isExpanded && (
        <div style={{ padding: '0 12px 12px', borderTop: '1px solid var(--pf-v5-global--BorderColor--100)' }}>
          {/* Description */}
          <p
            style={{
              fontSize: '0.8em',
              color: 'var(--pf-v5-global--Color--200)',
              margin: '8px 0 8px',
              lineHeight: 1.4,
            }}
          >
            {meta.description}
          </p>

          {/* Looper progress (expanded view) */}
          {sidecarType === 'looper' && enabled && currentIteration > 0 && (
            <div style={{ marginBottom: 8 }}>
              <Progress
                value={iterationPct}
                title={`Iteration ${currentIteration} of ${counterLimit} (${iterationPct}%)`}
                measureLocation={ProgressMeasureLocation.outside}
                variant={iterationPct >= 80 ? ProgressVariant.warning : undefined}
                style={{ fontSize: '0.8em' }}
              />
            </div>
          )}

          {/* Controls */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              marginBottom: 8,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Switch
                data-testid="sidecar-enable-switch"
                id={`sidecar-enable-${sidecarType}`}
                label="On"
                labelOff="Off"
                isChecked={enabled}
                onChange={(_event, checked) => onToggleEnable(checked)}
              />
              <HelpTip text="Turn this sidecar on or off for the current session." />
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Switch
                data-testid="sidecar-auto-toggle"
                id={`sidecar-auto-${sidecarType}`}
                label="Auto-approve"
                labelOff="Review first"
                isChecked={autoApprove}
                onChange={(_event, checked) => onToggleAutoApprove(checked)}
                isDisabled={!enabled}
              />
              <HelpTip text="Auto-approve: sidecar acts immediately without asking. Review first: sidecar shows a pending approval before acting." />
            </div>
          </div>

          {/* Config fields */}
          {meta.configFields.length > 0 && enabled && (
            <div
              style={{
                borderTop: '1px solid var(--pf-v5-global--BorderColor--100)',
                paddingTop: 8,
                marginBottom: 8,
              }}
            >
              <div style={{ fontSize: '0.8em', fontWeight: 600, marginBottom: 6 }}>Settings</div>
              {meta.configFields.map((field) => (
                <div
                  key={field.key}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    marginBottom: 6,
                  }}
                >
                  <span style={{ fontSize: '0.8em', minWidth: 110 }}>
                    {field.label}
                    <HelpTip text={field.help} />
                  </span>
                  <TextInput
                    type="number"
                    value={String((config[field.key] as number) ?? field.defaultValue)}
                    onChange={(_event, val) => onConfigChange(field.key, Number(val))}
                    style={{ width: 80, fontSize: '0.85em' }}
                    isDisabled={!enabled}
                  />
                </div>
              ))}
            </div>
          )}

          {/* Reset button (Looper) */}
          {sidecarType === 'looper' && enabled && (
            <Button
              variant="link"
              size="sm"
              onClick={onReset}
              style={{ fontSize: '0.8em', padding: 0 }}
            >
              Reset counter
            </Button>
          )}

          {/* Observation stream */}
          {enabled && observations.length > 0 && (
            <div
              ref={scrollRef}
              data-testid="sidecar-tab-content"
              style={{
                borderTop: '1px solid var(--pf-v5-global--BorderColor--100)',
                marginTop: 8,
                paddingTop: 8,
                maxHeight: 200,
                overflowY: 'auto',
              }}
            >
              {observations.map((obs) => (
                <div
                  key={obs.id}
                  data-testid="sidecar-observation"
                  style={{
                    fontSize: '0.8em',
                    padding: '4px 0',
                    borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
                    borderLeft: obs.requires_approval
                      ? '3px solid var(--pf-v5-global--warning-color--100)'
                      : '3px solid transparent',
                    paddingLeft: 6,
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 6,
                  }}
                >
                  {obs.severity === 'critical' ? (
                    <ExclamationCircleIcon
                      style={{ color: 'var(--pf-v5-global--danger-color--100)', flexShrink: 0, marginTop: 2 }}
                    />
                  ) : obs.severity === 'warning' ? (
                    <ExclamationTriangleIcon
                      style={{ color: 'var(--pf-v5-global--warning-color--100)', flexShrink: 0, marginTop: 2 }}
                    />
                  ) : (
                    <CheckCircleIcon
                      style={{ color: 'var(--pf-v5-global--info-color--100)', flexShrink: 0, marginTop: 2 }}
                    />
                  )}
                  <div style={{ flex: 1 }}>
                    <span style={{ fontFamily: 'monospace', color: 'var(--pf-v5-global--Color--200)', fontSize: '0.9em' }}>
                      {new Date(obs.timestamp * 1000).toLocaleTimeString()}
                    </span>{' '}
                    {obs.message}
                    {obs.requires_approval && (
                      <div data-testid="sidecar-hitl-pending" style={{ marginTop: 4, display: 'flex', gap: 6 }}>
                        <Button data-testid="sidecar-approve-btn" variant="primary" size="sm" onClick={() => handleApprove(obs.id)}>
                          Approve
                        </Button>
                        <Button data-testid="sidecar-deny-btn" variant="danger" size="sm" onClick={() => handleDeny(obs.id)}>
                          Deny
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {enabled && observations.length === 0 && (
            <div
              style={{
                fontSize: '0.8em',
                color: 'var(--pf-v5-global--Color--200)',
                textAlign: 'center',
                padding: '8px 0',
                borderTop: '1px solid var(--pf-v5-global--BorderColor--100)',
                marginTop: 8,
              }}
            >
              <Spinner size="sm" /> Waiting for activity...
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// SidecarPanel — right panel containing all sidecar cards
// ---------------------------------------------------------------------------

interface SidecarPanelProps {
  namespace: string;
  contextId: string;
  sidecars: Array<{
    sidecar_type: string;
    enabled: boolean;
    auto_approve: boolean;
    config: Record<string, unknown>;
    observation_count: number;
    pending_count: number;
  }>;
  onToggleEnable: (type: string, enabled: boolean) => void;
  onToggleAutoApprove: (type: string, auto: boolean) => void;
  onConfigChange: (type: string, key: string, value: unknown) => void;
  onReset: (type: string) => void;
}

const SIDECAR_ORDER = ['looper', 'hallucination_observer', 'context_guardian'];

export const SidecarPanel: React.FC<SidecarPanelProps> = ({
  namespace,
  contextId,
  sidecars,
  onToggleEnable,
  onToggleAutoApprove,
  onConfigChange,
  onReset,
}) => {
  const [expandedSidecar, setExpandedSidecar] = useState<string | null>(null);

  const handleToggleExpand = (type: string) => {
    setExpandedSidecar((prev) => (prev === type ? null : type));
  };

  return (
    <div
      data-testid="sidecar-panel"
      style={{
        padding: '8px',
        height: '100%',
        overflowY: 'auto',
      }}
    >
      <div
        style={{
          fontSize: '0.85em',
          fontWeight: 600,
          marginBottom: 8,
          display: 'flex',
          alignItems: 'center',
          gap: 4,
        }}
      >
        Sidecar Agents
        <HelpTip text="Sidecar agents run alongside your session. They observe what the agent is doing and can intervene — auto-continue it, detect hallucinations, or warn about context usage." />
      </div>

      {SIDECAR_ORDER.map((type) => {
        const sc = sidecars.find((s) => s.sidecar_type === type);
        return (
          <SidecarCard
            key={type}
            namespace={namespace}
            contextId={contextId}
            sidecarType={type}
            enabled={sc?.enabled ?? false}
            autoApprove={sc?.auto_approve ?? false}
            config={(sc?.config as Record<string, unknown>) ?? {}}
            observationCount={sc?.observation_count ?? 0}
            pendingCount={sc?.pending_count ?? 0}
            isExpanded={expandedSidecar === type}
            onToggleExpand={() => handleToggleExpand(type)}
            onToggleEnable={(enabled) => onToggleEnable(type, enabled)}
            onToggleAutoApprove={(auto) => onToggleAutoApprove(type, auto)}
            onConfigChange={(key, val) => onConfigChange(type, key, val)}
            onReset={() => onReset(type)}
          />
        );
      })}
    </div>
  );
};
