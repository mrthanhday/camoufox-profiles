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

export interface SystemInfo {
  machine_id: string;
  hostname: string;
  version: string;
  platform: string;
  max_tags_per_profile: number;
}

export interface AppSettings {
  host: string;
  port: number;
  base_dir: string;
  max_tags_per_profile: number;
  server_url: string | null;
  server_api_key: string | null;
  profile_count: number;
  storage_size_bytes: number;
}

export interface ServerStatus {
  cloud_enabled: boolean;
  connected: boolean;
  healthy?: boolean;
  server_url: string | null;
}

export interface BrowseResult {
  current: string;
  parent: string | null;
  directories: { name: string; path: string }[];
}

export interface DriveList {
  drives: { name: string; path: string }[];
}

export interface TagMeta {
  name: string;
  color: string;
  count: number;
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
    source?: string;
  }) => request<Profile>('/api/profiles', { method: 'POST', body: JSON.stringify(data) }),

  getProfile: (id: string, source = 'local') =>
    request<Profile>(`/api/profiles/${id}?source=${source}`),

  updateProfile: (id: string, data: Record<string, unknown>, source = 'local') =>
    request<Profile>(`/api/profiles/${id}?source=${source}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteProfile: (id: string, source = 'local') =>
    request<void>(`/api/profiles/${id}?source=${source}`, { method: 'DELETE' }),

  // Browser
  launchProfile: (id: string, opts?: { headless?: boolean; drift?: boolean; startup_url?: string }, source = 'local') =>
    request<Session>(`/api/profiles/${id}/launch?source=${source}`, {
      method: 'POST',
      body: JSON.stringify(opts || {}),
    }),

  stopProfile: (id: string, source = 'local') =>
    request<{ status: string }>(`/api/profiles/${id}/stop?source=${source}`, { method: 'POST' }),

  listSessions: () =>
    request<{ sessions: Session[] }>('/api/sessions'),

  // Health
  healthCheck: (id: string, source = 'local') =>
    request<HealthReport>(`/api/profiles/${id}/health?source=${source}`),

  // Proxies
  listProxies: () =>
    request<{ proxies: ProxyEntry[]; source: string }>('/api/proxies'),

  addProxy: (data: { server: string; username?: string; password?: string; tags?: string[] }) =>
    request<ProxyEntry>('/api/proxies', { method: 'POST', body: JSON.stringify(data) }),

  updateProxy: (id: string, data: { tags?: string[] }) =>
    request<ProxyEntry>(`/api/proxies/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  removeProxy: (id: string) =>
    request<void>(`/api/proxies/${id}`, { method: 'DELETE' }),

  checkProxies: () =>
    request<{ checked: number; results: ProxyEntry[] }>('/api/proxies/check', { method: 'POST' }),

  checkProxy: (id: string) =>
    request<ProxyEntry>(`/api/proxies/${id}/check`, { method: 'POST' }),

  bulkAddProxies: (data: { proxies: Array<{ server: string; username?: string; password?: string }>; tags?: string[]; skip_duplicates?: boolean }) =>
    request<{ added: number; skipped: number; proxies: ProxyEntry[] }>('/api/proxies/bulk', { method: 'POST', body: JSON.stringify(data) }),

  // Tags
  listTags: () =>
    request<{ tags: TagMeta[] }>('/api/tags'),

  createTag: (data: { name: string; color?: string }) =>
    request<TagMeta>('/api/tags', { method: 'POST', body: JSON.stringify(data) }),

  updateTag: (name: string, data: { new_name?: string; color?: string }) =>
    request<TagMeta>(`/api/tags/${encodeURIComponent(name)}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteTag: (name: string) =>
    request<void>(`/api/tags/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  // System
  getSystemInfo: () =>
    request<SystemInfo>('/api/info'),

  // Settings
  getSettings: () =>
    request<AppSettings>('/api/settings'),

  updateSettings: (data: { base_dir?: string; max_tags_per_profile?: number; server_url?: string; server_api_key?: string }) =>
    request<AppSettings & { restart_required: boolean; changed_fields: string[] }>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  browseDirectories: (path: string) =>
    request<BrowseResult>(`/api/settings/browse?path=${encodeURIComponent(path)}`),

  listDrives: () =>
    request<DriveList>('/api/settings/drives'),

  // Server / Cloud
  getServerStatus: () =>
    request<ServerStatus>('/api/server/status'),

  connectServer: () =>
    request<{ connected: boolean; server_url?: string; error?: string }>('/api/server/connect', { method: 'POST' }),

  disconnectServer: () =>
    request<{ connected: boolean }>('/api/server/disconnect', { method: 'POST' }),
};
