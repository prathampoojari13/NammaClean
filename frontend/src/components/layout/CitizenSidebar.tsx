import React from 'react';
import { Link } from 'react-router-dom';
import {
  LayoutDashboard,
  Truck,
  AlertTriangle,
  FileText,
  User,
  Bell,
} from 'lucide-react';

interface CitizenSidebarProps {
  activeTab?: string;
  onTabChange?: (tab: string) => void;
  notificationCount?: number;
}

export const CitizenSidebar: React.FC<CitizenSidebarProps> = ({
  activeTab = 'dashboard',
  onTabChange,
  notificationCount = 2,
}) => {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, path: '/citizen' },
    { id: 'track', label: 'Track Vehicles', icon: Truck, path: '/citizen' },
    { id: 'report', label: 'Report Dumping', icon: AlertTriangle, path: '/citizen' },
    { id: 'my-reports', label: 'My Reports', icon: FileText, path: '/citizen' },
    { id: 'profile', label: 'Profile', icon: User, path: '/citizen' },
    {
      id: 'notifications',
      label: 'Notifications',
      icon: Bell,
      path: '/citizen',
      badge: notificationCount,
    },
  ];

  const handleNavClick = (id: string, e: React.MouseEvent) => {
    if (onTabChange) {
      e.preventDefault();
      onTabChange(id);
    }
  };

  return (
    <aside
      style={{
        width: '250px',
        minWidth: '250px',
        backgroundColor: '#0B3024',
        color: '#FFFFFF',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '1.5rem 1rem',
        borderRight: '1px solid #144635',
        position: 'sticky',
        top: 0,
        height: '100vh',
        boxSizing: 'border-box',
        zIndex: 40,
      }}
    >
      {/* Top Branding & Navigation */}
      <div>
        {/* NammaClean Brand Header */}
        <Link
          to="/"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            textDecoration: 'none',
            color: 'inherit',
            marginBottom: '2rem',
            paddingLeft: '0.5rem',
          }}
        >
          {/* Stylized Leaf Logo */}
          <div
            style={{
              width: '40px',
              height: '40px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <svg
              width="36"
              height="36"
              viewBox="0 0 48 48"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              {/* Central Leaf */}
              <path
                d="M24 6C24 6 15 15 15 27C15 33.6 19 39 24 42C29 39 33 33.6 33 27C33 15 24 6 24 6Z"
                fill="#52B788"
              />
              <path
                d="M24 10V40"
                stroke="#1B4332"
                strokeWidth="2.5"
                strokeLinecap="round"
              />
              {/* Left Leaf */}
              <path
                d="M17 19C17 19 8 23 8 32C8 36.5 11 40 15 41C15 37 16 29 17 19Z"
                fill="#74C69D"
              />
              {/* Right Leaf */}
              <path
                d="M31 19C31 19 40 23 40 32C40 36.5 37 40 33 41C33 37 32 29 31 19Z"
                fill="#40916C"
              />
            </svg>
          </div>
          <div>
            <div
              style={{
                fontSize: '1.25rem',
                fontWeight: 700,
                letterSpacing: '-0.02em',
                lineHeight: 1.1,
                color: '#FFFFFF',
              }}
            >
              NammaClean
            </div>
            <div
              style={{
                fontSize: '0.68rem',
                color: '#74C69D',
                marginTop: '2px',
                fontWeight: 500,
              }}
            >
              Clean Bengaluru. Green Bengaluru.
            </div>
          </div>
        </Link>

        {/* Navigation List */}
        <nav style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          {navItems.map((item) => {
            const isActive = activeTab === item.id;
            const Icon = item.icon;

            return (
              <a
                key={item.id}
                href={item.path}
                onClick={(e) => handleNavClick(item.id, e)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '0.65rem 0.85rem',
                  borderRadius: '10px',
                  color: isActive ? '#FFFFFF' : '#A7D7C5',
                  backgroundColor: isActive ? '#175640' : 'transparent',
                  textDecoration: 'none',
                  fontSize: '0.9rem',
                  fontWeight: isActive ? 600 : 500,
                  transition: 'background-color 0.15s ease, color 0.15s ease',
                  cursor: 'pointer',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.backgroundColor = 'rgba(23, 86, 64, 0.45)';
                    e.currentTarget.style.color = '#FFFFFF';
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.backgroundColor = 'transparent';
                    e.currentTarget.style.color = '#A7D7C5';
                  }
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <Icon size={18} strokeWidth={isActive ? 2.2 : 1.8} />
                  <span>{item.label}</span>
                </div>

                {item.badge !== undefined && (
                  <span
                    style={{
                      backgroundColor: '#EF4444',
                      color: '#FFFFFF',
                      fontSize: '0.7rem',
                      fontWeight: 700,
                      padding: '2px 7px',
                      borderRadius: '9999px',
                      lineHeight: 1.2,
                    }}
                  >
                    {item.badge}
                  </span>
                )}
              </a>
            );
          })}
        </nav>
      </div>

      {/* Bottom Vidhana Soudha Illustration & Slogan */}
      <div
        style={{
          borderTop: '1px solid rgba(116, 198, 157, 0.2)',
          paddingTop: '1.25rem',
          textAlign: 'center',
        }}
      >
        {/* Subtle Vidhana Soudha Architectural Silhouette */}
        <div style={{ marginBottom: '0.75rem', opacity: 0.85 }}>
          <svg
            width="140"
            height="55"
            viewBox="0 0 160 60"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            style={{ margin: '0 auto', display: 'block' }}
          >
            {/* Base platform */}
            <rect x="10" y="52" width="140" height="4" fill="#2D6A4F" />
            <rect x="20" y="48" width="120" height="4" fill="#40916C" />
            {/* Colonnade columns */}
            <rect x="35" y="32" width="4" height="16" fill="#52B788" />
            <rect x="45" y="32" width="4" height="16" fill="#52B788" />
            <rect x="55" y="32" width="4" height="16" fill="#52B788" />
            <rect x="65" y="32" width="4" height="16" fill="#52B788" />
            <rect x="75" y="32" width="4" height="16" fill="#52B788" />
            <rect x="85" y="32" width="4" height="16" fill="#52B788" />
            <rect x="95" y="32" width="4" height="16" fill="#52B788" />
            <rect x="105" y="32" width="4" height="16" fill="#52B788" />
            <rect x="115" y="32" width="4" height="16" fill="#52B788" />
            <rect x="125" y="32" width="4" height="16" fill="#52B788" />
            {/* Central Dome & Pediment */}
            <polygon points="70,32 90,32 80,24" fill="#74C69D" />
            <path
              d="M72 24 C72 16, 88 16, 88 24 Z"
              fill="#95D5B2"
            />
            <rect x="79" y="10" width="2" height="6" fill="#D8F3DC" />
            <circle cx="80" cy="9" r="2" fill="#D8F3DC" />
            {/* Side Pavilions */}
            <path d="M26 36 C26 30, 36 30, 36 36 Z" fill="#74C69D" />
            <path d="M124 36 C124 30, 134 30, 134 36 Z" fill="#74C69D" />
            {/* Trees in foreground */}
            <circle cx="20" cy="46" r="6" fill="#1B4332" />
            <circle cx="28" cy="48" r="5" fill="#2D6A4F" />
            <circle cx="132" cy="48" r="5" fill="#2D6A4F" />
            <circle cx="140" cy="46" r="6" fill="#1B4332" />
          </svg>
        </div>

        {/* Civic Motto in Script Styling */}
        <div
          style={{
            fontFamily: "'Caveat', cursive, sans-serif",
            fontSize: '1.15rem',
            fontWeight: 600,
            color: '#B7E4C7',
            lineHeight: 1.25,
            letterSpacing: '0.01em',
          }}
        >
          A Cleaner Bengaluru
          <br />
          <span style={{ fontSize: '1rem', color: '#95D5B2' }}>
            For a Better Tomorrow
          </span>
        </div>
      </div>
    </aside>
  );
};
