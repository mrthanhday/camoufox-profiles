import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import type { TagMeta } from '../api';

const COLOR_PRESETS = [
  { key: '', label: 'None', hex: '' },
  { key: 'red', label: 'Red', hex: '#ff3b30' },
  { key: 'orange', label: 'Orange', hex: '#ff9f0a' },
  { key: 'yellow', label: 'Yellow', hex: '#ffd60a' },
  { key: 'green', label: 'Green', hex: '#30d158' },
  { key: 'blue', label: 'Blue', hex: '#007aff' },
  { key: 'purple', label: 'Purple', hex: '#bf5af2' },
  { key: 'pink', label: 'Pink', hex: '#ff375f' },
];

export function TagManager() {
  const [tags, setTags] = useState<TagMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [newTagName, setNewTagName] = useState('');
  const [newTagColor, setNewTagColor] = useState('');
  const [editingTag, setEditingTag] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editColor, setEditColor] = useState('');
  const [toast, setToast] = useState<{ type: string; message: string } | null>(null);

  const showToast = (type: string, message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 3000);
  };

  const fetchTags = useCallback(async () => {
    try {
      const data = await api.listTags();
      setTags(data.tags);
    } catch {
      showToast('error', 'Failed to load tags');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTags();
  }, [fetchTags]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTagName.trim()) return;
    try {
      await api.createTag({ name: newTagName.trim(), color: newTagColor });
      setNewTagName('');
      setNewTagColor('');
      await fetchTags();
      showToast('success', `Tag "${newTagName.trim()}" created`);
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Failed');
    }
  };

  const handleSaveEdit = async (oldName: string) => {
    try {
      await api.updateTag(oldName, {
        new_name: editName !== oldName ? editName : undefined,
        color: editColor,
      });
      setEditingTag(null);
      await fetchTags();
      showToast('success', 'Tag updated');
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Failed');
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete tag "${name}"? This will remove it from all profiles.`)) return;
    try {
      await api.deleteTag(name);
      await fetchTags();
      showToast('success', `Tag "${name}" deleted`);
    } catch (e) {
      showToast('error', e instanceof Error ? e.message : 'Failed');
    }
  };

  const filtered = search
    ? tags.filter((t) => t.name.toLowerCase().includes(search.toLowerCase()))
    : tags;

  const getColorHex = (key: string) => {
    return COLOR_PRESETS.find((c) => c.key === key)?.hex || '';
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
        <span className="spinner" />
      </div>
    );
  }

  return (
    <>
      {/* Toolbar */}
      <div className="toolbar">
        <div className="search-input">
          <span className="search-icon" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>[/]</span>
          <input
            className="input"
            placeholder="Search tags..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button 
              className="btn btn-ghost"
              style={{ position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)', padding: '2px 6px', fontSize: 12, height: 'auto', minHeight: 0, border: 'none' }}
              onClick={() => setSearch('')}
            >
              [x]
            </button>
          )}
        </div>

        {/* Create form */}
        <form
          onSubmit={handleCreate}
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'center',
          }}
        >
          <input
            className="input"
            style={{ width: 180 }}
            value={newTagName}
            onChange={(e) => setNewTagName(e.target.value)}
            placeholder="New tag name..."
          />
          <div style={{ display: 'flex', gap: 4 }}>
            {COLOR_PRESETS.map((c) => (
              <button
                key={c.key}
                type="button"
                title={c.label}
                onClick={() => setNewTagColor(c.key)}
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: 'var(--radius-sm)',
                  border: newTagColor === c.key ? '2px solid var(--text-primary)' : '1px solid var(--border)',
                  background: c.hex || 'var(--bg-elevated)',
                  cursor: 'pointer',
                  padding: 0,
                }}
              />
            ))}
          </div>
          <button type="submit" className="btn btn-primary btn-sm" disabled={!newTagName.trim()}>
            [+] Create
          </button>
        </form>

        <span style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginLeft: 'auto' }}>
          {tags.length} tags
        </span>
      </div>

      {/* Tags list */}
      <div className="profile-table-wrap" style={{ flex: 1, overflow: 'auto' }}>
        <table className="profile-table">
          <thead>
            <tr>
              <th style={{ width: 36 }}>[c]</th>
              <th>Name</th>
              <th style={{ width: 100 }}>Profiles</th>
              <th style={{ width: 120 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)' }}>
                  {tags.length === 0 ? 'No tags created yet' : 'No matching tags'}
                </td>
              </tr>
            ) : (
              filtered.map((tag) => (
                <tr key={tag.name}>
                  <td>
                    {getColorHex(tag.color) ? (
                      <span style={{
                        display: 'inline-block',
                        width: 12,
                        height: 12,
                        borderRadius: 'var(--radius-sm)',
                        background: getColorHex(tag.color),
                      }} />
                    ) : (
                      <span style={{ color: 'var(--text-muted)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>[-]</span>
                    )}
                  </td>
                  <td>
                    {editingTag === tag.name ? (
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <input
                          className="input"
                          style={{ width: 160, fontSize: 12 }}
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          autoFocus
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSaveEdit(tag.name);
                            if (e.key === 'Escape') setEditingTag(null);
                          }}
                        />
                        <div style={{ display: 'flex', gap: 3 }}>
                          {COLOR_PRESETS.map((c) => (
                            <button
                              key={c.key}
                              type="button"
                              onClick={() => setEditColor(c.key)}
                              style={{
                                width: 14,
                                height: 14,
                                borderRadius: 'var(--radius-sm)',
                                border: editColor === c.key ? '2px solid var(--text-primary)' : '1px solid var(--border)',
                                background: c.hex || 'var(--bg-elevated)',
                                cursor: 'pointer',
                                padding: 0,
                              }}
                            />
                          ))}
                        </div>
                      </div>
                    ) : (
                      <span
                        className="cell-mono"
                        style={{ cursor: 'pointer' }}
                        onClick={() => {
                          setEditingTag(tag.name);
                          setEditName(tag.name);
                          setEditColor(tag.color);
                        }}
                      >
                        {tag.name}
                      </span>
                    )}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)' }}>
                    {tag.count}
                  </td>
                  <td>
                    {editingTag === tag.name ? (
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button
                          className="btn btn-primary btn-sm"
                          style={{ padding: '2px 8px', fontSize: 11 }}
                          onClick={() => handleSaveEdit(tag.name)}
                        >
                          Save
                        </button>
                        <button
                          className="btn btn-ghost btn-sm"
                          style={{ padding: '2px 8px', fontSize: 11 }}
                          onClick={() => setEditingTag(null)}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button
                          className="btn btn-ghost btn-sm"
                          style={{ padding: '2px 6px', fontSize: 11 }}
                          onClick={() => {
                            setEditingTag(tag.name);
                            setEditName(tag.name);
                            setEditColor(tag.color);
                          }}
                          title="Edit"
                        >
                          [edit]
                        </button>
                        <button
                          className="btn btn-ghost btn-sm"
                          style={{ padding: '2px 6px', fontSize: 11, color: 'var(--red)' }}
                          onClick={() => handleDelete(tag.name)}
                          title="Delete"
                        >
                          [x]
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {toast && (
        <div className="toast-container">
          <div className={`toast ${toast.type}`}>{toast.message}</div>
        </div>
      )}
    </>
  );
}
