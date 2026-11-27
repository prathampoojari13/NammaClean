import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  ShieldCheck,
  MapPin,
  Truck,
  AlertTriangle,
  QrCode,
  LogIn,
  Users,
  Compass,
} from 'lucide-react';
import { fetchPublicMapSummary } from '../api/publicMap';
import { PublicMapSummary } from '../types';

export const WelcomePage: React.FC = () => {
  const [summary, setSummary] = useState<PublicMapSummary | null>(null);

  useEffect(() => {
    let active = true;
    fetchPublicMapSummary()
      .then((data) => {
        if (active) setSummary(data);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  return (
    <div style={{ backgroundColor: '#F8FAF9', minHeight: '100vh', color: '#183B2A' }}>
      {/* Top Navigation Bar */}
      <header
        style={{
          backgroundColor: '#0F382A',
          color: '#FFFFFF',
          padding: '1rem 2rem',
          borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
        }}
      >
        <div
          style={{
            maxWidth: '1280px',
            margin: '0 auto',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '1rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <div
              style={{
                width: '38px',
                height: '38px',
                borderRadius: '9px',
                backgroundColor: '#2D6A4F',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 800,
                fontSize: '1.1rem',
                color: '#FFFFFF',
                boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
              }}
            >
              NC
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <span style={{ fontSize: '1.25rem', fontWeight: 800, letterSpacing: '-0.02em' }}>
                  NammaClean
                </span>
                <span
                  style={{
                    backgroundColor: '#74C69D',
                    color: '#0A291E',
                    fontSize: '0.72rem',
                    fontWeight: 750,
                    padding: '2px 7px',
                    borderRadius: '999px',
                  }}
                >
                  ನಮ್ಮಕ್ಲೀನ್
                </span>
              </div>
              <div style={{ fontSize: '0.75rem', color: '#A3D9BA' }}>
                Bruhat Bengaluru Mahanagara Palike (BBMP) Civic SWM
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Link
              to="/citizen"
              style={{
                textDecoration: 'none',
                color: '#FFFFFF',
                fontSize: '0.85rem',
                fontWeight: 650,
                padding: '6px 14px',
                borderRadius: '7px',
                backgroundColor: 'rgba(255, 255, 255, 0.1)',
              }}
            >
              Citizen View
            </Link>
            <Link
              to="/login"
              style={{
                textDecoration: 'none',
                color: '#0A291E',
                backgroundColor: '#74C69D',
                fontSize: '0.85rem',
                fontWeight: 700,
                padding: '6px 16px',
                borderRadius: '7px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.4rem',
              }}
            >
              <LogIn size={15} />
              <span>Sign In</span>
            </Link>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section
        style={{
          background: 'linear-gradient(180deg, #0F382A 0%, #184D3B 60%, #F8FAF9 100%)',
          color: '#FFFFFF',
          padding: '3.5rem 1.5rem 4rem 1.5rem',
          textAlign: 'center',
        }}
      >
        <div style={{ maxWidth: '860px', margin: '0 auto' }}>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.5rem',
              backgroundColor: 'rgba(116, 198, 157, 0.18)',
              border: '1px solid rgba(116, 198, 157, 0.35)',
              padding: '4px 14px',
              borderRadius: '999px',
              fontSize: '0.82rem',
              fontWeight: 700,
              color: '#D8F3DC',
              marginBottom: '1.25rem',
            }}
          >
            <span>🌿 ಸ್ಮಾರ್ಟ್ ತ್ಯಾಜ್ಯ ನಿರ್ವಹಣೆ ಮತ್ತು ನಾಗರಿಕ ಸೇವೆಗಳು</span>
          </div>

          <h1
            style={{
              fontSize: '2.75rem',
              fontWeight: 850,
              lineHeight: 1.15,
              letterSpacing: '-0.03em',
              marginBottom: '1.25rem',
            }}
          >
            Evidence-Based Solid Waste Management &amp; Civic Redressal for Bengaluru
          </h1>

          <p
            style={{
              fontSize: '1.15rem',
              lineHeight: 1.6,
              color: '#E8F5E9',
              maxWidth: '720px',
              margin: '0 auto 2.25rem auto',
              fontWeight: 450,
            }}
          >
            NammaClean connects Bengaluru citizens, Pourakarmikas, collection drivers, and BBMP supervisors
            into a transparent municipal platform for blackspot elimination, verified muster attendance,
            and real-time fleet collection telemetry.
          </p>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '1rem',
              flexWrap: 'wrap',
            }}
          >
            <Link
              to="/citizen"
              style={{
                textDecoration: 'none',
                backgroundColor: '#2E7D32',
                color: '#FFFFFF',
                padding: '12px 26px',
                borderRadius: '9px',
                fontWeight: 750,
                fontSize: '1rem',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.5rem',
                boxShadow: '0 4px 14px rgba(46, 125, 50, 0.4)',
                border: '1px solid #4CAF50',
              }}
            >
              <span>Open Citizen Portal</span>
              <ArrowRight size={18} />
            </Link>

            <Link
              to="/login/official"
              style={{
                textDecoration: 'none',
                backgroundColor: 'rgba(255, 255, 255, 0.12)',
                color: '#FFFFFF',
                padding: '12px 22px',
                borderRadius: '9px',
                fontWeight: 700,
                fontSize: '1rem',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.5rem',
                border: '1px solid rgba(255, 255, 255, 0.25)',
              }}
            >
              <ShieldCheck size={18} />
              <span>BBMP Official Login</span>
            </Link>
          </div>
        </div>
      </section>

      {/* Real Civic Telemetry Counters */}
      <section style={{ maxWidth: '1120px', margin: '-2rem auto 2.5rem auto', padding: '0 1.5rem' }}>
        <div
          style={{
            backgroundColor: '#FFFFFF',
            borderRadius: '14px',
            border: '1px solid #D5E3D7',
            padding: '1.5rem',
            boxShadow: '0 10px 25px rgba(0,0,0,0.04)',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '1.25rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <div style={{ backgroundColor: '#E8F5E9', padding: '10px', borderRadius: '10px', color: '#2E7D32' }}>
              <Compass size={24} />
            </div>
            <div>
              <div style={{ fontSize: '0.78rem', color: '#5A7565', fontWeight: 650 }}>Pilot Operational Corridor</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#183B2A' }}>Ward 4 - Yelahanka</div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <div style={{ backgroundColor: '#E0F2FE', padding: '10px', borderRadius: '10px', color: '#0369A1' }}>
              <Truck size={24} />
            </div>
            <div>
              <div style={{ fontSize: '0.78rem', color: '#5A7565', fontWeight: 650 }}>Monitored Fleet Vehicles</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#183B2A' }}>
                {summary ? `${summary.active_live_vehicles} Active` : 'Operational Pilot'}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <div style={{ backgroundColor: '#FEF3C7', padding: '10px', borderRadius: '10px', color: '#B45309' }}>
              <MapPin size={24} />
            </div>
            <div>
              <div style={{ fontSize: '0.78rem', color: '#5A7565', fontWeight: 650 }}>Collection Points &amp; Routes</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#183B2A' }}>
                {summary ? `${summary.published_collection_points} Points` : 'Mapped Routes'}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            <div style={{ backgroundColor: '#F3E8FF', padding: '10px', borderRadius: '10px', color: '#7E22CE' }}>
              <Users size={24} />
            </div>
            <div>
              <div style={{ fontSize: '0.78rem', color: '#5A7565', fontWeight: 650 }}>Sanitation Workforce</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#183B2A' }}>Verified Roll-Call</div>
            </div>
          </div>
        </div>
      </section>

      {/* Core Civic Capabilities */}
      <section style={{ maxWidth: '1120px', margin: '0 auto 4rem auto', padding: '0 1.5rem' }}>
        <div style={{ textAlign: 'center', marginBottom: '2.5rem' }}>
          <h2 style={{ fontSize: '1.85rem', fontWeight: 800, color: '#183B2A', letterSpacing: '-0.02em', margin: '0 0 0.5rem 0' }}>
            Integrated Solid Waste Municipal Architecture
          </h2>
          <p style={{ fontSize: '0.98rem', color: '#5A7565', maxWidth: '640px', margin: '0 auto' }}>
            Built specifically for Bengaluru’s civic operations with institutional safeguards, GPS verification, and honest telemetry.
          </p>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
            gap: '1.5rem',
          }}
        >
          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '12px',
              padding: '1.5rem',
              border: '1px solid #D5E3D7',
              boxShadow: '0 2px 8px rgba(0,0,0,0.02)',
            }}
          >
            <div style={{ backgroundColor: '#FEE2E2', color: '#DC2626', width: '42px', height: '42px', borderRadius: '9px', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '1rem' }}>
              <AlertTriangle size={20} />
            </div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 750, color: '#183B2A', margin: '0 0 0.4rem 0' }}>
              Blackspot Reporting
            </h3>
            <p style={{ fontSize: '0.88rem', color: '#5A7565', lineHeight: 1.5, margin: 0 }}>
              Citizens report illegal waste dumping with map pin selection, satellite imagery, and watermarked photo evidence.
            </p>
          </div>

          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '12px',
              padding: '1.5rem',
              border: '1px solid #D5E3D7',
              boxShadow: '0 2px 8px rgba(0,0,0,0.02)',
            }}
          >
            <div style={{ backgroundColor: '#E8F5E9', color: '#2E7D32', width: '42px', height: '42px', borderRadius: '9px', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '1rem' }}>
              <Truck size={20} />
            </div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 750, color: '#183B2A', margin: '0 0 0.4rem 0' }}>
              Fleet Telemetry
            </h3>
            <p style={{ fontSize: '0.88rem', color: '#5A7565', lineHeight: 1.5, margin: 0 }}>
              Live compactor and auto-tipper tracking with honest freshness indicators, straight-line distance, and arrival notices.
            </p>
          </div>

          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '12px',
              padding: '1.5rem',
              border: '1px solid #D5E3D7',
              boxShadow: '0 2px 8px rgba(0,0,0,0.02)',
            }}
          >
            <div style={{ backgroundColor: '#E0F2FE', color: '#0369A1', width: '42px', height: '42px', borderRadius: '9px', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '1rem' }}>
              <QrCode size={20} />
            </div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 750, color: '#183B2A', margin: '0 0 0.4rem 0' }}>
              Muster &amp; Attendance
            </h3>
            <p style={{ fontSize: '0.88rem', color: '#5A7565', lineHeight: 1.5, margin: 0 }}>
              Pourakarmika roll-call verified at muster depots with 150m geofence precision and single-use cryptographic QR tokens.
            </p>
          </div>

          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '12px',
              padding: '1.5rem',
              border: '1px solid #D5E3D7',
              boxShadow: '0 2px 8px rgba(0,0,0,0.02)',
            }}
          >
            <div style={{ backgroundColor: '#F3E8FF', color: '#7E22CE', width: '42px', height: '42px', borderRadius: '9px', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '1rem' }}>
              <ShieldCheck size={20} />
            </div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 750, color: '#183B2A', margin: '0 0 0.4rem 0' }}>
              Role Governance
            </h3>
            <p style={{ fontSize: '0.88rem', color: '#5A7565', lineHeight: 1.5, margin: 0 }}>
              Municipal Administrators, Ward Supervisors, Drivers, and Workers operate with server-enforced role boundaries.
            </p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer
        style={{
          borderTop: '1px solid #D5E3D7',
          backgroundColor: '#FFFFFF',
          padding: '2rem 1.5rem',
          textAlign: 'center',
          fontSize: '0.82rem',
          color: '#5A7565',
        }}
      >
        <div style={{ maxWidth: '1120px', margin: '0 auto' }}>
          <div style={{ fontWeight: 700, color: '#183B2A', marginBottom: '0.25rem' }}>
            NammaClean (ನಮ್ಮಕ್ಲೀನ್) — Bruhat Bengaluru Mahanagara Palike
          </div>
          <div>Solid Waste Management &amp; Fleet Telemetry Monitoring System</div>
        </div>
      </footer>
    </div>
  );
};
