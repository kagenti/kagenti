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
  NumberInput,
  Grid,
  GridItem,
  Checkbox,
  Radio,
} from '@patternfly/react-core';
import { TrashIcon, PlusCircleIcon } from '@patternfly/react-icons';
import { useMutation } from '@tanstack/react-query';

import { toolService, ShipwrightBuildConfig } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';
import { BuildStrategySelector } from '@/components/BuildStrategySelector';

const PROTOCOLS = [
  { value: 'streamable_http', label: 'Streamable HTTP' },
  { value: 'sse', label: 'Server-Sent Events (SSE)' },
];

// Example MCP tool subfolders
const TOOL_EXAMPLES = [
  { value: '', label: 'Select an example...' },
  { value: 'mcp/weather_tool', label: 'Weather Tool' },
  { value: 'mcp/flight_tool', label: 'Flight Tool' },
  { value: 'mcp/github_tool', label: 'GitHub Tool' },
  { value: 'mcp/image_tool', label: 'Image Tool' },
  { value: 'mcp/movie_tool', label: 'Movie Tool' },
  { value: 'mcp/reservation_tool', label: 'Reservation Tool' },
  { value: 'mcp/slack_tool', label: 'Slack Tool' },
  { value: 'mcp/cloud_storage_tool', label: 'Cloud Storage Tool' },
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
  value: string;
}

interface ServicePort {
  name: string;
  port: number;
  targetPort: number;
  protocol: 'TCP' | 'UDP';
}

export const ImportToolPage: React.FC = () => {
  const navigate = useNavigate();

  // Deployment method
  const [deploymentMethod, setDeploymentMethod] = useState<DeploymentMethod>('image');

  // Form state
  const [namespace, setNamespace] = useState('team1');
  const [name, setName] = useState('');
  const [protocol, setProtocol] = useState('streamable_http');

  // Build from source state
  const [gitUrl, setGitUrl] = useState(DEFAULT_REPO_URL);
  const [gitBranch, setGitBranch] = useState(DEFAULT_BRANCH);
  const [gitPath, setGitPath] = useState('');
  const [selectedExample, setSelectedExample] = useState('');

  // Registry configuration (for build from source)
  const [registryType, setRegistryType] = useState('local');
  const [registryNamespace, setRegistryNamespace] = useState('');
  const [registrySecret, setRegistrySecret] = useState('');
  const [imageTag, setImageTag] = useState('v0.0.1');

  // Update registry secret default when registry type changes
  React.useEffect(() => {
    if (registryType !== 'local') {
      setRegistrySecret(`${registryType}-registry-secret`);
    } else {
      setRegistrySecret('');
    }
  }, [registryType]);

  // Shipwright build configuration
  const [buildStrategy, setBuildStrategy] = useState('buildah-insecure-push');
  const [dockerfile, setDockerfile] = useState('Dockerfile');
  const [buildTimeout, setBuildTimeout] = useState('15m');
  const [buildArgs, setBuildArgs] = useState<string[]>([]);
  const [showBuildConfig, setShowBuildConfig] = useState(false);

  // Deploy from image state
  const [containerImage, setContainerImage] = useState('');
  const [imagePullSecret, setImagePullSecret] = useState('');

  // Pod configuration
  const [servicePorts, setServicePorts] = useState<ServicePort[]>([
    { name: 'http', port: 8000, targetPort: 8000, protocol: 'TCP' },
  ]);
  const [showPodConfig, setShowPodConfig] = useState(false);

  // Environment variables
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [showEnvVars, setShowEnvVars] = useState(false);

  // Workload type
  const [workloadType, setWorkloadType] = useState<'deployment' | 'statefulset'>('deployment');
  const [persistentStorageSize, setPersistentStorageSize] = useState('1Gi');

  // HTTPRoute/Route creation
  const [createHttpRoute, setCreateHttpRoute] = useState(false);

  // Validation state
  const [validated, setValidated] = useState<Record<string, 'success' | 'error' | 'default'>>({});

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof toolService.create>[0]) =>
      toolService.create(data),
    onSuccess: () => {
      const finalName = name || getNameFromPath();
      // Navigate to build progress page for source builds
      if (deploymentMethod === 'source') {
        navigate(`/tools/${namespace}/${finalName}/build`);
      } else {
        navigate(`/tools/${namespace}/${finalName}`);
      }
    },
  });

  const getNameFromPath = () => {
    if (deploymentMethod === 'image') {
      // Extract name from image URL
      if (!containerImage) return '';
      const parts = containerImage.split('/');
      const imageName = parts[parts.length - 1].split(':')[0];
      return imageName.replace(/_/g, '-').toLowerCase();
    }
    // Extract name from git path
    const path = gitPath || selectedExample;
    if (!path) return '';
    const parts = path.split('/');
    return parts[parts.length - 1].replace(/_/g, '-').toLowerCase();
  };

  const getNameFromImage = () => {
    if (!containerImage) return '';
    const parts = containerImage.split('/');
    const imageName = parts[parts.length - 1].split(':')[0];
    return imageName.replace(/_/g, '-').toLowerCase();
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
    // Auto-generate name from path
    if (value && !name) {
      const parts = value.split('/');
      const autoName = parts[parts.length - 1].replace(/_/g, '-').toLowerCase();
      setName(autoName);
    }
  };

  // Build registry URL from configuration
  const getRegistryUrl = () => {
    const registry = REGISTRY_OPTIONS.find((r) => r.value === registryType);
    if (!registry) return '';
    if (registryType === 'local') {
      return registry.url;
    }
    return registryNamespace ? `${registry.url}/${registryNamespace}` : registry.url;
  };

  const handleImageChange = (value: string) => {
    setContainerImage(value);
    if (value && !name) {
      setName(getNameFromImage());
    }
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

  // Service port handlers
  const addServicePort = () => {
    setServicePorts([
      ...servicePorts,
      { name: 'http', port: 8000, targetPort: 8000, protocol: 'TCP' },
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
      const finalPath = gitPath || selectedExample;
      if (!finalPath) {
        newValidated.gitPath = 'error';
        isValid = false;
      } else {
        newValidated.gitPath = 'success';
      }

      // Registry namespace validation for external registries
      if (registryType !== 'local' && !registryNamespace) {
        newValidated.registryNamespace = 'error';
        isValid = false;
      } else {
        newValidated.registryNamespace = 'success';
      }
    } else {
      // Container image validation for image deployment
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
      // Build Shipwright configuration
      const shipwrightConfig: ShipwrightBuildConfig = {
        buildStrategy,
        dockerfile,
        buildTimeout,
        buildArgs: buildArgs.filter((arg) => arg.trim()),
      };

      createMutation.mutate({
        name: finalName,
        namespace,
        protocol,
        framework: 'Python',
        workloadType,
        persistentStorage: workloadType === 'statefulset'
          ? { enabled: true, size: persistentStorageSize }
          : undefined,
        deploymentMethod: 'source',
        gitUrl,
        gitRevision: gitBranch,
        contextDir: gitPath || selectedExample,
        registryUrl: getRegistryUrl(),
        registrySecret: registrySecret || undefined,
        imageTag,
        shipwrightConfig,
        envVars: envVars.filter((ev) => ev.name && ev.value),
        servicePorts: showPodConfig ? servicePorts : undefined,
        createHttpRoute,
      });
    } else {
      // Image deployment
      const fullImage = imageTag ? `${containerImage}:${imageTag}` : containerImage;

      createMutation.mutate({
        name: finalName,
        namespace,
        deploymentMethod: 'image',
        containerImage: fullImage,
        protocol,
        framework: 'Python',
        workloadType,
        persistentStorage: workloadType === 'statefulset'
          ? { enabled: true, size: persistentStorageSize }
          : undefined,
        envVars: envVars.filter((ev) => ev.name && ev.value),
        imagePullSecret: imagePullSecret || undefined,
        servicePorts: showPodConfig ? servicePorts : undefined,
        createHttpRoute,
      });
    }
  };

  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">Import New Tool</Title>
          <Text component="p">
            Build from source or deploy an existing container image as an MCP tool.
          </Text>
        </TextContent>
      </PageSection>

      <PageSection>
        <Card>
          <CardTitle>Tool Configuration</CardTitle>
          <CardBody>
            {createMutation.isError && (
              <Alert
                variant="danger"
                title="Failed to create tool"
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
                      The namespace where the tool will be deployed
                    </HelperTextItem>
                  </HelperText>
                </FormHelperText>
              </FormGroup>

              <FormGroup label="Tool Name" fieldId="name" isRequired>
                <TextInput
                  id="name"
                  value={name}
                  onChange={(_e, value) => setName(value)}
                  placeholder="my-tool (auto-generated if empty)"
                  validated={validated.name}
                />
                <FormHelperText>
                  <HelperText>
                    <HelperTextItem variant={validated.name === 'error' ? 'error' : 'default'}>
                      {validated.name === 'error'
                        ? 'Name must be lowercase alphanumeric with hyphens'
                        : 'Leave empty to auto-generate from path or image name'}
                    </HelperTextItem>
                  </HelperText>
                </FormHelperText>
              </FormGroup>

              <Divider style={{ margin: '24px 0' }} />

              {/* Deployment Method Selection */}
              <Title headingLevel="h3" size="md" style={{ marginBottom: '16px' }}>
                Deployment Method
              </Title>

              <FormGroup role="radiogroup" fieldId="deploymentMethod">
                <Radio
                  name="deploymentMethod"
                  label="Deploy from Image"
                  description="Deploy from an existing container image"
                  isChecked={deploymentMethod === 'image'}
                  onChange={() => setDeploymentMethod('image')}
                  id="deploymentMethod-image"
                />
                <Radio
                  name="deploymentMethod"
                  label="Build from Source"
                  description="Build container image from source code using Shipwright"
                  isChecked={deploymentMethod === 'source'}
                  onChange={() => setDeploymentMethod('source')}
                  id="deploymentMethod-source"
                  style={{ marginTop: '8px' }}
                />
              </FormGroup>

              <Divider style={{ margin: '24px 0' }} />

              {/* Build from Source Configuration */}
              {deploymentMethod === 'source' && (
                <>
                  <Title headingLevel="h3" size="md" style={{ marginBottom: '16px' }}>
                    Source Code
                  </Title>

                  <FormGroup label="Git Repository URL" isRequired fieldId="gitUrl">
                    <TextInput
                      id="gitUrl"
                      value={gitUrl}
                      onChange={(_e, value) => setGitUrl(value)}
                      placeholder="https://github.com/myorg/my-tools"
                      validated={validated.gitUrl}
                    />
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem variant={validated.gitUrl === 'error' ? 'error' : 'default'}>
                          {validated.gitUrl === 'error'
                            ? 'Git URL is required'
                            : 'HTTPS URL of the Git repository containing your tool'}
                        </HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                  </FormGroup>

                  <FormGroup label="Branch or Tag" fieldId="gitBranch">
                    <TextInput
                      id="gitBranch"
                      value={gitBranch}
                      onChange={(_e, value) => setGitBranch(value)}
                      placeholder="main"
                    />
                  </FormGroup>

                  <FormGroup label="Example Tools" fieldId="selectedExample">
                    <FormSelect
                      id="selectedExample"
                      value={selectedExample}
                      onChange={(_e, value) => handleExampleChange(value)}
                    >
                      {TOOL_EXAMPLES.map((example) => (
                        <FormSelectOption
                          key={example.value}
                          value={example.value}
                          label={example.label}
                        />
                      ))}
                    </FormSelect>
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem>
                          Select a pre-configured example or enter a custom path below
                        </HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                  </FormGroup>

                  <FormGroup label="Source Subfolder" isRequired fieldId="gitPath">
                    <TextInput
                      id="gitPath"
                      value={gitPath}
                      onChange={(_e, value) => handlePathChange(value)}
                      placeholder="mcp/my_tool"
                      validated={validated.gitPath}
                    />
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem variant={validated.gitPath === 'error' ? 'error' : 'default'}>
                          {validated.gitPath === 'error'
                            ? 'Source subfolder is required'
                            : 'Path to the tool directory within the repository'}
                        </HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                  </FormGroup>

                  <Divider style={{ margin: '24px 0' }} />

                  <Title headingLevel="h3" size="md" style={{ marginBottom: '16px' }}>
                    Container Registry
                  </Title>

                  <FormGroup label="Registry" fieldId="registryType">
                    <FormSelect
                      id="registryType"
                      value={registryType}
                      onChange={(_e, value) => setRegistryType(value)}
                    >
                      {REGISTRY_OPTIONS.map((registry) => (
                        <FormSelectOption
                          key={registry.value}
                          value={registry.value}
                          label={registry.label}
                        />
                      ))}
                    </FormSelect>
                  </FormGroup>

                  {registryType !== 'local' && (
                    <FormGroup label="Registry Namespace" isRequired fieldId="registryNamespace">
                      <TextInput
                        id="registryNamespace"
                        value={registryNamespace}
                        onChange={(_e, value) => setRegistryNamespace(value)}
                        placeholder="myorg"
                        validated={validated.registryNamespace}
                      />
                      <FormHelperText>
                        <HelperText>
                          <HelperTextItem variant={validated.registryNamespace === 'error' ? 'error' : 'default'}>
                            {validated.registryNamespace === 'error'
                              ? 'Registry namespace is required for external registries'
                              : 'Your username or organization name in the registry'}
                          </HelperTextItem>
                        </HelperText>
                      </FormHelperText>
                    </FormGroup>
                  )}

                  <FormGroup label="Registry Secret" fieldId="registrySecret">
                    <TextInput
                      id="registrySecret"
                      value={registrySecret}
                      onChange={(_e, value) => setRegistrySecret(value)}
                      placeholder="Leave empty for public registries"
                    />
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem>
                          Kubernetes secret containing registry credentials
                        </HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                  </FormGroup>

                  <FormGroup label="Image Tag" fieldId="imageTag">
                    <TextInput
                      id="imageTag"
                      value={imageTag}
                      onChange={(_e, value) => setImageTag(value)}
                      placeholder="v0.0.1"
                    />
                  </FormGroup>

                  <Divider style={{ margin: '24px 0' }} />

                  {/* Build Configuration */}
                  <ExpandableSection
                    toggleText="Build Configuration (Advanced)"
                    isExpanded={showBuildConfig}
                    onToggle={() => setShowBuildConfig(!showBuildConfig)}
                  >
                    <Card isFlat style={{ marginTop: '8px' }}>
                      <CardBody>
                        <FormGroup label="Build Strategy" fieldId="buildStrategy">
                          <BuildStrategySelector
                            value={buildStrategy}
                            onChange={setBuildStrategy}
                            registryType={registryType}
                          />
                        </FormGroup>

                        <FormGroup label="Dockerfile" fieldId="dockerfile">
                          <TextInput
                            id="dockerfile"
                            value={dockerfile}
                            onChange={(_e, value) => setDockerfile(value)}
                            placeholder="Dockerfile"
                          />
                        </FormGroup>

                        <FormGroup label="Build Timeout" fieldId="buildTimeout">
                          <TextInput
                            id="buildTimeout"
                            value={buildTimeout}
                            onChange={(_e, value) => setBuildTimeout(value)}
                            placeholder="15m"
                          />
                        </FormGroup>

                        <FormGroup label="Build Arguments" fieldId="buildArgs">
                          {buildArgs.map((arg, index) => (
                            <Split hasGutter key={index} style={{ marginBottom: '8px' }}>
                              <SplitItem isFilled>
                                <TextInput
                                  aria-label="Build argument"
                                  value={arg}
                                  onChange={(_e, value) => {
                                    const updated = [...buildArgs];
                                    updated[index] = value;
                                    setBuildArgs(updated);
                                  }}
                                  placeholder="KEY=VALUE"
                                />
                              </SplitItem>
                              <SplitItem>
                                <Button
                                  variant="plain"
                                  onClick={() => setBuildArgs(buildArgs.filter((_, i) => i !== index))}
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
                            onClick={() => setBuildArgs([...buildArgs, ''])}
                          >
                            Add Build Argument
                          </Button>
                        </FormGroup>
                      </CardBody>
                    </Card>
                  </ExpandableSection>
                </>
              )}

              {/* Deploy from Image Configuration */}
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
                      placeholder="quay.io/myorg/my-tool"
                      validated={validated.containerImage}
                    />
                    <FormHelperText>
                      <HelperText>
                        <HelperTextItem variant={validated.containerImage === 'error' ? 'error' : 'default'}>
                          {validated.containerImage === 'error'
                            ? 'Container image is required'
                            : 'Full image path without tag (e.g., quay.io/myorg/my-tool)'}
                        </HelperTextItem>
                      </HelperText>
                    </FormHelperText>
                  </FormGroup>

                  <FormGroup label="Image Tag" fieldId="imageTagImage">
                    <TextInput
                      id="imageTagImage"
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

              {/* Workload Type */}
              <Title headingLevel="h3" size="md" style={{ marginBottom: '16px' }}>
                Workload Type
              </Title>

              <FormGroup role="radiogroup" fieldId="workloadType">
                <Radio
                  name="workloadType"
                  label="Deployment"
                  description="Standard Kubernetes Deployment (default, stateless workload)"
                  isChecked={workloadType === 'deployment'}
                  onChange={() => setWorkloadType('deployment')}
                  id="workloadType-deployment"
                />
                <Radio
                  name="workloadType"
                  label="StatefulSet"
                  description="Kubernetes StatefulSet with persistent storage (for tools that need data persistence)"
                  isChecked={workloadType === 'statefulset'}
                  onChange={() => setWorkloadType('statefulset')}
                  id="workloadType-statefulset"
                  style={{ marginTop: '8px' }}
                />
              </FormGroup>

              {workloadType === 'statefulset' && (
                <FormGroup label="Persistent Volume Size" fieldId="persistentStorageSize">
                  <TextInput
                    id="persistentStorageSize"
                    value={persistentStorageSize}
                    onChange={(_e, value) => setPersistentStorageSize(value)}
                    placeholder="1Gi"
                  />
                  <FormHelperText>
                    <HelperText>
                      <HelperTextItem>
                        Size of the persistent volume claim (e.g., 1Gi, 5Gi, 10Gi)
                      </HelperTextItem>
                    </HelperText>
                  </FormHelperText>
                </FormGroup>
              )}

              <Divider style={{ margin: '24px 0' }} />

              {/* MCP Configuration */}
              <FormGroup label="MCP Transport Protocol" fieldId="protocol">
                <FormSelect
                  id="protocol"
                  value={protocol}
                  onChange={(_e, value) => setProtocol(value)}
                >
                  {PROTOCOLS.map((p) => (
                    <FormSelectOption key={p.value} value={p.value} label={p.label} />
                  ))}
                </FormSelect>
                <FormHelperText>
                  <HelperText>
                    <HelperTextItem>
                      Transport protocol for the MCP server
                    </HelperTextItem>
                  </HelperText>
                </FormHelperText>
              </FormGroup>

              {/* HTTPRoute/Route Creation */}
              <FormGroup fieldId="createHttpRoute">
                <Checkbox
                  id="createHttpRoute"
                  label="Enable external access to the tool endpoint"
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
                      Configure service ports for the tool pod.
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
                              updateServicePort(index, 'port', parseInt(target.value, 10) || 8000);
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
                    {envVars.map((env, index) => (
                      <Split hasGutter key={index} style={{ marginBottom: '8px' }}>
                        <SplitItem isFilled>
                          <TextInput
                            aria-label="Environment variable name"
                            value={env.name}
                            onChange={(_e, value) => updateEnvVar(index, 'name', value)}
                            placeholder="VAR_NAME"
                          />
                        </SplitItem>
                        <SplitItem isFilled>
                          <TextInput
                            aria-label="Environment variable value"
                            value={env.value}
                            onChange={(_e, value) => updateEnvVar(index, 'value', value)}
                            placeholder="value"
                          />
                        </SplitItem>
                        <SplitItem>
                          <Button
                            variant="plain"
                            onClick={() => removeEnvVar(index)}
                            aria-label="Remove environment variable"
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
                      onClick={addEnvVar}
                    >
                      Add Environment Variable
                    </Button>
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
                    ? deploymentMethod === 'source'
                      ? 'Starting Build...'
                      : 'Deploying...'
                    : deploymentMethod === 'source'
                      ? 'Build & Deploy Tool'
                      : 'Deploy Tool'}
                </Button>
                <Button variant="link" onClick={() => navigate('/tools')}>
                  Cancel
                </Button>
              </ActionGroup>
            </Form>
          </CardBody>
        </Card>

        {/* Developer Resources */}
        <Alert
          variant="info"
          title="MCP Tool Developer Resources"
          isInline
          style={{ marginTop: '24px' }}
        >
          New to MCP tool development? Check the{' '}
          <a
            href="https://modelcontextprotocol.io/introduction"
            target="_blank"
            rel="noopener noreferrer"
          >
            Model Context Protocol documentation
          </a>{' '}
          and{' '}
          <a
            href="https://github.com/kagenti/agent-examples/tree/main/mcp"
            target="_blank"
            rel="noopener noreferrer"
          >
            example MCP tools
          </a>
          .
        </Alert>
      </PageSection>
    </>
  );
};
