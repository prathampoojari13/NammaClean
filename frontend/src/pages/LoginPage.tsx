import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Eye, EyeOff, LockKeyhole, Mail, UserRoundPlus, UsersRound } from 'lucide-react';
import { Button } from '../components/ui/Button';
import { Alert } from '../components/ui/Alert';
import { AuthBrandPanel } from '../components/auth/AuthBrandPanel';
import { apiClient } from '../api/client';
import type { AuthTokens, User } from '../types';

type LoginAudience = 'citizen' | 'staff' | 'official';

const roleDestinations: Partial<Record<User['role'], {
  audience: LoginAudience;
  path: string;
  label: string;
  loginPath: string;
  loginLabel: string;
}>> = {
  CITIZEN: {
    audience: 'citizen',
    path: '/citizen',
    label: 'citizen',
    loginPath: '/login',
    loginLabel: 'Citizen Login',
  },
  SANITATION_WORKER: {
    audience: 'staff',
    path: '/worker',
    label: 'sanitation workforce',
    loginPath: '/login/staff',
    loginLabel: 'Staff Login',
  },
  DRIVER: {
    audience: 'staff',
    path: '/driver',
    label: 'sanitation workforce',
    loginPath: '/login/staff',
    loginLabel: 'Staff Login',
  },
  WARD_SUPERVISOR: {
    audience: 'official',
    path: '/supervisor',
    label: 'municipal administration',
    loginPath: '/login/official',
    loginLabel: 'Official Login',
  },
  MUNICIPAL_ADMIN: {
    audience: 'official',
    path: '/supervisor',
    label: 'municipal administration',
    loginPath: '/login/official',
    loginLabel: 'Official Login',
  },
};

export const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const locationState = location.state as { registered?: boolean; loginNotice?: string } | null;
  const registered = locationState?.registered === true;
  const audience: LoginAudience = location.pathname === '/login/staff'
    ? 'staff'
    : location.pathname === '/login/official'
      ? 'official'
      : 'citizen';
  const loginNotice = typeof locationState?.loginNotice === 'string'
    ? locationState.loginNotice
    : null;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const tokens = await apiClient.post<AuthTokens>('/auth/login', { email, password });
      apiClient.setToken(tokens.access_token);
      localStorage.setItem('nammaclean.access_token', tokens.access_token);

      const user = await apiClient.get<User>('/users/me');
      const roleDestination = roleDestinations[user.role];
      if (!roleDestination) {
        throw new Error('Your account role is not recognized.');
      }

      if (audience !== 'citizen' && roleDestination.audience !== audience) {
        apiClient.setToken(null);
        localStorage.removeItem('nammaclean.access_token');
        localStorage.removeItem('nammaclean.user_role');
        navigate(roleDestination.loginPath, {
          replace: true,
          state: {
            loginNotice: `This verified account is for ${roleDestination.label} access. Please use ${roleDestination.loginLabel}.`,
          },
        });
        return;
      }

      localStorage.setItem('nammaclean.user_role', user.role);
      navigate(roleDestination.path, { replace: true });
    } catch (reason) {
      const detail = typeof reason === 'object' && reason !== null && 'detail' in reason
        ? String((reason as { detail: unknown }).detail)
        : reason instanceof Error
          ? reason.message
          : 'Could not sign in. Please try again.';
      setError(detail);
      apiClient.setToken(null);
      localStorage.removeItem('nammaclean.access_token');
      localStorage.removeItem('nammaclean.user_role');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="nc-login-page nc-login-page-login" key={location.pathname}>
      <AuthBrandPanel />
      <section className="nc-login-card" aria-labelledby="login-heading">
        <div className="nc-auth-heading nc-login-heading">
          <h1 id="login-heading">
            {audience === 'staff' ? 'Staff Login' : audience === 'official' ? 'Official Login' : 'Welcome Back!'}
          </h1>
          <p className="nc-login-subtitle">
            {audience === 'staff'
              ? 'Sign in to access your NammaClean workforce account.'
              : audience === 'official'
                ? 'Sign in to access the NammaClean municipal administration portal.'
                : 'Login to access your NammaClean account'}
          </p>
        </div>
        {loginNotice && <Alert type="info" title="Use the correct sign-in page">{loginNotice}</Alert>}
        {registered && (
          <Alert type="success" title="Registration complete">
            Your citizen account is ready. Sign in to continue.
          </Alert>
        )}
        {error && <Alert type="danger" title="Sign-in failed">{error}</Alert>}
        <form onSubmit={handleSubmit} className="nc-login-form">
          <div className="nc-login-input-wrap">
            <label className="nc-visually-hidden" htmlFor="email">Email address</label>
            <Mail size={21} strokeWidth={1.8} aria-hidden="true" />
            <input id="email" type="email" autoComplete="email" placeholder="Email Address" required value={email} onChange={(event) => setEmail(event.target.value)} />
          </div>
          <div className="nc-login-input-wrap">
            <label className="nc-visually-hidden" htmlFor="password">Password</label>
            <LockKeyhole size={21} strokeWidth={1.8} aria-hidden="true" />
            <input id="password" type={passwordVisible ? 'text' : 'password'} autoComplete="current-password" placeholder="Password" required value={password} onChange={(event) => setPassword(event.target.value)} />
            <button
              className="nc-password-toggle"
              type="button"
              aria-label={passwordVisible ? 'Hide password' : 'Show password'}
              aria-pressed={passwordVisible}
              onClick={() => setPasswordVisible((visible) => !visible)}
            >
              {passwordVisible ? <EyeOff size={20} aria-hidden="true" /> : <Eye size={20} aria-hidden="true" />}
            </button>
          </div>
          <Button
            className="nc-login-submit"
            type="submit"
            variant="primary"
            isLoading={submitting}
            style={{ width: '100%', minHeight: 58, gap: 12, borderRadius: 12, fontWeight: 700 }}
          >
            <span>Login</span>
            <ArrowRight size={23} strokeWidth={2} aria-hidden="true" />
          </Button>
        </form>
        {audience === 'citizen' ? (
          <>
            <div className="nc-auth-divider" aria-label="or"><span>or</span></div>
            <Link className="nc-register-cta" to="/register">
              <UserRoundPlus size={22} strokeWidth={2.2} aria-hidden="true" />
              <span>Register as a Citizen</span>
            </Link>
            <p className="nc-auth-staff-link">
              <UsersRound size={20} fill="currentColor" strokeWidth={1.6} aria-hidden="true" />
              <Link to="/staff-access">Are you a NammaClean staff member?</Link>
            </p>
          </>
        ) : (
          <>
            <p className="nc-audience-note">
              {audience === 'staff'
                ? 'Staff accounts must be provisioned by authorized administrators.'
                : 'Official accounts must be provisioned by authorized administrators.'}
            </p>
            <p className="nc-auth-staff-link nc-audience-back-link">
              <ArrowLeft size={18} aria-hidden="true" />
              <Link to="/staff-access">Back to Staff &amp; Official Access</Link>
            </p>
          </>
        )}
        <div className="nc-bmsit-credit">
          <img src="/assets/bmsit-institution-logo.svg" alt="BMS Institute of Technology and Management" />
          <div className="nc-bmsit-credit-copy">
            <span>Made by students of BMSIT</span>
            {' '}
            <small>NammaClean is not an official BMSIT product.</small>
          </div>
        </div>
      </section>
    </main>
  );
};
