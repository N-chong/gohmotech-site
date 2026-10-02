export interface ApiPage<T> { count: number; next: string | null; previous: string | null; results: T[] }
export interface MobileUser { id: number; username: string; email: string; display_name: string; role: 'admin' | 'farm_owner' | 'farm_operator'; permissions: { farm_access: boolean; manage_farm: boolean } }
export interface DashboardData {
  generated_at: string;
  system: { online: boolean; controller_online: boolean; controller_last_seen: string | null; iot_online: number; iot_total: number; cameras_online: number; cameras_total: number };
  environment: { temperature: number | null; humidity: number | null; light_level: number | null; updated_at: string | null };
  feed: { percentage: number | null; is_low: boolean | null; updated_at: string | null };
  goats: { registered: number }; automation: { door: ActuatorSummary | null; light: ActuatorSummary | null }; alerts: AlertSummary[];
}
export interface ActuatorSummary { id: number; state: string; mode: string; updated_at: string }
export interface AlertSummary { id: number; title: string; severity: string; type: string; created_at: string }
export interface Goat {
  id: number; goat_id: string; name: string; tag_number: string; breed: string; breed_display: string; gender: string;
  gender_display: string; age: string; weight_kg: number | null; latest_weight: { weight_kg: string; measured_at: string } | null;
  health_status: string; status: string; last_seen: string | null; cover_image_url: string | null;
}
export interface GoatDetail extends Goat {
  date_of_birth: string | null; color_markings: string; health_notes: string; notes: string; vaccination_status: string;
  vaccination_status_display: string; vaccine_name: string; vaccination_date: string | null; next_due_date: string | null;
  date_added: string; last_updated: string;
  images: Array<{ id: number; image_url: string; angle: string | null; angle_display: string; image_type: string; captured_at: string; is_primary: boolean }>;
  weight_history: Array<{ id: number; weight_kg: string; source: string; source_display: string; measured_at: string; recorded_at: string; device_id: string }>;
}
export interface Camera { id: number; camera_id: string; name: string; camera_type: string; location: string; status: string; is_active: boolean; last_connected: string | null; last_error: string; updated_at: string }
export interface Notification { id: number; title: string; description: string; severity: string; severity_display: string; notification_type: string; type_display: string; source: string; is_read: boolean; is_resolved: boolean; created_at: string; event_url: string | null }
