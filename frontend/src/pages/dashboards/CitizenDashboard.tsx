import React, { useState } from 'react';
import { CitizenHeader } from '../../components/layout/CitizenHeader';
import { CitizenBanner } from '../../components/dashboard/CitizenBanner';
import { SummaryCards } from '../../components/dashboard/SummaryCards';
import { PublicVehicleMap } from '../../components/map/PublicVehicleMap';
import { VehicleDetailsPanel } from '../../components/dashboard/VehicleDetailsPanel';
import { CitizenActionCards } from '../../components/dashboard/CitizenActionCards';
import { PublicVehicle, PublicMapSummary } from '../../types';
import '../../styles/citizen-dashboard.css';

const scrollToMap = () => {
  document.getElementById('citizen-map')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
};

export const CitizenDashboard: React.FC = () => {
  const [selectedVehicle, setSelectedVehicle] = useState<PublicVehicle | null>(null);
  const [summary, setSummary] = useState<PublicMapSummary | null>(null);

  return (
    <div className="nc-citizen-dashboard">
      <section className="nc-dashboard-band" id="home">
        <CitizenHeader onTrackClick={scrollToMap} />
        <div className="nc-dashboard-band-inner">
          <CitizenBanner />
          <SummaryCards summary={summary} />
        </div>
      </section>

      <main className="nc-dashboard-main">
        <PublicVehicleMap
          selectedVehicle={selectedVehicle}
          onVehicleSelect={setSelectedVehicle}
          onSummaryLoaded={setSummary}
          details={
            selectedVehicle ? (
              <VehicleDetailsPanel
                vehicle={selectedVehicle}
                freshnessMinutes={summary?.freshness_threshold_minutes ?? null}
                onClose={() => setSelectedVehicle(null)}
              />
            ) : null
          }
        />

        <CitizenActionCards onTrackClick={scrollToMap} />
      </main>

      <footer className="nc-dashboard-footer">
        <span>Public collection information for Bengaluru</span>
      </footer>
    </div>
  );
};

export default CitizenDashboard;
