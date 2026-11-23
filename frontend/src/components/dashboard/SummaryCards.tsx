import React from 'react';
import { FileText, MapPin, Route, Truck } from 'lucide-react';
import { PublicMapSummary } from '../../types';

interface SummaryCardsProps {
  summary: PublicMapSummary | null;
  myReportsCount?: number | null;
  resolvedCount?: number | null;
  onMyReportsClick?: () => void;
  onVehiclesClick?: () => void;
  onRoutesClick?: () => void;
}

export const SummaryCards: React.FC<SummaryCardsProps> = ({
  summary,
  myReportsCount = null,
  resolvedCount: _resolvedCount = null,
  onMyReportsClick,
  onVehiclesClick,
  onRoutesClick,
}) => {
  const cards = [
    {
      id: 'vehicles',
      icon: Truck,
      value: summary ? String(summary.active_live_vehicles) : '—',
      label: 'Active Vehicles',
      badge: '↑ Live',
      badgeColor: '#2E7D32',
      clickable: Boolean(onVehiclesClick),
      onClick: onVehiclesClick,
    },
    {
      id: 'collection_points',
      icon: MapPin,
      value: summary ? String(summary.published_collection_points) : '—',
      label: 'Collection Points',
      badge: 'Across Bengaluru',
      badgeColor: '#5A7565',
      clickable: false,
      onClick: undefined,
    },
    {
      id: 'routes',
      icon: Route,
      value: summary ? String(summary.published_routes) : '—',
      label: 'Published Routes',
      badge: 'View Routes →',
      badgeColor: '#2E7D32',
      clickable: Boolean(onRoutesClick),
      onClick: onRoutesClick,
    },
    {
      id: 'reports',
      icon: FileText,
      value: myReportsCount !== null && myReportsCount !== undefined ? String(myReportsCount) : '—',
      label: 'Your Reports',
      badge: 'View All →',
      badgeColor: '#2E7D32',
      clickable: Boolean(onMyReportsClick),
      onClick: onMyReportsClick,
    },
  ];

  return (
    <div className="nc-summary-overview" aria-label="Published collection summary">
      <div className="nc-summary-grid">
        {cards.map((card) => {
          const Icon = card.icon;
          const isClickable = Boolean(card.clickable && card.onClick);
          return (
            <article
              className={`nc-summary-card ${isClickable ? 'is-clickable' : ''}`}
              key={card.id}
              onClick={isClickable ? card.onClick : undefined}
              role={isClickable ? 'button' : undefined}
              tabIndex={isClickable ? 0 : undefined}
              onKeyDown={
                isClickable
                  ? (e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        card.onClick?.();
                      }
                    }
                  : undefined
              }
              title={
                card.id === 'reports'
                  ? 'Click to view your incident reports'
                  : card.id === 'vehicles' || card.id === 'routes'
                  ? 'Click to view vehicle tracking map'
                  : undefined
              }
            >
              <span className="nc-summary-icon">
                <Icon size={20} strokeWidth={2.2} aria-hidden="true" />
              </span>
              <span className="nc-summary-copy">
                <strong>{card.value}</strong>
                <span className="nc-summary-label">{card.label}</span>
                <span className="nc-summary-note" style={{ color: card.badgeColor }}>
                  {card.badge}
                </span>
              </span>
            </article>
          );
        })}
      </div>
    </div>
  );
};
