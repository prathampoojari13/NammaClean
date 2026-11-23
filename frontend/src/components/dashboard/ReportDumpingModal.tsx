import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Camera,
  CheckCircle2,
  FileImage,
  MapPin,
  RefreshCw,
  Upload,
  X,
} from 'lucide-react';
import { Button } from '../ui/Button';
import { Alert } from '../ui/Alert';
import { Spinner } from '../ui/Spinner';
import {
  createDumpingReport,
  uploadReportEvidence,
  fetchWardsForSelection,
  WardSummary,
} from '../../api/reports';
import { DumpingReport } from '../../types';

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

  // Form states
  const [description, setDescription] = useState('');
  const [latitude, setLatitude] = useState(defaultCoordinates ? String(defaultCoordinates.latitude) : '');
  const [longitude, setLongitude] = useState(defaultCoordinates ? String(defaultCoordinates.longitude) : '');
  const [selectedWardId, setSelectedWardId] = useState<string>('');
  const [files, setFiles] = useState<File[]>([]);
  const [wards, setWards] = useState<WardSummary[]>([]);

  // Processing & progress states
  const [isLocating, setIsLocating] = useState(false);
  const [locationNotice, setLocationNotice] = useState<{ type: 'info' | 'danger'; message: string } | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
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

  // Load wards for optional selection
  useEffect(() => {
    let active = true;
    fetchWardsForSelection()
      .then((data) => {
        if (active && Array.isArray(data)) {
          setWards(data);
        }
      })
      .catch(() => {
        // Optional wards fetch failed non-fatally
      });
    return () => {
      active = false;
    };
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
      if (e.key === 'Escape' && !isSubmitting) {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, isSubmitting, onClose]);

  if (!isOpen) return null;

  // Browser Geolocation Detection
  const handleDetectLocation = () => {
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
        setLatitude(position.coords.latitude.toFixed(6));
        setLongitude(position.coords.longitude.toFixed(6));
        setLocationNotice({
          type: 'info',
          message: `Location captured: accuracy within ±${Math.round(position.coords.accuracy)}m.`,
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
  };

  // File selection & validation
  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files || []);
    if (!selected.length) return;

    const newFiles: File[] = [];
    const errors: string[] = [];

    for (const file of selected) {
      if (!ALLOWED_MIME_TYPES.includes(file.type)) {
        errors.push(`"${file.name}": Unsupported format. Allowed formats: JPEG, PNG, WebP.`);
        continue;
      }
      if (file.size > MAX_FILE_SIZE_BYTES) {
        errors.push(`"${file.name}": File size exceeds 5MB limit (${(file.size / (1024 * 1024)).toFixed(1)}MB).`);
        continue;
      }
      newFiles.push(file);
    }

    if (files.length + newFiles.length > MAX_EVIDENCE_FILES) {
      errors.push(`You can attach a maximum of ${MAX_EVIDENCE_FILES} photos per report.`);
    }

    if (errors.length > 0) {
      setErrorMessage(errors.join(' '));
    } else {
      setErrorMessage(null);
    }

    const combined = [...files, ...newFiles].slice(0, MAX_EVIDENCE_FILES);
    setFiles(combined);

    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleRemoveFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
    setErrorMessage(null);
  };

  // Sequential Evidence Upload Worker
  const uploadEvidenceFiles = async (reportId: string, filesToUpload: File[]) => {
    const failed: { file: File; reason: string }[] = [];

    for (let i = 0; i < filesToUpload.length; i++) {
      const file = filesToUpload[i];
      setUploadProgress(`Uploading evidence photo ${i + 1} of ${filesToUpload.length}: ${file.name}...`);

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

    // Client-side validation
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
        ward_id: selectedWardId || null,
      });

      setCreatedReport(report);
      onReportCreated?.(report);

      // Step 2: Upload attached evidence photos sequentially
      if (files.length > 0) {
        const failed = await uploadEvidenceFiles(report.id, files);
        if (failed.length > 0) {
          setFailedUploads(failed);
          setErrorMessage(`Report #${report.id.slice(0, 8)} was registered, but ${failed.length} of ${files.length} photos failed to attach.`);
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

  // Retry Failed Evidence Uploads (Reuses existing report ID without recreating report)
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

  return (
    <div className="nc-modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget && !isSubmitting) onClose(); }}>
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
            <p>Submit location and evidence to BBMP control room for inspection and clearance.</p>
          </div>
          <button
            type="button"
            className="nc-modal-close"
            onClick={onClose}
            disabled={isSubmitting}
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
                <span>{files.length - failedUploads.length} photo(s)</span>
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
                rows={4}
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

            {/* Incident Location Coordinates */}
            <div className="nc-form-group">
              <div className="nc-form-label-row">
                <label>Incident Coordinates (WGS 84) <span className="nc-required">*</span></label>
                <button
                  type="button"
                  className="nc-detect-location-btn"
                  onClick={handleDetectLocation}
                  disabled={isSubmitting || isLocating}
                >
                  {isLocating ? <Spinner size="sm" /> : <MapPin size={15} aria-hidden="true" />}
                  <span>{isLocating ? 'Detecting...' : 'Detect GPS Location'}</span>
                </button>
              </div>

              {locationNotice && (
                <Alert type={locationNotice.type}>
                  {locationNotice.message}
                </Alert>
              )}

              <div className="nc-coordinate-grid">
                <div>
                  <label htmlFor="report-latitude" className="nc-sub-label">Latitude (-90 to +90)</label>
                  <input
                    id="report-latitude"
                    type="number"
                    step="any"
                    min="-90"
                    max="90"
                    required
                    disabled={isSubmitting}
                    placeholder="e.g. 12.9716"
                    value={latitude}
                    onChange={(e) => setLatitude(e.target.value)}
                    className="nc-input"
                  />
                </div>
                <div>
                  <label htmlFor="report-longitude" className="nc-sub-label">Longitude (-180 to +180)</label>
                  <input
                    id="report-longitude"
                    type="number"
                    step="any"
                    min="-180"
                    max="180"
                    required
                    disabled={isSubmitting}
                    placeholder="e.g. 77.5946"
                    value={longitude}
                    onChange={(e) => setLongitude(e.target.value)}
                    className="nc-input"
                  />
                </div>
              </div>
            </div>

            {/* Optional Ward Selection */}
            <div className="nc-form-group">
              <label htmlFor="report-ward">Municipal Ward (Optional)</label>
              <select
                id="report-ward"
                value={selectedWardId}
                onChange={(e) => setSelectedWardId(e.target.value)}
                disabled={isSubmitting}
                className="nc-select"
              >
                <option value="">Auto-resolve from coordinates (Optional)</option>
                {wards.map((w) => (
                  <option key={w.id} value={w.id}>
                    Ward {w.ward_number} — {w.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Evidence Attachments */}
            <div className="nc-form-group">
              <div className="nc-form-label-row">
                <label>Photo Evidence (Optional, max 5)</label>
                <span className="nc-file-count">{files.length} of {MAX_EVIDENCE_FILES} attached</span>
              </div>
              <p className="nc-field-hint">
                Accepted: JPEG, PNG, WebP (max 5 MB per photo).
              </p>

              {files.length < MAX_EVIDENCE_FILES && (
                <div className="nc-file-dropzone">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    multiple
                    disabled={isSubmitting}
                    onChange={handleFileSelect}
                    id="report-photo-input"
                    className="nc-visually-hidden"
                  />
                  <label htmlFor="report-photo-input" className="nc-file-upload-trigger">
                    <Camera size={20} aria-hidden="true" />
                    <span>Choose Photos to Attach</span>
                  </label>
                </div>
              )}

              {files.length > 0 && (
                <ul className="nc-file-list" aria-label="Attached photos">
                  {files.map((file, idx) => (
                    <li key={idx} className="nc-file-item">
                      <FileImage size={18} aria-hidden="true" />
                      <span className="nc-file-name" title={file.name}>{file.name}</span>
                      <span className="nc-file-size">({(file.size / (1024 * 1024)).toFixed(2)} MB)</span>
                      <button
                        type="button"
                        className="nc-file-remove"
                        onClick={() => handleRemoveFile(idx)}
                        disabled={isSubmitting}
                        aria-label={`Remove ${file.name}`}
                      >
                        <X size={16} aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
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
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                isLoading={isSubmitting}
                disabled={isSubmitting}
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
