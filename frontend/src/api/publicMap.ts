import { apiClient } from './client';
import {
  PublicVehicle,
  PublicCollectionPoint,
  PublicRoute,
  PublicMapSummary,
} from '../types';

/**
 * Public Map API Service
 * Unauthenticated, public-safe geospatial endpoints for citizen tracking.
 * Excludes driver personal info, private identifiers, and unapproved records.
 */

export interface PublicMapQueryOptions {
  wardId?: string;
  limit?: number;
  signal?: AbortSignal;
}

/**
 * Fetch live published fleet vehicles with fresh locations.
 */
export async function fetchPublicVehicles(
  options: PublicMapQueryOptions = {}
): Promise<PublicVehicle[]> {
  const params = new URLSearchParams();
  if (options.wardId) params.set('ward_id', options.wardId);
  if (options.limit) params.set('limit', String(options.limit));

  const query = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<PublicVehicle[]>(`/public/map/vehicles${query}`, {
    signal: options.signal,
  });
}

/**
 * Fetch a single published vehicle by its UUID.
 */
export async function fetchPublicVehicle(
  vehicleId: string,
  signal?: AbortSignal
): Promise<PublicVehicle> {
  return apiClient.get<PublicVehicle>(`/public/map/vehicles/${vehicleId}`, {
    signal,
  });
}

/**
 * Fetch published waste collection points for a ward or city-wide.
 */
export async function fetchPublicCollectionPoints(
  options: PublicMapQueryOptions = {}
): Promise<PublicCollectionPoint[]> {
  const params = new URLSearchParams();
  if (options.wardId) params.set('ward_id', options.wardId);
  if (options.limit) params.set('limit', String(options.limit));

  const query = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<PublicCollectionPoint[]>(
    `/public/map/collection-points${query}`,
    { signal: options.signal }
  );
}

/**
 * Fetch published collection routes with ordered stops and paths.
 */
export async function fetchPublicRoutes(
  options: PublicMapQueryOptions = {}
): Promise<PublicRoute[]> {
  const params = new URLSearchParams();
  if (options.wardId) params.set('ward_id', options.wardId);
  if (options.limit) params.set('limit', String(options.limit));

  const query = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<PublicRoute[]>(`/public/map/routes${query}`, {
    signal: options.signal,
  });
}

/**
 * Fetch public map summary civic metrics (active counts, freshness threshold, disclaimer).
 */
export async function fetchPublicMapSummary(
  wardId?: string,
  signal?: AbortSignal
): Promise<PublicMapSummary> {
  const params = new URLSearchParams();
  if (wardId) params.set('ward_id', wardId);
  const queryString = params.toString();
  const query = queryString ? `?${queryString}` : '';
  return apiClient.get<PublicMapSummary>(`/public/map/summary${query}`, {
    signal,
  });
}
