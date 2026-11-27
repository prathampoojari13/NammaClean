import React, { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Layout } from './components/layout/Layout';
import { WelcomePage } from './pages/WelcomePage';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { StaffAccessPage } from './pages/StaffAccessPage';
import { CitizenDashboard } from './pages/dashboards/CitizenDashboard';
import { SupervisorDashboard } from './pages/dashboards/SupervisorDashboard';
import { WorkerDashboard } from './pages/dashboards/WorkerDashboard';
import { DriverDashboard } from './pages/dashboards/DriverDashboard';
import { AdminDashboard } from './pages/dashboards/AdminDashboard';
import { NotFoundPage } from './pages/NotFoundPage';
import { apiClient } from './api/client';
import type { User, UserRole } from './types';

const ALLOWED_CITIZEN: UserRole[] = ['CITIZEN'];
const ALLOWED_SUPERVISOR: UserRole[] = ['WARD_SUPERVISOR', 'MUNICIPAL_ADMIN'];
const ALLOWED_WORKER: UserRole[] = ['SANITATION_WORKER', 'DRIVER'];
const ALLOWED_DRIVER: UserRole[] = ['DRIVER'];
const ALLOWED_ADMIN: UserRole[] = ['MUNICIPAL_ADMIN'];

const RoleRoute: React.FC<{ allowed: UserRole[]; children: React.ReactElement }> = ({ allowed, children }) => {
  const location = useLocation();
  const [state, setState] = useState<'loading' | 'allowed' | 'denied'>('loading');

  useEffect(() => {
    const token = localStorage.getItem('nammaclean.access_token');
    if (!token) {
      setState('denied');
      return;
    }
    apiClient.setToken(token);
    let active = true;

    apiClient
      .get<User>('/users/me')
      .then((user) => {
        if (active) {
          setState(allowed.includes(user.role) ? 'allowed' : 'denied');
        }
      })
      .catch(() => {
        if (active) setState('denied');
      });

    return () => {
      active = false;
    };
  }, [allowed, location.pathname]);

  if (state === 'loading') {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          backgroundColor: '#0B3024',
          color: '#FFFFFF',
        }}
      >
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '1.25rem', fontWeight: 800, letterSpacing: '-0.02em', marginBottom: '0.4rem' }}>
            NammaClean
          </div>
          <div style={{ fontSize: '0.85rem', color: '#74C69D' }}>Verifying role authorization...</div>
        </div>
      </div>
    );
  }

  if (state === 'denied') return <Navigate to="/login" replace />;
  return children;
};

export const App: React.FC = () => {
  useEffect(() => {
    // Back-Forward Cache (bfcache) protection:
    // If a cached page is restored via browser back-button after logout, ensure immediate redirect.
    const handlePageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        const token = localStorage.getItem('nammaclean.access_token');
        const path = window.location.pathname;
        const isPublicPath = path === '/' || path === '/welcome' || path.startsWith('/login') || path === '/register';
        if (!token && !isPublicPath) {
          window.location.replace('/login');
        }
      }
    };
    window.addEventListener('pageshow', handlePageShow);
    return () => {
      window.removeEventListener('pageshow', handlePageShow);
    };
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CitizenDashboard />} />
        <Route
          path="/citizen"
          element={
            <RoleRoute allowed={ALLOWED_CITIZEN}>
              <CitizenDashboard />
            </RoleRoute>
          }
        />
        <Route
          path="/supervisor"
          element={
            <RoleRoute allowed={ALLOWED_SUPERVISOR}>
              <SupervisorDashboard />
            </RoleRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <RoleRoute allowed={ALLOWED_ADMIN}>
              <AdminDashboard />
            </RoleRoute>
          }
        />
        <Route
          path="/worker"
          element={
            <RoleRoute allowed={ALLOWED_WORKER}>
              <WorkerDashboard />
            </RoleRoute>
          }
        />
        <Route
          path="/driver"
          element={
            <RoleRoute allowed={ALLOWED_DRIVER}>
              <DriverDashboard />
            </RoleRoute>
          }
        />
        <Route element={<Layout />}>
          <Route path="welcome" element={<WelcomePage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="login/staff" element={<LoginPage />} />
          <Route path="login/official" element={<LoginPage />} />
          <Route path="register" element={<RegisterPage />} />
          <Route path="staff-access" element={<StaffAccessPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
};

export default App;