// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * SandboxCreatePage -- Thin wrapper around the reusable SandboxWizard component.
 */

import React from 'react';
import { PageSection, Title } from '@patternfly/react-core';
import { useNavigate } from 'react-router-dom';
import { SandboxWizard } from '@/components/SandboxWizard';

export const SandboxCreatePage: React.FC = () => {
  const navigate = useNavigate();
  return (
    <PageSection variant="light">
      <Title headingLevel="h1" style={{ marginBottom: 16 }}>
        Create Sandbox Agent
      </Title>
      <SandboxWizard
        mode="create"
        onClose={() => navigate('/sandbox')}
        onSuccess={() => navigate('/sandbox')}
      />
    </PageSection>
  );
};
