import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api';
import type { HealthReport } from '../api';
import { useProfiles } from '../hooks/useProfiles';
import { StatusBadge } from '../components/StatusBadge';
import { OsIcon, SourceIcon } from '../components/Icons';
import { CreateProfileModal } from '../components/CreateProfileModal';
import { BatchCreateModal } from '../components/BatchCreateModal';
import { ImportModal } from '../components/ImportModal';
import { HealthModal } from '../components/HealthModal';
import { InlineEditPopup } from '../components/InlineEditPopup';
import { InlineProxyEditPopup } from '../components/InlineProxyEditPopup';
import { ConfirmModal } from '../components/ConfirmModal';
import { BulkEditModal } from '../components/BulkEditModal';

type InlineEdit = {
  profileId: string;
  field: 'name' | 'tags' | 'notes';
  value: string;
  rect: DOMRect;
} | null;

type InlineProxyEdit = {
  profileId: string;
  value: string;
  rect: DOMRect;
} | null;

type ColumnId = 'src' | 'os' | 'status' | 'proxy' | 'lastrun' | 'tags' | 'notes';
const ALL_COLUMNS: { id: ColumnId; label: string }[] = [
  { id: 'src', label: 'Source' },
  { id: 'os', label: 'OS' },
  { id: 'status', label: 'Status' },
  { id: 'proxy', label: 'Proxy' },
  { id: 'lastrun', label: 'Last Run' },
  { id: 'tags', label: 'Tags' },
  { id: 'notes', label: 'Notes' },
];

type StatusFilter = 'all' | 'idle' | 'running' | 'error';
type SortKey = 'name' | 'status' | 'os' | 'last_used_at' | 'created_at';
type SortDir = 'asc' | 'desc';

function relativeTime(iso: string | null): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}

const PAGE_SIZES = [25, 50, 100];

// ── Dropdown Portal ─────────────────────────────────────────

function DropdownMenu({
  anchorRef,
  children,
  onClose,
}: {
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  children: React.ReactNode;
  onClose: () => void;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    if (anchorRef.current) {
      const rect = anchorRef.current.getBoundingClientRect();
      // Position dropdown below the button, aligned to right edge
      setPos({
        top: rect.bottom + 4,
        left: rect.right - 180, // 180 = min-width of menu
      });
    }
  }, [anchorRef]);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node) &&
          anchorRef.current && !anchorRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose, anchorRef]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  if (!pos) return null;

  return createPortal(
    <div
      ref={menuRef}
      className="dropdown-menu"
      style={{
        position: 'fixed',
        top: pos.top,
        left: Math.max(8, pos.left), // Don't go off-screen left
        zIndex: 999,
      }}
    >
      {children}
    </div>,
    document.body
  );
}

export function Profiles() {
  const {
    profiles, loading, actionLoading, error, serverConnected,
    launchProfile, stopProfile, createProfile, deleteProfile, fetchProfiles,
  } = useProfiles();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sortKey, setSortKey] = useState<SortKey>('created_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showCreate, setShowCreate] = useState(false);
  const [showBatchCreate, setShowBatchCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showHeaderMenu, setShowHeaderMenu] = useState(false);
  const [showColMenu, setShowColMenu] = useState(false);
  const [visibleCols, setVisibleCols] = useState<Set<ColumnId>>(new Set(ALL_COLUMNS.map(c => c.id)));
  const [healthReport, setHealthReport] = useState<HealthReport | null>(null);
  const [healthName, setHealthName] = useState('');
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: string; message: string } | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [inlineEdit, setInlineEdit] = useState<InlineEdit>(null);
  const [inlineProxyEdit, setInlineProxyEdit] = useState<InlineProxyEdit>(null);

  // Modal states for bulk actions
  const [showBulkDeleteConfirm, setShowBulkDeleteConfirm] = useState(false);
  const [showBulkSetTags, setShowBulkSetTags] = useState(false);
  const [showBulkSetProxy, setShowBulkSetProxy] = useState(false);

  const toggleCol = (id: ColumnId) => {
    setVisibleCols(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const col = (id: ColumnId) => visibleCols.has(id);

  // Refs for dropdown anchor buttons
  const menuAnchorRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  const showToast = (type: string, message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  };

  // ── Filter + Sort ──────────────────────────────────────────

  const filtered = useMemo(() => {
    let list = profiles.filter((p) => {
      if (statusFilter !== 'all') {
        if (statusFilter === 'error' && p.status !== 'error' && p.status !== 'sync_failed') return false;
        if (statusFilter === 'idle' && p.status !== 'idle') return false;
        if (statusFilter === 'running' && !['running', 'launching', 'stopping'].includes(p.status)) return false;
      }
      if (search) {
        const q = search.toLowerCase();
        return (
          p.name.toLowerCase().includes(q) ||
          p.tags.some((t) => t.toLowerCase().includes(q)) ||
          p.id.includes(q) ||
          (p.proxy_server || '').toLowerCase().includes(q) ||
          (p.notes || '').toLowerCase().includes(q)
        );
      }
      return true;
    });

    list.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case 'name': cmp = a.name.localeCompare(b.name); break;
        case 'status': cmp = a.status.localeCompare(b.status); break;
        case 'os': cmp = a.os.localeCompare(b.os); break;
        case 'last_used_at':
          cmp = (a.last_used_at || '').localeCompare(b.last_used_at || '');
          break;
        case 'created_at':
          cmp = (a.created_at || '').localeCompare(b.created_at || '');
          break;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });

    return list;
  }, [profiles, search, statusFilter, sortKey, sortDir]);

  // ── Pagination ─────────────────────────────────────────────

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const paged = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  // Reset page when filter changes
  useMemo(() => { setPage(1); }, [search, statusFilter]);

  // ── Selection ──────────────────────────────────────────────

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === paged.length && paged.every((p) => selected.has(p.id))) {
      setSelected(new Set());
    } else {
      setSelected(new Set(paged.map((p) => p.id)));
    }
  };

  const isAllSelected = paged.length > 0 && paged.every((p) => selected.has(p.id));
  const hasSelection = selected.size > 0;

  // ── Sort ───────────────────────────────────────────────────

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const sortArrow = (key: SortKey) =>
    sortKey === key ? (sortDir === 'asc' ? '↑' : '↓') : '';

  // ── Actions ────────────────────────────────────────────────

  const handleLaunch = useCallback(async (id: string) => {
    try {
      await launchProfile(id);
      showToast('success', 'Browser launched');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Launch failed');
    }
  }, [launchProfile]);

  const handleStop = useCallback(async (id: string) => {
    try {
      await stopProfile(id);
      showToast('success', 'Browser stopped');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Stop failed');
    }
  }, [stopProfile]);

  const handleDelete = useCallback(async (id: string) => {
    const profile = profiles.find((p) => p.id === id);
    if (!confirm(`Delete "${profile?.name}"? This cannot be undone.`)) return;
    try {
      await deleteProfile(id, profile?.source || 'local');
      setSelected((prev) => { const next = new Set(prev); next.delete(id); return next; });
      showToast('info', 'Profile deleted');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Delete failed');
    }
  }, [profiles, deleteProfile]);

  const handleHealthCheck = useCallback(async (id: string) => {
    try {
      const profile = profiles.find((p) => p.id === id);
      const source = profile?.source || 'local';
      const report = await api.healthCheck(id, source);
      setHealthReport(report);
      setHealthName(profile?.name || id);
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Health check failed');
    }
  }, [profiles]);

  // ── Bulk actions ───────────────────────────────────────────

  const selectedProfiles = useMemo(
    () => profiles.filter((p) => selected.has(p.id)),
    [profiles, selected]
  );

  const bulkLaunch = useCallback(async () => {
    const ids = selectedProfiles.filter((p) => p.status === 'idle').map((p) => p.id);
    if (ids.length === 0) { showToast('info', 'No idle profiles selected'); return; }
    for (const id of ids) { try { await launchProfile(id); } catch { /* continue */ } }
    showToast('success', `Launched ${ids.length} profile${ids.length !== 1 ? 's' : ''}`);
  }, [selectedProfiles, launchProfile]);

  const bulkStop = useCallback(async () => {
    const ids = selectedProfiles.filter((p) => ['running', 'launching'].includes(p.status)).map((p) => p.id);
    if (ids.length === 0) { showToast('info', 'No running profiles selected'); return; }
    for (const id of ids) { try { await stopProfile(id); } catch { /* continue */ } }
    showToast('success', `Stopped ${ids.length} profile${ids.length !== 1 ? 's' : ''}`);
  }, [selectedProfiles, stopProfile]);

  // bulkDelete: opens modal → confirmed via ConfirmModal → executes here
  const executeBulkDelete = useCallback(async () => {
    const ids = [...selected];
    const count = ids.length;
    for (const id of ids) {
      const profile = profiles.find((p) => p.id === id);
      try { await deleteProfile(id, profile?.source || 'local'); } catch { /* continue */ }
    }
    setSelected(new Set());
    showToast('info', `Deleted ${count} profile${count !== 1 ? 's' : ''}`);
  }, [selected, profiles, deleteProfile]);

  const bulkCheckProxy = useCallback(async () => {
    const withProxy = selectedProfiles.filter((p) => p.proxy_server);
    if (withProxy.length === 0) { showToast('info', 'No profiles with proxy selected'); return; }
    for (const p of withProxy) {
      try { await api.healthCheck(p.id, p.source); } catch { /* continue */ }
    }
    showToast('info', `Checked proxy for ${withProxy.length} profile${withProxy.length !== 1 ? 's' : ''}`);
  }, [selectedProfiles]);

  const bulkExport = useCallback(async () => {
    const data = selectedProfiles.map((p) => ({
      name: p.name, os: p.os, source: p.source,
      proxy_server: p.proxy_server, tags: p.tags, notes: p.notes,
    }));
    const json = JSON.stringify(data, null, 2);
    const filename = `cfox-export-${selectedProfiles.length}-profiles.json`;

    // Prefer File System Access API (Chromium / Edge) — lets user choose location
    if ('showSaveFilePicker' in window) {
      try {
        const handle = await (window as any).showSaveFilePicker({
          suggestedName: filename,
          types: [{ description: 'JSON', accept: { 'application/json': ['.json'] } }],
        });
        const writable = await handle.createWritable();
        await writable.write(json);
        await writable.close();
        showToast('success', `Saved as "${handle.name}"`);
        return;
      } catch (e) {
        if ((e as Error).name === 'AbortError') return; // user cancelled
      }
    }

    // Fallback: auto-download to browser Downloads folder
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
    showToast('info', `"${filename}" saved to Downloads folder`);
  }, [selectedProfiles]);

  // bulkSetProxy: opened via modal, value injected here
  const executeBulkSetProxy = useCallback(async (proxy: string) => {
    const ids = selectedProfiles.map((p) => p.id);
    let ok = 0;
    for (const id of ids) {
      const src = selectedProfiles.find((p) => p.id === id)?.source || 'local';
      try { await api.updateProfile(id, { proxy_server: proxy }, src); ok++; } catch { /* continue */ }
    }
    await fetchProfiles();
    showToast('success', `Proxy set for ${ok} profile${ok !== 1 ? 's' : ''}`);
  }, [selectedProfiles, fetchProfiles]);

  // bulkSetTags: opened via modal, value injected here
  const executeBulkSetTags = useCallback(async (input: string) => {
    const tags = JSON.parse(input) as string[];
    const ids = selectedProfiles.map((p) => p.id);
    let ok = 0;
    for (const id of ids) {
      const src = selectedProfiles.find((p) => p.id === id)?.source || 'local';
      try { await api.updateProfile(id, { tags }, src); ok++; } catch { /* continue */ }
    }
    await fetchProfiles();
    showToast('success', `Tags set for ${ok} profile${ok !== 1 ? 's' : ''}`);
  }, [selectedProfiles, fetchProfiles]);

  const bulkCopyIds = useCallback(() => {
    navigator.clipboard.writeText([...selected].join('\n'));
    showToast('info', `Copied ${selected.size} IDs`);
  }, [selected]);

  const bulkCopyNames = useCallback(() => {
    const names = selectedProfiles.map((p) => p.name);
    navigator.clipboard.writeText(names.join('\n'));
    showToast('info', `Copied ${names.length} names`);
  }, [selectedProfiles]);

  // ── Row context menu (portal-based) ───────────────────────

  const openMenu = (profileId: string) => {
    setMenuOpen(menuOpen === profileId ? null : profileId);
  };

  const closeMenu = useCallback(() => setMenuOpen(null), []);

  const runningCount = profiles.filter((p) => p.status === 'running').length;

  // ── Inline edit handler ───────────────────────────────────

  const openInlineEdit = (profileId: string, field: 'name' | 'tags' | 'notes', value: string, e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setInlineEdit({ profileId, field, value, rect });
  };

  const handleInlineSave = async (newValue: string) => {
    if (!inlineEdit) return;
    const { profileId, field } = inlineEdit;
    const src = profiles.find((p) => p.id === profileId)?.source || 'local';
    try {
      if (field === 'tags') {
        const tags = JSON.parse(newValue);
        await api.updateProfile(profileId, { tags }, src);
      } else {
        await api.updateProfile(profileId, { [field]: newValue }, src);
      }
      // Refresh from server
      await fetchProfiles();
      showToast('success', `${field.charAt(0).toUpperCase() + field.slice(1)} updated`);
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Update failed');
    }
  };

  const openInlineProxyEdit = (profileId: string, value: string, e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setInlineProxyEdit({ profileId, value, rect });
  };

  const handleInlineProxySave = async (data: { proxy_server?: string; proxy_id?: string }) => {
    if (!inlineProxyEdit) return;
    const { profileId } = inlineProxyEdit;
    const src = profiles.find((p) => p.id === profileId)?.source || 'local';
    try {
      await api.updateProfile(profileId, data, src);
      await fetchProfiles();
      showToast('success', 'Proxy updated');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Update failed');
    }
    setInlineProxyEdit(null);
  };

  // ── Keyboard shortcuts ────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Skip if user is typing in an input/textarea/select
      const tag = (e.target as HTMLElement).tagName;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return;
      // Skip if any modal is open
      if (showCreate || showBatchCreate || showImport || healthReport ||
          showBulkDeleteConfirm || showBulkSetTags || showBulkSetProxy || inlineEdit || inlineProxyEdit) return;

      if (e.key === 'a' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        setSelected(new Set(paged.map((p) => p.id)));
      } else if (e.key === 'Delete' && hasSelection) {
        e.preventDefault();
        setShowBulkDeleteConfirm(true);   // open modal instead of confirm()
      } else if (e.key === 'Enter' && hasSelection) {
        e.preventDefault();
        bulkLaunch();
      } else if (e.key === 'Escape') {
        if (hasSelection) setSelected(new Set());
        if (menuOpen) setMenuOpen(null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [paged, hasSelection, selected,
      showCreate, showBatchCreate, showImport, healthReport,
      showBulkDeleteConfirm, showBulkSetTags, showBulkSetProxy, inlineEdit,
      menuOpen, bulkLaunch]);

  // ── Render ─────────────────────────────────────────────────

  return (
    <>
      {/* Header */}
      <div className="page-header">
        <div>
          <h2>Profiles ({filtered.length})</h2>
          <div className="subtitle">
            {profiles.length} total
            {runningCount > 0 && <> · <span style={{ color: 'var(--success)' }}>{runningCount} running</span></>}
          </div>
        </div>
        <div className="header-actions">
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            [+] New Profile
          </button>
          <div style={{ position: 'relative' }}>
            <button className="btn btn-ghost" onClick={() => setShowHeaderMenu(!showHeaderMenu)}>▾ More</button>
            {showHeaderMenu && (
              <div className="dropdown-menu" style={{ position: 'absolute', right: 0, top: '100%', marginTop: 4, zIndex: 50 }}>
                <button className="dropdown-item" onClick={() => { setShowBatchCreate(true); setShowHeaderMenu(false); }}>[+] Batch Create</button>
                <button className="dropdown-item" onClick={() => { setShowImport(true); setShowHeaderMenu(false); }}>[↑] Import Profiles</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div className="toolbar">
        <div className="search-input">
          <span className="search-icon">⌕</span>
          <input
            className="input"
            placeholder="Search name, tag, proxy, notes..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="filter-group">
          {(['all', 'idle', 'running', 'error'] as StatusFilter[]).map((f) => (
            <button
              key={f}
              className={`filter-btn ${statusFilter === f ? 'active' : ''}`}
              onClick={() => setStatusFilter(f)}
            >
              {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
          <div className="bulk-divider" />
          <div style={{ position: 'relative' }}>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowColMenu(!showColMenu)} title="Toggle columns">⫶ Columns</button>
            {showColMenu && (
              <div className="dropdown-menu" style={{ position: 'absolute', right: 0, top: '100%', marginTop: 4, zIndex: 50 }}>
                {ALL_COLUMNS.map(c => (
                  <label key={c.id} className="dropdown-item" style={{ cursor: 'pointer', gap: 6 }}>
                    <input type="checkbox" checked={visibleCols.has(c.id)} onChange={() => toggleCol(c.id)} />
                    {c.label}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bulk action bar */}
      {hasSelection && (
        <div className="bulk-bar">
          <span className="bulk-count">{selected.size} selected</span>
          <button className="btn btn-ghost btn-sm" onClick={bulkLaunch} title="Launch idle profiles">▶ Launch</button>
          <button className="btn btn-ghost btn-sm" onClick={bulkStop} title="Stop running profiles">■ Stop</button>
          <div className="bulk-divider" />
          <button className="btn btn-ghost btn-sm" onClick={bulkCheckProxy} title="Check proxies">⟳ Check Proxy</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setShowBulkSetProxy(true)} title="Set proxy for selected">⇄ Set Proxy</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setShowBulkSetTags(true)} title="Set tags for selected"># Set Tags</button>
          <div className="bulk-divider" />
          <button className="btn btn-ghost btn-sm" onClick={bulkExport} title="Export selected profiles">↓ Export</button>
          <button className="btn btn-ghost btn-sm" onClick={bulkCopyIds} title="Copy IDs">[c] IDs</button>
          <button className="btn btn-ghost btn-sm" onClick={bulkCopyNames} title="Copy names">[c] Names</button>
          <div className="bulk-divider" />
          <button className="btn btn-danger-outline btn-sm" onClick={() => setShowBulkDeleteConfirm(true)} title="Delete selected (Del)">[x] Delete</button>
          <div style={{ flex: 1 }} />
          <button className="btn btn-ghost btn-sm" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="empty-state">
          <div className="icon">⏳</div>
          <h3>Loading profiles...</h3>
        </div>
      ) : error ? (
        <div className="empty-state">
          <div className="icon">⚠</div>
          <h3>Connection Error</h3>
          <p>{error}</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📁</div>
          <h3>{search ? 'No matching profiles' : 'No profiles yet'}</h3>
          <p>{search ? 'Try a different search' : 'Create your first antidetect browser profile'}</p>
          {!search && (
            <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
              [+] Create Profile
            </button>
          )}
        </div>
      ) : (
        <div className="table-container">
          <div className="table-wrapper">
            <table className="profile-table">
              <thead>
                <tr>
                  <th style={{ width: 36, textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      className="cell-checkbox"
                      checked={isAllSelected}
                      onChange={toggleSelectAll}
                    />
                  </th>
                  <th className={sortKey === 'name' ? 'sorted' : ''} onClick={() => handleSort('name')} style={{ minWidth: 120 }}>
                    Name <span className="sort-arrow">{sortArrow('name')}</span>
                  </th>
                  {col('src') && <th style={{ width: 48, textAlign: 'center' }}>Src</th>}
                  {col('os') && <th className={sortKey === 'os' ? 'sorted' : ''} onClick={() => handleSort('os')} style={{ width: 48, textAlign: 'center' }}>
                    OS <span className="sort-arrow">{sortArrow('os')}</span>
                  </th>}
                  {col('status') && <th className={sortKey === 'status' ? 'sorted' : ''} onClick={() => handleSort('status')}>
                    Status <span className="sort-arrow">{sortArrow('status')}</span>
                  </th>}
                  {col('proxy') && <th>Proxy</th>}
                  {col('lastrun') && <th className={sortKey === 'last_used_at' ? 'sorted' : ''} onClick={() => handleSort('last_used_at')}>
                    Last Run <span className="sort-arrow">{sortArrow('last_used_at')}</span>
                  </th>}
                  {col('tags') && <th>Tags</th>}
                  {col('notes') && <th>Notes</th>}
                  <th style={{ textAlign: 'right', width: 80 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {paged.map((p) => (
                  <tr
                    key={p.id}
                    className={selected.has(p.id) ? 'selected' : ''}
                  >
                    <td style={{ textAlign: 'center' }}>
                      <input
                        type="checkbox"
                        className="cell-checkbox"
                        checked={selected.has(p.id)}
                        onChange={() => toggleSelect(p.id)}
                      />
                    </td>
                    <td>
                      <span
                        className="cell-name"
                        onClick={(e) => openInlineEdit(p.id, 'name', p.name, e)}
                        title="Click to edit"
                      >{p.name}</span>
                    </td>
                    {col('src') && <td style={{ textAlign: 'center' }}><SourceIcon source={p.source} /></td>}
                    {col('os') && <td style={{ textAlign: 'center' }}><OsIcon os={p.os} /></td>}
                    {col('status') && <td><StatusBadge status={p.status} /></td>}
                    {col('proxy') && <td>
                      <span 
                        className="cell-proxy"
                        onClick={(e) => openInlineProxyEdit(p.id, p.proxy_server || '', e)}
                        title="Click to edit proxy"
                      >
                        {p.proxy_server || '—'}
                      </span>
                    </td>}
                    {col('lastrun') && <td><span className="cell-lastrun">{relativeTime(p.last_used_at)}</span></td>}
                    {col('tags') && <td>
                      <div
                        className="cell-tags"
                        onClick={(e) => openInlineEdit(p.id, 'tags', p.tags.join(', '), e)}
                        title="Click to edit tags"
                      >
                        {p.tags.length > 0 ? (
                          <>
                            {p.tags.slice(0, 2).map((t) => <span key={t} className="tag">{t}</span>)}
                            {p.tags.length > 2 && <span className="tag">+{p.tags.length - 2}</span>}
                          </>
                        ) : (
                          <span className="cell-notes">—</span>
                        )}
                      </div>
                    </td>}
                    {col('notes') && <td>
                      <span
                        className="cell-notes"
                        onClick={(e) => openInlineEdit(p.id, 'notes', p.notes || '', e)}
                        title="Click to edit notes"
                      >{p.notes || '—'}</span>
                    </td>}
                    <td>
                      <div className="cell-actions">
                        {p.status === 'idle' ? (
                          <button
                            className="btn btn-launch btn-xs"
                            disabled={actionLoading[p.id]}
                            onClick={() => handleLaunch(p.id)}
                            title="Launch browser"
                          >
                            {actionLoading[p.id] ? <span className="spinner" /> : '▶'}
                          </button>
                        ) : ['running', 'launching'].includes(p.status) ? (
                          <button
                            className="btn btn-stop btn-xs"
                            disabled={actionLoading[p.id]}
                            onClick={() => handleStop(p.id)}
                            title="Stop browser"
                          >
                            {actionLoading[p.id] ? <span className="spinner" /> : '■'}
                          </button>
                        ) : null}
                        <button
                          className="btn btn-ghost btn-xs"
                          ref={(el) => { if (el) menuAnchorRefs.current.set(p.id, el); }}
                          onClick={(e) => { e.stopPropagation(); openMenu(p.id); }}
                        >
                          ⋯
                        </button>
                        {menuOpen === p.id && (
                          <DropdownMenu
                            anchorRef={{ current: menuAnchorRefs.current.get(p.id) || null }}
                            onClose={closeMenu}
                          >
                            <button className="dropdown-item" onClick={() => { handleHealthCheck(p.id); closeMenu(); }}>
                              [h] Health Check
                            </button>
                            <button className="dropdown-item" onClick={() => { navigator.clipboard.writeText(p.id); showToast('info', 'ID copied'); closeMenu(); }}>
                              [c] Copy ID
                            </button>
                            <button className="dropdown-item" onClick={() => { navigator.clipboard.writeText(p.name); showToast('info', 'Name copied'); closeMenu(); }}>
                              [n] Copy Name
                            </button>
                            <div className="dropdown-divider" />
                            <button className="dropdown-item danger" onClick={() => { handleDelete(p.id); closeMenu(); }}>
                              [x] Delete
                            </button>
                          </DropdownMenu>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination footer */}
          <div className="table-footer">
            <div className="table-footer-info">
              {filtered.length} profile{filtered.length !== 1 ? 's' : ''}
              {hasSelection && <> · {selected.size} selected</>}
            </div>
            <div className="table-footer-pagination">
              <span className="table-footer-label">Per page:</span>
              <select
                className="input page-size-select"
                value={pageSize}
                onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
              >
                {PAGE_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button className="btn btn-ghost btn-xs" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>◀</button>
              <span className="table-footer-label">{currentPage}/{totalPages}</span>
              <button className="btn btn-ghost btn-xs" disabled={currentPage >= totalPages} onClick={() => setPage(currentPage + 1)}>▶</button>
            </div>
          </div>
        </div>
      )}

      {/* Modals */}

      {/* Bulk delete confirmation */}
      <ConfirmModal
        open={showBulkDeleteConfirm}
        title={`Delete ${selected.size} profile${selected.size !== 1 ? 's' : ''}?`}
        message={`This will permanently delete ${selected.size} profile${selected.size !== 1 ? 's' : ''} and all associated data. This action cannot be undone.`}
        confirmLabel="Delete"
        danger
        onConfirm={executeBulkDelete}
        onClose={() => setShowBulkDeleteConfirm(false)}
      />

      <BulkEditModal
        open={showBulkSetTags}
        title={`Set Tags — ${selected.size} profile${selected.size !== 1 ? 's' : ''}`}
        label="Tags"
        placeholder="Add tags..."
        hint="This will replace existing tags on all selected profiles."
        mode="tags"
        onSubmit={executeBulkSetTags}
        onClose={() => setShowBulkSetTags(false)}
      />

      {/* Bulk set proxy */}
      <BulkEditModal
        open={showBulkSetProxy}
        title={`Set Proxy — ${selected.size} profile${selected.size !== 1 ? 's' : ''}`}
        label="Proxy Server"
        placeholder="ip:port or user:pass@ip:port"
        hint="Applied to all selected profiles. Leave empty to clear proxy."
        allowEmpty
        onSubmit={executeBulkSetProxy}
        onClose={() => setShowBulkSetProxy(false)}
      />

      <CreateProfileModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        serverConnected={serverConnected}
        onCreate={async (data) => {
          await createProfile(data);
          showToast('success', `Profile "${data.name}" created ${data.source === 'cloud' ? '☁️ on cloud' : '💾 locally'}`);
        }}
      />

      <BatchCreateModal
        open={showBatchCreate}
        onClose={() => setShowBatchCreate(false)}
        onCreate={async (data) => {
          await createProfile(data);
        }}
      />

      <ImportModal
        open={showImport}
        onClose={() => setShowImport(false)}
        onCreate={async (data) => {
          await createProfile(data);
        }}
      />

      <HealthModal
        report={healthReport}
        profileName={healthName}
        onClose={() => setHealthReport(null)}
      />

      {/* Inline edit popup */}
      {inlineEdit && (
        <InlineEditPopup
          label={inlineEdit.field === 'tags' ? 'Tags' : inlineEdit.field}
          value={inlineEdit.field === 'tags' ? JSON.stringify(inlineEdit.value.split(',').map(t => t.trim()).filter(Boolean)) : inlineEdit.value}
          multiline={inlineEdit.field === 'notes'}
          mode={inlineEdit.field === 'tags' ? 'tags' : 'text'}
          anchorRect={inlineEdit.rect}
          onSave={handleInlineSave}
          onClose={() => setInlineEdit(null)}
        />
      )}

      {inlineProxyEdit && (
        <InlineProxyEditPopup
          initialValue={inlineProxyEdit.value}
          anchorRect={inlineProxyEdit.rect}
          onSave={handleInlineProxySave}
          onClose={() => setInlineProxyEdit(null)}
        />
      )}

      {toast && (
        <div className="toast-container">
          <div className={`toast ${toast.type}`}>{toast.message}</div>
        </div>
      )}
    </>
  );
}
