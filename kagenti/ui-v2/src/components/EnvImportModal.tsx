// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useEffect } from 'react';
import {
  Modal,
  ModalVariant,
  Button,
  Form,
  FormGroup,
  TextInput,
  Alert,
  Tabs,
  Tab,
  TabTitleText,
  FileUpload,
  Card,
  CardBody,
  CardTitle,
  Text,
  TextContent,
  List,
  ListItem,
  Spinner,
} from '@patternfly/react-core';
import { CheckCircleIcon, ExclamationCircleIcon, UploadIcon } from '@patternfly/react-icons';
import { agentService } from '@/services/api';

export interface EnvVar {
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

interface EnvImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onImport: (envVars: EnvVar[]) => void;
  defaultUrl?: string;
}

export const EnvImportModal: React.FC<EnvImportModalProps> = ({ isOpen, onClose, onImport, defaultUrl }) => {
  const [activeTabKey, setActiveTabKey] = useState<string | number>(defaultUrl ? 'url' : 'file');
  const [fileContent, setFileContent] = useState<string>('');
  const [fileName, setFileName] = useState('');
  const [url, setUrl] = useState(defaultUrl || '');
  const [previewVars, setPreviewVars] = useState<EnvVar[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isParsed, setIsParsed] = useState(false);

  // Update URL and tab when modal opens with a defaultUrl
  useEffect(() => {
    if (isOpen && defaultUrl) {
      setUrl(defaultUrl);
      setActiveTabKey('url');
    }
  }, [isOpen, defaultUrl]);

  const resetState = (preserveUrl = false) => {
    setFileContent('');
    setFileName('');
    if (!preserveUrl) {
      setUrl(defaultUrl || '');
    }
    setPreviewVars([]);
    setWarnings([]);
    setError(null);
    setIsParsed(false);
  };

  const handleClose = () => {
    resetState();
    onClose();
  };

  const handleTextChange = (_event: React.ChangeEvent<HTMLTextAreaElement>, value: string) => {
    setFileContent(value);
    setIsParsed(false);
    setError(null);
  };

  const parseContent = async (content: string) => {
    if (!content.trim()) {
      setError('Content is empty');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await agentService.parseEnvFile(content);
      setPreviewVars(response.envVars);
      setWarnings(response.warnings || []);
      setIsParsed(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to parse .env file');
      setPreviewVars([]);
      setWarnings([]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFetchUrl = async () => {
    if (!url.trim()) {
      setError('Please enter a URL');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Fetch the content from URL
      const fetchResponse = await agentService.fetchEnvFromUrl(url);
      setFileContent(fetchResponse.content);

      // Parse the fetched content
      const parseResponse = await agentService.parseEnvFile(fetchResponse.content);
      setPreviewVars(parseResponse.envVars);
      setWarnings(parseResponse.warnings || []);
      setIsParsed(true);
    } catch (err: any) {
      console.error('Error fetching URL:', err);
      const detail = err.response?.data?.detail || err.message || 'Failed to fetch URL';
      setError(`Failed to fetch URL: ${detail}`);
      setPreviewVars([]);
      setWarnings([]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleImport = () => {
    if (previewVars.length === 0) {
      setError('No environment variables to import');
      return;
    }
    onImport(previewVars);
    handleClose();
  };

  const getEnvVarDisplay = (envVar: EnvVar): string => {
    if (envVar.value !== undefined) {
      return envVar.value;
    }
    if (envVar.valueFrom?.secretKeyRef) {
      return `Secret: ${envVar.valueFrom.secretKeyRef.name}/${envVar.valueFrom.secretKeyRef.key}`;
    }
    if (envVar.valueFrom?.configMapKeyRef) {
      return `ConfigMap: ${envVar.valueFrom.configMapKeyRef.name}/${envVar.valueFrom.configMapKeyRef.key}`;
    }
    return 'Unknown';
  };

  return (
    <Modal
      variant={ModalVariant.large}
      title="Import Environment Variables"
      isOpen={isOpen}
      onClose={handleClose}
      actions={[
        <Button
          key="import"
          variant="primary"
          onClick={handleImport}
          isDisabled={!isParsed || previewVars.length === 0 || isLoading}
          icon={<UploadIcon />}
        >
          Import {previewVars.length > 0 && `(${previewVars.length})`}
        </Button>,
        <Button key="cancel" variant="link" onClick={handleClose}>
          Cancel
        </Button>,
      ]}
    >
      <TextContent style={{ marginBottom: '16px' }}>
        <Text component="p">
          Import environment variables from a local .env file or a remote URL. Supports standard
          KEY=value format and extended JSON format for Kubernetes secret/configMap references.
        </Text>
      </TextContent>

      <Tabs
        activeKey={activeTabKey}
        onSelect={(_event, tabIndex) => {
          setActiveTabKey(tabIndex);
          resetState();
        }}
        aria-label="Import source tabs"
      >
        <Tab eventKey="file" title={<TabTitleText>Upload File</TabTitleText>}>
          <div style={{ marginTop: '16px' }}>
            <Form>
              <FormGroup label="Select .env file" fieldId="file-upload">
                <FileUpload
                  id="file-upload"
                  value={fileContent}
                  filename={fileName}
                  filenamePlaceholder="Drag and drop a .env file or click to upload"
                  onFileInputChange={(_event, file) => {
                    if (file) {
                      setFileName(file.name);
                      setError(null);
                      setIsParsed(false);

                      const reader = new FileReader();
                      reader.onload = (e) => {
                        const content = e.target?.result as string;
                        setFileContent(content);
                        parseContent(content);
                      };
                      reader.onerror = () => {
                        setError('Failed to read file');
                      };
                      reader.readAsText(file);
                    }
                  }}
                  onTextChange={handleTextChange}
                  onClearClick={() => {
                    setFileContent('');
                    setFileName('');
                    setIsParsed(false);
                    setPreviewVars([]);
                    setWarnings([]);
                  }}
                  browseButtonText="Choose file"
                  type="text"
                  allowEditingUploadedText
                />
              </FormGroup>

              {fileContent && !isParsed && (
                <Button variant="secondary" onClick={() => parseContent(fileContent)}>
                  Parse File
                </Button>
              )}
            </Form>
          </div>
        </Tab>

        <Tab eventKey="url" title={<TabTitleText>From URL</TabTitleText>}>
          <div style={{ marginTop: '16px' }}>
            <Form>
              <FormGroup label="URL" fieldId="url-input">
                <TextInput
                  id="url-input"
                  value={url}
                  onChange={(_e, value) => setUrl(value)}
                  placeholder="https://raw.githubusercontent.com/kagenti/agent-examples/main/a2a/git_issue_agent/.env.openai"
                  onKeyPress={(e) => {
                    if (e.key === 'Enter') {
                      handleFetchUrl();
                    }
                  }}
                />
              </FormGroup>

              <Button
                variant="primary"
                onClick={handleFetchUrl}
                isDisabled={!url.trim() || isLoading}
              >
                Fetch & Parse
              </Button>
            </Form>
          </div>
        </Tab>
      </Tabs>

      {isLoading && (
        <div style={{ marginTop: '16px', textAlign: 'center' }}>
          <Spinner size="lg" />
          <Text component="p" style={{ marginTop: '8px' }}>
            Processing...
          </Text>
        </div>
      )}

      {error && (
        <Alert
          variant="danger"
          title="Error"
          isInline
          style={{ marginTop: '16px' }}
          actionClose={<Button variant="plain" onClick={() => setError(null)} />}
        >
          {error}
        </Alert>
      )}

      {warnings.length > 0 && (
        <Alert variant="warning" title="Parsing Warnings" isInline style={{ marginTop: '16px' }}>
          <List>
            {warnings.map((warning, index) => (
              <ListItem key={index}>
                <ExclamationCircleIcon /> {warning}
              </ListItem>
            ))}
          </List>
        </Alert>
      )}

      {isParsed && previewVars.length > 0 && (
        <Card style={{ marginTop: '16px' }}>
          <CardTitle>
            <CheckCircleIcon color="var(--pf-v5-global--success-color--100)" /> Preview (
            {previewVars.length} variable{previewVars.length !== 1 ? 's' : ''})
          </CardTitle>
          <CardBody>
            <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)' }}>
                    <th style={{ padding: '8px', textAlign: 'left', fontWeight: 'bold' }}>Name</th>
                    <th style={{ padding: '8px', textAlign: 'left', fontWeight: 'bold' }}>Value</th>
                  </tr>
                </thead>
                <tbody>
                  {previewVars.map((envVar, index) => (
                    <tr
                      key={index}
                      style={{
                        borderBottom: '1px solid var(--pf-v5-global--BorderColor--100)',
                      }}
                    >
                      <td
                        style={{
                          padding: '8px',
                          fontFamily: 'monospace',
                          fontWeight: 'bold',
                        }}
                      >
                        {envVar.name}
                      </td>
                      <td
                        style={{
                          padding: '8px',
                          fontFamily: 'monospace',
                          wordBreak: 'break-all',
                        }}
                      >
                        {getEnvVarDisplay(envVar)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      )}

      {isParsed && previewVars.length === 0 && !error && (
        <Alert variant="info" title="No Variables Found" isInline style={{ marginTop: '16px' }}>
          The file contains no valid environment variables.
        </Alert>
      )}
    </Modal>
  );
};
