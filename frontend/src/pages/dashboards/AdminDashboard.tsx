import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users,
  Truck,
  ShieldCheck,
  UserPlus,
  Search,
  CheckCircle2,
  AlertCircle,
  Phone,
  Mail,
  RefreshCw,
  LogOut,
  X,
  Eye,
  EyeOff,
  UserCheck,
  MapPin,
  ChevronDown,
  User as UserIcon,
} from 'lucide-react';
import { apiClient } from '../../api/client';
import { fetchWorkforce, createOperationalUser, WorkforceMember } from '../../api/admin';
import { fetchWardsForSelection, WardSummary } from '../../api/reports';
import { User, UserRole } from '../../types';
import { UserProfileModal } from '../../components/profile/UserProfileModal';
import { NotificationPanel } from '../../components/notifications/NotificationPanel';

export const AdminDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [workforce, setWorkforce] = useState<WorkforceMember[]>([]);
  const [wards, setWards] = useState<WardSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<'ALL' | UserRole>('ALL');

  // Modal State
  const [isRegisterModalOpen, setIsRegisterModalOpen] = useState(false);
  const [modalRole, setModalRole] = useState<'SANITATION_WORKER' | 'DRIVER'>('SANITATION_WORKER');
  const [formData, setFormData] = useState({
    full_name: '',
    official_id: '',
    email: '',
    phone_number: '',
    password: '',
    ward_id: '',
  });
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);

  // Profile Drawer State
  const [selectedStaff, setSelectedStaff] = useState<WorkforceMember | null>(null);

  // Profile Modal & Header Menu State
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false);
  const [isProfileModalOpen, setIsProfileModalOpen] = useState(false);

  const getInitials = (user?: User | null) => {
    if (!user) return 'AD';
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
    return 'AD';
  };

  const loadData = useCallback(async () => {
    try {
      const [userRes, workforceRes, wardsRes] = await Promise.all([
        apiClient.get<User>('/users/me'),
        fetchWorkforce(),
        fetchWardsForSelection().catch(() => []),
      ]);
      setCurrentUser(userRes);
      setWorkforce(workforceRes);
      setWards(wardsRes);
    } catch (err: any) {
      console.error('Failed to load admin dashboard data:', err);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    loadData();
  };

  const handleSignOut = () => {
    apiClient.logout();
    window.location.replace('/login');
  };

  const openRegisterModal = (role: 'SANITATION_WORKER' | 'DRIVER') => {
    setModalRole(role);
    setFormData({
      full_name: '',
      official_id: '',
      email: '',
      phone_number: '',
      password: '',
      ward_id: wards.length > 0 ? wards[0].id : '',
    });
    setSubmitError(null);
    setSubmitSuccess(null);
    setIsRegisterModalOpen(true);
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);

    try {
      if (formData.password.length < 12) {
        throw new Error('Password must be at least 12 characters long.');
      }

      await createOperationalUser({
        email: formData.email.trim(),
        password: formData.password,
        role: modalRole,
        full_name: formData.full_name.trim() || undefined,
        official_id: formData.official_id.trim() || undefined,
        phone_number: formData.phone_number.trim() || undefined,
        ward_id: formData.ward_id || undefined,
      });

      setSubmitSuccess(
        `New ${modalRole === 'SANITATION_WORKER' ? 'Pourakarmika' : 'Driver'} account created successfully!`
      );
      setTimeout(() => {
        setIsRegisterModalOpen(false);
        loadData();
      }, 1200);
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to create personnel account.';
      setSubmitError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setIsSubmitting(false);
    }
  };

  const filteredWorkforce = useMemo(() => {
    return workforce.filter((item) => {
      const matchesRole = roleFilter === 'ALL' || item.role === roleFilter;
      const q = searchQuery.toLowerCase().trim();
      const matchesSearch =
        !q ||
        (item.full_name && item.full_name.toLowerCase().includes(q)) ||
        item.email.toLowerCase().includes(q) ||
        (item.official_id && item.official_id.toLowerCase().includes(q)) ||
        (item.ward_name && item.ward_name.toLowerCase().includes(q));
      return matchesRole && matchesSearch;
    });
  }, [workforce, roleFilter, searchQuery]);

  // Statistics
  const totalCount = workforce.length;
  const workerCount = workforce.filter((w) => w.role === 'SANITATION_WORKER').length;
  const driverCount = workforce.filter((w) => w.role === 'DRIVER').length;
  const supervisorCount = workforce.filter((w) => w.role === 'WARD_SUPERVISOR').length;

  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          backgroundColor: '#0B3024',
          color: '#FFFFFF',
          fontFamily: 'system-ui, sans-serif',
        }}
      >
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: '0.5rem' }}>NammaClean</div>
          <div style={{ fontSize: '0.9rem', color: '#74C69D' }}>Loading Municipal Administration Portal...</div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#F4F7F4', fontFamily: 'system-ui, sans-serif' }}>
      {/* Top Municipal Navigation Bar */}
      <header
        style={{
          backgroundColor: '#0E3A28',
          color: '#FFFFFF',
          padding: '0.85rem 2rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid rgba(255,255,255,0.1)',
          position: 'sticky',
          top: 0,
          zIndex: 40,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div
            style={{
              backgroundColor: '#1E5E41',
              width: '38px',
              height: '38px',
              borderRadius: '9px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 800,
              fontSize: '1.15rem',
              color: '#FFFFFF',
            }}
          >
            NC
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ fontSize: '1.15rem', fontWeight: 800, letterSpacing: '-0.02em' }}>
                NammaClean Administration
              </span>
              <span
                style={{
                  backgroundColor: '#74C69D',
                  color: '#0B3024',
                  fontSize: '0.7rem',
                  fontWeight: 750,
                  padding: '2px 7px',
                  borderRadius: '999px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}
              >
                BBMP Official
              </span>
            </div>
            <div style={{ fontSize: '0.78rem', color: '#A3D9BA' }}>
              Municipal Workforce & Civic Governance Command Center
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isRefreshing}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.4rem',
              backgroundColor: 'rgba(255,255,255,0.1)',
              color: '#FFFFFF',
              border: 'none',
              padding: '6px 12px',
              borderRadius: '7px',
              fontSize: '0.82rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <RefreshCw size={14} className={isRefreshing ? 'nc-refreshing' : ''} />
            <span>Refresh</span>
          </button>

          <button
            type="button"
            onClick={() => navigate('/supervisor')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.4rem',
              backgroundColor: 'rgba(255,255,255,0.12)',
              color: '#FFFFFF',
              border: 'none',
              padding: '6px 12px',
              borderRadius: '7px',
              fontSize: '0.82rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <ShieldCheck size={14} />
            <span>Supervisor Portal</span>
          </button>

          <NotificationPanel />

          <div style={{ height: '24px', width: '1px', backgroundColor: 'rgba(255,255,255,0.2)' }} />

          <div style={{ position: 'relative' }}>
            <button
              type="button"
              onClick={() => setIsProfileMenuOpen(!isProfileMenuOpen)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.65rem',
                backgroundColor: 'rgba(255, 255, 255, 0.1)',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                color: '#FFFFFF',
                padding: '5px 10px 5px 6px',
                borderRadius: '8px',
                cursor: 'pointer',
              }}
            >
              <div
                style={{
                  width: '28px',
                  height: '28px',
                  borderRadius: '50%',
                  backgroundColor: '#2D6A4F',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 700,
                  fontSize: '0.75rem',
                  color: '#FFFFFF',
                  border: '1px solid #74C69D',
                }}
              >
                {getInitials(currentUser)}
              </div>
              <div style={{ textAlign: 'left' }}>
                <div style={{ fontSize: '0.82rem', fontWeight: 700, lineHeight: 1.2 }}>
                  {currentUser?.full_name || currentUser?.email.split('@')[0] || 'Administrator'}
                </div>
                <div style={{ fontSize: '0.68rem', color: '#74C69D', lineHeight: 1 }}>MUNICIPAL_ADMIN</div>
              </div>
              <ChevronDown size={14} color="#A3D9BA" />
            </button>

            {isProfileMenuOpen && (
              <div
                style={{
                  position: 'absolute',
                  top: '120%',
                  right: 0,
                  backgroundColor: '#FFFFFF',
                  color: '#1F2937',
                  borderRadius: '10px',
                  boxShadow: '0 10px 25px rgba(0,0,0,0.25)',
                  minWidth: '220px',
                  padding: '0.5rem 0',
                  zIndex: 100,
                  border: '1px solid #E5E7EB',
                }}
              >
                <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid #F3F4F6' }}>
                  <div style={{ fontSize: '0.75rem', color: '#6B7280' }}>Signed in as</div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem', wordBreak: 'break-all' }}>
                    {currentUser ? currentUser.email : 'admin.central@nammaclean.local'}
                  </div>
                  <div style={{ fontSize: '0.72rem', color: '#1B4332', fontWeight: 700, marginTop: '2px' }}>
                    Municipal Admin
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    setIsProfileMenuOpen(false);
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
                    color: '#1B4332',
                    fontWeight: 600,
                    fontSize: '0.85rem',
                    cursor: 'pointer',
                    textAlign: 'left',
                    borderBottom: '1px solid #F3F4F6',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F0FDF4')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  <UserIcon size={15} />
                  <span>Manage Profile</span>
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
                    fontSize: '0.85rem',
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#FEF2F2')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  <LogOut size={15} />
                  <span>Sign Out</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Content Container */}
      <main style={{ maxWidth: '1440px', margin: '0 auto', padding: '1.75rem 2rem' }}>
        {/* KPI Summary Cards */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: '1rem',
            marginBottom: '1.75rem',
          }}
        >
          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '12px',
              padding: '1.25rem 1.4rem',
              border: '1px solid #D5E3D7',
              boxShadow: '0 2px 6px rgba(0,0,0,0.02)',
              display: 'flex',
              alignItems: 'center',
              gap: '1rem',
            }}
          >
            <div
              style={{
                backgroundColor: '#E8F5E9',
                color: '#2E7D32',
                width: '46px',
                height: '46px',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Users size={22} />
            </div>
            <div>
              <div style={{ fontSize: '0.8rem', color: '#5A7565', fontWeight: 600 }}>Total Workforce</div>
              <div style={{ fontSize: '1.65rem', fontWeight: 800, color: '#183B2A' }}>{totalCount}</div>
            </div>
          </div>

          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '12px',
              padding: '1.25rem 1.4rem',
              border: '1px solid #D5E3D7',
              boxShadow: '0 2px 6px rgba(0,0,0,0.02)',
              display: 'flex',
              alignItems: 'center',
              gap: '1rem',
            }}
          >
            <div
              style={{
                backgroundColor: '#E0F2FE',
                color: '#0284C7',
                width: '46px',
                height: '46px',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <UserCheck size={22} />
            </div>
            <div>
              <div style={{ fontSize: '0.8rem', color: '#5A7565', fontWeight: 600 }}>Pourakarmikas (Workers)</div>
              <div style={{ fontSize: '1.65rem', fontWeight: 800, color: '#183B2A' }}>{workerCount}</div>
            </div>
          </div>

          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '12px',
              padding: '1.25rem 1.4rem',
              border: '1px solid #D5E3D7',
              boxShadow: '0 2px 6px rgba(0,0,0,0.02)',
              display: 'flex',
              alignItems: 'center',
              gap: '1rem',
            }}
          >
            <div
              style={{
                backgroundColor: '#FEF3C7',
                color: '#D97706',
                width: '46px',
                height: '46px',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Truck size={22} />
            </div>
            <div>
              <div style={{ fontSize: '0.8rem', color: '#5A7565', fontWeight: 600 }}>Drivers & Fleet Crew</div>
              <div style={{ fontSize: '1.65rem', fontWeight: 800, color: '#183B2A' }}>{driverCount}</div>
            </div>
          </div>

          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '12px',
              padding: '1.25rem 1.4rem',
              border: '1px solid #D5E3D7',
              boxShadow: '0 2px 6px rgba(0,0,0,0.02)',
              display: 'flex',
              alignItems: 'center',
              gap: '1rem',
            }}
          >
            <div
              style={{
                backgroundColor: '#F3E8FF',
                color: '#7C3AED',
                width: '46px',
                height: '46px',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <ShieldCheck size={22} />
            </div>
            <div>
              <div style={{ fontSize: '0.8rem', color: '#5A7565', fontWeight: 600 }}>Ward Supervisors</div>
              <div style={{ fontSize: '1.65rem', fontWeight: 800, color: '#183B2A' }}>{supervisorCount}</div>
            </div>
          </div>
        </div>

        {/* Workforce Management Header & Action Bar */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            borderRadius: '14px',
            border: '1px solid #D5E3D7',
            padding: '1.25rem 1.5rem',
            marginBottom: '1.25rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '1rem',
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: '1.3rem', fontWeight: 750, color: '#183B2A' }}>
              Municipal Workforce Directory
            </h2>
            <p style={{ margin: '3px 0 0 0', fontSize: '0.84rem', color: '#5A7565' }}>
              Official administrative registry of active sanitation staff, official IDs, and vehicle assignments
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={() => openRegisterModal('SANITATION_WORKER')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.45rem',
                backgroundColor: '#2E7D32',
                color: '#FFFFFF',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '8px',
                fontWeight: 700,
                fontSize: '0.85rem',
                cursor: 'pointer',
                boxShadow: '0 2px 6px rgba(46,125,50,0.25)',
              }}
            >
              <UserPlus size={16} />
              <span>+ Register Worker</span>
            </button>

            <button
              type="button"
              onClick={() => openRegisterModal('DRIVER')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.45rem',
                backgroundColor: '#1E5E41',
                color: '#FFFFFF',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '8px',
                fontWeight: 700,
                fontSize: '0.85rem',
                cursor: 'pointer',
                boxShadow: '0 2px 6px rgba(30,94,65,0.25)',
              }}
            >
              <Truck size={16} />
              <span>+ Register Driver</span>
            </button>
          </div>
        </div>

        {/* Filter and Search Bar */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            borderRadius: '12px',
            border: '1px solid #D5E3D7',
            padding: '0.85rem 1.25rem',
            marginBottom: '1.25rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '1rem',
          }}
        >
          {/* Role Filter Tabs */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 700, color: '#5A7565', marginRight: '0.4rem' }}>
              Filter:
            </span>
            {(
              [
                { label: 'All Roles', value: 'ALL' },
                { label: 'Pourakarmikas', value: 'SANITATION_WORKER' },
                { label: 'Drivers', value: 'DRIVER' },
                { label: 'Supervisors', value: 'WARD_SUPERVISOR' },
              ] as const
            ).map((tab) => (
              <button
                key={tab.value}
                type="button"
                onClick={() => setRoleFilter(tab.value as any)}
                style={{
                  padding: '5px 12px',
                  borderRadius: '6px',
                  border: 'none',
                  backgroundColor: roleFilter === tab.value ? '#183B2A' : '#F4F7F4',
                  color: roleFilter === tab.value ? '#FFFFFF' : '#334155',
                  fontSize: '0.8rem',
                  fontWeight: 650,
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Search Input */}
          <div
            style={{
              position: 'relative',
              minWidth: '280px',
              maxWidth: '380px',
              width: '100%',
            }}
          >
            <Search
              size={16}
              color="#64748B"
              style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)' }}
            />
            <input
              type="text"
              placeholder="Search by name, email, or Official ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                padding: '7px 10px 7px 32px',
                borderRadius: '8px',
                border: '1px solid #CBD5E1',
                fontSize: '0.84rem',
                backgroundColor: '#F8FAFC',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                style={{
                  position: 'absolute',
                  right: '8px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  color: '#94A3B8',
                  cursor: 'pointer',
                  padding: '2px',
                }}
              >
                <X size={14} />
              </button>
            )}
          </div>
        </div>

        {/* Workforce Roster Table */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            borderRadius: '14px',
            border: '1px solid #D5E3D7',
            overflow: 'hidden',
            boxShadow: '0 2px 8px rgba(0,0,0,0.02)',
          }}
        >
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.86rem' }}>
              <thead>
                <tr style={{ backgroundColor: '#F8FAF8', borderBottom: '1px solid #E2E8F0', color: '#475569' }}>
                  <th style={{ padding: '12px 16px', fontWeight: 700 }}>Personnel Details</th>
                  <th style={{ padding: '12px 16px', fontWeight: 700 }}>Official ID</th>
                  <th style={{ padding: '12px 16px', fontWeight: 700 }}>Designation</th>
                  <th style={{ padding: '12px 16px', fontWeight: 700 }}>Assigned Ward</th>
                  <th style={{ padding: '12px 16px', fontWeight: 700 }}>Vehicle / Telemetry</th>
                  <th style={{ padding: '12px 16px', fontWeight: 700 }}>Status</th>
                  <th style={{ padding: '12px 16px', fontWeight: 700, textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredWorkforce.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', padding: '3.5rem 1rem', color: '#64748B' }}>
                      <Users size={36} color="#CBD5E1" style={{ margin: '0 auto 0.75rem auto' }} />
                      <div style={{ fontWeight: 650, color: '#334155', fontSize: '0.95rem' }}>
                        No personnel matched your filter criteria
                      </div>
                      <div style={{ fontSize: '0.8rem', marginTop: '4px' }}>
                        Try adjusting your search query or role filter.
                      </div>
                    </td>
                  </tr>
                ) : (
                  filteredWorkforce.map((person) => {
                    const isWorker = person.role === 'SANITATION_WORKER';
                    const isDriver = person.role === 'DRIVER';
                    const isSupervisor = person.role === 'WARD_SUPERVISOR';

                    return (
                      <tr
                        key={person.id}
                        style={{
                          borderBottom: '1px solid #F1F5F9',
                          transition: 'background-color 0.15s ease',
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F8FAF8')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#FFFFFF')}
                      >
                        {/* Name & Email */}
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ fontWeight: 700, color: '#1E293B' }}>
                            {person.full_name || 'Personnel Name Not Set'}
                          </div>
                          <div style={{ fontSize: '0.78rem', color: '#64748B', display: 'flex', alignItems: 'center', gap: '0.35rem', marginTop: '2px' }}>
                            <Mail size={12} />
                            <span>{person.email}</span>
                          </div>
                          {person.phone_number && (
                            <div style={{ fontSize: '0.78rem', color: '#64748B', display: 'flex', alignItems: 'center', gap: '0.35rem', marginTop: '1px' }}>
                              <Phone size={12} />
                              <span>{person.phone_number}</span>
                            </div>
                          )}
                        </td>

                        {/* Official ID */}
                        <td style={{ padding: '12px 16px' }}>
                          {person.official_id ? (
                            <span
                              style={{
                                display: 'inline-block',
                                backgroundColor: '#E0F2FE',
                                color: '#0369A1',
                                border: '1px solid #BAE6FD',
                                padding: '3px 8px',
                                borderRadius: '6px',
                                fontWeight: 750,
                                fontSize: '0.78rem',
                                letterSpacing: '0.03em',
                                fontFamily: 'monospace',
                              }}
                            >
                              {person.official_id}
                            </span>
                          ) : (
                            <span
                              style={{
                                display: 'inline-block',
                                backgroundColor: '#FEF3C7',
                                color: '#92400E',
                                border: '1px solid #FDE68A',
                                padding: '3px 8px',
                                borderRadius: '6px',
                                fontWeight: 650,
                                fontSize: '0.75rem',
                              }}
                            >
                              Pending Official ID
                            </span>
                          )}
                        </td>

                        {/* Designation */}
                        <td style={{ padding: '12px 16px' }}>
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '0.3rem',
                              fontWeight: 700,
                              fontSize: '0.78rem',
                              padding: '3px 9px',
                              borderRadius: '999px',
                              backgroundColor: isWorker
                                ? '#E8F5E9'
                                : isDriver
                                ? '#FEF3C7'
                                : '#F3E8FF',
                              color: isWorker
                                ? '#1B5E20'
                                : isDriver
                                ? '#92400E'
                                : '#6B21A8',
                            }}
                          >
                            {isWorker && <UserCheck size={12} />}
                            {isDriver && <Truck size={12} />}
                            {isSupervisor && <ShieldCheck size={12} />}
                            <span>
                              {isWorker ? 'Pourakarmika' : isDriver ? 'Fleet Driver' : 'Ward Supervisor'}
                            </span>
                          </span>
                        </td>

                        {/* Assigned Ward */}
                        <td style={{ padding: '12px 16px', color: '#334155' }}>
                          {person.ward_name ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                              <MapPin size={13} color="#2E7D32" />
                              <span style={{ fontWeight: 600 }}>{person.ward_name}</span>
                            </div>
                          ) : (
                            <span style={{ color: '#94A3B8', fontStyle: 'italic', fontSize: '0.8rem' }}>
                              Unassigned
                            </span>
                          )}
                        </td>

                        {/* Vehicle / Telemetry */}
                        <td style={{ padding: '12px 16px' }}>
                          {isDriver && person.assigned_vehicle ? (
                            <div>
                              <div style={{ fontWeight: 700, color: '#1E293B', fontSize: '0.82rem' }}>
                                {person.assigned_vehicle.registration_number}
                              </div>
                              <div style={{ fontSize: '0.74rem', color: '#64748B' }}>
                                {person.assigned_vehicle.vehicle_type.replace('_', ' ')} •{' '}
                                <span style={{ fontWeight: 600, color: person.assigned_vehicle.status === 'ON_DUTY' ? '#16A34A' : '#D97706' }}>
                                  {person.assigned_vehicle.status}
                                </span>
                              </div>
                            </div>
                          ) : isDriver ? (
                            <span style={{ color: '#D97706', fontSize: '0.78rem', fontWeight: 600 }}>
                              No Vehicle Assigned
                            </span>
                          ) : (
                            <span style={{ color: '#94A3B8', fontSize: '0.8rem' }}>—</span>
                          )}
                        </td>

                        {/* Status */}
                        <td style={{ padding: '12px 16px' }}>
                          <span
                            style={{
                              display: 'inline-block',
                              padding: '2px 8px',
                              borderRadius: '999px',
                              fontSize: '0.74rem',
                              fontWeight: 700,
                              backgroundColor: person.status === 'ACTIVE' ? '#D1FAE5' : '#FEE2E2',
                              color: person.status === 'ACTIVE' ? '#065F46' : '#991B1B',
                            }}
                          >
                            {person.status}
                          </span>
                        </td>

                        {/* Actions */}
                        <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                          <button
                            type="button"
                            onClick={() => setSelectedStaff(person)}
                            style={{
                              backgroundColor: '#F1F5F9',
                              border: '1px solid #CBD5E1',
                              color: '#334155',
                              padding: '4px 10px',
                              borderRadius: '6px',
                              fontSize: '0.78rem',
                              fontWeight: 650,
                              cursor: 'pointer',
                            }}
                          >
                            View Details
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>

      {/* Register Personnel Modal */}
      {isRegisterModalOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            backdropFilter: 'blur(3px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 50,
            padding: '1rem',
          }}
        >
          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '14px',
              maxWidth: '520px',
              width: '100%',
              overflow: 'hidden',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04)',
              border: '1px solid #D5E3D7',
            }}
          >
            {/* Modal Header */}
            <div
              style={{
                backgroundColor: '#0E3A28',
                color: '#FFFFFF',
                padding: '1.25rem 1.5rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 750 }}>
                  {modalRole === 'SANITATION_WORKER' ? 'Register Pourakarmika' : 'Register Fleet Driver'}
                </h3>
                <p style={{ margin: '3px 0 0 0', fontSize: '0.78rem', color: '#A3D9BA' }}>
                  BBMP Civic Operational Workforce Registration
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsRegisterModalOpen(false)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#A3D9BA',
                  cursor: 'pointer',
                  padding: '4px',
                }}
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Form */}
            <form onSubmit={handleFormSubmit} style={{ padding: '1.5rem' }}>
              {submitError && (
                <div
                  style={{
                    backgroundColor: '#FEF2F2',
                    border: '1px solid #FCA5A5',
                    color: '#991B1B',
                    padding: '0.65rem 0.85rem',
                    borderRadius: '8px',
                    fontSize: '0.82rem',
                    marginBottom: '1rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                  }}
                >
                  <AlertCircle size={15} />
                  <span>{submitError}</span>
                </div>
              )}

              {submitSuccess && (
                <div
                  style={{
                    backgroundColor: '#ECFDF5',
                    border: '1px solid #6EE7B7',
                    color: '#065F46',
                    padding: '0.65rem 0.85rem',
                    borderRadius: '8px',
                    fontSize: '0.82rem',
                    marginBottom: '1rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                  }}
                >
                  <CheckCircle2 size={15} />
                  <span>{submitSuccess}</span>
                </div>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                    Full Legal Name *
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Manjunatha Swamy"
                    value={formData.full_name}
                    onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '7px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.85rem',
                      boxSizing: 'border-box',
                    }}
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                      Official Staff ID (Optional)
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. BBMP-PK-0401"
                      value={formData.official_id}
                      onChange={(e) => setFormData({ ...formData, official_id: e.target.value })}
                      style={{
                        width: '100%',
                        padding: '8px 10px',
                        borderRadius: '7px',
                        border: '1px solid #CBD5E1',
                        fontSize: '0.85rem',
                        boxSizing: 'border-box',
                      }}
                    />
                    <span style={{ fontSize: '0.7rem', color: '#64748B' }}>Leave blank for Pending ID</span>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                      Phone Number
                    </label>
                    <input
                      type="tel"
                      placeholder="e.g. +91 98450 12345"
                      value={formData.phone_number}
                      onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })}
                      style={{
                        width: '100%',
                        padding: '8px 10px',
                        borderRadius: '7px',
                        border: '1px solid #CBD5E1',
                        fontSize: '0.85rem',
                        boxSizing: 'border-box',
                      }}
                    />
                  </div>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                    Official Email (Login Identifier) *
                  </label>
                  <input
                    type="email"
                    required
                    placeholder={
                      modalRole === 'SANITATION_WORKER'
                        ? 'worker.name@nammaclean.local'
                        : 'driver.name@nammaclean.local'
                    }
                    value={formData.email}
                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '7px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.85rem',
                      boxSizing: 'border-box',
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                    Temporary Initial Password * (min 12 characters)
                  </label>
                  <div style={{ position: 'relative' }}>
                    <input
                      type={showPassword ? 'text' : 'password'}
                      required
                      placeholder="Enter minimum 12-character password"
                      value={formData.password}
                      onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                      style={{
                        width: '100%',
                        padding: '8px 34px 8px 10px',
                        borderRadius: '7px',
                        border: '1px solid #CBD5E1',
                        fontSize: '0.85rem',
                        boxSizing: 'border-box',
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      style={{
                        position: 'absolute',
                        right: '8px',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        background: 'none',
                        border: 'none',
                        color: '#64748B',
                        cursor: 'pointer',
                        padding: '2px',
                      }}
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                    Assigned Administrative Ward
                  </label>
                  <select
                    value={formData.ward_id}
                    onChange={(e) => setFormData({ ...formData, ward_id: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: '7px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.85rem',
                      boxSizing: 'border-box',
                      backgroundColor: '#FFFFFF',
                    }}
                  >
                    <option value="">No Initial Ward Assignment</option>
                    {wards.map((ward) => (
                      <option key={ward.id} value={ward.id}>
                        {ward.name} (Ward {ward.ward_number})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button
                  type="button"
                  onClick={() => setIsRegisterModalOpen(false)}
                  style={{
                    padding: '8px 16px',
                    borderRadius: '7px',
                    border: '1px solid #CBD5E1',
                    backgroundColor: '#FFFFFF',
                    color: '#475569',
                    fontSize: '0.85rem',
                    fontWeight: 650,
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  style={{
                    padding: '8px 20px',
                    borderRadius: '7px',
                    border: 'none',
                    backgroundColor: '#2E7D32',
                    color: '#FFFFFF',
                    fontSize: '0.85rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                    boxShadow: '0 2px 6px rgba(46,125,50,0.25)',
                  }}
                >
                  {isSubmitting ? 'Registering...' : 'Complete Registration'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Staff Details Drawer */}
      {selectedStaff && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.4)',
            backdropFilter: 'blur(2px)',
            display: 'flex',
            justifyContent: 'flex-end',
            zIndex: 50,
          }}
        >
          <div
            style={{
              backgroundColor: '#FFFFFF',
              width: '100%',
              maxWidth: '420px',
              height: '100%',
              boxShadow: '-4px 0 20px rgba(0,0,0,0.1)',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <div
              style={{
                backgroundColor: '#0E3A28',
                color: '#FFFFFF',
                padding: '1.25rem 1.5rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 750 }}>Personnel Record</h3>
                <p style={{ margin: '2px 0 0 0', fontSize: '0.76rem', color: '#A3D9BA' }}>
                  Authoritative Municipal ID & Audit Profile
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedStaff(null)}
                style={{ background: 'none', border: 'none', color: '#FFFFFF', cursor: 'pointer', padding: '4px' }}
              >
                <X size={18} />
              </button>
            </div>

            <div style={{ padding: '1.5rem', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div>
                <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#1E293B' }}>
                  {selectedStaff.full_name || 'Personnel Name Not Set'}
                </div>
                <div style={{ fontSize: '0.85rem', color: '#64748B', marginTop: '2px' }}>{selectedStaff.email}</div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                <div style={{ backgroundColor: '#F8FAFC', padding: '10px 12px', borderRadius: '8px', border: '1px solid #E2E8F0' }}>
                  <div style={{ fontSize: '0.72rem', color: '#64748B', fontWeight: 650 }}>Official ID</div>
                  <div style={{ fontSize: '0.88rem', fontWeight: 800, color: '#0369A1', marginTop: '3px' }}>
                    {selectedStaff.official_id || 'Pending Official ID'}
                  </div>
                </div>

                <div style={{ backgroundColor: '#F8FAFC', padding: '10px 12px', borderRadius: '8px', border: '1px solid #E2E8F0' }}>
                  <div style={{ fontSize: '0.72rem', color: '#64748B', fontWeight: 650 }}>Role Designation</div>
                  <div style={{ fontSize: '0.85rem', fontWeight: 750, color: '#1E293B', marginTop: '3px' }}>
                    {selectedStaff.role}
                  </div>
                </div>
              </div>

              <div style={{ backgroundColor: '#F8FAFC', padding: '12px', borderRadius: '8px', border: '1px solid #E2E8F0' }}>
                <div style={{ fontSize: '0.72rem', color: '#64748B', fontWeight: 650 }}>Assigned Ward</div>
                <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#1E293B', marginTop: '3px' }}>
                  {selectedStaff.ward_name || 'No Ward Assigned'}
                </div>
              </div>

              {selectedStaff.assigned_vehicle && (
                <div style={{ backgroundColor: '#FFFBEB', padding: '12px', borderRadius: '8px', border: '1px solid #FDE68A' }}>
                  <div style={{ fontSize: '0.72rem', color: '#92400E', fontWeight: 650 }}>Fleet Vehicle Assignment</div>
                  <div style={{ fontSize: '0.92rem', fontWeight: 800, color: '#1E293B', marginTop: '3px' }}>
                    {selectedStaff.assigned_vehicle.registration_number}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: '#78350F' }}>
                    {selectedStaff.assigned_vehicle.vehicle_type.replace('_', ' ')} • Status: {selectedStaff.assigned_vehicle.status}
                  </div>
                </div>
              )}

              <div style={{ backgroundColor: '#F8FAFC', padding: '12px', borderRadius: '8px', border: '1px solid #E2E8F0' }}>
                <div style={{ fontSize: '0.72rem', color: '#64748B', fontWeight: 650 }}>Account Created</div>
                <div style={{ fontSize: '0.85rem', color: '#334155', marginTop: '3px' }}>
                  {new Date(selectedStaff.created_at).toLocaleString('en-IN')}
                </div>
              </div>
            </div>

            <div style={{ padding: '1rem 1.5rem', borderTop: '1px solid #E2E8F0', backgroundColor: '#F8FAFC' }}>
              <button
                type="button"
                onClick={() => setSelectedStaff(null)}
                style={{
                  width: '100%',
                  padding: '9px',
                  borderRadius: '7px',
                  border: '1px solid #CBD5E1',
                  backgroundColor: '#FFFFFF',
                  color: '#475569',
                  fontWeight: 700,
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                }}
              >
                Close Profile
              </button>
            </div>
          </div>
        </div>
      )}
      {/* User Profile Modal */}
      <UserProfileModal
        isOpen={isProfileModalOpen}
        onClose={() => setIsProfileModalOpen(false)}
        currentUser={currentUser}
        onProfileUpdated={(updated) => setCurrentUser(updated)}
      />
    </div>
  );
};
