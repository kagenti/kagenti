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
  Divider,
  Radio,
  NumberInput,
  Grid,
  GridItem,
  Checkbox,
} from '@patternfly/react-core';
import { TrashIcon, PlusCircleIcon, UploadIcon } from '@patternfly/react-icons';
import { useMutation } from '@tanstack/react-query';

import { agentService, ShipwrightBuildConfig } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';
import { EnvImportModal } from '@/components/EnvImportModal';
import { BuildStrategySelector } from '@/components/BuildStrategySelector';

// Example agent subfolders from the original UI
const AGENT_EXAMPLES = [
  { value: '', label: 'Select an example...' },
  { value: 'a2a/a2a_contact_extractor', label: 'Contact Extractor Agent' },
  { value: 'a2a/a2a_currency_converter', label: 'Currency Converter Agent' },
  { value: 'a2a/generic_agent', label: 'Generic Agent' },
  { value: 'a2a/git_issue_agent', label: 'Git Issue Agent' },
  { value: 'a2a/file_organizer', label: 'File Organizer Agent' },
  { value: 'a2a/slack_researcher', label: 'Slack Researcher Agent' },
  { value: 'a2a/weather_service', label: 'Weather Service Agent' },
];

const FRAMEWORKS = [
  { value: 'LangGraph', label: 'LangGraph' },
  { value: 'CrewAI', label: 'CrewAI' },
  { value: 'AG2', label: 'AG2' },
  { value: 'Python', label: 'Python (Custom)' },
];

const REGISTRY_OPTIONS = [
  { value: 'local', label: 'Local Registry (In-Cluster)', url: 'registry.cr-system.svc.cluster.local:5000' },
  { value: 'quay', label: 'Quay.io', url: 'quay.io' },
  { value: 'dockerhub', label: 'Docker Hub', url: 'docker.io' },
  { value: 'github', label: 'GitHub Container Registry', url: 'ghcr.io' },
];

const DEFAULT_REPO_URL = 'https://github.com/kagenti/agent-examples';
const DEFAULT_BRANCH = 'main';

type DeploymentMethod = 'source' | 'image';

interface EnvVar {
  name: string;
  value?: string;
  valueFrom?: {
    secretKeyRef?: {
      name: string;
      key: string;
    };
    configMapKeyRef?: {
      name: string;
      key: string;
    };
  };
}

type EnvVarType = 'value' | 'secret' | 'configMap';

interface ServicePort {
  name: string;
  port: number;
  targetPort: number;
  protocol: 'TCP' | 'UDP';
}

export const ImportAgentPage: React.FC = () => {
  const navigate = useNavigate();

  // Deployment method
  const [deploymentMethod, setDeploymentMethod] = useState<DeploymentMethod>('source');

  // Basic info
  const [namespace, setNamespace] = useState('team1');
  const [name, setName] = useState('');
  const [framework, setFramework] = useState('LangGraph');

  // Build from source state
  const [gitUrl, setGitUrl] = useState(DEFAULT_REPO_URL);
  const [gitBranch, setGitBranch] = useState(DEFAULT_BRANCH);
  const [gitPath, setGitPath] = useState('');
  const [selectedExample, setSelectedExample] = useState('');
  const [startCommand, setStartCommand] = useState('python main.py');
  const [showStartCommand, setShowStartCommand] = useState(false);

  // Registry configuration (for build from source)
  const [registryType, setRegistryType] = useState('local');
  const [registryNamespace, setRegistryNamespace] = useState('');
  const [registrySecret, setRegistrySecret] = useState('');

  // Update registry secret default when registry type changes
  React.useEffect(() => {
    if (registryType !== 'local') {
      setRegistrySecret(`${registryType}-registry-secret`);
    } else {
      setRegistrySecret('');
    }
  }, [registryType]);

  // Shipwright build configuration (always enabled for source builds)
  const [buildStrategy, setBuildStrategy] = useState('buildah-insecure-push');
  const [dockerfile, setDockerfile] = useState('Dockerfile');
  const [buildTimeout, setBuildTimeout] = useState('15m');
  const [buildArgs, setBuildArgs] = useState<string[]>([]);
  const [showBuildConfig, setShowBuildConfig] = useState(false);

  // Deploy from image state
  const [containerImage, setContainerImage] = useState('');
  const [imageTag, setImageTag] = useState('latest');
  const [imagePullSecret, setImagePullSecret] = useState('');

  // Pod configuration
  const [servicePorts, setServicePorts] = useState<ServicePort[]>([
    { name: 'http', port: 8080, targetPort: 8000, protocol: 'TCP' },
  ]);
  const [showPodConfig, setShowPodConfig] = useState(false);

  // Environment variables
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [showEnvVars, setShowEnvVars] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);

  // Workload type
  const [workloadType, setWorkloadType] = useState<'deployment' | 'statefulset' | 'job'>('deployment');

  // HTTPRoute/Route creation
  const [createHttpRoute, setCreateHttpRoute] = useState(false);

  // Validation state
  const [validated, setValidated] = useState<Record<string, 'success' | 'error' | 'default'>>({});

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof agentService.create>[0]) =>
      agentService.create(data),
    onSuccess: () => {
      const finalName = name || getNameFromPath();
      // Navigate to build progress page if using Shipwright for source builds
      // Always navigate to build page for source builds (Shipwright)
      if (deploymentMethod === 'source') {
        navigate(`/agents/${namespace}/${finalName}/build`);
      } else {
        navigate(`/agents/${namespace}/${finalName}`);
      }
    },
  });

  const getNameFromPath = () => {
    if (deploymentMethod === 'image') {
      // Extract name from image URL
      const parts = containerImage.split('/');
      const imageName = parts[parts.length - 1].split(':')[0];
      return imageName.replace(/_/g, '-').toLowerCase();
    }
    const path = gitPath || selectedExample;
    if (!path) return '';
    const parts = path.split('/');
    return parts[parts.length - 1].replace(/_/g, '-').toLowerCase();
  };

  const handleExampleChange = (value: string) => {
    setSelectedExample(value);
    if (value) {
      setGitPath(value);
      const parts = value.split('/');
      const autoName = parts[parts.length - 1].replace(/_/g, '-').toLowerCase();
      if (!name) {
        setName(autoName);
      }
    }
  };

  const handlePathChange = (value: string) => {
    setGitPath(value);
    setSelectedExample('');
    if (value && !name) {
      const parts = value.split('/');
      const autoName = parts[parts.length - 1].replace(/_/g, '-').toLowerCase();
      setName(autoName);
    }
  };

  const handleImageChange = (value: string) => {
    setContainerImage(value);
    if (value && !name) {
      const parts = value.split('/');
      const imageName = parts[parts.length - 1].split(':')[0];
      setName(imageName.replace(/_/g, '-').toLowerCase());
    }
  };

  // Construct default .env URL from git repo info
  const getDefaultEnvUrl = (): string | undefined => {
    if (!gitUrl || !gitPath) return undefined;

    // Parse GitHub URL to extract org and repo
    // Supports: https://github.com/org/repo or https://github.com/org/repo.git
    const githubMatch = gitUrl.match(/github\.com[/:]([^/]+)\/([^/.]+)(\.git)?/);
    if (!githubMatch) return undefined;

    const [, org, repo] = githubMatch;
    const branch = gitBranch || 'main';
    const path = gitPath.replace(/^\/+|\/+$/g, ''); // Remove leading/trailing slashes

    return `https://raw.githubusercontent.com/${org}/${repo}/refs/heads/${branch}/${path}/.env.openai`;
  };

  // Environment variable handlers
  const addEnvVar = () => {
    setEnvVars([...envVars, { name: '', value: '' }]);
  };

  const removeEnvVar = (index: number) => {
    setEnvVars(envVars.filter((_, i) => i !== index));
  };

  const updateEnvVar = (index: number, field: 'name' | 'value', value: string) => {
    const updated = [...envVars];
    updated[index][field] = value;
    setEnvVars(updated);
  };

  const handleImportEnvVars = (importedVars: EnvVar[]) => {
    // Merge imported variables with existing ones, avoiding duplicates
    const existingNames = new Set(envVars.map(v => v.name));
    const newVars = importedVars.filter(v => !existingNames.has(v.name));
    setEnvVars([...envVars, ...newVars]);
    setShowEnvVars(true);
  };

  const getEnvVarType = (envVar: EnvVar): EnvVarType => {
    if (envVar.valueFrom?.secretKeyRef) return 'secret';
    if (envVar.valueFrom?.configMapKeyRef) return 'configMap';
    return 'value';
  };

  const handleEnvVarTypeChange = (index: number, type: EnvVarType) => {
    const updated = [...envVars];
    const currentName = updated[index].name;
    
    if (type === 'value') {
      updated[index] = { name: currentName, value: '' };
    } else if (type === 'secret') {
      updated[index] = { 
        name: currentName, 
        valueFrom: { secretKeyRef: { name: '', key: '' } } 
      };
    } else if (type === 'configMap') {
      updated[index] = { 
        name: currentName, 
        valueFrom: { configMapKeyRef: { name: '', key: '' } } 
      };
    }
    
    setEnvVars(updated);
  };

  const updateEnvVarSecret = (index: number, field: 'name' | 'key', value: string) => {
    const updated = [...envVars];
    if (updated[index].valueFrom?.secretKeyRef) {
      updated[index].valueFrom!.secretKeyRef![field] = value;
      setEnvVars(updated);
    }
  };

  const updateEnvVarConfigMap = (index: number, field: 'name' | 'key', value: string) => {
    const updated = [...envVars];
    if (updated[index].valueFrom?.configMapKeyRef) {
      updated[index].valueFrom!.configMapKeyRef![field] = value;
      setEnvVars(updated);
    }
  };

  // Service port handlers
  const addServicePort = () => {
    setServicePorts([
      ...servicePorts,
      { name: 'http', port: 8080, targetPort: 8000, protocol: 'TCP' },
    ]);
  };

  const removeServicePort = (index: number) => {
    setServicePorts(servicePorts.filter((_, i) => i !== index));
  };

  const updateServicePort = (index: number, field: keyof ServicePort, value: string | number) => {
    const updated = [...servicePorts];
    if (field === 'port' || field === 'targetPort') {
      updated[index][field] = Number(value);
    } else if (field === 'protocol') {
      updated[index][field] = value as 'TCP' | 'UDP';
    } else {
      updated[index][field] = value as string;
    }
    setServicePorts(updated);
  };

  // Build argument handlers
  const addBuildArg = () => {
    setBuildArgs([...buildArgs, '']);
  };

  const removeBuildArg = (index: number) => {
    setBuildArgs(buildArgs.filter((_, i) => i !== index));
  };

  const updateBuildArg = (index: number, value: string) => {
    const updated = [...buildArgs];
    updated[index] = value;
    setBuildArgs(updated);
  };

  const getRegistryUrl = () => {
    const registry = REGISTRY_OPTIONS.find((r) => r.value === registryType);
    if (!registry) return '';
    if (registryType === 'local') return registry.url;
    return registryNamespace ? `${registry.url}/${registryNamespace}` : registry.url;
  };

  const validateForm = (): boolean => {
    const newValidated: Record<string, 'success' | 'error' | 'default'> = {};
    let isValid = true;

    // Name validation
    const finalName = name || getNameFromPath();
    if (!finalName) {
      newValidated.name = 'error';
      isValid = false;
    } else if (!/^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/.test(finalName)) {
      newValidated.name = 'error';
      isValid = false;
    } else {
      newValidated.name = 'success';
    }

    if (deploymentMethod === 'source') {
      // Git URL validation
      if (!gitUrl) {
        newValidated.gitUrl = 'error';
        isValid = false;
      } else {
        newValidated.gitUrl = 'success';
      }

      // Git path validation
      if (!gitPath && !selectedExample) {
        newValidated.gitPath = 'error';
        isValid = false;
      } else {
        newValidated.gitPath = 'success';
      }

      // Registry namespace validation for external registries
      if (registryType !== 'local' && !registryNamespace) {
        newValidated.registryNamespace = 'error';
        isValid = false;
      }
    } else {
      // Container image validation
      if (!containerImage) {
        newValidated.containerImage = 'error';
        isValid = false;
      } else {
        newValidated.containerImage = 'success';
      }
    }

    setValidated(newValidated);
    return isValid;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    const finalName = name || getNameFromPath();

    if (deploymentMethod === 'source') {
      const finalPath = gitPath || selectedExample;

      // Build Shipwright configuration (always used for source builds)
      const shipwrightConfig: ShipwrightBuildConfig = {
        buildStrategy,
        dockerfile,
        buildTimeout,
        buildArgs: buildArgs.filter((arg) => arg.trim() !== ''),
      };

      createMutation.mutate({
        name: finalName,
        namespace,
        gitUrl,
        gitPath: finalPath,
        gitBranch,
        imageTag: 'v0.0.1',
        protocol: 'a2a',
        framework,
        envVars: envVars.filter((ev) => ev.name && (ev.value || ev.valueFrom)),
        // Workload type
        workloadType,
        // Additional fields for build from source
        deploymentMethod: 'source',
        registryUrl: getRegistryUrl(),
        registrySecret: registryType !== 'local' ? registrySecret : undefined,
        startCommand: showStartCommand ? startCommand : undefined,
        servicePorts,
        createHttpRoute,
        // Shipwright build configuration (always enabled)
        useShipwright: true,
        shipwrightConfig,
      });
    } else {
      // Deploy from existing image
      const fullImage = imageTag ? `${containerImage}:${imageTag}` : containerImage;
      createMutation.mutate({
        name: finalName,
        namespace,
        gitUrl: '', // Not used for image deployment
        gitPath: '', // Not used for image deployment
        gitBranch: '',
        imageTag,
        protocol: 'a2a',
        framework,
        envVars: envVars.filter((ev) => ev.name && (ev.value || ev.valueFrom)),
        // Workload type
        workloadType,
        // Additional fields for image deployment
        deploymentMethod: 'image',
        containerImage: fullImage,
        imagePullSecret: imagePullSecret || undefined,
        servicePorts,
        createHttpRoute,
      });
    }
  };

  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">Import New Agent</Title>
          <Text component="p">
            Build from source or deploy an existing container image as an A2A agent.
          </Text>
        </TextContent>
      </PageSection>

      <PageSection>
        <Card>
          <CardTitle>Agent Configuration</CardTitle>
          <CardBody>
            {createMutation.isError && (
              <Alert
                variant="danger"
                title="Failed to create agent"
                isInline
                style={{ marginBottom: '16px' }}
              >
                {createMutation.error instanceof Error
                  ? createMutation.error.message
                  : 'An unexpected error occurred'}
              </Alert>
            )}

            <Form onSubmit={handleSubmit}>
              {/* Basic Information */}
              <FormGroup label="Namespace" isRequired fieldId="namespace">
                <NamespaceSelector
                  namespace={namespace}
                  onNamespaceChange={setNamespace}
                />
                <FormHelperText>
                  <HelperText>
                    <HelperTextItem>
                      The namespace where the agent will be deployed
                    </HelperTextItem>
                  </HelperText>
                </FormHelperText>
              </FormGroup>

              <FormGroup label="Agent Name" fieldId="name" isRequired>
                <TextInput
                  id="name"
                  value={name}
                  onChange={(_e, value) => setName(value)}
                  placeholder="my-agent (auto-generated if empty)"
                  validated={validated.name}
                />
                <FormHelperText>
                  <HelperText>
                    <HelperTextItem variant={validated.name === 'error' ? 'error' : 'default'}>
                      {validated.name === 'error'
                        ? 'Name must be lowercase alphanumeric with hyphens'
                        : 'Leave empty to auto-generate from source path or image name'}
                    </HelperTextItem>
                  </HelperText>
                </FormHelperText>
              </FormGroup>

              <Divider style={{ margin: '24px 0' }} />

              {/* Deployment Method Selection */}
              <Title headingLevel="h3" size="md" style={{ marginBottom: '16px' }}>
                Deployment Method
              </Title>

              <FormGroup role="radiogroup" fieldId="deployment-method">
                <Radio
                  id="method-source"
                  name="deployment-method"
                  label="Build from Source"
                  description="Build container image from a git repository"
                  isChecked={deploymentMethod === 'source'}
                  onChange={() => setDeploymentMethod('source')}
                />
                <Radio
                  id="method-image"
                  name="deployment-method"
                  label="Deploy from Existing Image"
                  description="Deploy using an existing container image"
                  isChecked={deploymentMethod === 'image'}
                  onChange={() => setDeploymentMethod('image')}
                  style={{ marginTop: '8px' }}
                />
              </FormGroup>

              <Divider style={{ margin: '24px 0' }} />

              {/* Build from Source Configuration */}
              {deploymentMethod === 'source' && (
                <>
                  <Title headingLevel="h3" size="md" style={{ marginBottom: '16px' }}>
                    Source Repository
                  </Title>

                  <FormGroup label="Git Repository URL" isRequired fieldId="gitUrl">
                    <TextInput
                      id="gitUrl"
                      value={gitUrl}
                      onChange={(_e, value) => setGitUrl(value)}
                      placeholder="https://github.com/org/repo"
                      validated={validated.gitUrl}
                    />
                  </FormGroup>

                  <FormGroup label="Git Branch" fieldId="gitBranch">
                    <TextInput
                      id="gitBranch"
                      value={gitBranch}
                      onChange={(_e, value) => setGitBranch(value)}
                      placeholder="main"
                    />
                  </FormGroup>

                  <FormGroup label="Select Example" fieldId="example">
                    <FormSelect
                      id="example"
                      value={selectedExample}
                      onChange={(_e, value) => handleExampleChange(value)}
                    >
                      {AGENT_EXAMPLES.map((ex) => (
                        <FormSelectOption key={ex.value} value={ex.value} label={ex.label} />
                      ))}
                    </FormSelect>
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem>Or enter a custom path below</HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                  </FormGroup>

                  <FormGroup label="Source Path" isRequired fieldId="gitPath">
                    <TextInput
                      id="gitPath"
                      value={gitPath}
                      onChange={(_e, value) => handlePathChange(value)}
                      placeholder="path/to/agent"
                      validated={validated.gitPath}
                    />
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem variant={validated.gitPath === 'error' ? 'error' : 'default'}>
                          {validated.gitPath === 'error'
                            ? 'Source path is required'
                            : 'Path to agent source within the repository'}
                        </HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                  </FormGroup>

                  <Divider style={{ margin: '24px 0' }} />

                  {/* Container Registry Configuration */}
                  <Title headingLevel="h3" size="md" style={{ marginBottom: '16px' }}>
                    Container Registry Configuration
                  </Title>

                  <FormGroup label="Container Registry" fieldId="registryType">
                    <FormSelect
                      id="registryType"
                      value={registryType}
                      onChange={(_e, value) => setRegistryType(value)}
                    >
                      {REGISTRY_OPTIONS.map((reg) => (
                        <FormSelectOption key={reg.value} value={reg.value} label={reg.label} />
                      ))}
                    </FormSelect>
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem>
                          Where the built container image will be pushed
                        </HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                  </FormGroup>

                  {registryType !== 'local' && (
                    <>
                      <FormGroup
                        label="Registry Namespace/Organization"
                        isRequired
                        fieldId="registryNamespace"
                      >
                        <TextInput
                          id="registryNamespace"
                          value={registryNamespace}
                          onChange={(_e, value) => setRegistryNamespace(value)}
                          placeholder="your-org-name"
                          validated={validated.registryNamespace}
                        />
                        <FormHelperText>
                          <HelperText>
                            <HelperTextItem>
                              Your organization or namespace in the registry
                            </HelperTextItem>
                          </HelperText>
                        </FormHelperText>
                      </FormGroup>

                      <FormGroup label="Registry Secret Name" fieldId="registrySecret">
                        <TextInput
                          id="registrySecret"
                          value={registrySecret}
                          onChange={(_e, value) => setRegistrySecret(value)}
                          placeholder={`${registryType}-registry-secret`}
                        />
                        <FormHelperText>
                          <HelperText>
                            <HelperTextItem>
                              Kubernetes secret containing registry credentials
                            </HelperTextItem>
                          </HelperText>
                        </FormHelperText>
                      </FormGroup>

                      <Alert
                        variant="info"
                        title="Authentication Required"
                        isInline
                        style={{ marginBottom: '16px' }}
                      >
                        Ensure the registry secret exists in the target namespace with push credentials.
                      </Alert>
                    </>
                  )}

                  <Divider style={{ margin: '24px 0' }} />

                  {/* Shipwright Build Configuration */}
                  <Title headingLevel="h3" size="md" style={{ marginBottom: '16px' }}>
                    Build Configuration
                  </Title>

                  {/* Shipwright is always used for source builds */}
                  <>
                      <FormGroup label="Build Strategy" fieldId="buildStrategy">
                        <BuildStrategySelector
                          value={buildStrategy}
                          onChange={setBuildStrategy}
                          registryType={registryType}
                        />
                      </FormGroup>

                      <ExpandableSection
                        toggleText="Advanced Build Options"
                        isExpanded={showBuildConfig}
                        onToggle={() => setShowBuildConfig(!showBuildConfig)}
                      >
                        <Card isFlat style={{ marginTop: '8px' }}>
                          <CardBody>
                            <FormGroup label="Dockerfile Path" fieldId="dockerfile">
                              <TextInput
                                id="dockerfile"
                                value={dockerfile}
                                onChange={(_e, value) => setDockerfile(value)}
                                placeholder="Dockerfile"
                              />
                              <FormHelperText>
                                <HelperText>
                                  <HelperTextItem>
                                    Path to the Dockerfile relative to the source context
                                  </HelperTextItem>
                                </HelperText>
                              </FormHelperText>
                            </FormGroup>

                            <FormGroup label="Build Timeout" fieldId="buildTimeout">
                              <TextInput
                                id="buildTimeout"
                                value={buildTimeout}
                                onChange={(_e, value) => setBuildTimeout(value)}
                                placeholder="15m"
                              />
                              <FormHelperText>
                                <HelperText>
                                  <HelperTextItem>
                                    Maximum time for the build (e.g., "15m", "1h")
                                  </HelperTextItem>
                                </HelperText>
                              </FormHelperText>
                            </FormGroup>

                            <FormGroup label="Build Arguments" fieldId="buildArgs">
                              {buildArgs.map((arg, index) => (
                                <Split hasGutter key={index} style={{ marginBottom: '8px' }}>
                                  <SplitItem isFilled>
                                    <TextInput
                                      aria-label="Build argument"
                                      value={arg}
                                      onChange={(_e, value) => updateBuildArg(index, value)}
                                      placeholder="KEY=value"
                                    />
                                  </SplitItem>
                                  <SplitItem>
                                    <Button
                                      variant="plain"
                                      onClick={() => removeBuildArg(index)}
                                      aria-label="Remove build argument"
                                      style={{ color: 'var(--pf-v5-global--danger-color--100)' }}
                                    >
                                      <TrashIcon />
                                    </Button>
                                  </SplitItem>
                                </Split>
                              ))}
                              <Button
                                variant="link"
                                icon={<PlusCircleIcon />}
                                onClick={addBuildArg}
                              >
                                Add Build Argument
                              </Button>
                              <FormHelperText>
                                <HelperText>
                                  <HelperTextItem>
                                    Build-time variables passed to the Dockerfile (KEY=value format)
                                  </HelperTextItem>
                                </HelperText>
                              </FormHelperText>
                            </FormGroup>
                          </CardBody>
                        </Card>
                      </ExpandableSection>
                    </>

                  {/* Start Command Override */}
                  <ExpandableSection
                    toggleText="Override Start Command"
                    isExpanded={showStartCommand}
                    onToggle={() => setShowStartCommand(!showStartCommand)}
                  >
                    <FormGroup label="Start Command" fieldId="startCommand">
                      <TextInput
                        id="startCommand"
                        value={startCommand}
                        onChange={(_e, value) => setStartCommand(value)}
                        placeholder="python main.py"
                      />
                      <FormHelperText>
                        <HelperText>
                          <HelperTextItem>
                            Command to start the agent (e.g., "python main.py", "uvicorn app:app")
                          </HelperTextItem>
                        </HelperText>
                      </FormHelperText>
                    </FormGroup>
                  </ExpandableSection>
                </>
              )}

              {/* Deploy from Existing Image Configuration */}
              {deploymentMethod === 'image' && (
                <>
                  <Title headingLevel="h3" size="md" style={{ marginBottom: '16px' }}>
                    Container Image
                  </Title>

                  <FormGroup label="Container Image" isRequired fieldId="containerImage">
                    <TextInput
                      id="containerImage"
                      value={containerImage}
                      onChange={(_e, value) => handleImageChange(value)}
                      placeholder="myrepo/my-agent"
                      validated={validated.containerImage}
                    />
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem variant={validated.containerImage === 'error' ? 'error' : 'default'}>
                          {validated.containerImage === 'error'
                            ? 'Container image is required'
                            : 'Full image path without tag (e.g., quay.io/myorg/my-agent)'}
                        </HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                  </FormGroup>

                  <FormGroup label="Image Tag" fieldId="imageTag">
                    <TextInput
                      id="imageTag"
                      value={imageTag}
                      onChange={(_e, value) => setImageTag(value)}
                      placeholder="latest"
                    />
                  </FormGroup>

                  <FormGroup label="Image Pull Secret" fieldId="imagePullSecret">
                    <TextInput
                      id="imagePullSecret"
                      value={imagePullSecret}
                      onChange={(_e, value) => setImagePullSecret(value)}
                      placeholder="Leave empty for public images"
                    />
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem>
                          Kubernetes secret containing credentials for private registries
                        </HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                  </FormGroup>
                </>
              )}

              <Divider style={{ margin: '24px 0' }} />

              {/* Framework Selection */}
              <FormGroup label="Framework" fieldId="framework">
                <FormSelect
                  id="framework"
                  value={framework}
                  onChange={(_e, value) => setFramework(value)}
                >
                  {FRAMEWORKS.map((fw) => (
                    <FormSelectOption key={fw.value} value={fw.value} label={fw.label} />
                  ))}
                </FormSelect>
              </FormGroup>

              {/* Workload Type Selection */}
              <FormGroup label="Workload Type" fieldId="workloadType">
                <FormSelect
                  id="workloadType"
                  value={workloadType}
                  onChange={(_e, value) => setWorkloadType(value as 'deployment' | 'statefulset' | 'job')}
                  aria-label="Workload type selector"
                >
                  <FormSelectOption value="deployment" label="Deployment (Recommended)" />
                  <FormSelectOption value="statefulset" label="StatefulSet" />
                  <FormSelectOption value="job" label="Job" />
                </FormSelect>
                <FormHelperText>
                  <HelperText>
                    <HelperTextItem>
                      {workloadType === 'deployment' && 'Standard deployment for long-running agents with auto-restart'}
                      {workloadType === 'statefulset' && 'For stateful agents requiring stable network identity and persistent storage'}
                      {workloadType === 'job' && 'For batch/one-time agents that run to completion'}
                    </HelperTextItem>
                  </HelperText>
                </FormHelperText>
              </FormGroup>

              {/* HTTPRoute/Route Creation */}
              <FormGroup fieldId="createHttpRoute">
                <Checkbox
                  id="createHttpRoute"
                  label="Enable external access to the agent endpoint"
                  isChecked={createHttpRoute}
                  onChange={(_e, checked) => setCreateHttpRoute(checked)}
                />
              </FormGroup>

              {/* Pod Configuration */}
              <ExpandableSection
                toggleText={`Pod Configuration (${servicePorts.length} port${servicePorts.length !== 1 ? 's' : ''})`}
                isExpanded={showPodConfig}
                onToggle={() => setShowPodConfig(!showPodConfig)}
              >
                <Card isFlat style={{ marginTop: '8px' }}>
                  <CardBody>
                    <Text component="p" style={{ marginBottom: '16px' }}>
                      Configure service ports for the agent pod.
                    </Text>

                    {servicePorts.map((port, index) => (
                      <Grid hasGutter key={index} style={{ marginBottom: '8px' }}>
                        <GridItem span={3}>
                          <TextInput
                            aria-label="Port name"
                            value={port.name}
                            onChange={(_e, value) => updateServicePort(index, 'name', value)}
                            placeholder="http"
                          />
                          {index === 0 && (
                            <FormHelperText>
                              <HelperText>
                                <HelperTextItem>Port Name</HelperTextItem>
                              </HelperText>
                            </FormHelperText>
                          )}
                        </GridItem>
                        <GridItem span={2}>
                          <NumberInput
                            value={port.port}
                            min={1}
                            max={65535}
                            onMinus={() => updateServicePort(index, 'port', port.port - 1)}
                            onPlus={() => updateServicePort(index, 'port', port.port + 1)}
                            onChange={(event) => {
                              const target = event.target as HTMLInputElement;
                              updateServicePort(index, 'port', parseInt(target.value, 10) || 8080);
                            }}
                            inputAriaLabel="Service port"
                          />
                          {index === 0 && (
                            <FormHelperText>
                              <HelperText>
                                <HelperTextItem>Service Port</HelperTextItem>
                              </HelperText>
                            </FormHelperText>
                          )}
                        </GridItem>
                        <GridItem span={2}>
                          <NumberInput
                            value={port.targetPort}
                            min={1}
                            max={65535}
                            onMinus={() => updateServicePort(index, 'targetPort', port.targetPort - 1)}
                            onPlus={() => updateServicePort(index, 'targetPort', port.targetPort + 1)}
                            onChange={(event) => {
                              const target = event.target as HTMLInputElement;
                              updateServicePort(index, 'targetPort', parseInt(target.value, 10) || 8000);
                            }}
                            inputAriaLabel="Target port"
                          />
                          {index === 0 && (
                            <FormHelperText>
                              <HelperText>
                                <HelperTextItem>Target Port</HelperTextItem>
                              </HelperText>
                            </FormHelperText>
                          )}
                        </GridItem>
                        <GridItem span={2}>
                          <FormSelect
                            value={port.protocol}
                            onChange={(_e, value) => updateServicePort(index, 'protocol', value)}
                            aria-label="Protocol"
                          >
                            <FormSelectOption value="TCP" label="TCP" />
                            <FormSelectOption value="UDP" label="UDP" />
                          </FormSelect>
                          {index === 0 && (
                            <FormHelperText>
                              <HelperText>
                                <HelperTextItem>Protocol</HelperTextItem>
                              </HelperText>
                            </FormHelperText>
                          )}
                        </GridItem>
                        <GridItem span={1}>
                          <Button
                            variant="plain"
                            onClick={() => removeServicePort(index)}
                            aria-label="Remove port"
                            isDisabled={servicePorts.length <= 1}
                            style={{ color: 'var(--pf-v5-global--danger-color--100)' }}
                          >
                            <TrashIcon />
                          </Button>
                        </GridItem>
                      </Grid>
                    ))}

                    <Button
                      variant="link"
                      icon={<PlusCircleIcon />}
                      onClick={addServicePort}
                    >
                      Add Service Port
                    </Button>
                  </CardBody>
                </Card>
              </ExpandableSection>

              {/* Environment Variables */}
              <ExpandableSection
                toggleText={`Environment Variables (${envVars.length})`}
                isExpanded={showEnvVars}
                onToggle={() => setShowEnvVars(!showEnvVars)}
              >
                <Card isFlat style={{ marginTop: '8px' }}>
                  <CardBody>
                    <div style={{ marginBottom: '16px' }}>
                      <Button
                        variant="secondary"
                        icon={<UploadIcon />}
                        onClick={() => setShowImportModal(true)}
                        style={{ marginRight: '8px' }}
                      >
                        Import from File/URL
                      </Button>
                      <Button
                        variant="link"
                        icon={<PlusCircleIcon />}
                        onClick={addEnvVar}
                      >
                        Add Variable
                      </Button>
                    </div>

                    {envVars.map((env, index) => {
                      const envType = getEnvVarType(env);
                      return (
                        <Grid hasGutter key={index} style={{ marginBottom: '12px' }}>
                          <GridItem span={3}>
                            <TextInput
                              aria-label="Environment variable name"
                              value={env.name}
                              onChange={(_e, value) => updateEnvVar(index, 'name', value)}
                              placeholder="VAR_NAME"
                            />
                          </GridItem>
                          <GridItem span={2}>
                            <FormSelect
                              value={envType}
                              onChange={(_e, value) => handleEnvVarTypeChange(index, value as EnvVarType)}
                              aria-label="Variable type"
                            >
                              <FormSelectOption value="value" label="Direct Value" />
                              <FormSelectOption value="secret" label="Secret" />
                              <FormSelectOption value="configMap" label="ConfigMap" />
                            </FormSelect>
                          </GridItem>
                          <GridItem span={6}>
                            {envType === 'value' && (
                              <TextInput
                                aria-label="Environment variable value"
                                value={env.value || ''}
                                onChange={(_e, value) => updateEnvVar(index, 'value', value)}
                                placeholder="value"
                              />
                            )}
                            {envType === 'secret' && (
                              <Split hasGutter>
                                <SplitItem isFilled>
                                  <TextInput
                                    aria-label="Secret name"
                                    value={env.valueFrom?.secretKeyRef?.name || ''}
                                    onChange={(_e, value) => updateEnvVarSecret(index, 'name', value)}
                                    placeholder="secret-name"
                                  />
                                </SplitItem>
                                <SplitItem isFilled>
                                  <TextInput
                                    aria-label="Secret key"
                                    value={env.valueFrom?.secretKeyRef?.key || ''}
                                    onChange={(_e, value) => updateEnvVarSecret(index, 'key', value)}
                                    placeholder="key"
                                  />
                                </SplitItem>
                              </Split>
                            )}
                            {envType === 'configMap' && (
                              <Split hasGutter>
                                <SplitItem isFilled>
                                  <TextInput
                                    aria-label="ConfigMap name"
                                    value={env.valueFrom?.configMapKeyRef?.name || ''}
                                    onChange={(_e, value) => updateEnvVarConfigMap(index, 'name', value)}
                                    placeholder="configmap-name"
                                  />
                                </SplitItem>
                                <SplitItem isFilled>
                                  <TextInput
                                    aria-label="ConfigMap key"
                                    value={env.valueFrom?.configMapKeyRef?.key || ''}
                                    onChange={(_e, value) => updateEnvVarConfigMap(index, 'key', value)}
                                    placeholder="key"
                                  />
                                </SplitItem>
                              </Split>
                            )}
                          </GridItem>
                          <GridItem span={1}>
                            <Button
                              variant="plain"
                              onClick={() => removeEnvVar(index)}
                              aria-label="Remove environment variable"
                              style={{ color: 'var(--pf-v5-global--danger-color--100)' }}
                            >
                              <TrashIcon />
                            </Button>
                          </GridItem>
                        </Grid>
                      );
                    })}

                    {envVars.length === 0 && (
                      <Text component="p" style={{ fontStyle: 'italic', color: 'var(--pf-v5-global--Color--200)' }}>
                        No environment variables configured. Click "Import from File/URL" or "Add Variable" to get started.
                      </Text>
                    )}
                  </CardBody>
                </Card>
              </ExpandableSection>

              <ActionGroup style={{ marginTop: '24px' }}>
                <Button
                  variant="primary"
                  type="submit"
                  isLoading={createMutation.isPending}
                  isDisabled={createMutation.isPending}
                >
                  {createMutation.isPending
                    ? 'Creating...'
                    : deploymentMethod === 'source'
                      ? 'Build & Deploy Agent'
                      : 'Deploy Agent'}
                </Button>
                <Button variant="link" onClick={() => navigate('/agents')}>
                  Cancel
                </Button>
              </ActionGroup>
            </Form>
          </CardBody>
        </Card>

        {/* Developer Resources */}
        <Alert
          variant="info"
          title="Agent Developer Resources"
          isInline
          style={{ marginTop: '24px' }}
        >
          New to agent development? Check our{' '}
          <a
            href="https://github.com/kagenti/kagenti/blob/main/PERSONAS_AND_ROLES.md#11-agent-developer"
            target="_blank"
            rel="noopener noreferrer"
          >
            Agent Developer guide
          </a>{' '}
          and{' '}
          <a
            href="https://github.com/kagenti/agent-examples"
            target="_blank"
            rel="noopener noreferrer"
          >
            agent-examples repository
          </a>
          .
        </Alert>
      </PageSection>

      {/* Import Modal */}
      <EnvImportModal
        isOpen={showImportModal}
        onClose={() => setShowImportModal(false)}
        onImport={handleImportEnvVars}
        defaultUrl={getDefaultEnvUrl()}
      />
    </>
  );
};
