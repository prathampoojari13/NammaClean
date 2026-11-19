import type { PublicVehicle } from '../types';

/** A current position must be fresh according to both the API and its timestamp. */
export const hasCurrentVehicleSignal = (
  vehicle: PublicVehicle,
  freshnessMinutes: number | null,
  now: number = Date.now()
): boolean => {
  if (!vehicle.is_fresh || freshnessMinutes === null || freshnessMinutes <= 0 || !vehicle.last_seen_at) {
    return false;
  }

  const lastSeen = Date.parse(vehicle.last_seen_at);
  return Number.isFinite(lastSeen) && lastSeen <= now && now - lastSeen < freshnessMinutes * 60_000;
};
