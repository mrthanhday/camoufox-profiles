import { useState } from 'react';
import { TagInput } from './TagInput';

interface CreateProfileModalProps {
  open: boolean;
  onClose: () => void;
  serverConnected?: boolean;
  onCreate: (data: {
    name: string;
    os: string;
    proxy_server?: string;
    proxy_username?: string;
    proxy_password?: string;
    tags?: string[];
    notes?: string;
    source?: string;
  }) => Promise<void>;
}

export function CreateProfileModal({ open, onClose, onCreate, serverConnected }: CreateProfileModalProps) {
  const [name, setName] = useState('');
  const [os, setOs] = useState('windows');
  const [source, setSource] = useState<'local' | 'cloud'>('local');
  const [proxyServer, setProxyServer] = useState('');
  const [proxyUser, setProxyUser] = useState('');
  const [proxyPass, setProxyPass] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('Name is required');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await onCreate({
        name: name.trim(),
        os,
        proxy_server: proxyServer || undefined,
        proxy_username: proxyUser || undefined,
        proxy_password: proxyPass || undefined,
        tags: tags.length > 0 ? tags : undefined,
        notes: notes || undefined,
        source,
      });
      // Reset
      setName(''); setOs('windows'); setSource('local'); setProxyServer(''); setProxyUser('');
      setProxyPass(''); setTags([]); setNotes('');
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create profile');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title">Create Profile</h3>
        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <label>Profile Name *</label>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="shop-account-1"
              autoFocus
            />
          </div>

          {/* Source selector — only show when cloud is available */}
          <div className="input-group">
            <label>Storage</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                className={`btn btn-sm ${source === 'local' ? 'btn-accent' : 'btn-ghost'}`}
                onClick={() => setSource('local')}
                style={{ flex: 1 }}
              >
                💾 Local
              </button>
              <button
                type="button"
                className={`btn btn-sm ${source === 'cloud' ? 'btn-accent' : 'btn-ghost'}`}
                onClick={() => setSource('cloud')}
                disabled={!serverConnected}
                style={{ flex: 1, opacity: serverConnected ? 1 : 0.4 }}
                title={!serverConnected ? 'Connect to cloud server in Settings first' : 'Store profile on cloud server'}
              >
                ☁️ Cloud {!serverConnected && '(offline)'}
              </button>
            </div>
          </div>

          <div className="input-group">
            <label>Target OS</label>
            <select className="input" value={os} onChange={(e) => setOs(e.target.value)}>
              <option value="windows">Windows</option>
              <option value="macos">macOS</option>
              <option value="linux">Linux</option>
            </select>
          </div>

          <div className="input-group">
            <label>Proxy Server</label>
            <input
              className="input"
              value={proxyServer}
              onChange={(e) => setProxyServer(e.target.value)}
              placeholder="http://proxy:8080 (optional)"
            />
          </div>

          {proxyServer && (
            <div style={{ display: 'flex', gap: 12 }}>
              <div className="input-group" style={{ flex: 1 }}>
                <label>Username</label>
                <input
                  className="input"
                  value={proxyUser}
                  onChange={(e) => setProxyUser(e.target.value)}
                  placeholder="user"
                />
              </div>
              <div className="input-group" style={{ flex: 1 }}>
                <label>Password</label>
                <input
                  className="input"
                  type="password"
                  value={proxyPass}
                  onChange={(e) => setProxyPass(e.target.value)}
                  placeholder="pass"
                />
              </div>
            </div>
          )}

          <div className="input-group">
            <label>Tags</label>
            <TagInput
              value={tags}
              onChange={setTags}
              placeholder="Add tags..."
            />
          </div>

          <div className="input-group">
            <label>Notes</label>
            <input
              className="input"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional description"
            />
          </div>

          {error && (
            <div style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>
              ⚠ {error}
            </div>
          )}

          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? <><span className="spinner" /> Creating…</> : `Create ${source === 'cloud' ? '☁️' : '💾'} Profile`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
