// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * Sandbox Agent Import Wizard — Step-by-step creation of hardened sandbox agents.
 *
 * Steps:
 *   1. Source — Git repo, branch, agent variant
 *   2. Security — Isolation mode, Landlock, proxy allowlist
 *   3. Identity — PAT (quick) or GitHub App (enterprise)
 *   4. Persistence — PostgreSQL toggle
 *   5. Observability — OTEL endpoint, model
 *   6. Review — Summary + Deploy
 *
 * MVP: Steps 1 and 6 are functional. Steps 2-5 show defaults (editable later).
 */

import React, { useState } from 'react';
import {
  PageSection,
  Title,
  Card,
  CardBody,
  Form,
  FormGroup,
  TextInput,
  FormSelect,
  FormSelectOption,
  ActionGroup,
  Button,
  ProgressStepper,
  ProgressStep,
  Alert,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Switch,
  TextArea,
  Split,
  SplitItem,
} from '@patternfly/react-core';
import { useNavigate } from 'react-router-dom';

interface WizardState {
  // Step 1: Source
  name: string;
  repo: string;
  branch: string;
  contextDir: string;
  dockerfile: string;
  variant: string;
  // Step 2: Security
  isolationMode: 'shared' | 'pod-per-session';
  readOnlyRoot: boolean;
  dropCaps: boolean;
  nonRoot: boolean;
  landlockRules: string;
  proxyAllowlist: string;
  workspaceSize: string;
  sessionTtl: string;
  // Step 3: Identity
  credentialMode: 'pat' | 'github-app';
  githubPat: string;
  llmApiKey: string;
  // Step 4: Persistence
  enablePersistence: boolean;
  dbSource: 'in-cluster' | 'external';
  externalDbUrl: string;
  enableCheckpointing: boolean;
  // Step 5: Observability
  otelEndpoint: string;
  enableMlflow: boolean;
  model: string;
}

const INITIAL_STATE: WizardState = {
  name: '',
  repo: '',
  branch: 'main',
  contextDir: '/',
  dockerfile: 'Dockerfile',
  variant: 'sandbox-legion',
  isolationMode: 'shared',
  readOnlyRoot: true,
  dropCaps: true,
  nonRoot: true,
  landlockRules: '/workspace:rw, /tmp:rw',
  proxyAllowlist: 'github.com, api.openai.com, pypi.org',
  workspaceSize: '5Gi',
  sessionTtl: '7d',
  credentialMode: 'pat',
  githubPat: '',
  llmApiKey: '',
  enablePersistence: true,
  dbSource: 'in-cluster',
  externalDbUrl: '',
  enableCheckpointing: true,
  otelEndpoint: 'otel-collector.kagenti-system:8335',
  enableMlflow: true,
  model: 'gpt-4o-mini',
};

const STEPS = [
  'Source',
  'Security',
  'Identity',
  'Persistence',
  'Observability',
  'Review',
];

const VARIANTS = [
  { value: 'sandbox-legion', label: 'Sandbox Legion (multi-agent, persistent)' },
  { value: 'sandbox-agent', label: 'Sandbox Agent (basic, stateless)' },
  { value: 'custom', label: 'Custom' },
];

const MODELS = [
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4.1-mini', label: 'GPT-4.1 Mini' },
  { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
];

const WORKSPACE_SIZES = [
  { value: '1Gi', label: '1 GiB' },
  { value: '5Gi', label: '5 GiB' },
  { value: '10Gi', label: '10 GiB' },
  { value: '20Gi', label: '20 GiB' },
];

const SESSION_TTLS = [
  { value: '1h', label: '1 hour' },
  { value: '1d', label: '1 day' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
];

export const SandboxCreatePage: React.FC = () => {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>(INITIAL_STATE);
  const [deploying, setDeploying] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);

  const update = <K extends keyof WizardState>(
    key: K,
    value: WizardState[K]
  ) => {
    setState((prev) => ({ ...prev, [key]: value }));
  };

  const canAdvance = (): boolean => {
    if (step === 0) return !!state.name && !!state.repo;
    return true;
  };

  const handleDeploy = async () => {
    setDeploying(true);
    setDeployError(null);
    try {
      // TODO: POST /api/v1/sandbox/create with wizard state
      // For now, just navigate back to sandbox page
      await new Promise((resolve) => setTimeout(resolve, 1000));
      navigate('/sandbox');
    } catch (err) {
      setDeployError(
        err instanceof Error ? err.message : 'Deployment failed'
      );
    } finally {
      setDeploying(false);
    }
  };

  // Step renderers
  const renderSourceStep = () => (
    <Form>
      <FormGroup label="Agent Name" isRequired fieldId="agent-name">
        <TextInput
          id="agent-name"
          value={state.name}
          onChange={(_e, v) => update('name', v)}
          placeholder="my-sandbox-agent"
        />
      </FormGroup>
      <FormGroup label="Git Repository URL" isRequired fieldId="repo-url">
        <TextInput
          id="repo-url"
          value={state.repo}
          onChange={(_e, v) => update('repo', v)}
          placeholder="https://github.com/org/repo"
        />
      </FormGroup>
      <FormGroup label="Branch" isRequired fieldId="branch">
        <TextInput
          id="branch"
          value={state.branch}
          onChange={(_e, v) => update('branch', v)}
        />
      </FormGroup>
      <FormGroup label="Context Directory" fieldId="context-dir">
        <TextInput
          id="context-dir"
          value={state.contextDir}
          onChange={(_e, v) => update('contextDir', v)}
        />
      </FormGroup>
      <FormGroup label="Dockerfile Path" fieldId="dockerfile">
        <TextInput
          id="dockerfile"
          value={state.dockerfile}
          onChange={(_e, v) => update('dockerfile', v)}
        />
      </FormGroup>
      <FormGroup label="Agent Variant" isRequired fieldId="variant">
        <FormSelect
          id="variant"
          value={state.variant}
          onChange={(_e, v) => update('variant', v)}
        >
          {VARIANTS.map((v) => (
            <FormSelectOption key={v.value} value={v.value} label={v.label} />
          ))}
        </FormSelect>
      </FormGroup>
    </Form>
  );

  const renderSecurityStep = () => (
    <Form>
      <FormGroup label="Isolation Mode" fieldId="isolation-mode">
        <FormSelect
          id="isolation-mode"
          value={state.isolationMode}
          onChange={(_e, v) =>
            update('isolationMode', v as 'shared' | 'pod-per-session')
          }
        >
          <FormSelectOption
            value="shared"
            label="Shared pod (lower cost, interactive)"
          />
          <FormSelectOption
            value="pod-per-session"
            label="Pod per session (strongest isolation, autonomous)"
          />
        </FormSelect>
      </FormGroup>
      <FormGroup label="Security Hardening" fieldId="hardening">
        <Switch
          id="readonly-root"
          label="Read-only root filesystem"
          isChecked={state.readOnlyRoot}
          onChange={(_e, c) => update('readOnlyRoot', c)}
          style={{ marginBottom: 8 }}
        />
        <Switch
          id="drop-caps"
          label="Drop all capabilities"
          isChecked={state.dropCaps}
          onChange={(_e, c) => update('dropCaps', c)}
          style={{ marginBottom: 8 }}
        />
        <Switch
          id="non-root"
          label="Non-root user"
          isChecked={state.nonRoot}
          onChange={(_e, c) => update('nonRoot', c)}
        />
      </FormGroup>
      <FormGroup label="Landlock Filesystem Rules" fieldId="landlock">
        <TextArea
          id="landlock"
          value={state.landlockRules}
          onChange={(_e, v) => update('landlockRules', v)}
          rows={2}
        />
      </FormGroup>
      <FormGroup label="Network Proxy Allowlist" fieldId="proxy-allowlist">
        <TextArea
          id="proxy-allowlist"
          value={state.proxyAllowlist}
          onChange={(_e, v) => update('proxyAllowlist', v)}
          rows={2}
        />
      </FormGroup>
      <Split hasGutter>
        <SplitItem isFilled>
          <FormGroup label="Workspace Size" fieldId="workspace-size">
            <FormSelect
              id="workspace-size"
              value={state.workspaceSize}
              onChange={(_e, v) => update('workspaceSize', v)}
            >
              {WORKSPACE_SIZES.map((s) => (
                <FormSelectOption
                  key={s.value}
                  value={s.value}
                  label={s.label}
                />
              ))}
            </FormSelect>
          </FormGroup>
        </SplitItem>
        <SplitItem isFilled>
          <FormGroup label="Session TTL" fieldId="session-ttl">
            <FormSelect
              id="session-ttl"
              value={state.sessionTtl}
              onChange={(_e, v) => update('sessionTtl', v)}
            >
              {SESSION_TTLS.map((t) => (
                <FormSelectOption
                  key={t.value}
                  value={t.value}
                  label={t.label}
                />
              ))}
            </FormSelect>
          </FormGroup>
        </SplitItem>
      </Split>
    </Form>
  );

  const renderIdentityStep = () => (
    <Form>
      <FormGroup label="Credential Mode" fieldId="cred-mode">
        <FormSelect
          id="cred-mode"
          value={state.credentialMode}
          onChange={(_e, v) => update('credentialMode', v as 'pat' | 'github-app')}
        >
          <FormSelectOption value="pat" label="Quick Setup (Personal Access Token)" />
          <FormSelectOption
            value="github-app"
            label="Enterprise (GitHub App + SPIRE)"
          />
        </FormSelect>
      </FormGroup>
      {state.credentialMode === 'pat' && (
        <FormGroup label="GitHub PAT" fieldId="github-pat">
          <TextInput
            id="github-pat"
            type="password"
            value={state.githubPat}
            onChange={(_e, v) => update('githubPat', v)}
            placeholder="ghp_..."
          />
        </FormGroup>
      )}
      {state.credentialMode === 'github-app' && (
        <Alert variant="info" title="GitHub App Setup" isInline>
          Enterprise setup with GitHub App and SPIRE identity is coming soon.
          The wizard will list installed GitHub Apps and let you scope
          repos/permissions.
        </Alert>
      )}
      <FormGroup label="LLM API Key" isRequired fieldId="llm-key">
        <TextInput
          id="llm-key"
          type="password"
          value={state.llmApiKey}
          onChange={(_e, v) => update('llmApiKey', v)}
          placeholder="sk-..."
        />
      </FormGroup>
    </Form>
  );

  const renderPersistenceStep = () => (
    <Form>
      <FormGroup label="Session Persistence" fieldId="persistence">
        <Switch
          id="enable-persistence"
          label="Enable PostgreSQL session store"
          isChecked={state.enablePersistence}
          onChange={(_e, c) => update('enablePersistence', c)}
        />
      </FormGroup>
      {state.enablePersistence && (
        <>
          <FormGroup label="Database Source" fieldId="db-source">
            <FormSelect
              id="db-source"
              value={state.dbSource}
              onChange={(_e, v) =>
                update('dbSource', v as 'in-cluster' | 'external')
              }
            >
              <FormSelectOption
                value="in-cluster"
                label="In-cluster StatefulSet (auto-provisioned)"
              />
              <FormSelectOption
                value="external"
                label="External (RDS, Cloud SQL, etc.)"
              />
            </FormSelect>
          </FormGroup>
          {state.dbSource === 'external' && (
            <FormGroup label="External DB URL" fieldId="external-db">
              <TextInput
                id="external-db"
                value={state.externalDbUrl}
                onChange={(_e, v) => update('externalDbUrl', v)}
                placeholder="postgresql://user:pass@host:5432/db"
              />
            </FormGroup>
          )}
          <FormGroup label="Graph Checkpointing" fieldId="checkpointing">
            <Switch
              id="enable-checkpointing"
              label="Enable LangGraph checkpointing"
              isChecked={state.enableCheckpointing}
              onChange={(_e, c) => update('enableCheckpointing', c)}
            />
          </FormGroup>
        </>
      )}
    </Form>
  );

  const renderObservabilityStep = () => (
    <Form>
      <FormGroup label="OTEL Collector Endpoint" fieldId="otel-endpoint">
        <TextInput
          id="otel-endpoint"
          value={state.otelEndpoint}
          onChange={(_e, v) => update('otelEndpoint', v)}
        />
      </FormGroup>
      <FormGroup label="MLflow Tracking" fieldId="mlflow">
        <Switch
          id="enable-mlflow"
          label="Send traces to MLflow"
          isChecked={state.enableMlflow}
          onChange={(_e, c) => update('enableMlflow', c)}
        />
      </FormGroup>
      <FormGroup label="Default LLM Model" fieldId="model">
        <FormSelect
          id="model"
          value={state.model}
          onChange={(_e, v) => update('model', v)}
        >
          {MODELS.map((m) => (
            <FormSelectOption key={m.value} value={m.value} label={m.label} />
          ))}
        </FormSelect>
      </FormGroup>
    </Form>
  );

  const renderReviewStep = () => (
    <>
      <DescriptionList isHorizontal>
        <DescriptionListGroup>
          <DescriptionListTerm>Agent Name</DescriptionListTerm>
          <DescriptionListDescription>{state.name || '-'}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Repository</DescriptionListTerm>
          <DescriptionListDescription>{state.repo || '-'}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Branch</DescriptionListTerm>
          <DescriptionListDescription>{state.branch}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Variant</DescriptionListTerm>
          <DescriptionListDescription>{state.variant}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Isolation</DescriptionListTerm>
          <DescriptionListDescription>{state.isolationMode}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Persistence</DescriptionListTerm>
          <DescriptionListDescription>
            {state.enablePersistence
              ? `${state.dbSource} PostgreSQL`
              : 'Disabled'}
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Model</DescriptionListTerm>
          <DescriptionListDescription>{state.model}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Credentials</DescriptionListTerm>
          <DescriptionListDescription>
            {state.credentialMode === 'pat' ? 'PAT (Quick Setup)' : 'GitHub App (Enterprise)'}
          </DescriptionListDescription>
        </DescriptionListGroup>
      </DescriptionList>

      {deployError && (
        <Alert
          variant="danger"
          title="Deploy failed"
          isInline
          style={{ marginTop: 16 }}
        >
          {deployError}
        </Alert>
      )}
    </>
  );

  const stepRenderers = [
    renderSourceStep,
    renderSecurityStep,
    renderIdentityStep,
    renderPersistenceStep,
    renderObservabilityStep,
    renderReviewStep,
  ];

  return (
    <PageSection variant="light">
      <Title headingLevel="h1" style={{ marginBottom: 16 }}>
        Create Sandbox Agent
      </Title>

      {/* Step indicator */}
      <ProgressStepper style={{ marginBottom: 24 }}>
        {STEPS.map((label, i) => (
          <ProgressStep
            key={label}
            variant={
              i < step ? 'success' : i === step ? 'info' : 'pending'
            }
            id={`step-${i}`}
            titleId={`step-${i}-title`}
            isCurrent={i === step}
            aria-label={label}
            onClick={() => i < step && setStep(i)}
            style={{ cursor: i < step ? 'pointer' : 'default' }}
          >
            {label}
          </ProgressStep>
        ))}
      </ProgressStepper>

      {/* Step content */}
      <Card>
        <CardBody>{stepRenderers[step]()}</CardBody>
      </Card>

      {/* Navigation */}
      <ActionGroup style={{ marginTop: 16 }}>
        <Button
          variant="secondary"
          onClick={() => (step > 0 ? setStep(step - 1) : navigate('/sandbox'))}
        >
          {step > 0 ? 'Back' : 'Cancel'}
        </Button>
        {step < STEPS.length - 1 ? (
          <Button
            variant="primary"
            onClick={() => setStep(step + 1)}
            isDisabled={!canAdvance()}
          >
            Next
          </Button>
        ) : (
          <Button
            variant="primary"
            onClick={handleDeploy}
            isLoading={deploying}
            isDisabled={deploying || !state.name || !state.repo}
          >
            Deploy Agent
          </Button>
        )}
      </ActionGroup>
    </PageSection>
  );
};
