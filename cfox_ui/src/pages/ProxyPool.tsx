import { useState, useEffect, useCallback, useMemo } from 'react';
import { api } from '../api';
import type { ProxyEntry } from '../api';
import { ProxyToolbar } from '../components/ProxyToolbar';
import { ProxyBulkBar } from '../components/ProxyBulkBar';
import { ProxyTable } from '../components/ProxyTable';
import { ProxyAddModal } from '../components/ProxyAddModal';
import { ProxyBulkImportModal } from '../components/ProxyBulkImportModal';
import { InlineEditPopup } from '../components/InlineEditPopup';

type SortKey = 'server' | 'is_alive' | 'last_latency_ms' | 'last_checked_at';
type SortDir = 'asc' | 'desc';
type Filter = 'all' | 'alive' | 'dead' | 'unchecked';

type InlineEdit = {
  id: string;
  field: 'tags';
  value: string;
  rect: DOMRect;
};

export function ProxyPool() {
  // ── Data ──────────────────────────────────────────────────────
  const [proxies, setProxies] = useState<ProxyEntry[]>([]);
  const [loading, setLoading] = useState(true);

  // ── UI State ──────────────────────────────────────────────────
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [sortKey, setSortKey] = useState<SortKey>('server');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showAdd, setShowAdd] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [checkingAll, setCheckingAll] = useState(false);
  const [checkingId, setCheckingId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: string; message: string } | null>(null);
  const [inlineEdit, setInlineEdit] = useState<InlineEdit | null>(null);

  // ── Fetch ─────────────────────────────────────────────────────
  const fetchProxies = useCallback(async () => {
    try {
      const data = await api.listProxies();
      setProxies(data.proxies);
    } catch {
      showToast('error', 'Failed to load proxies');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProxies();
  }, [fetchProxies]);

  // ── Toast ─────────────────────────────────────────────────────
  const showToast = (type: string, message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 3000);
  };

  // ── Filter + Search + Sort ────────────────────────────────────
  const filtered = useMemo(() => {
    let list = [...proxies];

    // Filter
    if (filter === 'alive') list = list.filter((p) => p.is_alive && p.last_checked_at);
    else if (filter === 'dead') list = list.filter((p) => !p.is_alive && p.last_checked_at);
    else if (filter === 'unchecked') list = list.filter((p) => !p.last_checked_at);

    // Search
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (p) =>
          p.server.toLowerCase().includes(q) ||
          (p.username || '').toLowerCase().includes(q) ||
          (p.last_ip || '').toLowerCase().includes(q) ||
          (p.tags || []).some((t) => t.toLowerCase().includes(q))
      );
    }

    // Sort
    list.sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'server') cmp = a.server.localeCompare(b.server);
      else if (sortKey === 'is_alive') cmp = (a.is_alive ? 1 : 0) - (b.is_alive ? 1 : 0);
      else if (sortKey === 'last_latency_ms') cmp = (a.last_latency_ms ?? 9999) - (b.last_latency_ms ?? 9999);
      else if (sortKey === 'last_checked_at') {
        const da = a.last_checked_at || '';
        const db = b.last_checked_at || '';
        cmp = da.localeCompare(db);
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });

    return list;
  }, [proxies, filter, search, sortKey, sortDir]);

  // ── Sort handler ──────────────────────────────────────────────
  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  // ── Selection ─────────────────────────────────────────────────
  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (filtered.every((p) => selected.has(p.id))) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map((p) => p.id)));
    }
  };

  // ── Actions ───────────────────────────────────────────────────
  const handleAdd = async (data: {
    server: string;
    username?: string;
    password?: string;
    tags?: string[];
  }) => {
    await api.addProxy(data);
    await fetchProxies();
    showToast('success', 'Proxy added');
  };

  const handleDelete = async (id: string) => {
    await api.removeProxy(id);
    setProxies((prev) => prev.filter((p) => p.id !== id));
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
    showToast('success', 'Proxy deleted');
  };

  const handleCheckAll = async () => {
    setCheckingAll(true);
    try {
      const res = await api.checkProxies();
      setProxies(res.results);
      showToast('success', `Checked ${res.checked} proxies`);
    } catch {
      showToast('error', 'Health check failed');
    } finally {
      setCheckingAll(false);
    }
  };

  const handleCheckProxy = async (id: string) => {
    setCheckingId(id);
    try {
      const updated = await api.checkProxy(id);
      setProxies((prev) => prev.map((p) => (p.id === id ? updated : p)));
    } catch {
      showToast('error', 'Check failed');
    } finally {
      setCheckingId(null);
    }
  };

  const handleCheckSelected = async () => {
    setCheckingAll(true);
    for (const id of selected) {
      try {
        const updated = await api.checkProxy(id);
        setProxies((prev) => prev.map((p) => (p.id === id ? updated : p)));
      } catch { /* continue */ }
    }
    setCheckingAll(false);
    showToast('success', `Checked ${selected.size} proxies`);
  };

  const handleDeleteSelected = async () => {
    const ids = [...selected];
    let ok = 0;
    for (const id of ids) {
      try { await api.removeProxy(id); ok++; } catch { /* continue */ }
    }
    setSelected(new Set());
    await fetchProxies();
    showToast('success', `Deleted ${ok} proxies`);
  };

  const handleBulkImport = async (data: {
    proxies: Array<{ server: string; username?: string; password?: string }>;
    tags: string[];
    skip_duplicates: boolean;
  }) => {
    const res = await api.bulkAddProxies(data);
    await fetchProxies();
    showToast('success', `Imported ${res.added} proxies (${res.skipped} skipped)`);
    return res;
  };

  const openInlineEdit = (id: string, field: 'tags', value: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setInlineEdit({ id, field, value, rect });
  };

  const handleInlineSave = async (val: string) => {
    if (!inlineEdit) return;
    const { id, field } = inlineEdit;
    try {
      if (field === 'tags') {
        const tags = JSON.parse(val);
        const updated = await api.updateProxy(id, { tags });
        setProxies((prev) => prev.map((p) => (p.id === id ? updated : p)));
      }
      showToast('success', 'Tags updated');
    } catch {
      showToast('error', 'Failed to update tags');
    } finally {
      setInlineEdit(null);
    }
  };

  // ── Existing servers set for dedup ────────────────────────────
  const existingServers = useMemo(() => {
    return new Set(
      proxies.map((p) =>
        p.server.replace(/^https?:\/\//i, '').replace(/^socks[45]?:\/\//i, '').toLowerCase().replace(/\/$/, '')
      )
    );
  }, [proxies]);

  // ── Render ────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
        <span className="spinner" />
      </div>
    );
  }

  return (
    <>
      <ProxyToolbar
        search={search}
        onSearchChange={setSearch}
        filter={filter}
        onFilterChange={setFilter}
        proxyCount={proxies.length}
        onAdd={() => setShowAdd(true)}
        onImport={() => setShowImport(true)}
        onCheckAll={handleCheckAll}
        checking={checkingAll}
      />

      <ProxyBulkBar
        count={selected.size}
        onCheckSelected={handleCheckSelected}
        onDeleteSelected={handleDeleteSelected}
        onClearSelection={() => setSelected(new Set())}
        checking={checkingAll}
      />

      <ProxyTable
        proxies={filtered}
        selected={selected}
        onToggleSelect={toggleSelect}
        onToggleAll={toggleAll}
        sortKey={sortKey}
        sortDir={sortDir}
        onSort={handleSort}
        onCheckProxy={handleCheckProxy}
        onDeleteProxy={handleDelete}
        checkingId={checkingId}
        onEditProxy={openInlineEdit}
      />

      {inlineEdit && (
        <InlineEditPopup
          label="Tags"
          value={inlineEdit.value}
          mode="tags"
          anchorRect={inlineEdit.rect}
          onSave={handleInlineSave}
          onClose={() => setInlineEdit(null)}
        />
      )}

      <ProxyAddModal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onAdd={handleAdd}
      />

      <ProxyBulkImportModal
        open={showImport}
        existingServers={existingServers}
        onClose={() => setShowImport(false)}
        onImport={handleBulkImport}
      />

      {toast && (
        <div className="toast-container">
          <div className={`toast ${toast.type}`}>{toast.message}</div>
        </div>
      )}
    </>
  );
}
