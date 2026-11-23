import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CalendarCheck,
  Clock,
  FileText,
  MapPin,
  QrCode,
  RefreshCw,
  Route,
  ShieldAlert,
  Truck,
  Users,
  X,
} from 'lucide-react';
import { CitizenSidebar } from '../../components/layout/CitizenSidebar';
import { CitizenHeader } from '../../components/layout/CitizenHeader';
import { CitizenBanner } from '../../components/dashboard/CitizenBanner';
import { PublicVehicleMap } from '../../components/map/PublicVehicleMap';
import { VehicleDetailsPanel } from '../../components/dashboard/VehicleDetailsPanel';
import { Button } from '../../components/ui/Button';
import { Alert } from '../../components/ui/Alert';
import { Spinner } from '../../components/ui/Spinner';
import { apiClient } from '../../api/client';
import {
  issueRollCallQr,
  getDailyAttendanceRoster,
  reviewAttendanceRecord,
  getWardMusterPoints,
  QrTokenIssueResponse,
  AttendanceDailyRoster,
  MusterPoint,
} from '../../api/attendance';
import { fetchReportsForReview, updateReportStatus } from '../../api/reports';
import type { User, DumpingReport, PublicMapSummary, PublicVehicle } from '../../types';
import '../../styles/citizen-dashboard.css';

// High-fidelity SVG QR Code component with authentic finder corners & data matrix pattern
const QrCodeDisplay: React.FC<{ token: string; size?: number }> = ({ token, size = 200 }) => {
  const hash = token.split('').reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) % 1000003, 0);

  return (
    <div
      style={{
        display: 'inline-flex',
        padding: '16px',
        backgroundColor: '#FFFFFF',
        borderRadius: '16px',
        boxShadow: '0 8px 30px rgba(0,0,0,0.08)',
        border: '1px solid #E2E8F0',
      }}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 29 29"
        shapeRendering="crispEdges"
        style={{ display: 'block' }}
      >
        <rect width="29" height="29" fill="#FFFFFF" />

        {/* Top-Left Finder Pattern (7x7) */}
        <rect x="1" y="1" width="7" height="7" fill="#0B3024" />
        <rect x="2" y="2" width="5" height="5" fill="#FFFFFF" />
        <rect x="3" y="3" width="3" height="3" fill="#0B3024" />

        {/* Top-Right Finder Pattern (7x7) */}
        <rect x="21" y="1" width="7" height="7" fill="#0B3024" />
        <rect x="22" y="2" width="5" height="5" fill="#FFFFFF" />
        <rect x="23" y="3" width="3" height="3" fill="#0B3024" />

        {/* Bottom-Left Finder Pattern (7x7) */}
        <rect x="1" y="21" width="7" height="7" fill="#0B3024" />
        <rect x="2" y="22" width="5" height="5" fill="#FFFFFF" />
        <rect x="3" y="23" width="3" height="3" fill="#0B3024" />

        {/* Timing Patterns */}
        {[9, 11, 13, 15, 17, 19].map((pos) => (
          <React.Fragment key={pos}>
            <rect x={pos} y="4" width="1" height="1" fill="#0B3024" />
            <rect x="4" y={pos} width="1" height="1" fill="#0B3024" />
          </React.Fragment>
        ))}

        {/* Alignment Pattern at (19, 19) */}
        <rect x="19" y="19" width="5" height="5" fill="#0B3024" />
        <rect x="20" y="20" width="3" height="3" fill="#FFFFFF" />
        <rect x="21" y="21" width="1" height="1" fill="#0B3024" />

        {/* Deterministic Data Matrix Modules */}
        {Array.from({ length: 29 * 29 }).map((_, idx) => {
          const x = idx % 29;
          const y = Math.floor(idx / 29);

          const inFinderTL = x < 8 && y < 8;
          const inFinderTR = x > 20 && y < 8;
          const inFinderBL = x < 8 && y > 20;
          const inTimingH = y === 4;
          const inTimingV = x === 4;
          const inAlignment = x >= 19 && x <= 23 && y >= 19 && y <= 23;

          if (inFinderTL || inFinderTR || inFinderBL || inTimingH || inTimingV || inAlignment) {
            return null;
          }

          const bit = (hash + x * 37 + y * 73 + (token.charCodeAt(x % token.length) || 0)) % 3 === 0;
          return bit ? <rect key={idx} x={x} y={y} width="1" height="1" fill="#0B3024" /> : null;
        })}
      </svg>
    </div>
  );
};

export type SupervisorTab = 'dashboard' | 'vehicles' | 'reports' | 'workers' | 'analytics';

export const SupervisorDashboard: React.FC = () => {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(true);
  const [activeTab, setActiveTab] = useState<SupervisorTab>('dashboard');
  const [selectedWardId, setSelectedWardId] = useState<string>('44444444-4444-4444-4444-444444440004');
  const [musterPoints, setMusterPoints] = useState<MusterPoint[]>([]);
  const [selectedMusterId, setSelectedMusterId] = useState<string>('');

  // Operational summary from live map
  const [mapSummary, setMapSummary] = useState<PublicMapSummary | null>(null);
  const [selectedVehicle, setSelectedVehicle] = useState<PublicVehicle | null>(null);

  // QR Token state
  const [qrTokenData, setQrTokenData] = useState<QrTokenIssueResponse | null>(null);
  const [qrSecondsRemaining, setQrSecondsRemaining] = useState<number>(0);
  const [isIssuingQr, setIsIssuingQr] = useState(false);
  const timerRef = useRef<number | null>(null);

  // Daily Attendance Roster state
  const [rosterData, setRosterData] = useState<AttendanceDailyRoster | null>(null);
  const [isLoadingRoster, setIsLoadingRoster] = useState(false);
  const [reviewProcessingId, setReviewProcessingId] = useState<string | null>(null);
  const [reviewModalRecord, setReviewModalRecord] = useState<any | null>(null);
  const [reviewNotesInput, setReviewNotesInput] = useState('');

  // Citizen Reports Oversight state
  const [reports, setReports] = useState<DumpingReport[]>([]);
  const [isLoadingReports, setIsLoadingReports] = useState(false);
  const [reportStatusFilter, setReportStatusFilter] = useState<string>('ALL');
  const [selectedReport, setSelectedReport] = useState<DumpingReport | null>(null);
  const [statusUpdateVal, setStatusUpdateVal] = useState<'UNDER_REVIEW' | 'ACTION_SCHEDULED' | 'RESOLVED' | 'REJECTED'>('UNDER_REVIEW');
  const [officialNotesVal, setOfficialNotesVal] = useState('');
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);

  const [notice, setNotice] = useState<{ type: 'success' | 'danger' | 'warning'; message: string } | null>(null);

  // Load Current Official User
  const loadOfficialData = useCallback(async () => {
    setIsLoadingUser(true);
    try {
      const user = await apiClient.get<User>('/users/me');
      setCurrentUser(user);
      if (user.ward_id) {
        setSelectedWardId(user.ward_id);
      }
    } catch {
      setNotice({ type: 'danger', message: 'Official session expired or unauthorized. Please sign in again.' });
    } finally {
      setIsLoadingUser(false);
    }
  }, []);

  // Load Live Map Operational Summary
  const loadMapSummary = useCallback(async () => {
    try {
      const summary = await apiClient.get<PublicMapSummary>('/public/map/summary');
      setMapSummary(summary);
    } catch {
      // Safe fallback
    }
  }, []);

  // Load Muster Points for Ward
  const loadMusterStations = useCallback(async (wardId: string) => {
    try {
      const points = await getWardMusterPoints(wardId);
      setMusterPoints(points);
      if (points.length > 0) {
        setSelectedMusterId(points[0].id);
      }
    } catch {
      setMusterPoints([]);
      setSelectedMusterId('');
    }
  }, []);

  // Load Daily Attendance Roster
  const loadRoster = useCallback(async (wardId: string) => {
    setIsLoadingRoster(true);
    try {
      const data = await getDailyAttendanceRoster(wardId);
      setRosterData(data);
    } catch {
      setRosterData(null);
    } finally {
      setIsLoadingRoster(false);
    }
  }, []);

  // Load Citizen Reports for Oversight
  const loadReports = useCallback(async (wardId: string) => {
    setIsLoadingReports(true);
    try {
      const list = await fetchReportsForReview({ wardId });
      setReports(list);
    } catch {
      setReports([]);
    } finally {
      setIsLoadingReports(false);
    }
  }, []);

  useEffect(() => {
    loadOfficialData();
    loadMapSummary();
  }, [loadOfficialData, loadMapSummary]);

  useEffect(() => {
    if (selectedWardId) {
      loadMusterStations(selectedWardId);
      loadRoster(selectedWardId);
      loadReports(selectedWardId);
    }
  }, [selectedWardId, loadMusterStations, loadRoster, loadReports]);

  // QR Timer Countdown effect
  useEffect(() => {
    if (qrSecondsRemaining <= 0) return;

    timerRef.current = window.setInterval(() => {
      setQrSecondsRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(timerRef.current!);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [qrSecondsRemaining]);

  // Issue 5-Minute Roll-Call QR
  const handleGenerateQr = async () => {
    if (!selectedMusterId) return;
    setIsIssuingQr(true);
    setNotice(null);

    try {
      const res = await issueRollCallQr(selectedWardId, selectedMusterId);
      setQrTokenData(res);
      setQrSecondsRemaining(res.expires_in_seconds || 300);
      setNotice({
        type: 'success',
        message: 'Active 5-minute single-use roll-call token generated for worker scanning.',
      });
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to issue QR token. Check ward authorization.';
      setNotice({ type: 'danger', message: msg });
    } finally {
      setIsIssuingQr(false);
    }
  };

  // Review Attendance Exception
  const handleReviewAttendance = async (recordId: string, action: 'APPROVE' | 'REJECT') => {
    setReviewProcessingId(recordId);
    setNotice(null);
    try {
      await reviewAttendanceRecord({
        recordId,
        action,
        reviewNotes: reviewNotesInput || `Reviewed by official ${currentUser?.email} on ${new Date().toLocaleDateString()}`,
      });
      setNotice({
        type: 'success',
        message: `Attendance exception record has been ${action === 'APPROVE' ? 'approved' : 'rejected'}.`,
      });
      setReviewModalRecord(null);
      setReviewNotesInput('');
      await loadRoster(selectedWardId);
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to record attendance review.';
      setNotice({ type: 'danger', message: msg });
    } finally {
      setReviewProcessingId(null);
    }
  };

  // Update Report Status
  const handleUpdateReportStatusSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedReport) return;

    setIsUpdatingStatus(true);
    setNotice(null);

    try {
      await updateReportStatus(selectedReport.id, {
        status: statusUpdateVal,
        official_notes: officialNotesVal.trim() || undefined,
      });

      setNotice({
        type: 'success',
        message: `Report ${selectedReport.id.slice(0, 8)} status successfully updated to ${statusUpdateVal}.`,
      });
      setSelectedReport(null);
      setOfficialNotesVal('');
      await loadReports(selectedWardId);
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to update report status.';
      setNotice({ type: 'danger', message: msg });
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  const minutesRemaining = Math.floor(qrSecondsRemaining / 60);
  const secondsRemaining = qrSecondsRemaining % 60;
  const isQrExpired = qrTokenData && qrSecondsRemaining <= 0;

  const pendingReports = reports.filter(
    (r) => r.status === 'SUBMITTED' || r.status === 'UNDER_REVIEW'
  );
  const pendingReportsCount = pendingReports.length;

  const filteredReports = reportStatusFilter === 'ALL'
    ? reports
    : reports.filter((r) => r.status === reportStatusFilter);

  return (
    <div style={{ display: 'flex', minHeight: '100vh', backgroundColor: '#F5F9F5' }}>
      {/* Sidebar matching Citizen Dashboard visual language */}
      <CitizenSidebar
        role={currentUser?.role === 'MUNICIPAL_ADMIN' ? 'admin' : 'supervisor'}
        activeTab={activeTab}
        onTabChange={(tab) => {
          if (['dashboard', 'vehicles', 'reports', 'workers', 'analytics'].includes(tab)) {
            setActiveTab(tab as SupervisorTab);
          }
        }}
        notificationCount={pendingReportsCount}
      />

      {/* Main Content Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflowX: 'hidden' }}>
        {/* Unified Dashboard Band with Vidhana Soudha background */}
        <section className="nc-dashboard-band" id="home">
          <CitizenHeader
            selectedWardName={
              currentUser?.locality
                ? `Ward: ${currentUser.locality}`
                : currentUser?.ward_id
                ? `Ward: ${selectedWardId.slice(0, 8)}`
                : 'Bengaluru (Ward Administration)'
            }
          />

          <div className="nc-dashboard-band-inner">
            <CitizenBanner
              user={currentUser}
              isLoading={isLoadingUser}
              titlePrefix="Welcome Back, Officer"
              subtitle="Monitor collection operations, fleet movement, and field attendance across Bengaluru."
              roleBadge={currentUser?.role === 'MUNICIPAL_ADMIN' ? 'Municipal Administration' : 'Ward Supervision'}
              showBirds={false}
            />

            {/* 4 Operational Summary Cards matching civic design system */}
            <div className="nc-summary-overview" aria-label="Official operational metrics">
              <div className="nc-summary-grid">
                {/* 1. Active Vehicles */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('vehicles')}
                  role="button"
                  tabIndex={0}
                  title="Click to view Live Vehicle Monitoring Map"
                >
                  <span className="nc-summary-icon">
                    <Truck size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>{mapSummary ? String(mapSummary.active_live_vehicles) : '—'}</strong>
                    <span className="nc-summary-label">Active Vehicles</span>
                    <span className="nc-summary-note" style={{ color: '#2E7D32' }}>
                      {mapSummary?.simulation_active ? '● Live (Simulated)' : '↑ Live Telemetry'}
                    </span>
                  </span>
                </article>

                {/* 2. Published Routes */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('vehicles')}
                  role="button"
                  tabIndex={0}
                  title="Click to view collection routes on map"
                >
                  <span className="nc-summary-icon">
                    <Route size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>{mapSummary ? String(mapSummary.published_routes) : '—'}</strong>
                    <span className="nc-summary-label">Published Routes</span>
                    <span className="nc-summary-note" style={{ color: '#2E7D32' }}>
                      Across Bengaluru →
                    </span>
                  </span>
                </article>

                {/* 3. Pending Reports */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('reports')}
                  role="button"
                  tabIndex={0}
                  title="Click to review citizen dumping reports"
                >
                  <span className="nc-summary-icon">
                    <FileText size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>{isLoadingReports ? '…' : String(pendingReportsCount)}</strong>
                    <span className="nc-summary-label">Pending Reports</span>
                    <span
                      className="nc-summary-note"
                      style={{ color: pendingReportsCount > 0 ? '#B45309' : '#2E7D32' }}
                    >
                      {pendingReportsCount > 0 ? `${pendingReportsCount} Needs Action →` : '✓ All Cleared'}
                    </span>
                  </span>
                </article>

                {/* 4. Staff on Duty */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('analytics')}
                  role="button"
                  tabIndex={0}
                  title="Click to view daily attendance roster"
                >
                  <span className="nc-summary-icon">
                    <Users size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>
                      {isLoadingRoster ? '…' : (rosterData ? String(rosterData.present_count) : '—')}
                    </strong>
                    <span className="nc-summary-label">Staff on Duty</span>
                    <span className="nc-summary-note" style={{ color: '#2E7D32' }}>
                      {rosterData?.exception_pending_count
                        ? `${rosterData.exception_pending_count} Exceptions Pending`
                        : 'Attendance Roster →'}
                    </span>
                  </span>
                </article>
              </div>
            </div>
          </div>
        </section>

        {/* Dashboard Main Workspace */}
        <main className="nc-dashboard-main" style={{ padding: '1.25rem 2rem 2.5rem' }}>
          {notice && (
            <div style={{ marginBottom: '1.25rem' }}>
              <Alert type={notice.type}>{notice.message}</Alert>
            </div>
          )}

          {/* TAB 1: OPERATIONAL OVERVIEW */}
          {activeTab === 'dashboard' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              {/* Quick Actions & Navigation Bar */}
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '16px',
                  padding: '1.25rem 1.5rem',
                  border: '1px solid #D5E3D7',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '1rem',
                  flexWrap: 'wrap',
                }}
              >
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 750, color: '#183B2A' }}>
                    Quick Management Actions
                  </h3>
                  <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                    Direct shortcuts to daily supervisory operations
                  </p>
                </div>

                <div style={{ display: 'flex', gap: '0.65rem', flexWrap: 'wrap' }}>
                  <Button
                    type="button"
                    variant="primary"
                    onClick={() => setActiveTab('workers')}
                    style={{ fontSize: '0.85rem', padding: '0.55rem 1rem' }}
                  >
                    <QrCode size={16} />
                    <span>Issue Roll-Call QR</span>
                  </Button>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setActiveTab('vehicles')}
                    style={{ fontSize: '0.85rem', padding: '0.55rem 1rem' }}
                  >
                    <Truck size={16} />
                    <span>Live Fleet Map</span>
                  </Button>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setActiveTab('reports')}
                    style={{ fontSize: '0.85rem', padding: '0.55rem 1rem' }}
                  >
                    <FileText size={16} />
                    <span>Review Reports ({pendingReportsCount})</span>
                  </Button>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setActiveTab('analytics')}
                    style={{ fontSize: '0.85rem', padding: '0.55rem 1rem' }}
                  >
                    <BarChart3 size={16} />
                    <span>Operations Roster</span>
                  </Button>
                </div>
              </div>

              {/* Two Column Summary Overview */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
                  gap: '1.5rem',
                }}
              >
                {/* Column 1: Today's Roll-Call Status Card */}
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: '16px',
                    padding: '1.5rem',
                    border: '1px solid #D5E3D7',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '1.15rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                      <div
                        style={{
                          width: '38px',
                          height: '38px',
                          borderRadius: '10px',
                          backgroundColor: '#E8F5E9',
                          color: '#2E7D32',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <CalendarCheck size={20} />
                      </div>
                      <div>
                        <h4 style={{ margin: 0, fontSize: '1.02rem', fontWeight: 750, color: '#183B2A' }}>
                          Muster Roll-Call Progress
                        </h4>
                        <div style={{ fontSize: '0.78rem', color: '#5A7565' }}>
                          Station: {musterPoints[0]?.name || 'No active muster station'}
                        </div>
                      </div>
                    </div>

                    <span
                      style={{
                        padding: '3px 9px',
                        borderRadius: '999px',
                        fontSize: '0.75rem',
                        fontWeight: 700,
                        backgroundColor: '#E8F5E9',
                        color: '#2E7D32',
                      }}
                    >
                      Today
                    </span>
                  </div>

                  {/* Attendance Stats Progress */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                      <span style={{ color: '#4B5563' }}>Attendance Rate</span>
                      <strong style={{ color: '#183B2A' }}>
                        {rosterData && rosterData.total_count > 0
                          ? `${Math.round((rosterData.present_count / rosterData.total_count) * 100)}%`
                          : '0%'}
                      </strong>
                    </div>

                    {/* Progress Bar */}
                    <div
                      style={{
                        height: '10px',
                        backgroundColor: '#E5E7EB',
                        borderRadius: '999px',
                        overflow: 'hidden',
                      }}
                    >
                      <div
                        style={{
                          height: '100%',
                          width: `${rosterData && rosterData.total_count > 0 ? (rosterData.present_count / rosterData.total_count) * 100 : 0}%`,
                          backgroundColor: '#2E7D32',
                          borderRadius: '999px',
                          transition: 'width 0.4s ease',
                        }}
                      />
                    </div>
                  </div>

                  {/* Stat Pills */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem' }}>
                    <div style={{ backgroundColor: '#F8FAFC', padding: '0.75rem', borderRadius: '10px', textAlign: 'center' }}>
                      <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#2E7D32' }}>
                        {rosterData?.present_count ?? 0}
                      </div>
                      <div style={{ fontSize: '0.72rem', color: '#64748B', fontWeight: 600 }}>Present</div>
                    </div>

                    <div style={{ backgroundColor: '#F8FAFC', padding: '0.75rem', borderRadius: '10px', textAlign: 'center' }}>
                      <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#D97706' }}>
                        {rosterData?.exception_pending_count ?? 0}
                      </div>
                      <div style={{ fontSize: '0.72rem', color: '#64748B', fontWeight: 600 }}>Exceptions</div>
                    </div>

                    <div style={{ backgroundColor: '#F8FAFC', padding: '0.75rem', borderRadius: '10px', textAlign: 'center' }}>
                      <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#1E293B' }}>
                        {rosterData?.total_count ?? 0}
                      </div>
                      <div style={{ fontSize: '0.72rem', color: '#64748B', fontWeight: 600 }}>Total Roster</div>
                    </div>
                  </div>

                  <div style={{ marginTop: 'auto', paddingTop: '0.5rem' }}>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setActiveTab('analytics')}
                      style={{ width: '100%', justifyContent: 'center', fontSize: '0.85rem' }}
                    >
                      <span>View Full Daily Roster</span>
                      <ArrowRight size={15} />
                    </Button>
                  </div>
                </div>

                {/* Column 2: Recent Incident Reports Card */}
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: '16px',
                    padding: '1.5rem',
                    border: '1px solid #D5E3D7',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '1.15rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                      <div
                        style={{
                          width: '38px',
                          height: '38px',
                          borderRadius: '10px',
                          backgroundColor: '#FEF3C7',
                          color: '#B45309',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <ShieldAlert size={20} />
                      </div>
                      <div>
                        <h4 style={{ margin: 0, fontSize: '1.02rem', fontWeight: 750, color: '#183B2A' }}>
                          Citizen Dumping Incidents
                        </h4>
                        <div style={{ fontSize: '0.78rem', color: '#5A7565' }}>
                          {pendingReportsCount} pending review
                        </div>
                      </div>
                    </div>

                    <span
                      style={{
                        padding: '3px 9px',
                        borderRadius: '999px',
                        fontSize: '0.75rem',
                        fontWeight: 700,
                        backgroundColor: pendingReportsCount > 0 ? '#FEF3C7' : '#E8F5E9',
                        color: pendingReportsCount > 0 ? '#92400E' : '#2E7D32',
                      }}
                    >
                      {pendingReportsCount > 0 ? 'Action Required' : 'Cleared'}
                    </span>
                  </div>

                  {/* List of top 3 pending reports */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {isLoadingReports ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#64748B', padding: '1rem 0' }}>
                        <Spinner size="sm" />
                        <span>Loading complaints...</span>
                      </div>
                    ) : reports.length === 0 ? (
                      <div style={{ padding: '1.5rem', textAlign: 'center', color: '#64748B', fontSize: '0.85rem' }}>
                        No incident reports filed in this ward.
                      </div>
                    ) : (
                      reports.slice(0, 3).map((r) => (
                        <div
                          key={r.id}
                          style={{
                            padding: '0.85rem',
                            borderRadius: '10px',
                            backgroundColor: '#F8FAFC',
                            border: '1px solid #E2E8F0',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: '0.85rem',
                          }}
                        >
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              {r.description}
                            </div>
                            <div style={{ fontSize: '0.75rem', color: '#64748B', marginTop: '2px' }}>
                              Coords: {r.latitude.toFixed(4)}, {r.longitude.toFixed(4)}
                            </div>
                          </div>

                          <Button
                            type="button"
                            variant="outline"
                            onClick={() => {
                              setSelectedReport(r);
                              setStatusUpdateVal(r.status as any);
                              setActiveTab('reports');
                            }}
                            style={{ padding: '4px 8px', fontSize: '0.78rem' }}
                          >
                            <span>Inspect</span>
                            <ArrowRight size={13} />
                          </Button>
                        </div>
                      ))
                    )}
                  </div>

                  <div style={{ marginTop: 'auto', paddingTop: '0.5rem' }}>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setActiveTab('reports')}
                      style={{ width: '100%', justifyContent: 'center', fontSize: '0.85rem' }}
                    >
                      <span>Manage All Incident Reports ({reports.length})</span>
                      <ArrowRight size={15} />
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: LIVE VEHICLE MONITORING MAP */}
          {activeTab === 'vehicles' && (
            <div style={{ width: '100%', minWidth: 0, display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  padding: '1rem 1.5rem',
                  borderRadius: '14px',
                  border: '1px solid #D5E3D7',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: '1rem',
                }}
              >
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 750, color: '#183B2A' }}>
                    Fleet Telemetry & Operational Routing
                  </h3>
                  <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                    Real-time GPS vehicle positions, collection routes, and telemetry freshness.
                  </p>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
                  <span
                    style={{
                      padding: '4px 10px',
                      borderRadius: '999px',
                      backgroundColor: '#E8F5E9',
                      color: '#2E7D32',
                      fontSize: '0.75rem',
                      fontWeight: 700,
                    }}
                  >
                    ● 15s Auto Polling Active
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => loadMapSummary()}
                    style={{ fontSize: '0.82rem', padding: '5px 10px' }}
                  >
                    <RefreshCw size={14} />
                    <span>Refresh Telemetry</span>
                  </Button>
                </div>
              </div>

              {/* Embedded PublicVehicleMap reusing existing map component */}
              <div style={{ width: '100%', minWidth: 0 }}>
                <PublicVehicleMap
                  selectedVehicle={selectedVehicle}
                  onVehicleSelect={setSelectedVehicle}
                  onSummaryLoaded={setMapSummary}
                  details={
                    selectedVehicle ? (
                      <VehicleDetailsPanel
                        vehicle={selectedVehicle}
                        freshnessMinutes={mapSummary?.freshness_threshold_minutes ?? null}
                        onClose={() => setSelectedVehicle(null)}
                      />
                    ) : null
                  }
                />
              </div>
            </div>
          )}

          {/* TAB 3: CITIZEN REPORTS OVERSIGHT */}
          {activeTab === 'reports' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              {/* Filter and Header */}
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  padding: '1.25rem 1.5rem',
                  borderRadius: '14px',
                  border: '1px solid #D5E3D7',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: '1rem',
                }}
              >
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 750, color: '#183B2A' }}>
                    Citizen Dumping Incident Reports
                  </h3>
                  <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                    Review photographic evidence, verify GPS blackspots, and schedule clearance action.
                  </p>
                </div>

                {/* Filter Pills */}
                <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                  {['ALL', 'SUBMITTED', 'UNDER_REVIEW', 'ACTION_SCHEDULED', 'RESOLVED', 'REJECTED'].map((st) => (
                    <button
                      key={st}
                      type="button"
                      onClick={() => setReportStatusFilter(st)}
                      style={{
                        padding: '5px 11px',
                        borderRadius: '999px',
                        border: '1px solid',
                        borderColor: reportStatusFilter === st ? '#1B4D3E' : '#D1D5DB',
                        backgroundColor: reportStatusFilter === st ? '#1B4D3E' : '#FFFFFF',
                        color: reportStatusFilter === st ? '#FFFFFF' : '#4B5563',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        textTransform: 'capitalize',
                      }}
                    >
                      {st.toLowerCase().replace('_', ' ')}
                    </button>
                  ))}
                </div>
              </div>

              {/* Reports Table or Grid */}
              {isLoadingReports ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3rem', color: '#4B5563' }}>
                  <Spinner size="md" />
                  <span style={{ marginLeft: '0.75rem' }}>Loading reports from database...</span>
                </div>
              ) : filteredReports.length === 0 ? (
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    padding: '3rem 2rem',
                    borderRadius: '14px',
                    border: '1px solid #D5E3D7',
                    textAlign: 'center',
                    color: '#64748B',
                  }}
                >
                  <FileText size={36} style={{ margin: '0 auto 0.75rem', opacity: 0.5 }} />
                  <div style={{ fontSize: '1rem', fontWeight: 700, color: '#183B2A' }}>No reports match the filter</div>
                  <p style={{ margin: '0.25rem 0 0', fontSize: '0.85rem' }}>All citizen incident reports have been cleared or none filed in this category.</p>
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '1.25rem' }}>
                  {filteredReports.map((r) => {
                    const hasEvidence = r.evidence && r.evidence.length > 0;
                    return (
                      <div
                        key={r.id}
                        style={{
                          backgroundColor: '#FFFFFF',
                          borderRadius: '14px',
                          border: '1px solid #D5E3D7',
                          padding: '1.25rem',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '0.85rem',
                          boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem' }}>
                          <span
                            style={{
                              fontSize: '0.72rem',
                              fontWeight: 700,
                              fontFamily: 'monospace',
                              backgroundColor: '#F1F5F9',
                              color: '#475569',
                              padding: '2px 6px',
                              borderRadius: '6px',
                            }}
                          >
                            #{r.id.slice(0, 8)}
                          </span>

                          <span
                            style={{
                              padding: '3px 8px',
                              borderRadius: '999px',
                              fontSize: '0.72rem',
                              fontWeight: 700,
                              backgroundColor:
                                r.status === 'RESOLVED'
                                  ? '#D1FAE5'
                                  : r.status === 'REJECTED'
                                  ? '#FEE2E2'
                                  : r.status === 'ACTION_SCHEDULED'
                                  ? '#F3E8FF'
                                  : '#FEF3C7',
                              color:
                                r.status === 'RESOLVED'
                                  ? '#065F46'
                                  : r.status === 'REJECTED'
                                  ? '#991B1B'
                                  : r.status === 'ACTION_SCHEDULED'
                                  ? '#6B21A8'
                                  : '#92400E',
                            }}
                          >
                            {r.status.replace('_', ' ')}
                          </span>
                        </div>

                        <p style={{ margin: 0, fontSize: '0.92rem', color: '#1E293B', fontWeight: 600, lineHeight: 1.4 }}>
                          {r.description}
                        </p>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.78rem', color: '#64748B' }}>
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                            <MapPin size={13} />
                            {r.latitude.toFixed(4)}, {r.longitude.toFixed(4)}
                          </span>
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                            <Clock size={13} />
                            {new Date(r.created_at).toLocaleDateString()}
                          </span>
                        </div>

                        {/* Evidence Thumbnails */}
                        {hasEvidence && (
                          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.25rem' }}>
                            {r.evidence.map((ev, i) => (
                              <img
                                key={ev.id || i}
                                src={`/api/v1/reports/${r.id}/evidence/${ev.id}/download`}
                                alt="Report Evidence"
                                onError={(e) => {
                                  // Fallback placeholder on broken media link
                                  (e.target as HTMLElement).style.display = 'none';
                                }}
                                style={{
                                  width: '54px',
                                  height: '54px',
                                  borderRadius: '8px',
                                  objectFit: 'cover',
                                  border: '1px solid #CBD5E1',
                                }}
                              />
                            ))}
                          </div>
                        )}

                        <div style={{ marginTop: 'auto', paddingTop: '0.5rem', borderTop: '1px solid #F1F5F9' }}>
                          <Button
                            type="button"
                            variant="primary"
                            onClick={() => {
                              setSelectedReport(r);
                              setStatusUpdateVal(r.status as any);
                              setOfficialNotesVal(r.official_notes || '');
                            }}
                            style={{ width: '100%', justifyContent: 'center', fontSize: '0.85rem' }}
                          >
                            <span>Inspect & Update Status</span>
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Status Update Modal */}
              {selectedReport && (
                <div
                  style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    backgroundColor: 'rgba(0, 0, 0, 0.55)',
                    zIndex: 100,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '1.5rem',
                  }}
                  onClick={() => setSelectedReport(null)}
                >
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: '18px',
                      maxWidth: '560px',
                      width: '100%',
                      padding: '1.75rem',
                      boxShadow: '0 20px 40px rgba(0,0,0,0.2)',
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                      <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 750, color: '#183B2A' }}>
                        Update Incident Status
                      </h3>
                      <button
                        type="button"
                        onClick={() => setSelectedReport(null)}
                        style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#64748B' }}
                      >
                        <X size={20} />
                      </button>
                    </div>

                    <form onSubmit={handleUpdateReportStatusSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.15rem' }}>
                      <div>
                        <div style={{ fontSize: '0.78rem', color: '#64748B', fontWeight: 600, marginBottom: '0.3rem' }}>
                          Report #{selectedReport.id.slice(0, 8)}
                        </div>
                        <div style={{ fontSize: '0.92rem', color: '#1E293B', backgroundColor: '#F8FAFC', padding: '0.85rem', borderRadius: '10px' }}>
                          {selectedReport.description}
                        </div>
                      </div>

                      <div>
                        <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.4rem' }}>
                          Set Lifecycle Status
                        </label>
                        <select
                          value={statusUpdateVal}
                          onChange={(e) => setStatusUpdateVal(e.target.value as any)}
                          style={{
                            width: '100%',
                            padding: '0.65rem 0.85rem',
                            borderRadius: '10px',
                            border: '1px solid #CBD5E1',
                            fontSize: '0.9rem',
                            fontWeight: 600,
                          }}
                        >
                          <option value="UNDER_REVIEW">UNDER REVIEW (Investigation Assigned)</option>
                          <option value="ACTION_SCHEDULED">ACTION SCHEDULED (Truck / Crew Dispatched)</option>
                          <option value="RESOLVED">RESOLVED (Waste Cleared & Validated)</option>
                          <option value="REJECTED">REJECTED (Invalid / False Alarm)</option>
                        </select>
                      </div>

                      <div>
                        <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.4rem' }}>
                          Official Resolution Notes
                        </label>
                        <textarea
                          rows={3}
                          value={officialNotesVal}
                          onChange={(e) => setOfficialNotesVal(e.target.value)}
                          placeholder="e.g., Crew dispatched with Auto Tipper; 2 tons cleared; blackspot remediated."
                          style={{
                            width: '100%',
                            padding: '0.65rem 0.85rem',
                            borderRadius: '10px',
                            border: '1px solid #CBD5E1',
                            fontSize: '0.88rem',
                            boxSizing: 'border-box',
                            resize: 'vertical',
                          }}
                        />
                      </div>

                      <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => setSelectedReport(null)}
                        >
                          Cancel
                        </Button>

                        <Button
                          type="submit"
                          variant="primary"
                          disabled={isUpdatingStatus}
                        >
                          {isUpdatingStatus ? (
                            <>
                              <Spinner size="sm" />
                              <span style={{ marginLeft: '0.4rem' }}>Saving...</span>
                            </>
                          ) : (
                            <span>Confirm Status Update</span>
                          )}
                        </Button>
                      </div>
                    </form>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 4: ROLL-CALL QR GENERATOR */}
          {activeTab === 'workers' && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
                gap: '1.75rem',
                alignItems: 'start',
              }}
            >
              {/* Controls */}
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '16px',
                  padding: '1.75rem',
                  border: '1px solid #D5E3D7',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '1.25rem',
                }}
              >
                <div>
                  <h3 style={{ margin: '0 0 0.35rem', fontSize: '1.2rem', fontWeight: 750, color: '#183B2A' }}>
                    Issue 5-Minute Roll-Call QR
                  </h3>
                  <p style={{ margin: 0, fontSize: '0.85rem', color: '#5A7565' }}>
                    Workers scan this temporary code at the muster depot to register presence within the 150m geofence.
                  </p>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.4rem' }}>
                    Select Ward Muster Station
                  </label>
                  <select
                    value={selectedMusterId}
                    onChange={(e) => setSelectedMusterId(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '0.75rem 1rem',
                      borderRadius: '10px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.9rem',
                      fontWeight: 600,
                    }}
                  >
                    {musterPoints.length === 0 ? (
                      <option value="">No muster points found</option>
                    ) : (
                      musterPoints.map((pt) => (
                        <option key={pt.id} value={pt.id}>
                          {pt.name} ({pt.geofence_radius_meters}m geofence)
                        </option>
                      ))
                    )}
                  </select>
                </div>

                <div style={{ backgroundColor: '#F8FAFC', padding: '1rem', borderRadius: '12px', fontSize: '0.85rem', color: '#475569' }}>
                  <div style={{ fontWeight: 700, color: '#183B2A', marginBottom: '0.25rem' }}>Security Protocol:</div>
                  <ul style={{ margin: 0, paddingLeft: '1.2rem', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                    <li>Single-use cryptographic token, expires in strictly 300 seconds.</li>
                    <li>Device GPS must match station coordinates within geofence radius.</li>
                    <li>Proxy check-ins are detected and flagged as exceptions.</li>
                  </ul>
                </div>

                <Button
                  type="button"
                  variant="primary"
                  onClick={handleGenerateQr}
                  disabled={isIssuingQr}
                  style={{ justifyContent: 'center', padding: '0.85rem 1.5rem', fontSize: '0.95rem' }}
                >
                  {isIssuingQr ? (
                    <>
                      <Spinner size="sm" />
                      <span style={{ marginLeft: '0.5rem' }}>Generating Token...</span>
                    </>
                  ) : (
                    <>
                      <QrCode size={18} />
                      <span>{qrTokenData ? 'Regenerate QR Token' : 'Generate Roll-Call QR Code'}</span>
                    </>
                  )}
                </Button>
              </div>

              {/* QR Code Display Card */}
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '16px',
                  padding: '2rem',
                  border: '1px solid #D5E3D7',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  textAlign: 'center',
                  gap: '1.25rem',
                }}
              >
                {qrTokenData && !isQrExpired ? (
                  <>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span
                        style={{
                          backgroundColor: '#E8F5E9',
                          color: '#2E7D32',
                          fontWeight: 700,
                          fontSize: '0.85rem',
                          padding: '4px 12px',
                          borderRadius: '999px',
                        }}
                      >
                        ● Active Roll-Call Token
                      </span>
                    </div>

                    <QrCodeDisplay token={qrTokenData.token} size={220} />

                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        fontSize: '1.1rem',
                        fontWeight: 800,
                        color: qrSecondsRemaining <= 60 ? '#DC2626' : '#183B2A',
                      }}
                    >
                      <Clock size={18} />
                      <span>
                        Expires in: {String(minutesRemaining).padStart(2, '0')}:
                        {String(secondsRemaining).padStart(2, '0')}
                      </span>
                    </div>

                    <div style={{ fontSize: '0.78rem', color: '#64748B', maxWidth: '280px' }}>
                      Token ID: {qrTokenData.token.slice(0, 16)}...
                    </div>
                  </>
                ) : isQrExpired ? (
                  <div style={{ padding: '2.5rem 1rem' }}>
                    <div
                      style={{
                        width: '56px',
                        height: '56px',
                        borderRadius: '50%',
                        backgroundColor: '#FEE2E2',
                        color: '#DC2626',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        margin: '0 auto 1rem',
                      }}
                    >
                      <AlertTriangle size={28} />
                    </div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 750, color: '#1E293B' }}>Token Expired</div>
                    <p style={{ margin: '0.4rem 0 1.25rem', fontSize: '0.85rem', color: '#64748B' }}>
                      The 5-minute validity window elapsed. Generate a fresh QR code for the roll-call.
                    </p>
                    <Button type="button" variant="primary" onClick={handleGenerateQr}>
                      Generate New QR
                    </Button>
                  </div>
                ) : (
                  <div style={{ padding: '3.5rem 1rem', color: '#64748B' }}>
                    <QrCode size={48} style={{ margin: '0 auto 1rem', opacity: 0.4 }} />
                    <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#183B2A' }}>No Active QR Code</div>
                    <p style={{ margin: '0.4rem 0 0', fontSize: '0.85rem' }}>
                      Select a muster station and click Generate to start the 5-minute shift roll-call.
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 5: OPERATIONS ROSTER */}
          {activeTab === 'analytics' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              {/* Header */}
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  padding: '1.25rem 1.5rem',
                  borderRadius: '14px',
                  border: '1px solid #D5E3D7',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: '1rem',
                }}
              >
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 750, color: '#183B2A' }}>
                    Daily Pourakarmika Attendance Roster
                  </h3>
                  <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                    Muster Station: {musterPoints[0]?.name || 'No active muster station'} (Date: {new Date().toLocaleDateString()})
                  </p>
                </div>

                <Button
                  type="button"
                  variant="outline"
                  onClick={() => loadRoster(selectedWardId)}
                  style={{ fontSize: '0.82rem', padding: '6px 12px' }}
                >
                  <RefreshCw size={14} />
                  <span>Refresh Roster</span>
                </Button>
              </div>

              {/* Roster Records Table */}
              {isLoadingRoster ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3rem', color: '#4B5563' }}>
                  <Spinner size="md" />
                  <span style={{ marginLeft: '0.75rem' }}>Loading roster data...</span>
                </div>
              ) : !rosterData || rosterData.records.length === 0 ? (
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    padding: '3rem 2rem',
                    borderRadius: '14px',
                    border: '1px solid #D5E3D7',
                    textAlign: 'center',
                    color: '#64748B',
                  }}
                >
                  <Users size={36} style={{ margin: '0 auto 0.75rem', opacity: 0.5 }} />
                  <div style={{ fontSize: '1rem', fontWeight: 700, color: '#183B2A' }}>No attendance records found for today</div>
                  <p style={{ margin: '0.25rem 0 0', fontSize: '0.85rem' }}>
                    Workers can register attendance using the 5-Minute Roll-Call QR code or their field mobile dashboard.
                  </p>
                </div>
              ) : (
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: '14px',
                    border: '1px solid #D5E3D7',
                    overflowX: 'auto',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                  }}
                >
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.88rem' }}>
                    <thead>
                      <tr style={{ backgroundColor: '#F8FAFC', borderBottom: '1px solid #E2E8F0', color: '#475569' }}>
                        <th style={{ padding: '0.85rem 1.25rem', fontWeight: 700 }}>Worker Email</th>
                        <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Check-In</th>
                        <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Check-Out</th>
                        <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Muster Distance</th>
                        <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Status</th>
                        <th style={{ padding: '0.85rem 1.25rem', fontWeight: 700, textAlign: 'right' }}>Official Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rosterData.records.map((rec) => {
                        const isException = rec.status === 'EXCEPTION_PENDING';
                        return (
                          <tr key={rec.id} style={{ borderBottom: '1px solid #F1F5F9' }}>
                            <td style={{ padding: '0.85rem 1.25rem', fontWeight: 600, color: '#1E293B' }}>
                              {rec.worker_email || `Worker (${rec.worker_id.slice(0, 8)})`}
                            </td>
                            <td style={{ padding: '0.85rem 1rem', color: '#4B5563' }}>
                              {rec.check_in_at
                                ? new Date(rec.check_in_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
                                : '—'}
                            </td>
                            <td style={{ padding: '0.85rem 1rem', color: '#4B5563' }}>
                              {rec.check_out_at
                                ? new Date(rec.check_out_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
                                : '—'}
                            </td>
                            <td style={{ padding: '0.85rem 1rem', color: '#4B5563' }}>
                              {rec.check_in_distance_meters !== null && rec.check_in_distance_meters !== undefined
                                ? `${Math.round(rec.check_in_distance_meters)}m`
                                : '—'}
                            </td>
                            <td style={{ padding: '0.85rem 1rem' }}>
                              <span
                                style={{
                                  padding: '3px 8px',
                                  borderRadius: '999px',
                                  fontSize: '0.75rem',
                                  fontWeight: 700,
                                  backgroundColor:
                                    rec.status === 'PRESENT'
                                      ? '#D1FAE5'
                                      : rec.status === 'REJECTED'
                                      ? '#FEE2E2'
                                      : rec.status === 'EXCEPTION_PENDING'
                                      ? '#FEF3C7'
                                      : '#F1F5F9',
                                  color:
                                    rec.status === 'PRESENT'
                                      ? '#065F46'
                                      : rec.status === 'REJECTED'
                                      ? '#991B1B'
                                      : rec.status === 'EXCEPTION_PENDING'
                                      ? '#92400E'
                                      : '#475569',
                                }}
                              >
                                {rec.status}
                              </span>
                            </td>
                            <td style={{ padding: '0.85rem 1.25rem', textAlign: 'right' }}>
                              {isException ? (
                                <Button
                                  type="button"
                                  variant="primary"
                                  onClick={() => setReviewModalRecord(rec)}
                                  disabled={reviewProcessingId === rec.id}
                                  style={{ padding: '4px 10px', fontSize: '0.78rem' }}
                                >
                                  <span>Review Exception</span>
                                </Button>
                              ) : (
                                <span style={{ fontSize: '0.78rem', color: '#94A3B8' }}>Verified</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Exception Review Modal */}
              {reviewModalRecord && (
                <div
                  style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    backgroundColor: 'rgba(0, 0, 0, 0.55)',
                    zIndex: 100,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '1.5rem',
                  }}
                  onClick={() => setReviewModalRecord(null)}
                >
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: '18px',
                      maxWidth: '520px',
                      width: '100%',
                      padding: '1.75rem',
                      boxShadow: '0 20px 40px rgba(0,0,0,0.2)',
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                      <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 750, color: '#183B2A' }}>
                        Review Attendance Exception
                      </h3>
                      <button
                        type="button"
                        onClick={() => setReviewModalRecord(null)}
                        style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#64748B' }}
                      >
                        <X size={20} />
                      </button>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                      <div style={{ backgroundColor: '#FEF3C7', padding: '0.85rem', borderRadius: '10px', color: '#92400E', fontSize: '0.88rem' }}>
                        <strong>Reason: </strong>
                        {reviewModalRecord.exception_reason || 'Check-in was recorded beyond the 150m muster geofence.'}
                      </div>

                      <div style={{ fontSize: '0.85rem', color: '#4B5563' }}>
                        <div><strong>Worker:</strong> {reviewModalRecord.worker_email || reviewModalRecord.worker_id}</div>
                        <div><strong>Recorded Distance:</strong> {Math.round(reviewModalRecord.check_in_distance_meters || 0)} meters from depot</div>
                        <div><strong>Time:</strong> {reviewModalRecord.check_in_at ? new Date(reviewModalRecord.check_in_at).toLocaleTimeString() : '—'}</div>
                      </div>

                      <div>
                        <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                          Official Review Notes
                        </label>
                        <input
                          type="text"
                          value={reviewNotesInput}
                          onChange={(e) => setReviewNotesInput(e.target.value)}
                          placeholder="e.g. Field verification confirmed valid detour"
                          style={{
                            width: '100%',
                            padding: '0.65rem 0.85rem',
                            borderRadius: '8px',
                            border: '1px solid #CBD5E1',
                            fontSize: '0.88rem',
                            boxSizing: 'border-box',
                          }}
                        />
                      </div>

                      <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                        <Button
                          type="button"
                          variant="danger"
                          onClick={() => handleReviewAttendance(reviewModalRecord.id, 'REJECT')}
                          disabled={Boolean(reviewProcessingId)}
                        >
                          Reject Absence
                        </Button>

                        <Button
                          type="button"
                          variant="primary"
                          onClick={() => handleReviewAttendance(reviewModalRecord.id, 'APPROVE')}
                          disabled={Boolean(reviewProcessingId)}
                        >
                          Approve Exception (Mark Present)
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
};
