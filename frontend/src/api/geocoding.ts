import { apiClient } from './client';

export interface PlaceSearchResult {
  place_id: string;
  display_name: string;
  latitude: number;
  longitude: number;
  locality?: string;
  zone?: string;
}

export interface ReverseGeocodeResult {
  display_name: string;
  locality?: string;
  latitude: number;
  longitude: number;
  selection_method: string;
}

export async function searchPlaces(query: string): Promise<PlaceSearchResult[]> {
  if (!query || query.trim().length < 2) return [];
  try {
    return await apiClient.get<PlaceSearchResult[]>(`/geocoding/search?q=${encodeURIComponent(query.trim())}`);
  } catch {
    return [];
  }
}

export async function reverseGeocode(
  latitude: number,
  longitude: number,
  method: 'gps' | 'search' | 'manual' = 'manual'
): Promise<ReverseGeocodeResult> {
  try {
    return await apiClient.get<ReverseGeocodeResult>(
      `/geocoding/reverse?latitude=${latitude}&longitude=${longitude}&method=${method}`
    );
  } catch {
    return {
      display_name: `Location (${latitude.toFixed(4)}, ${longitude.toFixed(4)})`,
      latitude,
      longitude,
      selection_method: method,
    };
  }
}
