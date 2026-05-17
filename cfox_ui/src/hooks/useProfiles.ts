import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api';
import type { Profile } from '../api';
import { useWebSocket } from './useWebSocket';

export function useProfiles() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [serverConnected, setServerConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const fetchProfiles = useCallback(async () => {
    try {
      const data = await api.listProfiles();
      if (mountedRef.current) {
        setProfiles(data.profiles);
        setServerConnected(data.server_connected);
        setError(null);
      }
    } catch (e) {
      if (mountedRef.current) {
        setError(e instanceof Error ? e.message : 'Failed to load profiles');
      }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  // WS handler — update profile status in-place
  useWebSocket((event) => {
    if (event.type === 'browser_status' && event.profile_id) {
      setProfiles((prev) =>
        prev.map((p) =>
          p.id === event.profile_id
            ? {
                ...p,
                status: event.status || p.status,
                ...(event.last_used_at ? { last_used_at: event.last_used_at as string } : {}),
              }
            : p
        )
      );
    }
    if (event.type === 'server_connection') {
      setServerConnected(event.status === 'connected');
      // Re-fetch profiles to load/unload cloud profiles
      fetchProfiles();
    }
  });

  useEffect(() => {
    mountedRef.current = true;
    fetchProfiles();
    return () => { mountedRef.current = false; };
  }, [fetchProfiles]);

  const setActionState = (id: string, loading: boolean) => {
    setActionLoading((prev) => ({ ...prev, [id]: loading }));
  };

  const launchProfile = async (id: string) => {
    setActionState(id, true);
    try {
      const profile = profiles.find((p) => p.id === id);
      const source = profile?.source || 'local';
      await api.launchProfile(id, undefined, source);
      setProfiles((prev) => prev.map((p) => (p.id === id ? { ...p, status: 'launching' } : p)));
    } catch (e) {
      throw e;
    } finally {
      setActionState(id, false);
    }
  };

  const stopProfile = async (id: string) => {
    setActionState(id, true);
    try {
      const profile = profiles.find((p) => p.id === id);
      const source = profile?.source || 'local';
      await api.stopProfile(id, source);
      setProfiles((prev) => prev.map((p) => (p.id === id ? { ...p, status: 'stopping' } : p)));
    } catch (e) {
      throw e;
    } finally {
      setActionState(id, false);
    }
  };

  const createProfile = async (data: Parameters<typeof api.createProfile>[0]) => {
    const profile = await api.createProfile(data);
    setProfiles((prev) => [profile, ...prev]);
    return profile;
  };

  const deleteProfile = async (id: string, source = 'local') => {
    await api.deleteProfile(id, source);
    setProfiles((prev) => prev.filter((p) => p.id !== id));
  };

  return {
    profiles,
    serverConnected,
    loading,
    actionLoading,
    error,
    fetchProfiles,
    launchProfile,
    stopProfile,
    createProfile,
    deleteProfile,
  };
}
