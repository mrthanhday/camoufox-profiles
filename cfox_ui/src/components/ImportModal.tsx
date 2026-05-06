import { useState, useRef } from 'react';

interface ImportModalProps {
  open: boolean;
  onClose: () => void;
  onCreate: (data: {
    name: string;
    os?: string;
    proxy_server?: string;
    tags?: string[];
    notes?: string;
  }) => Promise<void>;
}

interface ImportedProfile {
  name: string;
  os?: string;
  proxy_server?: string;
  tags?: string[];
  notes?: string;
}

export function ImportModal({ open, onClose, onCreate }: ImportModalProps) {
  const [mode, setMode] = useState<'cfox' | 'csv'>('cfox');
  const [profiles, setProfiles] = useState<ImportedProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [progress, setProgress] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);

  if (!open) return null;

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError('');

    try {
      const text = await file.text();

      if (mode === 'cfox') {
        // JSON format: array of profile objects
        const data = JSON.parse(text);
        const arr = Array.isArray(data) ? data : data.profiles || [];
        const parsed: ImportedProfile[] = arr.map((item: Record<string, unknown>) => ({
          name: String(item.name || 'unnamed'),
          os: String(item.os || 'windows'),
          proxy_server: item.proxy_server ? String(item.proxy_server) : undefined,
          tags: Array.isArray(item.tags) ? item.tags.map(String) : undefined,
          notes: item.notes ? String(item.notes) : undefined,
        }));
        setProfiles(parsed);
      } else {
        // CSV format: name,os,proxy,tags,notes
        const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
        // Skip header if first line looks like header
        const start = /^name/i.test(lines[0]) ? 1 : 0;
        const parsed: ImportedProfile[] = [];
        for (let i = start; i < lines.length; i++) {
          const cols = lines[i].split(',').map((c) => c.trim());
          if (!cols[0]) continue;
          parsed.push({
            name: cols[0],
            os: cols[1] || 'windows',
            proxy_server: cols[2] || undefined,
            tags: cols[3] ? cols[3].split(';').map((t) => t.trim()).filter(Boolean) : undefined,
            notes: cols[4] || undefined,
          });
        }
        setProfiles(parsed);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to parse file');
      setProfiles([]);
    }
  };

  const handleImport = async () => {
    if (profiles.length === 0) return;
    setLoading(true);
    setError('');
    setProgress(0);

    let created = 0;
    const errors: string[] = [];

    for (let i = 0; i < profiles.length; i++) {
      try {
        await onCreate(profiles[i]);
        created++;
      } catch (e) {
        errors.push(`${profiles[i].name}: ${e instanceof Error ? e.message : 'failed'}`);
      }
      setProgress(Math.round(((i + 1) / profiles.length) * 100));
    }

    setLoading(false);
    if (errors.length > 0) {
      setError(`Imported ${created}/${profiles.length}. Errors:\n${errors.join('\n')}`);
    } else {
      setProfiles([]);
      setProgress(0);
      onClose();
    }
  };

  const reset = () => {
    setProfiles([]);
    setError('');
    setProgress(0);
    if (fileRef.current) fileRef.current.value = '';
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
        <h3 className="modal-title">Import Profiles</h3>

        {/* Mode tabs */}
        <div style={{
          display: 'flex', gap: 0, marginBottom: 16,
          border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
          overflow: 'hidden',
        }}>
          <button
            className={`btn ${mode === 'cfox' ? 'btn-primary' : 'btn-ghost'}`}
            style={{ flex: 1, borderRadius: 0, border: 'none' }}
            onClick={() => { setMode('cfox'); reset(); }}
          >
            .cfox / JSON
          </button>
          <button
            className={`btn ${mode === 'csv' ? 'btn-primary' : 'btn-ghost'}`}
            style={{ flex: 1, borderRadius: 0, border: 'none' }}
            onClick={() => { setMode('csv'); reset(); }}
          >
            CSV / Excel
          </button>
        </div>

        {/* File picker */}
        <div className="input-group">
          <label>{mode === 'cfox' ? 'Select .cfox or .json file' : 'Select .csv file'}</label>
          <input
            ref={fileRef}
            type="file"
            accept={mode === 'cfox' ? '.json,.cfox' : '.csv,.txt'}
            onChange={handleFileSelect}
            className="input"
            style={{ padding: '8px 10px' }}
          />
        </div>

        {/* Format hint */}
        <div style={{
          background: 'var(--bg-input)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)',
          padding: '8px 10px',
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-muted)',
          marginBottom: 12,
          lineHeight: 1.6,
        }}>
          {mode === 'cfox' ? (
            <>
              <div>Format: JSON array</div>
              <div>{'[{"name":"acc-01","os":"windows","proxy_server":"...","tags":["a"],"notes":"..."}]'}</div>
            </>
          ) : (
            <>
              <div>Format: name,os,proxy,tags(;separated),notes</div>
              <div>acc-01,windows,http://1.2.3.4:8080,shop;main,My note</div>
            </>
          )}
        </div>

        {/* Preview */}
        {profiles.length > 0 && (
          <div className="input-group">
            <label style={{ color: 'var(--text-secondary)' }}>
              {profiles.length} profiles found
            </label>
            <div style={{
              background: 'var(--bg-input)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              padding: '8px 10px',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-secondary)',
              lineHeight: 1.6,
              maxHeight: 120,
              overflowY: 'auto',
            }}>
              {profiles.slice(0, 8).map((p, i) => (
                <div key={i}>
                  {p.name} · {p.os || 'win'}
                  {p.proxy_server && ` · ${p.proxy_server}`}
                  {p.tags && p.tags.length > 0 && ` · [${p.tags.join(', ')}]`}
                </div>
              ))}
              {profiles.length > 8 && (
                <div style={{ color: 'var(--text-muted)' }}>... +{profiles.length - 8} more</div>
              )}
            </div>
          </div>
        )}

        {/* Progress */}
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
              Importing... {progress}%
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
          <button
            className="btn btn-primary"
            onClick={handleImport}
            disabled={loading || profiles.length === 0}
          >
            {loading ? `Importing...` : `Import ${profiles.length} Profiles`}
          </button>
        </div>
      </div>
    </div>
  );
}
