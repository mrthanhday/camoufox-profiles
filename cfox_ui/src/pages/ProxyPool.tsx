import { useState, useEffect } from 'react';
import { api } from '../api';
import type { ProxyEntry } from '../api';

export function ProxyPool() {
  const [proxies, setProxies] = useState<ProxyEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [newServer, setNewServer] = useState('');
  const [newUser, setNewUser] = useState('');
  const [newPass, setNewPass] = useState('');
  const [addError, setAddError] = useState('');
  const [toast, setToast] = useState<{ type: string; message: string } | null>(null);

  const showToast = (type: string, message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  };

  const fetchProxies = async () => {
    try {
      const data = await api.listProxies();
      setProxies(data.proxies);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchProxies(); }, []);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newServer.trim()) { setAddError('Server URL is required'); return; }
    try {
      const entry = await api.addProxy({
        server: newServer.trim(),
        username: newUser || undefined,
        password: newPass || undefined,
      });
      setProxies((prev) => [entry, ...prev]);
      setNewServer(''); setNewUser(''); setNewPass('');
      setShowAdd(false);
      showToast('success', 'Proxy added');
    } catch (e) {
      setAddError(e instanceof Error ? e.message : 'Failed to add proxy');
    }
  };

  const handleRemove = async (id: string) => {
    if (!confirm('Remove this proxy?')) return;
    await api.removeProxy(id);
    setProxies((prev) => prev.filter((p) => p.id !== id));
    showToast('info', 'Proxy removed');
  };

  const handleCheckAll = async () => {
    setChecking(true);
    try {
      const data = await api.checkProxies();
      setProxies(data.results);
      showToast('success', `Checked ${data.checked} proxies`);
    } catch {
      showToast('error', 'Health check failed');
    } finally {
      setChecking(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Proxy Pool</h2>
          <div className="subtitle">{proxies.length} proxies (local)</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-ghost" onClick={handleCheckAll} disabled={checking}>
            {checking ? <><span className="spinner" /> Checking…</> : '🩺 Health Check'}
          </button>
          <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
            + Add Proxy
          </button>
        </div>
      </div>

      {loading ? (
        <div className="empty-state"><div className="icon">⏳</div><h3>Loading…</h3></div>
      ) : proxies.length === 0 ? (
        <div className="empty-state">
          <div className="icon">🌐</div>
          <h3>No proxies yet</h3>
          <p>Add proxies to bind to your profiles</p>
          <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ Add Proxy</button>
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Server</th>
                  <th>Username</th>
                  <th>Status</th>
                  <th>Latency</th>
                  <th>IP</th>
                  <th>Last Checked</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {proxies.map((p) => (
                  <tr key={p.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{p.server}</td>
                    <td>{p.username || '—'}</td>
                    <td>
                      <span className={`health-badge ${p.is_alive ? 'pass' : 'fail'}`}>
                        {p.is_alive ? '✓ Alive' : '✗ Dead'}
                      </span>
                    </td>
                    <td>{p.last_latency_ms ? `${p.last_latency_ms}ms` : '—'}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {p.last_ip || '—'}
                    </td>
                    <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      {p.last_checked_at
                        ? new Date(p.last_checked_at).toLocaleString()
                        : 'Never'}
                    </td>
                    <td>
                      <button
                        className="btn btn-ghost btn-sm btn-icon"
                        onClick={() => handleRemove(p.id)}
                        title="Remove"
                        style={{ color: 'var(--red)' }}
                      >
                        🗑
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showAdd && (
        <div className="modal-overlay" onClick={() => setShowAdd(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="modal-title">Add Proxy</h3>
            <form onSubmit={handleAdd}>
              <div className="input-group">
                <label>Server URL *</label>
                <input
                  className="input"
                  value={newServer}
                  onChange={(e) => setNewServer(e.target.value)}
                  placeholder="http://proxy:8080 or socks5://..."
                  autoFocus
                />
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <div className="input-group" style={{ flex: 1 }}>
                  <label>Username</label>
                  <input className="input" value={newUser} onChange={(e) => setNewUser(e.target.value)} />
                </div>
                <div className="input-group" style={{ flex: 1 }}>
                  <label>Password</label>
                  <input className="input" type="password" value={newPass} onChange={(e) => setNewPass(e.target.value)} />
                </div>
              </div>
              {addError && <div style={{ color: 'var(--red)', fontSize: 13 }}>⚠ {addError}</div>}
              <div className="modal-actions">
                <button type="button" className="btn btn-ghost" onClick={() => setShowAdd(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary">Add</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {toast && (
        <div className="toast-container">
          <div className={`toast ${toast.type}`}>{toast.message}</div>
        </div>
      )}
    </>
  );
}
