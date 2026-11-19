import React from 'react';

interface AlertProps {
  type?: 'info' | 'success' | 'warning' | 'danger';
  title?: string;
  children: React.ReactNode;
}

export const Alert: React.FC<AlertProps> = ({
  type = 'info',
  title,
  children,
}) => {
  const typeStyles: Record<string, { bg: string; border: string; text: string }> = {
    info: {
      bg: 'var(--color-info-bg)',
      border: 'var(--color-info)',
      text: 'var(--color-info)',
    },
    success: {
      bg: 'var(--color-success-bg)',
      border: 'var(--color-success)',
      text: 'var(--color-success)',
    },
    warning: {
      bg: 'var(--color-warning-bg)',
      border: 'var(--color-warning)',
      text: 'var(--color-warning)',
    },
    danger: {
      bg: 'var(--color-danger-bg)',
      border: 'var(--color-danger)',
      text: 'var(--color-danger)',
    },
  };

  const current = typeStyles[type];

  return (
    <div
      style={{
        backgroundColor: current.bg,
        borderLeft: `4px solid ${current.border}`,
        borderRadius: 'var(--radius-sm)',
        padding: '0.875rem 1rem',
        marginBottom: '1rem',
      }}
      role="alert"
    >
      {title && (
        <strong
          style={{
            display: 'block',
            fontWeight: 600,
            color: current.text,
            marginBottom: '0.25rem',
          }}
        >
          {title}
        </strong>
      )}
      <div style={{ color: 'var(--color-text-main)', fontSize: '0.9rem' }}>
        {children}
      </div>
    </div>
  );
};
