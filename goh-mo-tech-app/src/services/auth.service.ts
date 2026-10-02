import { apiRequest } from './api';
import { clearSession, setSession } from '@/stores/auth.store';
import type { MobileUser } from '@/types/api';
export const authService = {
  async login(username: string, password: string) {
    const result = await apiRequest<{ token: string; user: MobileUser }>('/api/mobile/auth/login/', { method: 'POST', body: JSON.stringify({ username, password }) });
    setSession(result.token, result.user); return result.user;
  },
  async logout() { try { await apiRequest<void>('/api/mobile/auth/logout/', { method: 'POST' }); } finally { clearSession(); } },
};
