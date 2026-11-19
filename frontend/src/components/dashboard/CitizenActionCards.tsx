import React from 'react';
import { ArrowRight, Truck } from 'lucide-react';

interface CitizenActionCardsProps {
  onTrackClick: () => void;
}

export const CitizenActionCards: React.FC<CitizenActionCardsProps> = ({ onTrackClick }) => {
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
    </div>
  );
};
