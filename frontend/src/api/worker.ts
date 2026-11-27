import { apiClient } from './client';
import type { AttendanceDailyItem } from './attendance';

export interface WorkerScheduleResponse {
  has_schedule: boolean;
  today_is_workday: boolean;
  today_reason?: string | null;
  is_override: boolean;
  override_type?: string | null;
  shift_start_time?: string | null;
  shift_end_time?: string | null;
  check_in_start_time?: string | null;
  check_in_end_time?: string | null;
  check_out_start_time?: string | null;
  check_out_end_time?: string | null;
  grace_period_minutes?: number | null;
  window_status: 'NOT_OPEN' | 'ON_TIME' | 'GRACE' | 'LATE_EXCEPTION' | 'CLOSED';
  window_message: string;
  can_check_in_now: boolean;
  route_id?: string | null;
  route_name?: string | null;
  days_of_week?: number[];
  upcoming_overrides?: Array<{
    override_date: string;
    override_type: string;
    reason?: string | null;
  }>;
}

export interface WorkerRouteResponse {
  route_id: string | null;
  route_name: string | null;
  description?: string | null;
  ward_id: string | null;
  ward_name?: string | null;
  waypoints: Array<[number, number]>;
  stops: Array<{
    id: string;
    name: string;
    sequence_order: number;
    latitude: number;
    longitude: number;
  }>;
}

export async function fetchWorkerSchedule(): Promise<WorkerScheduleResponse> {
  return apiClient.get<WorkerScheduleResponse>('/worker/schedule');
}

export async function fetchWorkerRoute(): Promise<WorkerRouteResponse> {
  return apiClient.get<WorkerRouteResponse>('/worker/route');
}

export async function fetchWorkerAttendanceHistory(
  limit: number = 30,
): Promise<AttendanceDailyItem[]> {
  return apiClient.get<AttendanceDailyItem[]>(`/worker/attendance/history?limit=${limit}`);
}
