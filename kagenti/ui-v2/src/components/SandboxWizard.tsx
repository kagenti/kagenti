// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * SandboxWizard -- Reusable wizard for creating or reconfiguring sandbox agents.
 *
 * Steps:
 *   1. Source -- Git repo, branch, agent variant
 *   2. Security -- Isolation mode, Landlock, proxy allowlist
 *   3. Identity -- PAT (quick) or GitHub App (enterprise)
 *   4. Persistence -- PostgreSQL toggle
 *   5. Observability -- OTEL endpoint, model
 *   6. Review -- Summary + Deploy / Redeploy
 */

import React, { useState, useEffect } from 'react';
import {
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
  Spinner,
  Bullseye,
} from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import { sandboxService } from '@/services/api';

export interface WizardState {
  // Step 1: Source
  name: string;
  repo: string;
  branch: string;
  contextDir: string;
  dockerfile: string;
  variant: string;
  // Step 2: Security (composable layers)
  isolationMode: 'shared' | 'pod-per-session';
  secctx: boolean;
  landlock: boolean;
  proxy: boolean;
  proxyDomains: string;
  workspaceSize: string;
  sessionTtl: string;
  // Step 3: Identity
  credentialMode: 'pat' | 'github-app';
  githubPat: string;
  llmKeySource: 'new' | 'existing';
  llmSecretName: string;
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
  forceToolChoice: boolean;
  textToolParsing: boolean;
  // Step 6: Budget
  maxIterations: number;
  maxTokens: number;
  maxToolCallsPerStep: number;
  maxWallClockS: number;
  hitlInterval: number;
  recursionLimit: number;
}

export const INITIAL_STATE: WizardState = {
  name: '',
  repo: '',
  branch: 'main',
  contextDir: '/',
  dockerfile: 'Dockerfile',
  variant: 'sandbox-legion',
  isolationMode: 'shared',
  secctx: true,
  landlock: false,
  proxy: false,
  proxyDomains: 'github.com, pypi.org',
  workspaceSize: '5Gi',
  sessionTtl: '7d',
  credentialMode: 'pat',
  githubPat: '',
  llmKeySource: 'existing',
  llmSecretName: 'openai-secret',
  llmApiKey: '',
  enablePersistence: true,
  dbSource: 'in-cluster',
  externalDbUrl: '',
  enableCheckpointing: true,
  otelEndpoint: 'otel-collector.kagenti-system:8335',
  enableMlflow: true,
  model: 'llama-4-scout',
  forceToolChoice: true,
  textToolParsing: true,
  maxIterations: 100,
  maxTokens: 1000000,
  maxToolCallsPerStep: 10,
  maxWallClockS: 600,
  hitlInterval: 50,
  recursionLimit: 300,
};

const STEPS = [
  'Source',
  'Security',
  'Identity',
  'Persistence',
  'Observability',
  'Budget',
  'Review',
];

const VARIANTS = [
  { value: 'sandbox-legion', label: 'Sandbox Legion (multi-agent, persistent)' },
  { value: 'sandbox-agent', label: 'Sandbox Agent (basic, stateless)' },
  { value: 'custom', label: 'Custom' },
];

// Models served via LiteLLM proxy -- names match litellm config model_name
const MODELS = [
  { value: 'llama-4-scout', label: 'Llama 4 Scout 109B (tool calling)' },
  { value: 'mistral-small', label: 'Mistral Small 24B' },
  { value: 'deepseek-r1', label: 'DeepSeek R1 14B (reasoning)' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gpt-4o', label: 'GPT-4o' },
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

export interface SandboxWizardProps {
  mode: 'create' | 'reconfigure';
  initialState?: Partial<WizardState>;
  agentName?: string;      // for reconfigure -- used in PUT URL
  namespace?: string;       // for reconfigure
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * Map backend config response fields to WizardState.
 * The backend may use snake_case or different key names.
 */
function configToWizardState(config: Record<string, unknown>): Partial<WizardState> {
  const ws: Partial<WizardState> = {};
  if (config.name != null) ws.name = String(config.name);
  if (config.repo != null) ws.repo = String(config.repo);
  if (config.branch != null) ws.branch = String(config.branch);
  if (config.context_dir != null) ws.contextDir = String(config.context_dir);
  if (config.dockerfile != null) ws.dockerfile = String(config.dockerfile);
  if (config.base_agent != null) ws.variant = String(config.base_agent);
  if (config.variant != null) ws.variant = String(config.variant);
  if (config.model != null) ws.model = String(config.model);
  if (config.isolation_mode != null)
    ws.isolationMode = config.isolation_mode as 'shared' | 'pod-per-session';
  if (config.workspace_size != null) ws.workspaceSize = String(config.workspace_size);
  if (config.session_ttl != null) ws.sessionTtl = String(config.session_ttl);
  if (config.secctx != null) ws.secctx = Boolean(config.secctx);
  if (config.landlock != null) ws.landlock = Boolean(config.landlock);
  if (config.proxy != null) ws.proxy = Boolean(config.proxy);
  if (config.proxy_domains != null) ws.proxyDomains = String(config.proxy_domains);
  if (config.enable_persistence != null) ws.enablePersistence = Boolean(config.enable_persistence);
  if (config.db_source != null) ws.dbSource = config.db_source as 'in-cluster' | 'external';
  if (config.external_db_url != null) ws.externalDbUrl = String(config.external_db_url);
  if (config.enable_checkpointing != null) ws.enableCheckpointing = Boolean(config.enable_checkpointing);
  if (config.otel_endpoint != null) ws.otelEndpoint = String(config.otel_endpoint);
  if (config.enable_mlflow != null) ws.enableMlflow = Boolean(config.enable_mlflow);
  if (config.credential_mode != null) ws.credentialMode = config.credential_mode as 'pat' | 'github-app';
  if (config.llm_key_source != null) ws.llmKeySource = config.llm_key_source as 'new' | 'existing';
  if (config.llm_secret_name != null) ws.llmSecretName = String(config.llm_secret_name);
  if (config.maxIterations != null) ws.maxIterations = Number(config.maxIterations);
  if (config.maxTokens != null) ws.maxTokens = Number(config.maxTokens);
  if (config.maxToolCallsPerStep != null) ws.maxToolCallsPerStep = Number(config.maxToolCallsPerStep);
  if (config.maxWallClockS != null) ws.maxWallClockS = Number(config.maxWallClockS);
  if (config.hitlInterval != null) ws.hitlInterval = Number(config.hitlInterval);
  if (config.recursionLimit != null) ws.recursionLimit = Number(config.recursionLimit);
  return ws;
}

export const SandboxWizard: React.FC<SandboxWizardProps> = ({
  mode,
  initialState,
  agentName,
  namespace,
  onClose,
  onSuccess,
}) => {
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>({
    ...INITIAL_STATE,
    ...initialState,
  });
  const [deploying, setDeploying] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);
  const [configApplied, setConfigApplied] = useState(false);

  // Fetch existing config in reconfigure mode
  const {
    data: existingConfig,
    isLoading: configLoading,
    isError: configError,
  } = useQuery({
    queryKey: ['sandbox-config', namespace, agentName],
    queryFn: () => sandboxService.getConfig(namespace!, agentName!),
    enabled: mode === 'reconfigure' && !!namespace && !!agentName,
    staleTime: 30000,
    retry: 1,
  });

  // Apply fetched config to state once
  useEffect(() => {
    if (existingConfig && !configApplied) {
      const mapped = configToWizardState(existingConfig);
      setState((prev) => ({ ...prev, ...mapped }));
      setConfigApplied(true);
    }
  }, [existingConfig, configApplied]);

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
      const ns = namespace || 'team1';
      const payload = {
        name: state.name,
        repo: state.repo,
        branch: state.branch,
        context_dir: state.contextDir,
        dockerfile: state.dockerfile,
        base_agent: state.variant,
        model: state.model,
        namespace: ns,
        enable_persistence: state.enablePersistence,
        isolation_mode: state.isolationMode,
        workspace_size: state.workspaceSize,
        // Composable security layers
        secctx: state.secctx,
        landlock: state.landlock,
        proxy: state.proxy,
        proxy_domains: state.proxy ? state.proxyDomains : undefined,
        // Credentials
        github_pat: state.githubPat || undefined,
        llm_api_key: state.llmApiKey || undefined,
        llm_key_source: state.llmKeySource,
        llm_secret_name: state.llmSecretName,
        // LLM behavior
        force_tool_choice: state.forceToolChoice,
        text_tool_parsing: state.textToolParsing,
        // Budget controls
        max_iterations: state.maxIterations,
        max_tokens: state.maxTokens,
        max_tool_calls_per_step: state.maxToolCallsPerStep,
        max_wall_clock_s: state.maxWallClockS,
        hitl_interval: state.hitlInterval,
        recursion_limit: state.recursionLimit,
      };

      if (mode === 'reconfigure' && agentName) {
        const result = await sandboxService.updateSandbox(ns, agentName, payload);
        if (result.status === 'failed') {
          setDeployError(result.message);
        } else {
          onSuccess();
        }
      } else {
        const result = await sandboxService.createSandbox(ns, payload);
        if (result.status === 'failed') {
          setDeployError(result.message);
        } else if (result.security_warnings?.length) {
          setDeployError(`Deployed with warnings: ${result.security_warnings.join('; ')}`);
          setTimeout(() => onSuccess(), 3000);
        } else {
          onSuccess();
        }
      }
    } catch (err) {
      setDeployError(
        err instanceof Error ? err.message : 'Deployment failed'
      );
    } finally {
      setDeploying(false);
    }
  };

  // Show loading spinner while fetching config in reconfigure mode
  if (mode === 'reconfigure' && configLoading) {
    return (
      <Bullseye style={{ minHeight: 200 }}>
        <Spinner size="xl" aria-label="Loading agent configuration" />
      </Bullseye>
    );
  }

  if (mode === 'reconfigure' && configError) {
    return (
      <Alert variant="danger" title="Failed to load agent configuration" isInline>
        Could not fetch the current configuration for agent &quot;{agentName}&quot;. Please try again.
      </Alert>
    );
  }

  const isReconfigure = mode === 'reconfigure';
  const deployButtonLabel = isReconfigure ? 'Redeploy' : 'Deploy Agent';

  // Step renderers
  const renderSourceStep = () => (
    <Form>
      <FormGroup label="Agent Name" isRequired fieldId="agent-name">
        <TextInput
          id="agent-name"
          value={state.name}
          onChange={(_e, v) => update('name', v)}
          placeholder="my-sandbox-agent"
          isDisabled={isReconfigure}
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
      <FormGroup label="Security Layers" fieldId="security-layers">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Switch
            id="secctx"
            label="Container Hardening (non-root, drop caps, seccomp)"
            isChecked={state.secctx}
            onChange={(_e, c) => update('secctx', c)}
          />
          <Switch
            id="landlock"
            label="Landlock Filesystem Sandbox"
            isChecked={state.landlock}
            onChange={(_e, c) => update('landlock', c)}
          />
          <Switch
            id="proxy"
            label="Network Proxy (egress allowlist)"
            isChecked={state.proxy}
            onChange={(_e, c) => update('proxy', c)}
          />
          {state.proxy && (
            <FormGroup label="Allowed Domains" fieldId="proxy-domains" style={{ marginLeft: 24 }}>
              <TextArea
                id="proxy-domains"
                value={state.proxyDomains}
                onChange={(_e, v) => update('proxyDomains', v)}
                rows={2}
              />
            </FormGroup>
          )}
        </div>
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
      <FormGroup label="LLM API Key" isRequired fieldId="llm-key-source">
        <FormSelect
          id="llm-key-source"
          value={state.llmKeySource}
          onChange={(_e, v) =>
            update('llmKeySource', v as 'new' | 'existing')
          }
        >
          <FormSelectOption
            value="existing"
            label="Use existing namespace secret (recommended)"
          />
          <FormSelectOption value="new" label="Paste a new API key" />
        </FormSelect>
      </FormGroup>
      {state.llmKeySource === 'existing' && (
        <FormGroup label="Secret Name" fieldId="llm-secret-name">
          <TextInput
            id="llm-secret-name"
            value={state.llmSecretName}
            onChange={(_e, v) => update('llmSecretName', v)}
            placeholder="openai-secret"
          />
          <div className="pf-v5-c-form__helper-text" style={{ fontSize: '0.82em', marginTop: 4 }}>
            Kubernetes Secret in the target namespace containing the API key.
          </div>
        </FormGroup>
      )}
      {state.llmKeySource === 'new' && (
        <FormGroup label="API Key" fieldId="llm-key">
          <TextInput
            id="llm-key"
            type="password"
            value={state.llmApiKey}
            onChange={(_e, v) => update('llmApiKey', v)}
            placeholder="sk-..."
          />
          <div className="pf-v5-c-form__helper-text" style={{ fontSize: '0.82em', marginTop: 4 }}>
            Will be stored as a Kubernetes Secret in the target namespace.
          </div>
        </FormGroup>
      )}
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
      <FormGroup label="Force Tool Calling" fieldId="force-tool-choice">
        <Switch
          id="force-tool-choice"
          label="Force structured tool calls (required for Llama 4 Scout)"
          isChecked={state.forceToolChoice}
          onChange={(_e, c) => update('forceToolChoice', c)}
        />
      </FormGroup>
      <FormGroup label="Text Tool Parsing" fieldId="text-tool-parsing">
        <Switch
          id="text-tool-parsing"
          label="Parse tool calls from text responses and strip fabricated output"
          isChecked={state.textToolParsing}
          onChange={(_e, c) => update('textToolParsing', c)}
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

  const sectionHeader = (title: string, subtitle: string) => (
    <div style={{ marginBottom: 8, marginTop: 16 }}>
      <div style={{ fontWeight: 600, fontSize: '0.95em', color: 'var(--pf-v5-global--Color--100)' }}>{title}</div>
      <div className="pf-v5-c-form__helper-text" style={{ fontSize: '0.82em', marginTop: 2 }}>{subtitle}</div>
    </div>
  );

  const budgetHelper = (text: string) => (
    <div className="pf-v5-c-form__helper-text" style={{ fontSize: '0.8em', marginTop: 4 }}>{text}</div>
  );

  const renderBudgetStep = () => (
    <Form>
      {sectionHeader('Session Limits', 'Total resource budget for a single user message (across all reasoning loops)')}
      <Split hasGutter>
        <SplitItem isFilled>
          <FormGroup label="Max Tokens" fieldId="max-tokens">
            <TextInput id="max-tokens" type="number"
              value={String(state.maxTokens)}
              onChange={(_e, v) => update('maxTokens', Number(v) || 1000000)} />
            {budgetHelper('Total prompt + completion tokens consumed across all LLM calls per message. Prevents runaway cost.')}
          </FormGroup>
        </SplitItem>
        <SplitItem isFilled>
          <FormGroup label="Max Wall Clock (seconds)" fieldId="max-wall-clock">
            <TextInput id="max-wall-clock" type="number"
              value={String(state.maxWallClockS)}
              onChange={(_e, v) => update('maxWallClockS', Number(v) || 600)} />
            {budgetHelper('Maximum real-time seconds the agent can work on a single message before being stopped.')}
          </FormGroup>
        </SplitItem>
      </Split>

      {sectionHeader('Loop Limits', 'Controls for the planner → executor → reflector reasoning cycle')}
      <Split hasGutter>
        <SplitItem isFilled>
          <FormGroup label="Max Iterations" fieldId="max-iterations">
            <TextInput id="max-iterations" type="number"
              value={String(state.maxIterations)}
              onChange={(_e, v) => update('maxIterations', Number(v) || 100)} />
            {budgetHelper('Maximum planner→executor→reflector cycles. Each iteration executes one plan step and reflects.')}
          </FormGroup>
        </SplitItem>
        <SplitItem isFilled>
          <FormGroup label="Recursion Limit" fieldId="recursion-limit">
            <TextInput id="recursion-limit" type="number"
              value={String(state.recursionLimit)}
              onChange={(_e, v) => update('recursionLimit', Number(v) || 50)} />
            {budgetHelper('LangGraph internal graph traversal limit. Triggers a warning (not failure) when reached.')}
          </FormGroup>
        </SplitItem>
      </Split>
      <FormGroup label="HITL Check-in Interval" fieldId="hitl-interval">
        <TextInput id="hitl-interval" type="number"
          value={String(state.hitlInterval)}
          onChange={(_e, v) => update('hitlInterval', Number(v) || 50)} />
        {budgetHelper('After this many iterations, pause and ask the user before continuing. Set high to run autonomously.')}
      </FormGroup>

      {sectionHeader('Step Limits', 'Controls for individual plan step execution')}
      <FormGroup label="Tool Calls Per Step" fieldId="max-tool-calls">
        <TextInput id="max-tool-calls" type="number"
          value={String(state.maxToolCallsPerStep)}
          onChange={(_e, v) => update('maxToolCallsPerStep', Number(v) || 10)} />
        {budgetHelper('Maximum tool invocations (shell commands, API calls) within a single plan step before moving on.')}
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
          <DescriptionListTerm>GitHub Credential</DescriptionListTerm>
          <DescriptionListDescription>
            {state.credentialMode === 'pat'
              ? state.githubPat
                ? 'PAT provided (will create Secret)'
                : 'PAT (not provided)'
              : 'GitHub App (Enterprise)'}
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Budget</DescriptionListTerm>
          <DescriptionListDescription>
            {state.maxIterations} iterations, {(state.maxTokens / 1000).toFixed(0)}K tokens, {state.maxWallClockS}s wall clock
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>LLM API Key</DescriptionListTerm>
          <DescriptionListDescription>
            {state.llmKeySource === 'existing'
              ? `Existing secret: ${state.llmSecretName}`
              : state.llmApiKey
                ? 'New key provided (will create Secret)'
                : 'New key (not provided)'}
          </DescriptionListDescription>
        </DescriptionListGroup>
      </DescriptionList>

      {deployError && (
        <Alert
          variant="danger"
          title={isReconfigure ? 'Redeploy failed' : 'Deploy failed'}
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
    renderBudgetStep,
    renderReviewStep,
  ];

  return (
    <>
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
            onClick={() => {
              // Allow backward always; forward only if current step passes validation
              if (i < step || canAdvance()) setStep(i);
            }}
            style={{ cursor: (i < step || canAdvance()) ? 'pointer' : 'default' }}
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
          onClick={() => (step > 0 ? setStep(step - 1) : onClose())}
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
            {deployButtonLabel}
          </Button>
        )}
      </ActionGroup>
    </>
  );
};
