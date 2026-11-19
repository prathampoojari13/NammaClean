import React from 'react';
import { Link, useLocation } from 'react-router-dom';

export const Navbar: React.FC = () => {
  const location = useLocation();

  const navLinks = [
    { label: 'Overview', path: '/' },
    { label: 'Citizen Portal', path: '/citizen' },
    { label: 'Supervisor Portal', path: '/supervisor' },
    { label: 'Sanitation Worker', path: '/worker' },
  ];

  return (
    <header
      style={{
        backgroundColor: 'var(--color-primary)',
        color: 'var(--color-text-inverse)',
        boxShadow: 'var(--shadow-md)',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}
    >
      <div
        className="container"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          height: '4rem',
        }}
      >
        <Link
          to="/"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            color: 'inherit',
            textDecoration: 'none',
          }}
        >
          <div
            style={{
              backgroundColor: 'var(--color-accent)',
              color: 'var(--color-primary)',
              width: '2.25rem',
              height: '2.25rem',
              borderRadius: 'var(--radius-md)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 700,
              fontSize: '1.25rem',
            }}
          >
            ನ
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '1.2rem', lineHeight: 1.1 }}>
              NammaClean
            </div>
            <div
              style={{
                fontSize: '0.75rem',
                color: 'var(--color-accent)',
                letterSpacing: '0.02em',
              }}
            >
              ನಮ್ಮಕ್ಲೀನ್ • BBMP Civic Solid Waste
            </div>
          </div>
        </Link>

        <nav
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '1.5rem',
          }}
        >
          {navLinks.map((link) => {
            const isActive = location.pathname === link.path;
            return (
              <Link
                key={link.path}
                to={link.path}
                style={{
                  color: isActive ? 'var(--color-accent)' : 'var(--color-text-inverse)',
                  textDecoration: 'none',
                  fontSize: '0.925rem',
                  fontWeight: isActive ? 600 : 400,
                  borderBottom: isActive ? '2px solid var(--color-accent)' : '2px solid transparent',
                  paddingBottom: '0.25rem',
                  transition: 'color 0.15s ease',
                }}
              >
                {link.label}
              </Link>
            );
          })}
          <Link
            to="/login"
            style={{
              backgroundColor: 'var(--color-secondary)',
              color: 'var(--color-text-inverse)',
              padding: '0.4rem 0.9rem',
              borderRadius: 'var(--radius-md)',
              fontSize: '0.875rem',
              fontWeight: 500,
              textDecoration: 'none',
              marginLeft: '0.5rem',
              border: '1px solid var(--color-accent)',
            }}
          >
            Sign In
          </Link>
        </nav>
      </div>
    </header>
  );
};
