import { useState, useMemo } from 'react';
import { TagInput } from './TagInput';

interface ProxyBulkImportModalProps {
  open: boolean;
  existingServers: Set<string>;
  onClose: () => void;
  onImport: (data: {
    proxies: Array<{ server: string; username?: string; password?: string }>;
    tags: string[];
    skip_duplicates: boolean;
  }) => Promise<{ added: number; skipped: number }>;
}

interface ParsedProxy {
  server: string;
  username?: string;
  password?: string;
  isDuplicate: boolean;
}

function normalizeServer(s: string): string {
  return s.replace(/^https?:\/\//i, '').replace(/^socks[45]?:\/\//i, '').toLowerCase().replace(/\/$/, '');
}

function parseProxyLine(line: string): ParsedProxy | null {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith('#')) return null;

  const parts = trimmed.split(':');
  if (parts.length < 2) return null;

  // Format: ip:port:user:pass
  const ip = parts[0];
  const port = parts[1];
  const server = `${ip}:${port}`;

  if (parts.length >= 4) {
    return { server, username: parts[2], password: parts.slice(3).join(':'), isDuplicate: false };
  }
  if (parts.length === 3) {
    return { server, username: parts[2], isDuplicate: false };
  }
  return { server, isDuplicate: false };
}

export function ProxyBulkImportModal({
  open,
  existingServers,
  onClose,
  onImport,
}: ProxyBulkImportModalProps) {
  const [text, setText] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ added: number; skipped: number } | null>(null);

  const parsed = useMemo(() => {
    if (!open) return [];
    
    const lines = text.split('\n');
    const results: ParsedProxy[] = [];
    for (const line of lines) {
      const proxy = parseProxyLine(line);
      if (proxy) {
        proxy.isDuplicate = existingServers.has(normalizeServer(proxy.server));
        results.push(proxy);
      }
    }
    return results;
  }, [text, existingServers, open]);

  const duplicateCount = parsed.filter((p) => p.isDuplicate).length;
  const newCount = parsed.length - duplicateCount;

  if (!open) return null;

  const handleImport = async () => {
    if (newCount === 0) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await onImport({
        proxies: parsed
          .filter((p) => !p.isDuplicate)
          .map((p) => ({
            server: p.server,
            username: p.username,
            password: p.password,
          })),
        tags,
        skip_duplicates: true,
      });
      setResult(res);
      // Auto close after short delay on success
      setTimeout(() => {
        setText('');
        setTags([]);
        setResult(null);
        onClose();
      }, 1500);
    } catch {
      setResult({ added: 0, skipped: parsed.length });
    } finally {
      setLoading(false);
    }
  };

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        setText(reader.result);
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 540 }} onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title">Bulk Import Proxies</h3>

        <div className="input-group">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <label>Proxy List</label>
            <label
              className="btn btn-ghost btn-sm"
              style={{ cursor: 'pointer', fontSize: 11, padding: '2px 8px' }}
            >
              [open] Browse
              <input
                type="file"
                accept=".txt,.csv"
                onChange={handleFile}
                style={{ display: 'none' }}
              />
            </label>
          </div>
          <textarea
            className="input"
            style={{ minHeight: 140, fontFamily: 'var(--font-mono)', fontSize: 12, resize: 'vertical' }}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={`ip:port:user:pass\n14.224.198.119:42760:user1:pass1\n103.42.28.6:45600:user2:pass2`}
          />
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
            Format: ip:port:user:pass - one per line
          </div>
        </div>

        {parsed.length > 0 && (
          <div style={{
            padding: '8px 12px',
            background: 'var(--bg-input)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            fontSize: 12,
            fontFamily: 'var(--font-mono)',
            marginBottom: 12,
          }}>
            <div style={{ display: 'flex', gap: 16 }}>
              <span>Parsed: <b>{parsed.length}</b></span>
              <span style={{ color: 'var(--green)' }}>New: <b>{newCount}</b></span>
              {duplicateCount > 0 && (
                <span style={{ color: 'var(--yellow)' }}>
                  Duplicates: <b>{duplicateCount}</b> (will skip)
                </span>
              )}
            </div>
          </div>
        )}

        <div className="input-group">
          <label>Tags (applied to all imported)</label>
          <TagInput value={tags} onChange={setTags} placeholder="Add tags..." />
        </div>

        {result && (
          <div style={{
            padding: '8px 12px',
            background: result.added > 0 ? 'var(--green-subtle)' : 'var(--red-subtle)',
            borderRadius: 'var(--radius-sm)',
            fontSize: 12,
            marginBottom: 12,
            color: result.added > 0 ? 'var(--green)' : 'var(--red)',
          }}>
            [+] Added {result.added}, skipped {result.skipped}
          </div>
        )}

        <div className="modal-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleImport}
            disabled={loading || newCount === 0}
          >
            {loading ? (
              <><span className="spinner" /> Importing...</>
            ) : (
              `Import ${newCount} Proxies`
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
