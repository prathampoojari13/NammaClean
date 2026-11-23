import React from 'react';
import type { User } from '../../types';
import { resolveUserDisplayName } from '../../utils/userDisplayName';

export { resolveUserDisplayName };

interface CitizenBannerProps {
  user?: User | null;
  userName?: string | null;
  isLoading?: boolean;
  titlePrefix?: string;
  subtitle?: string;
  roleBadge?: string;
  showBirds?: boolean;
}

export const CitizenBanner: React.FC<CitizenBannerProps> = ({
  user = null,
  userName = null,
  isLoading = false,
  titlePrefix = 'Welcome Back',
  subtitle = 'Together for a cleaner and greener Bengaluru 🌱',
  roleBadge,
  showBirds = true,
}) => {
  const displayName = resolveUserDisplayName(user, userName);

  return (
    <div className="nc-welcome">
      <div className="nc-welcome-header-row">
        <div className="nc-welcome-text">
          {roleBadge && (
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                padding: '3px 10px',
                borderRadius: '999px',
                backgroundColor: '#E8F5E9',
                color: '#2E7D32',
                fontSize: '0.75rem',
                fontWeight: 700,
                letterSpacing: '0.03em',
                textTransform: 'uppercase',
                marginBottom: '0.35rem',
                border: '1px solid #C8E6C9',
              }}
            >
              {roleBadge}
            </div>
          )}
          {isLoading ? (
            <h1>{titlePrefix}!</h1>
          ) : displayName ? (
            <h1>{titlePrefix}, {displayName}!</h1>
          ) : (
            <h1>{titlePrefix}!</h1>
          )}
          <p>{subtitle}</p>
        </div>

        {/* Birds flying in nature to the right of welcome message matching user reference image */}
        {showBirds && (
          <div className="nc-flying-birds" aria-hidden="true" title="Birds soaring in nature">
            <svg
              width="210"
              height="70"
              viewBox="0 0 210 70"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className="nc-birds-svg"
            >
              <defs>
                <linearGradient id="birdGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#1B3F2B" stopOpacity="0.85" />
                  <stop offset="100%" stopColor="#28593A" stopOpacity="0.72" />
                </linearGradient>
              </defs>

              {/* Bird 1: High soaring gull (top right in reference image) */}
              <g transform="translate(160, 6) scale(0.95)">
                <path
                  d="M 0 10 C 4 7, 10 9, 17 14 C 19 13, 21 10, 23 7 C 28 1, 35 0, 40 4 C 34 3, 28 6, 22 15 C 20 18, 18 18, 15 16 C 10 13, 5 10, 0 10 Z"
                  fill="url(#birdGrad)"
                />
              </g>

              {/* Bird 2: Graceful banked gull with arched wings (center in reference image) */}
              <g transform="translate(95, 18) scale(1.05)">
                <path
                  d="M 0 8 C 4 3, 9 1, 20 10 C 31 1, 36 3, 40 8 C 35 4, 28 3, 20 13 C 12 3, 5 4, 0 8 Z"
                  fill="url(#birdGrad)"
                />
              </g>

              {/* Bird 3: Arched V gull (left in reference image) */}
              <g transform="translate(18, 26) scale(0.9)">
                <path
                  d="M 0 8 C 3 3, 7 1, 16 9 C 25 1, 29 3, 32 8 C 28 4, 23 3, 16 12 C 9 3, 4 4, 0 8 Z"
                  fill="url(#birdGrad)"
                />
              </g>

              {/* Bird 4: Outstretched gliding bird (lower right in reference image) */}
              <g transform="translate(178, 38) scale(0.72)">
                <path
                  d="M 0 9 C 5 7, 11 9, 17 13 C 19 12, 21 10, 23 8 C 28 2, 34 1, 38 5 C 33 4, 27 7, 21 15 C 19 17, 17 17, 15 15 C 10 12, 5 10, 0 9 Z"
                  fill="url(#birdGrad)"
                />
              </g>

              {/* Bird 5: Distant soaring bird (mid lower in reference image) */}
              <g transform="translate(125, 42) scale(0.55)">
                <path
                  d="M 0 8 C 4 3, 9 1, 18 10 C 27 1, 32 3, 36 8 C 31 4, 25 3, 18 13 C 11 3, 5 4, 0 8 Z"
                  fill="url(#birdGrad)"
                />
              </g>
            </svg>
          </div>
        )}
      </div>
    </div>
  );
};
