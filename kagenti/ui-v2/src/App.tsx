// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { Routes, Route } from 'react-router-dom';

import { AppLayout } from './components/AppLayout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { HomePage } from './pages/HomePage';
import { AgentCatalogPage } from './pages/AgentCatalogPage';
import { AgentDetailPage } from './pages/AgentDetailPage';
import { BuildProgressPage } from './pages/BuildProgressPage';
import { ToolCatalogPage } from './pages/ToolCatalogPage';
import { ToolDetailPage } from './pages/ToolDetailPage';
import { ToolBuildProgressPage } from './pages/ToolBuildProgressPage';
import { MCPGatewayPage } from './pages/MCPGatewayPage';
import { AIGatewayPage } from './pages/AIGatewayPage';
import { GatewayPoliciesPage } from './pages/GatewayPoliciesPage';
import { ObservabilityPage } from './pages/ObservabilityPage';
import { ImportAgentPage } from './pages/ImportAgentPage';
import { ImportToolPage } from './pages/ImportToolPage';
import { AdminPage } from './pages/AdminPage';
import { IntegrationsPage } from './pages/IntegrationsPage';
import { AddIntegrationPage } from './pages/AddIntegrationPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { SandboxPage } from './pages/SandboxPage';
import { SandboxCreatePage } from './pages/SandboxCreatePage';
import { SandboxesPage } from './pages/SandboxesPage';
import { SessionsTablePage } from './pages/SessionsTablePage';

function App() {
  return (
    <AppLayout>
      <Routes>
        {/* Public route - accessible to everyone */}
        <Route path="/" element={<HomePage />} />
        
        {/* Protected routes - require authentication */}
        <Route
          path="/agents"
          element={
            <ProtectedRoute>
              <AgentCatalogPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/agents/import"
          element={
            <ProtectedRoute>
              <ImportAgentPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/agents/:namespace/:name/build"
          element={
            <ProtectedRoute>
              <BuildProgressPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/agents/:namespace/:name"
          element={
            <ProtectedRoute>
              <AgentDetailPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/tools"
          element={
            <ProtectedRoute>
              <ToolCatalogPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/tools/import"
          element={
            <ProtectedRoute>
              <ImportToolPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/tools/:namespace/:name/build"
          element={
            <ProtectedRoute>
              <ToolBuildProgressPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/tools/:namespace/:name"
          element={
            <ProtectedRoute>
              <ToolDetailPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/integrations"
          element={
            <ProtectedRoute>
              <IntegrationsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/integrations/add"
          element={
            <ProtectedRoute>
              <AddIntegrationPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/integrations/:namespace/:name"
          element={
            <ProtectedRoute>
              <IntegrationsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/sessions"
          element={
            <ProtectedRoute>
              <SessionsTablePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/mcp-gateway"
          element={
            <ProtectedRoute>
              <MCPGatewayPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/ai-gateway"
          element={
            <ProtectedRoute>
              <AIGatewayPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/gateway-policies"
          element={
            <ProtectedRoute>
              <GatewayPoliciesPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/observability"
          element={
            <ProtectedRoute>
              <ObservabilityPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute>
              <AdminPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/sandbox"
          element={
            <ProtectedRoute>
              <SandboxPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/sandbox/create"
          element={
            <ProtectedRoute>
              <SandboxCreatePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/sandbox/sessions"
          element={
            <ProtectedRoute>
              <SessionsTablePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/sandboxes"
          element={
            <ProtectedRoute>
              <SandboxesPage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </AppLayout>
  );
}

export default App;
