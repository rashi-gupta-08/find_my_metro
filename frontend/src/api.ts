import type { Acknowledgement, CommunitySignal, JourneySnapshot, Network, Preference, Report, ReportOutcome, Snapshot, SourceStatus, SurfaceReport, Trip } from './types';

let csrfToken: string | null = null;
export interface Account { id: string; username: string; display_name: string; role: string; verified_contributor: boolean }
interface AuthResult { user: Account | null; csrf_token: string | null }
export class ApiError extends Error { constructor(message: string, public status: number, public retryAfter = 0) { super(message); } }
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...options, signal: options?.signal ?? AbortSignal.timeout(8000) });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status})`, response.status, Number(response.headers.get('Retry-After')) || 0);
  }
  return response.json();
}

export const api = {
  network: () => request<Network>('/api/v1/network'),
  health: () => request<{ ready: boolean; api: string; database: string; worker: string; queued_events: number }>('/api/v1/health'),
  eta: (station: string) => request<Snapshot>(`/api/v1/eta/${encodeURIComponent(station)}`),
  trips: () => request<{ trips: Trip[] }>('/api/v1/trips'),
  status: (trip: string) => request<SourceStatus>(`/api/v1/source-status/${encodeURIComponent(trip)}`),
  routes: (origin: string, destination: string, preference: Preference = 'fastest', signal?: AbortSignal) => request<JourneySnapshot>(`/api/v1/routes?origin=${encodeURIComponent(origin)}&destination=${encodeURIComponent(destination)}&preference=${preference}`,{signal}),
  serviceStatus: () => request<{signals: CommunitySignal[]; generated_at: string}>('/api/v1/service-status'),
  submitSurface: (reports: SurfaceReport[]) => mutation<{acknowledgements: Acknowledgement[]}>('/api/v1/reports/batch', {reports}),
  mySurfaceReports: () => request<{reports: ReportOutcome[]; generated_at: string}>('/api/v1/reports/mine'),
  contributions: () => request<{points: number; validated_contributions: number; badges: string[]; award_policy: string}>('/api/v1/contributions/mine'),
  me: async () => { const result = await request<AuthResult>('/api/v1/auth/me'); csrfToken = result.csrf_token; return result; },
  authenticate: async (kind: 'login' | 'register', body: { username: string; password: string; display_name?: string }) => {
    const result = await request<AuthResult>(`/api/v1/auth/${kind}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    csrfToken = result.csrf_token; return result;
  },
  logout: async () => { await mutation('/api/v1/auth/logout', {}); csrfToken = null; },
  password: (current_password: string, new_password: string) => mutation('/api/v1/auth/password', { current_password, new_password }),
  recoverPassword: (token: string, new_password: string) => request<{ok: boolean}>('/api/v1/auth/password/reset', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({token, new_password})}),
  deleteAccount: (current_password: string) => mutation('/api/v1/auth/account/delete', { current_password }),
  timetable: (body: unknown) => mutation('/api/v1/operator/timetable', body),
  submit: (reports: Report[]) => mutation<{ acknowledgements: Acknowledgement[] }>('/api/v1/crowd-reports/batch', { reports }),
};

async function mutation<T = unknown>(path: string, body: unknown): Promise<T> {
  if (!csrfToken) await api.me();
  return request<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken ?? '' }, body: JSON.stringify(body) });
}

export const sourceName: Record<string, string> = {
  wsn: 'Underground signal', crowd: 'Community signal', fused: 'Combined evidence',
  estimate: 'Transition estimate', schedule: 'Timetable estimate',
};

export function readStored<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback; } catch { return fallback; }
}

export function saveStored(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* The UI still works when storage is unavailable. */ }
}
