/**
 * NammaClean Domain TypeScript Types
 * Aligned with FastAPI backend models and Pydantic schemas.
 */

export type UserRole =
  | 'CITIZEN'
  | 'SANITATION_WORKER'
  | 'WARD_SUPERVISOR'
  | 'MUNICIPAL_ADMIN'
  | 'DRIVER';

export type UserStatus = 'ACTIVE' | 'PENDING' | 'DISABLED';

export interface User {
  id: string;
  email: string;
  role: UserRole;
  status: UserStatus;
  ward_id?: string;
  locality?: string;
  address?: string;
  created_at: string;
  updated_at: string;
}

export interface UserRegisterRequest {
  email: string;
  password: string;
}

export interface UserProfileUpdateRequest {
  ward_id?: string;
  locality?: string;
  address?: string;
}

export interface AdminUserCreateRequest {
  email: string;
  password: string;
  role: UserRole;
  status?: UserStatus;
}

export interface UserWardAssignment {
  id: string;
  user_id: string;
  ward_id: string;
  assigned_at: string;
  revoked_at?: string | null;
}

export interface AuthTokens {
  access_token: string;
  token_type: string;
}

export interface Ward {
  id: string;
  ward_code: string;
  display_name: string;
}

export interface MusterPoint {
  id: string;
  ward_id: string;
  name: string;
  geofence_radius_meters: number;
  is_active: boolean;
}

export type AttendanceStatus =
  | 'PRESENT'
  | 'ABSENT'
  | 'HALF_DAY'
  | 'EXCEPTION_PENDING'
  | 'REJECTED';

export interface AttendanceRecord {
  id: string;
  worker_id: string;
  ward_id: string;
  muster_point_id?: string;
  attendance_date: string;
  check_in_at?: string;
  check_out_at?: string;
  status: AttendanceStatus;
  check_in_distance_meters?: number;
  exception_reason?: string;
}

export interface QrIssueResponse {
  token: string;
  muster_point_id: string;
  ward_id: string;
  issued_at: string;
  expires_at: string;
  expires_in_seconds: number;
}

export interface QrCheckInPayload {
  qr_token: string;
  latitude: number;
  longitude: number;
  device_timestamp?: string;
}

export interface QrCheckInResponse {
  attendance_id: string;
  worker_id: string;
  ward_id: string;
  muster_point_id: string;
  attendance_date: string;
  check_in_at: string;
  status: AttendanceStatus;
  distance_meters: number;
  is_within_geofence: boolean;
  exception_reason?: string | null;
  message: string;
}

export interface AttendanceCheckOutPayload {
  latitude: number;
  longitude: number;
  ward_id?: string;
  muster_point_id?: string;
  device_timestamp?: string;
}

export interface AttendanceCheckOutResponse {
  attendance_id: string;
  worker_id: string;
  ward_id: string;
  muster_point_id?: string | null;
  attendance_date: string;
  check_in_at?: string | null;
  check_out_at: string;
  status: AttendanceStatus;
  distance_meters?: number | null;
  is_within_geofence: boolean;
  exception_reason?: string | null;
  message: string;
}

export interface AttendanceDailyItem {
  id: string;
  worker_id: string;
  worker_email?: string | null;
  ward_id: string;
  muster_point_id?: string | null;
  muster_point_name?: string | null;
  attendance_date: string;
  check_in_at?: string | null;
  check_out_at?: string | null;
  status: AttendanceStatus;
  check_in_distance_meters?: number | null;
  check_out_distance_meters?: number | null;
  exception_reason?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AttendanceDailyRosterResponse {
  ward_id: string;
  attendance_date: string;
  total_count: number;
  present_count: number;
  exception_pending_count: number;
  rejected_count: number;
  records: AttendanceDailyItem[];
}

export type AttendanceReviewAction = 'APPROVE' | 'REJECT';

export interface AttendanceReviewPayload {
  action: AttendanceReviewAction;
  review_notes?: string | null;
}

export interface AttendanceReviewResponse {
  attendance_id: string;
  worker_id: string;
  ward_id: string;
  attendance_date: string;
  previous_status: string;
  new_status: string;
  reviewed_by: string;
  reviewed_at: string;
  review_notes?: string | null;
  message: string;
}

export interface ApiErrorDetail {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
}

export interface ApiError {
  detail: string | ApiErrorDetail[];
  status?: number;
}

// ==========================================
// Illegal Dumping Reports & Evidence Types
// ==========================================

export type DumpingReportStatus =
  | 'SUBMITTED'
  | 'UNDER_REVIEW'
  | 'ACTION_SCHEDULED'
  | 'RESOLVED'
  | 'REJECTED';

export interface ReportEvidence {
  id: string;
  report_id: string;
  file_name: string;
  file_size_bytes: number;
  content_type: string;
  created_at: string;
}

export interface DumpingReportStatusHistoryItem {
  previous_status: string | null;
  new_status: string;
  changed_by_user_id: string;
  changed_by_role: string;
  notes?: string | null;
  timestamp: string;
}

export interface DumpingReport {
  id: string;
  reporter_id?: string | null;
  ward_id?: string | null;
  latitude: number;
  longitude: number;
  description: string;
  status: DumpingReportStatus;
  official_notes?: string | null;
  status_history: DumpingReportStatusHistoryItem[];
  evidence: ReportEvidence[];
  created_at: string;
  updated_at: string;
}

export interface DumpingReportCreatePayload {
  latitude: number;
  longitude: number;
  description: string;
  ward_id?: string | null;
}

export interface DumpingReportStatusUpdatePayload {
  status: DumpingReportStatus;
  official_notes?: string | null;
}

// ==========================================
// Vehicle Fleet, Telemetry & Public Map Types
// ==========================================

export type VehicleStatus =
  | 'IDLE'
  | 'ON_DUTY'
  | 'COLLECTING'
  | 'MAINTENANCE'
  | 'OFFLINE';

export type VehicleType =
  | 'AUTO_TIPPER'
  | 'COMPACTOR_TRUCK'
  | 'MECHANICAL_SWEEPER'
  | 'LORRY';

export interface Vehicle {
  id: string;
  registration_number: string;
  vehicle_type: VehicleType;
  status: VehicleStatus;
  assigned_ward_id?: string | null;
  assigned_driver_id?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  last_seen_at?: string | null;
  is_simulated: boolean;
  is_published: boolean;
  created_at: string;
  updated_at: string;
}

export interface VehiclePosition {
  id: string;
  vehicle_id: string;
  latitude: number;
  longitude: number;
  speed_kmh?: number | null;
  heading?: number | null;
  recorded_at: string;
  received_at: string;
  is_simulated: boolean;
}

export interface VehiclePositionCreatePayload {
  latitude: number;
  longitude: number;
  speed_kmh?: number | null;
  heading?: number | null;
  recorded_at: string;
  is_simulated?: boolean;
}

export interface PublicVehicle {
  id: string;
  registration_number?: string;
  vehicle_type: VehicleType;
  status: VehicleStatus;
  latitude?: number | null;
  longitude?: number | null;
  last_seen_at?: string | null;
  is_simulated: boolean;
  is_fresh: boolean;
}

export interface PublicCollectionPoint {
  id: string;
  ward_id: string;
  ward_name?: string | null;
  name: string;
  point_type: string;
  latitude: number;
  longitude: number;
}

export interface PublicRouteStop {
  stop_sequence: number;
  collection_point_id: string;
  collection_point_name?: string | null;
  point_type?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  planned_arrival_offset_minutes?: number | null;
}

export interface PublicRoute {
  id: string;
  ward_id: string;
  ward_name?: string | null;
  name: string;
  route_code?: string | null;
  coordinates: [number, number][]; // [longitude, latitude] GeoJSON coordinate pairs
  stops: PublicRouteStop[];
  is_simulated: boolean;
}

export interface PublicMapSummary {
  published_collection_points: number;
  published_routes: number;
  active_live_vehicles: number;
  freshness_threshold_minutes: number;
  generated_at: string;
  simulation_active: boolean;
  disclaimer: string;
}

