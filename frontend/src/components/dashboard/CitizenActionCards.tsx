import React from 'react';
import { AlertTriangle, ArrowRight, Truck } from 'lucide-react';

interface CitizenActionCardsProps {
  onTrackClick: () => void;
  onReportClick: () => void;
}

export const CitizenActionCards: React.FC<CitizenActionCardsProps> = ({
  onTrackClick,
  onReportClick,
}) => {
  return (
    <div className="nc-action-grid">
      <button type="button" className="nc-action-card" onClick={onTrackClick}>
        <span className="nc-action-icon">
          <Truck size={21} aria-hidden="true" />
        </span>
        <span className="nc-action-copy">
          <span className="nc-action-title">Explore collection activity</span>
          <span className="nc-action-subtitle">View published vehicles, routes and collection points</span>
        </span>
        <ArrowRight className="nc-action-arrow" size={19} aria-hidden="true" />
      </button>

      <button
        type="button"
        className="nc-action-card nc-action-card-report"
        onClick={onReportClick}
      >
        <span className="nc-action-icon nc-action-icon-report">
          <AlertTriangle size={21} aria-hidden="true" />
        </span>
        <span className="nc-action-copy">
          <span className="nc-action-title">Report Illegal Dumping</span>
          <span className="nc-action-subtitle">Upload photo evidence and location for municipal waste clearance</span>
        </span>
        <ArrowRight className="nc-action-arrow" size={19} aria-hidden="true" />
      </button>
    </div>
  );
};
