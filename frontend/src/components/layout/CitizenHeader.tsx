import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowDown, Home, LogIn } from 'lucide-react';

interface CitizenHeaderProps {
  onTrackClick: () => void;
}

export const CitizenHeader: React.FC<CitizenHeaderProps> = ({ onTrackClick }) => {
  return (
    <header className="nc-citizen-header">
      <div className="nc-header-inner">
        <Link to="/" className="nc-brand" aria-label="NammaClean home">
          <img
            className="nc-brand-mark"
            src="/assets/namma-clean-brand-mark.png"
            alt=""
            aria-hidden="true"
          />
          <span className="nc-brand-copy">
            <strong>NammaClean</strong>
            <span>Clean Bengaluru. Green Bengaluru.</span>
          </span>
        </Link>

        <nav className="nc-primary-nav" aria-label="Main navigation">
          <Link to="/" className="nc-nav-link" aria-current="page">
            <Home size={17} strokeWidth={2} aria-hidden="true" />
            <span>Home</span>
          </Link>
          <button type="button" className="nc-nav-link" onClick={onTrackClick}>
            <ArrowDown size={17} strokeWidth={2} aria-hidden="true" />
            <span>Track collection</span>
          </button>
          <Link to="/login" className="nc-nav-account">
            <LogIn size={17} strokeWidth={2} aria-hidden="true" />
            <span>Sign in</span>
          </Link>
        </nav>
      </div>
      <div className="nc-header-photo-credit">
        <a
          href="https://commons.wikimedia.org/wiki/File:Vidhana_Soudha_(Bengaluru)_-_Panoramic_view.jpg"
          target="_blank"
          rel="noreferrer"
        >
          Vidhana Soudha · iMahesh / Wikimedia Commons
        </a>
        <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noreferrer">
          CC BY-SA 4.0
        </a>
      </div>
    </header>
  );
};
