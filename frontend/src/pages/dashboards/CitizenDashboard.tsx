import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  FileImage,
  LogIn,
  MapPin,
  RefreshCw,
} from 'lucide-react';
import { CitizenHeader } from '../../components/layout/CitizenHeader';
import { CitizenSidebar } from '../../components/layout/CitizenSidebar';
import { CitizenBanner } from '../../components/dashboard/CitizenBanner';
import { SummaryCards } from '../../components/dashboard/SummaryCards';
import { PublicVehicleMap } from '../../components/map/PublicVehicleMap';
import { VehicleDetailsPanel } from '../../components/dashboard/VehicleDetailsPanel';
import { ReportDumpingModal } from '../../components/dashboard/ReportDumpingModal';
import { UserProfileModal } from '../../components/profile/UserProfileModal';
import { apiClient } from '../../api/client';
import { getMyReports } from '../../api/reports';
import { fetchPublicMapSummary } from '../../api/publicMap';
import { PublicVehicle, PublicMapSummary, DumpingReport, User } from '../../types';
import { DEFAULT_PILOT_LOCALITY, LocalityOption } from '../../utils/localities';
import '../../styles/citizen-dashboard.css';

const scrollToMap = () => {
  document.getElementById('citizen-map')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
};

const getStatusBadgeStyle = (status: string) => {
  switch (status) {
    case 'SUBMITTED':
      return { bg: '#FEF3C7', color: '#92400E', border: '#FDE68A', label: 'Submitted' };
    case 'UNDER_REVIEW':
      return { bg: '#DBEAFE', color: '#1E40AF', border: '#BFDBFE', label: 'Under Review' };
    case 'ACTION_SCHEDULED':
      return { bg: '#F3E8FF', color: '#6B21A8', border: '#E9D5FF', label: 'Action Scheduled' };
    case 'RESOLVED':
      return { bg: '#D1FAE5', color: '#065F46', border: '#A7F3D0', label: 'Resolved' };
    case 'REJECTED':
      return { bg: '#FEE2E2', color: '#991B1B', border: '#FECACA', label: 'Rejected' };
    default:
      return { bg: '#F3F4F6', color: '#374151', border: '#E5E7EB', label: status };
  }
};

export const CitizenDashboard: React.FC = () => {
  const [selectedVehicle, setSelectedVehicle] = useState<PublicVehicle | null>(null);
  const [summary, setSummary] = useState<PublicMapSummary | null>(null);
  const [selectedLocality, setSelectedLocality] = useState<LocalityOption>(DEFAULT_PILOT_LOCALITY);
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);
  const [isProfileModalOpen, setIsProfileModalOpen] = useState(false);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(false);
  const [userReports, setUserReports] = useState<DumpingReport[] | null>(null);
  const [isLoadingReports, setIsLoadingReports] = useState(false);
  const [activeTab, setActiveTab] = useState<'dashboard' | 'my-reports'>('dashboard');

  const loadUser = useCallback(() => {
    const token = localStorage.getItem('nammaclean.access_token');
    if (!token) {
      setCurrentUser(null);
      setUserReports(null);
      setIsLoadingUser(false);
      return;
    }

    setIsLoadingUser(true);
    apiClient
      .get<User>('/users/me')
      .then((user) => {
        setCurrentUser(user);
      })
      .catch(() => {
        setCurrentUser(null);
        setUserReports(null);
      })
      .finally(() => {
        setIsLoadingUser(false);
      });
  }, []);

  const loadUserReports = useCallback(() => {
    const token = localStorage.getItem('nammaclean.access_token');
    if (!token) {
      setUserReports(null);
      return;
    }

    setIsLoadingReports(true);
    getMyReports()
      .then((reports) => {
        setUserReports(reports);
      })
      .catch(() => {
        setUserReports(null);
      })
      .finally(() => {
        setIsLoadingReports(false);
      });
  }, []);

  useEffect(() => {
    loadUser();
    loadUserReports();

    fetchPublicMapSummary()
      .then((data) => setSummary(data))
      .catch(() => {});

    const handleAuthChange = () => {
      loadUser();
      loadUserReports();
    };

    window.addEventListener('nammaclean:unauthorized', handleAuthChange);
    window.addEventListener('nammaclean:logout', handleAuthChange);

    return () => {
      window.removeEventListener('nammaclean:unauthorized', handleAuthChange);
      window.removeEventListener('nammaclean:logout', handleAuthChange);
    };
  }, [loadUser, loadUserReports]);

  const resolvedCount = userReports
    ? userReports.filter((r) => r.status === 'RESOLVED').length
    : null;

  return (
    <div style={{ display: 'flex', minHeight: '100vh', backgroundColor: '#F5F9F5' }}>
      {/* Sidebar matching montage */}
      <CitizenSidebar
        role="citizen"
        activeTab={activeTab}
        onTabChange={(tab) => {
          if (tab === 'track') {
            setActiveTab('dashboard');
            scrollToMap();
          } else if (tab === 'my-reports') {
            setActiveTab('my-reports');
          } else if (tab === 'profile') {
            setIsProfileModalOpen(true);
          } else {
            setActiveTab('dashboard');
          }
        }}
        onReportClick={() => setIsReportModalOpen(true)}
        notificationCount={userReports ? userReports.filter((r) => r.status === 'SUBMITTED').length : undefined}
      />

      {/* Main Content Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflowX: 'hidden' }}>
        <section className="nc-dashboard-band" id="home">
          <CitizenHeader
            onTrackClick={scrollToMap}
            selectedWardName={selectedLocality.name}
            onLocalityChange={setSelectedLocality}
          />
          <div className="nc-dashboard-band-inner">
            <CitizenBanner user={currentUser} isLoading={isLoadingUser} />
            <SummaryCards
              summary={summary}
              myReportsCount={userReports !== null ? userReports.length : (currentUser ? null : 0)}
              resolvedCount={resolvedCount}
              onMyReportsClick={() => setActiveTab('my-reports')}
              onVehiclesClick={scrollToMap}
              onRoutesClick={scrollToMap}
            />
          </div>
        </section>

        <main className="nc-dashboard-main" style={{ padding: '0.85rem 0 2rem' }}>
          {activeTab === 'dashboard' ? (
            /* Vehicle-Tracking Map occupies nearly the entire available width */
            <div style={{ width: '100%', minWidth: 0 }}>
              <PublicVehicleMap
                selectedVehicle={selectedVehicle}
                onVehicleSelect={setSelectedVehicle}
                onSummaryLoaded={setSummary}
                selectedLocality={selectedLocality}
                onLocalityChange={setSelectedLocality}
                complaints={userReports || []}
                details={
                  selectedVehicle ? (
                    <VehicleDetailsPanel
                      vehicle={selectedVehicle}
                      freshnessMinutes={summary?.freshness_threshold_minutes ?? null}
                      onClose={() => setSelectedVehicle(null)}
                    />
                  ) : null
                }
              />
            </div>
          ) : (
            /* Dedicated Full-Width My Reports Management View */
            <div style={{ width: '100%', minWidth: 0, display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '1rem',
                  flexWrap: 'wrap',
                  backgroundColor: '#FFFFFF',
                  padding: '1.25rem 1.5rem',
                  borderRadius: '14px',
                  border: '1px solid #D5E3D7',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
                  <button
                    type="button"
                    onClick={() => setActiveTab('dashboard')}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.35rem',
                      padding: '6px 12px',
                      borderRadius: '8px',
                      border: '1px solid #D5E3D7',
                      backgroundColor: '#F5F9F5',
                      color: '#183B2A',
                      fontSize: '0.82rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                    title="Return to vehicle tracking map"
                  >
                    <span>← Back to Live Map</span>
                  </button>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 750, color: '#183B2A' }}>
                      My Incident Reports
                    </h2>
                    {userReports && (
                      <span
                        style={{
                          backgroundColor: '#E8F5E9',
                          color: '#2E7D32',
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          padding: '2px 8px',
                          borderRadius: '999px',
                          border: '1px solid #C8E6C9',
                        }}
                      >
                        {userReports.length}
                      </span>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  {currentUser && (
                    <button
                      type="button"
                      onClick={loadUserReports}
                      disabled={isLoadingReports}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        padding: '6px 12px',
                        borderRadius: '8px',
                        border: '1px solid #D5E3D7',
                        backgroundColor: '#FFFFFF',
                        color: '#183B2A',
                        fontSize: '0.82rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      <RefreshCw size={14} className={isLoadingReports ? 'nc-refreshing' : ''} />
                      <span>Refresh</span>
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => setIsReportModalOpen(true)}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.4rem',
                      padding: '7px 14px',
                      borderRadius: '8px',
                      border: 'none',
                      backgroundColor: '#2E7D32',
                      color: '#FFFFFF',
                      fontSize: '0.85rem',
                      fontWeight: 700,
                      cursor: 'pointer',
                      boxShadow: '0 2px 6px rgba(46, 125, 50, 0.25)',
                    }}
                  >
                    <span>+ Report Illegal Dumping</span>
                  </button>
                </div>
              </div>

              {!currentUser ? (
                <div
                  style={{
                    textAlign: 'center',
                    padding: '3rem 2rem',
                    backgroundColor: '#FFFFFF',
                    borderRadius: '14px',
                    border: '1px solid #D5E3D7',
                  }}
                >
                  <LogIn size={36} color="#5A7565" style={{ margin: '0 auto 0.75rem' }} />
                  <h3 style={{ margin: '0 0 0.5rem', fontSize: '1.1rem', fontWeight: 700, color: '#183B2A' }}>
                    Sign In to Track Your Complaints
                  </h3>
                  <p style={{ margin: '0 0 1.25rem', fontSize: '0.88rem', color: '#5A7565', maxWidth: '420px', marginLeft: 'auto', marginRight: 'auto' }}>
                    Sign in to your citizen account to track real-time resolution progress and municipal actions on your reports.
                  </p>
                  <Link
                    to="/login"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      backgroundColor: '#2E7D32',
                      color: '#FFFFFF',
                      fontSize: '0.88rem',
                      fontWeight: 700,
                      padding: '0.65rem 1.25rem',
                      borderRadius: '8px',
                      textDecoration: 'none',
                    }}
                  >
                    <span>Sign In to Account</span>
                    <ArrowRight size={15} />
                  </Link>
                </div>
              ) : isLoadingReports && !userReports ? (
                <div style={{ textAlign: 'center', padding: '3rem', backgroundColor: '#FFFFFF', borderRadius: '14px', border: '1px solid #D5E3D7', color: '#5A7565' }}>
                  Loading your reported incidents...
                </div>
              ) : userReports && userReports.length === 0 ? (
                <div
                  style={{
                    textAlign: 'center',
                    padding: '3rem 2rem',
                    backgroundColor: '#FFFFFF',
                    borderRadius: '14px',
                    border: '1px solid #D5E3D7',
                  }}
                >
                  <CheckCircle2 size={36} color="#2E7D32" style={{ margin: '0 auto 0.75rem' }} />
                  <h3 style={{ margin: '0 0 0.4rem', fontSize: '1.1rem', fontWeight: 700, color: '#183B2A' }}>
                    No Incidents Reported Yet
                  </h3>
                  <p style={{ margin: '0 0 1.25rem', fontSize: '0.88rem', color: '#5A7565' }}>
                    Help keep Bengaluru clean! Notice illegal garbage dumping or uncleared black spots?
                  </p>
                  <button
                    type="button"
                    onClick={() => setIsReportModalOpen(true)}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      backgroundColor: '#2E7D32',
                      color: '#FFFFFF',
                      fontSize: '0.85rem',
                      fontWeight: 700,
                      padding: '0.65rem 1.25rem',
                      borderRadius: '8px',
                      border: 'none',
                      cursor: 'pointer',
                    }}
                  >
                    <span>Report Dumping Incident</span>
                  </button>
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '1rem' }}>
                  {userReports?.map((report) => {
                    const badge = getStatusBadgeStyle(report.status);
                    const reportDate = new Date(report.created_at).toLocaleDateString('en-IN', {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    });

                    return (
                      <div
                        key={report.id}
                        style={{
                          padding: '1.15rem',
                          borderRadius: '12px',
                          backgroundColor: '#FFFFFF',
                          border: '1px solid #D5E3D7',
                          boxShadow: '0 2px 6px rgba(0,0,0,0.03)',
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'space-between',
                          gap: '0.75rem',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
                          <span
                            style={{
                              fontSize: '0.72rem',
                              fontWeight: 700,
                              textTransform: 'uppercase',
                              padding: '2px 8px',
                              borderRadius: '4px',
                              backgroundColor: badge.bg,
                              color: badge.color,
                              border: `1px solid ${badge.border}`,
                            }}
                          >
                            {badge.label}
                          </span>
                          <span style={{ fontSize: '0.75rem', color: '#5A7565', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                            <Clock size={12} />
                            {reportDate}
                          </span>
                        </div>

                        <p
                          style={{
                            margin: 0,
                            fontSize: '0.88rem',
                            color: '#183B2A',
                            lineHeight: 1.45,
                            display: '-webkit-box',
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                          }}
                        >
                          {report.description}
                        </p>

                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            fontSize: '0.75rem',
                            color: '#5A7565',
                            borderTop: '1px solid #E8F5E9',
                            paddingTop: '0.6rem',
                          }}
                        >
                          <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                            <MapPin size={13} color="#2E7D32" />
                            {report.latitude.toFixed(4)}, {report.longitude.toFixed(4)}
                          </span>

                          {report.evidence && report.evidence.length > 0 && (
                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', color: '#0284C7', fontWeight: 600 }}>
                              <FileImage size={13} />
                              {report.evidence.length} photo{report.evidence.length > 1 ? 's' : ''}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </main>

        <ReportDumpingModal
          isOpen={isReportModalOpen}
          onClose={() => setIsReportModalOpen(false)}
          onReportCreated={() => {
            loadUserReports();
          }}
        />

        <UserProfileModal
          isOpen={isProfileModalOpen}
          onClose={() => setIsProfileModalOpen(false)}
          currentUser={currentUser}
          onProfileUpdated={(updated) => {
            setCurrentUser(updated);
          }}
        />

        <footer className="nc-dashboard-footer">
          <span>Public collection information for Bengaluru · BBMP Solid Waste Management</span>
        </footer>
      </div>
    </div>
  );
};

export default CitizenDashboard;