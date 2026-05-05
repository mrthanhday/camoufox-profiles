import type { Profile } from '../api';
import { StatusBadge } from './StatusBadge';

interface ProfileCardProps {
  profile: Profile;
  isActionLoading: boolean;
  onLaunch: (id: string) => void;
  onStop: (id: string) => void;
  onDelete: (id: string) => void;
  onHealthCheck: (id: string) => void;
}

export function ProfileCard({
  profile,
  isActionLoading,
  onLaunch,
  onStop,
  onDelete,
  onHealthCheck,
}: ProfileCardProps) {
  const isRunning = profile.status === 'running';
  const isBusy = ['launching', 'stopping', 'downloading', 'uploading'].includes(profile.status);

  return (
    <div className="card profile-card">
      <div className="profile-card-header">
        <div>
          <div className="profile-card-name">{profile.name}</div>
          <div className="profile-card-meta">
            <span className={`source-badge ${profile.source}`}>
              {profile.source === 'local' ? '💻' : '☁️'} {profile.source}
            </span>
            <span>{profile.os}</span>
            <span>·</span>
            <span>{profile.sessions} sessions</span>
          </div>
        </div>
        <StatusBadge status={profile.status} />
      </div>

      {profile.proxy_server && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: 8 }}>
          🔒 {profile.proxy_server}
        </div>
      )}

      {profile.tags.length > 0 && (
        <div className="profile-card-tags">
          {profile.tags.map((tag) => (
            <span key={tag} className="tag">{tag}</span>
          ))}
        </div>
      )}

      <div className="profile-card-actions">
        {isRunning ? (
          <button
            className="btn btn-danger btn-sm"
            onClick={() => onStop(profile.id)}
            disabled={isActionLoading || isBusy}
          >
            {isActionLoading ? <span className="spinner" /> : '■'} Stop
          </button>
        ) : (
          <button
            className="btn btn-success btn-sm"
            onClick={() => onLaunch(profile.id)}
            disabled={isActionLoading || isBusy}
          >
            {isActionLoading ? <span className="spinner" /> : '▶'} Launch
          </button>
        )}
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => onHealthCheck(profile.id)}
          disabled={isRunning || isBusy}
          title="Health Check"
        >
          🩺
        </button>
        <div style={{ flex: 1 }} />
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => onDelete(profile.id)}
          disabled={isRunning || isBusy}
          title="Delete"
          style={{ color: 'var(--red)' }}
        >
          🗑
        </button>
      </div>
    </div>
  );
}
