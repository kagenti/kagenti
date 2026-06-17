// Copyright 2026 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  PageSection,
  Title,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
  Button,
  Spinner,
  EmptyState,
  EmptyStateHeader,
  EmptyStateIcon,
  EmptyStateBody,
  EmptyStateFooter,
  EmptyStateActions,
  SearchInput,
  Label,
  Alert,
  Modal,
  ModalVariant,
} from '@patternfly/react-core';
import { PlusCircleIcon, WrenchIcon, ExternalLinkAltIcon } from '@patternfly/react-icons';
import {
  Table,
  Thead,
  Tr,
  Th,
  Tbody,
  Td,
} from '@patternfly/react-table';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { Skill, SkillAutoSyncStatus } from '@/types';
import { skillService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';
import { getSkillberryUiUrl, getSkillberryStoreUrl } from '@/utils/validation';

export const SkillCatalogPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [namespace, setNamespace] = useState<string>('team1');
  const [searchQuery, setSearchQuery] = useState('');
  const [disableConfirmOpen, setDisableConfirmOpen] = useState(false);

  const { data: skills = [], isLoading, error } = useQuery({
    queryKey: ['skills', namespace, searchQuery],
    queryFn: () => skillService.list(namespace, searchQuery || undefined),
  });

  const { data: autoSyncStatus } = useQuery<SkillAutoSyncStatus>({
    queryKey: ['skillAutoSync'],
    queryFn: () => skillService.getAutoSync(),
  });

  const disableAutoSyncMutation = useMutation({
    mutationFn: () => skillService.disableAutoSync(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skillAutoSync'] });
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setDisableConfirmOpen(false);
    },
  });

  const isAutoSyncActive = autoSyncStatus?.enabled === true;

  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Skills</Title>
      </PageSection>

      <PageSection>
        {isAutoSyncActive && (
          <Alert
            variant="info"
            isInline
            title={`Auto-sync active — syncing from ${autoSyncStatus?.registryUrl}`}
            style={{ marginBottom: '1rem' }}
            actionLinks={
              <>
                <Button
                  variant="link"
                  component="a"
                  href={getSkillberryStoreUrl(autoSyncStatus?.registryUrl ?? '')}
                  target="_blank"
                  rel="noreferrer"
                >
                  Manage in Skillberry Store ↗
                </Button>
                <Button
                  variant="link"
                  isDanger
                  onClick={() => setDisableConfirmOpen(true)}
                >
                  Disable Auto-Sync
                </Button>
              </>
            }
          />
        )}

        <Modal
          variant={ModalVariant.small}
          title="Disable auto-sync?"
          isOpen={disableConfirmOpen}
          onClose={() => setDisableConfirmOpen(false)}
          actions={[
            <Button
              key="confirm"
              variant="danger"
              isLoading={disableAutoSyncMutation.isPending}
              onClick={() => disableAutoSyncMutation.mutate()}
            >
              Disable and remove {autoSyncStatus?.skillCount ?? 'all'} synced skills
            </Button>,
            <Button key="cancel" variant="link" onClick={() => setDisableConfirmOpen(false)}>
              Cancel
            </Button>,
          ]}
        >
          This will remove all auto-synced skills from Kagenti. Skills managed in
          Skillberry Store will not be affected.
        </Modal>
        <Toolbar>
          <ToolbarContent>
            <ToolbarItem>
              <NamespaceSelector
                namespace={namespace}
                onNamespaceChange={setNamespace}
              />
            </ToolbarItem>
            <ToolbarItem variant="search-filter">
              <SearchInput
                placeholder="Search skills..."
                value={searchQuery}
                onChange={(_event, value) => setSearchQuery(value)}
                onClear={() => setSearchQuery('')}
              />
            </ToolbarItem>
            <ToolbarItem>
              {isAutoSyncActive ? (
                <Button
                  variant="secondary"
                  icon={<ExternalLinkAltIcon />}
                  component="a"
                  href={getSkillberryStoreUrl(autoSyncStatus?.registryUrl ?? '')}
                  target="_blank"
                  rel="noreferrer"
                >
                  Manage in Skillberry Store ↗
                </Button>
              ) : (
                <Button
                  variant="primary"
                  icon={<PlusCircleIcon />}
                  onClick={() => navigate('/skills/import')}
                >
                  Import Skill
                </Button>
              )}
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>

        {isLoading && (
          <div style={{ textAlign: 'center', padding: '2rem' }}>
            <Spinner size="lg" />
          </div>
        )}

        {error && (
          <EmptyState>
            <EmptyStateHeader
              titleText="Error loading skills"
              headingLevel="h2"
              icon={<EmptyStateIcon icon={WrenchIcon} />}
            />
            <EmptyStateBody>
              {error instanceof Error ? error.message : 'An error occurred'}
            </EmptyStateBody>
          </EmptyState>
        )}

        {!isLoading && !error && skills.length === 0 && (
          <EmptyState>
            <EmptyStateHeader
              titleText="No skills found"
              headingLevel="h2"
              icon={<EmptyStateIcon icon={WrenchIcon} />}
            />
            <EmptyStateBody>
              {searchQuery
                ? 'No skills match your search criteria.'
                : 'Get started by importing your first skill.'}
            </EmptyStateBody>
            <EmptyStateFooter>
              <EmptyStateActions>
                {isAutoSyncActive ? (
                  <Button
                    variant="secondary"
                    icon={<ExternalLinkAltIcon />}
                    component="a"
                    href={getSkillberryStoreUrl(autoSyncStatus?.registryUrl ?? '')}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Manage in Skillberry Store ↗
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    icon={<PlusCircleIcon />}
                    onClick={() => navigate('/skills/import')}
                  >
                    Import Skill
                  </Button>
                )}
              </EmptyStateActions>
            </EmptyStateFooter>
          </EmptyState>
        )}

        {!isLoading && !error && skills.length > 0 && (
          <Table aria-label="Skills table" variant="compact">
            <Thead>
              <Tr>
                <Th>Name</Th>
                <Th>Description</Th>
                <Th>Category</Th>
                <Th>Usage Count</Th>
                <Th>Created</Th>
                <Th>Registry</Th>
              </Tr>
            </Thead>
            <Tbody>
              {skills.map((skill: Skill) => (
                <Tr
                  key={`${skill.namespace}/${skill.resourceName}`}
                  onClick={() =>
                    navigate(`/skills/${skill.namespace}/${skill.resourceName}`)
                  }
                  style={{ cursor: 'pointer' }}
                >
                  <Td dataLabel="Name">
                    <strong>{skill.name}</strong>
                    {skill.source === 'external' && (
                      <Label color="blue" isCompact style={{ marginLeft: '0.5rem' }}>
                        External
                      </Label>
                    )}
                    {skill.labels?.autoSync === 'true' && (
                      <Label color="green" isCompact style={{ marginLeft: '0.5rem' }}>
                        Auto-synced
                      </Label>
                    )}
                  </Td>
                  <Td dataLabel="Description">
                    {skill.description || <em>No description</em>}
                  </Td>
                  <Td dataLabel="Category">
                    {skill.labels.category ? (
                      <Label color="blue">{skill.labels.category}</Label>
                    ) : (
                      <em>None</em>
                    )}
                  </Td>
                  <Td dataLabel="Usage Count">{skill.usageCount}</Td>
                  <Td dataLabel="Created">
                    {skill.createdAt
                      ? new Date(skill.createdAt).toLocaleDateString()
                      : 'N/A'}
                  </Td>
                  <Td dataLabel="Registry">
                    {skill.source === 'external' &&
                    skill.externalInfo?.registryType === 'skillberry' &&
                    getSkillberryUiUrl(skill.externalInfo.registryUrl, skill.externalInfo.registrySkillName) ? (
                      <a
                        href={getSkillberryUiUrl(skill.externalInfo.registryUrl, skill.externalInfo.registrySkillName)}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                      >
                        View ↗
                      </a>
                    ) : (
                      <span>—</span>
                    )}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </PageSection>
    </>
  );
};

