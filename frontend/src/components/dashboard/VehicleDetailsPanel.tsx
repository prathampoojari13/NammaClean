import React from 'react';
import { Clock, MapPin, Truck, X } from 'lucide-react';
import { PublicVehicle } from '../../types';
import { hasCurrentVehicleSignal } from '../../utils/publicMapFreshness';

interface VehicleDetailsPanelProps {
  vehicle: PublicVehicle | null;
  freshnessMinutes?: number | null;
  onClose: () => void;
  onViewHistory?: (vehicle: PublicVehicle) => void;
}

const formatLabel = (value: string) =>
  value
    .split('_')
    .map((word) => word.charAt(0) + word.slice(1).toLowerCase())
    .join(' ');

const formatLastSeen = (timestamp?: string | null) => {
  if (!timestamp) return 'Unknown';
  const lastSeen = Date.parse(timestamp);
  if (!Number.isFinite(lastSeen) || lastSeen > Date.now()) return 'Unknown';
  const diffMinutes = Math.floor((Date.now() - lastSeen) / 60000);
  if (diffMinutes === 0) return 'Just now';
  if (diffMinutes === 1) return '1 min ago';
  if (diffMinutes < 60) return `${diffMinutes} min ago`;
  const hours = Math.floor(diffMinutes / 60);
  return `${hours} hr${hours > 1 ? 's' : ''} ago`;
};

const statusColor = (status: string) => {
  switch (status) {
    case 'COLLECTING':
    case 'ON_DUTY':
      return '#16A34A';
    case 'IDLE':
    case 'MAINTENANCE':
      return '#D97706';
    default:
      return '#6B7280';
  }
};

export const VehicleDetailsPanel: React.FC<VehicleDetailsPanelProps> = ({
  vehicle,
  freshnessMinutes = null,
  onClose,
  onViewHistory,
}) => {
  if (!vehicle) return null;

  const telemetryFresh = hasCurrentVehicleSignal(vehicle, freshnessMinutes);

  const plate =
    vehicle.registration_number ||
    (vehicle.id.startsWith('KA-') ? vehicle.id : 'Published vehicle');

  const rows = [
    { label: 'Type', value: formatLabel(vehicle.vehicle_type) },
    { label: 'Status', value: telemetryFresh ? formatLabel(vehicle.status) : 'Signal stale', status: true },
    { label: 'Last Updated', value: formatLastSeen(vehicle.last_seen_at) },
  ];

  return (
    <aside
      className="nc-vehicle-details-card"
      aria-label="Selected vehicle details"
    >
      <div className="nc-vehicle-details-head">
        <div className="nc-vehicle-details-title">
          <Truck size={16} aria-hidden="true" />
          <h3>Vehicle details</h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close vehicle details"
          className="nc-vehicle-details-close"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>

      <div className="nc-vehicle-details-plate">{plate}</div>
      <div className="nc-vehicle-details-badge-wrap">
        <span className={`nc-vehicle-details-badge${vehicle.is_simulated ? ' is-demo' : ''}`}>
          {vehicle.is_simulated ? 'Demo vehicle' : 'Published municipal record'}
        </span>
      </div>

      <div className="nc-vehicle-details-rows">
        {rows.map((row) => (
          <div key={row.label} className="nc-vehicle-details-row">
            <span>{row.label}</span>
            <span className="nc-vehicle-details-value">
              {row.status && (
                <span
                  className="nc-vehicle-status-dot"
                  style={{ backgroundColor: telemetryFresh ? statusColor(vehicle.status) : '#D97706' }}
                />
              )}
              {row.value}
            </span>
          </div>
        ))}
        <div className="nc-vehicle-details-location">
          <MapPin size={14} aria-hidden="true" />
          <span>
            {telemetryFresh && vehicle.latitude != null && vehicle.longitude != null
              ? `${vehicle.latitude.toFixed(4)}, ${vehicle.longitude.toFixed(4)}`
              : 'No current signal'}
          </span>
        </div>
      </div>

      {onViewHistory && (
        <button
          type="button"
          onClick={() => onViewHistory(vehicle)}
          className="nc-vehicle-history-button"
        >
          <Clock size={15} aria-hidden="true" />
          View history
        </button>
      )}
    </aside>
  );
};
