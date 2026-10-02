import { apiRequest } from './api';
export interface Actuator { id: number; device_name: string; actuator_type: 'door' | 'light' | 'feeder'; current_state: string; current_state_display: string; mode: string; mode_display: string; last_changed_at: string }
export const automationService = {
  list: () => apiRequest<{ count: number; results: Actuator[] }>('/iot/api/actuators/'),
  control: (id: number, state: string) => apiRequest<{ message: string; current_state: string; result: string; device_online: boolean }>(`/iot/api/actuators/${id}/control/`, { method: 'POST', body: JSON.stringify({ state }) }),
};
