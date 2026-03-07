// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useEffect, useRef } from 'react';
import {
  Button,
  Switch,
  Label,
  Spinner,
} from '@patternfly/react-core';
import {
  CheckCircleIcon,
  ExclamationTriangleIcon,
  ExclamationCircleIcon,
  SyncIcon,
} from '@patternfly/react-icons';
import { sidecarService, type SidecarObservation } from '../services/api';

interface SidecarTabProps {
  namespace: string;
  contextId: string;
  sidecarType: string;
  displayName: string;
  enabled: boolean;
  autoApprove: boolean;
  onToggleEnable: (enabled: boolean) => void;
  onToggleAutoApprove: (auto: boolean) => void;
}

export const SidecarTab: React.FC<SidecarTabProps> = ({
  namespace,
  contextId,
  sidecarType,
  displayName,
  enabled,
  autoApprove,
  onToggleEnable,
  onToggleAutoApprove,
}) => {
  const [observations, setObservations] = useState<SidecarObservation[]>([]);
  const [connecting, setConnecting] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Connect to SSE observation stream when enabled
  useEffect(() => {
    if (!enabled || !contextId) {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      return;
    }

    setConnecting(true);
    const url = sidecarService.observationUrl(namespace, contextId, sidecarType);
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const obs: SidecarObservation = JSON.parse(event.data);
        setObservations((prev) => [...prev, obs]);
      } catch {
        // ignore parse errors
      }
    };

    es.onopen = () => setConnecting(false);
    es.onerror = () => setConnecting(false);

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [enabled, contextId, namespace, sidecarType]);

  // Auto-scroll to bottom on new observations
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

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'critical':
        return <ExclamationCircleIcon style={{ color: 'var(--pf-v5-global--danger-color--100)' }} />;
      case 'warning':
        return <ExclamationTriangleIcon style={{ color: 'var(--pf-v5-global--warning-color--100)' }} />;
      default:
        return <CheckCircleIcon style={{ color: 'var(--pf-v5-global--info-color--100)' }} />;
    }
  };

  const getSeverityLabel = (severity: string) => {
    const colorMap: Record<string, 'red' | 'orange' | 'blue'> = {
      critical: 'red',
      warning: 'orange',
      info: 'blue',
    };
    return (
      <Label color={colorMap[severity] || 'blue'} isCompact>
        {severity}
      </Label>
    );
  };

  return (
    <div
      data-testid="sidecar-tab-content"
      style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
    >
      {/* Header controls */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          padding: '8px 12px',
          borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: '1em' }}>{displayName}</span>
        <Switch
          data-testid="sidecar-enable-switch"
          id={`sidecar-enable-${sidecarType}`}
          label="Enabled"
          isChecked={enabled}
          onChange={(_event, checked) => onToggleEnable(checked)}
        />
        <Switch
          data-testid="sidecar-auto-toggle"
          id={`sidecar-auto-${sidecarType}`}
          label="Auto-approve"
          labelOff="HITL"
          isChecked={autoApprove}
          onChange={(_event, checked) => onToggleAutoApprove(checked)}
          isDisabled={!enabled}
        />
        {connecting && <Spinner size="sm" />}
        {enabled && (
          <Label color="green" isCompact icon={<SyncIcon />}>
            Active
          </Label>
        )}
      </div>

      {/* Observations stream */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px 12px',
        }}
      >
        {observations.length === 0 && enabled && (
          <div
            style={{
              textAlign: 'center',
              padding: 24,
              color: 'var(--pf-v5-global--Color--200)',
            }}
          >
            Waiting for observations...
          </div>
        )}

        {observations.map((obs) => (
          <div
            key={obs.id}
            data-testid="sidecar-observation"
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 8,
              padding: '8px 0',
              borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
              borderLeft: obs.requires_approval
                ? '3px solid var(--pf-v5-global--warning-color--100)'
                : '3px solid transparent',
              paddingLeft: 8,
            }}
          >
            <div style={{ flexShrink: 0, marginTop: 2 }}>
              {getSeverityIcon(obs.severity)}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span
                  style={{
                    fontSize: '0.75em',
                    color: 'var(--pf-v5-global--Color--200)',
                    fontFamily: 'monospace',
                  }}
                >
                  {new Date(obs.timestamp * 1000).toLocaleTimeString()}
                </span>
                {getSeverityLabel(obs.severity)}
              </div>
              <div style={{ fontSize: '0.9em', marginTop: 4 }}>{obs.message}</div>

              {obs.requires_approval && (
                <div
                  data-testid="sidecar-hitl-pending"
                  style={{ marginTop: 8, display: 'flex', gap: 8 }}
                >
                  <Button
                    data-testid="sidecar-approve-btn"
                    variant="primary"
                    isSmall
                    onClick={() => handleApprove(obs.id)}
                  >
                    Approve
                  </Button>
                  <Button
                    data-testid="sidecar-deny-btn"
                    variant="danger"
                    isSmall
                    onClick={() => handleDeny(obs.id)}
                  >
                    Deny
                  </Button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
