import { apiClient } from './client';

export interface NotificationItem {
  id: string;
  user_id: string;
  title: string;
  message: string;
  notification_type: string;
  is_read: boolean;
  read_at: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  created_at: string;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  total_count: number;
  unread_count: number;
}

export interface UnreadCountResponse {
  unread_count: number;
}

export async function fetchNotifications(
  status: 'ALL' | 'UNREAD' | 'READ' = 'ALL',
  limit = 30,
  offset = 0
): Promise<NotificationListResponse> {
  return apiClient.get<NotificationListResponse>(
    `/notifications?status=${status}&limit=${limit}&offset=${offset}`
  );
}

export async function fetchUnreadCount(): Promise<number> {
  try {
    const res = await apiClient.get<UnreadCountResponse>('/notifications/unread-count');
    return res.unread_count;
  } catch {
    return 0;
  }
}

export async function markNotificationAsRead(id: string): Promise<NotificationItem> {
  return apiClient.patch<NotificationItem>(`/notifications/${id}/read`, {});
}

export async function markAllNotificationsAsRead(): Promise<{ message: string; updated_count: number }> {
  return apiClient.post<{ message: string; updated_count: number }>('/notifications/mark-all-read', {});
}

export async function triggerTestNotification(
  payloadOrMessage: string | {
    title: string;
    message: string;
    notification_type?: string;
    related_entity_type?: string;
    related_entity_id?: string;
  },
  notificationType?: string
): Promise<NotificationItem> {
  const payload =
    typeof payloadOrMessage === 'string'
      ? {
          title: 'Civic Alert',
          message: payloadOrMessage,
          notification_type: notificationType || 'INFO',
        }
      : payloadOrMessage;
  return apiClient.post<NotificationItem>('/notifications/test-trigger', payload);
}
