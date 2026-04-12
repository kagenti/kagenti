// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import {
  PageSection,
  Title,
  TextContent,
  Text,
  Card,
  CardBody,
  Form,
  FormGroup,
  TextInput,
  FormSelect,
  FormSelectOption,
  NumberInput,
  Button,
  Alert,
  ActionGroup,
  FormHelperText,
  HelperText,
  HelperTextItem,
  Tabs,
  Tab,
  TabTitleText,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
} from '@patternfly/react-core';
import { useMutation } from '@tanstack/react-query';

import { triggerService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';

// Webhook event options
const WEBHOOK_EVENTS = ['pull_request', 'push', 'issue_comment', 'check_suite'];

// Alert severity options
const ALERT_SEVERITIES = ['info', 'warning', 'critical'];

export const TriggerManagementPage: React.FC = () => {
  const [namespace, setNamespace] = useState('team1');
  const [activeTabKey, setActiveTabKey] = useState<number>(0);

  // Cron form state
  const [cronSkill, setCronSkill] = useState('');
  const [cronSchedule, setCronSchedule] = useState('');
  const [cronTtl, setCronTtl] = useState(2);

  // Webhook form state
  const [webhookEvent, setWebhookEvent] = useState('pull_request');
  const [webhookRepo, setWebhookRepo] = useState('');
  const [webhookBranch, setWebhookBranch] = useState('main');
  const [webhookPrNumber, setWebhookPrNumber] = useState<number | undefined>(undefined);
  const [webhookTtl, setWebhookTtl] = useState(2);

  // Alert form state
  const [alertName, setAlertName] = useState('');
  const [alertCluster, setAlertCluster] = useState('');
  const [alertSeverity, setAlertSeverity] = useState('warning');
  const [alertTtl, setAlertTtl] = useState(2);

  // Success/error state
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof triggerService.create>[0]) =>
      triggerService.create(data),
    onSuccess: (result) => {
      setSuccessMessage(
        `Trigger created successfully. SandboxClaim: ${result.sandbox_claim}`
      );
    },
  });

  const handleCronSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSuccessMessage(null);
    createMutation.mutate({
      type: 'cron',
      skill: cronSkill,
      schedule: cronSchedule || undefined,
      namespace,
      ttl_hours: cronTtl,
    });
  };

  const handleWebhookSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSuccessMessage(null);
    createMutation.mutate({
      type: 'webhook',
      event: webhookEvent,
      repo: webhookRepo,
      branch: webhookBranch,
      pr_number: webhookPrNumber,
      namespace,
      ttl_hours: webhookTtl,
    });
  };

  const handleAlertSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSuccessMessage(null);
    createMutation.mutate({
      type: 'alert',
      alert: alertName,
      cluster: alertCluster || undefined,
      severity: alertSeverity,
      namespace,
      ttl_hours: alertTtl,
    });
  };

  const renderCronTab = () => (
    <Card>
      <CardBody>
        <Form onSubmit={handleCronSubmit}>
          <FormGroup label="Skill name" isRequired fieldId="cron-skill">
            <TextInput
              id="cron-skill"
              value={cronSkill}
              onChange={(_event, value) => setCronSkill(value)}
              placeholder="tdd:ci"
              isRequired
            />
          </FormGroup>

          <FormGroup label="Schedule" fieldId="cron-schedule">
            <TextInput
              id="cron-schedule"
              value={cronSchedule}
              onChange={(_event, value) => setCronSchedule(value)}
              placeholder="0 2 * * *"
            />
            <FormHelperText>
              <HelperText>
                <HelperTextItem>Cron expression</HelperTextItem>
              </HelperText>
            </FormHelperText>
          </FormGroup>

          <FormGroup label="TTL Hours" fieldId="cron-ttl">
            <NumberInput
              id="cron-ttl"
              value={cronTtl}
              min={1}
              max={168}
              onMinus={() => setCronTtl(Math.max(1, cronTtl - 1))}
              onPlus={() => setCronTtl(Math.min(168, cronTtl + 1))}
              onChange={(event) => {
                const val = Number((event.target as HTMLInputElement).value);
                if (!isNaN(val)) setCronTtl(Math.max(1, Math.min(168, val)));
              }}
              widthChars={5}
            />
          </FormGroup>

          <ActionGroup>
            <Button
              variant="primary"
              type="submit"
              isLoading={createMutation.isPending}
              isDisabled={createMutation.isPending || !cronSkill.trim()}
            >
              Create Trigger
            </Button>
          </ActionGroup>
        </Form>
      </CardBody>
    </Card>
  );

  const renderWebhookTab = () => (
    <Card>
      <CardBody>
        <Form onSubmit={handleWebhookSubmit}>
          <FormGroup label="Event type" isRequired fieldId="webhook-event">
            <FormSelect
              id="webhook-event"
              value={webhookEvent}
              onChange={(_event, value) => setWebhookEvent(value)}
            >
              {WEBHOOK_EVENTS.map((evt) => (
                <FormSelectOption key={evt} value={evt} label={evt} />
              ))}
            </FormSelect>
          </FormGroup>

          <FormGroup label="Repository URL" isRequired fieldId="webhook-repo">
            <TextInput
              id="webhook-repo"
              value={webhookRepo}
              onChange={(_event, value) => setWebhookRepo(value)}
              placeholder="https://github.com/org/repo"
              isRequired
            />
          </FormGroup>

          <FormGroup label="Branch" fieldId="webhook-branch">
            <TextInput
              id="webhook-branch"
              value={webhookBranch}
              onChange={(_event, value) => setWebhookBranch(value)}
              placeholder="main"
            />
          </FormGroup>

          <FormGroup label="PR Number" fieldId="webhook-pr-number">
            <NumberInput
              id="webhook-pr-number"
              value={webhookPrNumber ?? 0}
              min={0}
              onMinus={() => setWebhookPrNumber(Math.max(0, (webhookPrNumber ?? 0) - 1))}
              onPlus={() => setWebhookPrNumber((webhookPrNumber ?? 0) + 1)}
              onChange={(event) => {
                const val = Number((event.target as HTMLInputElement).value);
                if (!isNaN(val)) setWebhookPrNumber(val > 0 ? val : undefined);
              }}
              widthChars={5}
            />
          </FormGroup>

          <FormGroup label="TTL Hours" fieldId="webhook-ttl">
            <NumberInput
              id="webhook-ttl"
              value={webhookTtl}
              min={1}
              max={168}
              onMinus={() => setWebhookTtl(Math.max(1, webhookTtl - 1))}
              onPlus={() => setWebhookTtl(Math.min(168, webhookTtl + 1))}
              onChange={(event) => {
                const val = Number((event.target as HTMLInputElement).value);
                if (!isNaN(val)) setWebhookTtl(Math.max(1, Math.min(168, val)));
              }}
              widthChars={5}
            />
          </FormGroup>

          <ActionGroup>
            <Button
              variant="primary"
              type="submit"
              isLoading={createMutation.isPending}
              isDisabled={createMutation.isPending || !webhookRepo.trim()}
            >
              Create Trigger
            </Button>
          </ActionGroup>
        </Form>
      </CardBody>
    </Card>
  );

  const renderAlertTab = () => (
    <Card>
      <CardBody>
        <Form onSubmit={handleAlertSubmit}>
          <FormGroup label="Alert name" isRequired fieldId="alert-name">
            <TextInput
              id="alert-name"
              value={alertName}
              onChange={(_event, value) => setAlertName(value)}
              placeholder="HighCPUUsage"
              isRequired
            />
          </FormGroup>

          <FormGroup label="Cluster" fieldId="alert-cluster">
            <TextInput
              id="alert-cluster"
              value={alertCluster}
              onChange={(_event, value) => setAlertCluster(value)}
              placeholder="production-cluster"
            />
          </FormGroup>

          <FormGroup label="Severity" fieldId="alert-severity">
            <FormSelect
              id="alert-severity"
              value={alertSeverity}
              onChange={(_event, value) => setAlertSeverity(value)}
            >
              {ALERT_SEVERITIES.map((sev) => (
                <FormSelectOption key={sev} value={sev} label={sev} />
              ))}
            </FormSelect>
          </FormGroup>

          <FormGroup label="TTL Hours" fieldId="alert-ttl">
            <NumberInput
              id="alert-ttl"
              value={alertTtl}
              min={1}
              max={168}
              onMinus={() => setAlertTtl(Math.max(1, alertTtl - 1))}
              onPlus={() => setAlertTtl(Math.min(168, alertTtl + 1))}
              onChange={(event) => {
                const val = Number((event.target as HTMLInputElement).value);
                if (!isNaN(val)) setAlertTtl(Math.max(1, Math.min(168, val)));
              }}
              widthChars={5}
            />
          </FormGroup>

          <ActionGroup>
            <Button
              variant="primary"
              type="submit"
              isLoading={createMutation.isPending}
              isDisabled={createMutation.isPending || !alertName.trim()}
            >
              Create Trigger
            </Button>
          </ActionGroup>
        </Form>
      </CardBody>
    </Card>
  );

  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">Triggers</Title>
          <Text component="p">
            Create sandbox triggers from cron schedules, webhook events, or alerts.
          </Text>
        </TextContent>
      </PageSection>

      <PageSection variant="light" padding={{ default: 'noPadding' }}>
        <Toolbar>
          <ToolbarContent>
            <ToolbarItem>
              <NamespaceSelector
                namespace={namespace}
                onNamespaceChange={setNamespace}
              />
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </PageSection>

      <PageSection>
        {successMessage && (
          <Alert
            variant="success"
            title="Trigger created"
            isInline
            style={{ marginBottom: '16px' }}
          >
            {successMessage}
          </Alert>
        )}

        {createMutation.isError && (
          <Alert
            variant="danger"
            title="Failed to create trigger"
            isInline
            style={{ marginBottom: '16px' }}
          >
            {createMutation.error instanceof Error
              ? createMutation.error.message
              : 'An unexpected error occurred'}
          </Alert>
        )}

        <Tabs
          activeKey={activeTabKey}
          onSelect={(_event, tabIndex) => setActiveTabKey(tabIndex as number)}
          aria-label="Trigger type tabs"
        >
          <Tab eventKey={0} title={<TabTitleText>Cron</TabTitleText>}>
            {renderCronTab()}
          </Tab>
          <Tab eventKey={1} title={<TabTitleText>Webhook</TabTitleText>}>
            {renderWebhookTab()}
          </Tab>
          <Tab eventKey={2} title={<TabTitleText>Alert</TabTitleText>}>
            {renderAlertTab()}
          </Tab>
        </Tabs>
      </PageSection>
    </>
  );
};
