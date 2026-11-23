import React from 'react';
import { Link } from 'react-router-dom';
import { Building2, Truck } from 'lucide-react';
import { AuthBrandPanel } from '../components/auth/AuthBrandPanel';

export const StaffAccessPage: React.FC = () => (
  <main className="nc-login-page nc-staff-access-page">
    <AuthBrandPanel />
    <section className="nc-staff-access-content" aria-labelledby="staff-access-heading">
      <div className="nc-auth-heading">
        <span className="nc-auth-eyebrow">Secure portal</span>
        <h1 id="staff-access-heading">Staff &amp; Official Access</h1>
        <p className="nc-login-subtitle">
          Choose the sign-in link for your work area. Your access is determined by your verified account role.
        </p>
      </div>
      <div className="nc-staff-access-grid">
        <article className="nc-staff-access-card">
          <span className="nc-staff-access-icon"><Truck size={21} aria-hidden="true" /></span>
          <h2>Sanitation Workforce</h2>
          <p>For sanitation workers and drivers with provisioned NammaClean accounts.</p>
          <Link className="nc-staff-login-action" to="/login/staff">Worker Login</Link>
        </article>
        <article className="nc-staff-access-card">
          <span className="nc-staff-access-icon"><Building2 size={21} aria-hidden="true" /></span>
          <h2>Municipal Administration</h2>
          <p>For ward supervisors and authorized municipal administrators.</p>
          <Link className="nc-staff-login-action" to="/login/official">Official Login</Link>
        </article>
      </div>
      <p className="nc-staff-provision-note">
        Staff and official accounts must be provisioned by authorized administrators. Public registration is for citizens only.
      </p>
      <p className="nc-auth-switch"><Link to="/login">Back to sign in</Link></p>
    </section>
  </main>
);
