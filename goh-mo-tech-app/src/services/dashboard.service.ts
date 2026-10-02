import { apiRequest } from './api';
import type { DashboardData } from '@/types/api';
export const dashboardService = { get: () => apiRequest<DashboardData>('/api/mobile/dashboard/') };
