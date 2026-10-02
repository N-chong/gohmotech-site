import { authState, clearSession } from '@/stores/auth.store';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
export class ApiError extends Error { constructor(public status: number, message: string, public payload?: unknown) { super(message); } }

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (authState.token) headers.set('Authorization', `Token ${authState.token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  let response: Response;
  try { response = await fetch(`${API_BASE}${path}`, { ...init, headers }); }
  catch { throw new ApiError(0, navigator.onLine ? 'Cannot connect to GoHMoTech server.' : 'No internet connection.'); }
  if (response.status === 401) clearSession();
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string; error?: string } | null;
    throw new ApiError(response.status, payload?.detail || payload?.error || `Request failed (${response.status}).`, payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function authenticatedImageUrl(path: string): Promise<string> {
  const headers = new Headers();
  if (authState.token) headers.set('Authorization', `Token ${authState.token}`);
  const response = await fetch(path.startsWith('http') ? path : `${API_BASE}${path}`, { headers });
  if (!response.ok) throw new ApiError(response.status, 'Unable to load image.');
  return URL.createObjectURL(await response.blob());
}
