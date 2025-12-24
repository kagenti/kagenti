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
} from '@patternfly/react-core';
import { TrashIcon, PlusCircleIcon } from '@patternfly/react-icons';
import { useMutation } from '@tanstack/react-query';

import { toolService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';

const PROTOCOLS = [
  { value: 'streamable_http', label: 'Streamable HTTP' },
  { value: 'sse', label: 'Server-Sent Events (SSE)' },
];

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

  // Form state
  const [namespace, setNamespace] = useState('team1');
  const [name, setName] = useState('');
  const [containerImage, setContainerImage] = useState('');
  const [imageTag, setImageTag] = useState('latest');
  const [protocol, setProtocol] = useState('streamable_http');
  const [imagePullSecret, setImagePullSecret] = useState('');

  // Pod configuration
  const [servicePorts, setServicePorts] = useState<ServicePort[]>([
    { name: 'http', port: 8000, targetPort: 8000, protocol: 'TCP' },
  ]);
  const [showPodConfig, setShowPodConfig] = useState(false);

  // Environment variables
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [showEnvVars, setShowEnvVars] = useState(false);

  // Validation state
  const [validated, setValidated] = useState<Record<string, 'success' | 'error' | 'default'>>({});

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof toolService.create>[0]) =>
      toolService.create(data),
    onSuccess: () => {
      navigate(`/tools/${namespace}/${name || getNameFromImage()}`);
    },
  });

  const getNameFromImage = () => {
    if (!containerImage) return '';
    const parts = containerImage.split('/');
    const imageName = parts[parts.length - 1].split(':')[0];
    return imageName.replace(/_/g, '-').toLowerCase();
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
    const finalName = name || getNameFromImage();
    if (!finalName) {
      newValidated.name = 'error';
      isValid = false;
    } else if (!/^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/.test(finalName)) {
      newValidated.name = 'error';
      isValid = false;
    } else {
      newValidated.name = 'success';
    }

    // Container image validation
    if (!containerImage) {
      newValidated.containerImage = 'error';
      isValid = false;
    } else {
      newValidated.containerImage = 'success';
    }

    setValidated(newValidated);
    return isValid;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    const finalName = name || getNameFromImage();
    const fullImage = imageTag ? `${containerImage}:${imageTag}` : containerImage;

    createMutation.mutate({
      name: finalName,
      namespace,
      containerImage: fullImage,
      protocol,
      framework: 'Python',
      envVars: envVars.filter((ev) => ev.name && ev.value),
      imagePullSecret: imagePullSecret || undefined,
      servicePorts: showPodConfig ? servicePorts : undefined,
    });
  };

  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">Import New Tool</Title>
          <Text component="p">
            Deploy an MCP tool from an existing container image.
          </Text>
        </TextContent>
      </PageSection>

      <PageSection>
        <Alert
          variant="info"
          title="Tools are deployed from container images"
          isInline
          style={{ marginBottom: '16px' }}
        >
          Unlike agents, MCP tools are deployed directly from pre-built container images.
          Building from source is not supported for tools.
        </Alert>

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
                        : 'Leave empty to auto-generate from image name'}
                    </HelperTextItem>
                  </HelperText>
                </FormHelperText>
              </FormGroup>

              <Divider style={{ margin: '24px 0' }} />

              {/* Container Image */}
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
                  {createMutation.isPending ? 'Deploying...' : 'Deploy Tool'}
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
