export function Settings() {
  return (
    <>
      <div className="page-header">
        <div>
          <h2>Settings</h2>
          <div className="subtitle">Machine configuration and server connection</div>
        </div>
      </div>

      <div className="settings-section">
        <h3>Machine Info</h3>
        <div className="settings-row">
          <span className="settings-label">Service</span>
          <span className="settings-value">cfox-local v0.1.0</span>
        </div>
        <div className="settings-row">
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

      <div className="settings-section">
        <h3>Cloud Server (Phase 3)</h3>
        <div className="input-group">
          <label>Server URL</label>
          <input
            className="input"
            placeholder="https://cfox.myserver.com"
            disabled
          />
        </div>
        <div className="input-group">
          <label>API Key</label>
          <input
            className="input"
            type="password"
            placeholder="sk-..."
            disabled
          />
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
          Cloud sync will be available in a future update. Currently, all profiles are stored locally.
        </p>
      </div>

      <div className="settings-section">
        <h3>Keyboard Shortcuts</h3>
        <div className="settings-row">
          <span className="settings-label">Create Profile</span>
          <span className="settings-value" style={{ fontSize: 11 }}>Click "+ New Profile"</span>
        </div>
        <div className="settings-row">
          <span className="settings-label">Launch/Stop</span>
          <span className="settings-value" style={{ fontSize: 11 }}>Click ▶/■ on profile card</span>
        </div>
      </div>
    </>
  );
}
