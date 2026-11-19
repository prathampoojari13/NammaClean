import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/layout/Layout';
import { WelcomePage } from './pages/WelcomePage';
import { LoginPage } from './pages/LoginPage';
import { CitizenDashboard } from './pages/dashboards/CitizenDashboard';
import { SupervisorDashboard } from './pages/dashboards/SupervisorDashboard';
import { WorkerDashboard } from './pages/dashboards/WorkerDashboard';
import { NotFoundPage } from './pages/NotFoundPage';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CitizenDashboard />} />
        <Route path="/citizen" element={<CitizenDashboard />} />
        <Route element={<Layout />}>
          <Route path="welcome" element={<WelcomePage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="supervisor" element={<SupervisorDashboard />} />
          <Route path="worker" element={<WorkerDashboard />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
};

export default App;
