import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  ArrowRight,
  Bell,
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
import {
  fetchWorkerSchedule,
  fetchWorkerRoute,
  fetchWorkerAttendanceHistory,
  WorkerScheduleResponse,
  WorkerRouteResponse,
} from '../../api/worker';
import {
  fetchNotifications,
  fetchUnreadCount,
  markNotificationAsRead,
  markAllNotificationsAsRead,
  NotificationItem,
} from '../../api/notifications';
import type { User as UserType } from '../../types';
import '../../styles/citizen-dashboard.css';

export type WorkerTab =
  | 'dashboard'
  | 'schedule'
  | 'route'
  | 'history'
  | 'notifications'
  | 'profile'
  | 'attendance'
  | 'tasks'
  | 'vehicle';

export const WorkerDashboard: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [currentUser, setCurrentUser] = useState<UserType | null>(null);
  const [assignment, setAssignment] = useState<WorkerAssignment | null>(null);
  const [todayRecord, setTodayRecord] = useState<AttendanceDailyItem | null>(null);
  const [scheduleData, setScheduleData] = useState<WorkerScheduleResponse | null>(null);
  const [routeData, setRouteData] = useState<WorkerRouteResponse | null>(null);
  const [historyRecords, setHistoryRecords] = useState<AttendanceDailyItem[]>([]);
  const [notificationsList, setNotificationsList] = useState<NotificationItem[]>([]);
  const [unreadNotificationCount, setUnreadNotificationCount] = useState<number>(0);
  const [isLoadingSubTab, setIsLoadingSubTab] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<WorkerTab>('dashboard');

  useEffect(() => {
    const tabParam = searchParams.get('tab') as WorkerTab | null;
    const validTabs: WorkerTab[] = [
      'dashboard',
      'schedule',
      'route',
      'history',
      'notifications',
      'profile',
      'attendance',
      'tasks',
      'vehicle',
    ];
    if (tabParam && validTabs.includes(tabParam) && tabParam !== activeTab) {
      setActiveTab(tabParam);
    }
  }, [searchParams, activeTab]);

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

      const [assignRes, attRes, schedRes, unreadRes] = await Promise.all([
        getWorkerAssignment().catch(() => null),
        getWorkerTodayAttendance().catch(() => null),
        fetchWorkerSchedule().catch(() => null),
        fetchUnreadCount().catch(() => 0),
      ]);
      setAssignment(assignRes);
      setTodayRecord(attRes);
      setScheduleData(schedRes);
      setUnreadNotificationCount(unreadRes);
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

  // Tab content loader
  useEffect(() => {
    const loadTabContent = async () => {
      if (activeTab === 'schedule') {
        setIsLoadingSubTab(true);
        try {
          const res = await fetchWorkerSchedule();
          setScheduleData(res);
        } catch (e) {
          console.error(e);
        } finally {
          setIsLoadingSubTab(false);
        }
      } else if (activeTab === 'route') {
        setIsLoadingSubTab(true);
        try {
          const res = await fetchWorkerRoute();
          setRouteData(res);
        } catch (e) {
          console.error(e);
        } finally {
          setIsLoadingSubTab(false);
        }
      } else if (activeTab === 'history') {
        setIsLoadingSubTab(true);
        try {
          const res = await fetchWorkerAttendanceHistory(30);
          setHistoryRecords(res);
        } catch (e) {
          console.error(e);
        } finally {
          setIsLoadingSubTab(false);
        }
      } else if (activeTab === 'notifications') {
        setIsLoadingSubTab(true);
        try {
          const res = await fetchNotifications('ALL', 50);
          setNotificationsList(res.items);
          setUnreadNotificationCount(res.unread_count);
        } catch (e) {
          console.error(e);
        } finally {
          setIsLoadingSubTab(false);
        }
      }
    };
    loadTabContent();
  }, [activeTab]);

  const handleMarkNotificationRead = async (id: string) => {
    try {
      await markNotificationAsRead(id);
      setNotificationsList((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true, read_at: new Date().toISOString() } : n))
      );
      setUnreadNotificationCount((prev) => Math.max(0, prev - 1));
    } catch (e) {
      console.error(e);
    }
  };

  const handleMarkAllNotificationsRead = async () => {
    try {
      await markAllNotificationsAsRead();
      setNotificationsList((prev) =>
        prev.map((n) => ({ ...n, is_read: true, read_at: new Date().toISOString() }))
      );
      setUnreadNotificationCount(0);
    } catch (e) {
      console.error(e);
    }
  };

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
      let acc: number | undefined;

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
        acc = position.coords.accuracy;
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
        accuracy_meters: acc,
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
      let acc: number | undefined;
      try {
        const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 8000 });
        });
        lat = pos.coords.latitude;
        lon = pos.coords.longitude;
        acc = pos.coords.accuracy;
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
        accuracy_meters: acc,
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
          if (['dashboard', 'schedule', 'route', 'history', 'notifications', 'profile', 'attendance', 'tasks', 'vehicle'].includes(tab)) {
            const nextTab = tab as WorkerTab;
            setActiveTab(nextTab);
            setSearchParams({ tab: nextTab });
          }
        }}
        notificationCount={unreadNotificationCount}
      />

      {/* Main Content Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflowX: 'hidden' }}>
        {/* Unified Dashboard Band with Vidhana Soudha background */}
        <section className="nc-dashboard-band" id="home">
          <CitizenHeader
            selectedWardName={assignment?.ward_name ? `Ward: ${assignment.ward_name}` : 'Bengaluru (Field Operations)'}
          />

          <div className="nc-dashboard-band-inner">
            {(() => {
              const hour = new Date().getHours();
              const greetingPrefix = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
              const firstName = currentUser?.full_name ? currentUser.full_name.trim().split(' ')[0] : 'Pourakarmika';
              return (
                <CitizenBanner
                  user={currentUser}
                  userName={firstName}
                  isLoading={isLoading}
                  titlePrefix={greetingPrefix}
                  subtitle="Your daily assignment, muster roll-call, and shift attendance in one place."
                  roleBadge={currentUser?.role === 'DRIVER' ? 'Collection Driver' : 'Pourakarmika'}
                  showBirds={false}
                />
              );
            })()}

            {/* 4 Daily Summary Cards matching civic design system */}
            <div className="nc-summary-overview" aria-label="Pourakarmika daily metrics">
              <div className="nc-summary-grid">
                {/* 1. Today's Assignment */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => {
                    setActiveTab('schedule');
                    setSearchParams({ tab: 'schedule' });
                  }}
                  role="button"
                  tabIndex={0}
                  title="Click to view muster depot & shift schedule"
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
                  onClick={() => {
                    setActiveTab('history');
                    setSearchParams({ tab: 'history' });
                  }}
                  role="button"
                  tabIndex={0}
                  title="Click to open attendance history"
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

                {/* 3. Scheduled Shift Hours */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => {
                    setActiveTab('schedule');
                    setSearchParams({ tab: 'schedule' });
                  }}
                  role="button"
                  tabIndex={0}
                  title="Click to view weekly schedule"
                >
                  <span className="nc-summary-icon">
                    <Clock size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>
                      {scheduleData?.shift_start_time
                        ? `${scheduleData.shift_start_time} - ${scheduleData.shift_end_time}`
                        : '07:00 - 14:00'}
                    </strong>
                    <span className="nc-summary-label">Today's Shift Hours</span>
                    <span className="nc-summary-note" style={{ color: '#2E7D32' }}>
                      {scheduleData?.today_is_workday !== false ? 'Scheduled Workday' : 'Day Off'} →
                    </span>
                  </span>
                </article>

                {/* 4. Duration Worked */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => {
                    setActiveTab('history');
                    setSearchParams({ tab: 'history' });
                  }}
                  role="button"
                  tabIndex={0}
                  title="Click to view work duration details"
                >
                  <span className="nc-summary-icon">
                    <CalendarCheck size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>
                      {todayRecord?.duration_minutes !== null && todayRecord?.duration_minutes !== undefined
                        ? `${Math.floor(todayRecord.duration_minutes / 60)}h ${todayRecord.duration_minutes % 60}m`
                        : isCheckedIn
                        ? 'On Duty'
                        : '—'}
                    </strong>
                    <span className="nc-summary-label">Duration Worked</span>
                    <span className="nc-summary-note" style={{ color: '#2E7D32' }}>
                      {isCheckedOut
                        ? 'Shift Completed'
                        : isCheckedIn
                        ? '● In Progress'
                        : 'Shift Not Started'}
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
                  {/* Enhanced Mobile-First Shift Status Card */}
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: '16px',
                      padding: '1.5rem 1.75rem',
                      border: '1px solid #D5E3D7',
                      boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '1.25rem',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                          <span
                            style={{
                              padding: '4px 12px',
                              borderRadius: '999px',
                              fontSize: '0.8rem',
                              fontWeight: 750,
                              backgroundColor: isCheckedOut
                                ? '#D1FAE5'
                                : isCheckedIn
                                ? todayRecord?.status === 'PRESENT'
                                  ? '#D1FAE5'
                                  : '#FEF3C7'
                                : scheduleData?.window_status === 'ON_TIME'
                                ? '#DCFCE7'
                                : scheduleData?.window_status === 'GRACE'
                                ? '#FEF3C7'
                                : scheduleData?.window_status === 'LATE_EXCEPTION'
                                ? '#FEE2E2'
                                : '#F1F5F9',
                              color: isCheckedOut
                                ? '#065F46'
                                : isCheckedIn
                                ? todayRecord?.status === 'PRESENT'
                                  ? '#065F46'
                                  : '#92400E'
                                : scheduleData?.window_status === 'ON_TIME'
                                ? '#15803D'
                                : scheduleData?.window_status === 'GRACE'
                                ? '#B45309'
                                : scheduleData?.window_status === 'LATE_EXCEPTION'
                                ? '#B91C1C'
                                : '#475569',
                            }}
                          >
                            {isCheckedOut
                              ? 'Shift Completed'
                              : isCheckedIn
                              ? todayRecord?.status === 'PRESENT'
                                ? 'On Duty (Verified)'
                                : 'Exception Review Pending'
                              : scheduleData?.window_status === 'ON_TIME'
                              ? 'Check-In Open (On-Time)'
                              : scheduleData?.window_status === 'GRACE'
                              ? 'Grace Period Active (+15m)'
                              : scheduleData?.window_status === 'LATE_EXCEPTION'
                              ? 'Window Expired (Late Exception)'
                              : scheduleData?.window_status === 'NOT_OPEN'
                              ? 'Window Not Open'
                              : 'Shift Closed'}
                          </span>
                          <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 800, color: '#183B2A' }}>
                            {isCheckedOut
                              ? 'Today’s Shift Concluded'
                              : isCheckedIn
                              ? 'You are Active on Field Duty'
                              : 'Daily Muster Roll-Call Check-In'}
                          </h3>
                        </div>
                        <p style={{ margin: '0.35rem 0 0', fontSize: '0.88rem', color: '#5A7565' }}>
                          {isCheckedOut
                            ? `Shift successfully recorded. Total duration worked: ${Math.floor((todayRecord?.duration_minutes || 0) / 60)}h ${(todayRecord?.duration_minutes || 0) % 60}m.`
                            : isCheckedIn
                            ? `Checked in at ${new Date(todayRecord?.check_in_at || '').toLocaleTimeString()} at ${assignment?.muster_point_name || 'Assigned Depot'}.`
                            : scheduleData?.window_message || 'Verify presence at assigned muster depot via Email OTP and GPS coordinates.'}
                        </p>
                      </div>

                      {/* Large Touch Action Buttons (>= 48px target) */}
                      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                        {!isCheckedIn ? (
                          <Button
                            type="button"
                            variant="primary"
                            onClick={openAttendanceModal}
                            style={{
                              minHeight: '48px',
                              minWidth: '48px',
                              padding: '12px 24px',
                              fontSize: '0.95rem',
                              fontWeight: 700,
                              boxShadow: '0 4px 14px rgba(6,95,70,0.25)',
                            }}
                          >
                            <ShieldCheck size={20} />
                            <span>Mark Attendance (Email OTP & GPS)</span>
                          </Button>
                        ) : !isCheckedOut ? (
                          <Button
                            type="button"
                            variant="outline"
                            onClick={handleCheckOut}
                            disabled={isCheckingOut}
                            style={{
                              minHeight: '48px',
                              minWidth: '48px',
                              padding: '12px 24px',
                              fontSize: '0.95rem',
                              fontWeight: 700,
                              borderColor: '#DC2626',
                              color: '#DC2626',
                            }}
                          >
                            {isCheckingOut ? (
                              <>
                                <Spinner size="sm" />
                                <span style={{ marginLeft: '0.4rem' }}>Recording Check-Out...</span>
                              </>
                            ) : (
                              <>
                                <Clock size={20} />
                                <span>Record Shift Check-Out</span>
                              </>
                            )}
                          </Button>
                        ) : (
                          <div
                            style={{
                              minHeight: '48px',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '0.5rem',
                              padding: '10px 20px',
                              borderRadius: '12px',
                              backgroundColor: '#E8F5E9',
                              color: '#2E7D32',
                              fontWeight: 800,
                              fontSize: '0.95rem',
                            }}
                          >
                            <CheckCircle2 size={20} />
                            <span>
                              Shift Concluded — Duration: {Math.floor((todayRecord?.duration_minutes || 0) / 60)}h{' '}
                              {(todayRecord?.duration_minutes || 0) % 60}m
                            </span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Shift & Window Timing Grid */}
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                        gap: '1rem',
                        backgroundColor: '#F8FAFC',
                        padding: '1rem 1.25rem',
                        borderRadius: '12px',
                        fontSize: '0.86rem',
                      }}
                    >
                      <div>
                        <div style={{ color: '#64748B', fontWeight: 600 }}>Shift Hours</div>
                        <strong style={{ color: '#1E293B', fontSize: '0.95rem' }}>
                          {scheduleData?.shift_start_time || '07:00'} – {scheduleData?.shift_end_time || '14:00'}
                        </strong>
                      </div>
                      <div>
                        <div style={{ color: '#64748B', fontWeight: 600 }}>Check-In Window</div>
                        <strong style={{ color: '#1E293B', fontSize: '0.95rem' }}>
                          {scheduleData?.check_in_start_time || '06:45'} – {scheduleData?.check_in_end_time || '07:30'}
                        </strong>
                      </div>
                      <div>
                        <div style={{ color: '#64748B', fontWeight: 600 }}>Grace Period</div>
                        <strong style={{ color: '#1E293B', fontSize: '0.95rem' }}>
                          +{scheduleData?.grace_period_minutes ?? 15} minutes
                        </strong>
                      </div>
                      <div>
                        <div style={{ color: '#64748B', fontWeight: 600 }}>Assigned Route</div>
                        <strong style={{ color: '#0369A1', fontSize: '0.95rem' }}>
                          {scheduleData?.route_name || assignment?.ward_name || 'Ward General'}
                        </strong>
                      </div>
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
                            {assignment?.ward_name ? `BBMP Ward — ${assignment.ward_name}` : 'Ward Depot'}
                          </div>
                        </div>
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', backgroundColor: '#F8FAFC', padding: '1rem', borderRadius: '12px', fontSize: '0.88rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Depot Name:</span>
                          <strong style={{ color: '#1E293B' }}>{assignment?.muster_point_name || 'Ward Muster Depot'}</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Geofence Radius:</span>
                          <strong style={{ color: '#1E293B' }}>{assignment?.geofence_radius_meters || 150} meters</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Assigned Ward:</span>
                          <strong style={{ color: '#1E293B' }}>{assignment?.ward_name || 'Bengaluru'}</strong>
                        </div>
                      </div>

                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                          setActiveTab('schedule');
                          setSearchParams({ tab: 'schedule' });
                        }}
                        style={{ width: '100%', justifyContent: 'center', fontSize: '0.85rem' }}
                      >
                        <span>View Shift Schedule & Overrides</span>
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
                            Assigned Route & Fleet
                          </h4>
                          <div style={{ fontSize: '0.78rem', color: '#5A7565' }}>
                            Daily Waste Collection Route
                          </div>
                        </div>
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', backgroundColor: '#F8FAFC', padding: '1rem', borderRadius: '12px', fontSize: '0.88rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Route Code:</span>
                          <strong style={{ color: '#1E293B' }}>
                            {scheduleData?.route_name || (assignment?.ward_name ? `${assignment.ward_name} Collection Route` : 'Ward General Route')}
                          </strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Vehicle Type:</span>
                          <strong style={{ color: '#1E293B' }}>
                            {currentUser?.role === 'DRIVER' ? 'Compactor Truck' : 'Auto Tipper (Door-to-Door)'}
                          </strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#64748B' }}>Shift Turnout:</span>
                          <strong style={{ color: isCheckedIn ? '#059669' : '#D97706' }}>
                            {isCheckedIn ? 'Checked In' : 'Pending Roll-Call'}
                          </strong>
                        </div>
                      </div>

                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                          setActiveTab('route');
                          setSearchParams({ tab: 'route' });
                        }}
                        style={{ width: '100%', justifyContent: 'center', fontSize: '0.85rem' }}
                      >
                        <span>Inspect Route Map & Stops</span>
                        <ArrowRight size={15} />
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 2: MY SCHEDULE */}
              {activeTab === 'schedule' && (
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
                      <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 750, color: '#183B2A' }}>
                        Weekly Recurring Schedule & Shift Rules
                      </h3>
                      <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                        Enforced muster depot roll-call timetable and approved schedule overrides.
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => fetchWorkerSchedule().then(setScheduleData)}
                      style={{ fontSize: '0.82rem', padding: '6px 12px' }}
                    >
                      <RefreshCw size={14} />
                      <span>Refresh Schedule</span>
                    </Button>
                  </div>

                  {isLoadingSubTab ? (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: '3rem' }}>
                      <Spinner size="md" />
                    </div>
                  ) : (
                    <>
                      {/* Active Recurring Schedule Details */}
                      <div
                        style={{
                          backgroundColor: '#FFFFFF',
                          borderRadius: '16px',
                          border: '1px solid #D5E3D7',
                          padding: '1.5rem',
                          boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '1.25rem',
                        }}
                      >
                        <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 750, color: '#183B2A' }}>
                          Standard Recurring Weekly Timetable
                        </h4>

                        {/* Working Days */}
                        <div>
                          <div style={{ fontSize: '0.82rem', color: '#64748B', fontWeight: 600, marginBottom: '0.5rem' }}>
                            Active Working Days (Weekly Duty)
                          </div>
                          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                            {[
                              { day: 1, label: 'Mon' },
                              { day: 2, label: 'Tue' },
                              { day: 3, label: 'Wed' },
                              { day: 4, label: 'Thu' },
                              { day: 5, label: 'Fri' },
                              { day: 6, label: 'Sat' },
                              { day: 7, label: 'Sun' },
                            ].map(({ day, label }) => {
                              const isActive = (scheduleData?.days_of_week || [1, 2, 3, 4, 5, 6]).includes(day);
                              return (
                                <span
                                  key={day}
                                  style={{
                                    padding: '6px 14px',
                                    borderRadius: '8px',
                                    fontSize: '0.84rem',
                                    fontWeight: 700,
                                    backgroundColor: isActive ? '#ECFDF5' : '#F1F5F9',
                                    color: isActive ? '#065F46' : '#94A3B8',
                                    border: isActive ? '1px solid #A7F3D0' : '1px solid #E2E8F0',
                                  }}
                                >
                                  {label} {isActive ? '✓' : '—'}
                                </span>
                              );
                            })}
                          </div>
                        </div>

                        {/* Schedule Metric Grid */}
                        <div
                          style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                            gap: '1rem',
                            backgroundColor: '#F8FAFC',
                            padding: '1.25rem',
                            borderRadius: '12px',
                          }}
                        >
                          <div>
                            <div style={{ fontSize: '0.78rem', color: '#64748B', fontWeight: 600 }}>Shift Start – End</div>
                            <div style={{ fontSize: '1.15rem', fontWeight: 800, color: '#1E293B', marginTop: '2px' }}>
                              {scheduleData?.shift_start_time || '07:00'} – {scheduleData?.shift_end_time || '14:00'}
                            </div>
                            <div style={{ fontSize: '0.74rem', color: '#059669', marginTop: '2px' }}>Official daily working hours</div>
                          </div>

                          <div>
                            <div style={{ fontSize: '0.78rem', color: '#64748B', fontWeight: 600 }}>Check-In Window</div>
                            <div style={{ fontSize: '1.15rem', fontWeight: 800, color: '#1E293B', marginTop: '2px' }}>
                              {scheduleData?.check_in_start_time || '06:45'} – {scheduleData?.check_in_end_time || '07:30'}
                            </div>
                            <div style={{ fontSize: '0.74rem', color: '#0369A1', marginTop: '2px' }}>
                              Grace: +{scheduleData?.grace_period_minutes ?? 15} mins
                            </div>
                          </div>

                          <div>
                            <div style={{ fontSize: '0.78rem', color: '#64748B', fontWeight: 600 }}>Muster Point Geofence</div>
                            <div style={{ fontSize: '1.15rem', fontWeight: 800, color: '#1E293B', marginTop: '2px' }}>
                              150 meters
                            </div>
                            <div style={{ fontSize: '0.74rem', color: '#64748B', marginTop: '2px' }}>Strict GPS verification radius</div>
                          </div>
                        </div>
                      </div>

                      {/* Upcoming Schedule Overrides Table */}
                      <div
                        style={{
                          backgroundColor: '#FFFFFF',
                          borderRadius: '16px',
                          border: '1px solid #D5E3D7',
                          padding: '1.5rem',
                          boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                        }}
                      >
                        <h4 style={{ margin: '0 0 1rem', fontSize: '1.05rem', fontWeight: 750, color: '#183B2A' }}>
                          Approved Date-Specific Schedule Overrides
                        </h4>

                        {!scheduleData?.upcoming_overrides || scheduleData.upcoming_overrides.length === 0 ? (
                          <div style={{ textAlign: 'center', padding: '2rem', color: '#64748B', fontSize: '0.9rem' }}>
                            No date-specific overrides recorded. Standard weekly recurring schedule applies.
                          </div>
                        ) : (
                          <div style={{ overflowX: 'auto' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.88rem' }}>
                              <thead>
                                <tr style={{ backgroundColor: '#F8FAFC', borderBottom: '1px solid #E2E8F0', color: '#475569' }}>
                                  <th style={{ padding: '0.75rem 1rem', fontWeight: 700 }}>Date</th>
                                  <th style={{ padding: '0.75rem 1rem', fontWeight: 700 }}>Override Type</th>
                                  <th style={{ padding: '0.75rem 1rem', fontWeight: 700 }}>Justification / Reason</th>
                                </tr>
                              </thead>
                              <tbody>
                                {scheduleData.upcoming_overrides.map((ov, idx) => (
                                  <tr key={idx} style={{ borderBottom: '1px solid #F1F5F9' }}>
                                    <td style={{ padding: '0.75rem 1rem', fontWeight: 600, color: '#1E293B' }}>
                                      {ov.override_date}
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem' }}>
                                      <span
                                        style={{
                                          padding: '2px 8px',
                                          borderRadius: '999px',
                                          fontSize: '0.75rem',
                                          fontWeight: 700,
                                          backgroundColor:
                                            ov.override_type === 'DAY_OFF'
                                              ? '#E0F2FE'
                                              : ov.override_type === 'HOLIDAY'
                                              ? '#FEF3C7'
                                              : ov.override_type === 'LEAVE'
                                              ? '#FEE2E2'
                                              : '#ECFDF5',
                                          color:
                                            ov.override_type === 'DAY_OFF'
                                              ? '#0369A1'
                                              : ov.override_type === 'HOLIDAY'
                                              ? '#92400E'
                                              : ov.override_type === 'LEAVE'
                                              ? '#B91C1C'
                                              : '#065F46',
                                        }}
                                      >
                                        {ov.override_type}
                                      </span>
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem', color: '#4B5563' }}>
                                      {ov.reason || 'Supervisor authorized override'}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* TAB 3: MY ROUTE */}
              {activeTab === 'route' && (
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
                      <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 750, color: '#183B2A' }}>
                        Assigned Waste Collection Route
                      </h3>
                      <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                        Route: <strong>{routeData?.route_name || scheduleData?.route_name || 'Ward General Route'}</strong> ({routeData?.ward_name || assignment?.ward_name || 'BBMP Ward'})
                      </p>
                    </div>

                    <span
                      style={{
                        padding: '4px 12px',
                        borderRadius: '999px',
                        backgroundColor: '#E8F5E9',
                        color: '#2E7D32',
                        fontSize: '0.78rem',
                        fontWeight: 700,
                      }}
                    >
                      ● Active Daily Route
                    </span>
                  </div>

                  {/* Embedded Route Map */}
                  <div style={{ width: '100%', minWidth: 0, borderRadius: '16px', overflow: 'hidden' }}>
                    <PublicVehicleMap />
                  </div>

                  {/* Route Stops / Waypoints List */}
                  {routeData?.stops && routeData.stops.length > 0 && (
                    <div
                      style={{
                        backgroundColor: '#FFFFFF',
                        borderRadius: '16px',
                        border: '1px solid #D5E3D7',
                        padding: '1.5rem',
                      }}
                    >
                      <h4 style={{ margin: '0 0 1rem', fontSize: '1.05rem', fontWeight: 750, color: '#183B2A' }}>
                        Scheduled Collection Stops ({routeData.stops.length})
                      </h4>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        {routeData.stops.map((stop) => (
                          <div
                            key={stop.id}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              padding: '0.75rem 1rem',
                              backgroundColor: '#F8FAFC',
                              borderRadius: '10px',
                              border: '1px solid #E2E8F0',
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                              <span
                                style={{
                                  width: '28px',
                                  height: '28px',
                                  borderRadius: '50%',
                                  backgroundColor: '#E0F2FE',
                                  color: '#0369A1',
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'center',
                                  fontWeight: 800,
                                  fontSize: '0.8rem',
                                }}
                              >
                                {stop.sequence_order}
                              </span>
                              <span style={{ fontWeight: 600, color: '#1E293B', fontSize: '0.9rem' }}>
                                {stop.name}
                              </span>
                            </div>
                            <span style={{ fontSize: '0.8rem', color: '#64748B' }}>
                              {stop.latitude.toFixed(4)}° N, {stop.longitude.toFixed(4)}° E
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* TAB 4: ATTENDANCE HISTORY */}
              {activeTab === 'history' && (
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
                      <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 750, color: '#183B2A' }}>
                        Pourakarmika Attendance History (Past 30 Days)
                      </h3>
                      <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                        Official muster check-in, duration worked, and GPS verification audit trail.
                      </p>
                    </div>

                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => fetchWorkerAttendanceHistory(30).then(setHistoryRecords)}
                      style={{ fontSize: '0.82rem', padding: '6px 12px' }}
                    >
                      <RefreshCw size={14} />
                      <span>Refresh History</span>
                    </Button>
                  </div>

                  {isLoadingSubTab ? (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: '3rem' }}>
                      <Spinner size="md" />
                    </div>
                  ) : historyRecords.length === 0 ? (
                    <div
                      style={{
                        backgroundColor: '#FFFFFF',
                        borderRadius: '16px',
                        border: '1px solid #D5E3D7',
                        padding: '3rem 2rem',
                        textAlign: 'center',
                        color: '#64748B',
                      }}
                    >
                      <CalendarCheck size={40} style={{ margin: '0 auto 0.75rem', opacity: 0.5 }} />
                      <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#183B2A' }}>
                        No attendance records recorded yet
                      </div>
                      <p style={{ margin: '0.25rem 0 0', fontSize: '0.85rem' }}>
                        Your verified daily muster check-ins will appear here with calculated shift duration.
                      </p>
                    </div>
                  ) : (
                    <div
                      style={{
                        backgroundColor: '#FFFFFF',
                        borderRadius: '16px',
                        border: '1px solid #D5E3D7',
                        overflowX: 'auto',
                        boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                      }}
                    >
                      <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.88rem' }}>
                        <thead>
                          <tr style={{ backgroundColor: '#F8FAFC', borderBottom: '1px solid #E2E8F0', color: '#475569' }}>
                            <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Date</th>
                            <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Check-In</th>
                            <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Check-Out</th>
                            <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Duration Worked</th>
                            <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Muster Distance</th>
                            <th style={{ padding: '0.85rem 1rem', fontWeight: 700, textAlign: 'right' }}>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {historyRecords.map((rec) => {
                            const durHrs = rec.duration_minutes ? Math.floor(rec.duration_minutes / 60) : 0;
                            const durMins = rec.duration_minutes ? rec.duration_minutes % 60 : 0;
                            return (
                              <tr key={rec.id} style={{ borderBottom: '1px solid #F1F5F9' }}>
                                <td style={{ padding: '0.85rem 1rem', fontWeight: 700, color: '#1E293B' }}>
                                  {rec.attendance_date}
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
                                <td style={{ padding: '0.85rem 1rem', color: '#183B2A', fontWeight: 700 }}>
                                  {rec.duration_minutes !== null && rec.duration_minutes !== undefined ? (
                                    <span style={{ backgroundColor: '#F0FDF4', padding: '3px 8px', borderRadius: '6px', border: '1px solid #DCFCE7' }}>
                                      {durHrs}h {durMins}m
                                    </span>
                                  ) : rec.check_in_at ? (
                                    <span style={{ color: '#059669', fontSize: '0.8rem' }}>On Duty</span>
                                  ) : (
                                    '—'
                                  )}
                                </td>
                                <td style={{ padding: '0.85rem 1rem', color: '#4B5563' }}>
                                  {rec.check_in_distance_meters !== null && rec.check_in_distance_meters !== undefined
                                    ? `${Math.round(rec.check_in_distance_meters)}m`
                                    : '—'}
                                </td>
                                <td style={{ padding: '0.85rem 1rem', textAlign: 'right' }}>
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
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* TAB 5: NOTIFICATIONS */}
              {activeTab === 'notifications' && (
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
                      <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 750, color: '#183B2A' }}>
                        Notification Center
                      </h3>
                      <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                        Shift assignments, exception alerts, and supervisor review updates.
                      </p>
                    </div>

                    <div style={{ display: 'flex', gap: '0.75rem' }}>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={handleMarkAllNotificationsRead}
                        style={{ fontSize: '0.82rem', padding: '6px 12px' }}
                      >
                        <Check size={14} />
                        <span>Mark All as Read</span>
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => fetchNotifications('ALL', 50).then((res) => {
                          setNotificationsList(res.items);
                          setUnreadNotificationCount(res.unread_count);
                        })}
                        style={{ fontSize: '0.82rem', padding: '6px 12px' }}
                      >
                        <RefreshCw size={14} />
                        <span>Refresh</span>
                      </Button>
                    </div>
                  </div>

                  {isLoadingSubTab ? (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: '3rem' }}>
                      <Spinner size="md" />
                    </div>
                  ) : notificationsList.length === 0 ? (
                    <div
                      style={{
                        backgroundColor: '#FFFFFF',
                        borderRadius: '16px',
                        border: '1px solid #D5E3D7',
                        padding: '3rem 2rem',
                        textAlign: 'center',
                        color: '#64748B',
                      }}
                    >
                      <Bell size={40} style={{ margin: '0 auto 0.75rem', opacity: 0.5 }} />
                      <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#183B2A' }}>No notifications</div>
                      <p style={{ margin: '0.25rem 0 0', fontSize: '0.85rem' }}>
                        You're all caught up! New schedule changes and attendance notifications will appear here.
                      </p>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                      {notificationsList.map((n) => (
                        <div
                          key={n.id}
                          style={{
                            backgroundColor: n.is_read ? '#FFFFFF' : '#F0FDF4',
                            border: n.is_read ? '1px solid #E2E8F0' : '1.5px solid #86EFAC',
                            borderRadius: '14px',
                            padding: '1.1rem 1.4rem',
                            display: 'flex',
                            alignItems: 'flex-start',
                            justifyContent: 'space-between',
                            gap: '1rem',
                            boxShadow: '0 2px 6px rgba(0,0,0,0.02)',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
                            <div
                              style={{
                                width: '36px',
                                height: '36px',
                                borderRadius: '10px',
                                backgroundColor: n.is_read ? '#F1F5F9' : '#DCFCE7',
                                color: n.is_read ? '#64748B' : '#15803D',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                flexShrink: 0,
                                marginTop: '2px',
                              }}
                            >
                              <Bell size={18} />
                            </div>
                            <div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <h4 style={{ margin: 0, fontSize: '0.96rem', fontWeight: 750, color: '#1E293B' }}>
                                  {n.title}
                                </h4>
                                {!n.is_read && (
                                  <span
                                    style={{
                                      width: '8px',
                                      height: '8px',
                                      borderRadius: '50%',
                                      backgroundColor: '#059669',
                                    }}
                                  />
                                )}
                              </div>
                              <p style={{ margin: '0.25rem 0 0', fontSize: '0.86rem', color: '#4B5563', lineHeight: 1.4 }}>
                                {n.message}
                              </p>
                              <div style={{ fontSize: '0.75rem', color: '#94A3B8', marginTop: '0.35rem' }}>
                                {new Date(n.created_at).toLocaleString('en-IN', {
                                  dateStyle: 'medium',
                                  timeStyle: 'short',
                                })}
                              </div>
                            </div>
                          </div>

                          {!n.is_read && (
                            <Button
                              type="button"
                              variant="outline"
                              onClick={() => handleMarkNotificationRead(n.id)}
                              style={{ fontSize: '0.75rem', padding: '4px 8px', flexShrink: 0 }}
                            >
                              Mark Read
                            </Button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* TAB 6: MY PROFILE */}
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
                            {currentUser?.role === 'DRIVER' ? 'Collection Driver' : 'Sanitation Worker (Pourakarmika)'}
                          </span>
                          <span style={{ fontSize: '0.8rem', color: '#64748B' }}>
                            Ward: {assignment?.ward_name || 'No ward assigned'}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', backgroundColor: '#F8FAFC', padding: '1.25rem', borderRadius: '12px', fontSize: '0.9rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: '#64748B' }}>Official Staff ID:</span>
                        <strong style={{ color: currentUser?.official_id ? '#0369A1' : '#92400E' }}>
                          {currentUser?.official_id || 'BBMP-SW-042'}
                        </strong>
                      </div>
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
                        <span style={{ color: '#64748B' }}>Assigned Muster Depot:</span>
                        <strong style={{ color: '#1E293B' }}>{assignment?.muster_point_name || 'Yelahanka Satellite Town Depot'}</strong>
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
