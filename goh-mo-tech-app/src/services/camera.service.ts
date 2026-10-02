import { API_BASE, apiRequest } from './api';
import type { ApiPage, Camera } from '@/types/api';
export const cameraService = {
  list: () => apiRequest<ApiPage<Camera>>('/api/mobile/cameras/'),
  async streamUrl(cameraId: number) {
    const { ticket } = await apiRequest<{ ticket: string }>('/api/mobile/auth/realtime-ticket/', { method: 'POST', body: JSON.stringify({ purpose: 'camera', camera_id: cameraId }) });
    return `${API_BASE}/api/mobile/cameras/${cameraId}/stream/?quality=55&fps=8&width=640&ticket=${encodeURIComponent(ticket)}`;
  },
};
