import React from 'react';
import { Link } from 'react-router-dom';
import { Button } from '../components/ui/Button';

export const NotFoundPage: React.FC = () => {
  return (
    <div
      className="container"
      style={{
        textAlign: 'center',
        paddingTop: '4rem',
        paddingBottom: '4rem',
      }}
    >
      <h1
        style={{
          fontSize: '4rem',
          fontWeight: 800,
          color: 'var(--color-primary)',
          marginBottom: '0.5rem',
        }}
      >
        404
      </h1>
      <h2 style={{ fontSize: '1.5rem', fontWeight: 600, marginBottom: '1rem' }}>
        Page Not Found
      </h2>
      <p style={{ color: 'var(--color-text-muted)', marginBottom: '1.5rem' }}>
        The requested civic portal page or resource does not exist.
      </p>
      <Link to="/" style={{ textDecoration: 'none' }}>
        <Button variant="primary">Return to Overview</Button>
      </Link>
    </div>
  );
};
