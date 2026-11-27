import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Bell,
  Check,
  CheckCheck,
  AlertTriangle,
  Truck,
  CalendarCheck,
  ShieldAlert,
  Info,
  X,
  RefreshCw,
} from 'lucide-react';
import {
  fetchNotifications,
  fetchUnreadCount,
  markNotificationAsRead,
  markAllNotificationsAsRead,
  NotificationItem,
} from '../../api/notifications';

interface NotificationPanelProps {
  onNotificationClick?: (item: NotificationItem) => void;
}

const formatRelativeTime = (dateStr: string) => {
  try {
    const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  } catch {
    return 'Recent';
  }
};

const getNotificationIcon = (type: string) => {
  switch (type) {
    case 'COMPLAINT_UPDATE':
      return <AlertTriangle size={15} color="#D97706" />;
    case 'VEHICLE_ARRIVAL':
      return <Truck size={15} color="#16A34A" />;
    case 'ATTENDANCE_EXCEPTION':
      return <CalendarCheck size={15} color="#DC2626" />;
    case 'WORKFORCE_EVENT':
      return <ShieldAlert size={15} color="#2563EB" />;
    default:
      return <Info size={15} color="#0D9488" />;
  }
};

export const NotificationPanel: React.FC<NotificationPanelProps> = ({ onNotificationClick }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [activeFilter, setActiveFilter] = useState<'ALL' | 'UNREAD' | 'READ'>('ALL');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);

  const loadUnreadCount = useCallback(async () => {
    try {
      const count = await fetchUnreadCount();
      setUnreadCount(count);
    } catch {
      // Ignored if unauthenticated
    }
  }, []);

  const loadNotifications = useCallback(async (filter: 'ALL' | 'UNREAD' | 'READ') => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const res = await fetchNotifications(filter, 30, 0);
      setNotifications(res.items);
      setUnreadCount(res.unread_count);
    } catch (err: any) {
      setErrorMessage('Could not load notifications.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Poll unread count every 30 seconds
  useEffect(() => {
    loadUnreadCount();
    const interval = setInterval(loadUnreadCount, 30000);
    return () => clearInterval(interval);
  }, [loadUnreadCount]);

  // Load list when panel opens or filter changes
  useEffect(() => {
    if (isOpen) {
      loadNotifications(activeFilter);
    }
  }, [isOpen, activeFilter, loadNotifications]);

  // Handle click outside to close
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  const handleMarkAsRead = async (item: NotificationItem, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const updated = await markNotificationAsRead(item.id);
      setNotifications((prev) =>
        prev.map((n) => (n.id === updated.id ? { ...n, is_read: true } : n))
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch {
      // Ignore
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsAsRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnreadCount(0);
    } catch {
      // Ignore
    }
  };

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      {/* Notification Bell Button */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-label="Notifications"
        title="Notifications"
        style={{
          position: 'relative',
          width: '36px',
          height: '36px',
          borderRadius: '50%',
          border: '1px solid #D5E3D7',
          backgroundColor: '#FFFFFF',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#183B2A',
          cursor: 'pointer',
          boxShadow: '0 2px 6px rgba(0, 0, 0, 0.04)',
        }}
      >
        <Bell size={17} strokeWidth={2} />
        {unreadCount > 0 && (
          <span
            style={{
              position: 'absolute',
              top: '-3px',
              right: '-3px',
              backgroundColor: '#DC2626',
              color: '#FFFFFF',
              fontSize: '0.65rem',
              fontWeight: 800,
              minWidth: '18px',
              height: '18px',
              borderRadius: '999px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 4px',
              boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
            }}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Notification Dropdown Panel */}
      {isOpen && (
        <div
          style={{
            position: 'absolute',
            top: '120%',
            right: 0,
            width: '360px',
            maxWidth: '90vw',
            backgroundColor: '#FFFFFF',
            borderRadius: '12px',
            border: '1px solid #CBD5E1',
            boxShadow: '0 12px 30px rgba(0, 0, 0, 0.15)',
            zIndex: 1000,
            overflow: 'hidden',
          }}
        >
          {/* Header */}
          <div
            style={{
              padding: '0.85rem 1rem',
              borderBottom: '1px solid #F1F5F9',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              backgroundColor: '#FAFCFA',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ fontSize: '0.92rem', fontWeight: 750, color: '#183B2A' }}>Notifications</span>
              {unreadCount > 0 && (
                <span
                  style={{
                    backgroundColor: '#FEE2E2',
                    color: '#991B1B',
                    fontSize: '0.7rem',
                    fontWeight: 700,
                    padding: '1px 6px',
                    borderRadius: '999px',
                  }}
                >
                  {unreadCount} unread
                </span>
              )}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              {unreadCount > 0 && (
                <button
                  type="button"
                  onClick={handleMarkAllRead}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.25rem',
                    border: 'none',
                    background: 'none',
                    color: '#2E7D32',
                    fontSize: '0.75rem',
                    fontWeight: 650,
                    cursor: 'pointer',
                    padding: '3px 6px',
                  }}
                  title="Mark all as read"
                >
                  <CheckCheck size={14} />
                  <span>Mark All Read</span>
                </button>
              )}
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                style={{ border: 'none', background: 'none', color: '#94A3B8', cursor: 'pointer', padding: '2px' }}
              >
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Filter Tabs */}
          <div
            style={{
              display: 'flex',
              borderBottom: '1px solid #F1F5F9',
              backgroundColor: '#FFFFFF',
              padding: '0 0.5rem',
            }}
          >
            {(['ALL', 'UNREAD', 'READ'] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveFilter(tab)}
                style={{
                  flex: 1,
                  padding: '7px 0',
                  border: 'none',
                  borderBottom: activeFilter === tab ? '2px solid #2E7D32' : '2px solid transparent',
                  backgroundColor: 'transparent',
                  color: activeFilter === tab ? '#183B2A' : '#64748B',
                  fontWeight: activeFilter === tab ? 750 : 600,
                  fontSize: '0.78rem',
                  cursor: 'pointer',
                }}
              >
                {tab === 'ALL' ? 'All' : tab === 'UNREAD' ? 'Unread' : 'Read'}
              </button>
            ))}
          </div>

          {/* Notification List Body */}
          <div style={{ maxHeight: '340px', overflowY: 'auto' }}>
            {isLoading ? (
              <div style={{ padding: '2rem', textAlign: 'center', color: '#64748B', fontSize: '0.85rem' }}>
                <RefreshCw size={18} className="nc-refreshing" style={{ margin: '0 auto 6px auto', display: 'block' }} />
                <span>Loading notifications...</span>
              </div>
            ) : errorMessage ? (
              <div style={{ padding: '1.5rem', textAlign: 'center', color: '#DC2626', fontSize: '0.82rem' }}>
                {errorMessage}
              </div>
            ) : notifications.length === 0 ? (
              <div style={{ padding: '2.5rem 1rem', textAlign: 'center', color: '#94A3B8' }}>
                <Bell size={24} style={{ margin: '0 auto 8px auto', display: 'block', opacity: 0.5 }} />
                <div style={{ fontSize: '0.85rem', fontWeight: 600 }}>No notifications</div>
                <div style={{ fontSize: '0.75rem', marginTop: '2px' }}>
                  {activeFilter === 'UNREAD' ? 'You have read all your alerts!' : 'Civic and fleet alerts will appear here.'}
                </div>
              </div>
            ) : (
              notifications.map((item) => (
                <div
                  key={item.id}
                  onClick={() => onNotificationClick?.(item)}
                  style={{
                    padding: '0.85rem 1rem',
                    borderBottom: '1px solid #F8FAFC',
                    backgroundColor: item.is_read ? '#FFFFFF' : '#F0FDF4',
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '0.75rem',
                    cursor: onNotificationClick ? 'pointer' : 'default',
                    transition: 'background 0.15s ease',
                  }}
                  onMouseEnter={(e) => {
                    if (item.is_read) e.currentTarget.style.backgroundColor = '#F8FAFC';
                  }}
                  onMouseLeave={(e) => {
                    if (item.is_read) e.currentTarget.style.backgroundColor = '#FFFFFF';
                  }}
                >
                  <div style={{ marginTop: '2px' }}>{getNotificationIcon(item.notification_type)}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
                      <span style={{ fontSize: '0.82rem', fontWeight: item.is_read ? 650 : 750, color: '#1E293B', lineHeight: 1.2 }}>
                        {item.title}
                      </span>
                      <span style={{ fontSize: '0.68rem', color: '#94A3B8', whiteSpace: 'nowrap' }}>
                        {formatRelativeTime(item.created_at)}
                      </span>
                    </div>
                    <p style={{ margin: '3px 0 0 0', fontSize: '0.76rem', color: '#475569', lineHeight: 1.4 }}>
                      {item.message}
                    </p>
                  </div>
                  {!item.is_read && (
                    <button
                      type="button"
                      onClick={(e) => handleMarkAsRead(item, e)}
                      title="Mark as read"
                      style={{
                        background: 'none',
                        border: 'none',
                        color: '#16A34A',
                        cursor: 'pointer',
                        padding: '2px',
                        display: 'flex',
                        alignItems: 'center',
                      }}
                    >
                      <Check size={14} />
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};
