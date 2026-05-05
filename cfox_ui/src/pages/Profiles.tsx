import { useState, useCallback } from 'react';
import { api } from '../api';
import type { HealthReport } from '../api';
import { useProfiles } from '../hooks/useProfiles';
import { ProfileCard } from '../components/ProfileCard';
import { CreateProfileModal } from '../components/CreateProfileModal';
import { HealthModal } from '../components/HealthModal';

type StatusFilter = 'all' | 'idle' | 'running';

export function Profiles() {
  const {
    profiles,
    loading,
    actionLoading,
    error,
    launchProfile,
    stopProfile,
    createProfile,
    deleteProfile,
  } = useProfiles();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [showCreate, setShowCreate] = useState(false);
  const [healthReport, setHealthReport] = useState<HealthReport | null>(null);
  const [healthName, setHealthName] = useState('');
  const [toast, setToast] = useState<{ type: string; message: string } | null>(null);

  const showToast = (type: string, message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  };

  const handleLaunch = useCallback(async (id: string) => {
    try {
      await launchProfile(id);
      showToast('success', 'Browser launched');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Launch failed');
    }
  }, [launchProfile]);

  const handleStop = useCallback(async (id: string) => {
    try {
      await stopProfile(id);
      showToast('success', 'Browser stopped');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Stop failed');
    }
  }, [stopProfile]);

  const handleDelete = useCallback(async (id: string) => {
    const profile = profiles.find((p) => p.id === id);
    if (!confirm(`Delete "${profile?.name}"? This cannot be undone.`)) return;
    try {
      await deleteProfile(id);
      showToast('info', 'Profile deleted');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Delete failed');
    }
  }, [profiles, deleteProfile]);

  const handleHealthCheck = useCallback(async (id: string) => {
    try {
      const report = await api.healthCheck(id);
      const profile = profiles.find((p) => p.id === id);
      setHealthReport(report);
      setHealthName(profile?.name || id);
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Health check failed');
    }
  }, [profiles]);

  const filtered = profiles.filter((p) => {
    if (statusFilter !== 'all' && p.status !== statusFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        p.name.toLowerCase().includes(q) ||
        p.tags.some((t) => t.toLowerCase().includes(q)) ||
        p.id.includes(q)
      );
    }
    return true;
  });

  const runningCount = profiles.filter((p) => p.status === 'running').length;

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Profiles</h2>
          <div className="subtitle">
            {profiles.length} profile{profiles.length !== 1 ? 's' : ''}
            {runningCount > 0 && ` · ${runningCount} running`}
          </div>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          + New Profile
        </button>
      </div>

      <div className="toolbar">
        <div className="search-input">
          <span className="search-icon">🔍</span>
          <input
            className="input"
            placeholder="Search by name, tag, or ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="filter-group">
          {(['all', 'idle', 'running'] as StatusFilter[]).map((f) => (
            <button
              key={f}
              className={`filter-btn ${statusFilter === f ? 'active' : ''}`}
              onClick={() => setStatusFilter(f)}
            >
              {f === 'all' ? 'All' : f === 'idle' ? 'Idle' : 'Running'}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="empty-state">
          <div className="icon">⏳</div>
          <h3>Loading profiles...</h3>
        </div>
      ) : error ? (
        <div className="empty-state">
          <div className="icon">⚠️</div>
          <h3>Connection Error</h3>
          <p>{error}</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📁</div>
          <h3>{search ? 'No matching profiles' : 'No profiles yet'}</h3>
          <p>{search ? 'Try a different search term' : 'Create your first antidetect browser profile'}</p>
          {!search && (
            <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
              + Create Profile
            </button>
          )}
        </div>
      ) : (
        <div className="card-grid">
          {filtered.map((profile) => (
            <ProfileCard
              key={profile.id}
              profile={profile}
              isActionLoading={actionLoading[profile.id] || false}
              onLaunch={handleLaunch}
              onStop={handleStop}
              onDelete={handleDelete}
              onHealthCheck={handleHealthCheck}
            />
          ))}
        </div>
      )}

      <CreateProfileModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreate={async (data) => {
          await createProfile(data);
          showToast('success', `Profile "${data.name}" created`);
        }}
      />

      <HealthModal
        report={healthReport}
        profileName={healthName}
        onClose={() => setHealthReport(null)}
      />

      {toast && (
        <div className="toast-container">
          <div className={`toast ${toast.type}`}>{toast.message}</div>
        </div>
      )}
    </>
  );
}
