import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import type { AppSettings, BrowseResult } from '../api';

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

// ── Directory Browser Modal ─────────────────────────────────────

function DirectoryBrowser({
  initialPath,
  onSelect,
  onClose,
}: {
  initialPath: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}) {
  const [browse, setBrowse] = useState<BrowseResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const navigateTo = useCallback(async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.browseDirectories(path);
      setBrowse(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to browse');
    } finally {
      setLoading(false);
    }
  }, []);

  // Load initial path
  useEffect(() => {
    navigateTo(initialPath);
  }, [initialPath, navigateTo]);

  // Load drives for root navigation
  const [drives, setDrives] = useState<{ name: string; path: string }[]>([]);
  useEffect(() => {
    api.listDrives().then((d) => setDrives(d.drives)).catch(() => {});
  }, []);

  // Build breadcrumb segments
  const breadcrumbs = browse
    ? browse.current
        .replace(/\\/g, '/')
        .split('/')
        .filter(Boolean)
        .reduce<{ label: string; path: string }[]>((acc, seg, i) => {
          const isWinDrive = i === 0 && seg.endsWith(':');
          const prevPath = acc.length > 0 ? acc[acc.length - 1].path : '';
          const path = isWinDrive ? `${seg}\\` : `${prevPath}/${seg}`;
          acc.push({ label: seg, path });
          return acc;
        }, [])
    : [];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-title">📂 Browse Directory</div>

        {/* Breadcrumb */}
        <div className="dir-browser-path">
          {drives.length > 1 && (
            <>
              <span
                className="dir-browser-crumb"
                onClick={() => {
                  setBrowse(null);
                  setLoading(false);
                  setError(null);
                }}
              >
                💻
              </span>
              <span className="dir-browser-sep">/</span>
            </>
          )}
          {breadcrumbs.map((seg, i) => (
            <span key={i}>
              <span
                className={`dir-browser-crumb ${i === breadcrumbs.length - 1 ? 'current' : ''}`}
                onClick={() => i < breadcrumbs.length - 1 && navigateTo(seg.path)}
              >
                {seg.label}
              </span>
              {i < breadcrumbs.length - 1 && <span className="dir-browser-sep"> / </span>}
            </span>
          ))}
        </div>

        {/* Directory list */}
        <div className="dir-browser-list">
          {loading ? (
            <div className="dir-browser-empty">Loading...</div>
          ) : error ? (
            <div className="dir-browser-empty" style={{ color: 'var(--red)' }}>
              ⚠ {error}
            </div>
          ) : !browse ? (
            // Show drives
            drives.map((d) => (
              <div
                key={d.path}
                className="dir-browser-item"
                onClick={() => navigateTo(d.path)}
              >
                <span>💾</span> {d.name}
              </div>
            ))
          ) : browse.directories.length === 0 ? (
            <div className="dir-browser-empty">No subdirectories</div>
          ) : (
            <>
              {browse.parent && (
                <div
                  className="dir-browser-item dir-browser-parent"
                  onClick={() => navigateTo(browse.parent!)}
                >
                  <span>⬆</span> ..
                </div>
              )}
              {browse.directories.map((d) => (
                <div
                  key={d.path}
                  className="dir-browser-item"
                  onClick={() => navigateTo(d.path)}
                >
                  <span>📁</span> {d.name}
                </div>
              ))}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-accent"
            disabled={!browse}
            onClick={() => browse && onSelect(browse.current)}
          >
            Select This Folder
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Confirm Modal (inline) ──────────────────────────────────────

function ConfirmDanger({
  open,
  title,
  message,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  message: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 400 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-title" style={{ color: 'var(--red)' }}>
          {title}
        </div>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 0 }}>
          {message}
        </p>
        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-danger" onClick={onConfirm}>
            Reset
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main Settings Page ──────────────────────────────────────────

export function Settings() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [sysInfo, setSysInfo] = useState<{
    machine_id: string;
    hostname: string;
    version: string;
    platform: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  // Editable fields
  const [editBaseDir, setEditBaseDir] = useState('');
  const [editMaxTags, setEditMaxTags] = useState(10);
  const [restartRequired, setRestartRequired] = useState(false);

  // UI state
  const [showBrowser, setShowBrowser] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [toast, setToast] = useState<{ type: string; message: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  const showToast = (type: string, message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  };

  // Load settings + system info
  useEffect(() => {
    const load = async () => {
      try {
        const [s, info] = await Promise.all([api.getSettings(), api.getSystemInfo()]);
        setSettings(s);
        setSysInfo(info);
        setEditBaseDir(s.base_dir);
        setEditMaxTags(s.max_tags_per_profile);
      } catch (e) {
        showToast('error', 'Failed to load settings');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  // Detect unsaved base_dir change
  const baseDirChanged = settings ? editBaseDir !== settings.base_dir : false;
  const maxTagsChanged = settings ? editMaxTags !== settings.max_tags_per_profile : false;
  const hasChanges = baseDirChanged || maxTagsChanged;

  const handleSave = async () => {
    setSaving(true);
    try {
      const updates: { base_dir?: string; max_tags_per_profile?: number } = {};
      if (baseDirChanged) updates.base_dir = editBaseDir;
      if (maxTagsChanged) updates.max_tags_per_profile = editMaxTags;

      const result = await api.updateSettings(updates);
      setSettings({
        ...settings!,
        ...result,
      });

      if (result.restart_required) {
        setRestartRequired(true);
      }

      showToast('success', 'Settings saved');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setShowResetConfirm(false);
    setSaving(true);
    try {
      // Reset to defaults
      const result = await api.updateSettings({
        max_tags_per_profile: 10,
      });
      setSettings({ ...settings!, ...result });
      setEditMaxTags(10);
      showToast('success', 'Settings reset to defaults');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Reset failed');
    } finally {
      setSaving(false);
    }
  };

  const handleCopyMachineId = () => {
    if (sysInfo) {
      navigator.clipboard.writeText(sysInfo.machine_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleBrowseSelect = (path: string) => {
    setEditBaseDir(path);
    setShowBrowser(false);
  };

  if (loading) {
    return (
      <div className="empty-state">
        <div className="icon">⏳</div>
        <h3>Loading settings...</h3>
      </div>
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Settings</h2>
          <div className="subtitle">Application configuration and system information</div>
        </div>
        {hasChanges && (
          <div className="header-actions">
            <button
              className="btn btn-ghost"
              onClick={() => {
                if (settings) {
                  setEditBaseDir(settings.base_dir);
                  setEditMaxTags(settings.max_tags_per_profile);
                }
              }}
            >
              Discard
            </button>
            <button className="btn btn-accent" onClick={handleSave} disabled={saving}>
              {saving ? <span className="spinner" /> : '💾'} Save Changes
            </button>
          </div>
        )}
      </div>

      {/* Restart warning banner */}
      {restartRequired && (
        <div className="settings-warning">
          <span>⚠️</span>
          <span>
            <strong>Restart required</strong> — Profile storage path has been changed. Restart
            cfox-local for the changes to take effect.
          </span>
        </div>
      )}

      {/* ① Profile Storage */}
      <div className="settings-section">
        <h3>Profile Storage</h3>
        <div className="input-group">
          <label>Profile Directory</label>
          <div className="settings-path-group">
            <input
              className="input settings-path-input"
              value={editBaseDir}
              onChange={(e) => setEditBaseDir(e.target.value)}
              placeholder="Path to profile storage folder"
            />
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setShowBrowser(true)}
              title="Browse directories"
            >
              📂 Browse
            </button>
          </div>
        </div>
        {settings && (
          <div className="settings-storage-info">
            <span>📊 {settings.profile_count} profile{settings.profile_count !== 1 ? 's' : ''}</span>
            <span>💾 {formatBytes(settings.storage_size_bytes)}</span>
          </div>
        )}
      </div>

      {/* ② General */}
      <div className="settings-section">
        <h3>General</h3>
        <div className="settings-info-grid">
          <span className="settings-label">Server Port</span>
          <span className="settings-value">{settings?.port ?? '—'}</span>

          <span className="settings-label">Host</span>
          <span className="settings-value">{settings?.host ?? '—'}</span>

          <span className="settings-label">Max Tags per Profile</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="number"
              className="input"
              style={{ width: 80 }}
              value={editMaxTags}
              onChange={(e) => setEditMaxTags(Math.max(1, Math.min(100, Number(e.target.value))))}
              min={1}
              max={100}
            />
            {maxTagsChanged && (
              <span style={{ fontSize: 11, color: 'var(--yellow)' }}>unsaved</span>
            )}
          </div>
        </div>
      </div>

      {/* ③ System Information */}
      <div className="settings-section">
        <h3>System Information</h3>
        <div className="settings-info-grid">
          <span className="settings-label">Machine ID</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="settings-value" style={{ opacity: 0.7 }}>
              {sysInfo?.machine_id
                ? `${sysInfo.machine_id.slice(0, 8)}...${sysInfo.machine_id.slice(-4)}`
                : '—'}
            </span>
            <button className="settings-copy-btn" onClick={handleCopyMachineId} title="Copy full ID">
              {copied ? '✓' : '📋'}
            </button>
          </div>

          <span className="settings-label">Hostname</span>
          <span className="settings-value">{sysInfo?.hostname ?? '—'}</span>

          <span className="settings-label">Platform</span>
          <span className="settings-value">{sysInfo?.platform ?? '—'}</span>

          <span className="settings-label">Version</span>
          <span className="settings-value">cfox-local v{sysInfo?.version ?? '—'}</span>

          <span className="settings-label">API Docs</span>
          <a
            href="/docs"
            target="_blank"
            rel="noopener"
            className="settings-value"
            style={{ color: 'var(--accent)' }}
          >
            /docs (Swagger UI)
          </a>
        </div>
      </div>

      {/* ④ Cloud Server (Phase 3) */}
      <div className="settings-section">
        <h3>Cloud Server (Phase 3)</h3>
        <div className="input-group">
          <label>Server URL</label>
          <input className="input" placeholder="https://cfox.myserver.com" disabled />
        </div>
        <div className="input-group">
          <label>API Key</label>
          <input className="input" type="password" placeholder="sk-..." disabled />
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
          Cloud sync will be available in a future update. Currently, all profiles are stored
          locally.
        </p>
      </div>

      {/* ⑤ Danger Zone */}
      <div className="settings-danger-zone">
        <h3
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            fontWeight: 600,
            marginBottom: 12,
            paddingBottom: 8,
            borderBottom: '1px solid rgba(255,59,48,0.2)',
            color: 'var(--red)',
          }}
        >
          Danger Zone
        </h3>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <div style={{ fontSize: 13, color: 'var(--text-primary)', marginBottom: 2 }}>
              Reset Settings
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Restore max tags to default value (10). Profile data is not affected.
            </div>
          </div>
          <button
            className="btn btn-danger-outline btn-sm"
            onClick={() => setShowResetConfirm(true)}
          >
            Reset
          </button>
        </div>
      </div>

      {/* Modals */}
      {showBrowser && (
        <DirectoryBrowser
          initialPath={editBaseDir}
          onSelect={handleBrowseSelect}
          onClose={() => setShowBrowser(false)}
        />
      )}

      <ConfirmDanger
        open={showResetConfirm}
        title="Reset Settings?"
        message="This will restore max tags per profile to the default value (10). Your profiles and data will not be affected."
        onConfirm={handleReset}
        onClose={() => setShowResetConfirm(false)}
      />

      {/* Toast */}
      {toast && (
        <div className="toast-container">
          <div className={`toast ${toast.type}`}>{toast.message}</div>
        </div>
      )}
    </>
  );
}
