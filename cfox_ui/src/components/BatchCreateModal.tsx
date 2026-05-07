import { useState } from 'react';
import { TagInput } from './TagInput';

interface BatchCreateModalProps {
  open: boolean;
  onClose: () => void;
  onCreate: (data: {
    name: string;
    os: string;
    proxy_server?: string;
    tags?: string[];
    notes?: string;
  }) => Promise<void>;
}

export function BatchCreateModal({ open, onClose, onCreate }: BatchCreateModalProps) {
  const [prefix, setPrefix] = useState('');
  const [count, setCount] = useState(5);
  const [startNum, setStartNum] = useState(1);
  const [os, setOs] = useState('windows');
  const [proxyServer, setProxyServer] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [progress, setProgress] = useState(0);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prefix.trim()) {
      setError('Prefix is required');
      return;
    }
    if (count < 1 || count > 100) {
      setError('Count must be between 1 and 100');
      return;
    }
    setLoading(true);
    setError('');
    setProgress(0);

    const parsedTags = tags.length > 0 ? tags : undefined;
    let created = 0;
    const errors: string[] = [];

    for (let i = 0; i < count; i++) {
      const num = String(startNum + i).padStart(2, '0');
      const name = `${prefix.trim()}-${num}`;
      try {
        await onCreate({
          name,
          os,
          proxy_server: proxyServer || undefined,
          tags: parsedTags,
        });
        created++;
      } catch (e) {
        errors.push(`${name}: ${e instanceof Error ? e.message : 'failed'}`);
      }
      setProgress(Math.round(((i + 1) / count) * 100));
    }

    setLoading(false);
    if (errors.length > 0) {
      setError(`Created ${created}/${count}. Errors:\n${errors.join('\n')}`);
    } else {
      // Reset and close
      setPrefix(''); setCount(5); setStartNum(1);
      setOs('windows'); setProxyServer(''); setTags([]);
      setProgress(0);
      onClose();
    }
  };

  const previewNames = Array.from({ length: Math.min(count, 5) }, (_, i) => {
    const num = String(startNum + i).padStart(2, '0');
    return `${prefix || 'profile'}-${num}`;
  });

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title">Batch Create Profiles</h3>
        <form onSubmit={handleSubmit}>
          <div style={{ display: 'flex', gap: 12 }}>
            <div className="input-group" style={{ flex: 2 }}>
              <label>Name Prefix *</label>
              <input
                className="input"
                value={prefix}
                onChange={(e) => setPrefix(e.target.value)}
                placeholder="shop-acc"
                autoFocus
              />
            </div>
            <div className="input-group" style={{ flex: 1 }}>
              <label>Count</label>
              <input
                className="input"
                type="number"
                min={1}
                max={100}
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
              />
            </div>
            <div className="input-group" style={{ flex: 1 }}>
              <label>Start #</label>
              <input
                className="input"
                type="number"
                min={0}
                value={startNum}
                onChange={(e) => setStartNum(Number(e.target.value))}
              />
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
            <label>Proxy Server (shared)</label>
            <input
              className="input"
              value={proxyServer}
              onChange={(e) => setProxyServer(e.target.value)}
              placeholder="http://proxy:8080 (optional)"
            />
          </div>

          <div className="input-group">
            <label>Tags (shared)</label>
            <TagInput
              value={tags}
              onChange={setTags}
              placeholder="Add tags..."
            />
          </div>

          {/* Preview */}
          <div className="input-group">
            <label style={{ color: 'var(--text-muted)' }}>Preview</label>
            <div style={{
              background: 'var(--bg-input)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              padding: '8px 10px',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-secondary)',
              lineHeight: 1.6,
            }}>
              {previewNames.map((n) => (
                <div key={n}>{n}</div>
              ))}
              {count > 5 && <div style={{ color: 'var(--text-muted)' }}>... +{count - 5} more</div>}
            </div>
          </div>

          {loading && (
            <div style={{ marginBottom: 12 }}>
              <div style={{
                height: 4,
                background: 'var(--border)',
                borderRadius: 2,
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%',
                  width: `${progress}%`,
                  background: 'var(--accent)',
                  transition: 'width 0.2s',
                }} />
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                Creating... {progress}%
              </div>
            </div>
          )}

          {error && (
            <div style={{ color: 'var(--red)', fontSize: 12, marginBottom: 12, whiteSpace: 'pre-wrap' }}>
              ⚠ {error}
            </div>
          )}

          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? <>Creating {count}...</> : `Create ${count} Profiles`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
