// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PageSection,
  Title,
  Text,
  TextContent,
  Card,
  CardTitle,
  CardBody,
  Form,
  FormGroup,
  TextInput,
  FormSelect,
  FormSelectOption,
  Button,
  Alert,
  Split,
  SplitItem,
  ExpandableSection,
  ActionGroup,
  FormHelperText,
  HelperText,
  HelperTextItem,
  Checkbox,
} from '@patternfly/react-core';
import { TrashIcon, PlusCircleIcon } from '@patternfly/react-icons';
import { useMutation } from '@tanstack/react-query';

import { integrationService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';
import type { IntegrationProvider, IntegrationAgentRef } from '@/types';

// Webhook event options
const WEBHOOK_EVENTS = ['pull_request', 'push', 'issue_comment', 'check_suite'];

// Alert source options
const ALERT_SOURCES: Array<{ value: 'prometheus' | 'pagerduty'; label: string }> = [
  { value: 'prometheus', label: 'Prometheus' },
  { value: 'pagerduty', label: 'PagerDuty' },
];

interface ScheduleEntry {
  name: string;
  cron: string;
  skill: string;
  agent: string;
}

interface AlertEntry {
  name: string;
  source: 'prometheus' | 'pagerduty';
  agent: string;
}

export const AddIntegrationPage: React.FC = () => {
  const navigate = useNavigate();

  // Card 1: Repository
  const [namespace, setNamespace] = useState('team1');
  const [name, setName] = useState('');
  const [repoUrl, setRepoUrl] = useState('');
  const [provider, setProvider] = useState<IntegrationProvider>('github');
  const [branch, setBranch] = useState('main');
  const [credentialsSecret, setCredentialsSecret] = useState('');

  // Card 2: Agents
  const [agents, setAgents] = useState<IntegrationAgentRef[]>([
    { name: '', namespace: 'team1' },
  ]);

  // Card 3: Webhooks
  const [webhooksExpanded, setWebhooksExpanded] = useState(false);
  const [webhookEvents, setWebhookEvents] = useState<string[]>([]);
  const [branchFilter, setBranchFilter] = useState('');

  // Card 4: Schedules
  const [schedulesExpanded, setSchedulesExpanded] = useState(false);
  const [schedules, setSchedules] = useState<ScheduleEntry[]>([]);

  // Card 5: Alerts
  const [alertsExpanded, setAlertsExpanded] = useState(false);
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof integrationService.create>[0]) =>
      integrationService.create(data),
    onSuccess: () => {
      navigate('/integrations');
    },
  });

  // --- Agent helpers ---
  const addAgent = () => {
    setAgents([...agents, { name: '', namespace }]);
  };

  const removeAgent = (index: number) => {
    setAgents(agents.filter((_, i) => i !== index));
  };

  const updateAgent = (index: number, field: keyof IntegrationAgentRef, value: string) => {
    const updated = [...agents];
    updated[index] = { ...updated[index], [field]: value };
    setAgents(updated);
  };

  // --- Schedule helpers ---
  const addSchedule = () => {
    setSchedules([...schedules, { name: '', cron: '', skill: '', agent: '' }]);
  };

  const removeSchedule = (index: number) => {
    setSchedules(schedules.filter((_, i) => i !== index));
  };

  const updateSchedule = (index: number, field: keyof ScheduleEntry, value: string) => {
    const updated = [...schedules];
    updated[index] = { ...updated[index], [field]: value };
    setSchedules(updated);
  };

  // --- Alert helpers ---
  const addAlert = () => {
    setAlerts([...alerts, { name: '', source: 'prometheus', agent: '' }]);
  };

  const removeAlert = (index: number) => {
    setAlerts(alerts.filter((_, i) => i !== index));
  };

  const updateAlert = (index: number, field: keyof AlertEntry, value: string) => {
    const updated = [...alerts];
    updated[index] = { ...updated[index], [field]: value } as AlertEntry;
    setAlerts(updated);
  };

  // --- Webhook event toggle ---
  const toggleWebhookEvent = (event: string, checked: boolean) => {
    if (checked) {
      setWebhookEvents([...webhookEvents, event]);
    } else {
      setWebhookEvents(webhookEvents.filter((e) => e !== event));
    }
  };

  // --- Validation ---
  const validateForm = (): boolean => {
    if (!name.trim()) return false;
    if (!repoUrl.trim()) return false;
    if (!namespace) return false;
    // Need at least one agent with a name
    const validAgents = agents.filter((a) => a.name.trim());
    if (validAgents.length === 0) return false;
    return true;
  };

  // --- Submit ---
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    const validAgents = agents.filter((a) => a.name.trim());

    // Build webhooks array
    const webhooks =
      webhookEvents.length > 0
        ? [
            {
              name: `${name}-webhook`,
              events: webhookEvents,
              ...(branchFilter.trim()
                ? { filters: { branches: [branchFilter.trim()] } }
                : {}),
            },
          ]
        : undefined;

    // Build schedules array (only entries with required fields filled)
    const validSchedules = schedules.filter(
      (s) => s.name.trim() && s.cron.trim() && s.skill.trim() && s.agent.trim()
    );

    // Build alerts array (only entries with required fields filled)
    const validAlerts = alerts
      .filter((a) => a.name.trim() && a.agent.trim())
      .map((a) => ({
        name: a.name,
        source: a.source,
        matchLabels: {},
        agent: a.agent,
      }));

    createMutation.mutate({
      name: name.trim(),
      namespace,
      repository: {
        url: repoUrl.trim(),
        provider,
        branch: branch.trim() || 'main',
        ...(credentialsSecret.trim()
          ? { credentialsSecret: credentialsSecret.trim() }
          : {}),
      },
      agents: validAgents,
      ...(webhooks ? { webhooks } : {}),
      ...(validSchedules.length > 0 ? { schedules: validSchedules } : {}),
      ...(validAlerts.length > 0 ? { alerts: validAlerts } : {}),
    });
  };

  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">Add Integration</Title>
          <Text component="p">
            Connect a repository and bind agents to respond to events, schedules, and alerts.
          </Text>
        </TextContent>
      </PageSection>

      <PageSection>
        {createMutation.isError && (
          <Alert
            variant="danger"
            title="Failed to create integration"
            isInline
            style={{ marginBottom: '16px' }}
          >
            {createMutation.error instanceof Error
              ? createMutation.error.message
              : 'An unexpected error occurred'}
          </Alert>
        )}

        <Form onSubmit={handleSubmit}>
          {/* Card 1: Repository */}
          <Card style={{ marginBottom: '16px' }}>
            <CardTitle>Repository</CardTitle>
            <CardBody>
              <FormGroup label="Namespace" isRequired fieldId="namespace">
                <NamespaceSelector
                  namespace={namespace}
                  onNamespaceChange={setNamespace}
                />
              </FormGroup>

              <FormGroup label="Name" isRequired fieldId="name">
                <TextInput
                  id="name"
                  value={name}
                  onChange={(_event, value) => setName(value)}
                  placeholder="my-integration"
                  isRequired
                />
              </FormGroup>

              <FormGroup label="Repository URL" isRequired fieldId="repo-url">
                <TextInput
                  id="repo-url"
                  value={repoUrl}
                  onChange={(_event, value) => setRepoUrl(value)}
                  placeholder="https://github.com/org/repo"
                  isRequired
                />
              </FormGroup>

              <FormGroup label="Provider" fieldId="provider">
                <FormSelect
                  id="provider"
                  value={provider}
                  onChange={(_event, value) => setProvider(value as IntegrationProvider)}
                >
                  <FormSelectOption value="github" label="GitHub" />
                  <FormSelectOption value="gitlab" label="GitLab" />
                  <FormSelectOption value="bitbucket" label="Bitbucket" />
                </FormSelect>
              </FormGroup>

              <FormGroup label="Branch" fieldId="branch">
                <TextInput
                  id="branch"
                  value={branch}
                  onChange={(_event, value) => setBranch(value)}
                  placeholder="main"
                />
              </FormGroup>

              <FormGroup label="Credentials Secret" fieldId="credentials-secret">
                <TextInput
                  id="credentials-secret"
                  value={credentialsSecret}
                  onChange={(_event, value) => setCredentialsSecret(value)}
                  placeholder="repo-credentials"
                />
                <FormHelperText>
                  <HelperText>
                    <HelperTextItem>
                      Kubernetes Secret name containing repository access credentials
                    </HelperTextItem>
                  </HelperText>
                </FormHelperText>
              </FormGroup>
            </CardBody>
          </Card>

          {/* Card 2: Agents */}
          <Card style={{ marginBottom: '16px' }}>
            <CardTitle>Agents</CardTitle>
            <CardBody>
              {agents.map((agent, index) => (
                <Split
                  key={index}
                  hasGutter
                  style={{ marginBottom: '8px', alignItems: 'flex-end' }}
                >
                  <SplitItem isFilled>
                    <FormGroup
                      label={index === 0 ? 'Agent Name' : undefined}
                      isRequired
                      fieldId={`agent-name-${index}`}
                    >
                      <TextInput
                        id={`agent-name-${index}`}
                        value={agent.name}
                        onChange={(_event, value) => updateAgent(index, 'name', value)}
                        placeholder="agent-name"
                        isRequired
                      />
                    </FormGroup>
                  </SplitItem>
                  <SplitItem isFilled>
                    <FormGroup
                      label={index === 0 ? 'Agent Namespace' : undefined}
                      fieldId={`agent-ns-${index}`}
                    >
                      <TextInput
                        id={`agent-ns-${index}`}
                        value={agent.namespace}
                        onChange={(_event, value) => updateAgent(index, 'namespace', value)}
                        placeholder={namespace}
                      />
                    </FormGroup>
                  </SplitItem>
                  <SplitItem>
                    <Button
                      variant="plain"
                      aria-label="Remove agent"
                      onClick={() => removeAgent(index)}
                      isDisabled={agents.length === 1}
                    >
                      <TrashIcon />
                    </Button>
                  </SplitItem>
                </Split>
              ))}
              <Button
                variant="link"
                icon={<PlusCircleIcon />}
                onClick={addAgent}
              >
                Add Agent
              </Button>
            </CardBody>
          </Card>

          {/* Card 3: Webhooks */}
          <Card style={{ marginBottom: '16px' }}>
            <CardBody>
              <ExpandableSection
                toggleText="Webhooks"
                isExpanded={webhooksExpanded}
                onToggle={(_event, expanded) => setWebhooksExpanded(expanded)}
              >
                <FormGroup label="Webhook Events" fieldId="webhook-events">
                  {WEBHOOK_EVENTS.map((event) => (
                    <Checkbox
                      key={event}
                      id={`webhook-event-${event}`}
                      label={event}
                      isChecked={webhookEvents.includes(event)}
                      onChange={(_event, checked) => toggleWebhookEvent(event, checked)}
                      style={{ marginBottom: '4px' }}
                    />
                  ))}
                </FormGroup>

                <FormGroup label="Branch Filter" fieldId="branch-filter">
                  <TextInput
                    id="branch-filter"
                    value={branchFilter}
                    onChange={(_event, value) => setBranchFilter(value)}
                    placeholder="main"
                  />
                  <FormHelperText>
                    <HelperText>
                      <HelperTextItem>
                        Only trigger for events on this branch (optional)
                      </HelperTextItem>
                    </HelperText>
                  </FormHelperText>
                </FormGroup>
              </ExpandableSection>
            </CardBody>
          </Card>

          {/* Card 4: Schedules */}
          <Card style={{ marginBottom: '16px' }}>
            <CardBody>
              <ExpandableSection
                toggleText="Schedules"
                isExpanded={schedulesExpanded}
                onToggle={(_event, expanded) => setSchedulesExpanded(expanded)}
              >
                {schedules.map((schedule, index) => (
                  <Split
                    key={index}
                    hasGutter
                    style={{ marginBottom: '8px', alignItems: 'flex-end' }}
                  >
                    <SplitItem isFilled>
                      <FormGroup
                        label={index === 0 ? 'Name' : undefined}
                        fieldId={`schedule-name-${index}`}
                      >
                        <TextInput
                          id={`schedule-name-${index}`}
                          value={schedule.name}
                          onChange={(_event, value) =>
                            updateSchedule(index, 'name', value)
                          }
                          placeholder="nightly-scan"
                        />
                      </FormGroup>
                    </SplitItem>
                    <SplitItem isFilled>
                      <FormGroup
                        label={index === 0 ? 'Cron' : undefined}
                        fieldId={`schedule-cron-${index}`}
                      >
                        <TextInput
                          id={`schedule-cron-${index}`}
                          value={schedule.cron}
                          onChange={(_event, value) =>
                            updateSchedule(index, 'cron', value)
                          }
                          placeholder="0 2 * * *"
                        />
                      </FormGroup>
                    </SplitItem>
                    <SplitItem isFilled>
                      <FormGroup
                        label={index === 0 ? 'Skill' : undefined}
                        fieldId={`schedule-skill-${index}`}
                      >
                        <TextInput
                          id={`schedule-skill-${index}`}
                          value={schedule.skill}
                          onChange={(_event, value) =>
                            updateSchedule(index, 'skill', value)
                          }
                          placeholder="code-review"
                        />
                      </FormGroup>
                    </SplitItem>
                    <SplitItem isFilled>
                      <FormGroup
                        label={index === 0 ? 'Agent' : undefined}
                        fieldId={`schedule-agent-${index}`}
                      >
                        <TextInput
                          id={`schedule-agent-${index}`}
                          value={schedule.agent}
                          onChange={(_event, value) =>
                            updateSchedule(index, 'agent', value)
                          }
                          placeholder="agent-name"
                        />
                      </FormGroup>
                    </SplitItem>
                    <SplitItem>
                      <Button
                        variant="plain"
                        aria-label="Remove schedule"
                        onClick={() => removeSchedule(index)}
                      >
                        <TrashIcon />
                      </Button>
                    </SplitItem>
                  </Split>
                ))}
                <Button
                  variant="link"
                  icon={<PlusCircleIcon />}
                  onClick={addSchedule}
                >
                  Add Schedule
                </Button>
              </ExpandableSection>
            </CardBody>
          </Card>

          {/* Card 5: Alerts */}
          <Card style={{ marginBottom: '16px' }}>
            <CardBody>
              <ExpandableSection
                toggleText="Alerts"
                isExpanded={alertsExpanded}
                onToggle={(_event, expanded) => setAlertsExpanded(expanded)}
              >
                {alerts.map((alert, index) => (
                  <Split
                    key={index}
                    hasGutter
                    style={{ marginBottom: '8px', alignItems: 'flex-end' }}
                  >
                    <SplitItem isFilled>
                      <FormGroup
                        label={index === 0 ? 'Name' : undefined}
                        fieldId={`alert-name-${index}`}
                      >
                        <TextInput
                          id={`alert-name-${index}`}
                          value={alert.name}
                          onChange={(_event, value) =>
                            updateAlert(index, 'name', value)
                          }
                          placeholder="high-cpu-alert"
                        />
                      </FormGroup>
                    </SplitItem>
                    <SplitItem isFilled>
                      <FormGroup
                        label={index === 0 ? 'Source' : undefined}
                        fieldId={`alert-source-${index}`}
                      >
                        <FormSelect
                          id={`alert-source-${index}`}
                          value={alert.source}
                          onChange={(_event, value) =>
                            updateAlert(index, 'source', value)
                          }
                        >
                          {ALERT_SOURCES.map((src) => (
                            <FormSelectOption
                              key={src.value}
                              value={src.value}
                              label={src.label}
                            />
                          ))}
                        </FormSelect>
                      </FormGroup>
                    </SplitItem>
                    <SplitItem isFilled>
                      <FormGroup
                        label={index === 0 ? 'Agent' : undefined}
                        fieldId={`alert-agent-${index}`}
                      >
                        <TextInput
                          id={`alert-agent-${index}`}
                          value={alert.agent}
                          onChange={(_event, value) =>
                            updateAlert(index, 'agent', value)
                          }
                          placeholder="agent-name"
                        />
                      </FormGroup>
                    </SplitItem>
                    <SplitItem>
                      <Button
                        variant="plain"
                        aria-label="Remove alert"
                        onClick={() => removeAlert(index)}
                      >
                        <TrashIcon />
                      </Button>
                    </SplitItem>
                  </Split>
                ))}
                <Button
                  variant="link"
                  icon={<PlusCircleIcon />}
                  onClick={addAlert}
                >
                  Add Alert
                </Button>
              </ExpandableSection>
            </CardBody>
          </Card>

          {/* Actions */}
          <ActionGroup style={{ marginTop: '24px' }}>
            <Button
              variant="primary"
              type="submit"
              isLoading={createMutation.isPending}
              isDisabled={createMutation.isPending || !validateForm()}
            >
              {createMutation.isPending ? 'Creating...' : 'Create Integration'}
            </Button>
            <Button variant="link" onClick={() => navigate('/integrations')}>
              Cancel
            </Button>
          </ActionGroup>
        </Form>
      </PageSection>
    </>
  );
};
