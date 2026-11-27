import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  AlertTriangle,
  Clock,
  Crosshair,
  MapPin,
  Navigation,
  PhoneCall,
  Power,
  RefreshCw,
  Route,
  ShieldCheck,
  Truck,
  Wifi,
  WifiOff,
} from 'lucide-react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

import { CitizenSidebar } from '../../components/layout/CitizenSidebar';
import { CitizenHeader } from '../../components/layout/CitizenHeader';
import { CitizenBanner } from '../../components/dashboard/CitizenBanner';
import { Button } from '../../components/ui/Button';
import { Alert } from '../../components/ui/Alert';
import { Spinner } from '../../components/ui/Spinner';
import { apiClient } from '../../api/client';
import {
  getDriverMe,
  startDriverDuty,
  endDriverDuty,
  sendDriverLocationPing,
} from '../../api/drivers';
import type {
  DriverMeResponse,
  User as UserType,
} from '../../types';
import '../../styles/citizen-dashboard.css';

export type DriverTab = 'dashboard' | 'tracking' | 'vehicle' | 'profile';

interface RecentLog {
  id: string;
  time: string;
  message: string;
  type: 'info' | 'success' | 'warning' | 'error';
}

export const DriverDashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<DriverTab>('dashboard');
  const [currentUser, setCurrentUser] = useState<UserType | null>(null);
  const [driverContext, setDriverContext] = useState<DriverMeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [isSubmittingDuty, setIsSubmittingDuty] = useState(false);

  // Map layer toggle state: 'street' | 'satellite'
  const [mapMode, setMapMode] = useState<'street' | 'satellite'>('street');

  // Pre-trip vehicle checklist state
  const [checklist, setChecklist] = useState({
    brakes: true,
    tires: true,
    hydraulics: true,
    beacon: true,
    fuel: true,
    safety: true,
  });

  // GPS Telemetry State
  const [isGpsActive, setIsGpsActive] = useState(false);
  const [gpsError, setGpsError] = useState<string | null>(null);
  const [lastCoords, setLastCoords] = useState<{
    latitude: number;
    longitude: number;
    accuracy?: number;
    speed?: number;
    heading?: number;
    timestamp: Date;
  } | null>(null);
  const [lastPingTime, setLastPingTime] = useState<Date | null>(null);
  const [activityLogs, setActivityLogs] = useState<RecentLog[]>([]);

  // Leaflet Map Refs
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const trackingMapContainerRef = useRef<HTMLDivElement | null>(null);
  const leafletMapRef = useRef<L.Map | null>(null);
  const streetLayerRef = useRef<L.TileLayer | null>(null);
  const satelliteLayerRef = useRef<L.TileLayer | null>(null);
  const driverMarkerRef = useRef<L.Marker | null>(null);
  const accuracyCircleRef = useRef<L.Circle | null>(null);
  const telemetryIntervalRef = useRef<number | null>(null);

  const addLog = useCallback((message: string, type: RecentLog['type'] = 'info') => {
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    setActivityLogs((prev) => [
      { id: `${Date.now()}-${Math.random()}`, time: timeStr, message, type },
      ...prev.slice(0, 19),
    ]);
  }, []);

  // 1. Load Driver Profile, Context & User Data
  const loadDriverData = useCallback(async () => {
    try {
      // Parallel fetch for driver context and auth profile
      const [contextData, userData] = await Promise.all([
        getDriverMe(),
        apiClient.get<UserType>('/users/me').catch(() => null),
      ]);

      setDriverContext(contextData);
      if (userData) {
        setCurrentUser(userData);
      }

      if (contextData.assigned_vehicle && contextData.assigned_vehicle.latitude && contextData.assigned_vehicle.longitude) {
        setLastCoords({
          latitude: contextData.assigned_vehicle.latitude,
          longitude: contextData.assigned_vehicle.longitude,
          timestamp: contextData.assigned_vehicle.last_seen_at ? new Date(contextData.assigned_vehicle.last_seen_at) : new Date(),
        });
      }
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to load driver profile.';
      setActionError(msg);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDriverData();
  }, [loadDriverData]);

  // 2. Transmit GPS Position to Backend
  const transmitLocation = useCallback(
    async (lat: number, lon: number, accuracy?: number, speed?: number, heading?: number) => {
      try {
        await sendDriverLocationPing({
          latitude: lat,
          longitude: lon,
          accuracy_meters: accuracy,
          speed_kmh: speed ? Math.max(0, speed * 3.6) : undefined,
          heading: heading ?? undefined,
        });

        const now = new Date();
        setLastPingTime(now);
        setGpsError(null);
        addLog(`GPS telemetry broadcast: ${lat.toFixed(5)}, ${lon.toFixed(5)} (±${Math.round(accuracy || 0)}m)`, 'success');

        // Update assigned vehicle local coordinates in state
        setDriverContext((prev) => {
          if (!prev || !prev.assigned_vehicle) return prev;
          return {
            ...prev,
            assigned_vehicle: {
              ...prev.assigned_vehicle,
              latitude: lat,
              longitude: lon,
              last_seen_at: now.toISOString(),
              is_fresh: true,
            },
          };
        });
      } catch (err: unknown) {
        const msg = typeof err === 'object' && err !== null && 'detail' in err
          ? String((err as { detail: unknown }).detail)
          : 'Failed to send telemetry update.';
        setGpsError(msg);
        addLog(`GPS sync error: ${msg}`, 'error');
      }
    },
    [addLog]
  );

  // 3. Continuous Geolocation Loop when Duty is ON
  const isOnDuty = driverContext?.duty_status === 'ON_DUTY';

  const obtainCurrentGps = useCallback(() => {
    if (!navigator.geolocation) {
      setGpsError('Geolocation is not supported by your browser.');
      addLog('Geolocation not supported by device browser.', 'error');
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        const acc = pos.coords.accuracy;
        const spd = pos.coords.speed ?? undefined;
        const hdg = pos.coords.heading ?? undefined;

        setLastCoords({
          latitude: lat,
          longitude: lon,
          accuracy: acc,
          speed: spd,
          heading: hdg,
          timestamp: new Date(),
        });

        // Transmit if on duty
        if (driverContext?.duty_status === 'ON_DUTY') {
          transmitLocation(lat, lon, acc, spd, hdg);
        }
      },
      (err) => {
        let errorMsg = 'GPS location unavailable.';
        if (err.code === 1) {
          errorMsg = 'Location permission denied. Please allow location permissions in your browser settings to broadcast vehicle telemetry.';
        } else if (err.code === 2) {
          errorMsg = 'Location provider unavailable or GPS signal lost.';
        } else if (err.code === 3) {
          errorMsg = 'GPS acquisition timed out. Retrying on next telemetry cycle.';
        }
        setGpsError(errorMsg);
        addLog(`GPS acquire notice: ${errorMsg}`, 'warning');
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 5000,
      }
    );
  }, [driverContext?.duty_status, transmitLocation, addLog]);

  // Periodic Telemetry Timer while ON_DUTY (15-second interval contract)
  useEffect(() => {
    if (!isOnDuty) {
      setIsGpsActive(false);
      if (telemetryIntervalRef.current) {
        clearInterval(telemetryIntervalRef.current);
        telemetryIntervalRef.current = null;
      }
      return;
    }

    setIsGpsActive(true);
    addLog('Live GPS tracking engine activated for duty shift.', 'info');

    // Immediate first acquire
    obtainCurrentGps();

    // 15-second interval pings matching backend telemetry rate
    telemetryIntervalRef.current = window.setInterval(() => {
      obtainCurrentGps();
    }, 15000);

    return () => {
      if (telemetryIntervalRef.current) {
        clearInterval(telemetryIntervalRef.current);
        telemetryIntervalRef.current = null;
      }
    };
  }, [isOnDuty, obtainCurrentGps, addLog]);

  // 4. Start Duty Handler
  const handleStartDuty = async () => {
    setActionError(null);
    setActionSuccess(null);
    setIsSubmittingDuty(true);

    try {
      let initLat: number | undefined;
      let initLon: number | undefined;

      if (navigator.geolocation) {
        try {
          const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
            navigator.geolocation.getCurrentPosition(resolve, reject, {
              enableHighAccuracy: true,
              timeout: 6000,
            });
          });
          initLat = pos.coords.latitude;
          initLon = pos.coords.longitude;
        } catch {
          // Proceed without initial coords if permission pending
        }
      }

      const res = await startDriverDuty({
        latitude: initLat,
        longitude: initLon,
        tyre_condition_checked: checklist.tires,
        fuel_battery_level_ok: checklist.fuel,
        mirrors_lights_checked: checklist.beacon,
        safety_kit_present: checklist.safety,
        brakes_checked: checklist.brakes,
      });

      setDriverContext(res);
      setActionSuccess('Duty started successfully! Real-time GPS location sharing is now active.');
      addLog('Duty shift started. Assigned vehicle transitioned to ON_DUTY.', 'success');
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to start duty. Please verify vehicle assignment.';
      setActionError(msg);
      addLog(`Failed to start duty: ${msg}`, 'error');
    } finally {
      setIsSubmittingDuty(false);
    }
  };

  // 5. End Duty Handler
  const handleEndDuty = async () => {
    setActionError(null);
    setActionSuccess(null);
    setIsSubmittingDuty(true);

    try {
      const res = await endDriverDuty();
      setDriverContext(res);
      setActionSuccess('Duty session ended successfully. Assigned vehicle is now IDLE.');
      addLog('Duty shift completed. Assigned vehicle transitioned to IDLE.', 'info');
      setIsGpsActive(false);
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : 'Failed to end duty session.';
      setActionError(msg);
      addLog(`Failed to end duty: ${msg}`, 'error');
    } finally {
      setIsSubmittingDuty(false);
    }
  };

  // 6. Leaflet Map Lifecycle Management
  useEffect(() => {
    const container = activeTab === 'tracking' ? trackingMapContainerRef.current : mapContainerRef.current;
    if (!container) return;

    // Destroy existing instance if container re-mounted
    if (leafletMapRef.current) {
      leafletMapRef.current.remove();
      leafletMapRef.current = null;
      driverMarkerRef.current = null;
      accuracyCircleRef.current = null;
    }

    const initialCenter: [number, number] = lastCoords
      ? [lastCoords.latitude, lastCoords.longitude]
      : [13.1331, 77.5685]; // Default Yelahanka pilot area

    const map = L.map(container, {
      center: initialCenter,
      zoom: 15,
      zoomControl: true,
    });

    const streetLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
      updateWhenIdle: true,
      keepBuffer: 4,
    });

    const satelliteLayer = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      {
        attribution: '&copy; Esri World Imagery',
        maxZoom: 19,
        updateWhenIdle: true,
        keepBuffer: 4,
      }
    );

    streetLayerRef.current = streetLayer;
    satelliteLayerRef.current = satelliteLayer;

    if (mapMode === 'satellite') {
      satelliteLayer.addTo(map);
    } else {
      streetLayer.addTo(map);
    }

    leafletMapRef.current = map;

    return () => {
      map.remove();
      leafletMapRef.current = null;
      driverMarkerRef.current = null;
      accuracyCircleRef.current = null;
    };
  }, [activeTab]);

  // Handle Layer Toggle
  useEffect(() => {
    const map = leafletMapRef.current;
    if (!map || !streetLayerRef.current || !satelliteLayerRef.current) return;

    if (mapMode === 'satellite') {
      if (map.hasLayer(streetLayerRef.current)) map.removeLayer(streetLayerRef.current);
      if (!map.hasLayer(satelliteLayerRef.current)) satelliteLayerRef.current.addTo(map);
    } else {
      if (map.hasLayer(satelliteLayerRef.current)) map.removeLayer(satelliteLayerRef.current);
      if (!map.hasLayer(streetLayerRef.current)) streetLayerRef.current.addTo(map);
    }
  }, [mapMode]);

  // Update Driver Marker & Accuracy Circle
  useEffect(() => {
    const map = leafletMapRef.current;
    if (!map) return;

    if (lastCoords) {
      const latlng: L.LatLngExpression = [lastCoords.latitude, lastCoords.longitude];

      const vehicleIcon = L.divIcon({
        className: 'nc-driver-live-marker',
        html: `
          <div style="
            background: #1B4D3E;
            color: #FFFFFF;
            width: 38px;
            height: 38px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 3px solid #FFFFFF;
            box-shadow: 0 4px 14px rgba(0,0,0,0.35);
            position: relative;
          ">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/>
              <path d="M15 18H9"/>
              <path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/>
              <circle cx="17" cy="18" r="2"/>
              <circle cx="7" cy="18" r="2"/>
            </svg>
            ${isOnDuty ? '<span style="position: absolute; top: -2px; right: -2px; width: 10px; height: 10px; background: #22C55E; border: 2px solid #FFFFFF; border-radius: 50%;"></span>' : ''}
          </div>
        `,
        iconSize: [38, 38],
        iconAnchor: [19, 19],
      });

      if (!driverMarkerRef.current) {
        driverMarkerRef.current = L.marker(latlng, { icon: vehicleIcon }).addTo(map);
        driverMarkerRef.current.bindPopup(`
          <div style="font-family: inherit; font-size: 0.85rem; padding: 4px; line-height: 1.4;">
            <strong style="color: #183B2A; font-size: 0.95rem;">${driverContext?.assigned_vehicle?.registration_number || 'Assigned Vehicle'}</strong><br/>
            Status: <span style="font-weight: 700; color: ${isOnDuty ? '#16A34A' : '#64748B'};">${driverContext?.duty_status || 'IDLE'}</span><br/>
            Position: ${lastCoords.latitude.toFixed(5)}, ${lastCoords.longitude.toFixed(5)}<br/>
            Accuracy: ±${Math.round(lastCoords.accuracy || 0)}m
          </div>
        `);
      } else {
        driverMarkerRef.current.setLatLng(latlng);
        driverMarkerRef.current.setIcon(vehicleIcon);
      }

      // Accuracy ring
      if (lastCoords.accuracy && lastCoords.accuracy > 0) {
        if (!accuracyCircleRef.current) {
          accuracyCircleRef.current = L.circle(latlng, {
            radius: Math.min(lastCoords.accuracy, 300),
            color: '#1B4D3E',
            fillColor: '#52B788',
            fillOpacity: 0.15,
            weight: 1.5,
          }).addTo(map);
        } else {
          accuracyCircleRef.current.setLatLng(latlng);
          accuracyCircleRef.current.setRadius(Math.min(lastCoords.accuracy, 300));
        }
      }
    }
  }, [lastCoords, driverContext?.assigned_vehicle, driverContext?.duty_status, isOnDuty]);

  const handleRecenter = () => {
    if (leafletMapRef.current && lastCoords) {
      leafletMapRef.current.setView([lastCoords.latitude, lastCoords.longitude], 16, { animate: true });
    }
  };

  const driver = driverContext?.driver;
  const vehicle = driverContext?.assigned_vehicle;
  const ward = driverContext?.assigned_ward;
  const route = driverContext?.assigned_route;

  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          backgroundColor: '#F5F9F5',
          color: '#183B2A',
        }}
      >
        <div style={{ textAlign: 'center' }}>
          <Spinner size="lg" />
          <div style={{ fontSize: '1.25rem', fontWeight: 800, marginTop: '1rem', color: '#183B2A' }}>
            NammaClean Driver Portal
          </div>
          <div style={{ fontSize: '0.85rem', color: '#5A7565', marginTop: '0.25rem' }}>
            Loading driver telemetry & vehicle assignment...
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', backgroundColor: '#F5F9F5' }}>
      {/* Shared Sidebar */}
      <CitizenSidebar
        role="driver"
        activeTab={activeTab}
        onTabChange={(tab) => {
          setActiveTab(tab as DriverTab);
          setActionError(null);
          setActionSuccess(null);
        }}
      />

      {/* Main Content Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflowX: 'hidden' }}>
        {/* Top Header & Civic Montage Band */}
        <section className="nc-dashboard-band" id="home">
          <CitizenHeader
            selectedWardName={
              ward?.display_name
                ? ward.display_name
                : currentUser?.locality
                ? `Ward: ${currentUser.locality}`
                : 'Ward 4 - Yelahanka Satellite Town'
            }
          />

          <div className="nc-dashboard-band-inner">
            <CitizenBanner
              user={currentUser}
              userName={driver?.full_name || driver?.email}
              isLoading={isLoading}
              titlePrefix="Welcome"
              subtitle="Municipal Solid Waste Collection Fleet & Live GPS Telemetry Portal"
              roleBadge="Driver Operations"
              showBirds={true}
            />

            {/* 4 Summary Cards matching civic design system */}
            <div className="nc-summary-overview" aria-label="Driver operational metrics">
              <div className="nc-summary-grid">
                {/* 1. Duty Status */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('dashboard')}
                  role="button"
                  tabIndex={0}
                  title="Click to view duty controls"
                >
                  <span className="nc-summary-icon">
                    <Clock size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>{isOnDuty ? 'ON DUTY' : 'OFF DUTY'}</strong>
                    <span className="nc-summary-label">Shift Status</span>
                    <span
                      className="nc-summary-note"
                      style={{ color: isOnDuty ? '#16A34A' : '#64748B' }}
                    >
                      {isOnDuty ? '● Active Shift' : '○ Standby (Idle)'}
                    </span>
                  </span>
                </article>

                {/* 2. Assigned Vehicle */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('vehicle')}
                  role="button"
                  tabIndex={0}
                  title="Click to view assigned vehicle specifications"
                >
                  <span className="nc-summary-icon">
                    <Truck size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>{vehicle ? vehicle.registration_number : 'Unassigned'}</strong>
                    <span className="nc-summary-label">Assigned Vehicle</span>
                    <span
                      className="nc-summary-note"
                      style={{ color: vehicle ? '#1B4D3E' : '#B45309' }}
                    >
                      {vehicle ? `${vehicle.vehicle_type.replace('_', ' ')} →` : 'Contact Supervisor'}
                    </span>
                  </span>
                </article>

                {/* 3. GPS Telemetry */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('tracking')}
                  role="button"
                  tabIndex={0}
                  title="Click to view live GPS telemetry diagnostics"
                >
                  <span className="nc-summary-icon">
                    <Navigation size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>
                      {isGpsActive
                        ? lastCoords?.accuracy
                          ? `±${Math.round(lastCoords.accuracy)}m Fix`
                          : 'Broadcasting'
                        : 'Standby'}
                    </strong>
                    <span className="nc-summary-label">GPS Telemetry</span>
                    <span
                      className="nc-summary-note"
                      style={{ color: isGpsActive ? '#16A34A' : '#64748B' }}
                    >
                      {isGpsActive ? '● Signal Ingested' : 'Awaiting Shift Start'}
                    </span>
                  </span>
                </article>

                {/* 4. Assigned Ward / Sector */}
                <article
                  className="nc-summary-card is-clickable"
                  onClick={() => setActiveTab('vehicle')}
                  role="button"
                  tabIndex={0}
                  title="Click to view ward & corridor route"
                >
                  <span className="nc-summary-icon">
                    <MapPin size={20} strokeWidth={2.2} aria-hidden="true" />
                  </span>
                  <span className="nc-summary-copy">
                    <strong>{ward?.ward_code || (ward ? 'Ward 4' : 'Fleet Depot')}</strong>
                    <span className="nc-summary-label">Operational Ward</span>
                    <span className="nc-summary-note" style={{ color: '#2E7D32' }}>
                      {route ? route.name.split(' ')[0] : 'Yelahanka'} →
                    </span>
                  </span>
                </article>
              </div>
            </div>
          </div>
        </section>

        {/* Dashboard Main View Container */}
        <main className="nc-dashboard-main" style={{ padding: '1.25rem 0 2.5rem' }}>
          <div
            style={{
              width: 'min(calc(100% - 3rem), 1440px)',
              margin: '0 auto',
              display: 'flex',
              flexDirection: 'column',
              gap: '1.25rem',
            }}
          >
            {/* Action Notices */}
            {actionError && (
              <Alert type="danger" title="Operation Notice">
                {actionError}
              </Alert>
            )}
            {actionSuccess && (
              <Alert type="success" title="Success">
                {actionSuccess}
              </Alert>
            )}

            {/* TAB 1: OPERATIONAL OVERVIEW & SHIFT CONTROL */}
            {activeTab === 'dashboard' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                {/* Top Row: Duty Shift Controller & Vehicle Allocation */}
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
                    gap: '1.25rem',
                  }}
                >
                  {/* CARD 1: Duty Status Control */}
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: '16px',
                      padding: '1.5rem',
                      border: '1px solid #D5E3D7',
                      boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                          <div
                            style={{
                              padding: '8px',
                              borderRadius: '10px',
                              backgroundColor: isOnDuty ? '#E8F5E9' : '#F1F5F9',
                              color: isOnDuty ? '#2E7D32' : '#64748B',
                            }}
                          >
                            <Clock size={20} />
                          </div>
                          <h2 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 750, color: '#183B2A' }}>
                            Shift Duty Control
                          </h2>
                        </div>
                        <span
                          style={{
                            fontSize: '0.78rem',
                            fontWeight: 700,
                            padding: '4px 12px',
                            borderRadius: '999px',
                            backgroundColor: isOnDuty ? '#E8F5E9' : '#F1F5F9',
                            color: isOnDuty ? '#166534' : '#64748B',
                            border: `1px solid ${isOnDuty ? '#86EFAC' : '#E2E8F0'}`,
                          }}
                        >
                          {isOnDuty ? '● Active Shift' : '○ Shift Idle'}
                        </span>
                      </div>

                      <p style={{ fontSize: '0.88rem', color: '#5A7565', lineHeight: 1.5, margin: '0 0 1.25rem' }}>
                        {isOnDuty
                          ? 'Your shift is currently active. High-frequency GPS telemetry is being transmitted periodically to city official command.'
                          : 'Start your shift to activate live GPS broadcasting and assign your vehicle as on-duty.'}
                      </p>

                      {driverContext?.duty_start_time && (
                        <div
                          style={{
                            padding: '0.75rem 1rem',
                            borderRadius: '10px',
                            backgroundColor: '#F8FAFC',
                            border: '1px solid #E2E8F0',
                            fontSize: '0.82rem',
                            color: '#334155',
                            marginBottom: '1.25rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                          }}
                        >
                          <Clock size={16} color="#64748B" />
                          <span>
                            Shift Started:{' '}
                            <strong>
                              {new Date(driverContext.duty_start_time).toLocaleTimeString([], {
                                hour: '2-digit',
                                minute: '2-digit',
                              })}
                            </strong>{' '}
                            ({new Date(driverContext.duty_start_time).toLocaleDateString()})
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Duty Shift Action Button */}
                    <div>
                      {isOnDuty ? (
                        <Button
                          type="button"
                          variant="primary"
                          onClick={handleEndDuty}
                          disabled={isSubmittingDuty}
                          style={{
                            width: '100%',
                            padding: '1rem',
                            backgroundColor: '#DC2626',
                            borderColor: '#DC2626',
                            color: '#FFFFFF',
                            fontSize: '1.05rem',
                            fontWeight: 800,
                            borderRadius: '12px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '0.6rem',
                          }}
                        >
                          <Power size={20} />
                          <span>{isSubmittingDuty ? 'Ending Duty...' : 'END DUTY SHIFT'}</span>
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          variant="primary"
                          onClick={handleStartDuty}
                          disabled={isSubmittingDuty || !vehicle}
                          style={{
                            width: '100%',
                            padding: '1rem',
                            backgroundColor: !vehicle ? '#94A3B8' : '#1B4D3E',
                            borderColor: !vehicle ? '#94A3B8' : '#1B4D3E',
                            color: '#FFFFFF',
                            fontSize: '1.05rem',
                            fontWeight: 800,
                            borderRadius: '12px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '0.6rem',
                          }}
                        >
                          <Power size={20} />
                          <span>{isSubmittingDuty ? 'Starting Duty...' : 'START DUTY SHIFT'}</span>
                        </Button>
                      )}

                      {!vehicle && (
                        <div style={{ marginTop: '0.75rem', fontSize: '0.8rem', color: '#D97706', textAlign: 'center' }}>
                          * A collection vehicle must be assigned by a supervisor before duty can start.
                        </div>
                      )}
                    </div>
                  </div>

                  {/* CARD 2: Assigned Fleet Vehicle */}
                  <div
                    style={{
                      backgroundColor: '#FFFFFF',
                      borderRadius: '16px',
                      padding: '1.5rem',
                      border: '1px solid #D5E3D7',
                      boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                          <div
                            style={{
                              padding: '8px',
                              borderRadius: '10px',
                              backgroundColor: vehicle ? '#E8F5E9' : '#FEF3C7',
                              color: vehicle ? '#1B4D3E' : '#B45309',
                            }}
                          >
                            <Truck size={20} />
                          </div>
                          <h2 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 750, color: '#183B2A' }}>
                            Assigned Fleet Unit
                          </h2>
                        </div>
                        <span
                          style={{
                            fontSize: '0.78rem',
                            fontWeight: 700,
                            padding: '4px 12px',
                            borderRadius: '999px',
                            backgroundColor: vehicle ? '#E8F5E9' : '#FEF3C7',
                            color: vehicle ? '#166534' : '#B45309',
                            border: `1px solid ${vehicle ? '#86EFAC' : '#FDE68A'}`,
                          }}
                        >
                          {vehicle ? 'Authorized Assignment' : 'Unassigned'}
                        </span>
                      </div>

                      {vehicle ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                          <div
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              padding: '0.85rem 1rem',
                              backgroundColor: '#F8FAFC',
                              borderRadius: '12px',
                              border: '1px solid #E2E8F0',
                            }}
                          >
                            <span style={{ fontSize: '0.85rem', color: '#64748B', fontWeight: 600 }}>Registration:</span>
                            <span style={{ fontSize: '1.25rem', fontWeight: 800, color: '#0F172A', letterSpacing: '0.04em' }}>
                              {vehicle.registration_number}
                            </span>
                          </div>

                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                            <div style={{ padding: '0.65rem 0.85rem', backgroundColor: '#F8FAFC', borderRadius: '10px' }}>
                              <div style={{ fontSize: '0.75rem', color: '#64748B' }}>Classification</div>
                              <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#1E293B', textTransform: 'capitalize' }}>
                                {vehicle.vehicle_type.toLowerCase().replace('_', ' ')}
                              </div>
                            </div>
                            <div style={{ padding: '0.65rem 0.85rem', backgroundColor: '#F8FAFC', borderRadius: '10px' }}>
                              <div style={{ fontSize: '0.75rem', color: '#64748B' }}>Operating Ward</div>
                              <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#1E293B' }}>
                                {ward?.ward_code || 'Ward 4'}
                              </div>
                            </div>
                          </div>

                          {route && (
                            <div
                              style={{
                                padding: '0.75rem 1rem',
                                borderRadius: '10px',
                                backgroundColor: '#E8F5E9',
                                border: '1px solid #C8E6C9',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.6rem',
                                fontSize: '0.82rem',
                                color: '#1B4D3E',
                              }}
                            >
                              <Route size={16} />
                              <span>
                                Assigned Route: <strong>{route.name}</strong>
                              </span>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div
                          style={{
                            padding: '1.75rem 1.25rem',
                            textAlign: 'center',
                            backgroundColor: '#FFFBEB',
                            borderRadius: '12px',
                            border: '1px solid #FDE68A',
                          }}
                        >
                          <AlertTriangle size={36} color="#D97706" style={{ margin: '0 auto 0.5rem' }} />
                          <h4 style={{ margin: '0 0 0.25rem', fontSize: '1rem', fontWeight: 750, color: '#92400E' }}>
                            No Vehicle Assigned
                          </h4>
                          <p style={{ margin: 0, fontSize: '0.84rem', color: '#B45309', lineHeight: 1.4 }}>
                            You have not been assigned a collection vehicle. Please contact your BBMP supervisor or municipal administrator to link a vehicle to your account.
                          </p>
                        </div>
                      )}
                    </div>

                    <div style={{ marginTop: '1rem', fontSize: '0.78rem', color: '#64748B' }}>
                      * Official vehicle assignments are managed and verified by Ward Supervisors.
                    </div>
                  </div>
                </div>

                {/* Middle Row: Interactive Driver Map & Navigation */}
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: '16px',
                    border: '1px solid #D5E3D7',
                    overflow: 'hidden',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                    display: 'flex',
                    flexDirection: 'column',
                  }}
                >
                  {/* Map Header with Civic Navigation Controls */}
                  <div
                    style={{
                      padding: '1rem 1.5rem',
                      borderBottom: '1px solid #E2E8F0',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      flexWrap: 'wrap',
                      gap: '0.75rem',
                      backgroundColor: '#FFFFFF',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                      <MapPin size={20} color="#183B2A" />
                      <div>
                        <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 750, color: '#183B2A' }}>
                          Live Fleet GPS Tracking &amp; Position
                        </h3>
                        <p style={{ margin: '0.15rem 0 0', fontSize: '0.8rem', color: '#5A7565' }}>
                          Real-time device coordinates plotted on BBMP municipal collection corridor
                        </p>
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                      {/* Telemetry Status Badge */}
                      <span
                        style={{
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          padding: '4px 10px',
                          borderRadius: '999px',
                          backgroundColor: isGpsActive ? '#E8F5E9' : '#F1F5F9',
                          color: isGpsActive ? '#15803D' : '#64748B',
                          border: `1px solid ${isGpsActive ? '#86EFAC' : '#CBD5E1'}`,
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.35rem',
                        }}
                      >
                        <span
                          style={{
                            width: '6px',
                            height: '6px',
                            borderRadius: '50%',
                            backgroundColor: isGpsActive ? '#22C55E' : '#94A3B8',
                          }}
                        />
                        {isGpsActive ? '● Signal Ingested' : '○ Standby'}
                      </span>

                      {/* Map Layer Mode Switcher */}
                      <div
                        style={{
                          display: 'inline-flex',
                          borderRadius: '8px',
                          border: '1px solid #CBD5E1',
                          overflow: 'hidden',
                        }}
                      >
                        <button
                          type="button"
                          onClick={() => setMapMode('street')}
                          style={{
                            padding: '4px 10px',
                            fontSize: '0.78rem',
                            fontWeight: 700,
                            border: 'none',
                            backgroundColor: mapMode === 'street' ? '#1B4D3E' : '#FFFFFF',
                            color: mapMode === 'street' ? '#FFFFFF' : '#475569',
                            cursor: 'pointer',
                          }}
                        >
                          Street
                        </button>
                        <button
                          type="button"
                          onClick={() => setMapMode('satellite')}
                          style={{
                            padding: '4px 10px',
                            fontSize: '0.78rem',
                            fontWeight: 700,
                            border: 'none',
                            backgroundColor: mapMode === 'satellite' ? '#1B4D3E' : '#FFFFFF',
                            color: mapMode === 'satellite' ? '#FFFFFF' : '#475569',
                            cursor: 'pointer',
                          }}
                        >
                          Satellite
                        </button>
                      </div>

                      <Button
                        type="button"
                        variant="outline"
                        onClick={handleRecenter}
                        disabled={!lastCoords}
                        style={{ fontSize: '0.8rem', padding: '5px 12px' }}
                      >
                        <Crosshair size={14} />
                        <span>Recenter</span>
                      </Button>
                    </div>
                  </div>

                  {/* Leaflet Map Canvas */}
                  <div
                    ref={mapContainerRef}
                    style={{
                      width: '100%',
                      height: '420px',
                      backgroundColor: '#E2E8F0',
                    }}
                  />

                  {/* Map Footer status */}
                  <div
                    style={{
                      padding: '0.75rem 1.5rem',
                      backgroundColor: '#F8FAFC',
                      borderTop: '1px solid #E2E8F0',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      flexWrap: 'wrap',
                      gap: '0.75rem',
                      fontSize: '0.82rem',
                      color: '#64748B',
                    }}
                  >
                    <span>
                      Coordinates:{' '}
                      <strong style={{ color: '#0F172A', fontFamily: 'monospace' }}>
                        {lastCoords
                          ? `${lastCoords.latitude.toFixed(5)}, ${lastCoords.longitude.toFixed(5)}`
                          : 'Awaiting device fix'}
                      </strong>
                    </span>
                    <span>
                      Accuracy: <strong style={{ color: '#0F172A' }}>{lastCoords?.accuracy ? `±${Math.round(lastCoords.accuracy)} meters` : '—'}</strong>
                    </span>
                    <span>
                      Speed:{' '}
                      <strong style={{ color: '#0F172A' }}>
                        {lastCoords?.speed ? `${Math.round(lastCoords.speed * 3.6)} km/h` : '0 km/h'}
                      </strong>
                    </span>
                    <span>
                      Last Server Sync:{' '}
                      <strong style={{ color: '#0F172A' }}>
                        {lastPingTime
                          ? lastPingTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                          : 'Not transmitted yet'}
                      </strong>
                    </span>
                  </div>
                </div>

                {/* Bottom Row: Telemetry Health & Live Events Log */}
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: '16px',
                    padding: '1.5rem',
                    border: '1px solid #D5E3D7',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '1rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <div
                        style={{
                          padding: '6px',
                          borderRadius: '8px',
                          backgroundColor: isGpsActive ? '#E8F5E9' : '#F1F5F9',
                          color: isGpsActive ? '#1B4D3E' : '#64748B',
                        }}
                      >
                        {isGpsActive ? <Wifi size={18} /> : <WifiOff size={18} />}
                      </div>
                      <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 750, color: '#183B2A' }}>
                        Driver Shift Activity &amp; Ingestion Log
                      </h3>
                    </div>

                    <span style={{ fontSize: '0.78rem', color: '#64748B' }}>
                      Auto-purges older events (Max 20 retained in session)
                    </span>
                  </div>

                  {gpsError && (
                    <Alert type="warning" title="GPS Device Notice">
                      {gpsError}
                    </Alert>
                  )}

                  <div
                    style={{
                      backgroundColor: '#F8FAFC',
                      borderRadius: '12px',
                      border: '1px solid #E2E8F0',
                      padding: '0.5rem',
                      maxHeight: '180px',
                      overflowY: 'auto',
                      fontSize: '0.8rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.4rem',
                    }}
                  >
                    {activityLogs.length > 0 ? (
                      activityLogs.map((log) => (
                        <div
                          key={log.id}
                          style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: '0.75rem',
                            padding: '4px 8px',
                            borderRadius: '6px',
                            backgroundColor: log.type === 'error' ? '#FEE2E2' : log.type === 'success' ? '#F0FDF4' : 'transparent',
                            color: log.type === 'error' ? '#DC2626' : log.type === 'success' ? '#15803D' : '#334155',
                          }}
                        >
                          <span style={{ color: '#94A3B8', fontFamily: 'monospace', minWidth: '65px' }}>
                            {log.time}
                          </span>
                          <span style={{ fontWeight: 500 }}>{log.message}</span>
                        </div>
                      ))
                    ) : (
                      <div style={{ color: '#94A3B8', textAlign: 'center', padding: '1.5rem' }}>
                        No activity events recorded yet. Start duty to begin telemetry broadcasting.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: LIVE GPS TELEMETRY DEEP-DIVE */}
            {activeTab === 'tracking' && (
              <div
                style={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '16px',
                  padding: '1.75rem',
                  border: '1px solid #D5E3D7',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
                  <div>
                    <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 750, color: '#183B2A' }}>
                      Expanded GPS Telemetry &amp; Device Diagnostics
                    </h2>
                    <p style={{ margin: '0.2rem 0 0', fontSize: '0.85rem', color: '#5A7565' }}>
                      Inspect WGS 84 spatial coordinates, device signal precision, and transmission heartbeat.
                    </p>
                  </div>

                  <Button
                    type="button"
                    variant="primary"
                    onClick={obtainCurrentGps}
                    style={{ fontSize: '0.82rem', padding: '6px 14px', backgroundColor: '#1B4D3E' }}
                  >
                    <RefreshCw size={14} />
                    <span>Broadcast GPS Fix Now</span>
                  </Button>
                </div>

                {/* Diagnostics Grid */}
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                    gap: '1rem',
                    marginBottom: '1.5rem',
                  }}
                >
                  <div style={{ padding: '1rem', backgroundColor: '#F8FAFC', borderRadius: '12px', border: '1px solid #E2E8F0' }}>
                    <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Latitude (Y)</div>
                    <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#0F172A', fontFamily: 'monospace' }}>
                      {lastCoords?.latitude.toFixed(6) ?? '—'}
                    </div>
                  </div>
                  <div style={{ padding: '1rem', backgroundColor: '#F8FAFC', borderRadius: '12px', border: '1px solid #E2E8F0' }}>
                    <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Longitude (X)</div>
                    <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#0F172A', fontFamily: 'monospace' }}>
                      {lastCoords?.longitude.toFixed(6) ?? '—'}
                    </div>
                  </div>
                  <div style={{ padding: '1rem', backgroundColor: '#F8FAFC', borderRadius: '12px', border: '1px solid #E2E8F0' }}>
                    <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Signal Accuracy</div>
                    <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#0F172A' }}>
                      {lastCoords?.accuracy ? `±${Math.round(lastCoords.accuracy)} meters` : '—'}
                    </div>
                  </div>
                  <div style={{ padding: '1rem', backgroundColor: '#F8FAFC', borderRadius: '12px', border: '1px solid #E2E8F0' }}>
                    <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Ground Speed</div>
                    <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#0F172A' }}>
                      {lastCoords?.speed ? `${Math.round(lastCoords.speed * 3.6)} km/h` : '0 km/h'}
                    </div>
                  </div>
                </div>

                {/* Expanded Map View */}
                <div
                  ref={trackingMapContainerRef}
                  style={{
                    width: '100%',
                    height: '460px',
                    borderRadius: '12px',
                    border: '1px solid #CBD5E1',
                    overflow: 'hidden',
                  }}
                />
              </div>
            )}

            {/* TAB 3: VEHICLE & ROUTE INFO */}
            {activeTab === 'vehicle' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: '16px',
                    padding: '1.75rem',
                    border: '1px solid #D5E3D7',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                  }}
                >
                  <h2 style={{ margin: '0 0 0.4rem', fontSize: '1.25rem', fontWeight: 750, color: '#183B2A' }}>
                    Municipal Fleet Vehicle Record
                  </h2>
                  <p style={{ margin: '0 0 1.25rem', fontSize: '0.85rem', color: '#5A7565' }}>
                    Technical profile and operational telemetry specifications for your assigned unit.
                  </p>

                  {vehicle ? (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1rem' }}>
                      <div style={{ padding: '1rem', backgroundColor: '#F8FAFC', borderRadius: '12px', border: '1px solid #E2E8F0' }}>
                        <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Registration Number</div>
                        <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#0F172A' }}>
                          {vehicle.registration_number}
                        </div>
                      </div>
                      <div style={{ padding: '1rem', backgroundColor: '#F8FAFC', borderRadius: '12px', border: '1px solid #E2E8F0' }}>
                        <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Vehicle Type</div>
                        <div style={{ fontSize: '1.1rem', fontWeight: 750, color: '#0F172A', textTransform: 'capitalize' }}>
                          {vehicle.vehicle_type.toLowerCase().replace('_', ' ')}
                        </div>
                      </div>
                      <div style={{ padding: '1rem', backgroundColor: '#F8FAFC', borderRadius: '12px', border: '1px solid #E2E8F0' }}>
                        <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Assigned Ward</div>
                        <div style={{ fontSize: '1.1rem', fontWeight: 750, color: '#0F172A' }}>
                          {ward?.display_name || 'Ward 4 - Yelahanka Satellite Town'}
                        </div>
                      </div>
                      <div style={{ padding: '1rem', backgroundColor: '#F8FAFC', borderRadius: '12px', border: '1px solid #E2E8F0' }}>
                        <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Public Map Broadcast</div>
                        <div style={{ fontSize: '1.1rem', fontWeight: 750, color: vehicle.is_published ? '#15803D' : '#64748B' }}>
                          {vehicle.is_published ? 'Published to Citizens' : 'Internal Fleet Only'}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <Alert type="warning" title="No Vehicle Assigned">
                      No vehicle is currently associated with your driver account. Contact your ward supervisor to assign a collection vehicle.
                    </Alert>
                  )}
                </div>

                {/* Pre-Trip Safety Inspection Checklist */}
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: '16px',
                    padding: '1.5rem',
                    border: '1px solid #D5E3D7',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                  }}
                >
                  <h3 style={{ margin: '0 0 0.5rem', fontSize: '1.1rem', fontWeight: 750, color: '#183B2A' }}>
                    Pre-Trip Driver Safety &amp; Equipment Checklist
                  </h3>
                  <p style={{ margin: '0 0 1rem', fontSize: '0.85rem', color: '#5A7565' }}>
                    Mandatory daily inspection items before deploying on municipal collection routes.
                  </p>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '0.75rem' }}>
                    {[
                      { key: 'brakes' as const, label: 'Service Brakes & Steering Responsive' },
                      { key: 'tires' as const, label: 'Tire Pressure & Tread Condition Verified' },
                      { key: 'fuel' as const, label: 'Fuel / EV Battery Level Adequate' },
                      { key: 'beacon' as const, label: 'Mirrors, Warning Beacons & GPS Active' },
                      { key: 'safety' as const, label: 'Safety First Aid Kit & Reflective Vest Present' },
                      { key: 'hydraulics' as const, label: 'Compactor / Tipper Hydraulics Operational' },
                    ].map((item) => (
                      <label
                        key={item.key}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.75rem',
                          padding: '0.85rem 1rem',
                          borderRadius: '10px',
                          backgroundColor: checklist[item.key] ? '#F0FDF4' : '#F8FAFC',
                          border: `1px solid ${checklist[item.key] ? '#86EFAC' : '#E2E8F0'}`,
                          cursor: 'pointer',
                          fontSize: '0.85rem',
                          fontWeight: 600,
                          color: checklist[item.key] ? '#166534' : '#475569',
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={checklist[item.key]}
                          onChange={(e) => setChecklist((prev) => ({ ...prev, [item.key]: e.target.checked }))}
                          style={{ accentColor: '#1B4D3E', width: '16px', height: '16px' }}
                        />
                        <span>{item.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* TAB 4: DRIVER PROFILE & MUNICIPAL DIRECTORY */}
            {activeTab === 'profile' && (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
                  gap: '1.25rem',
                }}
              >
                {/* Driver Credentials Card */}
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: '16px',
                    padding: '1.75rem',
                    border: '1px solid #D5E3D7',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                  }}
                >
                  <h2 style={{ margin: '0 0 0.4rem', fontSize: '1.25rem', fontWeight: 750, color: '#183B2A' }}>
                    Driver Account Credentials
                  </h2>
                  <p style={{ margin: '0 0 1.25rem', fontSize: '0.85rem', color: '#5A7565' }}>
                    Official workforce identification for BBMP Solid Waste Management.
                  </p>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
                    <div style={{ padding: '0.85rem 1rem', backgroundColor: '#F8FAFC', borderRadius: '10px', border: '1px solid #E2E8F0' }}>
                      <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Driver Full Name</div>
                      <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#0F172A' }}>
                        {driver?.full_name || 'Driver (Unspecified Name)'}
                      </div>
                    </div>

                    <div style={{ padding: '0.85rem 1rem', backgroundColor: '#F8FAFC', borderRadius: '10px', border: '1px solid #E2E8F0' }}>
                      <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Official Driver ID</div>
                      <div style={{ fontSize: '1.05rem', fontWeight: 800, color: driver?.official_id ? '#0369A1' : '#92400E' }}>
                        {driver?.official_id || 'Pending Official ID'}
                      </div>
                    </div>

                    <div style={{ padding: '0.85rem 1rem', backgroundColor: '#F8FAFC', borderRadius: '10px', border: '1px solid #E2E8F0' }}>
                      <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Authorized Login ID</div>
                      <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#0F172A' }}>
                        {driver?.email}
                      </div>
                    </div>

                    <div style={{ padding: '0.85rem 1rem', backgroundColor: '#F8FAFC', borderRadius: '10px', border: '1px solid #E2E8F0' }}>
                      <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>System Role Classification</div>
                      <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#1B4D3E' }}>
                        DRIVER (Municipal Solid Waste Driver)
                      </div>
                    </div>

                    <div style={{ padding: '0.85rem 1rem', backgroundColor: '#F8FAFC', borderRadius: '10px', border: '1px solid #E2E8F0' }}>
                      <div style={{ fontSize: '0.75rem', color: '#64748B', fontWeight: 600 }}>Account Operational Status</div>
                      <div style={{ fontSize: '1.05rem', fontWeight: 800, color: driver?.status === 'ACTIVE' ? '#15803D' : '#DC2626' }}>
                        {driver?.status}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Municipal Emergency Contacts Card */}
                <div
                  style={{
                    backgroundColor: '#FFFFFF',
                    borderRadius: '16px',
                    padding: '1.75rem',
                    border: '1px solid #D5E3D7',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.4rem' }}>
                      <PhoneCall size={20} color="#1B4D3E" />
                      <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 750, color: '#183B2A' }}>
                        BBMP Operational Helplines
                      </h2>
                    </div>
                    <p style={{ margin: '0 0 1.25rem', fontSize: '0.85rem', color: '#5A7565' }}>
                      Immediate assistance for on-route vehicle breakdown, route issues, or supervisor dispatch.
                    </p>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                      <div style={{ padding: '0.75rem 1rem', backgroundColor: '#F8FAFC', borderRadius: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                          <div style={{ fontWeight: 750, color: '#183B2A' }}>BBMP City Control Room</div>
                          <div style={{ fontSize: '0.75rem', color: '#64748B' }}>Toll-Free 24x7 Civic Desk</div>
                        </div>
                        <a href="tel:1533" style={{ fontWeight: 800, color: '#1B4D3E', textDecoration: 'none', fontSize: '1.1rem' }}>
                          1533
                        </a>
                      </div>

                      <div style={{ padding: '0.75rem 1rem', backgroundColor: '#F8FAFC', borderRadius: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                          <div style={{ fontWeight: 750, color: '#183B2A' }}>Yelahanka Ward Supervisor Desk</div>
                          <div style={{ fontSize: '0.75rem', color: '#64748B' }}>Sub-Division Office, Sector 4</div>
                        </div>
                        <a href="tel:08022660000" style={{ fontWeight: 800, color: '#1B4D3E', textDecoration: 'none', fontSize: '0.95rem' }}>
                          080-22660000
                        </a>
                      </div>

                      <div style={{ padding: '0.75rem 1rem', backgroundColor: '#F8FAFC', borderRadius: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                          <div style={{ fontWeight: 750, color: '#183B2A' }}>Fleet Mechanical Breakdown</div>
                          <div style={{ fontSize: '0.75rem', color: '#64748B' }}>Emergency Municipal Towing</div>
                        </div>
                        <a href="tel:+918023630401" style={{ fontWeight: 800, color: '#1B4D3E', textDecoration: 'none', fontSize: '0.95rem' }}>
                          +91 80 2363 0401
                        </a>
                      </div>
                    </div>
                  </div>

                  <div style={{ marginTop: '1.5rem', padding: '0.75rem', backgroundColor: '#E8F5E9', borderRadius: '10px', fontSize: '0.8rem', color: '#1B4D3E' }}>
                    <ShieldCheck size={16} style={{ display: 'inline', marginRight: '6px', verticalAlign: 'text-bottom' }} />
                    Driver accounts are covered under the BBMP Municipal Workers Safety &amp; Insurance Protocol.
                  </div>
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
};
