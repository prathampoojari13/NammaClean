import React, { useState } from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Alert } from '../components/ui/Alert';

export const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
  };

  return (
    <div
      className="container"
      style={{
        maxWidth: '460px',
        marginTop: '2rem',
      }}
    >
      <Card
        title="Sign In to NammaClean"
        subtitle="Access your municipal, supervisory, or worker dashboard"
      >
        <Alert type="warning" title="Authentication Integration Pending">
          Real credentials must be authenticated against the backend endpoint <code>/api/v1/auth/login</code>. No mock authentication or hardcoded logins are permitted.
        </Alert>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div>
            <label
              htmlFor="email"
              style={{
                display: 'block',
                fontSize: '0.875rem',
                fontWeight: 500,
                color: 'var(--color-text-main)',
                marginBottom: '0.35rem',
              }}
            >
              Official / Registered Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. supervisor@bbmp.gov.in"
              style={{
                width: '100%',
                padding: '0.6rem 0.75rem',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--color-border)',
                backgroundColor: 'var(--color-bg-surface)',
                outline: 'none',
              }}
            />
          </div>

          <div>
            <label
              htmlFor="password"
              style={{
                display: 'block',
                fontSize: '0.875rem',
                fontWeight: 500,
                color: 'var(--color-text-main)',
                marginBottom: '0.35rem',
              }}
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              style={{
                width: '100%',
                padding: '0.6rem 0.75rem',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--color-border)',
                backgroundColor: 'var(--color-bg-surface)',
                outline: 'none',
              }}
            />
          </div>

          <Button
            type="submit"
            variant="primary"
            style={{ width: '100%', marginTop: '0.5rem' }}
          >
            Authenticate via Backend
          </Button>

          <p
            style={{
              fontSize: '0.8rem',
              color: 'var(--color-text-subtle)',
              textAlign: 'center',
            }}
          >
            Authorized access for BBMP officials, ward supervisors, sanitation workers, and registered citizens.
          </p>
        </form>
      </Card>
    </div>
  );
};
