import React from 'react';

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  subtitle?: string;
  headerAction?: React.ReactNode;
}

export const Card: React.FC<CardProps> = ({
  title,
  subtitle,
  headerAction,
  children,
  style,
  ...props
}) => {
  return (
    <div
      style={{
        backgroundColor: 'var(--color-bg-surface)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-sm)',
        padding: '1.5rem',
        ...style,
      }}
      {...props}
    >
      {(title || headerAction) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            marginBottom: '1rem',
            borderBottom: subtitle ? 'none' : '1px solid var(--color-border)',
            paddingBottom: subtitle ? '0' : '0.75rem',
          }}
        >
          <div>
            {title && (
              <h3
                style={{
                  fontSize: '1.25rem',
                  fontWeight: 600,
                  color: 'var(--color-primary)',
                }}
              >
                {title}
              </h3>
            )}
            {subtitle && (
              <p
                style={{
                  fontSize: '0.875rem',
                  color: 'var(--color-text-muted)',
                  marginTop: '0.25rem',
                }}
              >
                {subtitle}
              </p>
            )}
          </div>
          {headerAction && <div>{headerAction}</div>}
        </div>
      )}
      <div>{children}</div>
    </div>
  );
};
