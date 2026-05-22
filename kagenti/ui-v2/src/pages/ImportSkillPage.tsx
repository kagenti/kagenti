// Copyright 2026 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState, useEffect } from 'react';
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
  TextArea,
  Button,
  Alert,
  ActionGroup,
  HelperText,
  HelperTextItem,
  Split,
  SplitItem,
  List,
  ListItem,
  Label,
  Spinner,
} from '@patternfly/react-core';
import { PlusCircleIcon, TrashIcon, GithubIcon } from '@patternfly/react-icons';
import { useMutation } from '@tanstack/react-query';

import { skillService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';
import { importSkillFromGitHub, isValidGitHubUrl } from '@/utils/githubSkillImporter';

interface AdditionalFile {
  id: string;
  path: string;
  content: string;
}

export const ImportSkillPage: React.FC = () => {
  const navigate = useNavigate();

  const [namespace, setNamespace] = useState<string>('team1');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [url, setUrl] = useState('');
  const [skillMdContent, setSkillMdContent] = useState('');
  const [additionalFiles, setAdditionalFiles] = useState<AdditionalFile[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importSuccess, setImportSuccess] = useState(false);

  const addFile = () => {
    setAdditionalFiles([
      ...additionalFiles,
      { id: Date.now().toString(), path: '', content: '' },
    ]);
  };

  const removeFile = (id: string) => {
    setAdditionalFiles(additionalFiles.filter((f) => f.id !== id));
  };

  const updateFilePath = (id: string, path: string) => {
    setAdditionalFiles(
      additionalFiles.map((f) => (f.id === id ? { ...f, path } : f))
    );
  };

  const updateFileContent = (id: string, content: string) => {
    setAdditionalFiles(
      additionalFiles.map((f) => (f.id === id ? { ...f, content } : f))
    );
  };

  // Auto-import from GitHub URL when it changes
  useEffect(() => {
    const importFromGitHub = async () => {
      // Only proceed if URL is valid and not already importing
      if (!url.trim() || !isValidGitHubUrl(url) || isImporting) {
        return;
      }

      setIsImporting(true);
      setImportError(null);
      setImportSuccess(false);

      try {
        const importedData = await importSkillFromGitHub(url);

        // Only fill empty fields (don't overwrite existing content)
        if (!name && importedData.name) {
          setName(importedData.name);
        }
        if (!description && importedData.description) {
          setDescription(importedData.description);
        }
        if (!category && importedData.category) {
          setCategory(importedData.category);
        }
        if (!skillMdContent && importedData.skillMdContent) {
          setSkillMdContent(importedData.skillMdContent);
        }

        // Add imported files to additional files (only if not already present)
        if (importedData.files.length > 0) {
          const existingPaths = new Set(additionalFiles.map(f => f.path));
          const newFiles = importedData.files
            .filter(f => !existingPaths.has(f.path))
            .map(f => ({
              id: `${Date.now()}-${Math.random()}`,
              path: f.path,
              content: f.content,
            }));
          
          if (newFiles.length > 0) {
            setAdditionalFiles([...additionalFiles, ...newFiles]);
          }
        }

        setImportSuccess(true);
        setImportError(null);
      } catch (error) {
        setImportError(error instanceof Error ? error.message : 'Failed to import from GitHub');
        setImportSuccess(false);
      } finally {
        setIsImporting(false);
      }
    };

    // Debounce the import to avoid too many requests
    const timeoutId = setTimeout(() => {
      importFromGitHub();
    }, 1000);

    return () => clearTimeout(timeoutId);
  }, [url]); // Only depend on url

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!name.trim()) {
        throw new Error('Skill name is required');
      }
      if (!skillMdContent.trim() && !url.trim()) {
        throw new Error('Either SKILL.md content or URL is required');
      }

      // Build files object
      const files: Record<string, string> = {};
      
      // Add SKILL.md
      if (skillMdContent.trim()) {
        files['SKILL.md'] = skillMdContent.trim();
      }

      // Add additional files
      for (const file of additionalFiles) {
        if (file.path.trim() && file.content.trim()) {
          files[file.path.trim()] = file.content.trim();
        }
      }

      return skillService.create({
        name: name.trim(),
        namespace,
        description: description.trim() || undefined,
        category: category.trim() || undefined,
        url: url.trim() || undefined,
        files: Object.keys(files).length > 0 ? files : undefined,
      });
    },
    onSuccess: () => {
      setSubmitSuccess(true);
      setSubmitError(null);
      setTimeout(() => navigate('/skills'), 1500);
    },
    onError: (error) => {
      setSubmitError(error instanceof Error ? error.message : 'Failed to create skill');
    },
  });

  return (
    <>
      <PageSection variant="light">
        <TextContent>
          <Title headingLevel="h1">Import Skill</Title>
          <Text component="p">
            Import a skill by providing its content directly or a Git URL.
            The skill must contain a SKILL.md file with YAML frontmatter.
          </Text>
        </TextContent>
      </PageSection>

      <PageSection>
        <Card>
          <CardTitle>Skill Information</CardTitle>
          <CardBody>
            <Form>
              <FormGroup label="Namespace" isRequired>
                <NamespaceSelector
                  namespace={namespace}
                  onNamespaceChange={setNamespace}
                />
              </FormGroup>

              <FormGroup label="Name" isRequired>
                <TextInput
                  id="skill-name"
                  type="text"
                  value={name}
                  onChange={(_event, value) => setName(value)}
                  placeholder="e.g., code-review-assistant"
                />
                <HelperText>
                  <HelperTextItem>
                    A unique name for this skill
                  </HelperTextItem>
                </HelperText>
              </FormGroup>

              <FormGroup label="Description">
                <TextInput
                  id="skill-description"
                  type="text"
                  value={description}
                  onChange={(_event, value) => setDescription(value)}
                  placeholder="Brief description of what this skill does"
                />
              </FormGroup>

              <FormGroup label="Category">
                <TextInput
                  id="skill-category"
                  type="text"
                  value={category}
                  onChange={(_event, value) => setCategory(value)}
                  placeholder="e.g., development, analysis, documentation"
                />
              </FormGroup>

              <FormGroup
                label={
                  <Split hasGutter>
                    <SplitItem>URL</SplitItem>
                    <SplitItem>
                      <Label color="blue" icon={<GithubIcon />}>
                        Auto-imports files & metadata
                      </Label>
                    </SplitItem>
                  </Split>
                }
              >
                <Split hasGutter>
                  <SplitItem isFilled>
                    <TextInput
                      id="skill-url"
                      type="text"
                      value={url}
                      onChange={(_event, value) => {
                        setUrl(value);
                        setImportError(null);
                        setImportSuccess(false);
                      }}
                      placeholder="https://github.com/anthropics/skills/tree/main/skills/pdf"
                    />
                  </SplitItem>
                  {isImporting && (
                    <SplitItem>
                      <Spinner size="md" aria-label="Importing from GitHub" />
                    </SplitItem>
                  )}
                </Split>
                <HelperText>
                  <HelperTextItem variant="indeterminate">
                    <strong>💡 Tip:</strong> Paste a GitHub URL and all skill files, name, description, and category will be automatically populated
                  </HelperTextItem>
                </HelperText>
                {importError && (
                  <Alert
                    variant="danger"
                    title="Import failed"
                    isInline
                    isPlain
                    style={{ marginTop: '0.5rem' }}
                  >
                    {importError}
                  </Alert>
                )}
                {importSuccess && (
                  <Alert
                    variant="success"
                    title="Successfully imported from GitHub"
                    isInline
                    isPlain
                    style={{ marginTop: '0.5rem' }}
                  >
                    Skill data has been loaded. Review and click "Import Skill" to save.
                  </Alert>
                )}
              </FormGroup>

              <FormGroup label="SKILL.md Content" isRequired={!url}>
                <TextArea
                  id="skill-md-content"
                  value={skillMdContent}
                  onChange={(_event, value) => setSkillMdContent(value)}
                  placeholder="---&#10;name: my-skill&#10;description: A helpful skill&#10;---&#10;&#10;# Instructions&#10;..."
                  rows={15}
                />
                <HelperText>
                  <HelperTextItem>
                    Paste the SKILL.md content here (required), including YAML frontmatter
                  </HelperTextItem>
                </HelperText>
              </FormGroup>

              <FormGroup label="Additional Files">
                <Split hasGutter>
                  <SplitItem isFilled>
                    <Text component="small">
                      Add supporting files like examples, documentation, or helper scripts
                    </Text>
                  </SplitItem>
                  <SplitItem>
                    <Button
                      variant="link"
                      icon={<PlusCircleIcon />}
                      onClick={addFile}
                      size="sm"
                    >
                      Add File
                    </Button>
                  </SplitItem>
                </Split>

                {additionalFiles.length > 0 && (
                  <List isPlain style={{ marginTop: '1rem' }}>
                    {additionalFiles.map((file) => (
                      <ListItem key={file.id}>
                        <Card isCompact style={{ marginBottom: '0.5rem' }}>
                          <CardBody>
                            <Split hasGutter>
                              <SplitItem isFilled>
                                <FormGroup label="File Path" isRequired>
                                  <TextInput
                                    value={file.path}
                                    onChange={(_event, value) => updateFilePath(file.id, value)}
                                    placeholder="e.g., examples/example.py or docs/README.md"
                                  />
                                </FormGroup>
                                <FormGroup label="Content" isRequired>
                                  <TextArea
                                    value={file.content}
                                    onChange={(_event, value) => updateFileContent(file.id, value)}
                                    placeholder="File content..."
                                    rows={5}
                                  />
                                </FormGroup>
                              </SplitItem>
                              <SplitItem>
                                <Button
                                  variant="plain"
                                  icon={<TrashIcon />}
                                  onClick={() => removeFile(file.id)}
                                  aria-label="Remove file"
                                />
                              </SplitItem>
                            </Split>
                          </CardBody>
                        </Card>
                      </ListItem>
                    ))}
                  </List>
                )}
              </FormGroup>

              {submitError && (
                <Alert variant="danger" title="Import failed" isInline>
                  {submitError}
                </Alert>
              )}
              {submitSuccess && (
                <Alert variant="success" title="Skill imported" isInline>
                  Redirecting to skill catalog...
                </Alert>
              )}

              <ActionGroup>
                <Button
                  variant="primary"
                  onClick={() => createMutation.mutate()}
                  isLoading={createMutation.isPending}
                  isDisabled={createMutation.isPending || submitSuccess}
                >
                  Import Skill
                </Button>
                <Button
                  variant="link"
                  onClick={() => navigate('/skills')}
                  isDisabled={createMutation.isPending}
                >
                  Cancel
                </Button>
              </ActionGroup>
            </Form>
          </CardBody>
        </Card>
      </PageSection>
    </>
  );
};

