// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useEffect, useRef } from 'react';
import {
  Button,
  Switch,
  Label,
  Spinner,
  Tooltip,
  TextInput,
} from '@patternfly/react-core';
import {
  CheckCircleIcon,
  ExclamationTriangleIcon,
  ExclamationCircleIcon,
  SyncIcon,
  OutlinedQuestionCircleIcon,
} from '@patternfly/react-icons';
import { sidecarService, type SidecarObservation } from '../services/api';

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
  description: string;
  configFields: ConfigField[];
}

const SIDECAR_META: Record<string, SidecarMeta> = {
  looper: {
    name: 'Looper',
    description:
      'Auto-continue kicker. When the agent finishes a turn, Looper sends a "continue" message to keep it working. ' +
      'Tracks iterations and stops at the limit so the agent does not run forever.',
    configFields: [
      {
        key: 'counter_limit',
        label: 'Max iterations',
        help: 'How many times Looper will kick the agent before stopping and asking you to decide.',
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
  },
  hallucination_observer: {
    name: 'Hallucination Observer',
    description:
      'Watches tool outputs for fabricated file paths and "No such file" errors. ' +
      'Alerts you when the agent references files that do not exist in the workspace.',
    configFields: [],
  },
  context_guardian: {
    name: 'Context Guardian',
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
  onToggleEnable,
  onToggleAutoApprove,
  onConfigChange,
  onReset,
}) => {
  const [expanded, setExpanded] = useState(enabled);
  const [observations, setObservations] = useState<SidecarObservation[]>([]);
  const eventSourceRef = useRef<EventSource | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const meta = SIDECAR_META[sidecarType] || {
    name: sidecarType,
    description: 'Sidecar agent',
    configFields: [],
  };

  // SSE observation stream
  useEffect(() => {
    if (!enabled || !contextId) {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      return;
    }

    const url = sidecarService.observationUrl(namespace, contextId, sidecarType);
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const obs: SidecarObservation = JSON.parse(event.data);
        setObservations((prev) => [...prev, obs]);
      } catch {
        // ignore
      }
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [enabled, contextId, namespace, sidecarType]);

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

  return (
    <div
      data-testid={`sidecar-card-${sidecarType}`}
      style={{
        border: '1px solid var(--pf-v5-global--BorderColor--100)',
        borderRadius: 6,
        marginBottom: 8,
        backgroundColor: enabled
          ? 'var(--pf-v5-global--BackgroundColor--100)'
          : 'var(--pf-v5-global--BackgroundColor--200)',
      }}
    >
      {/* Header — always visible */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <span style={{ fontSize: '0.8em' }}>{expanded ? '▼' : '▶'}</span>
        <span style={{ fontWeight: 600, fontSize: '0.9em', flex: 1 }}>{meta.name}</span>
        {enabled && (
          <Label color="green" isCompact icon={<SyncIcon />}>
            Active
          </Label>
        )}
        {observationCount > 0 && (
          <Label color="blue" isCompact>
            {observationCount}
          </Label>
        )}
        {pendingCount > 0 && (
          <Label data-testid="sidecar-hitl-badge" color="orange" isCompact>
            {pendingCount} pending
          </Label>
        )}
      </div>

      {/* Expanded body */}
      {expanded && (
        <div style={{ padding: '0 12px 12px' }}>
          {/* Description */}
          <p
            style={{
              fontSize: '0.8em',
              color: 'var(--pf-v5-global--Color--200)',
              margin: '0 0 8px',
              lineHeight: 1.4,
            }}
          >
            {meta.description}
          </p>

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
        <HelpTip text="Sidecar agents run alongside your session. They observe what the agent is doing and can intervene — kick it to continue, detect hallucinations, or warn about context usage." />
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
