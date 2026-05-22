// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React from 'react';
import {
  Bullseye,
  Spinner,
  EmptyState,
  EmptyStateHeader,
  EmptyStateIcon,
  EmptyStateBody,
  EmptyStateFooter,
  EmptyStateActions,
  Button,
} from '@patternfly/react-core';
import { LockIcon } from '@patternfly/react-icons';

import { useAuth } from '@/contexts';

interface ProtectedRouteProps {
  children: React.ReactNode;
  /**
   * Optional array of roles required to access this route.
   * User must have at least one of the specified roles.
   * If empty or undefined, only authentication is required.
   * 
   * Future enhancement: Can be extended to support:
   * - namespace-based access control
   * - resource-level permissions
   * - fine-grained RBAC policies
   */
  requiredRoles?: string[];
  /**
   * Optional namespace restriction.
   * Reserved for future implementation of namespace-based access control.
   * When implemented, users will need appropriate roles/permissions for the specified namespace.
   */
  requiredNamespace?: string;
}

/**
 * ProtectedRoute component that wraps routes requiring authentication.
 *
 * Current behavior:
 * - Shows a loading spinner while auth state is being determined
 * - If auth is disabled, grants access to all users
 * - Shows login prompt if auth is enabled and user is not authenticated
 * - Shows access denied if user lacks required roles (when requiredRoles is specified)
 * - Renders children if user is authenticated and authorized
 *
 * Future extensibility:
 * - Role-based access control (RBAC) via requiredRoles parameter
 * - Namespace-based access control via requiredNamespace parameter
 * - Integration with OAuth2 provider roles and claims
 * - Resource-level permissions and fine-grained access policies
 */
export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requiredRoles = [],
  // requiredNamespace - reserved for future namespace-based access control
}) => {
  const { isAuthenticated, isLoading, isEnabled, user, login } = useAuth();

  // Show loading state while checking authentication
  if (isLoading) {
    return (
      <Bullseye style={{ minHeight: '400px' }}>
        <Spinner size="xl" aria-label="Checking authentication..." />
      </Bullseye>
    );
  }

  // If auth is disabled, render children directly (no protection needed)
  if (!isEnabled) {
    return <>{children}</>;
  }

  // Show login prompt if auth is enabled but user is not authenticated
  if (!isAuthenticated) {
    return (
      <Bullseye style={{ minHeight: '400px' }}>
        <EmptyState>
          <EmptyStateHeader
            titleText="Authentication Required"
            icon={<EmptyStateIcon icon={LockIcon} />}
            headingLevel="h4"
          />
          <EmptyStateBody>
            This page requires authentication. Please sign in to continue.
          </EmptyStateBody>
          <EmptyStateFooter>
            <EmptyStateActions>
              <Button variant="primary" onClick={login}>
                Sign In
              </Button>
            </EmptyStateActions>
          </EmptyStateFooter>
        </EmptyState>
      </Bullseye>
    );
  }

  // Check role-based access control if requiredRoles specified
  // This enables future RBAC implementation while maintaining backward compatibility
  if (requiredRoles.length > 0 && user) {
    const hasRequiredRole = requiredRoles.some((role) =>
      user.roles.includes(role)
    );

    if (!hasRequiredRole) {
      return (
        <Bullseye style={{ minHeight: '400px' }}>
          <EmptyState>
            <EmptyStateHeader
              titleText="Access Denied"
              icon={<EmptyStateIcon icon={LockIcon} />}
              headingLevel="h4"
            />
            <EmptyStateBody>
              You don't have the required permissions to access this page.
              <br />
              Required role(s): {requiredRoles.join(', ')}
            </EmptyStateBody>
          </EmptyState>
        </Bullseye>
      );
    }
  }

  // User is authenticated and authorized - render protected content
  return <>{children}</>;
};
