import React from 'react';
import { Leaf, Recycle, Route, Truck } from 'lucide-react';
import { PublicMapSummary } from '../../types';

interface SummaryCardsProps {
  summary: PublicMapSummary | null;
}

export const SummaryCards: React.FC<SummaryCardsProps> = ({ summary }) => {
  const summaryTimestamp = summary ? Date.parse(summary.generated_at) : Number.NaN;
  const summaryAgeMinutes = Number.isFinite(summaryTimestamp)
    ? Math.max(0, Math.floor((Date.now() - summaryTimestamp) / 60_000))
    : null;
  const summaryAge =
    summaryAgeMinutes === null
      ? 'Awaiting public data'
      : summaryAgeMinutes < 1
        ? 'Updated just now'
        : `Updated ${summaryAgeMinutes} min ago`;
  const cards = [
    {
      id: 'vehicles',
      icon: Truck,
      value: summary ? String(summary.active_live_vehicles) : '—',
      label: 'Fresh vehicle signals',
      note: summary ? 'Municipal + demo' : 'Awaiting public data',
    },
    {
      id: 'points',
      icon: Recycle,
      value: summary ? String(summary.published_collection_points) : '—',
      label: 'Collection points',
      note: summary ? 'Published locations' : 'Awaiting public data',
    },
    {
      id: 'routes',
      icon: Route,
      value: summary ? String(summary.published_routes) : '—',
      label: 'Published routes',
      note: summary ? 'Available on the map' : 'Awaiting public data',
    },
    {
      id: 'freshness',
      icon: Leaf,
      value: summary ? `${summary.freshness_threshold_minutes} min` : '—',
      label: 'Freshness window',
      note: summary ? 'Server threshold' : 'Awaiting public data',
    },
  ];

  return (
    <div className="nc-summary-overview" aria-label="Published collection summary">
      <div className="nc-summary-overview-head">
        <span>PUBLIC MAP SNAPSHOT</span>
        <span>{summary ? summaryAge : 'Public data currently unavailable'}</span>
      </div>
      <div className="nc-summary-grid">
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <article className="nc-summary-card" key={card.id}>
              <span className="nc-summary-icon">
                <Icon size={19} strokeWidth={2} aria-hidden="true" />
              </span>
              <span className="nc-summary-copy">
                <strong>{card.value}</strong>
                <span className="nc-summary-label">{card.label}</span>
                <span className="nc-summary-note">{card.note}</span>
              </span>
            </article>
          );
        })}
      </div>
    </div>
  );
};
