import React, { useEffect, useRef, useState, useCallback, type ReactNode } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { AlertTriangle, Crosshair, MapPin, RefreshCw } from 'lucide-react';
import {
  fetchPublicVehicles,
  fetchPublicRoutes,
  fetchPublicCollectionPoints,
  fetchPublicMapSummary,
  fetchPilotZoneInfo,
  PilotZoneInfo,
} from '../../api/publicMap';
import {
  PublicVehicle,
  PublicRoute,
  PublicCollectionPoint,
  PublicMapSummary,
} from '../../types';
import { Spinner } from '../ui/Spinner';
import { hasCurrentVehicleSignal } from '../../utils/publicMapFreshness';

const DEFAULT_CENTER: [number, number] = [12.9716, 77.5946];
const DEFAULT_ZOOM = 12;
const AUTO_REFRESH_INTERVAL_MS = 25000;

type TelemetrySource = 'unavailable' | 'api';

const isValidMapCoordinate = (latitude: unknown, longitude: unknown): boolean =>
  typeof latitude === 'number' &&
  typeof longitude === 'number' &&
  Number.isFinite(latitude) &&
  Number.isFinite(longitude) &&
  latitude >= -90 &&
  latitude <= 90 &&
  longitude >= -180 &&
  longitude <= 180;

const errorMessage = (reason: unknown): string => {
  if (typeof reason === 'object' && reason !== null && 'detail' in reason) {
    const detail = reason.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const messages = detail.flatMap((item) =>
        typeof item === 'object' && item !== null && 'msg' in item && typeof item.msg === 'string'
          ? [item.msg]
          : []
      );
      if (messages.length > 0) return messages.join('; ');
    }
  }
  if (reason instanceof Error) return reason.message;
  return 'An unexpected network error occurred.';
};

const escapeHtml = (value: string) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

const formatStatus = (value: string) =>
  value
    .split('_')
    .map((word) => word.charAt(0) + word.slice(1).toLowerCase())
    .join(' ');

const formatAgo = (date: Date | null) => {
  if (!date) return 'Unknown';
  const mins = Math.floor((Date.now() - date.getTime()) / 60000);
  if (mins <= 0) return 'Just now';
  if (mins === 1) return '1 min ago';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  return `${hours} hr${hours > 1 ? 's' : ''} ago`;
};

const vehiclePlate = (vehicle: PublicVehicle) =>
  vehicle.registration_number ||
  (vehicle.id.startsWith('KA-') ? vehicle.id : 'Published vehicle');

const signalPhrase = (vehicle: PublicVehicle, source: TelemetrySource, isFresh: boolean) => {
  const status = formatStatus(vehicle.status);
  if (vehicle.is_simulated) {
    return { text: `${status} • Demo`, dot: '#E8943A' };
  }
  if (source === 'api' && isFresh) {
    return { text: `${status} • Fresh`, dot: '#16A34A' };
  }
  if (source === 'api' && !isFresh) {
    return { text: `${status} • Stale`, dot: '#D97706' };
  }
  return { text: status, dot: '#9CA3AF' };
};

const createVehicleIcon = (isSimulated: boolean, isFresh: boolean, isSelected: boolean) => {
  const primaryColor = isSimulated
    ? isFresh
      ? '#E8943A'
      : '#C4A574'
    : isFresh
      ? '#1F8A4C'
      : '#9CA3AF';
  const cabColor = isSimulated
    ? isFresh
      ? '#C46A12'
      : '#A1845A'
    : isFresh
      ? '#146B3A'
      : '#6B7280';
  const strokeColor = isSelected ? '#145C34' : '#0B291D';
  const strokeWidth = isSelected ? '2.5' : '1.5';

  const html = `
    <div style="cursor: pointer; width: 44px; height: 32px; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));">
      <svg width="44" height="32" viewBox="0 0 44 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="2" y="4" width="26" height="18" rx="3" fill="${primaryColor}" stroke="${strokeColor}" stroke-width="${strokeWidth}"/>
        <rect x="6" y="7" width="2" height="12" fill="white" opacity="0.35"/>
        <rect x="11" y="7" width="2" height="12" fill="white" opacity="0.35"/>
        <rect x="16" y="7" width="2" height="12" fill="white" opacity="0.35"/>
        <path d="M28 9 L34 9 L39 15 L39 22 L28 22 Z" fill="${cabColor}" stroke="${strokeColor}" stroke-width="${strokeWidth}"/>
        <path d="M30 11 L33 11 L37 15 L30 15 Z" fill="#E0F2FE"/>
        <circle cx="10" cy="23" r="5" fill="#1F2937" stroke="#9CA3AF" stroke-width="1.5"/>
        <circle cx="33" cy="23" r="5" fill="#1F2937" stroke="#9CA3AF" stroke-width="1.5"/>
      </svg>
    </div>
  `;

  return L.divIcon({
    className: `custom-vehicle-marker ${isSelected ? 'is-selected' : ''}`,
    html,
    iconSize: [44, 32],
    iconAnchor: [22, 23],
    popupAnchor: [0, -22],
  });
};

const createCollectionPointIcon = () => {
  const html = `
    <div style="cursor: pointer; width: 28px; height: 32px; filter: drop-shadow(0 2px 3px rgba(0,0,0,0.25));">
      <svg width="26" height="30" viewBox="0 0 24 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="4" y="8" width="16" height="17" rx="3" fill="#2D6A4F" stroke="#1B4332" stroke-width="1.5"/>
        <rect x="7" y="11" width="2" height="11" rx="1" fill="#FFFFFF" opacity="0.4"/>
        <rect x="11" y="11" width="2" height="11" rx="1" fill="#FFFFFF" opacity="0.4"/>
        <rect x="15" y="11" width="2" height="11" rx="1" fill="#FFFFFF" opacity="0.4"/>
        <rect x="2" y="4" width="20" height="4" rx="2" fill="#1B4332"/>
        <rect x="9" y="2" width="6" height="2" rx="1" fill="#1B4332"/>
      </svg>
    </div>
  `;

  return L.divIcon({
    className: 'custom-point-marker',
    html,
    iconSize: [28, 32],
    iconAnchor: [14, 25],
    popupAnchor: [0, -24],
  });
};

export interface PublicVehicleMapProps {
  wardId?: string;
  selectedVehicle?: PublicVehicle | null;
  onVehicleSelect?: (vehicle: PublicVehicle | null) => void;
  onSummaryLoaded?: (summary: PublicMapSummary) => void;
  details?: ReactNode;
}

const LegendRow: React.FC<{ swatch: ReactNode; label: string }> = ({ swatch, label }) => (
  <div className="nc-map-legend-row">
    <span className="nc-map-legend-swatch">{swatch}</span>
    <span className="nc-map-legend-row-label">{label}</span>
  </div>
);

export const PublicVehicleMap: React.FC<PublicVehicleMapProps> = ({
  wardId,
  selectedVehicle,
  onVehicleSelect,
  onSummaryLoaded,
  details,
}) => {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const routesLayerRef = useRef<L.LayerGroup | null>(null);
  const pilotLayerRef = useRef<L.LayerGroup | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const selectedVehicleRef = useRef(selectedVehicle);
  const hasAutoSelectedVehicleRef = useRef(false);
  const hasFittedDataBoundsRef = useRef(false);

  const [vehicles, setVehicles] = useState<PublicVehicle[]>([]);
  const [routes, setRoutes] = useState<PublicRoute[]>([]);
  const [points, setPoints] = useState<PublicCollectionPoint[]>([]);
  const [pilotInfo, setPilotInfo] = useState<PilotZoneInfo | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  const [telemetrySource, setTelemetrySource] = useState<TelemetrySource>('unavailable');
  const [freshnessMinutes, setFreshnessMinutes] = useState<number | null>(null);
  const [summaryDisclaimer, setSummaryDisclaimer] = useState<string | null>(null);
  const [freshnessClock, setFreshnessClock] = useState(0);
  const [tileError, setTileError] = useState(false);
  const [mapMode, setMapMode] = useState<'street' | 'satellite'>('street');
  const [isSatelliteLoading, setIsSatelliteLoading] = useState(false);
  const mapModeRef = useRef<'street' | 'satellite'>(mapMode);
  const streetTileLayerRef = useRef<L.TileLayer | null>(null);
  const satelliteTileLayerRef = useRef<L.TileLayer | null>(null);
  const failedTilesCountRef = useRef(0);

  useEffect(() => {
    selectedVehicleRef.current = selectedVehicle;
  }, [selectedVehicle]);

  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      zoomControl: true,
    });

    const routesLayer = L.layerGroup().addTo(map);
    const pilotLayer = L.layerGroup().addTo(map);
    const markersLayer = L.layerGroup().addTo(map);

    mapInstanceRef.current = map;
    routesLayerRef.current = routesLayer;
    pilotLayerRef.current = pilotLayer;
    markersLayerRef.current = markersLayer;

    // 1. Street layer with smooth buffer and viewport-idle rendering
    const streetLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
      updateWhenIdle: true,
      updateWhenZooming: false,
      keepBuffer: 4,
      crossOrigin: 'anonymous',
    });
    streetLayer.addTo(map);
    streetTileLayerRef.current = streetLayer;

    // 2. Satellite layer (Esri World Imagery) with maxNativeZoom, buffer & idle rendering
    const satelliteLayer = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      {
        attribution:
          'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
        maxZoom: 19,
        maxNativeZoom: 18,
        updateWhenIdle: true,
        updateWhenZooming: false,
        keepBuffer: 4,
        crossOrigin: 'anonymous',
      }
    );

    satelliteLayer.on('loading', () => {
      setIsSatelliteLoading(true);
    });
    satelliteLayer.on('load', () => {
      setIsSatelliteLoading(false);
      failedTilesCountRef.current = 0;
      setTileError(false);
    });
    satelliteLayer.on('tileerror', () => {
      failedTilesCountRef.current += 1;
      // Only trigger error alert if multiple tiles fail
      if (failedTilesCountRef.current >= 4) {
        setTileError(true);
        setIsSatelliteLoading(false);
      }
    });

    satelliteTileLayerRef.current = satelliteLayer;

    const onResize = () => map.invalidateSize({ pan: false });
    const resizeObserver = new ResizeObserver(onResize);
    resizeObserver.observe(mapContainerRef.current);
    window.addEventListener('resize', onResize);
    const initialResize = window.requestAnimationFrame(onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      resizeObserver.disconnect();
      window.cancelAnimationFrame(initialResize);
      map.remove();
      mapInstanceRef.current = null;
      streetTileLayerRef.current = null;
      satelliteTileLayerRef.current = null;
      routesLayerRef.current = null;
      pilotLayerRef.current = null;
      markersLayerRef.current = null;
    };
  }, []);

  useEffect(() => {
    mapModeRef.current = mapMode;
  }, [mapMode]);

  // Manage Street vs Satellite Tile Layer Switching seamlessly without destroying layer instances
  useEffect(() => {
    const map = mapInstanceRef.current;
    const streetLayer = streetTileLayerRef.current;
    const satelliteLayer = satelliteTileLayerRef.current;
    if (!map || !streetLayer || !satelliteLayer) return;

    if (mapMode === 'satellite') {
      setIsSatelliteLoading(true);
      if (!map.hasLayer(satelliteLayer)) {
        map.addLayer(satelliteLayer);
      }

      // Smooth transition: remove street layer once satellite tiles begin displaying
      const onSatelliteLoaded = () => {
        if (map.hasLayer(streetLayer) && mapModeRef.current === 'satellite') {
          map.removeLayer(streetLayer);
        }
        satelliteLayer.off('load', onSatelliteLoaded);
      };
      satelliteLayer.once('load', onSatelliteLoaded);

      const fallbackTimer = window.setTimeout(() => {
        if (map.hasLayer(streetLayer) && mapModeRef.current === 'satellite') {
          map.removeLayer(streetLayer);
        }
      }, 700);

      return () => {
        window.clearTimeout(fallbackTimer);
        satelliteLayer.off('load', onSatelliteLoaded);
      };
    } else {
      if (!map.hasLayer(streetLayer)) {
        map.addLayer(streetLayer);
      }
      if (map.hasLayer(satelliteLayer)) {
        map.removeLayer(satelliteLayer);
      }
      setTileError(false);
      setIsSatelliteLoading(false);
    }
  }, [mapMode]);

  const loadMapData = useCallback(
    async (isBackground: boolean = false) => {
      if (!isBackground) {
        setLoading(true);
      } else {
        setRefreshing(true);
      }

      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;

      setError(null);

      try {
        const [vehiclesRes, routesRes, pointsRes, summaryRes, pilotRes] = await Promise.allSettled([
          fetchPublicVehicles({ wardId, signal: controller.signal }),
          fetchPublicRoutes({ wardId, signal: controller.signal }),
          fetchPublicCollectionPoints({ wardId, signal: controller.signal }),
          fetchPublicMapSummary(wardId, controller.signal),
          fetchPilotZoneInfo(controller.signal),
        ]);

        if (controller.signal.aborted) return;

        if (pilotRes.status === 'fulfilled') {
          setPilotInfo(pilotRes.value);
        }

        if (vehiclesRes.status === 'fulfilled') {
          const vList = vehiclesRes.value;
          setVehicles(vList);
          setTelemetrySource('api');
          const currentVehicle = selectedVehicleRef.current;
          if (currentVehicle) {
            onVehicleSelect?.(vList.find((vehicle) => vehicle.id === currentVehicle.id) ?? null);
          } else if (!hasAutoSelectedVehicleRef.current) {
            const responseFreshness =
              summaryRes.status === 'fulfilled' ? summaryRes.value.freshness_threshold_minutes : null;
            const firstMappableVehicle = vList.find(
              (vehicle) =>
                isValidMapCoordinate(vehicle.latitude, vehicle.longitude) &&
                hasCurrentVehicleSignal(vehicle, responseFreshness)
            );
            if (firstMappableVehicle) {
              hasAutoSelectedVehicleRef.current = true;
              onVehicleSelect?.(firstMappableVehicle);
            }
          }
        }

        if (routesRes.status === 'fulfilled') {
          setRoutes(routesRes.value);
        }

        if (pointsRes.status === 'fulfilled') {
          setPoints(pointsRes.value);
        }

        if (summaryRes.status === 'fulfilled') {
          setFreshnessMinutes(summaryRes.value.freshness_threshold_minutes);
          setSummaryDisclaimer(summaryRes.value.disclaimer);
          onSummaryLoaded?.(summaryRes.value);
        }

        const failures: string[] = [];
        if (vehiclesRes.status === 'rejected') {
          failures.push(`vehicle positions: ${errorMessage(vehiclesRes.reason)}`);
        }
        if (routesRes.status === 'rejected') {
          failures.push(`routes: ${errorMessage(routesRes.reason)}`);
        }
        if (pointsRes.status === 'rejected') {
          failures.push(`collection points: ${errorMessage(pointsRes.reason)}`);
        }
        if (summaryRes.status === 'rejected') {
          failures.push(`map summary: ${errorMessage(summaryRes.reason)}`);
        }
        setError(failures.length > 0 ? `Some map data could not be loaded — ${failures.join('; ')}` : null);

        if (failures.length === 0) {
          setLastRefreshedAt(new Date());
        }
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setError(errorMessage(err));
        }
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [wardId, onVehicleSelect, onSummaryLoaded]
  );

  useEffect(() => {
    loadMapData(false);

    const intervalId = window.setInterval(() => {
      loadMapData(true);
    }, AUTO_REFRESH_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
    };
  }, [loadMapData]);

  useEffect(() => {
    hasFittedDataBoundsRef.current = false;
  }, [wardId]);

  useEffect(() => {
    if (freshnessMinutes === null) return;

    const now = Date.now();
    const nextExpiry = vehicles.reduce<number | null>((soonest, vehicle) => {
      if (!vehicle.is_fresh || !vehicle.last_seen_at) return soonest;
      const timestamp = Date.parse(vehicle.last_seen_at);
      if (!Number.isFinite(timestamp) || timestamp > now) return soonest;
      const expiry = timestamp + freshnessMinutes * 60_000;
      if (expiry <= now) return soonest;
      return soonest === null ? expiry : Math.min(soonest, expiry);
    }, null);

    if (nextExpiry === null) return;
    const timeoutId = window.setTimeout(
      () => setFreshnessClock((clock) => clock + 1),
      Math.max(0, nextExpiry - now + 25)
    );
    return () => window.clearTimeout(timeoutId);
  }, [vehicles, freshnessMinutes, freshnessClock]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    const routesLayer = routesLayerRef.current;
    const markersLayer = markersLayerRef.current;
    if (!map || !routesLayer || !markersLayer) return;

    routesLayer.clearLayers();
    markersLayer.clearLayers();

    const bounds = L.latLngBounds([]);

    routes.forEach((route) => {
      if (route.coordinates && route.coordinates.length > 0) {
        const latLngs: [number, number][] = route.coordinates.map(([lon, lat]) => [lat, lon]);
        const polyline = L.polyline(latLngs, {
          color: route.is_simulated ? '#F59E0B' : '#1F9D4A',
          weight: 5,
          opacity: 0.95,
          dashArray: route.is_simulated ? '10, 8' : undefined,
        });
        routesLayer.addLayer(polyline);
        latLngs.forEach((coord) => bounds.extend(coord));
      }
    });

    points.forEach((point) => {
      if (isValidMapCoordinate(point.latitude, point.longitude)) {
        const marker = L.marker([point.latitude, point.longitude], {
          icon: createCollectionPointIcon(),
        });
        marker.bindPopup(`
          <div style="font-family: inherit; font-size: 0.85rem;">
            <strong>${escapeHtml(point.name)}</strong><br/>
            Type: <code>${escapeHtml(point.point_type)}</code>
          </div>
        `);
        markersLayer.addLayer(marker);
        bounds.extend([point.latitude, point.longitude]);
      }
    });

    vehicles.forEach((vehicle) => {
      const latitude = vehicle.latitude;
      const longitude = vehicle.longitude;
      if (
        typeof latitude === 'number' &&
        typeof longitude === 'number' &&
        isValidMapCoordinate(latitude, longitude) &&
        hasCurrentVehicleSignal(vehicle, freshnessMinutes)
      ) {
        const isSelected = selectedVehicle?.id === vehicle.id;
        const isFresh = hasCurrentVehicleSignal(vehicle, freshnessMinutes);
        const marker = L.marker([latitude, longitude], {
          icon: createVehicleIcon(vehicle.is_simulated, isFresh, isSelected),
          zIndexOffset: isSelected ? 1000 : 100,
        });

        marker.on('click', () => {
          if (onVehicleSelect) {
            onVehicleSelect(vehicle);
          }
        });

        if (isSelected) {
          const signal = signalPhrase(vehicle, telemetrySource, isFresh);
          marker.bindTooltip(
            `<div style="font-family: inherit;">
              <div style="font-weight:800;font-size:13px;color:#111827;">${escapeHtml(vehiclePlate(vehicle))}</div>
              <div style="display:flex;align-items:center;gap:6px;margin-top:2px;font-size:12px;color:#374151;">
                <span style="width:8px;height:8px;border-radius:50%;background:${signal.dot};display:inline-block;"></span>
                ${escapeHtml(signal.text)}
              </div>
            </div>`,
            {
              permanent: true,
              direction: 'top',
              offset: [0, -10],
              className: 'nc-vehicle-tip',
              opacity: 1,
            }
          );
        }

        markersLayer.addLayer(marker);
        bounds.extend([latitude, longitude]);
      }
    });

    // Only auto-fit bounds when filtering to an explicit ward; Bengaluru city-wide view stays centered on city
    if (wardId && bounds.isValid() && !hasFittedDataBoundsRef.current) {
      map.fitBounds(bounds.pad(0.12), { maxZoom: 15 });
      hasFittedDataBoundsRef.current = true;
    }
  }, [routes, points, vehicles, selectedVehicle, onVehicleSelect, telemetrySource, freshnessMinutes, freshnessClock, wardId]);

  // Render Pilot Zone Boundary Highlight Layer
  useEffect(() => {
    const pilotLayer = pilotLayerRef.current;
    if (!pilotLayer) return;

    pilotLayer.clearLayers();

    if (pilotInfo?.boundary_geojson) {
      try {
        const geoLayer = L.geoJSON(pilotInfo.boundary_geojson as any, {
          style: {
            color: '#059669',
            weight: 2.5,
            dashArray: '6, 6',
            fillColor: '#10B981',
            fillOpacity: 0.13,
          },
          onEachFeature: (_, layer) => {
            layer.bindTooltip(
              `<div style="font-family: inherit; font-size: 12px; font-weight: 700; color: #065F46;">
                🎯 Operational Pilot Zone: ${escapeHtml(pilotInfo.pilot_ward_name || pilotInfo.pilot_zone_name)}
              </div>`,
              { sticky: true, className: 'nc-pilot-tooltip' }
            );
          },
        });
        pilotLayer.addLayer(geoLayer);
      } catch (err) {
        console.warn('Failed to render pilot boundary layer', err);
      }
    }
  }, [pilotInfo]);

  const handleFocusPilot = useCallback(() => {
    if (mapInstanceRef.current) {
      const center = pilotInfo?.pilot_center || [13.1331, 77.5685];
      mapInstanceRef.current.flyTo(center as [number, number], 14, { duration: 1.2 });
    }
  }, [pilotInfo]);

  const handleFocusBengaluru = useCallback(() => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.flyTo(DEFAULT_CENTER, DEFAULT_ZOOM, { duration: 1.2 });
    }
  }, []);

  const handleFallbackToStreet = useCallback(() => {
    setMapMode('street');
    setTileError(false);
    setIsSatelliteLoading(false);
    failedTilesCountRef.current = 0;
  }, []);

  const handleRetrySatellite = useCallback(() => {
    setTileError(false);
    setIsSatelliteLoading(true);
    failedTilesCountRef.current = 0;
    if (satelliteTileLayerRef.current) {
      satelliteTileLayerRef.current.redraw();
    }
  }, []);

  const genuineFresh =
    telemetrySource === 'api' && vehicles.some((vehicle) => hasCurrentVehicleSignal(vehicle, freshnessMinutes) && !vehicle.is_simulated);
  const demoFresh =
    telemetrySource === 'api' && vehicles.some((vehicle) => hasCurrentVehicleSignal(vehicle, freshnessMinutes) && vehicle.is_simulated);
  const hasStaleVehicle = vehicles.some((vehicle) => !hasCurrentVehicleSignal(vehicle, freshnessMinutes));

  let mapStatusLabel = loading ? 'Connecting' : 'Unavailable';
  let mapStatusColor = '#6B7280';
  if (telemetrySource === 'api') {
    if (genuineFresh) {
      mapStatusLabel = 'Fresh';
      mapStatusColor = '#16A34A';
    } else if (demoFresh) {
      mapStatusLabel = 'Demo';
      mapStatusColor = '#E8943A';
    } else if (hasStaleVehicle) {
      mapStatusLabel = 'Stale';
      mapStatusColor = '#D97706';
    } else {
      mapStatusLabel = vehicles.length > 0 ? 'No current signal' : 'No vehicles';
      mapStatusColor = '#6B7280';
    }
  }

  const lastUpdatedLabel =
    lastRefreshedAt ? formatAgo(lastRefreshedAt) : 'Not available';
  const freshLabel =
    freshnessMinutes === null ? 'Fresh signal' : `Fresh (< ${freshnessMinutes}m)`;
  const staleLabel =
    freshnessMinutes === null ? 'Stale signal' : `Stale (> ${freshnessMinutes}m)`;
  const municipalVehicleMarkers = vehicles.filter(
    (vehicle) => !vehicle.is_simulated && isValidMapCoordinate(vehicle.latitude, vehicle.longitude) && hasCurrentVehicleSignal(vehicle, freshnessMinutes)
  );
  const demoVehicleMarkers = vehicles.filter(
    (vehicle) => vehicle.is_simulated && isValidMapCoordinate(vehicle.latitude, vehicle.longitude) && hasCurrentVehicleSignal(vehicle, freshnessMinutes)
  );
  const mappableRoutes = routes.filter((route) => route.coordinates?.length > 0);
  const hasMunicipalVehicleMarkers = municipalVehicleMarkers.length > 0;
  const hasDemoVehicleMarkers = demoVehicleMarkers.length > 0;
  const hasCollectionPointMarkers = points.some((point) => isValidMapCoordinate(point.latitude, point.longitude));
  const hasPublishedRoutes = mappableRoutes.some((route) => !route.is_simulated);
  const hasDemoRoutes = mappableRoutes.some((route) => route.is_simulated);
  const hasMapFeatures =
    hasMunicipalVehicleMarkers || hasDemoVehicleMarkers || hasCollectionPointMarkers || mappableRoutes.length > 0;
  const hasMapRecords = vehicles.length > 0 || points.length > 0 || routes.length > 0;
  const mapEmptyTitle =
    telemetrySource !== 'api'
      ? 'Map data unavailable'
      : error
        ? 'Map data is incomplete'
        : hasMapRecords
          ? 'No current locations to display'
          : 'No published map data yet';
  const mapEmptyMessage =
    telemetrySource !== 'api'
      ? 'Live map information could not be reached. Please try again shortly.'
      : error
        ? 'Some map services did not respond. Available data is shown, and the map will retry automatically.'
        : hasMapRecords
          ? 'Published records have no current mappable positions. Stale vehicle positions are hidden.'
          : 'Published vehicles, routes and collection points will appear here when available.';
  const legendEmptyMessage =
    telemetrySource !== 'api' || error
      ? 'Map features unavailable'
      : hasMapRecords
        ? 'No current map features'
        : 'No published map features';

  return (
    <div id="citizen-map">
      <div className="nc-map-section-head">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0 }}>Vehicle Tracking</h2>
          <div className="nc-map-mode-toggle" role="group" aria-label="Map view mode">
            <button
              type="button"
              className={`nc-map-mode-btn ${mapMode === 'street' ? 'active' : ''}`}
              onClick={() => setMapMode('street')}
            >
              Map
            </button>
            <button
              type="button"
              className={`nc-map-mode-btn ${mapMode === 'satellite' ? 'active' : ''}`}
              onClick={() => setMapMode('satellite')}
            >
              Satellite
            </button>
          </div>

          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
            <button
              type="button"
              onClick={handleFocusPilot}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                backgroundColor: '#E8F5E9',
                color: '#2E7D32',
                border: '1px solid #C8E6C9',
                borderRadius: '8px',
                padding: '4px 10px',
                fontSize: '0.8rem',
                fontWeight: 700,
                cursor: 'pointer',
              }}
              title="Focus map on Yelahanka & BMSIT&M Pilot Zone"
            >
              <Crosshair size={13} />
              <span>Pilot: Yelahanka (BMSIT&M)</span>
            </button>

            <button
              type="button"
              onClick={handleFocusBengaluru}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                backgroundColor: '#FFFFFF',
                color: '#183B2A',
                border: '1px solid #D5E3D7',
                borderRadius: '8px',
                padding: '4px 10px',
                fontSize: '0.8rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
              title="Reset viewport to Entire Bengaluru"
            >
              <MapPin size={13} />
              <span>Entire Bengaluru</span>
            </button>
          </div>
        </div>
        <div className="nc-map-head-meta">
          {summaryDisclaimer && (
            <details className="nc-map-disclaimer">
              <summary>Demonstration platform · no live BBMP GPS integration</summary>
              <span>{summaryDisclaimer}</span>
            </details>
          )}
          <span className="nc-map-status-note">Updates every 25 sec</span>
        </div>
      </div>
      {error && (
        <div className="nc-map-error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <details>
            <summary>Public map data unavailable · retrying</summary>
            <p>{error}</p>
          </details>
        </div>
      )}
      {tileError && (
        <div className="nc-map-error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <details open>
            <summary>Satellite imagery is taking longer to load or is temporarily unreachable</summary>
            <p style={{ margin: '0.35rem 0 0.5rem' }}>
              The satellite tile provider is experiencing network delays. You can continue using the street map or retry loading.
            </p>
            <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
              <button
                type="button"
                onClick={handleFallbackToStreet}
                style={{
                  padding: '4px 10px',
                  borderRadius: '6px',
                  border: '1px solid #C8E6C9',
                  backgroundColor: '#E8F5E9',
                  color: '#2E7D32',
                  fontSize: '0.78rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                Switch to Street Map
              </button>
              <button
                type="button"
                onClick={handleRetrySatellite}
                style={{
                  padding: '4px 10px',
                  borderRadius: '6px',
                  border: '1px solid #CBD5E1',
                  backgroundColor: '#FFFFFF',
                  color: '#475569',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Retry Satellite
              </button>
            </div>
          </details>
        </div>
      )}

      <div className="nc-map-layout">
        <aside className="nc-map-legend" aria-label="Map legend">
          <div className="nc-map-legend-title">Map legend</div>
          {pilotInfo?.boundary_geojson && (
            <LegendRow
              label="Pilot boundary (Yelahanka)"
              swatch={
                <span
                  style={{
                    width: '22px',
                    height: '14px',
                    border: '2px dashed #059669',
                    backgroundColor: 'rgba(16, 185, 129, 0.2)',
                    display: 'inline-block',
                    borderRadius: '2px',
                  }}
                />
              }
            />
          )}
          {hasMunicipalVehicleMarkers && <LegendRow
            label="Municipal vehicle"
            swatch={<svg width="22" height="14" viewBox="0 0 44 32" aria-hidden="true"><rect x="2" y="4" width="26" height="18" rx="3" fill="#1F8A4C" /><path d="M28 9 L39 15 L39 22 L28 22 Z" fill="#146B3A" /></svg>}
          />}
          {hasDemoVehicleMarkers && <LegendRow
            label="Demo / simulated"
            swatch={<svg width="22" height="14" viewBox="0 0 44 32" aria-hidden="true"><rect x="2" y="4" width="26" height="18" rx="3" fill="#E8943A" /><path d="M28 9 L39 15 L39 22 L28 22 Z" fill="#C46A12" /></svg>}
          />}
          {hasCollectionPointMarkers && <LegendRow
            label="Collection point"
            swatch={
              <svg width="14" height="16" viewBox="0 0 24 28" aria-hidden="true">
                <rect x="4" y="8" width="16" height="17" rx="3" fill="#2D6A4F" />
                <rect x="2" y="4" width="20" height="4" rx="2" fill="#1B4332" />
              </svg>
            }
          />}
          {hasPublishedRoutes && <LegendRow
            label="Published route"
            swatch={<span style={{ width: '22px', height: '3px', backgroundColor: '#1F9D4A', display: 'inline-block', borderRadius: '2px' }} />}
          />}
          {hasDemoRoutes && <LegendRow
            label="Demo route"
            swatch={<span style={{ width: '22px', borderTop: '3px dashed #F59E0B', display: 'inline-block' }} />}
          />}
          {!hasMapFeatures && <span className="nc-map-legend-empty">{legendEmptyMessage}</span>}
          <div className="nc-map-legend-subtitle">Signal status</div>
          <div className="nc-map-legend-signals">
            <LegendRow
              label={freshLabel}
              swatch={<span style={{ width: '9px', height: '9px', borderRadius: '50%', backgroundColor: '#16A34A', display: 'inline-block' }} />}
            />
            <LegendRow
              label={staleLabel}
              swatch={<span style={{ width: '9px', height: '9px', borderRadius: '50%', backgroundColor: '#F59E0B', display: 'inline-block' }} />}
            />
            <LegendRow
              label="No signal"
              swatch={<span style={{ width: '9px', height: '9px', borderRadius: '50%', backgroundColor: '#9CA3AF', display: 'inline-block' }} />}
            />
          </div>
        </aside>

        <div className="nc-map-column">
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              backgroundColor: '#E8F5E9',
              border: '1px solid #D5E3D7',
              borderRadius: '10px',
              padding: '6px 12px',
              fontSize: '0.82rem',
              color: '#183B2A',
              gap: '8px',
              flexWrap: 'wrap',
              marginBottom: '0.65rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '1rem' }}>🎯</span>
              <span>
                <strong>Bengaluru City-Wide Context:</strong> Operational pilot active in <strong>Yelahanka &amp; Avalahalli (BMSIT&amp;M Corridor)</strong>.
              </span>
            </div>
            <button
              type="button"
              onClick={handleFocusPilot}
              style={{
                backgroundColor: '#2E7D32',
                color: '#FFFFFF',
                border: 'none',
                borderRadius: '6px',
                padding: '4px 10px',
                fontSize: '0.76rem',
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              Focus Pilot Area
            </button>
          </div>

          <div className="nc-map-canvas">
            <div ref={mapContainerRef} style={{ width: '100%', height: '100%' }} />
            {mapMode === 'satellite' && isSatelliteLoading && (
              <div
                style={{
                  position: 'absolute',
                  top: '12px',
                  right: '12px',
                  zIndex: 400,
                  backgroundColor: 'rgba(15, 23, 42, 0.82)',
                  backdropFilter: 'blur(4px)',
                  color: '#FFFFFF',
                  padding: '6px 14px',
                  borderRadius: '20px',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  boxShadow: '0 4px 14px rgba(0,0,0,0.18)',
                  pointerEvents: 'none',
                }}
                role="status"
                aria-live="polite"
              >
                <RefreshCw size={13} className="nc-refreshing" />
                <span>Loading satellite imagery…</span>
              </div>
            )}
            {!loading && !hasMapFeatures && (
              <div className="nc-map-empty" role="status">
              <MapPin size={22} color="#438359" aria-hidden="true" />
              <strong>{mapEmptyTitle}</strong>
              <span>{mapEmptyMessage}</span>
              </div>
            )}
            {loading && (
              <div className="nc-map-loading" role="status" aria-live="polite">
              <Spinner size="md" />
              <span>Loading published map data…</span>
              </div>
            )}
          </div>

          {details ? <div className="nc-map-details">{details}</div> : null}

          <div className="nc-map-status">
            <div className="nc-map-chip">
              <MapPin size={14} color="#2E7D32" aria-hidden="true" />
              <span>
              <span className="nc-map-chip-label">Coverage</span>
              <span className="nc-map-chip-value">{wardId ? 'Selected ward' : 'Bengaluru (Pilot: Yelahanka)'}</span>
              </span>
            </div>

            <button
              type="button"
              onClick={() => loadMapData(true)}
              disabled={refreshing || loading}
              title={lastRefreshedAt ? `Last refreshed: ${lastRefreshedAt.toLocaleTimeString()}` : 'Refresh map'}
              className="nc-map-chip"
              aria-label="Refresh published map data"
            >
              <RefreshCw
              size={14}
              color="#2E7D32"
              className={refreshing ? 'nc-refreshing' : ''}
              />
              <span>
              <span className="nc-map-chip-label">Last updated</span>
              <span className="nc-map-chip-value">{lastUpdatedLabel}</span>
              </span>
            </button>

            <div className="nc-map-chip" aria-live="polite">
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: mapStatusColor }} />
              <span>
              <span className="nc-map-chip-label">Map status</span>
              <span className="nc-map-chip-value" style={{ color: mapStatusColor }}>{mapStatusLabel}</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
