import React from 'react';
import { Card } from '../../components/ui/Card';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';

export const SupervisorDashboard: React.FC = () => {
  return (
    <div className="container">
      <div style={{ marginBottom: '1.5rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--color-primary)' }}>
          BBMP Official & Supervisor Portal (ಮೇಲ್ವಿಚಾರಕರ ವೇದಿಕೆ)
        </h1>
        <p style={{ color: 'var(--color-text-muted)' }}>
          Ward administration, sanitation roll-call, and collection route oversight.
        </p>
      </div>

      <Alert type="warning" title="Development Placeholder — Authorization Required in Production">
        This view is a development preview. In production, access is strictly guarded by the backend dependency <code>require_roles(MUNICIPAL_ADMIN, WARD_SUPERVISOR)</code> and verified against active ward assignments.
      </Alert>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '1.5rem',
        }}
      >
        <Card
          title="Roll-Call QR Attendance Module"
          subtitle="Stage 2.10 Backend Ready"
          style={{ gridColumn: 'span 2' }}
        >
          <div style={{ marginBottom: '1rem', lineHeight: 1.6, color: 'var(--color-text-muted)' }}>
            <p>
              The backend attendance service provides 5-minute single-use QR tokens via:
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
              POST /api/v1/wards/{'{ward_id}'}/muster-points/{'{muster_point_id}'}/qr-code
            </code>
          </div>

          <div
            style={{
              padding: '1.5rem',
              backgroundColor: 'var(--color-bg-subtle)',
              border: '1px dashed var(--color-border-dark)',
              borderRadius: 'var(--radius-md)',
              textAlign: 'center',
              marginBottom: '1rem',
            }}
          >
            <div style={{ fontWeight: 600, color: 'var(--color-text-main)', marginBottom: '0.5rem' }}>
              Roll-Call QR Screen Component Slot
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', maxWidth: '480px', margin: '0 auto 1rem' }}>
              When authorized, the supervisor selects their assigned muster station and generates active 5-minute tokens for worker scanning.
            </p>
            <Button variant="primary" disabled>
              Generate Roll-Call QR (Awaiting Auth)
            </Button>
          </div>
        </Card>

        <Card title="Assigned Muster Stations" subtitle="Ward 150 (Bellandur)">
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <li style={{ padding: '0.5rem', backgroundColor: 'var(--color-bg-subtle)', borderRadius: 'var(--radius-sm)' }}>
              <strong>Bellandur Gate Station</strong>
              <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>Radius: 150m • Status: Active</div>
            </li>
            <li style={{ padding: '0.5rem', backgroundColor: 'var(--color-bg-subtle)', borderRadius: 'var(--radius-sm)' }}>
              <strong>Outer Ring Road Depot</strong>
              <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>Radius: 150m • Status: Active</div>
            </li>
          </ul>
        </Card>
      </div>
    </div>
  );
};
