import { useState } from 'react';
import { TagInput } from './TagInput';

interface ProxyAddModalProps {
  open: boolean;
  onClose: () => void;
  onAdd: (data: {
    server: string;
    username?: string;
    password?: string;
    tags?: string[];
  }) => Promise<void>;
}

export function ProxyAddModal({ open, onClose, onAdd }: ProxyAddModalProps) {
  const [server, setServer] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!server.trim()) {
      setError('Server is required');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await onAdd({
        server: server.trim(),
        username: username || undefined,
        password: password || undefined,
        tags: tags.length > 0 ? tags : undefined,
      });
      setServer('');
      setUsername('');
      setPassword('');
      setTags([]);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title">Add Proxy</h3>
        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <label>Server *</label>
            <input
              className="input"
              value={server}
              onChange={(e) => setServer(e.target.value)}
              placeholder="ip:port"
              autoFocus
            />
          </div>

          <div style={{ display: 'flex', gap: 12 }}>
            <div className="input-group" style={{ flex: 1 }}>
              <label>Username</label>
              <input
                className="input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="user"
              />
            </div>
            <div className="input-group" style={{ flex: 1 }}>
              <label>Password</label>
              <input
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="pass"
              />
            </div>
          </div>

          <div className="input-group">
            <label>Tags</label>
            <TagInput value={tags} onChange={setTags} placeholder="Add tags..." />
          </div>

          {error && (
            <div style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>
              [!] {error}
            </div>
          )}

          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? <><span className="spinner" /> Adding...</> : 'Add Proxy'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
