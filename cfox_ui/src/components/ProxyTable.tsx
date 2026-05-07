import type { ProxyEntry } from '../api';

type SortKey = 'server' | 'is_alive' | 'last_latency_ms' | 'last_checked_at';
type SortDir = 'asc' | 'desc';

interface ProxyTableProps {
  proxies: ProxyEntry[];
  selected: Set<string>;
  onToggleSelect: (id: string) => void;
  onToggleAll: () => void;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
  onCheckProxy: (id: string) => void;
  onDeleteProxy: (id: string) => void;
  checkingId: string | null;
  onEditProxy: (id: string, field: 'tags', value: string, e: React.MouseEvent) => void;
}

export function ProxyTable({
  proxies,
  selected,
  onToggleSelect,
  onToggleAll,
  sortKey,
  sortDir,
  onSort,
  onCheckProxy,
  onDeleteProxy,
  checkingId,
  onEditProxy,
}: ProxyTableProps) {
  const allSelected = proxies.length > 0 && proxies.every((p) => selected.has(p.id));

  const arrow = (key: SortKey) => {
    if (sortKey !== key) return '';
    return sortDir === 'asc' ? ' [^]' : ' [v]';
  };

  const statusDot = (proxy: ProxyEntry) => {
    if (proxy.last_checked_at === null) return '[-]';
    return proxy.is_alive ? '[+]' : '[x]';
  };

  const statusColor = (proxy: ProxyEntry) => {
    if (proxy.last_checked_at === null) return 'var(--text-muted)';
    return proxy.is_alive ? 'var(--green)' : 'var(--red)';
  };

  const formatLatency = (ms: number | null) => {
    if (ms === null) return '—';
    return `${ms}ms`;
  };

  const formatDate = (iso: string | null) => {
    if (!iso) return '—';
    const d = new Date(iso);
    const now = new Date();
    const diff = (now.getTime() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return d.toLocaleDateString();
  };

  return (
    <div className="profile-table-wrap" style={{ flex: 1, overflow: 'auto' }}>
      <table className="profile-table">
        <thead>
          <tr>
            <th style={{ width: 36 }}>
              <input
                type="checkbox"
                checked={allSelected}
                onChange={onToggleAll}
              />
            </th>
            <th style={{ width: 36 }}>[s]</th>
            <th
              className="sortable"
              onClick={() => onSort('server')}
              style={{ cursor: 'pointer' }}
            >
              Server{arrow('server')}
            </th>
            <th>Username</th>
            <th>Tags</th>
            <th
              className="sortable"
              onClick={() => onSort('last_latency_ms')}
              style={{ cursor: 'pointer', width: 80 }}
            >
              Latency{arrow('last_latency_ms')}
            </th>
            <th>IP</th>
            <th
              className="sortable"
              onClick={() => onSort('last_checked_at')}
              style={{ cursor: 'pointer', width: 100 }}
            >
              Checked{arrow('last_checked_at')}
            </th>
            <th style={{ width: 80 }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {proxies.length === 0 ? (
            <tr>
              <td colSpan={9} style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)' }}>
                No proxies found
              </td>
            </tr>
          ) : (
            proxies.map((p) => (
              <tr
                key={p.id}
                className={selected.has(p.id) ? 'selected' : ''}
              >
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(p.id)}
                    onChange={() => onToggleSelect(p.id)}
                  />
                </td>
                <td>
                  <span style={{ color: statusColor(p), fontSize: 12, fontFamily: 'var(--font-mono)' }}>
                    {statusDot(p)}
                  </span>
                </td>
                <td className="cell-mono">{p.server}</td>
                <td className="cell-mono" style={{ color: 'var(--text-secondary)' }}>
                  {p.username || '—'}
                </td>
                <td>
                  <div
                    className="cell-tags"
                    onClick={(e) => onEditProxy(p.id, 'tags', JSON.stringify(p.tags || []), e)}
                    title="Click to edit tags"
                  >
                    {(p.tags && p.tags.length > 0) ? (
                      <>
                        {p.tags.slice(0, 2).map((t) => <span key={t} className="tag">{t}</span>)}
                        {p.tags.length > 2 && <span className="tag">+{p.tags.length - 2}</span>}
                      </>
                    ) : (
                      <span className="cell-notes">—</span>
                    )}
                  </div>
                </td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                  {formatLatency(p.last_latency_ms)}
                </td>
                <td className="cell-mono" style={{ color: 'var(--text-secondary)' }}>
                  {p.last_ip || '—'}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                  {formatDate(p.last_checked_at)}
                </td>
                <td>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ padding: '2px 6px', fontSize: 11 }}
                      onClick={() => onCheckProxy(p.id)}
                      disabled={checkingId === p.id}
                      title="Health check"
                    >
                      {checkingId === p.id ? '...' : '[↻]'}
                    </button>
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ padding: '2px 6px', fontSize: 11, color: 'var(--red)' }}
                      onClick={() => onDeleteProxy(p.id)}
                      title="Delete"
                    >
                      [x]
                    </button>
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
