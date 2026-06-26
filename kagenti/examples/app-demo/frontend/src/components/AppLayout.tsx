import React from 'react';
import {
  Button,
  Masthead,
  MastheadBrand,
  MastheadContent,
  MastheadMain,
  Page,
  PageSection,
  Toolbar,
  ToolbarContent,
  ToolbarGroup,
  ToolbarItem,
} from '@patternfly/react-core';
import { UserIcon } from '@patternfly/react-icons';
import { Outlet } from 'react-router-dom';

import { useAuth } from '@/contexts/AuthContext';

export const AppLayout: React.FC = () => {
  const { isAuthenticated, user, login, logout } = useAuth();

  const mastheadEl = (
    <Masthead>
      <MastheadMain>
        <MastheadBrand>
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#fff', fontSize: '18px', fontWeight: 700, letterSpacing: '0.5px' }}>
            <span
              style={{
                background: '#0066cc',
                borderRadius: '6px',
                width: '32px',
                height: '32px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 800,
                fontSize: '18px',
              }}
            >
              K
            </span>
            App Demo
          </span>
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Toolbar isFullHeight>
          <ToolbarContent>
            <ToolbarGroup align={{ default: 'alignRight' }}>
              {isAuthenticated && user ? (
                <>
                  <ToolbarItem>
                    <span
                      style={{
                        color: '#fff',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                      }}
                    >
                      <UserIcon />
                      {user.username}
                    </span>
                  </ToolbarItem>
                  <ToolbarItem>
                    <Button variant="plain" onClick={logout} style={{ color: '#c9c9c9' }}>
                      Sign Out
                    </Button>
                  </ToolbarItem>
                </>
              ) : (
                <ToolbarItem>
                  <Button variant="plain" onClick={login} style={{ color: '#73bcf7' }}>
                    Sign In
                  </Button>
                </ToolbarItem>
              )}
            </ToolbarGroup>
          </ToolbarContent>
        </Toolbar>
      </MastheadContent>
    </Masthead>
  );

  return (
    <Page header={mastheadEl}>
      <PageSection isFilled>
        <Outlet />
      </PageSection>
    </Page>
  );
};
