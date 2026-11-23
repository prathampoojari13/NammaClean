import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Alert } from '../components/ui/Alert';
import { Button } from '../components/ui/Button';
import { AuthBrandPanel } from '../components/auth/AuthBrandPanel';
import { apiClient } from '../api/client';
import type { User } from '../types';

export const RegisterPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < 12) {
      setError('Password must be at least 12 characters.');
      return;
    }

    setSubmitting(true);
    try {
      await apiClient.post<User>('/auth/register', { email, password });
      navigate('/login', { replace: true, state: { registered: true } });
    } catch (reason) {
      const detail = typeof reason === 'object' && reason !== null && 'detail' in reason
        ? String((reason as { detail: unknown }).detail)
        : 'Could not create your citizen account. Please try again.';
      setError(detail);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="nc-login-page nc-register-page">
      <AuthBrandPanel />
      <section className="nc-login-card" aria-labelledby="register-heading">
        <div className="nc-auth-heading">
          <span className="nc-auth-eyebrow">Citizen account</span>
          <h1 id="register-heading">Create account</h1>
          <p className="nc-login-subtitle">Register to access Bengaluru's public civic dashboard.</p>
        </div>
        {error && <Alert type="danger" title="Registration failed">{error}</Alert>}
        <form onSubmit={handleSubmit} className="nc-login-form">
          <label htmlFor="register-email">Email address</label>
          <input
            id="register-email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <label htmlFor="register-password">Password</label>
          <input
            id="register-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <label htmlFor="register-confirm-password">Confirm password</label>
          <input
            id="register-confirm-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
          />
          <p className="nc-auth-password-note">Use at least 12 characters.</p>
          <Button type="submit" variant="primary" isLoading={submitting} style={{ width: '100%', minHeight: 46 }}>
            Create citizen account
          </Button>
        </form>
        <p className="nc-auth-switch">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </section>
    </main>
  );
};
