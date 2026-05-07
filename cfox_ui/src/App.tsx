import { useState, useEffect } from 'react';
import { Profiles } from './pages/Profiles';
import { ProxyPool } from './pages/ProxyPool';
import { TagManager } from './pages/TagManager';
import { Settings } from './pages/Settings';
import { useProfiles } from './hooks/useProfiles';
import { api } from './api';
import type { SystemInfo } from './api';

type Page = 'profiles' | 'proxies' | 'tags' | 'settings';

export default function App() {
  const [page, setPage] = useState<Page>('profiles');
  const { profiles } = useProfiles();
  const runningCount = profiles.filter((p) => p.status === 'running').length;

  // ── System info (#55) ───────────────────────────────────────
  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null);
  useEffect(() => {
    api.getSystemInfo().then(setSysInfo).catch(() => {});
  }, []);

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h1>🦊 camoufox</h1>
          <div className="version">cfox-local v{sysInfo?.version ?? '0.3.0'}</div>
        </div>

        <nav className="sidebar-nav">
          <button
            className={`nav-item ${page === 'profiles' ? 'active' : ''}`}
            onClick={() => setPage('profiles')}
          >
            [&gt;] Profiles
            {runningCount > 0 && (
              <span className="nav-badge running">{runningCount}</span>
            )}
          </button>
          <button
            className={`nav-item ${page === 'proxies' ? 'active' : ''}`}
            onClick={() => setPage('proxies')}
          >
            [~] Proxy Pool
          </button>
          <button
            className={`nav-item ${page === 'settings' ? 'active' : ''}`}
            onClick={() => setPage('settings')}
          >
            [*] Settings
          </button>
          <button
            className={`nav-item ${page === 'tags' ? 'active' : ''}`}
            onClick={() => setPage('tags')}
          >
            [#] Tag Manager
          </button>
        </nav>

        <div className="sidebar-footer">
          {sysInfo && (
            <div className="machine-badge" title={`Machine ID: ${sysInfo.machine_id}`}>
              <span className="machine-icon">💻</span>
              <span className="machine-name">{sysInfo.hostname}</span>
            </div>
          )}
          <div className="connection-badge">
            <span className="connection-dot disconnected" />
            cloud: offline
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="main-content">
        {page === 'profiles' && <Profiles />}
        {page === 'proxies' && <ProxyPool />}
        {page === 'tags' && <TagManager />}
        {page === 'settings' && <Settings />}
      </main>
    </div>
  );
}
