import React, { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowDown, Bell, ChevronDown, LogIn, LogOut, MapPin } from 'lucide-react';
import { apiClient } from '../../api/client';
import type { User } from '../../types';

interface CitizenHeaderProps {
  onTrackClick?: () => void;
  selectedWardName?: string;
}

export const CitizenHeader: React.FC<CitizenHeaderProps> = ({
  onTrackClick,
  selectedWardName = 'Bengaluru (Pilot: Yelahanka)',
}) => {
  const navigate = useNavigate();
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isMenuOpen) return;
    const handleOutsideClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
    };
  }, [isMenuOpen]);

  useEffect(() => {
    const token = localStorage.getItem('nammaclean.access_token');
    if (!token) {
      setCurrentUser(null);
      return;
    }

    let active = true;
    apiClient
      .get<User>('/users/me')
      .then((user) => {
        if (active) setCurrentUser(user);
      })
      .catch(() => {
        if (active) setCurrentUser(null);
      });

    const handleUnauthorized = () => {
      if (active) setCurrentUser(null);
    };
    const handleLogout = () => {
      if (active) setCurrentUser(null);
    };

    window.addEventListener('nammaclean:unauthorized', handleUnauthorized);
    window.addEventListener('nammaclean:logout', handleLogout);

    return () => {
      active = false;
      window.removeEventListener('nammaclean:unauthorized', handleUnauthorized);
      window.removeEventListener('nammaclean:logout', handleLogout);
    };
  }, []);

  const handleSignOut = () => {
    apiClient.logout();
    navigate('/login', { replace: true });
  };

  const getInitials = (user?: User | null) => {
    if (!user) return 'NC';
    if (user.full_name && user.full_name.trim().length > 0) {
      const parts = user.full_name.trim().split(/\s+/);
      if (parts.length >= 2) {
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
      }
      return parts[0].slice(0, 2).toUpperCase();
    }
    if (user.email) {
      const namePart = user.email.split('@')[0];
      const parts = namePart.split(/[._-]/);
      if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
      }
      return namePart.slice(0, 2).toUpperCase();
    }
    return 'NC';
  };

  const getRoleLabel = (role?: string) => {
    switch (role) {
      case 'CITIZEN':
        return 'Citizen';
      case 'SANITATION_WORKER':
        return 'Pourakarmika';
      case 'DRIVER':
        return 'Driver';
      case 'WARD_SUPERVISOR':
        return 'Ward Supervisor';
      case 'MUNICIPAL_ADMIN':
        return 'Municipal Admin';
      default:
        return 'Citizen';
    }
  };

  const getDisplayName = (user?: User | null) => {
    if (!user) return 'Citizen';
    if (user.full_name && user.full_name.trim().length > 0) {
      return user.full_name.trim();
    }
    if (user.locality && user.locality.trim().length > 0) {
      return user.locality.trim();
    }
    if (user.email) {
      const namePart = user.email.split('@')[0];
      const parts = namePart.split(/[._-]/);
      if (parts.length >= 2) {
        return `${parts[0].charAt(0).toUpperCase() + parts[0].slice(1)} ${parts[1].charAt(0).toUpperCase() + parts[1].slice(1)}`;
      }
      return namePart.charAt(0).toUpperCase() + namePart.slice(1);
    }
    return 'Citizen';
  };

  return (
    <header className="nc-citizen-header">
      <div className="nc-header-inner">
        {/* Location selector matching reference screenshot */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.45rem',
            backgroundColor: '#FFFFFF',
            padding: '0.4rem 0.95rem',
            borderRadius: '9999px',
            fontSize: '0.85rem',
            fontWeight: 600,
            color: '#183B2A',
            border: '1px solid #D5E3D7',
            boxShadow: '0 2px 5px rgba(0,0,0,0.04)',
            cursor: 'pointer',
          }}
          title="Active Operational Pilot: Yelahanka (Bengaluru)"
        >
          <MapPin size={15} color="#2E7D32" />
          <span>{selectedWardName || 'Yelahanka, Bengaluru'}</span>
          <ChevronDown size={14} color="#5A7565" />
        </div>

        {/* Main navigation & Account controls */}
        <nav className="nc-primary-nav" aria-label="Main navigation">
          {onTrackClick && (
            <button type="button" className="nc-nav-link" onClick={onTrackClick} style={{ color: '#183B2A' }}>
              <ArrowDown size={17} strokeWidth={2} aria-hidden="true" />
              <span>Track collection</span>
            </button>
          )}

          {/* Notification bell matching reference screenshot */}
          <button
            type="button"
            aria-label="Notifications"
            style={{
              position: 'relative',
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              border: '1px solid #D5E3D7',
              backgroundColor: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#183B2A',
              cursor: 'pointer',
              boxShadow: '0 2px 6px rgba(0, 0, 0, 0.04)',
            }}
            title="Notifications"
          >
            <Bell size={17} strokeWidth={2} aria-hidden="true" />
            <span
              style={{
                position: 'absolute',
                top: '7px',
                right: '7px',
                width: '7px',
                height: '7px',
                backgroundColor: '#2E7D32',
                borderRadius: '50%',
              }}
            />
          </button>

          {/* User profile pill matching reference screenshot */}
          <div ref={menuRef} style={{ position: 'relative' }}>
            <button
              type="button"
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.55rem',
                backgroundColor: '#FFFFFF',
                border: '1px solid #D5E3D7',
                borderRadius: '9999px',
                padding: '4px 12px 4px 5px',
                color: '#183B2A',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: '0.85rem',
                boxShadow: '0 2px 6px rgba(0, 0, 0, 0.04)',
              }}
            >
              <div
                style={{
                  width: '28px',
                  height: '28px',
                  borderRadius: '50%',
                  backgroundColor: '#0F3D2E',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 700,
                  fontSize: '0.72rem',
                  color: '#FFFFFF',
                }}
              >
                {getInitials(currentUser)}
              </div>
              <span>{getDisplayName(currentUser)}</span>
              <ChevronDown size={14} color="#5A7565" />
            </button>

            {isMenuOpen && (
              <div
                style={{
                  position: 'absolute',
                  top: '115%',
                  right: 0,
                  backgroundColor: '#FFFFFF',
                  color: '#1F2937',
                  borderRadius: '10px',
                  boxShadow: '0 10px 25px rgba(0,0,0,0.2)',
                  minWidth: '220px',
                  padding: '0.5rem 0',
                  zIndex: 100,
                  border: '1px solid #E5E7EB',
                }}
              >
                <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid #F3F4F6' }}>
                  <div style={{ fontSize: '0.8rem', color: '#6B7280' }}>Signed in as</div>
                  <div style={{ fontWeight: 600, fontSize: '0.9rem', wordBreak: 'break-all' }}>
                    {currentUser ? currentUser.email : 'Guest Citizen'}
                  </div>
                  {currentUser?.role && (
                    <div style={{ fontSize: '0.72rem', color: '#2E7D32', fontWeight: 600, marginTop: '2px' }}>
                      {getRoleLabel(currentUser.role)}
                    </div>
                  )}
                </div>
                {currentUser ? (
                  <button
                    type="button"
                    onClick={handleSignOut}
                    style={{
                      width: '100%',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      padding: '0.65rem 1rem',
                      border: 'none',
                      backgroundColor: 'transparent',
                      color: '#DC2626',
                      fontWeight: 600,
                      fontSize: '0.875rem',
                      cursor: 'pointer',
                      textAlign: 'left',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#FEE2E2')}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                  >
                    <LogOut size={16} />
                    <span>Sign Out</span>
                  </button>
                ) : (
                  <Link
                    to="/login"
                    onClick={() => setIsMenuOpen(false)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      padding: '0.65rem 1rem',
                      color: '#2E7D32',
                      textDecoration: 'none',
                      fontWeight: 600,
                      fontSize: '0.875rem',
                    }}
                  >
                    <LogIn size={16} />
                    <span>Sign In</span>
                  </Link>
                )}
              </div>
            )}
          </div>
        </nav>
      </div>
    </header>
  );
};
