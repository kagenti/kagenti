// Copyright 2026 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  PageSection,
  Title,
  Breadcrumb,
  BreadcrumbItem,
  Spinner,
  EmptyState,
  EmptyStateHeader,
  EmptyStateIcon,
  EmptyStateBody,
  Button,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Label,
  Card,
  CardTitle,
  CardBody,
  Alert,
  Split,
  SplitItem,
  Modal,
  ModalVariant,
  TextInput,
  FormGroup,
} from '@patternfly/react-core';
import {
  ExclamationTriangleIcon,
  TrashIcon,
} from '@patternfly/react-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { skillService } from '@/services/api';
import { SkillFileTree } from '@/components';

export const SkillDetailPage: React.FC = () => {
  const { namespace, name } = useParams<{ namespace: string; name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [deleteModalOpen, setDeleteModalOpen] = React.useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = React.useState('');

  const { data: skill, isLoading, isError, error } = useQuery({
    queryKey: ['skill', namespace, name],
    queryFn: () => skillService.get(namespace!, name!),
    enabled: !!namespace && !!name,
  });

  const deleteMutation = useMutation({
    mutationFn: () => skillService.delete(namespace!, name!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      navigate('/skills');
    },
  });

  const handleCloseDeleteModal = () => {
    setDeleteModalOpen(false);
    setDeleteConfirmText('');
  };

  const handleDeleteConfirm = () => {
    if (deleteConfirmText.trim() === name) {
      deleteMutation.mutate();
    }
  };

  if (isLoading) {
    return (
      <PageSection>
        <div style={{ textAlign: 'center', padding: '2rem' }}>
          <Spinner size="xl" />
        </div>
      </PageSection>
    );
  }

  if (isError || !skill) {
    return (
      <PageSection>
        <EmptyState>
          <EmptyStateHeader
            titleText="Skill not found"
            icon={<EmptyStateIcon icon={ExclamationTriangleIcon} />}
            headingLevel="h1"
          />
          <EmptyStateBody>
            {error instanceof Error ? error.message : 'The requested skill could not be found.'}
          </EmptyStateBody>
          <Button variant="primary" onClick={() => navigate('/skills')}>
            Back to Skills
          </Button>
        </EmptyState>
      </PageSection>
    );
  }

  return (
    <>
      <PageSection variant="light">
        <Breadcrumb>
          <BreadcrumbItem to="/skills" onClick={(e) => { e.preventDefault(); navigate('/skills'); }}>
            Skills
          </BreadcrumbItem>
          <BreadcrumbItem isActive>{skill.name}</BreadcrumbItem>
        </Breadcrumb>
        <Split hasGutter style={{ marginTop: '1rem' }}>
          <SplitItem isFilled>
            <Title headingLevel="h1">{skill.name}</Title>
          </SplitItem>
          <SplitItem>
            <Button
              variant="danger"
              icon={<TrashIcon />}
              onClick={() => setDeleteModalOpen(true)}
            >
              Delete
            </Button>
          </SplitItem>
        </Split>
      </PageSection>

      <PageSection>
        <Card>
          <CardTitle>Skill Information</CardTitle>
          <CardBody>
            <DescriptionList isHorizontal>
              <DescriptionListGroup>
                <DescriptionListTerm>Name</DescriptionListTerm>
                <DescriptionListDescription>{skill.name}</DescriptionListDescription>
              </DescriptionListGroup>

              <DescriptionListGroup>
                <DescriptionListTerm>Namespace</DescriptionListTerm>
                <DescriptionListDescription>{skill.namespace}</DescriptionListDescription>
              </DescriptionListGroup>

              <DescriptionListGroup>
                <DescriptionListTerm>Description</DescriptionListTerm>
                <DescriptionListDescription>
                  {skill.description || <em>No description</em>}
                </DescriptionListDescription>
              </DescriptionListGroup>

              {skill.labels?.category && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Category</DescriptionListTerm>
                  <DescriptionListDescription>
                    <Label color="blue">{skill.labels.category}</Label>
                  </DescriptionListDescription>
                </DescriptionListGroup>
              )}

              <DescriptionListGroup>
                <DescriptionListTerm>Status</DescriptionListTerm>
                <DescriptionListDescription>
                  <Label color="green">{skill.status}</Label>
                </DescriptionListDescription>
              </DescriptionListGroup>

              {skill.origin && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Origin</DescriptionListTerm>
                  <DescriptionListDescription>{skill.origin}</DescriptionListDescription>
                </DescriptionListGroup>
              )}

              <DescriptionListGroup>
                <DescriptionListTerm>Usage Count</DescriptionListTerm>
                <DescriptionListDescription>{skill.usageCount || 0}</DescriptionListDescription>
              </DescriptionListGroup>

              {skill.createdAt && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Created</DescriptionListTerm>
                  <DescriptionListDescription>
                    {new Date(skill.createdAt).toLocaleString()}
                  </DescriptionListDescription>
                </DescriptionListGroup>
              )}
            </DescriptionList>
          </CardBody>
        </Card>

        {/* File tree and preview split view */}
        {skill.files && skill.files.length > 0 && (
          <div style={{ marginTop: '1rem' }}>
            <SkillFileTree files={skill.files} showPreview={true} />
          </div>
        )}
      </PageSection>

      <Modal
        variant={ModalVariant.small}
        title="Delete Skill"
        isOpen={deleteModalOpen}
        onClose={handleCloseDeleteModal}
        actions={[
          <Button
            key="confirm"
            variant="danger"
            onClick={handleDeleteConfirm}
            isDisabled={deleteConfirmText.trim() !== name}
            isLoading={deleteMutation.isPending}
          >
            Delete
          </Button>,
          <Button key="cancel" variant="link" onClick={handleCloseDeleteModal}>
            Cancel
          </Button>,
        ]}
      >
        <Alert
          variant="warning"
          isInline
          title="This action cannot be undone"
          style={{ marginBottom: '1rem' }}
        />
        <p>
          To confirm deletion, type the skill name <strong>{name}</strong> below:
        </p>
        <FormGroup>
          <TextInput
            value={deleteConfirmText}
            onChange={(_event, value) => setDeleteConfirmText(value)}
            placeholder={name}
            aria-label="Confirm skill name"
          />
        </FormGroup>
      </Modal>
    </>
  );
};

