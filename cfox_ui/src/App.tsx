import { useState } from 'react';
import { Profiles } from './pages/Profiles';
import { ProxyPool } from './pages/ProxyPool';
import { Settings } from './pages/Settings';

type Page = 'profiles' | 'proxies' | 'settings';

const NAV_ITEMS: { id: Page; icon: string; label: string }[] = [
  { id: 'profiles', icon: '🦊', label: 'Profiles' },
  { id: 'proxies', icon: '🌐', label: 'Proxy Pool' },
  { id: 'settings', icon: '⚙️', label: 'Settings' },
];

export default function App() {
  const [page, setPage] = useState<Page>('profiles');

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h1>🦊 Camoufox</h1>
          <div className="version">cfox-local v0.1.0</div>
        </div>

        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? 'active' : ''}`}
              onClick={() => setPage(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="connection-badge">
            <span className="connection-dot disconnected" />
            Cloud: not connected
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="main-content">
        {page === 'profiles' && <Profiles />}
        {page === 'proxies' && <ProxyPool />}
        {page === 'settings' && <Settings />}
      </main>
    </div>
  );
}
