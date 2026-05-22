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
} from '@patternfly/react-core';
import { PlusCircleIcon, WrenchIcon } from '@patternfly/react-icons';
import {
  Table,
  Thead,
  Tr,
  Th,
  Tbody,
  Td,
} from '@patternfly/react-table';
import { useQuery } from '@tanstack/react-query';

import { Skill } from '@/types';
import { skillService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';

export const SkillCatalogPage: React.FC = () => {
  const navigate = useNavigate();
  const [namespace, setNamespace] = useState<string>('team1');
  const [searchQuery, setSearchQuery] = useState('');

  const { data: skills = [], isLoading, error } = useQuery({
    queryKey: ['skills', namespace, searchQuery],
    queryFn: () => skillService.list(namespace, searchQuery || undefined),
  });

  return (
    <>
      <PageSection variant="light">
        <Title headingLevel="h1">Skills</Title>
      </PageSection>

      <PageSection>
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
              <Button
                variant="primary"
                icon={<PlusCircleIcon />}
                onClick={() => navigate('/skills/import')}
              >
                Import Skill
              </Button>
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
                <Button
                  variant="primary"
                  icon={<PlusCircleIcon />}
                  onClick={() => navigate('/skills/import')}
                >
                  Import Skill
                </Button>
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
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </PageSection>
    </>
  );
};

