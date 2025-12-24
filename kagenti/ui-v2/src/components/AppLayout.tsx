// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Page,
  Masthead,
  MastheadToggle,
  MastheadMain,
  MastheadBrand,
  MastheadContent,
  PageSidebar,
  PageSidebarBody,
  PageToggleButton,
  Nav,
  NavList,
  NavItem,
  NavGroup,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
  Button,
  Avatar,
  Dropdown,
  DropdownItem,
  DropdownList,
  Divider,
  MenuToggle,
  MenuToggleElement,
  Spinner,
  Alert,
  AlertActionCloseButton,
  AlertGroup,
} from '@patternfly/react-core';
import {
  BarsIcon,
  CogIcon,
  QuestionCircleIcon,
  SignOutAltIcon,
  UserIcon,
  MoonIcon,
  SunIcon,
  AdjustIcon,
} from '@patternfly/react-icons';

import { useAuth, useTheme } from '@/contexts';
import type { ThemeMode } from '@/contexts';

interface AppLayoutProps {
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ children }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { isAuthenticated, isLoading, isEnabled, user, error, login, logout } = useAuth();
  const { mode, effectiveTheme, setMode } = useTheme();
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isUserDropdownOpen, setIsUserDropdownOpen] = useState(false);
  const [isThemeDropdownOpen, setIsThemeDropdownOpen] = useState(false);  const [showError, setShowError] = useState(false);

  // Show error alert when error changes
  React.useEffect(() => {
    if (error) {
      setShowError(true);
    }
  }, [error]);
  const onSidebarToggle = () => {
    setIsSidebarOpen(!isSidebarOpen);
  };

  const isNavItemActive = (path: string): boolean => {
    if (path === '/') {
      return location.pathname === '/';
    }
    return location.pathname.startsWith(path);
  };

  const handleNavSelect = (path: string) => {
    navigate(path);
  };

  const handleLogout = () => {
    setIsUserDropdownOpen(false);
    logout();
  };

  const handleThemeChange = (newMode: ThemeMode) => {
    setMode(newMode);
    setIsThemeDropdownOpen(false);
  };

  const getThemeIcon = () => {
    if (mode === 'auto') return <AdjustIcon />;
    return effectiveTheme === 'dark' ? <MoonIcon /> : <SunIcon />;
  };

  // Generate user display name
  const getUserDisplayName = (): string => {
    if (!user) return 'Guest';
    if (user.firstName && user.lastName) {
      return `${user.firstName} ${user.lastName}`;
    }
    return user.username;
  };

  // Generate avatar initials
  const getAvatarInitials = (): string => {
    if (!user) return '?';
    if (user.firstName && user.lastName) {
      return `${user.firstName[0]}${user.lastName[0]}`.toUpperCase();
    }
    return user.username[0].toUpperCase();
  };

  // Render user menu toggle
  const renderUserToggle = () => {
    console.log('renderUserToggle:', { isLoading, isAuthenticated, isEnabled, user });
    
    if (isLoading) {
      return (
        <ToolbarItem>
          <Spinner size="md" aria-label="Loading user..." />
        </ToolbarItem>
      );
    }

    if (!isAuthenticated && isEnabled) {
      return (
        <ToolbarItem>
          <Button variant="primary" onClick={login}>
            Sign In
          </Button>
        </ToolbarItem>
      );
    }

    return (
      <ToolbarItem>
        <Dropdown
          isOpen={isUserDropdownOpen}
          onSelect={() => setIsUserDropdownOpen(false)}
          onOpenChange={(isOpen) => setIsUserDropdownOpen(isOpen)}
          toggle={(toggleRef: React.Ref<MenuToggleElement>) => (
            <MenuToggle
              ref={toggleRef}
              onClick={() => setIsUserDropdownOpen(!isUserDropdownOpen)}
              isExpanded={isUserDropdownOpen}
              icon={
                <Avatar
                  src={`data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="50" fill="#0066CC"/><text x="50" y="62" font-family="Arial" font-size="40" font-weight="bold" fill="white" text-anchor="middle">${getAvatarInitials()}</text></svg>`)}`}
                  alt={getUserDisplayName()}
                  size="sm"
                />
              }
            >
              {getUserDisplayName()}
            </MenuToggle>
          )}
        >
          <DropdownList>
            {user?.email && (
              <>
                <DropdownItem
                  key="user-info"
                  isDisabled
                  description={user.email}
                  icon={<UserIcon />}
                >
                  {getUserDisplayName()}
                </DropdownItem>
                <Divider component="li" key="separator" />
              </>
            )}
            <DropdownItem key="settings" icon={<CogIcon />}>
              Settings
            </DropdownItem>
            {isEnabled && (
              <DropdownItem
                key="logout"
                icon={<SignOutAltIcon />}
                onClick={handleLogout}
              >
                Sign Out
              </DropdownItem>
            )}
          </DropdownList>
        </Dropdown>
      </ToolbarItem>
    );
  };

  const masthead = (
    <Masthead>
      <MastheadToggle>
        <PageToggleButton
          variant="plain"
          aria-label="Global navigation"
          isSidebarOpen={isSidebarOpen}
          onSidebarToggle={onSidebarToggle}
        >
          <BarsIcon />
        </PageToggleButton>
      </MastheadToggle>
      <MastheadMain>
        <MastheadBrand
          className="kagenti-brand"
          component="a"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate('/');
          }}
        >
          <svg
            className="kagenti-brand-logo"
            viewBox="0 0 100 100"
            xmlns="http://www.w3.org/2000/svg"
          >
            <rect width="100" height="100" rx="20" fill="#0066CC" />
            <text
              x="50"
              y="68"
              fontFamily="Arial, sans-serif"
              fontSize="50"
              fontWeight="bold"
              fill="white"
              textAnchor="middle"
            >
              K
            </text>
          </svg>
          Kagenti
        </MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Toolbar isFullHeight isStatic>
          <ToolbarContent>
            <ToolbarItem>
              <Dropdown
                isOpen={isThemeDropdownOpen}
                onSelect={() => setIsThemeDropdownOpen(false)}
                onOpenChange={(isOpen) => setIsThemeDropdownOpen(isOpen)}
                toggle={(toggleRef: React.Ref<MenuToggleElement>) => (
                  <MenuToggle
                    ref={toggleRef}
                    variant="plain"
                    onClick={() => setIsThemeDropdownOpen(!isThemeDropdownOpen)}
                    isExpanded={isThemeDropdownOpen}
                    aria-label="Theme selector"
                  >
                    {getThemeIcon()}
                  </MenuToggle>
                )}
              >
                <DropdownList>
                  <DropdownItem
                    key="auto"
                    icon={<AdjustIcon />}
                    onClick={() => handleThemeChange('auto')}
                    description="Follow system preference"
                  >
                    System default {mode === 'auto' && '✓'}
                  </DropdownItem>
                  <DropdownItem
                    key="light"
                    icon={<SunIcon />}
                    onClick={() => handleThemeChange('light')}
                  >
                    Light {mode === 'light' && '✓'}
                  </DropdownItem>
                  <DropdownItem
                    key="dark"
                    icon={<MoonIcon />}
                    onClick={() => handleThemeChange('dark')}
                  >
                    Dark {mode === 'dark' && '✓'}
                  </DropdownItem>
                </DropdownList>
              </Dropdown>
            </ToolbarItem>
            <ToolbarItem>
              <Button
                variant="plain"
                aria-label="Help"
                onClick={() =>
                  window.open('https://kagenti.github.io/.github/', '_blank')
                }
              >
                <QuestionCircleIcon />
              </Button>
            </ToolbarItem>
            {renderUserToggle()}
          </ToolbarContent>
        </Toolbar>
      </MastheadContent>
    </Masthead>
  );

  const sidebar = (
    <PageSidebar isSidebarOpen={isSidebarOpen}>
      <PageSidebarBody>
        <Nav aria-label="Navigation">
          <NavList>
            <NavItem
              itemId="home"
              isActive={isNavItemActive('/')}
              onClick={() => handleNavSelect('/')}
            >
              Home
            </NavItem>
          </NavList>

          {/* Only show navigation groups to authenticated users */}
          {(!isEnabled || isAuthenticated) && (
            <>
              <NavGroup title="Agentic Workloads">
                <NavList>
                  <NavItem
                    itemId="agents"
                    isActive={isNavItemActive('/agents')}
                    onClick={() => handleNavSelect('/agents')}
                  >
                    Agents
                  </NavItem>
                  <NavItem
                    itemId="tools"
                    isActive={isNavItemActive('/tools')}
                    onClick={() => handleNavSelect('/tools')}
                  >
                    Tools
                  </NavItem>
                </NavList>
              </NavGroup>

              <NavGroup title="Gateway & Routing">
                <NavList>
                  <NavItem
                    itemId="mcp-gateway"
                    isActive={isNavItemActive('/mcp-gateway')}
                    onClick={() => handleNavSelect('/mcp-gateway')}
                  >
                    MCP Gateway
                  </NavItem>
                  <NavItem
                    itemId="ai-gateway"
                    isActive={isNavItemActive('/ai-gateway')}
                    onClick={() => handleNavSelect('/ai-gateway')}
                  >
                    AI Gateway
                  </NavItem>
                  <NavItem
                    itemId="gateway-policies"
                    isActive={isNavItemActive('/gateway-policies')}
                    onClick={() => handleNavSelect('/gateway-policies')}
                  >
                    Gateway Policies
                  </NavItem>
                </NavList>
              </NavGroup>

              <NavGroup title="Operations">
                <NavList>
                  <NavItem
                    itemId="observability"
                    isActive={isNavItemActive('/observability')}
                    onClick={() => handleNavSelect('/observability')}
                  >
                    Observability
                  </NavItem>
                  <NavItem
                    itemId="admin"
                    isActive={isNavItemActive('/admin')}
                    onClick={() => handleNavSelect('/admin')}
                  >
                    Administration
                  </NavItem>
                </NavList>
              </NavGroup>
            </>
          )}
        </Nav>
      </PageSidebarBody>
    </PageSidebar>
  );

  return (
    <Page header={masthead} sidebar={sidebar} isManagedSidebar={false}>
      {error && showError && (
        <AlertGroup isToast isLiveRegion>
          <Alert
            variant="danger"
            title="Authentication Error"
            actionClose={
              <AlertActionCloseButton
                onClose={() => setShowError(false)}
              />
            }
            timeout={false}
          >
            {error}
            <br />
            <small>
              Check browser console (F12) for detailed logs.
            </small>
          </Alert>
        </AlertGroup>
      )}
      {children}
    </Page>
  );
};
