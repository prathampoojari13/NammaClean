import React, { useEffect, useRef, useState, useCallback, type ReactNode } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { AlertTriangle, Crosshair, MapPin, RefreshCw, Bell, BellRing, Navigation } from 'lucide-react';
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
  DumpingReport,
} from '../../types';
import { Spinner } from '../ui/Spinner';
import { hasCurrentVehicleSignal } from '../../utils/publicMapFreshness';
import { BENGALURU_LOCALITIES, LocalityOption } from '../../utils/localities';
import { triggerTestNotification } from '../../api/notifications';

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

const createComplaintIcon = (status: string) => {
  let color = '#D97706';
  if (status === 'UNDER_REVIEW') color = '#2563EB';
  else if (status === 'ACTION_SCHEDULED') color = '#9333EA';
  else if (status === 'RESOLVED') color = '#16A34A';
  else if (status === 'REJECTED') color = '#DC2626';

  const html = `
    <div style="cursor: pointer; width: 30px; height: 38px; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.35));">
      <svg width="30" height="38" viewBox="0 0 30 38" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M15 0C6.716 0 0 6.716 0 15C0 26.25 15 38 15 38C15 38 30 26.25 30 15C30 6.716 23.284 0 15 0Z" fill="${color}" stroke="#FFFFFF" stroke-width="2"/>
        <circle cx="15" cy="14" r="7" fill="#FFFFFF"/>
        <path d="M15 10V15M15 18H15.01" stroke="${color}" stroke-width="2.2" stroke-linecap="round"/>
      </svg>
    </div>
  `;

  return L.divIcon({
    className: 'custom-complaint-marker',
    html,
    iconSize: [30, 38],
    iconAnchor: [15, 38],
    popupAnchor: [0, -36],
  });
};

export interface PublicVehicleMapProps {
  wardId?: string;
  selectedVehicle?: PublicVehicle | null;
  onVehicleSelect?: (vehicle: PublicVehicle | null) => void;
  onSummaryLoaded?: (summary: PublicMapSummary) => void;
  details?: ReactNode;
  complaints?: DumpingReport[];
  selectedLocality?: LocalityOption;
  onLocalityChange?: (locality: LocalityOption) => void;
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
  complaints,
  selectedLocality,
  onLocalityChange,
}) => {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const routesLayerRef = useRef<L.LayerGroup | null>(null);
  const pilotLayerRef = useRef<L.LayerGroup | null>(null);
  const complaintsLayerRef = useRef<L.LayerGroup | null>(null);
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

  // User location & arrival alert states
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number; accuracy: number } | null>(null);
  const [isLocatingUser, setIsLocatingUser] = useState(false);
  const [locationNotice, setLocationNotice] = useState<string | null>(null);
  const [isArrivalAlertsEnabled, setIsArrivalAlertsEnabled] = useState<boolean>(() => {
    return localStorage.getItem('nammaclean:arrival_alerts') === 'true';
  });
  const [showArrivalModal, setShowArrivalModal] = useState(false);
  const userMarkerRef = useRef<L.Marker | null>(null);
  const userCircleRef = useRef<L.Circle | null>(null);
  const alertedVehiclesRef = useRef<Record<string, number>>({});
  const userLocationRef = useRef(userLocation);
  const isArrivalAlertsEnabledRef = useRef(isArrivalAlertsEnabled);

  useEffect(() => {
    userLocationRef.current = userLocation;
  }, [userLocation]);

  useEffect(() => {
    isArrivalAlertsEnabledRef.current = isArrivalAlertsEnabled;
  }, [isArrivalAlertsEnabled]);

  const haversineKm = (lat1: number, lon1: number, lat2: number, lon2: number): number => {
    const r = 6371.0;
    const dlat = ((lat2 - lat1) * Math.PI) / 180.0;
    const dlon = ((lon2 - lon1) * Math.PI) / 180.0;
    const a =
      Math.sin(dlat / 2) ** 2 +
      Math.cos((lat1 * Math.PI) / 180.0) *
        Math.cos((lat2 * Math.PI) / 180.0) *
        Math.sin(dlon / 2) ** 2;
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return r * c;
  };

  const handleLocateMe = useCallback(() => {
    if (!navigator.geolocation) {
      setLocationNotice('Geolocation is not supported by your browser.');
      return;
    }
    setIsLocatingUser(true);
    setLocationNotice(null);

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        const accuracy = pos.coords.accuracy;

        setUserLocation({ lat, lng, accuracy });
        setIsLocatingUser(false);

        const map = mapInstanceRef.current;
        if (!map) return;

        if (!userMarkerRef.current) {
          const userIcon = L.divIcon({
            className: 'custom-citizen-pin',
            html: `
              <div style="position: relative; width: 22px; height: 22px;">
                <div style="position: absolute; inset: 0; border-radius: 50%; background: #3B82F6; opacity: 0.35;"></div>
                <div style="position: absolute; inset: 4px; border-radius: 50%; background: #2563EB; border: 2px solid #FFFFFF; box-shadow: 0 2px 5px rgba(0,0,0,0.35);"></div>
              </div>
            `,
            iconSize: [22, 22],
            iconAnchor: [11, 11],
          });
          const marker = L.marker([lat, lng], { icon: userIcon, zIndexOffset: 1000 }).addTo(map);
          marker.bindPopup(`<strong>My Location</strong><br>Accuracy: ±${Math.round(accuracy)}m`);
          userMarkerRef.current = marker;

          const circle = L.circle([lat, lng], {
            radius: Math.min(accuracy, 200),
            color: '#3B82F6',
            fillColor: '#93C5FD',
            fillOpacity: 0.15,
            weight: 1,
          }).addTo(map);
          userCircleRef.current = circle;
        } else {
          userMarkerRef.current.setLatLng([lat, lng]);
          if (userCircleRef.current) {
            userCircleRef.current.setLatLng([lat, lng]);
            userCircleRef.current.setRadius(Math.min(accuracy, 200));
          }
        }

        map.flyTo([lat, lng], 15, { duration: 1.2 });
      },
      (err) => {
        setIsLocatingUser(false);
        if (err.code === err.PERMISSION_DENIED) {
          setLocationNotice('Location permission denied. Please enable GPS in browser.');
        } else {
          setLocationNotice('Could not acquire GPS fix. Try again.');
        }
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
    );
  }, []);

  const handleToggleArrivalAlerts = () => {
    if (!isArrivalAlertsEnabled) {
      setShowArrivalModal(true);
    } else {
      setIsArrivalAlertsEnabled(false);
      localStorage.setItem('nammaclean:arrival_alerts', 'false');
    }
  };

  const confirmEnableArrivalAlerts = async () => {
    setShowArrivalModal(false);
    setIsArrivalAlertsEnabled(true);
    localStorage.setItem('nammaclean:arrival_alerts', 'true');

    if ('Notification' in window && Notification.permission !== 'granted') {
      try {
        await Notification.requestPermission();
      } catch {
        // Fallback to in-app
      }
    }
  };

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
    const complaintsLayer = L.layerGroup().addTo(map);

    mapInstanceRef.current = map;
    routesLayerRef.current = routesLayer;
    pilotLayerRef.current = pilotLayer;
    markersLayerRef.current = markersLayer;
    complaintsLayerRef.current = complaintsLayer;

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
      complaintsLayerRef.current = null;
    };
  }, []);

  // Center or fly to selected locality when updated
  useEffect(() => {
    if (selectedLocality && mapInstanceRef.current) {
      mapInstanceRef.current.flyTo(
        [selectedLocality.latitude, selectedLocality.longitude],
        14,
        { duration: 1.2 }
      );
    }
  }, [selectedLocality]);

  // Render Citizen Complaints on Map
  useEffect(() => {
    const layer = complaintsLayerRef.current;
    if (!layer) return;

    layer.clearLayers();
    if (!complaints || complaints.length === 0) return;

    complaints.forEach((report) => {
      if (isValidMapCoordinate(report.latitude, report.longitude)) {
        const marker = L.marker([report.latitude, report.longitude], {
          icon: createComplaintIcon(report.status),
          zIndexOffset: 300,
        });

        const dateStr = new Date(report.created_at).toLocaleDateString('en-IN', {
          month: 'short',
          day: 'numeric',
          year: 'numeric',
        });

        const photosCount = report.evidence?.length || 0;

        let statusBg = '#FEF3C7';
        let statusColor = '#92400E';
        if (report.status === 'UNDER_REVIEW') {
          statusBg = '#DBEAFE';
          statusColor = '#1E40AF';
        } else if (report.status === 'ACTION_SCHEDULED') {
          statusBg = '#F3E8FF';
          statusColor = '#6B21A8';
        } else if (report.status === 'RESOLVED') {
          statusBg = '#D1FAE5';
          statusColor = '#065F46';
        } else if (report.status === 'REJECTED') {
          statusBg = '#FEE2E2';
          statusColor = '#991B1B';
        }

        marker.bindPopup(`
          <div style="font-family: inherit; font-size: 0.85rem; min-width: 220px; max-width: 270px; padding: 2px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <strong style="color: #183B2A; font-size: 0.88rem;">Incident #${escapeHtml(report.id.slice(0, 8))}</strong>
              <span style="font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 999px; background: ${statusBg}; color: ${statusColor};">
                ${escapeHtml(formatStatus(report.status))}
              </span>
            </div>
            <p style="margin: 0 0 6px; color: #374151; font-size: 0.82rem; line-height: 1.4;">
              ${escapeHtml(report.description)}
            </p>
            <div style="font-size: 0.74rem; color: #6B7280; border-top: 1px solid #E5E7EB; padding-top: 5px; display: flex; justify-content: space-between;">
              <span>📍 ${report.latitude.toFixed(4)}, ${report.longitude.toFixed(4)}</span>
              <span>📅 ${dateStr}</span>
            </div>
            ${photosCount > 0 ? `<div style="font-size: 0.74rem; color: #0284C7; font-weight: 600; margin-top: 3px;">📷 ${photosCount} photo(s) attached</div>` : ''}
          </div>
        `);

        layer.addLayer(marker);
      }
    });
  }, [complaints]);

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

          // Proximity arrival alerts detection (500m early alert, 200m near arrival)
          if (isArrivalAlertsEnabledRef.current && userLocationRef.current) {
            const uLoc = userLocationRef.current;
            const now = Date.now();
            vList.forEach((veh) => {
              if (isValidMapCoordinate(veh.latitude, veh.longitude) && veh.latitude != null && veh.longitude != null) {
                const distKm = haversineKm(uLoc.lat, uLoc.lng, veh.latitude, veh.longitude);
                const lastAlert = alertedVehiclesRef.current[veh.id] || 0;
                // Alert if within 500m (0.5km) and not alerted in the last 15 minutes
                if (distKm <= 0.5 && now - lastAlert > 15 * 60 * 1000) {
                  alertedVehiclesRef.current[veh.id] = now;
                  const distM = Math.round(distKm * 1000);
                  const isArrived = distKm <= 0.2;
                  const alertMsg = isArrived
                    ? `Collection vehicle ${vehiclePlate(veh)} is at your doorstep (${distM}m away)!`
                    : `Collection vehicle ${vehiclePlate(veh)} is approaching your location (~${distM}m away).`;

                  // System/Browser notification if permission granted
                  if ('Notification' in window && Notification.permission === 'granted') {
                    try {
                      new Notification('NammaClean Arrival Alert', {
                        body: alertMsg,
                        icon: '/favicon.ico',
                      });
                    } catch {
                      // ignore
                    }
                  }

                  // Persistent in-app notification center
                  triggerTestNotification(alertMsg, isArrived ? 'VEHICLE_ARRIVED' : 'VEHICLE_NEAR').catch(() => {});
                }
              }
            });
          }

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

            {/* Direct Citywide Locality Switcher */}
            <select
              aria-label="Filter Map by Bengaluru Sector"
              value={selectedLocality?.id || 'yelahanka'}
              onChange={(e) => {
                const targetLoc = BENGALURU_LOCALITIES.find((l) => l.id === e.target.value);
                if (targetLoc) {
                  onLocalityChange?.(targetLoc);
                  if (mapInstanceRef.current) {
                    mapInstanceRef.current.flyTo(
                      [targetLoc.latitude, targetLoc.longitude],
                      14,
                      { duration: 1.2 }
                    );
                  }
                }
              }}
              style={{
                padding: '4px 9px',
                borderRadius: '8px',
                border: '1px solid #D5E3D7',
                fontSize: '0.8rem',
                fontWeight: 600,
                backgroundColor: '#FFFFFF',
                color: '#183B2A',
                cursor: 'pointer',
              }}
            >
              {BENGALURU_LOCALITIES.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name} {loc.isPilot ? '★ Pilot' : ''}
                </option>
              ))}
            </select>

            {/* My Location GPS Button */}
            <button
              type="button"
              onClick={handleLocateMe}
              disabled={isLocatingUser}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                backgroundColor: userLocation ? '#EFF6FF' : '#FFFFFF',
                color: userLocation ? '#2563EB' : '#183B2A',
                border: userLocation ? '1px solid #BFDBFE' : '1px solid #D5E3D7',
                borderRadius: '8px',
                padding: '4px 10px',
                fontSize: '0.8rem',
                fontWeight: 650,
                cursor: 'pointer',
              }}
              title="Detect your current GPS location on the map"
            >
              <Navigation size={13} className={isLocatingUser ? 'nc-refreshing' : ''} />
              <span>{isLocatingUser ? 'Locating…' : userLocation ? 'My Location ✓' : 'My Location'}</span>
            </button>

            {/* Arrival Alerts Proximity Notifications Button */}
            <button
              type="button"
              onClick={handleToggleArrivalAlerts}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                backgroundColor: isArrivalAlertsEnabled ? '#FEF3C7' : '#FFFFFF',
                color: isArrivalAlertsEnabled ? '#92400E' : '#183B2A',
                border: isArrivalAlertsEnabled ? '1px solid #FDE68A' : '1px solid #D5E3D7',
                borderRadius: '8px',
                padding: '4px 10px',
                fontSize: '0.8rem',
                fontWeight: 650,
                cursor: 'pointer',
              }}
              title="Get notified when a waste collection vehicle approaches within 500m"
            >
              {isArrivalAlertsEnabled ? <BellRing size={13} color="#D97706" /> : <Bell size={13} />}
              <span>{isArrivalAlertsEnabled ? 'Arrival Alerts ON' : 'Arrival Alerts'}</span>
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
          {complaints && complaints.length > 0 && (
            <div style={{ marginTop: '0.75rem', paddingTop: '0.65rem', borderTop: '1px solid #E5E7EB' }}>
              <div className="nc-map-legend-subtitle" style={{ marginBottom: '0.4rem' }}>Incidents</div>
              <LegendRow
                label={`Complaints (${complaints.length})`}
                swatch={
                  <span
                    style={{
                      display: 'inline-block',
                      width: '10px',
                      height: '10px',
                      borderRadius: '50%',
                      backgroundColor: '#D97706',
                      border: '1.5px solid #FFFFFF',
                      boxShadow: '0 0 0 1px #D97706',
                    }}
                  />
                }
              />
            </div>
          )}
        </aside>

        <div className="nc-map-column">
          {selectedLocality && !selectedLocality.isPilot ? (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                backgroundColor: '#EFF6FF',
                border: '1px solid #BFDBFE',
                borderRadius: '10px',
                padding: '8px 12px',
                fontSize: '0.82rem',
                color: '#1E40AF',
                gap: '8px',
                flexWrap: 'wrap',
                marginBottom: '0.65rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '1.05rem' }}>📍</span>
                <span>
                  <strong>Viewing {selectedLocality.name} ({selectedLocality.zone}):</strong> Coverage Notice — Operational vehicle telemetry is currently active in the Yelahanka pilot corridor. BBMP solid waste fleet expansion is scheduled in Phase 2.
                </span>
              </div>
              <button
                type="button"
                onClick={handleFocusPilot}
                style={{
                  backgroundColor: '#2563EB',
                  color: '#FFFFFF',
                  border: 'none',
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '0.76rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                View Active Pilot
              </button>
            </div>
          ) : (
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
          )}

          {/* Location Notice (e.g. GPS permission denied) */}
          {locationNotice && (
            <div
              style={{
                backgroundColor: '#FEF2F2',
                border: '1px solid #FCA5A5',
                color: '#991B1B',
                padding: '7px 12px',
                borderRadius: '8px',
                fontSize: '0.8rem',
                marginBottom: '0.65rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <span>{locationNotice}</span>
              <button
                type="button"
                onClick={() => setLocationNotice(null)}
                style={{ background: 'none', border: 'none', color: '#991B1B', cursor: 'pointer', fontWeight: 700 }}
              >
                ×
              </button>
            </div>
          )}

          {/* Real-time Proximity / Distance & ETA honest status strip */}
          {selectedVehicle && userLocation && isValidMapCoordinate(selectedVehicle.latitude, selectedVehicle.longitude) && (
            <div
              style={{
                backgroundColor: '#F0FDF4',
                border: '1px solid #BBF7D0',
                borderRadius: '10px',
                padding: '8px 14px',
                marginBottom: '0.65rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '12px',
                flexWrap: 'wrap',
                boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Navigation size={15} color="#16A34A" />
                <span style={{ fontSize: '0.84rem', color: '#166534', fontWeight: 650 }}>
                  Tracking <strong>{vehiclePlate(selectedVehicle)}</strong>:
                </span>
                <span style={{ fontSize: '0.84rem', color: '#14532D', fontWeight: 750 }}>
                  Straight-line distance:{' '}
                  {(() => {
                    const distKm = haversineKm(userLocation.lat, userLocation.lng, selectedVehicle.latitude!, selectedVehicle.longitude!);
                    return distKm < 1 ? `${Math.round(distKm * 1000)} meters` : `${distKm.toFixed(2)} km`;
                  })()}
                </span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span
                  style={{
                    backgroundColor: '#E2E8F0',
                    color: '#475569',
                    padding: '2px 8px',
                    borderRadius: '999px',
                    fontSize: '0.72rem',
                    fontWeight: 700,
                  }}
                >
                  ETA: ETA unavailable
                </span>
                <span style={{ fontSize: '0.73rem', color: '#64748B' }}>
                  (Traffic telemetry required)
                </span>
              </div>
            </div>
          )}

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

      {/* Vehicle Arrival Alerts Permission Modal */}
      {showArrivalModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            backdropFilter: 'blur(3px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1rem',
          }}
        >
          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '14px',
              maxWidth: '480px',
              width: '100%',
              padding: '1.5rem',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.15)',
              border: '1px solid #D5E3D7',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
              <div
                style={{
                  backgroundColor: '#FEF3C7',
                  color: '#D97706',
                  width: '42px',
                  height: '42px',
                  borderRadius: '10px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <BellRing size={22} />
              </div>
              <div>
                <h3 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 750, color: '#183B2A' }}>
                  Enable Vehicle Arrival Alerts
                </h3>
                <p style={{ margin: '2px 0 0 0', fontSize: '0.78rem', color: '#5A7565' }}>
                  Proximity alerts for waste collection
                </p>
              </div>
            </div>

            <p style={{ fontSize: '0.85rem', color: '#374151', lineHeight: 1.5, margin: '0 0 1rem 0' }}>
              NammaClean can notify you when a BBMP solid waste collection vehicle approaches within <strong>~500 meters</strong> of your location, so you can bring out segregated waste promptly.
            </p>

            <div
              style={{
                backgroundColor: '#F8FAFC',
                borderRadius: '8px',
                padding: '0.75rem',
                fontSize: '0.78rem',
                color: '#475569',
                border: '1px solid #E2E8F0',
                marginBottom: '1.25rem',
                lineHeight: 1.4,
              }}
            >
              <strong>Privacy & Notifications:</strong> Clicking enable will request browser notification permission. Proximity alerts are also recorded in your in-app Notification Center. Your location coordinates remain on your device.
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.75rem' }}>
              <button
                type="button"
                onClick={() => setShowArrivalModal(false)}
                style={{
                  padding: '7px 14px',
                  borderRadius: '7px',
                  border: '1px solid #CBD5E1',
                  backgroundColor: '#FFFFFF',
                  color: '#475569',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmEnableArrivalAlerts}
                style={{
                  padding: '7px 16px',
                  borderRadius: '7px',
                  border: 'none',
                  backgroundColor: '#2E7D32',
                  color: '#FFFFFF',
                  fontSize: '0.82rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                  boxShadow: '0 2px 6px rgba(46,125,50,0.25)',
                }}
              >
                Enable Alerts
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
