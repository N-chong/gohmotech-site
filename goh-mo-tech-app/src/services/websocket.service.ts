import { API_BASE, apiRequest } from './api';
export class FarmSocket {
  private socket?: WebSocket; private retries = 0; private stopped = false;
  constructor(private channel: 'sensors' | 'alerts' | 'feeding' | 'detections', private onMessage: (data: unknown) => void) {}
  async connect() {
    this.stopped = false;
    const { ticket } = await apiRequest<{ ticket: string }>('/api/mobile/auth/realtime-ticket/', { method: 'POST', body: JSON.stringify({ purpose: 'websocket' }) });
    const wsBase = (API_BASE || window.location.origin).replace(/^http/, 'ws');
    this.socket = new WebSocket(`${wsBase}/ws/${this.channel}/?ticket=${encodeURIComponent(ticket)}`);
    this.socket.onopen = () => { this.retries = 0; };
    this.socket.onmessage = (event) => { try { this.onMessage(JSON.parse(event.data)); } catch { /* malformed frame */ } };
    this.socket.onclose = () => { if (!this.stopped) window.setTimeout(() => void this.connect().catch(() => undefined), Math.min(30_000, 1_000 * 2 ** this.retries++)); };
  }
  close() { this.stopped = true; this.socket?.close(); }
}
