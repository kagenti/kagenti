import React, { useEffect } from 'react';
import {
  Button,
  EmptyState,
  EmptyStateBody,
  EmptyStateHeader,
  EmptyStateIcon,
} from '@patternfly/react-core';
import { RobotIcon } from '@patternfly/react-icons';
import { useNavigate } from 'react-router-dom';

import { useAuth } from '@/contexts/AuthContext';

export const LandingPage: React.FC = () => {
  const { isAuthenticated, isLoading, login } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      navigate('/agents', { replace: true });
    }
  }, [isAuthenticated, isLoading, navigate]);

  return (
    <EmptyState>
      <EmptyStateHeader
        titleText="Kagenti App Demo"
        icon={<EmptyStateIcon icon={RobotIcon} />}
        headingLevel="h1"
      />
      <EmptyStateBody>
        Interact with AI agents deployed on the Kagenti platform. Sign in to get
        started.
      </EmptyStateBody>
      <Button variant="primary" size="lg" onClick={login}>
        Sign In with Keycloak
      </Button>
    </EmptyState>
  );
};
