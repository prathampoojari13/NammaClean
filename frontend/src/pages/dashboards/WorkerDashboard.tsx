import React from 'react';
import { Card } from '../../components/ui/Card';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';

export const WorkerDashboard: React.FC = () => {
  return (
    <div className="container">
      <div style={{ marginBottom: '1.5rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--color-primary)' }}>
          Pourakarmika Portal (ಪೌರಕಾರ್ಮಿಕರ ವೇದಿಕೆ)
        </h1>
        <p style={{ color: 'var(--color-text-muted)' }}>
          Daily shift roll-call check-in and attendance verification.
        </p>
      </div>

      <Alert type="warning" title="Development Placeholder — Authorization Required in Production">
        This view is a development preview. In production, check-in is restricted to authenticated sanitation workers via <code>require_roles(SANITATION_WORKER)</code> with active ward assignments.
      </Alert>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '1.5rem',
        }}
      >
        <Card
          title="Daily Shift QR Check-In"
          subtitle="Stage 2.10 Backend Ready"
          style={{ gridColumn: 'span 2' }}
        >
          <div style={{ marginBottom: '1rem', lineHeight: 1.6, color: 'var(--color-text-muted)' }}>
            <p>
              Scans single-use muster station QR code and submits device coordinates via:
            </p>
            <code
              style={{
                display: 'block',
                backgroundColor: 'var(--color-bg-subtle)',
                padding: '0.5rem 0.75rem',
                borderRadius: 'var(--radius-sm)',
                marginTop: '0.5rem',
                fontSize: '0.85rem',
                color: 'var(--color-primary)',
              }}
            >
              POST /api/v1/attendance/qr-check-in
            </code>
          </div>

          <div
            style={{
              padding: '2rem 1.5rem',
              backgroundColor: 'var(--color-bg-subtle)',
              border: '1px dashed var(--color-border-dark)',
              borderRadius: 'var(--radius-md)',
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📷</div>
            <div style={{ fontWeight: 600, color: 'var(--color-text-main)', marginBottom: '0.5rem' }}>
              QR Camera Scanner Slot
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', maxWidth: '440px', margin: '0 auto 1.25rem' }}>
              When integrated, requests camera and geolocation permissions to scan the supervisor's 5-minute single-use QR token.
            </p>
            <Button variant="primary" disabled>
              Open Camera Scanner (Awaiting Auth)
            </Button>
          </div>
        </Card>

        <Card title="Attendance Rules" subtitle="Authoritative Verification">
          <ul style={{ paddingLeft: '1.25rem', fontSize: '0.875rem', color: 'var(--color-text-muted)', lineHeight: 1.8 }}>
            <li>Tokens expire strictly in 5 minutes (300 seconds).</li>
            <li>GPS location must be within muster station geofence (150m) for instant <code>PRESENT</code> status.</li>
            <li>Out-of-geofence check-ins are recorded with <code>EXCEPTION_PENDING</code> for supervisor approval.</li>
            <li>Strictly one check-in permitted per Asia/Kolkata workday.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
};
