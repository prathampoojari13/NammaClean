import { apiClient } from './client';
import { AdminUserCreateRequest, User, UserRole, UserStatus } from '../types';

export interface WorkforceMember {
  id: string;
  email: string;
  full_name?: string | null;
  official_id?: string | null;
  phone_number?: string | null;
  role: UserRole;
  status: UserStatus;
  ward_id?: string | null;
  ward_name?: string | null;
  assigned_vehicle?: {
    id: string;
    registration_number: string;
    vehicle_type: string;
    status: string;
  } | null;
  created_at: string;
}

/**
 * Administrator: Fetch entire municipal workforce roster with official IDs and assignments.
 */
export async function fetchWorkforce(role?: string): Promise<WorkforceMember[]> {
  const query = role ? `?role=${role}` : '';
  return apiClient.get<WorkforceMember[]>(`/admin/workforce${query}`);
}

/**
 * Administrator: Register a new operational user (Sanitation Worker, Driver, or Supervisor).
 */
export async function createOperationalUser(payload: AdminUserCreateRequest): Promise<User> {
  return apiClient.post<User>('/admin/users', payload);
}

/**
 * Administrator: Assign user to ward.
 */
export async function assignUserToWard(userId: string, wardId: string): Promise<any> {
  return apiClient.post(`/admin/users/${userId}/wards/${wardId}`, {});
}
