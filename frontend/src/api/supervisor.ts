import { apiClient } from './client';

export interface SupervisorDashboardStats {
  workers_scheduled_today: number;
  present_today: number;
  attendance_pending: number;
  attendance_exceptions: number;
  total_registered_workers: number;
  target_date: string;
  ward_id: string;
}

export interface SupervisorWorkerSummary {
  id: string;
  email: string;
  full_name?: string | null;
  phone_number?: string | null;
  official_id?: string | null;
  status: string;
  ward_id?: string | null;
  ward_name?: string | null;
  route_id?: string | null;
  route_name?: string | null;
  has_active_schedule: boolean;
  shift_start_time?: string | null;
  shift_end_time?: string | null;
  check_in_window_start?: string | null;
  check_in_window_end?: string | null;
  today_attendance_status?: string | null;
  today_check_in_at?: string | null;
  today_check_out_at?: string | null;
  created_at?: string;
}

export interface SupervisorWorkerRegisterRequest {
  email: string;
  password?: string;
  full_name: string;
  phone_number?: string;
  official_id?: string;
  ward_id?: string;
}

export interface WorkerScheduleCreateRequest {
  worker_id: string;
  ward_id?: string;
  route_id?: string;
  days_of_week: number[];
  shift_start_time: string;
  shift_end_time: string;
  check_in_start_time?: string;
  check_in_end_time?: string;
  check_out_start_time?: string;
  check_out_end_time?: string;
  grace_period_minutes?: number;
  effective_from?: string;
  effective_to?: string;
}

export interface ScheduleOverrideCreateRequest {
  worker_id: string;
  override_date: string;
  override_type: 'DAY_OFF' | 'HOLIDAY' | 'LEAVE' | 'SPECIAL_SHIFT';
  reason?: string;
  shift_start_time?: string;
  shift_end_time?: string;
  check_in_start_time?: string;
  check_in_end_time?: string;
}

export async function fetchSupervisorDashboardStats(
  wardId?: string,
  targetDate?: string,
): Promise<SupervisorDashboardStats> {
  const params = new URLSearchParams();
  if (wardId) params.append('ward_id', wardId);
  if (targetDate) params.append('target_date', targetDate);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<SupervisorDashboardStats>(`/supervisor/dashboard/stats${qs}`);
}

export async function fetchSupervisorWorkers(
  wardId?: string,
  search?: string,
  statusFilter?: string,
): Promise<SupervisorWorkerSummary[]> {
  const params = new URLSearchParams();
  if (wardId) params.append('ward_id', wardId);
  if (search) params.append('search', search);
  if (statusFilter && statusFilter !== 'ALL') params.append('status', statusFilter);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<SupervisorWorkerSummary[]>(`/supervisor/workers${qs}`);
}

export async function registerSupervisorWorker(
  data: SupervisorWorkerRegisterRequest,
): Promise<{ id: string; email: string; full_name: string; message: string }> {
  return apiClient.post<{ id: string; email: string; full_name: string; message: string }>(
    '/supervisor/workers',
    data,
  );
}

export async function toggleWorkerStatus(
  workerId: string,
  newStatus: 'ACTIVE' | 'DISABLED',
): Promise<{ id: string; status: string; message: string }> {
  return apiClient.patch<{ id: string; status: string; message: string }>(
    `/supervisor/workers/${workerId}/status`,
    { status: newStatus },
  );
}

export async function assignWorkerSchedule(
  data: WorkerScheduleCreateRequest,
): Promise<any> {
  return apiClient.post('/supervisor/schedules', data);
}

export async function createScheduleOverride(
  data: ScheduleOverrideCreateRequest,
): Promise<any> {
  return apiClient.post('/supervisor/schedules/overrides', data);
}
