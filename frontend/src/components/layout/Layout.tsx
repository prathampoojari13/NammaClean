import React from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Navbar } from './Navbar';
import { Footer } from './Footer';

export const Layout: React.FC = () => {
  const pathname = useLocation().pathname;
  const isAuthRoute = pathname === '/login'
    || pathname === '/login/staff'
    || pathname === '/login/official'
    || pathname === '/register'
    || pathname === '/staff-access';

  return (
    <div
      className={isAuthRoute ? 'nc-app-layout nc-app-layout-auth' : 'nc-app-layout'}
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100vh',
      }}
    >
      {!isAuthRoute && <Navbar />}
      <main
        style={{
          flex: 1,
          paddingTop: isAuthRoute ? 0 : '2rem',
          paddingBottom: isAuthRoute ? 0 : '3rem',
        }}
      >
        <Outlet />
      </main>
      {!isAuthRoute && <Footer />}
    </div>
  );
};
