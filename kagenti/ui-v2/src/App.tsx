// Copyright 2025 IBM Corp.
// Licensed under the Apache License, Version 2.0

import { Routes, Route } from 'react-router-dom';

import { AppLayout } from './components/AppLayout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { HomePage } from './pages/HomePage';
import { AgentCatalogPage } from './pages/AgentCatalogPage';
import { AgentDetailPage } from './pages/AgentDetailPage';
import { ToolCatalogPage } from './pages/ToolCatalogPage';
import { ToolDetailPage } from './pages/ToolDetailPage';
import { MCPGatewayPage } from './pages/MCPGatewayPage';
import { AIGatewayPage } from './pages/AIGatewayPage';
import { GatewayPoliciesPage } from './pages/GatewayPoliciesPage';
import { ObservabilityPage } from './pages/ObservabilityPage';
import { ImportAgentPage } from './pages/ImportAgentPage';
import { ImportToolPage } from './pages/ImportToolPage';
import { AdminPage } from './pages/AdminPage';
import { NotFoundPage } from './pages/NotFoundPage';

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
          path="/tools/:namespace/:name"
          element={
            <ProtectedRoute>
              <ToolDetailPage />
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
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </AppLayout>
  );
}

export default App;
