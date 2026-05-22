// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import {
  Card,
  CardBody,
  CardTitle,
  Button,
  Label,
  CodeBlock,
  CodeBlockCode,
  Flex,
  FlexItem,
} from '@patternfly/react-core';
import {
  ShieldAltIcon,
  CheckCircleIcon,
  TimesCircleIcon,
} from '@patternfly/react-icons';

export interface HitlApprovalCardProps {
  /** The command or task ID needing approval */
  command: string;
  /** Why approval is needed */
  reason: string;
  /** Callback fired when the user approves */
  onApprove?: () => void;
  /** Callback fired when the user rejects */
  onReject?: () => void;
}

/**
 * Interactive card for Human-in-the-Loop approval requests.
 *
 * Renders a warning-styled card with the command that needs approval,
 * the reason, and Approve / Deny action buttons. Once actioned the
 * buttons are replaced with a status label.
 */
export const HitlApprovalCard: React.FC<HitlApprovalCardProps> = ({
  command,
  reason,
  onApprove,
  onReject,
}) => {
  const [actioned, setActioned] = useState<'approved' | 'denied' | null>(null);

  return (
    <Card
      isCompact
      style={{
        margin: '8px 0',
        borderLeft: '4px solid var(--pf-v5-global--warning-color--100)',
        boxShadow: '0 1px 4px rgba(0,0,0,0.12)',
      }}
    >
      <CardTitle
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '12px 16px 4px',
          fontSize: '0.95em',
          color: 'var(--pf-v5-global--warning-color--200)',
        }}
      >
        <ShieldAltIcon />
        <span style={{ fontWeight: 700 }}>Approval Required</span>
      </CardTitle>

      <CardBody style={{ padding: '4px 16px 12px' }}>
        {/* Command */}
        {command && (
          <div style={{ marginBottom: 8 }}>
            <div
              style={{
                fontSize: '0.8em',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: 4,
                color: 'var(--pf-v5-global--Color--200)',
              }}
            >
              Command
            </div>
            <CodeBlock>
              <CodeBlockCode>{command}</CodeBlockCode>
            </CodeBlock>
          </div>
        )}

        {/* Reason */}
        {reason && (
          <div
            style={{
              fontSize: '0.85em',
              color: 'var(--pf-v5-global--Color--200)',
              marginBottom: 12,
            }}
          >
            {reason}
          </div>
        )}

        {/* Actions / Status */}
        {actioned ? (
          <Label
            color={actioned === 'approved' ? 'green' : 'red'}
            icon={
              actioned === 'approved' ? (
                <CheckCircleIcon />
              ) : (
                <TimesCircleIcon />
              )
            }
          >
            {actioned === 'approved' ? 'Approved' : 'Denied'}
          </Label>
        ) : (
          <Flex>
            <FlexItem>
              <Button
                variant="primary"
                size="sm"
                icon={<CheckCircleIcon />}
                style={{
                  backgroundColor: 'var(--pf-v5-global--success-color--100)',
                }}
                onClick={() => {
                  setActioned('approved');
                  onApprove?.();
                }}
              >
                Approve
              </Button>
            </FlexItem>
            <FlexItem>
              <Button
                variant="danger"
                size="sm"
                icon={<TimesCircleIcon />}
                onClick={() => {
                  setActioned('denied');
                  onReject?.();
                }}
              >
                Deny
              </Button>
            </FlexItem>
          </Flex>
        )}
      </CardBody>
    </Card>
  );
};
