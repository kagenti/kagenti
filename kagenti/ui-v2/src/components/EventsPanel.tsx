// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useEffect, useRef } from 'react';
import {
  ExpandableSection,
  Label,
  Button,
  Spinner,
} from '@patternfly/react-core';
import {
  CheckCircleIcon,
  ExclamationCircleIcon,
  CubeIcon,
  OutlinedClockIcon,
} from '@patternfly/react-icons';

export interface A2AEvent {
  id: string;
  timestamp: Date;
  type: 'status' | 'artifact' | 'error';
  taskId?: string;
  state?: string;
  message?: string;
  artifactName?: string;
  artifactContent?: string;
  final?: boolean;
}

interface EventsPanelProps {
  events: A2AEvent[];
  isComplete: boolean;
  defaultExpanded?: boolean;
}

const ARTIFACT_TRUNCATE_LENGTH = 500;

export const EventsPanel: React.FC<EventsPanelProps> = ({
  events,
  isComplete,
  defaultExpanded = true,
}) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [expandedArtifacts, setExpandedArtifacts] = useState<Record<string, boolean>>({});
  const prevIsComplete = useRef(isComplete);
  const prevEventsLength = useRef(events.length);

  // Auto-collapse when isComplete changes from false to true OR when an artifact arrives
  useEffect(() => {
    const hasArtifact = events.some(e => e.type === 'artifact');
    const newArtifact = events.length > prevEventsLength.current && hasArtifact;
    
    if ((!prevIsComplete.current && isComplete) || newArtifact) {
      // Small delay for visual feedback before collapsing
      const timer = setTimeout(() => {
        setIsExpanded(false);
      }, 800);
      prevEventsLength.current = events.length;
      return () => clearTimeout(timer);
    }
    prevIsComplete.current = isComplete;
    prevEventsLength.current = events.length;
  }, [isComplete, events]);

  if (events.length === 0) {
    return null;
  }

  const getEventIcon = (event: A2AEvent) => {
    if (event.type === 'artifact') {
      return <CubeIcon style={{ color: 'var(--pf-v5-global--palette--purple-400)' }} />;
    }
    if (event.type === 'error' || event.state === 'FAILED') {
      return <ExclamationCircleIcon style={{ color: 'var(--pf-v5-global--danger-color--100)' }} />;
    }
    if (event.state === 'COMPLETED') {
      return <CheckCircleIcon style={{ color: 'var(--pf-v5-global--success-color--100)' }} />;
    }
    if (event.state === 'WORKING') {
      return <Spinner size="sm" style={{ marginRight: '4px' }} />;
    }
    // SUBMITTED or other states
    return <OutlinedClockIcon style={{ color: 'var(--pf-v5-global--info-color--100)' }} />;
  };

  const getEventLabel = (event: A2AEvent) => {
    if (event.type === 'artifact') {
      return (
        <Label color="purple" isCompact>
          Artifact
        </Label>
      );
    }
    if (event.state === 'COMPLETED') {
      return (
        <Label color="green" isCompact>
          Completed
        </Label>
      );
    }
    if (event.state === 'FAILED') {
      return (
        <Label color="red" isCompact>
          Failed
        </Label>
      );
    }
    if (event.state === 'WORKING') {
      return (
        <Label color="blue" isCompact>
          Working
        </Label>
      );
    }
    if (event.state === 'SUBMITTED') {
      return (
        <Label color="blue" isCompact>
          Submitted
        </Label>
      );
    }
    return (
      <Label isCompact>
        {event.state || event.type}
      </Label>
    );
  };

  const getEventDescription = (event: A2AEvent) => {
    if (event.type === 'artifact') {
      return event.artifactName || 'Intermediate output';
    }
    if (event.message) {
      return event.message;
    }
    switch (event.state) {
      case 'SUBMITTED':
        return 'Task received';
      case 'WORKING':
        return 'Processing...';
      case 'COMPLETED':
        return 'Task completed';
      case 'FAILED':
        return 'Task failed';
      default:
        return '';
    }
  };

  const toggleArtifact = (eventId: string) => {
    setExpandedArtifacts((prev) => ({
      ...prev,
      [eventId]: !prev[eventId],
    }));
  };

  const formatTimestamp = (date: Date) => {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  return (
    <>
      <style>
        {`
          .events-panel-container {
            transition: all 0.3s ease-out;
          }
          .events-panel-container .pf-v5-c-expandable-section__content {
            transition: max-height 0.3s ease-out, opacity 0.2s ease-out;
          }
          @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-4px); }
            to { opacity: 1; transform: translateY(0); }
          }
          .event-item {
            animation: fadeIn 0.2s ease-out;
          }
        `}
      </style>
      <ExpandableSection
        toggleText={`Events (${events.length})`}
        isExpanded={isExpanded}
        onToggle={() => setIsExpanded(!isExpanded)}
        className="events-panel-container"
        style={{
          marginBottom: '12px',
          backgroundColor: 'var(--pf-v5-global--BackgroundColor--100)',
          borderRadius: '4px',
          border: '1px solid var(--pf-v5-global--BorderColor--100)',
        }}
      >
      <div
        style={{
          maxHeight: '200px',
          overflowY: 'auto',
          overflowX: 'auto',
          padding: '8px 12px',
        }}
      >
        {events.map((event) => (
          <div
            key={event.id}
            className="event-item"
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '8px',
              padding: '6px 0',
              borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
            }}
          >
            <div style={{ flexShrink: 0, marginTop: '2px' }}>
              {getEventIcon(event)}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  flexWrap: 'wrap',
                }}
              >
                <span
                  style={{
                    fontSize: '0.75em',
                    color: 'var(--pf-v5-global--Color--200)',
                    fontFamily: 'monospace',
                  }}
                >
                  {formatTimestamp(event.timestamp)}
                </span>
                {getEventLabel(event)}
                <span style={{ fontSize: '0.9em', whiteSpace: 'nowrap' }}>
                  {getEventDescription(event)}
                </span>
              </div>
              {/* Artifact content (truncated with expand) */}
              {event.type === 'artifact' && event.artifactContent && (
                <div style={{ marginTop: '4px' }}>
                  <pre
                    style={{
                      backgroundColor: 'var(--pf-v5-global--BackgroundColor--100)',
                      padding: '8px',
                      borderRadius: '4px',
                      fontSize: '0.8em',
                      margin: 0,
                      overflow: 'auto',
                      maxHeight: expandedArtifacts[event.id] ? '300px' : '60px',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                    }}
                  >
                    {expandedArtifacts[event.id]
                      ? event.artifactContent
                      : event.artifactContent.length > ARTIFACT_TRUNCATE_LENGTH
                        ? `${event.artifactContent.substring(0, ARTIFACT_TRUNCATE_LENGTH)}...`
                        : event.artifactContent}
                  </pre>
                  {event.artifactContent.length > ARTIFACT_TRUNCATE_LENGTH && (
                    <Button
                      variant="link"
                      isInline
                      onClick={() => toggleArtifact(event.id)}
                      style={{ fontSize: '0.8em', padding: '4px 0' }}
                    >
                      {expandedArtifacts[event.id] ? 'Show less' : 'Show more'}
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </ExpandableSection>
    </>
  );
};
