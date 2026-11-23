import React from 'react';

export const AuthBrandPanel: React.FC = () => (
  <div className="nc-auth-brand-panel">
    <div className="nc-auth-photo" aria-hidden="true">
      <img
        src="/assets/vidhana-soudha-login.jpg"
        alt=""
      />
    </div>
    <div className="nc-auth-photo-brand">
      <span className="nc-auth-logo-tile">
        <img src="/assets/namma-clean-brand-mark.png" alt="" />
      </span>
      <span className="nc-auth-wordmark">
        <strong>NammaClean</strong>
        <span>Clean Bengaluru. Healthy Tomorrow.</span>
      </span>
    </div>
  </div>
);
