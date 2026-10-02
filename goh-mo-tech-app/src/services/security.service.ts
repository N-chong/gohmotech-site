import { apiRequest } from './api';
import type { ApiPage } from '@/types/api';
export interface Detection { id: number; detected_at: string; snapshot_url: string | null; source_display: string; detection_type_display: string; confidence: number; status_display: string; review_state: string }
export const securityService = { list: (page = 1) => apiRequest<ApiPage<Detection>>(`/security/api/detections/?page=${page}&ordering=-detected_at`) };
