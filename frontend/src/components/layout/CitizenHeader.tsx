import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDown, ChevronDown, Crosshair, LogIn, LogOut, MapPin, User as UserIcon } from 'lucide-react';
import { apiClient } from '../../api/client';
import type { User } from '../../types';
import { BENGALURU_LOCALITIES, LocalityOption } from '../../utils/localities';
import { UserProfileModal } from '../profile/UserProfileModal';
import { NotificationPanel } from '../notifications/NotificationPanel';

interface CitizenHeaderProps {
  onTrackClick?: () => void;
  selectedWardName?: string;
  onLocalityChange?: (locality: LocalityOption) => void;
}

export const CitizenHeader: React.FC<CitizenHeaderProps> = ({
  onTrackClick,
  selectedWardName = 'Bengaluru (Pilot: Yelahanka)',
  onLocalityChange,
}) => {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isProfileModalOpen, setIsProfileModalOpen] = useState(false);
  const [isLocalityMenuOpen, setIsLocalityMenuOpen] = useState(false);
  const [isLocatingUser, setIsLocatingUser] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const localityMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsMenuOpen(false);
      }
      if (localityMenuRef.current && !localityMenuRef.current.contains(e.target as Node)) {
        setIsLocalityMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
    };
  }, []);

  const handleDetectGPS = () => {
    if (!navigator.geolocation) {
      alert('Geolocation is not supported by your browser.');
      return;
    }
    setIsLocatingUser(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setIsLocatingUser(false);
        setIsLocalityMenuOpen(false);
        onLocalityChange?.({
          id: 'gps-current',
          name: 'My Current Location',
          zone: `GPS (±${Math.round(pos.coords.accuracy)}m)`,
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          isPilot: false,
        });
      },
      (err) => {
        setIsLocatingUser(false);
        alert('Could not retrieve current GPS position: ' + err.message);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

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
    window.location.replace('/login');
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
        {/* Location selector with citywide Bengaluru locality menu */}
        <div ref={localityMenuRef} style={{ position: 'relative' }}>
          <button
            type="button"
            onClick={() => setIsLocalityMenuOpen(!isLocalityMenuOpen)}
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
            title="Switch Bengaluru Locality or Ward"
          >
            <MapPin size={15} color="#2E7D32" />
            <span>{selectedWardName || 'Yelahanka, Bengaluru'}</span>
            <ChevronDown size={14} color="#5A7565" />
          </button>

          {isLocalityMenuOpen && (
            <div
              style={{
                position: 'absolute',
                top: '120%',
                left: 0,
                backgroundColor: '#FFFFFF',
                borderRadius: '12px',
                boxShadow: '0 12px 30px rgba(0,0,0,0.15)',
                border: '1px solid #D5E3D7',
                minWidth: '290px',
                zIndex: 1000,
                overflow: 'hidden',
                padding: '0.4rem 0',
              }}
            >
              <div
                style={{
                  padding: '0.5rem 1rem 0.35rem',
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  color: '#5A7565',
                  borderBottom: '1px solid #E5E7EB',
                }}
              >
                Bengaluru Locality Selector
              </div>

              {/* GPS Option */}
              <button
                type="button"
                onClick={handleDetectGPS}
                disabled={isLocatingUser}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.65rem',
                  padding: '0.65rem 1rem',
                  backgroundColor: '#F0FDF4',
                  border: 'none',
                  borderBottom: '1px solid #E5E7EB',
                  color: '#166534',
                  fontSize: '0.82rem',
                  fontWeight: 700,
                  textAlign: 'left',
                  cursor: isLocatingUser ? 'wait' : 'pointer',
                }}
              >
                <Crosshair size={15} color="#16A34A" />
                <span>{isLocatingUser ? 'Acquiring GPS Signal...' : '🎯 Use My Current Location (GPS)'}</span>
              </button>

              <div style={{ maxHeight: '280px', overflowY: 'auto' }}>
                {BENGALURU_LOCALITIES.map((loc) => {
                  const isCurrent =
                    selectedWardName?.includes(loc.name) || selectedWardName === loc.name;
                  return (
                    <button
                      key={loc.id}
                      type="button"
                      onClick={() => {
                        setIsLocalityMenuOpen(false);
                        onLocalityChange?.(loc);
                      }}
                      style={{
                        width: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '0.6rem 1rem',
                        backgroundColor: isCurrent ? '#F0FDF4' : 'transparent',
                        border: 'none',
                        color: isCurrent ? '#166534' : '#1F2937',
                        fontSize: '0.84rem',
                        textAlign: 'left',
                        cursor: 'pointer',
                        transition: 'background 0.15s ease',
                      }}
                      onMouseEnter={(e) => {
                        if (!isCurrent) e.currentTarget.style.backgroundColor = '#F9FAFB';
                      }}
                      onMouseLeave={(e) => {
                        if (!isCurrent) e.currentTarget.style.backgroundColor = 'transparent';
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: isCurrent ? 750 : 600 }}>{loc.name}</div>
                        <div style={{ fontSize: '0.72rem', color: '#6B7280' }}>{loc.zone}</div>
                      </div>
                      {loc.isPilot && (
                        <span
                          style={{
                            fontSize: '0.68rem',
                            fontWeight: 700,
                            padding: '2px 7px',
                            borderRadius: '999px',
                            backgroundColor: '#DCFCE7',
                            color: '#15803D',
                            border: '1px solid #BBF7D0',
                          }}
                        >
                          Live Pilot
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Main navigation & Account controls */}
        <nav className="nc-primary-nav" aria-label="Main navigation">
          {onTrackClick && (
            <button type="button" className="nc-nav-link" onClick={onTrackClick} style={{ color: '#183B2A' }}>
              <ArrowDown size={17} strokeWidth={2} aria-hidden="true" />
              <span>Track collection</span>
            </button>
          )}

          {/* Persistent Notification Center */}
          <NotificationPanel />

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
                  <>
                    <button
                      type="button"
                      onClick={() => {
                        setIsMenuOpen(false);
                        setIsProfileModalOpen(true);
                      }}
                      style={{
                        width: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        padding: '0.65rem 1rem',
                        border: 'none',
                        backgroundColor: 'transparent',
                        color: '#183B2A',
                        fontWeight: 600,
                        fontSize: '0.85rem',
                        cursor: 'pointer',
                        textAlign: 'left',
                        borderBottom: '1px solid #F3F4F6',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F5F9F5')}
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                    >
                      <UserIcon size={15} />
                      <span>My Profile</span>
                    </button>

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
                  </>
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

      <UserProfileModal
        isOpen={isProfileModalOpen}
        onClose={() => setIsProfileModalOpen(false)}
        currentUser={currentUser}
        onProfileUpdated={(updated) => setCurrentUser(updated)}
      />
    </header>
  );
};
