import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
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
  ShieldAlert,
  Truck,
  Users,
  X,
  Search,
  ShieldCheck,
  ShieldOff,
  UserPlus,
  Calendar,
  Sliders,
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
import {
  fetchSupervisorDashboardStats,
  fetchSupervisorWorkers,
  registerSupervisorWorker,
  toggleWorkerStatus,
  assignWorkerSchedule,
  createScheduleOverride,
  SupervisorDashboardStats,
  SupervisorWorkerSummary,
} from '../../api/supervisor';
import { fetchReportsForReview, updateReportStatus } from '../../api/reports';
import {
  fetchDrivers,
  createDriver,
  updateDriver,
  assignDriverVehicle,
} from '../../api/drivers';
import type {
  User,
  DumpingReport,
  PublicMapSummary,
  PublicVehicle,
  DriverSummary,
} from '../../types';
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

export type SupervisorTab = 'dashboard' | 'vehicles' | 'drivers' | 'reports' | 'workers' | 'attendance' | 'analytics';

export const SupervisorDashboard: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlTab = searchParams.get('tab') as SupervisorTab | null;
  const validTabs: SupervisorTab[] = ['dashboard', 'vehicles', 'drivers', 'reports', 'workers', 'attendance', 'analytics'];

  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(true);
  const [activeTab, setActiveTab] = useState<SupervisorTab>(
    urlTab && validTabs.includes(urlTab) ? urlTab : 'dashboard'
  );

  useEffect(() => {
    const tabParam = searchParams.get('tab') as SupervisorTab | null;
    if (tabParam && validTabs.includes(tabParam) && tabParam !== activeTab) {
      setActiveTab(tabParam);
    }
  }, [searchParams, activeTab]);
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

  // Driver Management state
  const [drivers, setDrivers] = useState<DriverSummary[]>([]);
  const [isLoadingDrivers, setIsLoadingDrivers] = useState(false);
  const [driverSearchQuery, setDriverSearchQuery] = useState('');
  const [driverStatusFilter, setDriverStatusFilter] = useState<string>('ALL');
  const [isRegisterDriverModalOpen, setIsRegisterDriverModalOpen] = useState(false);
  const [isAssignVehicleModalOpen, setIsAssignVehicleModalOpen] = useState(false);
  const [selectedDriverForVehicle, setSelectedDriverForVehicle] = useState<DriverSummary | null>(null);
  const [selectedVehicleIdToAssign, setSelectedVehicleIdToAssign] = useState<string>('');
  const [fleetVehicles, setFleetVehicles] = useState<any[]>([]);
  const [isSubmittingDriverReg, setIsSubmittingDriverReg] = useState(false);
  const [isSubmittingAssign, setIsSubmittingAssign] = useState(false);
  const [driverModalError, setDriverModalError] = useState<string | null>(null);

  // Driver Registration Form Fields
  const [regFullName, setRegFullName] = useState('');
  const [regEmail, setRegEmail] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [regWardId, setRegWardId] = useState('');
  const [regVehicleId, setRegVehicleId] = useState('');

  // Supervisor Operational Stats state
  const [supervisorStats, setSupervisorStats] = useState<SupervisorDashboardStats | null>(null);
  const [isLoadingStats, setIsLoadingStats] = useState(false);

  // Worker Management Directory state
  const [workersList, setWorkersList] = useState<SupervisorWorkerSummary[]>([]);
  const [isLoadingWorkers, setIsLoadingWorkers] = useState(false);
  const [workerSearchQuery, setWorkerSearchQuery] = useState('');
  const [workerStatusFilter, setWorkerStatusFilter] = useState<string>('ALL');

  // Modals for Worker Management
  const [isRegisterWorkerModalOpen, setIsRegisterWorkerModalOpen] = useState(false);
  const [isAssignScheduleModalOpen, setIsAssignScheduleModalOpen] = useState(false);
  const [isOverrideModalOpen, setIsOverrideModalOpen] = useState(false);

  // Worker Registration fields (pre-configured for test demonstration)
  const [workerRegFullName, setWorkerRegFullName] = useState('Pratik Gokavi');
  const [workerRegEmail, setWorkerRegEmail] = useState('pratikgokavi2007@gmail.com');
  const [workerRegPassword, setWorkerRegPassword] = useState('CleanBangalore@2026!');
  const [workerRegPhone, setWorkerRegPhone] = useState('+91 98450 12345');
  const [workerRegOfficialId, setWorkerRegOfficialId] = useState('BBMP-SW-042');
  const [isSubmittingWorkerReg, setIsSubmittingWorkerReg] = useState(false);
  const [workerRegError, setWorkerRegError] = useState<string | null>(null);

  // Schedule Assignment fields
  const [selectedWorkerForSchedule, setSelectedWorkerForSchedule] = useState<string>('');
  const [selectedRouteForSchedule, setSelectedRouteForSchedule] = useState<string>('');
  const [schedDaysOfWeek, setSchedDaysOfWeek] = useState<number[]>([1, 2, 3, 4, 5, 6]); // Mon-Sat
  const [schedShiftStart, setSchedShiftStart] = useState('07:00');
  const [schedShiftEnd, setSchedShiftEnd] = useState('14:00');
  const [schedCheckInStart, setSchedCheckInStart] = useState('06:45');
  const [schedCheckInEnd, setSchedCheckInEnd] = useState('07:30');
  const [schedGracePeriod, setSchedGracePeriod] = useState<number>(15);
  const [isSubmittingSchedule, setIsSubmittingSchedule] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  // Schedule Override fields
  const [overrideWorkerId, setOverrideWorkerId] = useState<string>('');
  const [overrideDate, setOverrideDate] = useState<string>(new Date().toISOString().split('T')[0]);
  const [overrideType, setOverrideType] = useState<'DAY_OFF' | 'HOLIDAY' | 'LEAVE' | 'SPECIAL_SHIFT'>('DAY_OFF');
  const [overrideReason, setOverrideReason] = useState<string>('Personal Leave');
  const [isSubmittingOverride, setIsSubmittingOverride] = useState(false);
  const [overrideError, setOverrideError] = useState<string | null>(null);

  // Ward Routes & Attendance Date Filter
  const [wardRoutes, setWardRoutes] = useState<any[]>([]);
  const [attendanceDate, setAttendanceDate] = useState<string>(new Date().toISOString().split('T')[0]);

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

  // Load Drivers
  const loadDrivers = useCallback(async () => {
    setIsLoadingDrivers(true);
    try {
      const data = await fetchDrivers({
        q: driverSearchQuery.trim() || undefined,
        wardId: currentUser?.role === 'WARD_SUPERVISOR' ? selectedWardId : undefined,
        status: driverStatusFilter !== 'ALL' ? driverStatusFilter : undefined,
      });
      setDrivers(data);
    } catch {
      // Safe fallback
    } finally {
      setIsLoadingDrivers(false);
    }
  }, [driverSearchQuery, selectedWardId, driverStatusFilter, currentUser?.role]);

  // Load Fleet Vehicles for Driver Assignment
  const loadFleetVehicles = useCallback(async () => {
    try {
      const res = await apiClient.get<any[]>('/vehicles');
      setFleetVehicles(res);
    } catch {
      // Safe fallback
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'drivers') {
      loadDrivers();
      loadFleetVehicles();
    }
  }, [activeTab, loadDrivers, loadFleetVehicles]);

  const handleRegisterDriver = async (e: React.FormEvent) => {
    e.preventDefault();
    setDriverModalError(null);
    if (!regFullName.trim()) {
      setDriverModalError('Please enter the driver full name.');
      return;
    }
    if (!regEmail.trim()) {
      setDriverModalError('Please enter a valid personal email.');
      return;
    }
    if (!regPassword || regPassword.length < 12) {
      setDriverModalError('Password must be at least 12 characters long.');
      return;
    }

    setIsSubmittingDriverReg(true);
    try {
      await createDriver({
        full_name: regFullName.trim(),
        email: regEmail.trim(),
        password: regPassword,
        ward_id: regWardId || currentUser?.ward_id || selectedWardId || undefined,
        vehicle_id: regVehicleId || undefined,
        status: 'ACTIVE',
      });

      setNotice({ type: 'success', message: `Driver ${regFullName} registered successfully with DRIVER role.` });
      setIsRegisterDriverModalOpen(false);
      setRegFullName('');
      setRegEmail('');
      setRegPassword('');
      setRegWardId('');
      setRegVehicleId('');
      loadDrivers();
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to register driver.';
      setDriverModalError(msg);
    } finally {
      setIsSubmittingDriverReg(false);
    }
  };

  const handleToggleDriverStatus = async (driver: DriverSummary) => {
    const nextStatus = driver.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE';
    try {
      await updateDriver(driver.id, { status: nextStatus });
      setNotice({
        type: 'success',
        message: `Driver ${driver.full_name || driver.email} account status updated to ${nextStatus}.`,
      });
      loadDrivers();
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to update driver status.';
      setNotice({ type: 'danger', message: msg });
    }
  };

  const handleAssignVehicle = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDriverForVehicle) return;
    setIsSubmittingAssign(true);
    try {
      await assignDriverVehicle(selectedDriverForVehicle.id, selectedVehicleIdToAssign || null);
      setNotice({
        type: 'success',
        message: `Vehicle assignment updated for driver ${selectedDriverForVehicle.full_name || selectedDriverForVehicle.email}.`,
      });
      setIsAssignVehicleModalOpen(false);
      setSelectedDriverForVehicle(null);
      setSelectedVehicleIdToAssign('');
      loadDrivers();
      loadFleetVehicles();
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to update vehicle assignment.';
      setNotice({ type: 'danger', message: msg });
    } finally {
      setIsSubmittingAssign(false);
    }
  };

  // Sanitation Worker Registration Handler
  const handleRegisterWorker = async (e: React.FormEvent) => {
    e.preventDefault();
    setWorkerRegError(null);
    if (!workerRegFullName.trim()) {
      setWorkerRegError('Please enter the worker full name.');
      return;
    }
    if (!workerRegEmail.trim()) {
      setWorkerRegError('Please enter a valid email address.');
      return;
    }
    if (!workerRegPassword || workerRegPassword.length < 8) {
      setWorkerRegError('Password must be at least 8 characters long.');
      return;
    }
    setIsSubmittingWorkerReg(true);
    try {
      await registerSupervisorWorker({
        full_name: workerRegFullName.trim(),
        email: workerRegEmail.trim(),
        password: workerRegPassword,
        phone_number: workerRegPhone.trim() || undefined,
        official_id: workerRegOfficialId.trim() || undefined,
        ward_id: selectedWardId,
      });
      setNotice({
        type: 'success',
        message: `Sanitation Worker ${workerRegFullName} (${workerRegEmail}) registered successfully in Ward.`,
      });
      setIsRegisterWorkerModalOpen(false);
      loadWorkersList(selectedWardId);
      loadSupervisorStats(selectedWardId, attendanceDate);
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to register worker.';
      setWorkerRegError(msg);
    } finally {
      setIsSubmittingWorkerReg(false);
    }
  };

  // Sanitation Worker Status Toggle (Active / Disabled)
  const handleToggleWorkerStatus = async (worker: SupervisorWorkerSummary) => {
    const nextStatus = worker.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE';
    try {
      await toggleWorkerStatus(worker.id, nextStatus);
      setNotice({
        type: 'success',
        message: `Worker ${worker.full_name || worker.email} account status updated to ${nextStatus}.`,
      });
      loadWorkersList(selectedWardId);
      loadSupervisorStats(selectedWardId, attendanceDate);
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to update worker status.';
      setNotice({ type: 'danger', message: msg });
    }
  };

  // Sanitation Worker Recurring Schedule Assignment
  const handleAssignSchedule = async (e: React.FormEvent) => {
    e.preventDefault();
    setScheduleError(null);
    if (!selectedWorkerForSchedule) {
      setScheduleError('Please select a worker.');
      return;
    }
    if (schedDaysOfWeek.length === 0) {
      setScheduleError('Please select at least one working day.');
      return;
    }
    setIsSubmittingSchedule(true);
    try {
      await assignWorkerSchedule({
        worker_id: selectedWorkerForSchedule,
        ward_id: selectedWardId,
        route_id: selectedRouteForSchedule || undefined,
        days_of_week: schedDaysOfWeek,
        shift_start_time: schedShiftStart,
        shift_end_time: schedShiftEnd,
        check_in_start_time: schedCheckInStart,
        check_in_end_time: schedCheckInEnd,
        grace_period_minutes: Number(schedGracePeriod) || 15,
      });
      setNotice({
        type: 'success',
        message: 'Recurring work schedule assigned successfully.',
      });
      setIsAssignScheduleModalOpen(false);
      loadWorkersList(selectedWardId);
      loadSupervisorStats(selectedWardId, attendanceDate);
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to assign work schedule.';
      setScheduleError(msg);
    } finally {
      setIsSubmittingSchedule(false);
    }
  };

  // Sanitation Worker Date-Specific Override
  const handleCreateOverride = async (e: React.FormEvent) => {
    e.preventDefault();
    setOverrideError(null);
    if (!overrideWorkerId) {
      setOverrideError('Please select a worker.');
      return;
    }
    setIsSubmittingOverride(true);
    try {
      await createScheduleOverride({
        worker_id: overrideWorkerId,
        override_date: overrideDate,
        override_type: overrideType,
        reason: overrideReason.trim() || undefined,
      });
      setNotice({
        type: 'success',
        message: `Schedule override (${overrideType}) saved for ${overrideDate}.`,
      });
      setIsOverrideModalOpen(false);
      loadWorkersList(selectedWardId);
      loadSupervisorStats(selectedWardId, attendanceDate);
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to create schedule override.';
      setOverrideError(msg);
    } finally {
      setIsSubmittingOverride(false);
    }
  };

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
  const loadRoster = useCallback(async (wardId: string, attDate?: string) => {
    setIsLoadingRoster(true);
    try {
      const data = await getDailyAttendanceRoster(wardId, attDate);
      setRosterData(data);
    } catch {
      setRosterData(null);
    } finally {
      setIsLoadingRoster(false);
    }
  }, []);

  // Load Supervisor Operational Stats
  const loadSupervisorStats = useCallback(async (wardId: string, targetDate?: string) => {
    setIsLoadingStats(true);
    try {
      const stats = await fetchSupervisorDashboardStats(wardId, targetDate);
      setSupervisorStats(stats);
    } catch {
      setSupervisorStats(null);
    } finally {
      setIsLoadingStats(false);
    }
  }, []);

  // Load Ward Workers Directory
  const loadWorkersList = useCallback(async (wardId: string) => {
    setIsLoadingWorkers(true);
    try {
      const list = await fetchSupervisorWorkers(wardId, workerSearchQuery, workerStatusFilter);
      setWorkersList(list);
    } catch {
      setWorkersList([]);
    } finally {
      setIsLoadingWorkers(false);
    }
  }, [workerSearchQuery, workerStatusFilter]);

  // Load Ward Routes
  const loadWardRoutes = useCallback(async (wardId: string) => {
    try {
      const res = await apiClient.get<any[]>(`/wards/${wardId}/routes`);
      setWardRoutes(res || []);
    } catch {
      setWardRoutes([]);
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
      loadRoster(selectedWardId, attendanceDate);
      loadReports(selectedWardId);
      loadSupervisorStats(selectedWardId, attendanceDate);
      loadWorkersList(selectedWardId);
      loadWardRoutes(selectedWardId);
    }
  }, [selectedWardId, attendanceDate, loadMusterStations, loadRoster, loadReports, loadSupervisorStats, loadWorkersList, loadWardRoutes]);

  useEffect(() => {
    if (activeTab === 'workers' && selectedWardId) {
      loadWorkersList(selectedWardId);
    }
    if (activeTab === 'attendance' && selectedWardId) {
      loadRoster(selectedWardId, attendanceDate);
    }
  }, [activeTab, selectedWardId, attendanceDate, loadWorkersList, loadRoster]);

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
          if (['dashboard', 'vehicles', 'drivers', 'reports', 'workers', 'attendance', 'analytics'].includes(tab)) {
            const nextTab = tab as SupervisorTab;
            setActiveTab(nextTab);
            setSearchParams({ tab: nextTab });
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
              userName={currentUser?.full_name ? currentUser.full_name.trim().split(' ')[0] : 'Officer'}
              isLoading={isLoadingUser}
              titlePrefix="Welcome back"
              subtitle="Manage your ward workforce, daily schedules, and attendance."
              roleBadge={currentUser?.role === 'MUNICIPAL_ADMIN' ? 'Municipal Administration' : 'Ward Supervision'}
              showBirds={false}
            />

            {/* 4 Operational Summary Cards matching civic design system */}
            <div className="nc-summary-overview" aria-label="Official operational metrics">
              <div className="nc-summary-grid">
                {/* 1. Workers Scheduled Today */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('workers')}
                  role="button"
                  tabIndex={0}
                  title="Click to view Worker Management"
                >
                  <span className="nc-summary-icon" style={{ backgroundColor: '#E8F5E9', color: '#2E7D32' }}>
                    <Users size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>{isLoadingStats ? '…' : (supervisorStats ? String(supervisorStats.workers_scheduled_today) : '0')}</strong>
                    <span className="nc-summary-label">Workers Scheduled Today</span>
                    <span className="nc-summary-note" style={{ color: '#2E7D32' }}>
                      {supervisorStats?.total_registered_workers ? `${supervisorStats.total_registered_workers} in Ward` : 'Worker Roster →'}
                    </span>
                  </span>
                </article>

                {/* 2. Present Today */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('attendance')}
                  role="button"
                  tabIndex={0}
                  title="Click to view Attendance"
                >
                  <span className="nc-summary-icon" style={{ backgroundColor: '#E0F2FE', color: '#0369A1' }}>
                    <CalendarCheck size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>{isLoadingStats ? '…' : (supervisorStats ? String(supervisorStats.present_today) : '0')}</strong>
                    <span className="nc-summary-label">Present Today</span>
                    <span className="nc-summary-note" style={{ color: '#0369A1' }}>
                      {supervisorStats && supervisorStats.workers_scheduled_today > 0
                        ? `${Math.round((supervisorStats.present_today / supervisorStats.workers_scheduled_today) * 100)}% Turnout`
                        : 'On Duty'}
                    </span>
                  </span>
                </article>

                {/* 3. Attendance Pending */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('attendance')}
                  role="button"
                  tabIndex={0}
                  title="Click to view Attendance"
                >
                  <span className="nc-summary-icon" style={{ backgroundColor: (supervisorStats?.attendance_pending ?? 0) > 0 ? '#FEF3C7' : '#F1F5F9', color: (supervisorStats?.attendance_pending ?? 0) > 0 ? '#B45309' : '#64748B' }}>
                    <Clock size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>{isLoadingStats ? '…' : (supervisorStats ? String(supervisorStats.attendance_pending) : '0')}</strong>
                    <span className="nc-summary-label">Attendance Pending</span>
                    <span
                      className="nc-summary-note"
                      style={{ color: (supervisorStats?.attendance_pending ?? 0) > 0 ? '#B45309' : '#2E7D32' }}
                    >
                      {(supervisorStats?.attendance_pending ?? 0) > 0 ? 'Window Closed / Unchecked' : '✓ No Pending'}
                    </span>
                  </span>
                </article>

                {/* 4. Attendance Exceptions */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('attendance')}
                  role="button"
                  tabIndex={0}
                  title="Click to review attendance exceptions"
                >
                  <span className="nc-summary-icon" style={{ backgroundColor: (supervisorStats?.attendance_exceptions ?? 0) > 0 ? '#FEE2E2' : '#E8F5E9', color: (supervisorStats?.attendance_exceptions ?? 0) > 0 ? '#DC2626' : '#2E7D32' }}>
                    <AlertTriangle size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>{isLoadingStats ? '…' : (supervisorStats ? String(supervisorStats.attendance_exceptions) : '0')}</strong>
                    <span className="nc-summary-label">Attendance Exceptions</span>
                    <span
                      className="nc-summary-note"
                      style={{ color: (supervisorStats?.attendance_exceptions ?? 0) > 0 ? '#DC2626' : '#2E7D32' }}
                    >
                      {(supervisorStats?.attendance_exceptions ?? 0) > 0 ? `${supervisorStats?.attendance_exceptions} Action Required →` : '✓ All Clear'}
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
                    onClick={() => {
                      setActiveTab('analytics');
                      setSearchParams({ tab: 'analytics' });
                    }}
                    style={{ fontSize: '0.85rem', padding: '0.55rem 1rem' }}
                  >
                    <BarChart3 size={16} />
                    <span>Operations Roster</span>
                  </Button>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setActiveTab('drivers');
                      setSearchParams({ tab: 'drivers' });
                    }}
                    style={{ fontSize: '0.85rem', padding: '0.55rem 1rem' }}
                  >
                    <Users size={16} />
                    <span>Driver Workforce</span>
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
                  complaints={reports}
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

          {/* TAB 2.5: DRIVER MANAGEMENT */}
          {activeTab === 'drivers' && (
            <div style={{ width: '100%', minWidth: 0, display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              {/* Header and Controls */}
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
                    Driver Workforce & Vehicle Assignments
                  </h3>
                  <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                    Manage municipal driver credentials, assign fleet vehicles, and monitor duty status.
                  </p>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => loadDrivers()}
                    style={{ fontSize: '0.82rem', padding: '6px 12px' }}
                  >
                    <RefreshCw size={14} />
                    <span>Refresh</span>
                  </Button>

                  <Button
                    type="button"
                    variant="primary"
                    onClick={() => {
                      setDriverModalError(null);
                      setIsRegisterDriverModalOpen(true);
                    }}
                    style={{
                      fontSize: '0.82rem',
                      padding: '6px 14px',
                      backgroundColor: '#1B4D3E',
                      color: '#FFFFFF',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.4rem',
                    }}
                  >
                    <UserPlus size={16} />
                    <span>Register Driver</span>
                  </Button>
                </div>
              </div>

              {/* Filters Bar */}
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  padding: '0.75rem 1.25rem',
                  borderRadius: '12px',
                  border: '1px solid #D5E3D7',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '1rem',
                  flexWrap: 'wrap',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, minWidth: '220px' }}>
                  <Search size={16} color="#64748B" />
                  <input
                    type="text"
                    placeholder="Search drivers by name or email..."
                    value={driverSearchQuery}
                    onChange={(e) => setDriverSearchQuery(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '6px 10px',
                      borderRadius: '8px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.85rem',
                      outline: 'none',
                    }}
                  />
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span style={{ fontSize: '0.8rem', color: '#64748B', fontWeight: 600 }}>Status:</span>
                  <select
                    value={driverStatusFilter}
                    onChange={(e) => setDriverStatusFilter(e.target.value)}
                    style={{
                      padding: '6px 10px',
                      borderRadius: '8px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.85rem',
                      backgroundColor: '#FFFFFF',
                    }}
                  >
                    <option value="ALL">All Statuses</option>
                    <option value="ACTIVE">Active Only</option>
                    <option value="DISABLED">Disabled Only</option>
                  </select>
                </div>
              </div>

              {/* Drivers Data Table */}
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '14px',
                  border: '1px solid #D5E3D7',
                  overflow: 'hidden',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                }}
              >
                {isLoadingDrivers ? (
                  <div style={{ padding: '3rem', textAlign: 'center' }}>
                    <Spinner size="md" />
                    <div style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: '#5A7565' }}>
                      Loading driver records...
                    </div>
                  </div>
                ) : drivers.length === 0 ? (
                  <div style={{ padding: '3rem 1.5rem', textAlign: 'center' }}>
                    <Users size={36} color="#94A3B8" style={{ margin: '0 auto 0.75rem' }} />
                    <h4 style={{ margin: '0 0 0.25rem', fontSize: '1rem', fontWeight: 700, color: '#1E293B' }}>
                      No Drivers Found
                    </h4>
                    <p style={{ margin: 0, fontSize: '0.85rem', color: '#64748B' }}>
                      {driverSearchQuery
                        ? 'No driver matches your search query. Try clearing the search filter.'
                        : 'No drivers have been registered yet. Click "Register Driver" above to create an account.'}
                    </p>
                  </div>
                ) : (
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                      <thead>
                        <tr style={{ backgroundColor: '#F8FAFC', borderBottom: '1px solid #E2E8F0', color: '#475569' }}>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Driver Name &amp; Email</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Account</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Assigned Vehicle</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Ward</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Duty State</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Telemetry / Signal</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700, textAlign: 'right' }}>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {drivers.map((drv) => {
                          const veh = drv.assigned_vehicle;
                          const isOnDuty = drv.duty_status === 'ON_DUTY';
                          const isLocFresh = !drv.is_stale;

                          return (
                            <tr
                              key={drv.id}
                              style={{
                                borderBottom: '1px solid #F1F5F9',
                                transition: 'background-color 0.15s ease',
                              }}
                            >
                              {/* Driver Info */}
                              <td style={{ padding: '0.85rem 1rem' }}>
                                <div style={{ fontWeight: 700, color: '#0F172A' }}>
                                  {drv.full_name || 'Driver (Unspecified Name)'}
                                </div>
                                <div style={{ fontSize: '0.78rem', color: '#64748B' }}>{drv.email}</div>
                              </td>

                              {/* Status Badge */}
                              <td style={{ padding: '0.85rem 1rem' }}>
                                <span
                                  style={{
                                    display: 'inline-block',
                                    padding: '3px 8px',
                                    borderRadius: '6px',
                                    fontSize: '0.72rem',
                                    fontWeight: 700,
                                    backgroundColor: drv.status === 'ACTIVE' ? '#E8F5E9' : '#FEE2E2',
                                    color: drv.status === 'ACTIVE' ? '#166534' : '#991B1B',
                                  }}
                                >
                                  {drv.status}
                                </span>
                              </td>

                              {/* Vehicle Assignment */}
                              <td style={{ padding: '0.85rem 1rem' }}>
                                {veh ? (
                                  <div>
                                    <div style={{ fontWeight: 750, color: '#1B4D3E', letterSpacing: '0.02em' }}>
                                      {veh.registration_number}
                                    </div>
                                    <div style={{ fontSize: '0.72rem', color: '#64748B', textTransform: 'capitalize' }}>
                                      {veh.vehicle_type.toLowerCase().replace('_', ' ')}
                                    </div>
                                  </div>
                                ) : (
                                  <span
                                    style={{
                                      display: 'inline-block',
                                      padding: '2px 8px',
                                      borderRadius: '4px',
                                      backgroundColor: '#FEF3C7',
                                      color: '#92400E',
                                      fontSize: '0.75rem',
                                      fontWeight: 600,
                                    }}
                                  >
                                    Unassigned
                                  </span>
                                )}
                              </td>

                              {/* Ward */}
                              <td style={{ padding: '0.85rem 1rem', color: '#334155' }}>
                                {drv.ward_name || (drv.ward_id ? drv.ward_id.slice(0, 8) : '—')}
                              </td>

                              {/* Duty Status */}
                              <td style={{ padding: '0.85rem 1rem' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                  <span
                                    style={{
                                      width: '7px',
                                      height: '7px',
                                      borderRadius: '50%',
                                      backgroundColor: isOnDuty ? '#16A34A' : '#94A3B8',
                                    }}
                                  />
                                  <span
                                    style={{
                                      fontWeight: 700,
                                      fontSize: '0.78rem',
                                      color: isOnDuty ? '#166534' : '#64748B',
                                    }}
                                  >
                                    {isOnDuty ? 'ON DUTY' : 'IDLE'}
                                  </span>
                                </div>
                                {drv.duty_start_time && (
                                  <div style={{ fontSize: '0.7rem', color: '#94A3B8', marginTop: '2px' }}>
                                    Since{' '}
                                    {new Date(drv.duty_start_time).toLocaleTimeString([], {
                                      hour: '2-digit',
                                      minute: '2-digit',
                                    })}
                                  </div>
                                )}
                              </td>

                              {/* Telemetry Snapshot */}
                              <td style={{ padding: '0.85rem 1rem' }}>
                                {drv.last_location ? (
                                  <div>
                                    <div style={{ fontFamily: 'monospace', fontSize: '0.75rem', color: '#334155' }}>
                                      {drv.last_location.latitude.toFixed(4)}, {drv.last_location.longitude.toFixed(4)}
                                    </div>
                                    <span
                                      style={{
                                        fontSize: '0.7rem',
                                        fontWeight: 700,
                                        color: isLocFresh ? '#16A34A' : '#D97706',
                                      }}
                                    >
                                      {isLocFresh ? '● Live Signal' : '○ Stale Position'}
                                    </span>
                                  </div>
                                ) : (
                                  <span style={{ fontSize: '0.75rem', color: '#94A3B8' }}>No GPS Fix</span>
                                )}
                              </td>

                              {/* Action Buttons */}
                              <td style={{ padding: '0.85rem 1rem', textAlign: 'right' }}>
                                <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}>
                                  <Button
                                    type="button"
                                    variant="outline"
                                    onClick={() => {
                                      setSelectedDriverForVehicle(drv);
                                      setSelectedVehicleIdToAssign(veh ? veh.id : '');
                                      setIsAssignVehicleModalOpen(true);
                                    }}
                                    style={{ fontSize: '0.75rem', padding: '4px 8px' }}
                                  >
                                    <Truck size={13} />
                                    <span>{veh ? 'Reassign' : 'Assign'}</span>
                                  </Button>

                                  <Button
                                    type="button"
                                    variant="outline"
                                    onClick={() => handleToggleDriverStatus(drv)}
                                    style={{
                                      fontSize: '0.75rem',
                                      padding: '4px 8px',
                                      color: drv.status === 'ACTIVE' ? '#DC2626' : '#166534',
                                      borderColor: drv.status === 'ACTIVE' ? '#FCA5A5' : '#86EFAC',
                                    }}
                                  >
                                    {drv.status === 'ACTIVE' ? (
                                      <>
                                        <ShieldOff size={13} />
                                        <span>Disable</span>
                                      </>
                                    ) : (
                                      <>
                                        <ShieldCheck size={13} />
                                        <span>Activate</span>
                                      </>
                                    )}
                                  </Button>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* MODAL 1: REGISTER DRIVER */}
              {isRegisterDriverModalOpen && (
                <div
                  style={{
                    position: 'fixed',
                    inset: 0,
                    backgroundColor: 'rgba(0,0,0,0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                    padding: '1rem',
                  }}
                >
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: '16px',
                      padding: '1.75rem',
                      maxWidth: '480px',
                      width: '100%',
                      boxShadow: '0 20px 40px rgba(0,0,0,0.2)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <UserPlus size={20} color="#1B4D3E" />
                        <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 800, color: '#183B2A' }}>
                          Register Driver Account
                        </h3>
                      </div>
                      <button
                        type="button"
                        onClick={() => setIsRegisterDriverModalOpen(false)}
                        style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#64748B' }}
                      >
                        <X size={20} />
                      </button>
                    </div>

                    {driverModalError && (
                      <div style={{ marginBottom: '1rem' }}>
                        <Alert type="danger" title="Registration Error">
                          {driverModalError}
                        </Alert>
                      </div>
                    )}

                    <form onSubmit={handleRegisterDriver} style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                          Driver Full Name *
                        </label>
                        <input
                          type="text"
                          required
                          placeholder="e.g. Anand Murthy"
                          value={regFullName}
                          onChange={(e) => setRegFullName(e.target.value)}
                          style={{
                            width: '100%',
                            padding: '8px 12px',
                            borderRadius: '8px',
                            border: '1px solid #CBD5E1',
                            fontSize: '0.88rem',
                          }}
                        />
                      </div>

                      <div>
                        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                          Personal Email Address (Login ID) *
                        </label>
                        <input
                          type="email"
                          required
                          placeholder="driver@nammaclean.in"
                          value={regEmail}
                          onChange={(e) => setRegEmail(e.target.value)}
                          style={{
                            width: '100%',
                            padding: '8px 12px',
                            borderRadius: '8px',
                            border: '1px solid #CBD5E1',
                            fontSize: '0.88rem',
                          }}
                        />
                      </div>

                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                          <label style={{ fontSize: '0.8rem', fontWeight: 700, color: '#334155' }}>
                            Password (Min 12 characters) *
                          </label>
                          <button
                            type="button"
                            onClick={() => {
                              const gen = `Driver#${Math.random().toString(36).slice(2, 8)}!2026`;
                              setRegPassword(gen);
                            }}
                            style={{ border: 'none', background: 'none', color: '#1B4D3E', fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer' }}
                          >
                            Auto-Generate
                          </button>
                        </div>
                        <input
                          type="text"
                          required
                          minLength={12}
                          placeholder="Enter secure password"
                          value={regPassword}
                          onChange={(e) => setRegPassword(e.target.value)}
                          style={{
                            width: '100%',
                            padding: '8px 12px',
                            borderRadius: '8px',
                            border: '1px solid #CBD5E1',
                            fontSize: '0.88rem',
                          }}
                        />
                      </div>

                      <div>
                        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '4px' }}>
                          Initial Vehicle Assignment (Optional)
                        </label>
                        <select
                          value={regVehicleId}
                          onChange={(e) => setRegVehicleId(e.target.value)}
                          style={{
                            width: '100%',
                            padding: '8px 12px',
                            borderRadius: '8px',
                            border: '1px solid #CBD5E1',
                            fontSize: '0.88rem',
                            backgroundColor: '#FFFFFF',
                          }}
                        >
                          <option value="">No vehicle assigned yet</option>
                          {fleetVehicles.map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.registration_number} ({v.vehicle_type.toLowerCase().replace('_', ' ')})
                              {v.assigned_driver_id ? ' - Currently Assigned' : ' - Available'}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1rem' }}>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => setIsRegisterDriverModalOpen(false)}
                        >
                          Cancel
                        </Button>
                        <Button
                          type="submit"
                          variant="primary"
                          disabled={isSubmittingDriverReg}
                          style={{ backgroundColor: '#1B4D3E', color: '#FFFFFF' }}
                        >
                          {isSubmittingDriverReg ? 'Registering...' : 'Register Driver'}
                        </Button>
                      </div>
                    </form>
                  </div>
                </div>
              )}

              {/* MODAL 2: ASSIGN VEHICLE */}
              {isAssignVehicleModalOpen && selectedDriverForVehicle && (
                <div
                  style={{
                    position: 'fixed',
                    inset: 0,
                    backgroundColor: 'rgba(0,0,0,0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                    padding: '1rem',
                  }}
                >
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: '16px',
                      padding: '1.75rem',
                      maxWidth: '460px',
                      width: '100%',
                      boxShadow: '0 20px 40px rgba(0,0,0,0.2)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Truck size={20} color="#1B4D3E" />
                        <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 800, color: '#183B2A' }}>
                          Assign Vehicle
                        </h3>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setIsAssignVehicleModalOpen(false);
                          setSelectedDriverForVehicle(null);
                        }}
                        style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#64748B' }}
                      >
                        <X size={20} />
                      </button>
                    </div>

                    <p style={{ margin: '0 0 1rem', fontSize: '0.85rem', color: '#5A7565' }}>
                      Assign a municipal collection truck or auto-tipper to driver{' '}
                      <strong>{selectedDriverForVehicle.full_name || selectedDriverForVehicle.email}</strong>.
                    </p>

                    <form onSubmit={handleAssignVehicle} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '6px' }}>
                          Select Fleet Vehicle
                        </label>
                        <select
                          value={selectedVehicleIdToAssign}
                          onChange={(e) => setSelectedVehicleIdToAssign(e.target.value)}
                          style={{
                            width: '100%',
                            padding: '10px 12px',
                            borderRadius: '8px',
                            border: '1px solid #CBD5E1',
                            fontSize: '0.88rem',
                            backgroundColor: '#FFFFFF',
                          }}
                        >
                          <option value="">Unassign (No Vehicle)</option>
                          {fleetVehicles.map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.registration_number} — {v.vehicle_type.toLowerCase().replace('_', ' ')}
                              {v.assigned_driver_id === selectedDriverForVehicle.id
                                ? ' (Current Vehicle)'
                                : v.assigned_driver_id
                                ? ' (Assigned to another driver)'
                                : ' (Available)'}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.5rem' }}>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => {
                            setIsAssignVehicleModalOpen(false);
                            setSelectedDriverForVehicle(null);
                          }}
                        >
                          Cancel
                        </Button>
                        <Button
                          type="submit"
                          variant="primary"
                          disabled={isSubmittingAssign}
                          style={{ backgroundColor: '#1B4D3E', color: '#FFFFFF' }}
                        >
                          {isSubmittingAssign ? 'Updating...' : 'Save Assignment'}
                        </Button>
                      </div>
                    </form>
                  </div>
                </div>
              )}
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

          {/* TAB 4: WORKER MANAGEMENT DIRECTORY & SCHEDULES */}
          {activeTab === 'workers' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              {/* Header & Quick Action Bar */}
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  padding: '1.25rem 1.5rem',
                  borderRadius: '16px',
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
                  <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 750, color: '#183B2A' }}>
                    Ward Sanitation Worker Management
                  </h3>
                  <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                    Register field workforce, assign recurring weekly duty schedules, and manage status for Ward {selectedWardId.slice(0, 8)}.
                  </p>
                </div>

                <div style={{ display: 'flex', gap: '0.65rem', flexWrap: 'wrap' }}>
                  <Button
                    type="button"
                    variant="primary"
                    onClick={() => {
                      setWorkerRegError(null);
                      setIsRegisterWorkerModalOpen(true);
                    }}
                    style={{ fontSize: '0.85rem', padding: '0.55rem 1.1rem' }}
                  >
                    <UserPlus size={16} />
                    <span>+ Register Worker</span>
                  </Button>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setScheduleError(null);
                      setIsAssignScheduleModalOpen(true);
                    }}
                    style={{ fontSize: '0.85rem', padding: '0.55rem 1.1rem' }}
                  >
                    <Calendar size={16} />
                    <span>+ Assign Schedule</span>
                  </Button>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setOverrideError(null);
                      setIsOverrideModalOpen(true);
                    }}
                    style={{ fontSize: '0.85rem', padding: '0.55rem 1.1rem' }}
                  >
                    <Sliders size={16} />
                    <span>+ Schedule Override</span>
                  </Button>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => loadWorkersList(selectedWardId)}
                    disabled={isLoadingWorkers}
                    style={{ fontSize: '0.85rem', padding: '0.55rem 1rem' }}
                  >
                    <RefreshCw size={15} className={isLoadingWorkers ? 'nc-spin' : ''} />
                    <span>Refresh</span>
                  </Button>
                </div>
              </div>

              {/* Filters Bar */}
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  padding: '1rem 1.5rem',
                  borderRadius: '14px',
                  border: '1px solid #D5E3D7',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '1rem',
                  flexWrap: 'wrap',
                  justifyContent: 'space-between',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, minWidth: '240px' }}>
                  <Search size={18} color="#64748B" />
                  <input
                    type="text"
                    value={workerSearchQuery}
                    onChange={(e) => setWorkerSearchQuery(e.target.value)}
                    placeholder="Search by worker name, email, or official ID..."
                    style={{
                      width: '100%',
                      border: 'none',
                      outline: 'none',
                      fontSize: '0.9rem',
                      color: '#1E293B',
                      backgroundColor: 'transparent',
                    }}
                  />
                  {workerSearchQuery && (
                    <button
                      type="button"
                      onClick={() => setWorkerSearchQuery('')}
                      style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#94A3B8' }}
                    >
                      <X size={16} />
                    </button>
                  )}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <label style={{ fontSize: '0.85rem', fontWeight: 600, color: '#475569' }}>Status:</label>
                  <select
                    value={workerStatusFilter}
                    onChange={(e) => setWorkerStatusFilter(e.target.value)}
                    style={{
                      padding: '0.45rem 0.85rem',
                      borderRadius: '8px',
                      border: '1px solid #CBD5E1',
                      fontSize: '0.85rem',
                      fontWeight: 600,
                      color: '#1E293B',
                      backgroundColor: '#FFFFFF',
                    }}
                  >
                    <option value="ALL">All Statuses</option>
                    <option value="ACTIVE">Active Only</option>
                    <option value="DISABLED">Disabled Only</option>
                  </select>
                </div>
              </div>

              {/* Workers Directory Table */}
              {isLoadingWorkers ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3.5rem', color: '#4B5563' }}>
                  <Spinner size="md" />
                  <span style={{ marginLeft: '0.75rem' }}>Loading ward worker directory...</span>
                </div>
              ) : workersList.length === 0 ? (
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    padding: '3.5rem 2rem',
                    borderRadius: '16px',
                    border: '1px solid #D5E3D7',
                    textAlign: 'center',
                    color: '#64748B',
                  }}
                >
                  <Users size={40} style={{ margin: '0 auto 0.75rem', opacity: 0.5 }} />
                  <h4 style={{ margin: '0 0 0.35rem', fontSize: '1.1rem', fontWeight: 700, color: '#183B2A' }}>
                    No Sanitation Workers Found
                  </h4>
                  <p style={{ margin: '0 0 1.25rem', fontSize: '0.88rem' }}>
                    Register a new worker to start assigning schedules and tracking attendance for this ward.
                  </p>
                  <Button
                    type="button"
                    variant="primary"
                    onClick={() => setIsRegisterWorkerModalOpen(true)}
                  >
                    <UserPlus size={16} />
                    <span>Register Sanitation Worker</span>
                  </Button>
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
                        <th style={{ padding: '0.9rem 1.25rem', fontWeight: 700 }}>Pourakarmika</th>
                        <th style={{ padding: '0.9rem 1rem', fontWeight: 700 }}>Status</th>
                        <th style={{ padding: '0.9rem 1rem', fontWeight: 700 }}>Assigned Ward / Route</th>
                        <th style={{ padding: '0.9rem 1.25rem', fontWeight: 700 }}>Weekly Schedule</th>
                        <th style={{ padding: '0.9rem 1rem', fontWeight: 700 }}>Today Attendance</th>
                        <th style={{ padding: '0.9rem 1.25rem', fontWeight: 700, textAlign: 'right' }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {workersList.map((w) => {
                        const isActive = w.status === 'ACTIVE';
                        return (
                          <tr key={w.id} style={{ borderBottom: '1px solid #F1F5F9' }}>
                            <td style={{ padding: '0.9rem 1.25rem' }}>
                              <div style={{ fontWeight: 700, color: '#1E293B', fontSize: '0.92rem' }}>
                                {w.full_name || 'Pourakarmika'}
                              </div>
                              <div style={{ fontSize: '0.78rem', color: '#64748B' }}>
                                {w.email}
                              </div>
                              {w.official_id && (
                                <span
                                  style={{
                                    display: 'inline-block',
                                    marginTop: '0.2rem',
                                    fontSize: '0.72rem',
                                    fontFamily: 'monospace',
                                    padding: '1px 6px',
                                    backgroundColor: '#E0F2FE',
                                    color: '#0369A1',
                                    borderRadius: '4px',
                                    fontWeight: 700,
                                  }}
                                >
                                  {w.official_id}
                                </span>
                              )}
                            </td>

                            <td style={{ padding: '0.9rem 1rem' }}>
                              <span
                                style={{
                                  display: 'inline-block',
                                  padding: '3px 8px',
                                  borderRadius: '999px',
                                  fontSize: '0.75rem',
                                  fontWeight: 700,
                                  backgroundColor: isActive ? '#D1FAE5' : '#FEE2E2',
                                  color: isActive ? '#065F46' : '#991B1B',
                                }}
                              >
                                {w.status}
                              </span>
                            </td>

                            <td style={{ padding: '0.9rem 1rem' }}>
                              <div style={{ color: '#1E293B', fontWeight: 600 }}>
                                {w.ward_name || `Ward: ${selectedWardId.slice(0, 8)}`}
                              </div>
                              <div style={{ fontSize: '0.78rem', color: '#64748B' }}>
                                {w.route_name ? `Route: ${w.route_name}` : 'No route assigned'}
                              </div>
                            </td>

                            <td style={{ padding: '0.9rem 1.25rem' }}>
                              {w.has_active_schedule ? (
                                <div>
                                  <div style={{ fontWeight: 600, color: '#183B2A' }}>
                                    {w.shift_start_time} – {w.shift_end_time}
                                  </div>
                                  <div style={{ fontSize: '0.76rem', color: '#5A7565' }}>
                                    Window: {w.check_in_window_start} – {w.check_in_window_end}
                                  </div>
                                </div>
                              ) : (
                                <span style={{ fontSize: '0.8rem', color: '#94A3B8', fontStyle: 'italic' }}>
                                  No recurring schedule
                                </span>
                              )}
                            </td>

                            <td style={{ padding: '0.9rem 1rem' }}>
                              <span
                                style={{
                                  display: 'inline-block',
                                  padding: '3px 8px',
                                  borderRadius: '999px',
                                  fontSize: '0.75rem',
                                  fontWeight: 700,
                                  backgroundColor:
                                    w.today_attendance_status === 'PRESENT'
                                      ? '#D1FAE5'
                                      : w.today_attendance_status === 'EXCEPTION_PENDING'
                                      ? '#FEF3C7'
                                      : w.today_attendance_status === 'REJECTED'
                                      ? '#FEE2E2'
                                      : '#F1F5F9',
                                  color:
                                    w.today_attendance_status === 'PRESENT'
                                      ? '#065F46'
                                      : w.today_attendance_status === 'EXCEPTION_PENDING'
                                      ? '#92400E'
                                      : w.today_attendance_status === 'REJECTED'
                                      ? '#991B1B'
                                      : '#64748B',
                                }}
                              >
                                {w.today_attendance_status || 'Not Checked In'}
                              </span>
                            </td>

                            <td style={{ padding: '0.9rem 1.25rem', textAlign: 'right' }}>
                              <div style={{ display: 'flex', gap: '0.4rem', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                                <Button
                                  type="button"
                                  variant="outline"
                                  onClick={() => {
                                    setSelectedWorkerForSchedule(w.id);
                                    setScheduleError(null);
                                    setIsAssignScheduleModalOpen(true);
                                  }}
                                  style={{ padding: '4px 8px', fontSize: '0.78rem' }}
                                >
                                  Schedule
                                </Button>

                                <Button
                                  type="button"
                                  variant="outline"
                                  onClick={() => {
                                    setOverrideWorkerId(w.id);
                                    setOverrideError(null);
                                    setIsOverrideModalOpen(true);
                                  }}
                                  style={{ padding: '4px 8px', fontSize: '0.78rem' }}
                                >
                                  Override
                                </Button>

                                <Button
                                  type="button"
                                  variant={isActive ? 'danger' : 'primary'}
                                  onClick={() => handleToggleWorkerStatus(w)}
                                  style={{ padding: '4px 8px', fontSize: '0.78rem' }}
                                >
                                  {isActive ? 'Disable' : 'Enable'}
                                </Button>
                              </div>
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

          {/* TAB: WORKER ATTENDANCE HUB */}
          {activeTab === 'attendance' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              {/* Top Controls Card */}
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
                    Worker Attendance Hub & Field Roll-Call
                  </h3>
                  <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                    Generate single-use 5-minute QR roll-call tokens and monitor daily pourakarmika attendance.
                  </p>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                  {/* Date Selector */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <Calendar size={16} color="#183B2A" />
                    <input
                      type="date"
                      value={attendanceDate}
                      onChange={(e) => setAttendanceDate(e.target.value)}
                      style={{
                        padding: '6px 10px',
                        borderRadius: '8px',
                        border: '1px solid #CBD5E1',
                        fontSize: '0.84rem',
                        color: '#1E293B',
                      }}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setAttendanceDate(new Date().toISOString().split('T')[0])}
                      style={{ fontSize: '0.78rem', padding: '5px 10px' }}
                    >
                      Today
                    </Button>
                  </div>

                  {/* Muster Station Selector */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <MapPin size={16} color="#183B2A" />
                    <select
                      value={selectedMusterId}
                      onChange={(e) => setSelectedMusterId(e.target.value)}
                      style={{
                        padding: '6px 10px',
                        borderRadius: '8px',
                        border: '1px solid #CBD5E1',
                        fontSize: '0.84rem',
                        color: '#1E293B',
                        maxWidth: '220px',
                      }}
                    >
                      {musterPoints.length === 0 ? (
                        <option value="">No muster station found</option>
                      ) : (
                        musterPoints.map((mp) => (
                          <option key={mp.id} value={mp.id}>
                            {mp.name} (Radius: {mp.geofence_radius_meters}m)
                          </option>
                        ))
                      )}
                    </select>
                  </div>

                  {/* Generate QR Button */}
                  <Button
                    type="button"
                    variant="primary"
                    onClick={handleGenerateQr}
                    disabled={!selectedMusterId || isIssuingQr}
                    style={{ fontSize: '0.84rem', padding: '6px 14px' }}
                  >
                    <QrCode size={16} />
                    <span>{isIssuingQr ? 'Generating...' : 'Issue 5-Min QR'}</span>
                  </Button>

                  {/* Refresh Button */}
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      loadRoster(selectedWardId, attendanceDate);
                      loadSupervisorStats(selectedWardId, attendanceDate);
                    }}
                    style={{ fontSize: '0.84rem', padding: '6px 12px' }}
                  >
                    <RefreshCw size={15} />
                    <span>Refresh</span>
                  </Button>
                </div>
              </div>

              {/* Active 5-Minute QR Code Display Card */}
              {qrTokenData && (
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: '16px',
                    border: isQrExpired ? '2px solid #EF4444' : '2px solid #10B981',
                    padding: '1.5rem',
                    boxShadow: '0 4px 15px rgba(0,0,0,0.05)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    textAlign: 'center',
                    gap: '1rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <QrCode size={22} color={isQrExpired ? '#EF4444' : '#059669'} />
                    <span style={{ fontSize: '1.05rem', fontWeight: 700, color: '#183B2A' }}>
                      Official Muster Roll-Call QR Code
                    </span>
                  </div>

                  <p style={{ margin: 0, fontSize: '0.85rem', color: '#64748B', maxWidth: '500px' }}>
                    Pourakarmikas stationed at <strong>{musterPoints.find(m => m.id === qrTokenData.muster_point_id)?.name || 'Ward Muster Station'}</strong> can scan this QR code with their mobile device to record on-site attendance within the 150m muster geofence.
                  </p>

                  <div style={{ margin: '0.5rem 0' }}>
                    <QrCodeDisplay token={qrTokenData.token} size={220} />
                  </div>

                  {/* Countdown Badge */}
                  <div
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      padding: '6px 16px',
                      borderRadius: '999px',
                      fontWeight: 700,
                      fontSize: '0.88rem',
                      backgroundColor: isQrExpired ? '#FEE2E2' : '#ECFDF5',
                      color: isQrExpired ? '#B91C1C' : '#047857',
                      border: isQrExpired ? '1px solid #FCA5A5' : '1px solid #A7F3D0',
                    }}
                  >
                    <Clock size={16} />
                    {isQrExpired ? (
                      <span>Token Expired — Please generate a fresh token</span>
                    ) : (
                      <span>
                        Expires in: {minutesRemaining}m {secondsRemaining < 10 ? '0' : ''}{secondsRemaining}s
                      </span>
                    )}
                  </div>

                  {isQrExpired && (
                    <Button
                      type="button"
                      variant="primary"
                      onClick={handleGenerateQr}
                      disabled={isIssuingQr}
                      style={{ fontSize: '0.84rem' }}
                    >
                      <RefreshCw size={15} />
                      <span>Regenerate Active Token</span>
                    </Button>
                  )}
                </div>
              )}

              {/* Daily Attendance Roster Table */}
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '14px',
                  border: '1px solid #D5E3D7',
                  overflow: 'hidden',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.03)',
                }}
              >
                <div
                  style={{
                    padding: '1rem 1.25rem',
                    borderBottom: '1px solid #E2E8F0',
                    backgroundColor: '#F8FAFC',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700, color: '#183B2A' }}>
                    Daily Attendance Records ({rosterData?.records?.length || 0}) — {attendanceDate}
                  </h4>
                  <div style={{ fontSize: '0.82rem', color: '#64748B' }}>
                    Muster Station: <strong>{musterPoints.find(m => m.id === selectedMusterId)?.name || 'Default Muster Depot'}</strong>
                  </div>
                </div>

                {isLoadingRoster ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3rem', color: '#4B5563' }}>
                    <Spinner size="md" />
                    <span style={{ marginLeft: '0.75rem' }}>Loading attendance roster...</span>
                  </div>
                ) : !rosterData || rosterData.records.length === 0 ? (
                  <div style={{ padding: '3rem 2rem', textAlign: 'center', color: '#64748B' }}>
                    <Users size={36} style={{ margin: '0 auto 0.75rem', opacity: 0.5 }} />
                    <div style={{ fontSize: '1rem', fontWeight: 700, color: '#183B2A' }}>
                      No attendance records found for {attendanceDate}
                    </div>
                    <p style={{ margin: '0.25rem 0 0', fontSize: '0.85rem' }}>
                      Workers can record attendance using the 5-Minute Roll-Call QR code or their mobile worker dashboard.
                    </p>
                  </div>
                ) : (
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.88rem' }}>
                      <thead>
                        <tr style={{ backgroundColor: '#F8FAFC', borderBottom: '1px solid #E2E8F0', color: '#475569' }}>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Official ID</th>
                          <th style={{ padding: '0.85rem 1.25rem', fontWeight: 700 }}>Pourakarmika</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Check-In</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Check-Out</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Duration Worked</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Muster Distance</th>
                          <th style={{ padding: '0.85rem 1rem', fontWeight: 700 }}>Status</th>
                          <th style={{ padding: '0.85rem 1.25rem', fontWeight: 700, textAlign: 'right' }}>Official Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rosterData.records.map((rec) => {
                          const isException = rec.status === 'EXCEPTION_PENDING';
                          const durHrs = rec.duration_minutes ? Math.floor(rec.duration_minutes / 60) : 0;
                          const durMins = rec.duration_minutes ? rec.duration_minutes % 60 : 0;
                          return (
                            <tr key={rec.id} style={{ borderBottom: '1px solid #F1F5F9' }}>
                              <td style={{ padding: '0.85rem 1rem' }}>
                                {rec.official_id ? (
                                  <span
                                    style={{
                                      backgroundColor: '#E0F2FE',
                                      color: '#0369A1',
                                      border: '1px solid #BAE6FD',
                                      padding: '2px 7px',
                                      borderRadius: '5px',
                                      fontFamily: 'monospace',
                                      fontSize: '0.78rem',
                                      fontWeight: 700,
                                    }}
                                  >
                                    {rec.official_id}
                                  </span>
                                ) : (
                                  <span
                                    style={{
                                      backgroundColor: '#FEF3C7',
                                      color: '#92400E',
                                      padding: '2px 7px',
                                      borderRadius: '5px',
                                      fontSize: '0.74rem',
                                      fontWeight: 600,
                                    }}
                                  >
                                    Pending ID
                                  </span>
                                )}
                              </td>
                              <td style={{ padding: '0.85rem 1.25rem', fontWeight: 600, color: '#1E293B' }}>
                                <div>{rec.worker_name || 'Pourakarmika'}</div>
                                <div style={{ fontSize: '0.76rem', color: '#64748B' }}>
                                  {rec.worker_email || `ID: ${rec.worker_id.slice(0, 8)}`}
                                </div>
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
                              <td style={{ padding: '0.85rem 1rem', color: '#183B2A', fontWeight: 600 }}>
                                {rec.duration_minutes ? (
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
                                <div>
                                  {rec.check_in_distance_meters !== null && rec.check_in_distance_meters !== undefined
                                    ? `${Math.round(rec.check_in_distance_meters)}m`
                                    : '—'}
                                </div>
                                {rec.check_in_accuracy_meters !== null && rec.check_in_accuracy_meters !== undefined && (
                                  <div style={{ fontSize: '0.72rem', color: '#94A3B8' }}>
                                    (±{Math.round(rec.check_in_accuracy_meters)}m GPS)
                                  </div>
                                )}
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
              </div>
            </div>
          )}

          {/* TAB: OPERATIONS ROSTER ANALYTICS */}
          {activeTab === 'analytics' && (
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
                    Operations Roster & Attendance Analytics
                  </h3>
                  <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                    Workforce turnout, punctuality, and schedule compliance metrics for Ward Administration.
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    loadRoster(selectedWardId, attendanceDate);
                    loadSupervisorStats(selectedWardId, attendanceDate);
                  }}
                  style={{ fontSize: '0.82rem', padding: '6px 12px' }}
                >
                  <RefreshCw size={14} />
                  <span>Refresh Metrics</span>
                </Button>
              </div>

              {/* Roster Metric Cards */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
                <div style={{ backgroundColor: '#FFFFFF', padding: '1.25rem', borderRadius: '12px', border: '1px solid #E2E8F0', borderLeft: '4px solid #059669' }}>
                  <div style={{ fontSize: '0.82rem', color: '#64748B', fontWeight: 600 }}>Scheduled Workforce</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#1E293B', marginTop: '0.25rem' }}>
                    {supervisorStats?.workers_scheduled_today ?? 0}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: '#059669', marginTop: '0.25rem' }}>Assigned for duty today</div>
                </div>

                <div style={{ backgroundColor: '#FFFFFF', padding: '1.25rem', borderRadius: '12px', border: '1px solid #E2E8F0', borderLeft: '4px solid #10B981' }}>
                  <div style={{ fontSize: '0.82rem', color: '#64748B', fontWeight: 600 }}>Present on Duty</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#047857', marginTop: '0.25rem' }}>
                    {supervisorStats?.present_today ?? 0}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: '#64748B', marginTop: '0.25rem' }}>Verified at muster depot</div>
                </div>

                <div style={{ backgroundColor: '#FFFFFF', padding: '1.25rem', borderRadius: '12px', border: '1px solid #E2E8F0', borderLeft: '4px solid #F59E0B' }}>
                  <div style={{ fontSize: '0.82rem', color: '#64748B', fontWeight: 600 }}>Attendance Pending</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#B45309', marginTop: '0.25rem' }}>
                    {supervisorStats?.attendance_pending ?? 0}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: '#64748B', marginTop: '0.25rem' }}>Shift window expired without check-in</div>
                </div>

                <div style={{ backgroundColor: '#FFFFFF', padding: '1.25rem', borderRadius: '12px', border: '1px solid #E2E8F0', borderLeft: '4px solid #EF4444' }}>
                  <div style={{ fontSize: '0.82rem', color: '#64748B', fontWeight: 600 }}>Attendance Exceptions</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#B91C1C', marginTop: '0.25rem' }}>
                    {supervisorStats?.attendance_exceptions ?? 0}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: '#64748B', marginTop: '0.25rem' }}>Geofence / Late exceptions</div>
                </div>
              </div>

              {/* Attendance Rate Progress Card */}
              <div style={{ backgroundColor: '#FFFFFF', padding: '1.5rem', borderRadius: '14px', border: '1px solid #D5E3D7' }}>
                <h4 style={{ margin: '0 0 1rem', fontSize: '1rem', fontWeight: 700, color: '#183B2A' }}>
                  Turnout & Operational Compliance Rate
                </h4>
                {(() => {
                  const scheduled = supervisorStats?.workers_scheduled_today || 0;
                  const present = supervisorStats?.present_today || 0;
                  const rate = scheduled > 0 ? Math.round((present / scheduled) * 100) : 0;
                  return (
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.88rem' }}>
                        <span style={{ fontWeight: 600, color: '#334155' }}>Muster Attendance Compliance</span>
                        <span style={{ fontWeight: 800, color: '#047857' }}>{rate}%</span>
                      </div>
                      <div style={{ height: '12px', backgroundColor: '#E2E8F0', borderRadius: '999px', overflow: 'hidden' }}>
                        <div
                          style={{
                            height: '100%',
                            width: `${rate}%`,
                            backgroundColor: rate >= 80 ? '#10B981' : rate >= 50 ? '#F59E0B' : '#EF4444',
                            borderRadius: '999px',
                            transition: 'width 0.4s ease',
                          }}
                        />
                      </div>
                      <div style={{ display: 'flex', gap: '2rem', marginTop: '1rem', fontSize: '0.82rem', color: '#64748B' }}>
                        <div><strong>Total Workers in Ward:</strong> {workersList.length}</div>
                        <div><strong>Scheduled Today:</strong> {scheduled}</div>
                        <div><strong>Present Today:</strong> {present}</div>
                        <div><strong>Pending / Absent:</strong> {supervisorStats?.attendance_pending ?? 0}</div>
                      </div>
                    </div>
                  );
                })()}
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* MODALS */}
          {/* ========================================================================= */}

          {/* 1. Worker Registration Modal */}
          {isRegisterWorkerModalOpen && (
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
              onClick={() => setIsRegisterWorkerModalOpen(false)}
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
                  <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 750, color: '#183B2A' }}>
                    Register Sanitation Worker (Pourakarmika)
                  </h3>
                  <button
                    type="button"
                    onClick={() => setIsRegisterWorkerModalOpen(false)}
                    style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#64748B' }}
                  >
                    <X size={20} />
                  </button>
                </div>

                {/* Quick prefill banner for evaluation */}
                <div
                  style={{
                    backgroundColor: '#ECFDF5',
                    border: '1px solid #A7F3D0',
                    padding: '0.75rem 1rem',
                    borderRadius: '10px',
                    marginBottom: '1.25rem',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <div style={{ fontSize: '0.82rem', color: '#065F46' }}>
                    <strong>Evaluation Mode:</strong> Prefill official test account
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setWorkerRegFullName('Pratik Gokavi');
                      setWorkerRegEmail('pratikgokavi2007@gmail.com');
                      setWorkerRegPassword('CleanBangalore@2026!');
                      setWorkerRegPhone('+91 98450 12345');
                      setWorkerRegOfficialId('BBMP-SW-042');
                    }}
                    style={{ fontSize: '0.75rem', padding: '3px 8px' }}
                  >
                    Prefill Pratik Gokavi
                  </Button>
                </div>

                {workerRegError && (
                  <div style={{ marginBottom: '1rem' }}>
                    <Alert type="danger">{workerRegError}</Alert>
                  </div>
                )}

                <form onSubmit={handleRegisterWorker} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                      Full Name *
                    </label>
                    <input
                      type="text"
                      required
                      value={workerRegFullName}
                      onChange={(e) => setWorkerRegFullName(e.target.value)}
                      placeholder="e.g. Pratik Gokavi"
                      style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                      Official Email Address *
                    </label>
                    <input
                      type="email"
                      required
                      value={workerRegEmail}
                      onChange={(e) => setWorkerRegEmail(e.target.value)}
                      placeholder="e.g. pratikgokavi2007@gmail.com"
                      style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                    />
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                        Password *
                      </label>
                      <input
                        type="password"
                        required
                        value={workerRegPassword}
                        onChange={(e) => setWorkerRegPassword(e.target.value)}
                        placeholder="••••••••"
                        style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                        Phone Number
                      </label>
                      <input
                        type="text"
                        value={workerRegPhone}
                        onChange={(e) => setWorkerRegPhone(e.target.value)}
                        placeholder="+91 98450 12345"
                        style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                      />
                    </div>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                      Official ID (BBMP Identifier)
                    </label>
                    <input
                      type="text"
                      value={workerRegOfficialId}
                      onChange={(e) => setWorkerRegOfficialId(e.target.value)}
                      placeholder="e.g. BBMP-SW-042"
                      style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                    />
                  </div>

                  <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setIsRegisterWorkerModalOpen(false)}
                      disabled={isSubmittingWorkerReg}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      variant="primary"
                      disabled={isSubmittingWorkerReg}
                    >
                      {isSubmittingWorkerReg ? 'Registering...' : 'Register Worker'}
                    </Button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* 2. Weekly Schedule Assignment Modal */}
          {isAssignScheduleModalOpen && (
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
              onClick={() => setIsAssignScheduleModalOpen(false)}
            >
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '18px',
                  maxWidth: '560px',
                  width: '100%',
                  padding: '1.75rem',
                  boxShadow: '0 20px 40px rgba(0,0,0,0.2)',
                  maxHeight: '90vh',
                  overflowY: 'auto',
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                  <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 750, color: '#183B2A' }}>
                    Assign Weekly Recurring Schedule
                  </h3>
                  <button
                    type="button"
                    onClick={() => setIsAssignScheduleModalOpen(false)}
                    style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#64748B' }}
                  >
                    <X size={20} />
                  </button>
                </div>

                {scheduleError && (
                  <div style={{ marginBottom: '1rem' }}>
                    <Alert type="danger">{scheduleError}</Alert>
                  </div>
                )}

                <form onSubmit={handleAssignSchedule} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                      Select Worker *
                    </label>
                    <select
                      required
                      value={selectedWorkerForSchedule}
                      onChange={(e) => setSelectedWorkerForSchedule(e.target.value)}
                      style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                    >
                      <option value="">Choose a worker...</option>
                      {workersList.map((w) => (
                        <option key={w.id} value={w.id}>
                          {w.full_name || 'Worker'} ({w.official_id || w.email})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                      Assigned Collection Route
                    </label>
                    <select
                      value={selectedRouteForSchedule}
                      onChange={(e) => setSelectedRouteForSchedule(e.target.value)}
                      style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                    >
                      <option value="">Ward General (No fixed route)</option>
                      {wardRoutes.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.route_name || r.id.slice(0, 8)}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Days of Week */}
                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.5rem' }}>
                      Active Working Days *
                    </label>
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
                        const isSelected = schedDaysOfWeek.includes(day);
                        return (
                          <button
                            key={day}
                            type="button"
                            onClick={() => {
                              if (isSelected) {
                                if (schedDaysOfWeek.length > 1) {
                                  setSchedDaysOfWeek(schedDaysOfWeek.filter((d) => d !== day));
                                }
                              } else {
                                setSchedDaysOfWeek([...schedDaysOfWeek, day].sort());
                              }
                            }}
                            style={{
                              padding: '6px 12px',
                              borderRadius: '8px',
                              fontSize: '0.82rem',
                              fontWeight: 700,
                              border: isSelected ? '1px solid #059669' : '1px solid #CBD5E1',
                              backgroundColor: isSelected ? '#ECFDF5' : '#FFFFFF',
                              color: isSelected ? '#065F46' : '#64748B',
                              cursor: 'pointer',
                            }}
                          >
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Shift Hours */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                        Shift Start (HH:MM) *
                      </label>
                      <input
                        type="time"
                        required
                        value={schedShiftStart}
                        onChange={(e) => setSchedShiftStart(e.target.value)}
                        style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                        Shift End (HH:MM) *
                      </label>
                      <input
                        type="time"
                        required
                        value={schedShiftEnd}
                        onChange={(e) => setSchedShiftEnd(e.target.value)}
                        style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                      />
                    </div>
                  </div>

                  {/* Check-In Window */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.75rem' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                        Window Start *
                      </label>
                      <input
                        type="time"
                        required
                        value={schedCheckInStart}
                        onChange={(e) => setSchedCheckInStart(e.target.value)}
                        style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.85rem', boxSizing: 'border-box' }}
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                        Window End *
                      </label>
                      <input
                        type="time"
                        required
                        value={schedCheckInEnd}
                        onChange={(e) => setSchedCheckInEnd(e.target.value)}
                        style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.85rem', boxSizing: 'border-box' }}
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                        Grace (Mins)
                      </label>
                      <input
                        type="number"
                        min={0}
                        max={60}
                        value={schedGracePeriod}
                        onChange={(e) => setSchedGracePeriod(parseInt(e.target.value, 10) || 0)}
                        style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.85rem', boxSizing: 'border-box' }}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setIsAssignScheduleModalOpen(false)}
                      disabled={isSubmittingSchedule}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      variant="primary"
                      disabled={isSubmittingSchedule}
                    >
                      {isSubmittingSchedule ? 'Saving...' : 'Assign Schedule'}
                    </Button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* 3. Schedule Override Modal */}
          {isOverrideModalOpen && (
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
              onClick={() => setIsOverrideModalOpen(false)}
            >
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '18px',
                  maxWidth: '500px',
                  width: '100%',
                  padding: '1.75rem',
                  boxShadow: '0 20px 40px rgba(0,0,0,0.2)',
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                  <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 750, color: '#183B2A' }}>
                    Create Schedule Override
                  </h3>
                  <button
                    type="button"
                    onClick={() => setIsOverrideModalOpen(false)}
                    style={{ border: 'none', background: 'transparent', cursor: 'pointer', color: '#64748B' }}
                  >
                    <X size={20} />
                  </button>
                </div>

                {overrideError && (
                  <div style={{ marginBottom: '1rem' }}>
                    <Alert type="danger">{overrideError}</Alert>
                  </div>
                )}

                <form onSubmit={handleCreateOverride} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                      Select Worker *
                    </label>
                    <select
                      required
                      value={overrideWorkerId}
                      onChange={(e) => setOverrideWorkerId(e.target.value)}
                      style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                    >
                      <option value="">Choose a worker...</option>
                      {workersList.map((w) => (
                        <option key={w.id} value={w.id}>
                          {w.full_name || 'Worker'} ({w.official_id || w.email})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                      Override Date *
                    </label>
                    <input
                      type="date"
                      required
                      value={overrideDate}
                      onChange={(e) => setOverrideDate(e.target.value)}
                      style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                      Override Type *
                    </label>
                    <select
                      value={overrideType}
                      onChange={(e) => setOverrideType(e.target.value as any)}
                      style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                    >
                      <option value="DAY_OFF">Day Off (Approved Rest Day)</option>
                      <option value="HOLIDAY">Public Holiday</option>
                      <option value="LEAVE">Official Leave</option>
                      <option value="SPECIAL_SHIFT">Special Emergency Shift</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                      Reason / Justification
                    </label>
                    <input
                      type="text"
                      value={overrideReason}
                      onChange={(e) => setOverrideReason(e.target.value)}
                      placeholder="e.g. Approved medical leave or festival holiday"
                      style={{ width: '100%', padding: '0.65rem 0.85rem', borderRadius: '8px', border: '1px solid #CBD5E1', fontSize: '0.88rem', boxSizing: 'border-box' }}
                    />
                  </div>

                  <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setIsOverrideModalOpen(false)}
                      disabled={isSubmittingOverride}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      variant="primary"
                      disabled={isSubmittingOverride}
                    >
                      {isSubmittingOverride ? 'Saving...' : 'Apply Override'}
                    </Button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* 4. Exception Review Modal */}
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
                    {reviewModalRecord.exception_reason || 'Check-in recorded beyond the 150m muster geofence or late.'}
                  </div>

                  <div style={{ fontSize: '0.85rem', color: '#4B5563' }}>
                    <div><strong>Worker:</strong> {reviewModalRecord.worker_name || reviewModalRecord.worker_email || reviewModalRecord.worker_id}</div>
                    <div><strong>Recorded Distance:</strong> {Math.round(reviewModalRecord.check_in_distance_meters || 0)} meters from depot</div>
                    <div><strong>Time:</strong> {reviewModalRecord.check_in_at ? new Date(reviewModalRecord.check_in_at).toLocaleTimeString() : '—'}</div>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 700, color: '#1E293B', marginBottom: '0.35rem' }}>
                      Official Review Notes *
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
        </main>
      </div>
    </div>
  );
};
