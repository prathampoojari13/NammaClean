import React, { useState, useEffect, useCallback } from 'react';
import {
  ArrowRight,
  CalendarCheck,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  KeyRound,
  LockKeyhole,
  MapPin,
  RefreshCw,
  Send,
  ShieldCheck,
  Truck,
  X,
} from 'lucide-react';
import { CitizenSidebar } from '../../components/layout/CitizenSidebar';
import { CitizenHeader } from '../../components/layout/CitizenHeader';
import { CitizenBanner } from '../../components/dashboard/CitizenBanner';
import { PublicVehicleMap } from '../../components/map/PublicVehicleMap';
import { Button } from '../../components/ui/Button';
import { Alert } from '../../components/ui/Alert';
import { Spinner } from '../../components/ui/Spinner';
import { apiClient } from '../../api/client';
import {
  requestAttendanceOtp,
  verifyAttendanceOtp,
  submitOtpAttendance,
  submitCheckOut,
  getWorkerTodayAttendance,
  getWorkerAssignment,
  AttendanceDailyItem,
  WorkerAssignment,
  AttendanceCheckInResponse,
} from '../../api/attendance';
import type { User as UserType } from '../../types';
import '../../styles/citizen-dashboard.css';

export type WorkerTab = 'dashboard' | 'attendance' | 'tasks' | 'vehicle' | 'profile';

export const WorkerDashboard: React.FC = () => {
  const [currentUser, setCurrentUser] = useState<UserType | null>(null);
  const [assignment, setAssignment] = useState<WorkerAssignment | null>(null);
  const [todayRecord, setTodayRecord] = useState<AttendanceDailyItem | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<WorkerTab>('dashboard');

  // Modal & OTP state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalStep, setModalStep] = useState<'request' | 'verify' | 'submitting' | 'success'>('request');
  const [challengeId, setChallengeId] = useState<string>('');
  const [otpCode, setOtpCode] = useState('');
  const [otpError, setOtpError] = useState<string | null>(null);
  const [checkInResult, setCheckInResult] = useState<AttendanceCheckInResponse | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [copiedOtp, setCopiedOtp] = useState(false);
  const [countdownSeconds, setCountdownSeconds] = useState<number>(300);
  const [remainingAttempts, setRemainingAttempts] = useState<number>(3);

  // Countdown timer for OTP validity in verify step
  useEffect(() => {
    if (!isModalOpen || modalStep !== 'verify' || countdownSeconds <= 0) {
      return;
    }
    const timer = setInterval(() => {
      setCountdownSeconds((prev) => {
        if (prev <= 1) {
          setDevOtp(null); // Clear displayed OTP once expired
          setOtpError('Verification code has expired. Please request a new code.');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [isModalOpen, modalStep, countdownSeconds]);

  const formatCountdown = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  const handleCopyOtp = async () => {
    if (!devOtp) return;
    try {
      await navigator.clipboard.writeText(devOtp);
      setCopiedOtp(true);
      setTimeout(() => setCopiedOtp(false), 2000);
    } catch {
      const textArea = document.createElement('textarea');
      textArea.value = devOtp;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      setCopiedOtp(true);
      setTimeout(() => setCopiedOtp(false), 2000);
    }
  };

  const openAttendanceModal = () => {
    setModalStep('request');
    setOtpError(null);
    setOtpCode('');
    setDevOtp(null);
    setCopiedOtp(false);
    setRemainingAttempts(3);
    setCountdownSeconds(300);
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
    setModalStep('request');
    setOtpError(null);
    setOtpCode('');
    setDevOtp(null);
    setCopiedOtp(false);
    setRemainingAttempts(3);
  };

  // Check-out processing
  const [isCheckingOut, setIsCheckingOut] = useState(false);
  const [actionNotice, setActionNotice] = useState<{ type: 'success' | 'danger' | 'warning'; message: string } | null>(null);

  const loadWorkerData = useCallback(async () => {
    setIsLoading(true);
    try {
      const user = await apiClient.get<UserType>('/users/me');
      setCurrentUser(user);

      const [assignRes, attRes] = await Promise.all([
        getWorkerAssignment(),
        getWorkerTodayAttendance(),
      ]);
      setAssignment(assignRes);
      setTodayRecord(attRes);
    } catch {
      setActionNotice({
        type: 'danger',
        message: 'Unable to load worker assignment or session expired. Please sign in again.',
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadWorkerData();
  }, [loadWorkerData]);

  // Step 1: Request Email OTP
  const handleRequestOtp = async () => {
    setOtpError(null);
    setIsProcessing(true);
    setCopiedOtp(false);
    try {
      const res = await requestAttendanceOtp();
      setChallengeId(res.challenge_id);
      setDevOtp(res.dev_otp || null);
      setCountdownSeconds(res.expires_in_seconds || 300);
      setRemainingAttempts(3);
      setModalStep('verify');
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to dispatch attendance OTP. Please verify backend connection.';
      setOtpError(msg);
    } finally {
      setIsProcessing(false);
    }
  };

  // Step 2 & 3: Verify OTP & submit coordinates
  const handleVerifyAndCheckIn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!otpCode || otpCode.length !== 6) {
      setOtpError('Please enter the full 6-digit verification code.');
      return;
    }

    setOtpError(null);
    setIsProcessing(true);

    try {
      // 1. Verify OTP code
      const verifyRes = await verifyAttendanceOtp(challengeId, otpCode);
      if (!verifyRes.verified) {
        setOtpError('The verification code is incorrect or expired. Please retry.');
        setIsProcessing(false);
        return;
      }

      // 2. Obtain device GPS coordinates
      if (!('geolocation' in navigator)) {
        setOtpError('Geolocation is not supported by your browser. Device GPS location is required to verify muster depot attendance.');
        setIsProcessing(false);
        return;
      }

      let lat: number;
      let lon: number;

      try {
        const position = await new Promise<GeolocationPosition>((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 8000,
            maximumAge: 0,
          });
        });
        lat = position.coords.latitude;
        lon = position.coords.longitude;
      } catch (geoErr: any) {
        let msg = 'Could not retrieve your GPS location. Please ensure location services are enabled.';
        if (geoErr && typeof geoErr === 'object' && geoErr.code === 1) {
          msg = 'Location permission was denied. Location access is required to verify muster depot attendance.';
        } else if (geoErr && typeof geoErr === 'object' && geoErr.code === 3) {
          msg = 'Location request timed out. Please check your GPS signal and retry.';
        }
        setOtpError(msg);
        setIsProcessing(false);
        return;
      }

      // 3. Submit check-in
      const checkInRes = await submitOtpAttendance({
        challengeId,
        latitude: lat,
        longitude: lon,
        wardId: assignment?.ward_id,
        musterPointId: assignment?.muster_point_id,
      });

      setCheckInResult(checkInRes);
      setModalStep('success');
      await loadWorkerData();

      setActionNotice({
        type: 'success',
        message: `Attendance registered successfully (${checkInRes.status}). Check-in time: ${new Date(checkInRes.check_in_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}.`,
      });
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to record attendance check-in. Please try again.';
      setRemainingAttempts((prev) => {
        const next = Math.max(0, prev - 1);
        if (next === 0) {
          setDevOtp(null); // Invalidate displayed OTP when attempts are exhausted
        }
        return next;
      });
      setOtpError(msg);
    } finally {
      setIsProcessing(false);
    }
  };

  // Check-Out Handler
  const handleCheckOut = async () => {
    setIsCheckingOut(true);
    setActionNotice(null);
    try {
      if (!('geolocation' in navigator)) {
        setActionNotice({
          type: 'danger',
          message: 'Geolocation is not supported by your browser. Device GPS location is required to record check-out.',
        });
        setIsCheckingOut(false);
        return;
      }

      let lat: number;
      let lon: number;
      try {
        const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 8000 });
        });
        lat = pos.coords.latitude;
        lon = pos.coords.longitude;
      } catch (geoErr: any) {
        let msg = 'Could not determine GPS coordinates for check-out. Please enable location services.';
        if (geoErr && typeof geoErr === 'object' && geoErr.code === 1) {
          msg = 'Location permission was denied. Location access is required to record shift check-out.';
        }
        setActionNotice({ type: 'danger', message: msg });
        setIsCheckingOut(false);
        return;
      }

      const res = await submitCheckOut({
        latitude: lat,
        longitude: lon,
        wardId: assignment?.ward_id,
        musterPointId: assignment?.muster_point_id,
      });

      setActionNotice({
        type: 'success',
        message: `Shift check-out recorded successfully at ${new Date(res.check_out_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}.`,
      });
      await loadWorkerData();
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to process shift check-out.';
      setActionNotice({ type: 'danger', message: msg });
    } finally {
      setIsCheckingOut(false);
    }
  };

  const isCheckedIn = Boolean(todayRecord && todayRecord.check_in_at);
  const isCheckedOut = Boolean(todayRecord && todayRecord.check_out_at);

  return (
    <div style={{ display: 'flex', minHeight: '100vh', backgroundColor: '#F5F9F5' }}>
      {/* Sidebar matching Citizen Dashboard visual language */}
      <CitizenSidebar
        role="worker"
        activeTab={activeTab}
        onTabChange={(tab) => {
          if (['dashboard', 'attendance', 'tasks', 'vehicle', 'profile'].includes(tab)) {
            setActiveTab(tab as WorkerTab);
          }
        }}
        notificationCount={isCheckedIn ? 0 : 1}
      />

      {/* Main Content Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflowX: 'hidden' }}>
        {/* Unified Dashboard Band with Vidhana Soudha background */}
        <section className="nc-dashboard-band" id="home">
          <CitizenHeader
            selectedWardName={assignment?.ward_name ? `Ward: ${assignment.ward_name}` : 'Bengaluru (Field Operations)'}
          />

          <div className="nc-dashboard-band-inner">
            <CitizenBanner
              user={currentUser}
              isLoading={isLoading}
              titlePrefix="Welcome Back"
              subtitle="Your daily assignment, muster roll-call, and shift attendance in one place."
              roleBadge={currentUser?.role === 'DRIVER' ? 'Collection Driver' : 'Pourakarmika'}
              showBirds={false}
            />

            {/* 4 Daily Summary Cards matching civic design system */}
            <div className="nc-summary-overview" aria-label="Pourakarmika daily metrics">
              <div className="nc-summary-grid">
                {/* 1. Today's Assignment */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('tasks')}
                  role="button"
                  tabIndex={0}
                  title="Click to view muster depot & tasks"
                >
                  <span className="nc-summary-icon">
                    <MapPin size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>
                      {assignment?.muster_point_name
                        ? assignment.muster_point_name.split(' ')[0]
                        : 'Unassigned'}
                    </strong>
                    <span className="nc-summary-label">Muster Depot</span>
                    <span className="nc-summary-note" style={{ color: assignment?.ward_name ? '#2E7D32' : '#64748B' }}>
                      {assignment?.ward_name || 'No Active Ward'} →
                    </span>
                  </span>
                </article>

                {/* 2. Attendance Status */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('attendance')}
                  role="button"
                  tabIndex={0}
                  title="Click to open shift attendance portal"
                >
                  <span className="nc-summary-icon">
                    <CalendarCheck size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>
                      {isCheckedIn
                        ? todayRecord?.status === 'PRESENT'
                          ? 'Present'
                          : 'Exception'
                        : 'Pending'}
                    </strong>
                    <span className="nc-summary-label">Shift Attendance</span>
                    <span
                      className="nc-summary-note"
                      style={{
                        color: isCheckedIn
                          ? todayRecord?.status === 'PRESENT'
                            ? '#2E7D32'
                            : '#D97706'
                          : '#DC2626',
                      }}
                    >
                      {isCheckedIn
                        ? todayRecord?.status === 'PRESENT'
                          ? '✓ Checked In'
                          : '⚠ Exception Pending'
                        : '● Not Checked In →'}
                    </span>
                  </span>
                </article>

                {/* 3. Assigned Vehicle */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('vehicle')}
                  role="button"
                  tabIndex={0}
                  title="Click to view vehicle & route info"
                >
                  <span className="nc-summary-icon">
                    <Truck size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>
                      {currentUser?.role === 'DRIVER' ? 'KA-04-TR' : 'Auto Tipper'}
                    </strong>
                    <span className="nc-summary-label">Assigned Vehicle</span>
                    <span className="nc-summary-note" style={{ color: '#2E7D32' }}>
                      Ward Fleet Unit →
                    </span>
                  </span>
                </article>

                {/* 4. Shift Time */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('attendance')}
                  role="button"
                  tabIndex={0}
                  title="Click to view shift timing details"
                >
                  <span className="nc-summary-icon">
                    <Clock size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>
                      {todayRecord?.check_in_at
                        ? new Date(todayRecord.check_in_at).toLocaleTimeString('en-IN', {
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : '—'}
                    </strong>
                    <span className="nc-summary-label">Check-In Time</span>
                    <span className="nc-summary-note" style={{ color: '#2E7D32' }}>
                      {isCheckedOut
                        ? 'Shift Completed'
                        : isCheckedIn
                        ? '● Shift Active'
                        : 'Roll-Call Ready'}
                    </span>
                  </span>
                </article>
              </div>
            </div>
          </div>
        </section>

        {/* Dashboard Main Workspace */}
        <main className="nc-dashboard-main" style={{ padding: '1.25rem 2rem 2.5rem' }}>
          {actionNotice && (
            <div style={{ marginBottom: '1.25rem' }}>
              <Alert type={actionNotice.type}>{actionNotice.message}</Alert>
            </div>
          )}

          {isLoading ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '4rem', color: '#4B5563' }}>
              <Spinner size="md" />
              <span style={{ marginLeft: '0.75rem' }}>Synchronizing worker assignment and shift records...</span>
            </div>
          ) : (
            <>
              {/* TAB 1: FIELD OVERVIEW */}
              {activeTab === 'dashboard' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                  {/* Attendance Callout Action Box */}
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: '16px',
                      padding: '1.5rem 1.75rem',
                      border: '1px solid #D5E3D7',
                      boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '1.5rem',
                      flexWrap: 'wrap',
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                        <span
                          style={{
                            padding: '3px 10px',
                            borderRadius: '999px',
                            fontSize: '0.75rem',
                            fontWeight: 700,
                            backgroundColor: isCheckedIn ? '#D1FAE5' : '#FEF3C7',
                            color: isCheckedIn ? '#065F46' : '#92400E',
                          }}
                        >
                          {isCheckedOut ? 'Shift Done' : isCheckedIn ? 'Shift In Progress' : 'Action Required'}
                        </span>
                        <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 750, color: '#183B2A' }}>
                          {isCheckedOut
                            ? 'Today’s Shift Completed'
                            : isCheckedIn
                            ? 'You are Checked In & On Duty'
                            : 'Daily Roll-Call Check-In'}
                        </h3>
                      </div>
                      <p style={{ margin: '0.35rem 0 0', fontSize: '0.88rem', color: '#5A7565' }}>
                        {isCheckedOut
                          ? 'Thank you for your civic contribution today. Check-out was recorded successfully.'
                          : isCheckedIn
                          ? `Checked in at ${new Date(todayRecord?.check_in_at || '').toLocaleTimeString()} at ${assignment?.muster_point_name || 'Muster Depot'}.`
                          : 'Verify your presence at your assigned depot using 6-digit Email OTP and GPS coordinates.'}
                      </p>
                    </div>

                    <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                      {!isCheckedIn ? (
                        <Button
                          type="button"
                          variant="primary"
                          onClick={openAttendanceModal}
                          style={{ padding: '0.75rem 1.4rem', fontSize: '0.95rem' }}
                        >
                          <ShieldCheck size={18} />
                          <span>Mark Daily Attendance (Email OTP)</span>
                        </Button>
                      ) : !isCheckedOut ? (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={handleCheckOut}
                          disabled={isCheckingOut}
                          style={{ padding: '0.75rem 1.4rem', fontSize: '0.95rem', borderColor: '#DC2626', color: '#DC2626' }}
                        >
                          {isCheckingOut ? (
                            <>
                              <Spinner size="sm" />
                              <span style={{ marginLeft: '0.4rem' }}>Recording Check-Out...</span>
                            </>
                          ) : (
                            <>
                              <Clock size={18} />
                              <span>Record Shift Check-Out</span>
                            </>
                          )}
                        </Button>
                      ) : (
                        <div
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.4rem',
                            padding: '0.65rem 1.25rem',
                            borderRadius: '10px',
                            backgroundColor: '#E8F5E9',
                            color: '#2E7D32',
                            fontWeight: 700,
                            fontSize: '0.9rem',
                          }}
                        >
                          <CheckCircle2 size={18} />
                          <span>Shift Concluded</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Two Column Layout: Assignment Details & Quick Navigation */}
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
                      gap: '1.5rem',
                    }}
                  >
                    {/* Today's Assignment Card */}
                    <div
                      style={{
                        backgroundColor: '#FFFFFF',
                        borderRadius: '16px',
                        padding: '1.5rem',
                        border: '1px solid #D5E3D7',
                        boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1rem',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                        <div
                          style={{
                            width: '40px',
                            height: '40px',
                            borderRadius: '10px',
                            backgroundColor: '#E8F5E9',
                            color: '#2E7D32',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          <MapPin size={22} />
                        </div>
                        <div>
                          <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 750, color: '#183B2A' }}>
                            Assigned Muster Station
                          </h4>
                          <div style={{ fontSize: '0.78rem', color: '#5A7565' }}>
                            BBMP Ward 04 — Yelahanka
                          </div>
                        </div>
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', backgroundColor: '#F8FAFC', padding: '1rem', borderRadius: '12px', fontSize: '0.88rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Depot Name:</span>
                          <strong style={{ color: '#1E293B' }}>{assignment?.muster_point_name || 'Yelahanka Satellite Town Muster Depot'}</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Geofence Radius:</span>
                          <strong style={{ color: '#1E293B' }}>{assignment?.geofence_radius_meters || 150} meters</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Assigned Ward:</span>
                          <strong style={{ color: '#1E293B' }}>{assignment?.ward_name || 'Yelahanka'}</strong>
                        </div>
                      </div>

                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => setActiveTab('tasks')}
                        style={{ width: '100%', justifyContent: 'center', fontSize: '0.85rem' }}
                      >
                        <span>View Station Details & Instructions</span>
                        <ArrowRight size={15} />
                      </Button>
                    </div>

                    {/* Assigned Vehicle & Route Card */}
                    <div
                      style={{
                        backgroundColor: '#FFFFFF',
                        borderRadius: '16px',
                        padding: '1.5rem',
                        border: '1px solid #D5E3D7',
                        boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1rem',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                        <div
                          style={{
                            width: '40px',
                            height: '40px',
                            borderRadius: '10px',
                            backgroundColor: '#E0F2FE',
                            color: '#0284C7',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          <Truck size={22} />
                        </div>
                        <div>
                          <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 750, color: '#183B2A' }}>
                            Assigned Fleet Unit & Route
                          </h4>
                          <div style={{ fontSize: '0.78rem', color: '#5A7565' }}>
                            Daily Collection Protocol
                          </div>
                        </div>
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', backgroundColor: '#F8FAFC', padding: '1rem', borderRadius: '12px', fontSize: '0.88rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Vehicle Type:</span>
                          <strong style={{ color: '#1E293B' }}>
                            {currentUser?.role === 'DRIVER' ? 'Compactor Truck' : 'Auto Tipper (Door-to-Door)'}
                          </strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Registration:</span>
                          <strong style={{ color: '#1E293B' }}>
                            {currentUser?.role === 'DRIVER' ? 'KA-04-TR-1082' : 'KA-04-AT-0914'}
                          </strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Route Code:</span>
                          <strong style={{ color: '#1E293B' }}>
                            {assignment?.ward_name ? `${assignment.ward_name} Route 01` : 'Yelahanka Route 01'}
                          </strong>
                        </div>
                      </div>

                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => setActiveTab('vehicle')}
                        style={{ width: '100%', justifyContent: 'center', fontSize: '0.85rem' }}
                      >
                        <span>Inspect Route on Live Map</span>
                        <ArrowRight size={15} />
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 2: ATTENDANCE PORTAL */}
              {activeTab === 'attendance' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
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
                        Pourakarmika Roll-Call & Shift Attendance
                      </h3>
                      <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                        Cryptographic OTP and geofence verification for authentic field presence.
                      </p>
                    </div>

                    <Button
                      type="button"
                      variant="outline"
                      onClick={loadWorkerData}
                      style={{ fontSize: '0.82rem', padding: '6px 12px' }}
                    >
                      <RefreshCw size={14} />
                      <span>Refresh Status</span>
                    </Button>
                  </div>

                  {/* Attendance Verification Box */}
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: '16px',
                      border: '1px solid #D5E3D7',
                      padding: '1.75rem',
                      boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '1.25rem',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <div
                          style={{
                            width: '46px',
                            height: '46px',
                            borderRadius: '12px',
                            backgroundColor: isCheckedIn ? '#D1FAE5' : '#FEF3C7',
                            color: isCheckedIn ? '#065F46' : '#92400E',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          <CalendarCheck size={24} />
                        </div>
                        <div>
                          <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 700, textTransform: 'uppercase' }}>
                            Today's Verification Status
                          </div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#1E293B', marginTop: '2px' }}>
                            {isCheckedIn
                              ? todayRecord?.status === 'PRESENT'
                                ? 'Present & Verified on Duty'
                                : 'Exception Flagged (Pending Review)'
                              : 'Not Checked In for Roll-Call'}
                          </div>
                        </div>
                      </div>

                      <span
                        style={{
                          padding: '6px 14px',
                          borderRadius: '999px',
                          fontSize: '0.82rem',
                          fontWeight: 700,
                          backgroundColor: isCheckedIn ? (todayRecord?.status === 'PRESENT' ? '#D1FAE5' : '#FEF3C7') : '#FEE2E2',
                          color: isCheckedIn ? (todayRecord?.status === 'PRESENT' ? '#065F46' : '#92400E') : '#DC2626',
                        }}
                      >
                        {isCheckedIn ? todayRecord?.status : 'PENDING'}
                      </span>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem', backgroundColor: '#F8FAFC', padding: '1.25rem', borderRadius: '12px' }}>
                      <div>
                        <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Check-In Timestamp</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 750, color: '#1E293B', marginTop: '3px' }}>
                          {todayRecord?.check_in_at
                            ? new Date(todayRecord.check_in_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
                            : '—'}
                        </div>
                      </div>

                      <div>
                        <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Check-Out Timestamp</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 750, color: '#1E293B', marginTop: '3px' }}>
                          {todayRecord?.check_out_at
                            ? new Date(todayRecord.check_out_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
                            : '—'}
                        </div>
                      </div>

                      <div>
                        <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Muster Distance</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 750, color: '#1E293B', marginTop: '3px' }}>
                          {todayRecord?.check_in_distance_meters !== null && todayRecord?.check_in_distance_meters !== undefined
                            ? `${Math.round(todayRecord.check_in_distance_meters)} meters`
                            : '—'}
                        </div>
                      </div>

                      <div>
                        <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Geofence Check</div>
                        <div style={{ fontSize: '1.05rem', fontWeight: 750, color: isCheckedIn ? (todayRecord?.status === 'PRESENT' ? '#2E7D32' : '#D97706') : '#64748B', marginTop: '3px' }}>
                          {isCheckedIn
                            ? todayRecord?.status === 'PRESENT'
                              ? 'Within 150m Depot'
                              : 'Beyond Geofence Radius'
                            : 'Pending Verification'}
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', paddingTop: '0.5rem' }}>
                      {!isCheckedIn ? (
                        <Button
                          type="button"
                          variant="primary"
                          onClick={openAttendanceModal}
                          style={{ padding: '0.85rem 1.6rem', fontSize: '0.95rem' }}
                        >
                          <ShieldCheck size={18} />
                          <span>Mark Daily Attendance (Email OTP)</span>
                        </Button>
                      ) : !isCheckedOut ? (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={handleCheckOut}
                          disabled={isCheckingOut}
                          style={{ padding: '0.85rem 1.6rem', fontSize: '0.95rem', borderColor: '#DC2626', color: '#DC2626' }}
                        >
                          {isCheckingOut ? (
                            <>
                              <Spinner size="sm" />
                              <span style={{ marginLeft: '0.4rem' }}>Recording Check-Out...</span>
                            </>
                          ) : (
                            <>
                              <Clock size={18} />
                              <span>Record Shift Check-Out</span>
                            </>
                          )}
                        </Button>
                      ) : (
                        <div
                          style={{
                            padding: '0.85rem 1.6rem',
                            borderRadius: '10px',
                            backgroundColor: '#E8F5E9',
                            color: '#2E7D32',
                            fontWeight: 700,
                          }}
                        >
                          ✓ Daily attendance and shift check-out completed
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 3: TASKS & MUSTER DEPOT */}
              {activeTab === 'tasks' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      padding: '1.25rem 1.5rem',
                      borderRadius: '14px',
                      border: '1px solid #D5E3D7',
                    }}
                  >
                    <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 750, color: '#183B2A' }}>
                      Daily Muster Station & Operational Tasks
                    </h3>
                    <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                      Muster point details, shift timetable, and field waste collection duties.
                    </p>
                  </div>

                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
                      gap: '1.5rem',
                    }}
                  >
                    <div
                      style={{
                        backgroundColor: '#FFFFFF',
                        borderRadius: '16px',
                        padding: '1.5rem',
                        border: '1px solid #D5E3D7',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1rem',
                      }}
                    >
                      <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 750, color: '#183B2A' }}>
                        Station Geolocation
                      </h4>

                      <div style={{ backgroundColor: '#F8FAFC', padding: '1rem', borderRadius: '12px', fontSize: '0.88rem', display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                        <div><strong>Depot:</strong> {assignment?.muster_point_name || 'No active muster station'}</div>
                        <div><strong>Coordinates:</strong> {assignment?.muster_point_name ? '13.0985° N, 77.5895° E' : '—'}</div>
                        <div><strong>Geofence Radius:</strong> {assignment?.geofence_radius_meters ? `${assignment.geofence_radius_meters} meters` : '—'}</div>
                        <div><strong>Assigned Ward:</strong> {assignment?.ward_name || 'No ward assigned'}</div>
                      </div>
                    </div>

                    <div
                      style={{
                        backgroundColor: '#FFFFFF',
                        borderRadius: '16px',
                        padding: '1.5rem',
                        border: '1px solid #D5E3D7',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1rem',
                      }}
                    >
                      <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 750, color: '#183B2A' }}>
                        Daily Shift Timetable
                      </h4>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.88rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                          <span style={{ padding: '3px 8px', borderRadius: '6px', backgroundColor: '#E8F5E9', color: '#2E7D32', fontWeight: 700, fontSize: '0.78rem' }}>06:30 AM</span>
                          <span>Depot roll-call check-in & tool allotment</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                          <span style={{ padding: '3px 8px', borderRadius: '6px', backgroundColor: '#E0F2FE', color: '#0284C7', fontWeight: 700, fontSize: '0.78rem' }}>07:00 AM</span>
                          <span>Commence door-to-door segregated waste collection</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                          <span style={{ padding: '3px 8px', borderRadius: '6px', backgroundColor: '#FEF3C7', color: '#D97706', fontWeight: 700, fontSize: '0.78rem' }}>11:30 AM</span>
                          <span>Transfer station tipping & secondary segregation</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                          <span style={{ padding: '3px 8px', borderRadius: '6px', backgroundColor: '#F3E8FF', color: '#7E22CE', fontWeight: 700, fontSize: '0.78rem' }}>02:30 PM</span>
                          <span>Return to muster depot & record shift check-out</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 4: VEHICLE & ROUTE */}
              {activeTab === 'vehicle' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
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
                        Assigned Collection Route & Fleet Tracker
                      </h3>
                      <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                        Vehicle: {currentUser?.role === 'DRIVER' ? 'KA-04-TR-1082' : 'Auto Tipper 02'} | Route: Yelahanka Satellite Town
                      </p>
                    </div>

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
                      ● Route Active
                    </span>
                  </div>

                  {/* Embedded Map for route tracking */}
                  <div style={{ width: '100%', minWidth: 0 }}>
                    <PublicVehicleMap />
                  </div>
                </div>
              )}

              {/* TAB 5: PROFILE */}
              {activeTab === 'profile' && (
                <div style={{ maxWidth: '640px', margin: '0 auto', width: '100%' }}>
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: '18px',
                      padding: '2rem',
                      border: '1px solid #D5E3D7',
                      boxShadow: '0 4px 14px rgba(0,0,0,0.04)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '1.5rem',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                      <div
                        style={{
                          width: '64px',
                          height: '64px',
                          borderRadius: '16px',
                          backgroundColor: '#063321',
                          color: '#FFFFFF',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: '1.4rem',
                          fontWeight: 800,
                        }}
                      >
                        {currentUser?.email ? currentUser.email.slice(0, 2).toUpperCase() : 'PK'}
                      </div>

                      <div>
                        <h3 style={{ margin: 0, fontSize: '1.3rem', fontWeight: 750, color: '#183B2A' }}>
                          {currentUser?.full_name || currentUser?.email?.split('@')[0] || 'Pourakarmika'}
                        </h3>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '4px' }}>
                          <span
                            style={{
                              padding: '2px 8px',
                              borderRadius: '999px',
                              fontSize: '0.72rem',
                              fontWeight: 700,
                              backgroundColor: '#E8F5E9',
                              color: '#2E7D32',
                              textTransform: 'uppercase',
                            }}
                          >
                            {currentUser?.role === 'DRIVER' ? 'Collection Driver' : 'Sanitation Worker'}
                          </span>
                          <span style={{ fontSize: '0.8rem', color: '#64748B' }}>
                            Ward: {assignment?.ward_name || 'No ward assigned'}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', backgroundColor: '#F8FAFC', padding: '1.25rem', borderRadius: '12px', fontSize: '0.9rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: '#64748B' }}>Official Email:</span>
                        <strong style={{ color: '#1E293B' }}>{currentUser?.email}</strong>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: '#64748B' }}>Role Designation:</span>
                        <strong style={{ color: '#1E293B' }}>{currentUser?.role}</strong>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: '#64748B' }}>Account Status:</span>
                        <strong style={{ color: '#059669' }}>ACTIVE</strong>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: '#64748B' }}>Assigned Muster Station:</span>
                        <strong style={{ color: '#1E293B' }}>{assignment?.muster_point_name || 'No active muster station'}</strong>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {/* 3-Step Email OTP Attendance Modal */}
          {isModalOpen && (
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
              onClick={handleCloseModal}
            >
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '18px',
                  maxWidth: '480px',
                  width: '100%',
                  padding: '1.75rem',
                  boxShadow: '0 20px 40px rgba(0,0,0,0.2)',
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                  <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 750, color: '#183B2A' }}>
                    Shift Attendance Verification
                  </h3>
                  <button
                    type="button"
                    onClick={handleCloseModal}
                    style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#64748B' }}
                    aria-label="Close modal"
                  >
                    <X size={20} />
                  </button>
                </div>

                {otpError && (
                  <div style={{ marginBottom: '1rem' }}>
                    <Alert type="danger">{otpError}</Alert>
                  </div>
                )}

                {/* Step 1: Request OTP */}
                {modalStep === 'request' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1.15rem' }}>
                    <p style={{ margin: 0, fontSize: '0.88rem', color: '#4B5563', lineHeight: 1.4 }}>
                      Click below to generate a single-use 6-digit attendance code sent to your registered email (<strong>{currentUser?.email}</strong>).
                    </p>

                    <Button
                      type="button"
                      variant="primary"
                      onClick={handleRequestOtp}
                      disabled={isProcessing}
                      style={{ justifyContent: 'center', padding: '0.85rem' }}
                    >
                      {isProcessing ? (
                        <>
                          <Spinner size="sm" />
                          <span style={{ marginLeft: '0.5rem' }}>Sending Code...</span>
                        </>
                      ) : (
                        <>
                          <Send size={16} />
                          <span>Send 6-Digit OTP Code</span>
                        </>
                      )}
                    </Button>
                  </div>
                )}

                {/* Step 2: Verify OTP & GPS Check-In */}
                {modalStep === 'verify' && (
                  <form onSubmit={handleVerifyAndCheckIn} style={{ display: 'flex', flexDirection: 'column', gap: '1.15rem' }}>
                    {/* Development-Only OTP Display Callout */}
                    {devOtp && (
                      <div
                        style={{
                          backgroundColor: '#F0FDF4',
                          border: '1.5px solid #86EFAC',
                          borderRadius: '14px',
                          padding: '1rem 1.15rem',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '0.65rem',
                        }}
                      >
                        {/* Mode Tag */}
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '0.35rem',
                              fontSize: '0.72rem',
                              fontWeight: 800,
                              letterSpacing: '0.04em',
                              textTransform: 'uppercase',
                              backgroundColor: '#DCFCE7',
                              color: '#15803D',
                              padding: '3px 8px',
                              borderRadius: '6px',
                            }}
                          >
                            <KeyRound size={13} />
                            Local Development Mode
                          </span>
                          <span style={{ fontSize: '0.72rem', color: '#166534', fontWeight: 600 }}>
                            Simulated Email Code
                          </span>
                        </div>

                        {/* Code Display & Action Buttons */}
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            backgroundColor: '#FFFFFF',
                            padding: '0.6rem 0.9rem',
                            borderRadius: '10px',
                            border: '1px solid #BBF7D0',
                          }}
                        >
                          <div>
                            <div style={{ fontSize: '0.68rem', color: '#64748B', fontWeight: 600, textTransform: 'uppercase' }}>
                              Demonstration OTP
                            </div>
                            <div
                              style={{
                                fontFamily: 'Consolas, monospace',
                                fontSize: '1.65rem',
                                fontWeight: 850,
                                letterSpacing: '0.22em',
                                color: '#14532D',
                                lineHeight: 1.15,
                                marginTop: '2px',
                              }}
                            >
                              {devOtp}
                            </div>
                          </div>

                          <div style={{ display: 'flex', gap: '0.4rem' }}>
                            <button
                              type="button"
                              onClick={() => setOtpCode(devOtp)}
                              title="Auto-fill verification input"
                              style={{
                                padding: '0.45rem 0.75rem',
                                fontSize: '0.78rem',
                                fontWeight: 700,
                                backgroundColor: '#E0F2FE',
                                color: '#0369A1',
                                border: '1px solid #BAE6FD',
                                borderRadius: '8px',
                                cursor: 'pointer',
                              }}
                            >
                              Fill
                            </button>
                            <button
                              type="button"
                              onClick={handleCopyOtp}
                              title="Copy verification code to clipboard"
                              style={{
                                padding: '0.45rem 0.75rem',
                                fontSize: '0.78rem',
                                fontWeight: 700,
                                backgroundColor: copiedOtp ? '#DCFCE7' : '#F1F5F9',
                                color: copiedOtp ? '#166534' : '#334155',
                                border: `1px solid ${copiedOtp ? '#86EFAC' : '#CBD5E1'}`,
                                borderRadius: '8px',
                                cursor: 'pointer',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '0.35rem',
                                transition: 'all 0.15s ease-in-out',
                              }}
                            >
                              {copiedOtp ? <Check size={14} color="#166534" /> : <Copy size={14} />}
                              <span>{copiedOtp ? 'Copied!' : 'Copy Code'}</span>
                            </button>
                          </div>
                        </div>

                        {/* Live Expiry Countdown & Attempts */}
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            fontSize: '0.74rem',
                            color: '#166534',
                            paddingTop: '0.15rem',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                            <Clock size={13} color={countdownSeconds <= 30 ? '#DC2626' : '#166534'} />
                            <span style={{ fontWeight: countdownSeconds <= 30 ? 700 : 500, color: countdownSeconds <= 30 ? '#DC2626' : '#166534' }}>
                              Expires in: <strong>{formatCountdown(countdownSeconds)}</strong>
                            </span>
                          </div>
                          <div>
                            Remaining attempts: <strong style={{ color: remainingAttempts <= 1 ? '#DC2626' : '#166534' }}>{remainingAttempts} / 3</strong>
                          </div>
                        </div>

                        {/* Strict Development Disclaimer */}
                        <p style={{ margin: 0, fontSize: '0.7rem', color: '#15803D', lineHeight: 1.35, opacity: 0.9 }}>
                          * Local testing demonstration only. Production environments dispatch OTP exclusively via secure email delivery without API code disclosure.
                        </p>
                      </div>
                    )}

                    <p style={{ margin: 0, fontSize: '0.85rem', color: '#4B5563' }}>
                      Enter the 6-digit code received on <strong>{currentUser?.email}</strong>. Your device GPS location will be verified against the muster depot.
                    </p>

                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                        <label style={{ fontSize: '0.85rem', fontWeight: 700, color: '#1E293B' }}>
                          Verification Code (OTP)
                        </label>
                        {!devOtp && (
                          <span style={{ fontSize: '0.75rem', color: countdownSeconds <= 30 ? '#DC2626' : '#64748B' }}>
                            Expires in: {formatCountdown(countdownSeconds)}
                          </span>
                        )}
                      </div>
                      <input
                        type="text"
                        maxLength={6}
                        value={otpCode}
                        onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ''))}
                        placeholder="••••••"
                        style={{
                          width: '100%',
                          padding: '0.85rem',
                          textAlign: 'center',
                          fontSize: '1.4rem',
                          fontWeight: 800,
                          letterSpacing: '0.3em',
                          borderRadius: '10px',
                          border: '2px solid #CBD5E1',
                          boxSizing: 'border-box',
                        }}
                      />
                    </div>

                    <Button
                      type="submit"
                      variant="primary"
                      disabled={isProcessing || otpCode.length !== 6 || countdownSeconds === 0}
                      style={{ justifyContent: 'center', padding: '0.85rem' }}
                    >
                      {isProcessing ? (
                        <>
                          <Spinner size="sm" />
                          <span style={{ marginLeft: '0.5rem' }}>Verifying & Checking In...</span>
                        </>
                      ) : (
                        <>
                          <LockKeyhole size={16} />
                          <span>Verify & Check In</span>
                        </>
                      )}
                    </Button>

                    <div style={{ display: 'flex', justifyContent: 'center', marginTop: '0.2rem' }}>
                      <button
                        type="button"
                        onClick={handleRequestOtp}
                        disabled={isProcessing}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: '#065F46',
                          fontSize: '0.8rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                          textDecoration: 'underline',
                          padding: '0.2rem 0.5rem',
                        }}
                      >
                        {isProcessing ? 'Sending new code...' : 'Resend verification code'}
                      </button>
                    </div>
                  </form>
                )}

                {/* Step 3: Success Screen */}
                {modalStep === 'success' && checkInResult && (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: '1rem', padding: '1rem 0' }}>
                    <div
                      style={{
                        width: '56px',
                        height: '56px',
                        borderRadius: '50%',
                        backgroundColor: '#D1FAE5',
                        color: '#065F46',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      <CheckCircle2 size={32} />
                    </div>

                    <h4 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 750, color: '#183B2A' }}>
                      Attendance Verified!
                    </h4>

                    <p style={{ margin: 0, fontSize: '0.88rem', color: '#4B5563' }}>
                      Status: <strong>{checkInResult.status}</strong>. Recorded distance: {Math.round(checkInResult.distance_meters)}m from muster station.
                    </p>

                    <Button
                      type="button"
                      variant="primary"
                      onClick={handleCloseModal}
                      style={{ width: '100%', justifyContent: 'center', marginTop: '0.5rem' }}
                    >
                      Done
                    </Button>
                  </div>
                )}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
};
