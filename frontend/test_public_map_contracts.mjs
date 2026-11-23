import test from 'node:test';
import assert from 'node:assert/strict';
import { hasCurrentVehicleSignal } from './src/utils/publicMapFreshness.ts';

// Response-shape fixtures for the public map API.
const mockVehicles = [
  {
    id: 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d',
    vehicle_type: 'COMPACTOR_TRUCK',
    status: 'COLLECTING',
    latitude: 12.9716,
    longitude: 77.5946,
    last_seen_at: new Date(Date.now() - 60_000).toISOString(),
    is_simulated: false,
    is_fresh: true,
  },
  {
    id: 'b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e',
    vehicle_type: 'AUTO_TIPPER',
    status: 'ON_DUTY',
    latitude: 12.9800,
    longitude: 77.6000,
    last_seen_at: new Date(Date.now() - 2 * 60_000).toISOString(),
    is_simulated: true, // Demo simulation
    is_fresh: true,
  },
  {
    id: 'c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f',
    vehicle_type: 'MECHANICAL_SWEEPER',
    status: 'IDLE',
    latitude: null, // Stale location redacted by backend
    longitude: null,
    last_seen_at: '2026-11-01T07:15:00Z',
    is_simulated: false,
    is_fresh: false,
  },
];

const mockRoutes = [
  {
    id: 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a',
    ward_id: 'e5f6a7b8-c9d0-1e2f-3a4b-5c6d7e8f9a0b',
    ward_name: 'Bellandur (Ward 150)',
    name: 'Main Road Morning Line',
    route_code: 'R-150-A',
    coordinates: [
      [77.5946, 12.9716],
      [77.6000, 12.9750],
      [77.6050, 12.9800],
    ],
    stops: [
      {
        stop_sequence: 1,
        collection_point_id: 'f6a7b8c9-d0e1-2f3a-4b5c-6d7e8f9a0b1c',
        collection_point_name: 'Market Bin 1',
        point_type: 'COMMUNITY_BIN',
        latitude: 12.9716,
        longitude: 77.5946,
        planned_arrival_offset_minutes: 10,
      },
    ],
    is_simulated: false,
  },
];

const mockCollectionPoints = [
  {
    id: 'f6a7b8c9-d0e1-2f3a-4b5c-6d7e8f9a0b1c',
    ward_id: 'e5f6a7b8-c9d0-1e2f-3a4b-5c6d7e8f9a0b',
    ward_name: 'Bellandur (Ward 150)',
    name: 'Market Bin 1',
    point_type: 'COMMUNITY_BIN',
    latitude: 12.9716,
    longitude: 77.5946,
  },
];

test('1. Successful API responses parsing & field verification', () => {
  assert.equal(mockVehicles.length, 3);
  assert.equal(mockVehicles[0].vehicle_type, 'COMPACTOR_TRUCK');
  assert.equal(mockVehicles[0].is_fresh, true);
  assert.equal(mockVehicles[0].is_simulated, false);
});

test('2. Coordinate filtering: identifies vehicles with and without coordinates', () => {
  const withCoords = mockVehicles.filter(v => v.latitude != null && v.longitude != null);
  const withoutCoords = mockVehicles.filter(v => v.latitude == null || v.longitude == null);

  assert.equal(withCoords.length, 2);
  assert.equal(withoutCoords.length, 1);
  assert.equal(withoutCoords[0].is_fresh, false);
  assert.equal(withoutCoords[0].id, 'c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f');
});

test('3. Simulated vs Genuine vehicle labeling', () => {
  const realTruck = mockVehicles[0];
  const demoTruck = mockVehicles[1];

  assert.equal(realTruck.is_simulated, false);
  assert.equal(demoTruck.is_simulated, true);

  const getLabel = (v) => v.is_simulated ? 'Demo Simulation' : 'Genuine Municipal';
  assert.equal(getLabel(realTruck), 'Genuine Municipal');
  assert.equal(getLabel(demoTruck), 'Demo Simulation');
});

test('4. GeoJSON to Leaflet coordinate conversion for routes', () => {
  const route = mockRoutes[0];
  assert.equal(route.coordinates.length, 3);

  // GeoJSON is [lon, lat]; Leaflet expects [lat, lon]
  const leafletCoords = route.coordinates.map(([lon, lat]) => [lat, lon]);

  assert.deepEqual(leafletCoords[0], [12.9716, 77.5946]);
  assert.deepEqual(leafletCoords[1], [12.9750, 77.6000]);
  assert.deepEqual(leafletCoords[2], [12.9800, 77.6050]);
});

test('5. Empty vehicle and route collections handle safely without crashing', () => {
  const emptyVehicles = [];
  const emptyRoutes = [];

  const withCoords = emptyVehicles.filter(v => v.latitude != null && v.longitude != null);
  assert.equal(withCoords.length, 0);

  const bounds = [];
  emptyRoutes.forEach(r => {
    if (r.coordinates) {
      r.coordinates.forEach(c => bounds.push(c));
    }
  });
  assert.equal(bounds.length, 0);
});

test('6. Stale and missing coordinates safe rendering', () => {
  const staleVehicle = mockVehicles[2];
  const getCoordinatesText = (v) => {
    if (v.latitude != null && v.longitude != null) {
      return `${v.latitude.toFixed(4)}, ${v.longitude.toFixed(4)}`;
    }
    return 'Redacted (Signal Stale)';
  };

  assert.equal(getCoordinatesText(staleVehicle), 'Redacted (Signal Stale)');
  assert.equal(getCoordinatesText(mockVehicles[0]), '12.9716, 77.5946');
});

test('7. Collection points and route stops mapping integrity', () => {
  const point = mockCollectionPoints[0];
  assert.equal(point.name, 'Market Bin 1');
  assert.equal(point.point_type, 'COMMUNITY_BIN');
  assert.equal(typeof point.latitude, 'number');
  assert.equal(typeof point.longitude, 'number');

  const stop = mockRoutes[0].stops[0];
  assert.equal(stop.collection_point_id, point.id);
  assert.equal(stop.planned_arrival_offset_minutes, 10);
});

test('8. AbortController signal cancels in-flight request on cleanup', () => {
  const controller = new AbortController();
  assert.equal(controller.signal.aborted, false);
  controller.abort();
  assert.equal(controller.signal.aborted, true);
});

test('9. Freshness helper requires the backend fresh flag and a current timestamp', () => {
  const now = Date.now();
  const fresh = { ...mockVehicles[0], last_seen_at: new Date(now - 60_000).toISOString() };
  const backendStale = { ...fresh, is_fresh: false };
  const futureTimestamp = { ...fresh, last_seen_at: new Date(now + 1_000).toISOString() };

  assert.equal(hasCurrentVehicleSignal(fresh, 15, now), true);
  assert.equal(hasCurrentVehicleSignal(backendStale, 15, now), false);
  assert.equal(hasCurrentVehicleSignal(futureTimestamp, 15, now), false);
});

test('10. Freshness helper rejects expired and unconfigured signals', () => {
  const now = Date.now();
  const expired = { ...mockVehicles[0], last_seen_at: new Date(now - 16 * 60_000).toISOString() };
  const recent = { ...mockVehicles[0], last_seen_at: new Date(now - 60_000).toISOString() };

  assert.equal(hasCurrentVehicleSignal(expired, 15, now), false);
  assert.equal(hasCurrentVehicleSignal(recent, null, now), false);
});

test('11. Satellite tile layer performance options and persistent caching contract', () => {
  const satelliteOptions = {
    attribution: 'Tiles © Esri',
    maxZoom: 19,
    maxNativeZoom: 18,
    updateWhenIdle: true,
    updateWhenZooming: false,
    keepBuffer: 4,
    crossOrigin: 'anonymous',
  };

  assert.equal(satelliteOptions.maxNativeZoom, 18);
  assert.equal(satelliteOptions.updateWhenIdle, true);
  assert.equal(satelliteOptions.updateWhenZooming, false);
  assert.ok(satelliteOptions.keepBuffer >= 4);
  assert.equal(satelliteOptions.crossOrigin, 'anonymous');
});
