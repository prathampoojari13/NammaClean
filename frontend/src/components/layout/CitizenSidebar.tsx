import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Home,
  AlertTriangle,
  FileText,
  Car,
  Info,
  User,
  CalendarCheck,
  ClipboardList,
  Users,
  BarChart3,
  Truck,
  LayoutDashboard,
} from 'lucide-react';

export type DashboardRole = 'citizen' | 'worker' | 'supervisor' | 'admin';

interface CitizenSidebarProps {
  role?: DashboardRole;
  activeTab?: string;
  onTabChange?: (tab: string) => void;
  onReportClick?: () => void;
  notificationCount?: number;
}

export const CitizenSidebar: React.FC<CitizenSidebarProps> = ({
  role = 'citizen',
  activeTab = 'dashboard',
  onTabChange,
  onReportClick,
  notificationCount,
}) => {
  const navigate = useNavigate();

  const getNavItems = () => {
    switch (role) {
      case 'worker':
        return [
          { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, path: '/worker' },
          { id: 'attendance', label: 'Attendance', icon: CalendarCheck, path: '/worker' },
          { id: 'tasks', label: 'My Tasks', icon: ClipboardList, path: '/worker' },
          { id: 'vehicle', label: 'Vehicle Info', icon: Truck, path: '/worker' },
          { id: 'profile', label: 'Profile', icon: User, path: '/worker' },
        ];
      case 'supervisor':
      case 'admin':
        return [
          { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, path: '/supervisor' },
          { id: 'vehicles', label: 'Vehicle Monitoring', icon: Truck, path: '/supervisor' },
          { id: 'reports', label: 'Citizen Reports', icon: FileText, path: '/supervisor' },
          { id: 'workers', label: 'Worker Attendance', icon: Users, path: '/supervisor' },
          { id: 'analytics', label: 'Operations Roster', icon: BarChart3, path: '/supervisor' },
        ];
      case 'citizen':
      default:
        return [
          { id: 'dashboard', label: 'Dashboard', icon: Home, path: '/citizen' },
          { id: 'report', label: 'Report Illegal Dumping', icon: AlertTriangle, path: '/citizen' },
          { id: 'my-reports', label: 'My Reports', icon: FileText, path: '/citizen' },
          { id: 'track', label: 'Track Vehicles', icon: Car, path: '/citizen' },
          { id: 'about', label: 'About', icon: Info, path: '/welcome' },
        ];
    }
  };

  const navItems = getNavItems();

  const handleNavClick = (item: { id: string; path: string }, e: React.MouseEvent) => {
    if (item.id === 'report' && onReportClick) {
      e.preventDefault();
      onReportClick();
      return;
    }

    if (item.id === 'about' || item.path.startsWith('/welcome')) {
      e.preventDefault();
      navigate(item.path);
      return;
    }

    if (onTabChange) {
      e.preventDefault();
      onTabChange(item.id);
    }
  };

  return (
    <aside
      className="nc-dashboard-sidebar"
      style={{
        width: '260px',
        minWidth: '260px',
        backgroundColor: '#063321',
        color: '#FFFFFF',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '1.5rem 1rem 1.25rem',
        borderRadius: '24px',
        margin: '12px',
        height: 'calc(100vh - 24px)',
        position: 'sticky',
        top: '12px',
        boxSizing: 'border-box',
        zIndex: 40,
        overflow: 'hidden',
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.12)',
      }}
    >
      {/* Top Branding & Navigation */}
      <div style={{ position: 'relative', zIndex: 2 }}>
        {/* NammaClean Brand Header matching reference image */}
        <Link
          to="/"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.85rem',
            textDecoration: 'none',
            color: 'inherit',
            marginBottom: '2rem',
            paddingLeft: '0.4rem',
          }}
        >
          <div
            style={{
              width: '42px',
              height: '42px',
              backgroundColor: '#FFFFFF',
              borderRadius: '12px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '3px',
              boxSizing: 'border-box',
              flexShrink: 0,
              boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
            }}
          >
            <img
              src="/assets/namma-clean-brand-mark.png"
              alt="NammaClean"
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'contain',
              }}
            />
          </div>
          <div>
            <div
              style={{
                fontSize: '1.28rem',
                fontWeight: 750,
                letterSpacing: '-0.02em',
                lineHeight: 1.15,
                color: '#FFFFFF',
              }}
            >
              NammaClean
            </div>
            <div
              style={{
                fontSize: '0.72rem',
                color: '#74C69D',
                marginTop: '2px',
                fontWeight: 600,
                letterSpacing: '0.01em',
              }}
            >
              Green Bengaluru
            </div>
          </div>
        </Link>

        {/* Navigation List matching reference image */}
        <nav style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
          {navItems.map((item) => {
            const isActive = activeTab === item.id;
            const Icon = item.icon;

            const activeColor = '#063321';
            const activeBg = '#CFE8D5';
            const inactiveColor = '#FFFFFF';
            const hoverBg = 'rgba(255, 255, 255, 0.08)';

            return (
              <a
                key={item.id}
                href={item.path}
                onClick={(e) => handleNavClick(item, e)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '0.75rem 1rem',
                  borderRadius: '16px',
                  color: isActive ? activeColor : inactiveColor,
                  backgroundColor: isActive ? activeBg : 'transparent',
                  textDecoration: 'none',
                  fontSize: '0.92rem',
                  fontWeight: isActive ? 750 : 500,
                  boxShadow: isActive ? '0 2px 8px rgba(0, 0, 0, 0.12)' : 'none',
                  transition: 'background-color 0.15s ease, color 0.15s ease',
                  cursor: 'pointer',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.backgroundColor = hoverBg;
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.backgroundColor = 'transparent';
                    e.currentTarget.style.color = inactiveColor;
                  }
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
                  <Icon
                    size={20}
                    strokeWidth={isActive ? 2.4 : 1.8}
                    fill={isActive && item.id === 'dashboard' ? 'currentColor' : 'none'}
                  />
                  <span>{item.label}</span>
                </div>

                {item.id === 'notifications' && notificationCount && (
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
                    {notificationCount}
                  </span>
                )}
              </a>
            );
          })}
        </nav>
      </div>

      {/* Bottom Leaf Graphic & Slogan matching reference image */}
      <div style={{ position: 'relative', width: '100%', minHeight: '150px' }}>
        {/* Organic two-leaf vector in bottom-left corner */}
        <svg
          width="200"
          height="210"
          viewBox="0 0 200 210"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          style={{
            position: 'absolute',
            bottom: '-20px',
            left: '-16px',
            pointerEvents: 'none',
            zIndex: 1,
          }}
        >
          <defs>
            <linearGradient id="leafGradLeft" x1="0" y1="210" x2="70" y2="30" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#1B4D36" stopOpacity="0.65" />
              <stop offset="45%" stopColor="#2E7D32" stopOpacity="0.48" />
              <stop offset="85%" stopColor="#52B788" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#74C69D" stopOpacity="0.25" />
            </linearGradient>
            <linearGradient id="leafGradRight" x1="25" y1="160" x2="160" y2="100" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#1B4D36" stopOpacity="0.6" />
              <stop offset="50%" stopColor="#2E7D32" stopOpacity="0.45" />
              <stop offset="85%" stopColor="#52B788" stopOpacity="0.32" />
              <stop offset="100%" stopColor="#74C69D" stopOpacity="0.2" />
            </linearGradient>
            <linearGradient id="stemGrad" x1="0" y1="210" x2="60" y2="50" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#2E7D32" stopOpacity="0.65" />
              <stop offset="100%" stopColor="#74C69D" stopOpacity="0.45" />
            </linearGradient>
          </defs>

          {/* Tall Left Leaf curving along left border */}
          <path
            d="M 0 210 C 15 150, 10 80, 56 32 C 68 65, 66 115, 38 165 C 24 190, 12 205, 0 210 Z"
            fill="url(#leafGradLeft)"
          />
          <path
            d="M 0 210 C 16 155, 24 95, 56 32"
            stroke="url(#stemGrad)"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <path
            d="M 22 135 C 32 125, 42 110, 48 95"
            stroke="#74C69D"
            strokeWidth="1.2"
            strokeOpacity="0.28"
            strokeLinecap="round"
          />

          {/* Pointed Right Leaf branching towards center */}
          <path
            d="M 32 165 C 55 130, 100 110, 160 118 C 132 145, 90 168, 32 165 Z"
            fill="url(#leafGradRight)"
          />
          <path
            d="M 32 165 C 75 142, 115 130, 160 118"
            stroke="url(#stemGrad)"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
          <path
            d="M 75 145 C 92 135, 115 125, 130 126"
            stroke="#74C69D"
            strokeWidth="1.2"
            strokeOpacity="0.28"
            strokeLinecap="round"
          />
        </svg>

        {/* Clean City / Green Tomorrow Centered Text */}
        <div
          style={{
            position: 'absolute',
            bottom: '4px',
            left: 0,
            right: 0,
            zIndex: 2,
            textAlign: 'center',
            pointerEvents: 'none',
          }}
        >
          <div
            style={{
              fontSize: '1.02rem',
              fontWeight: 750,
              color: '#FFFFFF',
              lineHeight: 1.25,
              letterSpacing: '-0.01em',
            }}
          >
            Clean City
          </div>
          <div
            style={{
              fontSize: '0.82rem',
              fontWeight: 600,
              color: '#74C69D',
              marginTop: '2px',
            }}
          >
            Green Tomorrow
          </div>
        </div>
      </div>
    </aside>
  );
};
