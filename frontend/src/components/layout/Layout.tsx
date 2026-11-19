import React from 'react';
import { Outlet } from 'react-router-dom';
import { Navbar } from './Navbar';
import { Footer } from './Footer';

export const Layout: React.FC = () => {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100vh',
      }}
    >
      <Navbar />
      <main
        style={{
          flex: 1,
          paddingTop: '2rem',
          paddingBottom: '3rem',
        }}
      >
        <Outlet />
      </main>
      <Footer />
    </div>
  );
};
