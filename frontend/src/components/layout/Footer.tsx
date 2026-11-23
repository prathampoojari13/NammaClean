import React from 'react';

export const Footer: React.FC = () => {
  return (
    <footer
      style={{
        backgroundColor: 'var(--color-bg-surface)',
        borderTop: '1px solid var(--color-border)',
        marginTop: 'auto',
        padding: '2rem 0',
      }}
    >
      <div
        className="container"
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
          gap: '0.75rem',
        }}
      >
        <div style={{ fontWeight: 600, color: 'var(--color-primary)' }}>
          NammaClean (ನಮ್ಮಕ್ಲೀನ್)
        </div>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-muted)', maxWidth: '600px' }}>
          Evidence-based municipal solid waste management, fleet telemetry, and Pourakarmika shift roll-call for Bruhat Bengaluru Mahanagara Palike (BBMP).
        </p>
        <div style={{ fontSize: '0.75rem', color: 'var(--color-text-subtle)' }}>
          © {new Date().getFullYear()} NammaClean Project • Connected to FastAPI Backend on port 8000
        </div>
      </div>
    </footer>
  );
};
