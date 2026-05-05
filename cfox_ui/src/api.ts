const API_BASE = import.meta.env.VITE_API_URL || '';

export interface Profile {
  id: string;
  name: string;
  source: 'local' | 'cloud';
  os: string;
  status: string;
  tags: string[];
  notes: string;
  sessions: number;
  created_at: string;
  last_used_at: string | null;
  proxy_server: string | null;
  warmup_completed: boolean;
}

export interface Session {
  profile_id: string;
  source: string;
  profile_name: string;
  started_at: string;
  browser_pid: number | null;
}

export interface ProxyEntry {
  id: string;
  server: string;
  username: string | null;
  tags: string[];
  is_alive: boolean;
  last_checked_at: string | null;
  last_latency_ms: number | null;
  last_ip: string | null;
}

export interface HealthCheck {
  name: string;
  passed: boolean;
  severity: string;
  message: string;
}

export interface HealthReport {
  profile_id: string;
  status: string;
  score: number;
  checks: HealthCheck[];
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Profiles
export const api = {
  listProfiles: () =>
    request<{ profiles: Profile[]; server_connected: boolean }>('/api/profiles'),

  createProfile: (data: {
    name: string;
    os?: string;
    proxy_server?: string;
    proxy_username?: string;
    proxy_password?: string;
    tags?: string[];
    notes?: string;
  }) => request<Profile>('/api/profiles', { method: 'POST', body: JSON.stringify(data) }),

  getProfile: (id: string, source = 'local') =>
    request<Profile>(`/api/profiles/${id}?source=${source}`),

  updateProfile: (id: string, data: Record<string, unknown>) =>
    request<Profile>(`/api/profiles/${id}?source=local`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteProfile: (id: string) =>
    request<void>(`/api/profiles/${id}?source=local`, { method: 'DELETE' }),

  // Browser
  launchProfile: (id: string, opts?: { headless?: boolean; drift?: boolean }) =>
    request<Session>(`/api/profiles/${id}/launch?source=local`, {
      method: 'POST',
      body: JSON.stringify(opts || {}),
    }),

  stopProfile: (id: string) =>
    request<{ status: string }>(`/api/profiles/${id}/stop?source=local`, { method: 'POST' }),

  listSessions: () =>
    request<{ sessions: Session[] }>('/api/sessions'),

  // Health
  healthCheck: (id: string) =>
    request<HealthReport>(`/api/profiles/${id}/health?source=local`),

  // Proxies
  listProxies: () =>
    request<{ proxies: ProxyEntry[]; source: string }>('/api/proxies'),

  addProxy: (data: { server: string; username?: string; password?: string; tags?: string[] }) =>
    request<ProxyEntry>('/api/proxies', { method: 'POST', body: JSON.stringify(data) }),

  removeProxy: (id: string) =>
    request<void>(`/api/proxies/${id}`, { method: 'DELETE' }),

  checkProxies: () =>
    request<{ checked: number; results: ProxyEntry[] }>('/api/proxies/check', { method: 'POST' }),
};
