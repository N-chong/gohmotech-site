import { apiRequest } from './api';
import type { ApiPage, Notification } from '@/types/api';
export const alertService = {
  list: (page = 1) => apiRequest<ApiPage<Notification>>(`/security/api/notifications/?page=${page}&ordering=-created_at`),
  markRead: (id: number) => apiRequest<Notification>(`/security/api/notifications/${id}/mark_read/`, { method: 'POST' }),
};
