

interface ProxyToolbarProps {
  search: string;
  onSearchChange: (v: string) => void;
  filter: 'all' | 'alive' | 'dead' | 'unchecked';
  onFilterChange: (f: 'all' | 'alive' | 'dead' | 'unchecked') => void;
  proxyCount: number;
  onAdd: () => void;
  onImport: () => void;
  onCheckAll: () => void;
  checking: boolean;
}

const filters: Array<{ key: 'all' | 'alive' | 'dead' | 'unchecked'; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'alive', label: 'Alive' },
  { key: 'dead', label: 'Dead' },
  { key: 'unchecked', label: 'Unchecked' },
];

export function ProxyToolbar({
  search,
  onSearchChange,
  filter,
  onFilterChange,
  proxyCount,
  onAdd,
  onImport,
  onCheckAll,
  checking,
}: ProxyToolbarProps) {
  return (
    <div className="toolbar">
      <div className="search-input">
        <span className="search-icon" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>[/]</span>
        <input
          className="input"
          placeholder="Search proxies..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
        {search && (
          <button 
            className="btn btn-ghost"
            style={{ position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)', padding: '2px 6px', fontSize: 12, height: 'auto', minHeight: 0, border: 'none' }}
            onClick={() => onSearchChange('')}
          >
            [x]
          </button>
        )}
      </div>

      <div className="filter-group">
        {filters.map((f) => (
          <button
            key={f.key}
            className={`filter-btn ${filter === f.key ? 'active' : ''}`}
            onClick={() => onFilterChange(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="toolbar-right">
        <span style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {proxyCount} proxies
        </span>
        <button className="btn btn-ghost btn-sm" onClick={onCheckAll} disabled={checking}>
          {checking ? <><span className="spinner" /> Checking...</> : '[*] Check All'}
        </button>
        <button className="btn btn-ghost btn-sm" onClick={onImport}>
          [^] Import
        </button>
        <button className="btn btn-primary btn-sm" onClick={onAdd}>
          [+] Add Proxy
        </button>
      </div>
    </div>
  );
}
