import React from 'react';
import {
  EmptyState,
  EmptyStateBody,
  EmptyStateHeader,
  EmptyStateIcon,
  Button,
  Spinner,
} from '@patternfly/react-core';
import { LockIcon } from '@patternfly/react-icons';

import { useAuth } from '@/contexts/AuthContext';

export const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { isAuthenticated, isLoading, isEnabled, login } = useAuth();

  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '60vh',
        }}
      >
        <Spinner size="xl" />
      </div>
    );
  }

  if (isEnabled && !isAuthenticated) {
    return (
      <EmptyState>
        <EmptyStateHeader
          titleText="Authentication Required"
          icon={<EmptyStateIcon icon={LockIcon} />}
          headingLevel="h2"
        />
        <EmptyStateBody>
          Please sign in to access this page.
        </EmptyStateBody>
        <Button variant="primary" onClick={login}>
          Sign In
        </Button>
      </EmptyState>
    );
  }

  return <>{children}</>;
};
