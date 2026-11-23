import React from 'react';
import { Link } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Alert } from '../components/ui/Alert';

export const WelcomePage: React.FC = () => {
  const portals = [
    {
      title: 'Citizen Portal',
      description: 'View ward collection schedules, locate waste drop-off points, and report blackspot garbage dumping with geo-tagged photo evidence.',
      path: '/citizen',
      role: 'Citizens & Residents',
      actionText: 'Open Citizen View',
    },
    {
      title: 'BBMP Supervisor Portal',
      description: 'Manage ward sanitation operations, oversee collection routes, and conduct daily roll-call attendance with 5-minute single-use QR tokens.',
      path: '/supervisor',
      role: 'Ward Supervisors & Municipal Admins',
      actionText: 'Open Supervisor View',
    },
    {
      title: 'Pourakarmika Worker Portal',
      description: 'Daily shift attendance verification. Scan muster station QR codes with GPS geofence verification to record attendance.',
      path: '/worker',
      role: 'Sanitation Workers',
      actionText: 'Open Worker View',
    },
  ];

  return (
    <div className="container">
      <div style={{ textAlign: 'center', marginBottom: '2.5rem' }}>
        <h1
          style={{
            fontSize: '2.5rem',
            fontWeight: 800,
            color: 'var(--color-primary)',
            marginBottom: '0.75rem',
            letterSpacing: '-0.025em',
          }}
        >
          NammaClean (ನಮ್ಮಕ್ಲೀನ್)
        </h1>
        <p
          style={{
            fontSize: '1.125rem',
            color: 'var(--color-text-muted)',
            maxWidth: '720px',
            margin: '0 auto',
          }}
        >
          Bengaluru Municipal Solid Waste Management & Evidence-Based Fleet Telemetry Platform.
        </p>
      </div>

      <Alert type="info" title="Development Environment Foundation">
        The NammaClean frontend is currently running in initial scaffolding mode alongside the FastAPI backend. Full authentication and API wiring will be connected in subsequent integration steps.
      </Alert>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '1.5rem',
          marginTop: '2rem',
        }}
      >
        {portals.map((portal) => (
          <Card
            key={portal.title}
            title={portal.title}
            subtitle={portal.role}
            style={{
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
            }}
          >
            <p
              style={{
                fontSize: '0.95rem',
                color: 'var(--color-text-muted)',
                marginBottom: '1.5rem',
                lineHeight: 1.6,
              }}
            >
              {portal.description}
            </p>
            <Link to={portal.path} style={{ textDecoration: 'none' }}>
              <Button variant="primary" style={{ width: '100%' }}>
                {portal.actionText}
              </Button>
            </Link>
          </Card>
        ))}
      </div>
    </div>
  );
};
