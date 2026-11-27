import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Camera,
  CheckCircle2,
  RefreshCw,
  Upload,
  X,
  Search,
  Layers,
  Crosshair,
} from 'lucide-react';
import { Button } from '../ui/Button';
import { Alert } from '../ui/Alert';
import { Spinner } from '../ui/Spinner';
import {
  createDumpingReport,
  uploadReportEvidence,
} from '../../api/reports';
import { searchPlaces, reverseGeocode, PlaceSearchResult } from '../../api/geocoding';
import { DumpingReport } from '../../types';
import { embedWatermark, WatermarkedEvidence } from '../../utils/watermark';

interface ReportDumpingModalProps {
  isOpen: boolean;
  onClose: () => void;
  defaultCoordinates?: { latitude: number; longitude: number };
  onReportCreated?: (report: DumpingReport) => void;
}

const MAX_EVIDENCE_FILES = 5;
const MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024; // 5 MB
const ALLOWED_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

export const ReportDumpingModal: React.FC<ReportDumpingModalProps> = ({
  isOpen,
  onClose,
  defaultCoordinates,
  onReportCreated,
}) => {
  const navigate = useNavigate();
  const dialogRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const miniMapContainerRef = useRef<HTMLDivElement | null>(null);
  const miniMapInstanceRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const streetLayerRef = useRef<L.TileLayer | null>(null);
  const satelliteLayerRef = useRef<L.TileLayer | null>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Form states
  const [description, setDescription] = useState('');
  const [latitude, setLatitude] = useState(defaultCoordinates ? String(defaultCoordinates.latitude) : '13.0985');
  const [longitude, setLongitude] = useState(defaultCoordinates ? String(defaultCoordinates.longitude) : '77.5895');
  const [evidenceItems, setEvidenceItems] = useState<WatermarkedEvidence[]>([]);

  // Location search & geocoding states
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<PlaceSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [readablePlace, setReadablePlace] = useState('Yelahanka New Town, Bengaluru');
  const [selectionMethod, setSelectionMethod] = useState<'gps' | 'search' | 'manual'>('manual');
  const [mapLayer, setMapLayer] = useState<'standard' | 'satellite'>('standard');

  // Processing & progress states
  const [isLocating, setIsLocating] = useState(false);
  const [gpsAccuracy, setGpsAccuracy] = useState<number | null>(null);
  const [locationNotice, setLocationNotice] = useState<{ type: 'info' | 'danger'; message: string } | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isWatermarking, setIsWatermarking] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Success / Partial success states
  const [createdReport, setCreatedReport] = useState<DumpingReport | null>(null);
  const [failedUploads, setFailedUploads] = useState<{ file: File; reason: string }[]>([]);
  const [isComplete, setIsComplete] = useState(false);

  // Authentication check
  const token = localStorage.getItem('nammaclean.access_token');
  const userRole = localStorage.getItem('nammaclean.user_role');
  const isCitizen = Boolean(token) && (!userRole || userRole === 'CITIZEN');

  // Resolve human-readable place name
  const resolvePlaceName = useCallback(async (lat: number, lon: number, method: 'gps' | 'search' | 'manual') => {
    try {
      const res = await reverseGeocode(lat, lon, method);
      if (res && res.display_name) {
        setReadablePlace(res.display_name);
      }
    } catch {
      setReadablePlace(`Bengaluru Location (${lat.toFixed(4)}, ${lon.toFixed(4)})`);
    }
  }, []);

  // Update default coordinates if provided
  useEffect(() => {
    if (defaultCoordinates) {
      setLatitude(String(defaultCoordinates.latitude));
      setLongitude(String(defaultCoordinates.longitude));
    }
  }, [defaultCoordinates]);

  // Handle Escape key and focus
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isSubmitting && !isWatermarking) {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, isSubmitting, isWatermarking, onClose]);

  // Leaflet Mini-Map Initialization with Draggable Pin
  useEffect(() => {
    if (!isOpen) {
      if (miniMapInstanceRef.current) {
        miniMapInstanceRef.current.remove();
        miniMapInstanceRef.current = null;
        markerRef.current = null;
      }
      return;
    }

    // Delay slightly to let modal container render in DOM
    const timer = setTimeout(() => {
      if (!miniMapContainerRef.current) return;

      const latNum = parseFloat(latitude) || 12.9716;
      const lonNum = parseFloat(longitude) || 77.5946;

      if (!miniMapInstanceRef.current) {
        const miniMap = L.map(miniMapContainerRef.current, {
          center: [latNum, lonNum],
          zoom: 15,
          zoomControl: false,
          attributionControl: false,
        });

        const streetLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19,
          attribution: '&copy; OpenStreetMap',
        });
        const satelliteLayer = L.tileLayer(
          'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          {
            maxZoom: 19,
            attribution: 'Tiles &copy; Esri',
          }
        );
        streetLayerRef.current = streetLayer;
        satelliteLayerRef.current = satelliteLayer;
        if (mapLayer === 'satellite') {
          satelliteLayer.addTo(miniMap);
        } else {
          streetLayer.addTo(miniMap);
        }

        const pinIcon = L.divIcon({
          className: 'custom-drag-pin',
          html: `
            <div style="cursor: grab; width: 28px; height: 34px; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4));">
              <svg width="28" height="34" viewBox="0 0 30 38" fill="none">
                <path d="M15 0C6.716 0 0 6.716 0 15C0 26.25 15 38 15 38C15 38 30 26.25 30 15C30 6.716 23.284 0 15 0Z" fill="#DC2626" stroke="#FFFFFF" stroke-width="2"/>
                <circle cx="15" cy="14" r="5" fill="#FFFFFF"/>
              </svg>
            </div>
          `,
          iconSize: [28, 34],
          iconAnchor: [14, 34],
        });

        const marker = L.marker([latNum, lonNum], {
          draggable: true,
          icon: pinIcon,
        }).addTo(miniMap);

        // Click on map moves marker and updates coordinates
        miniMap.on('click', (e: L.LeafletMouseEvent) => {
          const lat = e.latlng.lat;
          const lon = e.latlng.lng;
          setLatitude(lat.toFixed(6));
          setLongitude(lon.toFixed(6));
          setSelectionMethod('manual');
          if (markerRef.current) markerRef.current.setLatLng([lat, lon]);
          resolvePlaceName(lat, lon, 'manual');
        });

        marker.on('dragend', () => {
          const pos = marker.getLatLng();
          setLatitude(pos.lat.toFixed(6));
          setLongitude(pos.lng.toFixed(6));
          setSelectionMethod('manual');
          resolvePlaceName(pos.lat, pos.lng, 'manual');
        });

        markerRef.current = marker;
        miniMapInstanceRef.current = miniMap;
        resolvePlaceName(latNum, lonNum, 'manual');
      } else {
        miniMapInstanceRef.current.invalidateSize();
        miniMapInstanceRef.current.setView([latNum, lonNum], 15);
        if (markerRef.current) {
          markerRef.current.setLatLng([latNum, lonNum]);
        }
      }
    }, 150);

    return () => {
      clearTimeout(timer);
    };
  }, [isOpen]);

  // Synchronize mini-map when manual coordinate inputs change
  useEffect(() => {
    const latNum = parseFloat(latitude);
    const lonNum = parseFloat(longitude);
    if (
      !isNaN(latNum) &&
      !isNaN(lonNum) &&
      latNum >= -90 &&
      latNum <= 90 &&
      lonNum >= -180 &&
      lonNum <= 180 &&
      miniMapInstanceRef.current &&
      markerRef.current
    ) {
      const curPos = markerRef.current.getLatLng();
      if (Math.abs(curPos.lat - latNum) > 0.00005 || Math.abs(curPos.lng - lonNum) > 0.00005) {
        markerRef.current.setLatLng([latNum, lonNum]);
        miniMapInstanceRef.current.panTo([latNum, lonNum], { animate: true });
      }
    }
  }, [latitude, longitude]);

  // Layer switch handler
  const handleToggleMapLayer = (mode: 'standard' | 'satellite') => {
    setMapLayer(mode);
    if (!miniMapInstanceRef.current) return;
    if (mode === 'satellite') {
      if (streetLayerRef.current) miniMapInstanceRef.current.removeLayer(streetLayerRef.current);
      if (satelliteLayerRef.current) satelliteLayerRef.current.addTo(miniMapInstanceRef.current);
    } else {
      if (satelliteLayerRef.current) miniMapInstanceRef.current.removeLayer(satelliteLayerRef.current);
      if (streetLayerRef.current) streetLayerRef.current.addTo(miniMapInstanceRef.current);
    }
  };

  // Place search input debouncer
  const handleSearchChange = (val: string) => {
    setSearchQuery(val);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!val.trim()) {
      setSearchResults([]);
      setShowSuggestions(false);
      return;
    }
    searchTimerRef.current = setTimeout(async () => {
      setIsSearching(true);
      const res = await searchPlaces(val);
      setSearchResults(res);
      setShowSuggestions(res.length > 0);
      setIsSearching(false);
    }, 250);
  };

  const handleSelectPlace = (place: PlaceSearchResult) => {
    setSearchQuery(place.display_name);
    setShowSuggestions(false);
    setLatitude(place.latitude.toFixed(6));
    setLongitude(place.longitude.toFixed(6));
    setReadablePlace(place.display_name);
    setSelectionMethod('search');

    if (miniMapInstanceRef.current && markerRef.current) {
      miniMapInstanceRef.current.flyTo([place.latitude, place.longitude], 16, { duration: 0.8 });
      markerRef.current.setLatLng([place.latitude, place.longitude]);
    }
  };

  // Browser Geolocation Detection
  const handleDetectLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setLocationNotice({
        type: 'danger',
        message: 'Geolocation is not supported by your browser. Please enter coordinates manually.',
      });
      return;
    }

    setIsLocating(true);
    setLocationNotice(null);

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = position.coords.latitude;
        const lon = position.coords.longitude;
        const acc = position.coords.accuracy;

        setLatitude(lat.toFixed(6));
        setLongitude(lon.toFixed(6));
        setGpsAccuracy(acc);
        setSelectionMethod('gps');
        resolvePlaceName(lat, lon, 'gps');

        if (miniMapInstanceRef.current && markerRef.current) {
          miniMapInstanceRef.current.flyTo([lat, lon], 16, { duration: 1.0 });
          markerRef.current.setLatLng([lat, lon]);
        }

        setLocationNotice({
          type: 'info',
          message: `Location acquired: accuracy within ±${Math.round(acc)}m.`,
        });
        setIsLocating(false);
      },
      (error) => {
        let msg = 'Could not retrieve your location. Please enter coordinates manually.';
        if (error.code === error.PERMISSION_DENIED) {
          msg = 'Location permission was denied. Please enter coordinates manually.';
        } else if (error.code === error.TIMEOUT) {
          msg = 'Location detection timed out. Please enter coordinates manually.';
        }
        setLocationNotice({ type: 'danger', message: msg });
        setIsLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
    );
  }, [resolvePlaceName]);

  // Process selected or captured files with canvas watermarking
  const processAndWatermarkFiles = async (selected: File[]) => {
    if (!selected.length) return;

    setIsWatermarking(true);
    setErrorMessage(null);

    let latNum = parseFloat(latitude);
    let lonNum = parseFloat(longitude);
    let currentAcc = gpsAccuracy;

    // If coordinates are not set or default, auto-detect location
    if (isNaN(latNum) || isNaN(lonNum)) {
      if (navigator.geolocation) {
        try {
          const pos = await new Promise<GeolocationPosition>((res, rej) => {
            navigator.geolocation.getCurrentPosition(res, rej, { enableHighAccuracy: true, timeout: 6000 });
          });
          latNum = pos.coords.latitude;
          lonNum = pos.coords.longitude;
          currentAcc = pos.coords.accuracy;
          setLatitude(latNum.toFixed(6));
          setLongitude(lonNum.toFixed(6));
          setGpsAccuracy(currentAcc);
        } catch {
          latNum = 12.9716;
          lonNum = 77.5946;
          setLatitude('12.9716');
          setLongitude('77.5946');
        }
      } else {
        latNum = 12.9716;
        lonNum = 77.5946;
        setLatitude('12.9716');
        setLongitude('77.5946');
      }
    }

    const newItems: WatermarkedEvidence[] = [];
    const errors: string[] = [];

    const localityName = readablePlace || 'Bengaluru';

    for (const file of selected) {
      if (!ALLOWED_MIME_TYPES.includes(file.type)) {
        errors.push(`"${file.name}": Unsupported format. Allowed: JPEG, PNG, WebP.`);
        continue;
      }
      if (file.size > MAX_FILE_SIZE_BYTES) {
        errors.push(`"${file.name}": File size exceeds 5MB limit (${(file.size / (1024 * 1024)).toFixed(1)}MB).`);
        continue;
      }

      try {
        const item = await embedWatermark(file, {
          latitude: latNum,
          longitude: lonNum,
          accuracy: currentAcc,
          localityName,
          timestamp: new Date(),
        });
        newItems.push(item);
      } catch (err) {
        console.warn('Watermarking fallback to original file', err);
        newItems.push({
          originalFile: file,
          watermarkedFile: file,
          previewUrl: URL.createObjectURL(file),
        });
      }
    }

    if (evidenceItems.length + newItems.length > MAX_EVIDENCE_FILES) {
      errors.push(`You can attach a maximum of ${MAX_EVIDENCE_FILES} photos per report.`);
    }

    if (errors.length > 0) {
      setErrorMessage(errors.join(' '));
    }

    const combined = [...evidenceItems, ...newItems].slice(0, MAX_EVIDENCE_FILES);
    setEvidenceItems(combined);
    setIsWatermarking(false);
  };

  const handleRemoveEvidence = (index: number) => {
    setEvidenceItems((prev) => prev.filter((_, i) => i !== index));
    setErrorMessage(null);
  };

  // Sequential Evidence Upload Worker
  const uploadEvidenceFiles = async (reportId: string, filesToUpload: File[]) => {
    const failed: { file: File; reason: string }[] = [];

    for (let i = 0; i < filesToUpload.length; i++) {
      const file = filesToUpload[i];
      setUploadProgress(`Uploading geo-tagged photo ${i + 1} of ${filesToUpload.length}: ${file.name}...`);

      try {
        await uploadReportEvidence(reportId, file);
      } catch (err: unknown) {
        const detail = typeof err === 'object' && err !== null && 'detail' in err
          ? String((err as { detail: unknown }).detail)
          : err instanceof Error
            ? err.message
            : 'Upload failed.';
        failed.push({ file, reason: detail });
      }
    }

    return failed;
  };

  // Main Submit Handler
  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    const trimmedDesc = description.trim();
    if (trimmedDesc.length < 10) {
      setErrorMessage('Description must contain at least 10 characters.');
      return;
    }
    if (trimmedDesc.length > 1000) {
      setErrorMessage('Description must not exceed 1000 characters.');
      return;
    }

    const latNum = parseFloat(latitude);
    const lonNum = parseFloat(longitude);
    if (isNaN(latNum) || latNum < -90 || latNum > 90) {
      setErrorMessage('Please enter a valid latitude between -90 and +90.');
      return;
    }
    if (isNaN(lonNum) || lonNum < -180 || lonNum > 180) {
      setErrorMessage('Please enter a valid longitude between -180 and +180.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);
    setUploadProgress('Creating incident report with municipal control room...');

    try {
      // Step 1: Create the incident report
      const report = await createDumpingReport({
        description: trimmedDesc,
        latitude: latNum,
        longitude: lonNum,
        ward_id: null,
      });

      setCreatedReport(report);
      onReportCreated?.(report);

      // Step 2: Upload watermarked evidence photos sequentially
      const filesToUpload = evidenceItems.map((item) => item.watermarkedFile);
      if (filesToUpload.length > 0) {
        const failed = await uploadEvidenceFiles(report.id, filesToUpload);
        if (failed.length > 0) {
          setFailedUploads(failed);
          setErrorMessage(`Report #${report.id.slice(0, 8)} was registered, but ${failed.length} of ${filesToUpload.length} photos failed to attach.`);
        } else {
          setIsComplete(true);
        }
      } else {
        setIsComplete(true);
      }
    } catch (err: unknown) {
      const detail = typeof err === 'object' && err !== null && 'detail' in err
        ? String((err as { detail: unknown }).detail)
        : err instanceof Error
          ? err.message
          : 'Failed to submit report. Please check your network and try again.';
      setErrorMessage(detail);
    } finally {
      setIsSubmitting(false);
      setUploadProgress(null);
    }
  };

  // Retry Failed Evidence Uploads
  const handleRetryFailedEvidence = async () => {
    if (!createdReport || failedUploads.length === 0) return;

    setIsSubmitting(true);
    setErrorMessage(null);

    const filesToRetry = failedUploads.map((item) => item.file);
    const remainingFailed = await uploadEvidenceFiles(createdReport.id, filesToRetry);

    if (remainingFailed.length === 0) {
      setFailedUploads([]);
      setIsComplete(true);
    } else {
      setFailedUploads(remainingFailed);
      setErrorMessage(`${remainingFailed.length} photo(s) still failed to upload.`);
    }

    setIsSubmitting(false);
    setUploadProgress(null);
  };

  if (!isOpen) return null;

  return (
    <div className="nc-modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget && !isSubmitting && !isWatermarking) onClose(); }}>
      <div
        className="nc-modal-container"
        role="dialog"
        aria-modal="true"
        aria-labelledby="report-modal-title"
        ref={dialogRef}
      >
        <div className="nc-modal-header">
          <div className="nc-modal-header-copy">
            <span className="nc-modal-eyebrow">Civic Action</span>
            <h2 id="report-modal-title">Report Illegal Dumping</h2>
            <p>Submit location and geo-tagged photo evidence to BBMP control room for inspection and clearance.</p>
          </div>
          <button
            type="button"
            className="nc-modal-close"
            onClick={onClose}
            disabled={isSubmitting || isWatermarking}
            aria-label="Close report dialog"
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        {/* Unauthenticated / Non-Citizen View */}
        {!isCitizen ? (
          <div className="nc-modal-auth-gate">
            <Alert type="warning" title="Citizen Account Required">
              Illegal dumping and blackspot incident reports require verified citizen submission for accountability and audit tracking.
            </Alert>
            <p className="nc-modal-auth-copy">
              Please sign in with your citizen account or register to submit verified reports.
            </p>
            <div className="nc-modal-actions" style={{ marginTop: '1.25rem' }}>
              <Button
                variant="secondary"
                onClick={onClose}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => navigate('/login', { state: { loginNotice: 'Please sign in to submit a civic dumping report.' } })}
              >
                Sign In to Report
              </Button>
            </div>
          </div>
        ) : isComplete && createdReport ? (
          /* Success Screen */
          <div className="nc-modal-success-card">
            <div className="nc-modal-success-icon">
              <CheckCircle2 size={48} color="#15803D" aria-hidden="true" />
            </div>
            <h3>Incident Report Logged</h3>
            <p className="nc-modal-success-subtitle">
              Your report has been received and registered with BBMP municipal control.
            </p>

            <div className="nc-modal-summary-box">
              <div className="nc-summary-row">
                <span>Reference ID:</span>
                <strong>{createdReport.id}</strong>
              </div>
              <div className="nc-summary-row">
                <span>Status:</span>
                <span className="nc-status-chip">{createdReport.status}</span>
              </div>
              <div className="nc-summary-row">
                <span>Location:</span>
                <span>{createdReport.latitude.toFixed(5)}, {createdReport.longitude.toFixed(5)}</span>
              </div>
              <div className="nc-summary-row">
                <span>Evidence Attached:</span>
                <span>{evidenceItems.length - failedUploads.length} photo(s)</span>
              </div>
            </div>

            <div className="nc-modal-actions" style={{ marginTop: '1.5rem' }}>
              <Button
                variant="primary"
                onClick={onClose}
                style={{ width: '100%' }}
              >
                Return to Dashboard
              </Button>
            </div>
          </div>
        ) : (
          /* Report Submission Form */
          <form onSubmit={handleSubmit} className="nc-modal-form">
            {errorMessage && (
              <Alert type="danger" title="Submission Alert">
                {errorMessage}
              </Alert>
            )}

            {failedUploads.length > 0 && createdReport && (
              <div className="nc-failed-uploads-box">
                <p><strong>Incident #{createdReport.id.slice(0, 8)} is registered.</strong> Retry failed photos below:</p>
                <ul>
                  {failedUploads.map(({ file, reason }, idx) => (
                    <li key={idx}>
                      <code>{file.name}</code>: {reason}
                    </li>
                  ))}
                </ul>
                <Button
                  type="button"
                  variant="primary"
                  onClick={handleRetryFailedEvidence}
                  isLoading={isSubmitting}
                  style={{ marginTop: '0.5rem' }}
                >
                  <RefreshCw size={16} aria-hidden="true" />
                  <span>Retry Uploading Photos</span>
                </Button>
              </div>
            )}

            {/* Incident Description */}
            <div className="nc-form-group">
              <div className="nc-form-label-row">
                <label htmlFor="report-description">Incident Description <span className="nc-required">*</span></label>
                <span className={`nc-char-count ${description.length < 10 || description.length > 1000 ? 'nc-char-invalid' : ''}`}>
                  {description.length} / 1000
                </span>
              </div>
              <textarea
                id="report-description"
                rows={3}
                required
                minLength={10}
                maxLength={1000}
                disabled={isSubmitting}
                placeholder="Describe the waste dumping incident, volume, overflowing bins, or nearby landmarks (min 10 characters)..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="nc-textarea"
              />
            </div>

            {/* Incident Location Selection & Interactive Map */}
            <div className="nc-form-group">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.45rem' }}>
                <label style={{ margin: 0, fontWeight: 700, fontSize: '0.88rem', color: '#183B2A' }}>
                  Incident Location <span className="nc-required">*</span>
                </label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <button
                    type="button"
                    onClick={() => handleToggleMapLayer('standard')}
                    style={{
                      padding: '3px 8px',
                      borderRadius: '5px',
                      fontSize: '0.72rem',
                      fontWeight: 650,
                      border: '1px solid #CBD5E1',
                      backgroundColor: mapLayer === 'standard' ? '#183B2A' : '#FFFFFF',
                      color: mapLayer === 'standard' ? '#FFFFFF' : '#475569',
                      cursor: 'pointer',
                    }}
                  >
                    Standard Map
                  </button>
                  <button
                    type="button"
                    onClick={() => handleToggleMapLayer('satellite')}
                    style={{
                      padding: '3px 8px',
                      borderRadius: '5px',
                      fontSize: '0.72rem',
                      fontWeight: 650,
                      border: '1px solid #CBD5E1',
                      backgroundColor: mapLayer === 'satellite' ? '#183B2A' : '#FFFFFF',
                      color: mapLayer === 'satellite' ? '#FFFFFF' : '#475569',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.25rem',
                    }}
                  >
                    <Layers size={11} />
                    <span>Satellite View</span>
                  </button>
                </div>
              </div>

              {/* Location Controls: Search a Place & Detect GPS */}
              <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.65rem' }}>
                <div style={{ position: 'relative', flex: 1 }}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      backgroundColor: '#FFFFFF',
                      border: '1px solid #CBD5E1',
                      borderRadius: '7px',
                      padding: '0 8px',
                    }}
                  >
                    <Search size={15} color="#64748B" />
                    <input
                      type="text"
                      placeholder="Search a place in Bengaluru (e.g. Yelahanka, Hebbal, Jakkur)..."
                      value={searchQuery}
                      onChange={(e) => handleSearchChange(e.target.value)}
                      onFocus={() => { if (searchResults.length > 0) setShowSuggestions(true); }}
                      style={{
                        border: 'none',
                        outline: 'none',
                        padding: '7px 8px',
                        fontSize: '0.82rem',
                        width: '100%',
                      }}
                    />
                    {isSearching && <Spinner size="sm" />}
                  </div>

                  {/* Search Suggestions Dropdown */}
                  {showSuggestions && searchResults.length > 0 && (
                    <div
                      style={{
                        position: 'absolute',
                        top: '105%',
                        left: 0,
                        right: 0,
                        backgroundColor: '#FFFFFF',
                        border: '1px solid #CBD5E1',
                        borderRadius: '8px',
                        boxShadow: '0 10px 25px rgba(0,0,0,0.15)',
                        zIndex: 1000,
                        maxHeight: '190px',
                        overflowY: 'auto',
                      }}
                    >
                      {searchResults.map((item) => (
                        <div
                          key={item.place_id}
                          onClick={() => handleSelectPlace(item)}
                          style={{
                            padding: '8px 12px',
                            borderBottom: '1px solid #F1F5F9',
                            fontSize: '0.82rem',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F8FAFC')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                        >
                          <div>
                            <div style={{ fontWeight: 650, color: '#1E293B' }}>{item.locality || item.display_name.split(',')[0]}</div>
                            <div style={{ fontSize: '0.72rem', color: '#64748B' }}>{item.display_name}</div>
                          </div>
                          {item.zone && (
                            <span style={{ fontSize: '0.68rem', backgroundColor: '#E2E8F0', padding: '2px 6px', borderRadius: '4px', color: '#334155' }}>
                              {item.zone}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <button
                  type="button"
                  onClick={handleDetectLocation}
                  disabled={isSubmitting || isLocating}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.35rem',
                    backgroundColor: '#F0FDF4',
                    border: '1px solid #86EFAC',
                    color: '#166534',
                    padding: '0 12px',
                    borderRadius: '7px',
                    fontSize: '0.8rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {isLocating ? <Spinner size="sm" /> : <Crosshair size={15} color="#16A34A" />}
                  <span>{isLocating ? 'Acquiring...' : 'Detect My Location'}</span>
                </button>
              </div>

              {locationNotice && (
                <div style={{ marginBottom: '0.65rem' }}>
                  <Alert type={locationNotice.type}>
                    {locationNotice.message}
                  </Alert>
                </div>
              )}

              {/* Interactive Mini-Map with Draggable Pin */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.3rem' }}>
                  <span style={{ fontSize: '0.76rem', fontWeight: 600, color: '#183B2A' }}>
                    Incident Location Map Pin
                  </span>
                  <span style={{ fontSize: '0.72rem', color: '#5A7565' }}>
                    📍 Click map or drag red pin to set dumping spot
                  </span>
                </div>
                <div
                  ref={miniMapContainerRef}
                  style={{
                    height: '190px',
                    width: '100%',
                    borderRadius: '10px',
                    border: '1px solid #D5E3D7',
                    overflow: 'hidden',
                    position: 'relative',
                  }}
                />
              </div>

              {/* Readable Location Details Card */}
              <div
                style={{
                  marginTop: '0.65rem',
                  backgroundColor: '#F8FAFC',
                  border: '1px solid #E2E8F0',
                  borderRadius: '8px',
                  padding: '0.75rem 0.9rem',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                  <div style={{ fontSize: '0.84rem', fontWeight: 700, color: '#1E293B' }}>
                    📍 {readablePlace || 'Selected Location near Bengaluru'}
                  </div>
                  <span
                    style={{
                      fontSize: '0.7rem',
                      fontWeight: 700,
                      padding: '2px 7px',
                      borderRadius: '999px',
                      backgroundColor: selectionMethod === 'gps' ? '#DCFCE7' : selectionMethod === 'search' ? '#E0F2FE' : '#FEF3C7',
                      color: selectionMethod === 'gps' ? '#15803D' : selectionMethod === 'search' ? '#0369A1' : '#92400E',
                      border: '1px solid rgba(0,0,0,0.05)',
                    }}
                  >
                    {selectionMethod === 'gps' ? '🎯 GPS Detected' : selectionMethod === 'search' ? '🔍 Search Result' : '📍 Manually Selected'}
                  </span>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginTop: '6px' }}>
                  <div>
                    <span style={{ fontSize: '0.7rem', color: '#64748B', display: 'block' }}>Latitude</span>
                    <input
                      type="number"
                      step="any"
                      min="-90"
                      max="90"
                      required
                      value={latitude}
                      onChange={(e) => setLatitude(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '4px 7px',
                        borderRadius: '5px',
                        border: '1px solid #CBD5E1',
                        fontSize: '0.78rem',
                        boxSizing: 'border-box',
                        backgroundColor: '#FFFFFF',
                      }}
                    />
                  </div>
                  <div>
                    <span style={{ fontSize: '0.7rem', color: '#64748B', display: 'block' }}>Longitude</span>
                    <input
                      type="number"
                      step="any"
                      min="-180"
                      max="180"
                      required
                      value={longitude}
                      onChange={(e) => setLongitude(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '4px 7px',
                        borderRadius: '5px',
                        border: '1px solid #CBD5E1',
                        fontSize: '0.78rem',
                        boxSizing: 'border-box',
                        backgroundColor: '#FFFFFF',
                      }}
                    />
                  </div>
                </div>

                <div style={{ marginTop: '6px', fontSize: '0.72rem', color: '#64748B' }}>
                  🏛️ Municipal Ward: Automatically resolved from coordinates upon submission.
                </div>
              </div>
            </div>

            {/* Evidence Attachments with Direct Camera Capture and Canvas Watermarking */}
            <div className="nc-form-group">
              <div className="nc-form-label-row">
                <label>Photo Evidence with Embedded Geo-Watermark (Optional, max 5)</label>
                <span className="nc-file-count">{evidenceItems.length} of {MAX_EVIDENCE_FILES} attached</span>
              </div>
              <p className="nc-field-hint">
                Accepted: JPEG, PNG, WebP (max 5 MB). Photos are automatically stamped with GPS coordinates, accuracy, and timestamp.
              </p>

              {/* Hidden file inputs for direct camera and standard file picker */}
              <input
                ref={cameraInputRef}
                type="file"
                accept="image/*"
                capture="environment"
                disabled={isSubmitting || isWatermarking}
                onChange={(e) => {
                  const selected = Array.from(e.target.files || []);
                  if (selected.length > 0) processAndWatermarkFiles(selected);
                  if (cameraInputRef.current) cameraInputRef.current.value = '';
                }}
                id="report-camera-input"
                className="nc-visually-hidden"
              />

              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                disabled={isSubmitting || isWatermarking}
                onChange={(e) => {
                  const selected = Array.from(e.target.files || []);
                  if (selected.length > 0) processAndWatermarkFiles(selected);
                  if (fileInputRef.current) fileInputRef.current.value = '';
                }}
                id="report-photo-input"
                className="nc-visually-hidden"
              />

              {evidenceItems.length < MAX_EVIDENCE_FILES && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginTop: '0.4rem' }}>
                  <button
                    type="button"
                    onClick={() => cameraInputRef.current?.click()}
                    disabled={isSubmitting || isWatermarking}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '0.5rem',
                      padding: '0.65rem 1rem',
                      borderRadius: '8px',
                      border: '1px solid #C8E6C9',
                      backgroundColor: '#E8F5E9',
                      color: '#2E7D32',
                      fontWeight: 700,
                      fontSize: '0.84rem',
                      cursor: 'pointer',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                    }}
                  >
                    <Camera size={18} />
                    <span>📸 Take Live Photo</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isSubmitting || isWatermarking}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '0.5rem',
                      padding: '0.65rem 1rem',
                      borderRadius: '8px',
                      border: '1px solid #D5E3D7',
                      backgroundColor: '#FFFFFF',
                      color: '#183B2A',
                      fontWeight: 600,
                      fontSize: '0.84rem',
                      cursor: 'pointer',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                    }}
                  >
                    <Upload size={17} />
                    <span>📁 Upload from Device</span>
                  </button>
                </div>
              )}

              {isWatermarking && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#2E7D32', fontSize: '0.82rem', padding: '0.5rem 0' }}>
                  <Spinner size="sm" />
                  <span>Stamping photo with GPS coordinates &amp; civic audit watermark...</span>
                </div>
              )}

              {/* Watermarked photo evidence preview cards */}
              {evidenceItems.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '0.75rem', marginTop: '0.75rem' }}>
                  {evidenceItems.map((item, idx) => (
                    <div
                      key={idx}
                      style={{
                        position: 'relative',
                        borderRadius: '8px',
                        overflow: 'hidden',
                        border: '1px solid #D5E3D7',
                        backgroundColor: '#FFFFFF',
                        boxShadow: '0 2px 5px rgba(0,0,0,0.04)',
                      }}
                    >
                      <img
                        src={item.previewUrl}
                        alt={`Evidence ${idx + 1}`}
                        style={{ width: '100%', height: '85px', objectFit: 'cover', display: 'block' }}
                      />
                      <div style={{ padding: '0.4rem 0.5rem', fontSize: '0.7rem', color: '#183B2A' }}>
                        <div style={{ fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {item.originalFile.name}
                        </div>
                        <div style={{ color: '#15803D', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '3px', marginTop: '2px' }}>
                          <span>✓ Geo-watermarked</span>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRemoveEvidence(idx)}
                        disabled={isSubmitting}
                        style={{
                          position: 'absolute',
                          top: '4px',
                          right: '4px',
                          width: '22px',
                          height: '22px',
                          borderRadius: '50%',
                          backgroundColor: 'rgba(0,0,0,0.65)',
                          color: '#FFFFFF',
                          border: 'none',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          cursor: 'pointer',
                        }}
                        aria-label="Remove photo"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Progress indicator */}
            {uploadProgress && (
              <div className="nc-upload-progress-box" aria-live="polite">
                <Spinner size="sm" />
                <span>{uploadProgress}</span>
              </div>
            )}

            {/* Modal Actions */}
            <div className="nc-modal-actions">
              <Button
                type="button"
                variant="secondary"
                onClick={onClose}
                disabled={isSubmitting || isWatermarking}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                isLoading={isSubmitting}
                disabled={isSubmitting || isWatermarking}
              >
                <Upload size={16} aria-hidden="true" />
                <span>Submit Incident Report</span>
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
