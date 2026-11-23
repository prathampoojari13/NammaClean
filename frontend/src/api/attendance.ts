import { apiClient } from './client';

export interface AttendanceOtpIssueResponse {
  challenge_id: string;
  expires_in_seconds: number;
  worker_email: string;
  message: string;
  dev_otp?: string | null;
}

export interface AttendanceOtpVerifyResponse {
  challenge_id: string;
  verified: boolean;
  message: string;
}

export interface AttendanceCheckInResponse {
  attendance_id: string;
  worker_id: string;
  ward_id: string;
  muster_point_id: string;
  attendance_date: string;
  check_in_at: string;
  status: 'PRESENT' | 'EXCEPTION_PENDING' | 'REJECTED' | 'ABSENT' | 'HALF_DAY';
  distance_meters: number;
  is_within_geofence: boolean;
  exception_reason: string | null;
  message: string;
}

export interface AttendanceCheckOutResponse {
  attendance_id: string;
  worker_id: string;
  ward_id: string;
  muster_point_id: string;
  attendance_date: string;
  check_in_at: string;
  check_out_at: string;
  status: string;
  distance_meters: number | null;
  is_within_geofence: boolean;
  exception_reason: string | null;
  message: string;
}

export interface AttendanceDailyItem {
  id: string;
  worker_id: string;
  worker_email: string | null;
  ward_id: string;
  muster_point_id: string | null;
  muster_point_name: string | null;
  attendance_date: string;
  check_in_at: string | null;
  check_out_at: string | null;
  status: string;
  check_in_distance_meters: number | null;
  check_out_distance_meters: number | null;
  exception_reason: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AttendanceDailyRoster {
  ward_id: string;
  attendance_date: string;
  total_count: number;
  present_count: number;
  exception_pending_count: number;
  rejected_count: number;
  records: AttendanceDailyItem[];
}

export interface WorkerAssignment {
  worker_id: string;
  worker_email: string;
  ward_id: string | null;
  ward_number: number | null;
  ward_name: string | null;
  muster_point_id: string | null;
  muster_point_name: string | null;
  geofence_radius_meters: number | null;
}

export interface QrTokenIssueResponse {
  token: string;
  muster_point_id: string;
  ward_id: string;
  issued_at: string;
  expires_at: string;
  expires_in_seconds: number;
}

export interface MusterPoint {
  id: string;
  ward_id: string;
  name: string;
  latitude: number;
  longitude: number;
  geofence_radius_meters: number;
  is_active: boolean;
}

/**
 * Request a single-use Email OTP for attendance check-in.
 */
export async function requestAttendanceOtp(): Promise<AttendanceOtpIssueResponse> {
  return apiClient.post<AttendanceOtpIssueResponse>('/attendance/otp/request');
}

/**
 * Verify the 6-digit numeric OTP.
 */
export async function verifyAttendanceOtp(
  challengeId: string,
  otp: string
): Promise<AttendanceOtpVerifyResponse> {
  return apiClient.post<AttendanceOtpVerifyResponse>('/attendance/otp/verify', {
    challenge_id: challengeId,
    otp,
  });
}

/**
 * Submit attendance check-in following verified OTP and device GPS.
 */
export async function submitOtpAttendance(params: {
  challengeId: string;
  latitude: number;
  longitude: number;
  wardId?: string | null;
  musterPointId?: string | null;
}): Promise<AttendanceCheckInResponse> {
  return apiClient.post<AttendanceCheckInResponse>('/attendance/otp-check-in', {
    challenge_id: params.challengeId,
    latitude: params.latitude,
    longitude: params.longitude,
    ward_id: params.wardId || undefined,
    muster_point_id: params.musterPointId || undefined,
  });
}

/**
 * Submit shift check-out.
 */
export async function submitCheckOut(params: {
  latitude: number;
  longitude: number;
  wardId?: string | null;
  musterPointId?: string | null;
}): Promise<AttendanceCheckOutResponse> {
  return apiClient.post<AttendanceCheckOutResponse>('/attendance/check-out', {
    latitude: params.latitude,
    longitude: params.longitude,
    ward_id: params.wardId || undefined,
    muster_point_id: params.musterPointId || undefined,
  });
}

/**
 * Fetch worker's active attendance record for today.
 */
export async function getWorkerTodayAttendance(): Promise<AttendanceDailyItem | null> {
  try {
    const res = await apiClient.get<AttendanceDailyItem | null>('/attendance/today');
    return res && res.id ? res : null;
  } catch {
    return null;
  }
}

/**
 * Fetch worker's active assigned ward and muster station.
 */
export async function getWorkerAssignment(): Promise<WorkerAssignment | null> {
  try {
    return await apiClient.get<WorkerAssignment>('/attendance/worker-assignment');
  } catch {
    return null;
  }
}

/**
 * Supervisor: Issue 5-minute single-use QR token for roll-call attendance.
 */
export async function issueRollCallQr(
  wardId: string,
  musterPointId: string
): Promise<QrTokenIssueResponse> {
  return apiClient.post<QrTokenIssueResponse>(
    `/wards/${wardId}/muster-points/${musterPointId}/qr-code`
  );
}

/**
 * Supervisor: Query daily attendance roster for ward.
 */
export async function getDailyAttendanceRoster(
  wardId: string,
  attendanceDate?: string
): Promise<AttendanceDailyRoster> {
  const query = attendanceDate ? `?attendance_date=${attendanceDate}` : '';
  return apiClient.get<AttendanceDailyRoster>(`/wards/${wardId}/attendance/daily${query}`);
}

/**
 * Supervisor: Approve or reject an attendance exception.
 */
export async function reviewAttendanceRecord(params: {
  recordId: string;
  action: 'APPROVE' | 'REJECT';
  reviewNotes?: string;
}): Promise<void> {
  await apiClient.post(`/attendance/${params.recordId}/review`, {
    action: params.action,
    review_notes: params.reviewNotes,
  });
}

/**
 * Fetch muster points for a ward.
 */
export async function getWardMusterPoints(wardId: string): Promise<MusterPoint[]> {
  try {
    return await apiClient.get<MusterPoint[]>(`/wards/${wardId}/muster-points`);
  } catch {
    return [];
  }
}
