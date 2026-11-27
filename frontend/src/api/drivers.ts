import { apiClient } from './client';
import {
  DriverSummary,
  DriverCreatePayload,
  DriverUpdatePayload,
  DriverLocationPingPayload,
  DriverLocationPingResponse,
  DriverMeResponse,
  DriverDutyStartPayload,
  DriverDutyEndPayload,
} from '../types';

export interface DriverQueryOptions {
  q?: string;
  wardId?: string;
  status?: string;
}

/**
 * Official: Query registered drivers with duty status and vehicle assignments.
 */
export async function fetchDrivers(options: DriverQueryOptions = {}): Promise<DriverSummary[]> {
  const params = new URLSearchParams();
  if (options.q && options.q.trim()) params.set('q', options.q.trim());
  if (options.wardId) params.set('ward_id', options.wardId);
  if (options.status) params.set('status', options.status);

  const query = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<DriverSummary[]>(`/drivers${query}`);
}

/**
 * Official: Register a new Driver account.
 */
export async function createDriver(payload: DriverCreatePayload): Promise<DriverSummary> {
  return apiClient.post<DriverSummary>('/drivers', payload);
}

/**
 * Official: Update driver metadata or account status (activate/deactivate).
 */
export async function updateDriver(
  driverId: string,
  payload: DriverUpdatePayload
): Promise<DriverSummary> {
  return apiClient.patch<DriverSummary>(`/drivers/${driverId}`, payload);
}

/**
 * Official: Assign or reassign a vehicle to a driver.
 */
export async function assignDriverVehicle(
  driverId: string,
  vehicleId: string | null
): Promise<DriverSummary> {
  return apiClient.post<DriverSummary>(`/drivers/${driverId}/assign-vehicle`, {
    vehicle_id: vehicleId,
  });
}

/**
 * Driver: Fetch personal profile, assigned vehicle, duty status, and ward/route.
 */
export async function getDriverMe(): Promise<DriverMeResponse> {
  return apiClient.get<DriverMeResponse>('/drivers/me');
}

/**
 * Driver: Start duty session with optional initial GPS coordinates and pre-trip inspection checklist.
 */
export async function startDriverDuty(payload?: DriverDutyStartPayload): Promise<DriverMeResponse> {
  return apiClient.post<DriverMeResponse>('/drivers/me/duty/start', payload || {});
}

/**
 * Driver: End current duty session with optional post-trip inspection checklist.
 */
export async function endDriverDuty(payload?: DriverDutyEndPayload): Promise<DriverMeResponse> {
  return apiClient.post<DriverMeResponse>('/drivers/me/duty/end', payload || {});
}

/**
 * Driver: Send real-time GPS position telemetry update from browser/phone.
 */
export async function sendDriverLocationPing(
  payload: DriverLocationPingPayload
): Promise<DriverLocationPingResponse> {
  return apiClient.post<DriverLocationPingResponse>('/drivers/me/location', payload);
}
