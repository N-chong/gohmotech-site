import { apiRequest } from './api';
export interface TrackingRow { goat: { id: number; goat_id: string; name: string }; beacon: { id: number; device_name: string; minor: number; battery_level: number | null }; receiver: { name: string; location: string; status: string } | null; proximity: string; proximity_display: string; status: string; status_display: string; last_seen: string | null; current_rssi: number | null }
export interface TrackingSnapshot { summary: Record<string, number>; goats: TrackingRow[]; generated_at?: string }
export const trackingService = { get: () => apiRequest<TrackingSnapshot>('/api/mobile/tracking/') };
