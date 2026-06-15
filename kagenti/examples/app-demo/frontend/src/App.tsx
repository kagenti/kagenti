import React from 'react';
import { Routes, Route } from 'react-router-dom';

import { AppLayout } from '@/components/AppLayout';
import { ProtectedRoute } from '@/components/ProtectedRoute';
import { LandingPage } from '@/pages/LandingPage';
import { AgentListPage } from '@/pages/AgentListPage';
import { ChatPage } from '@/pages/ChatPage';

export const App: React.FC = () => {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<LandingPage />} />
        <Route
          path="agents"
          element={
            <ProtectedRoute>
              <AgentListPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="chat/:namespace/:name"
          element={
            <ProtectedRoute>
              <ChatPage />
            </ProtectedRoute>
          }
        />
      </Route>
    </Routes>
  );
};
