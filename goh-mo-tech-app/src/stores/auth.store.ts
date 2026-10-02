import { reactive, readonly } from 'vue';
import type { MobileUser } from '@/types/api';

interface AuthState { token: string | null; user: MobileUser | null }
const mutable = reactive<AuthState>({ token: null, user: null });
// Memory-only until native secure storage is installed; never put bearer tokens in localStorage/Preferences.
export const authState = readonly(mutable);
export function setSession(token: string, user: MobileUser) { mutable.token = token; mutable.user = user; }
export function clearSession() { mutable.token = null; mutable.user = null; }
