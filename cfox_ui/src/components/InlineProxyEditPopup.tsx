import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api';
import type { ProxyEntry } from '../api';

interface InlineProxyEditPopupProps {
  initialValue: string; // The current proxy_server string from the profile
  anchorRect: DOMRect;
  onSave: (data: { proxy_server?: string; proxy_id?: string }) => void;
  onClose: () => void;
}

/* ── Helpers (reused from ProxyTable pattern) ──────────────── */

function statusDot(proxy: ProxyEntry): string {
  if (proxy.last_checked_at === null) return '[-]';
  return proxy.is_alive ? '[+]' : '[x]';
}

function statusColor(proxy: ProxyEntry): string {
  if (proxy.last_checked_at === null) return 'var(--text-muted)';
  return proxy.is_alive ? 'var(--green)' : 'var(--red)';
}

export function InlineProxyEditPopup({
  initialValue,
  anchorRect,
  onSave,
  onClose,
}: InlineProxyEditPopupProps) {
  const [draft, setDraft] = useState(initialValue || '');
  const [proxies, setProxies] = useState<ProxyEntry[]>([]);
  const [search, setSearch] = useState('');
  const [selectedTag, setSelectedTag] = useState('all');
  const [loading, setLoading] = useState(true);
  const [checkStatus, setCheckStatus] = useState<'idle' | 'checking' | 'ok' | 'fail'>('idle');

  const popupRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 20);

    api.listProxies().then((res) => {
      setProxies(res.proxies);
      setLoading(false);
    }).catch((err) => {
      console.error('Failed to load proxies', err);
      setLoading(false);
    });
  }, []);

  // ── Position popup, clamped to viewport ───────────────────
  const popupWidth = 620;
  const popupMaxHeight = 540;

  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - popupMaxHeight - 20);
  const left = Math.min(anchorRect.left, window.innerWidth - popupWidth - 20);

  // ── Resolve current proxy from pool ───────────────────────
  const currentProxy = proxies.find((p) => p.server === initialValue) || null;

  // ── Handlers ──────────────────────────────────────────────

  const handleCustomSave = () => {
    if (!draft.trim()) return;
    onSave({ proxy_server: draft.trim() });
    onClose();
  };

  const handleClear = () => {
    onSave({ proxy_server: '' });
    onClose();
  };

  const handleSelectPool = (proxyId: string) => {
    onSave({ proxy_id: proxyId });
    onClose();
  };

  const handleCheckCustom = async () => {
    if (!draft.trim()) return;
    setCheckStatus('checking');
    try {
      // Try to find this proxy in the pool to check it via API
      const match = proxies.find((p) => p.server === draft.trim());
      if (match) {
        const result = await api.checkProxy(match.id);
        setCheckStatus(result.is_alive ? 'ok' : 'fail');
      } else {
        // No pool match — can't check an arbitrary string via existing API
        // Show a brief "unknown" then revert
        await new Promise((r) => setTimeout(r, 600));
        setCheckStatus('idle');
      }
    } catch {
      setCheckStatus('fail');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleCustomSave();
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  // ── Filtering ─────────────────────────────────────────────
  const filteredProxies = proxies.filter((p) => {
    if (selectedTag !== 'all') {
      if (!p.tags || !p.tags.includes(selectedTag)) return false;
    }
    const s = search.toLowerCase();
    if (!s) return true;
    if (p.server.toLowerCase().includes(s)) return true;
    if (p.username && p.username.toLowerCase().includes(s)) return true;
    if (p.tags && p.tags.some((t) => t.toLowerCase().includes(s))) return true;
    return false;
  });

  const allTags = Array.from(new Set(proxies.flatMap((p) => p.tags || []))).sort();

  // ── Check-status indicator ────────────────────────────────
  const checkDotColor = {
    idle: 'var(--text-muted)',
    checking: 'var(--yellow)',
    ok: 'var(--green)',
    fail: 'var(--red)',
  }[checkStatus];

  const checkDotAnim = checkStatus === 'checking' ? 'pulse 1s infinite' : 'none';

  return createPortal(
    <>
      <div className="inline-edit-overlay" onClick={onClose} />
      <div
        ref={popupRef}
        className="inline-edit-popup"
        style={{
          top,
          left,
          width: popupWidth,
          maxWidth: '90vw',
          padding: '14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '0',
          boxShadow: 'none',       /* design.md: no drop shadows */
          borderRadius: 'var(--radius-sm)', /* design.md: 4px */
        }}
        onClick={(e) => e.stopPropagation()}
      >

        {/* ── Section 1: Current Proxy ─────────────────────── */}
        <div style={{ paddingBottom: '10px', borderBottom: '1px solid var(--border)' }}>
          <div className="inline-edit-label" style={{ marginBottom: '6px' }}>Current Proxy</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minHeight: '24px' }}>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
              {initialValue ? (
                <>
                  <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px',
                    color: 'var(--text-primary)',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}>
                    {initialValue}
                  </span>
                  {currentProxy && currentProxy.tags && currentProxy.tags.length > 0 && (
                    <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                      {currentProxy.tags.slice(0, 3).map((t) => (
                        <span key={t} className="tag">{t}</span>
                      ))}
                      {currentProxy.tags.length > 3 && (
                        <span className="tag">+{currentProxy.tags.length - 3}</span>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <span style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '12px',
                  color: 'var(--text-muted)',
                  fontStyle: 'normal',
                }}>
                  No proxy assigned
                </span>
              )}
            </div>
            {initialValue && (
              <button
                className="btn btn-ghost btn-xs"
                onClick={handleClear}
                title="Clear proxy"
              >
                [x] Clear
              </button>
            )}
          </div>
        </div>

        {/* ── Section 2: Custom Proxy ──────────────────────── */}
        <div style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
          <div className="inline-edit-label" style={{ marginBottom: '6px' }}>Custom Proxy</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              ref={inputRef}
              type="text"
              className="input"
              style={{ flex: 1, fontSize: '12px', padding: '5px 8px' }}
              placeholder="http://user:pass@ip:port"
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                if (checkStatus !== 'idle') setCheckStatus('idle');
              }}
              onKeyDown={handleKeyDown}
            />
            {/* Status dot */}
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: checkDotColor,
                flexShrink: 0,
                animation: checkDotAnim,
              }}
              title={
                checkStatus === 'idle' ? 'Not checked' :
                checkStatus === 'checking' ? 'Checking...' :
                checkStatus === 'ok' ? 'Proxy OK' : 'Proxy failed'
              }
            />
            <button
              className="btn btn-ghost btn-sm"
              onClick={handleCheckCustom}
              disabled={checkStatus === 'checking' || !draft.trim()}
            >
              {checkStatus === 'checking' ? '...' : 'Check'}
            </button>
            <button
              className="btn btn-primary btn-sm"
              onClick={handleCustomSave}
              disabled={!draft.trim()}
            >
              Save
            </button>
          </div>
        </div>

        {/* ── Section 3: Select from Proxy Pool ────────────── */}
        <div style={{ padding: '10px 0', flex: 1, display: 'flex', flexDirection: 'column', gap: '8px', minHeight: 0 }}>
          <div className="inline-edit-label" style={{ marginBottom: '0' }}>Select from Proxy Pool</div>

          {/* Search + tag filter row */}
          <div style={{ display: 'flex', gap: '8px' }}>
            <input
              type="text"
              className="input"
              style={{ flex: 1, fontSize: '12px', padding: '5px 8px' }}
              placeholder="Search by ip, user, or tag..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select
              className="input"
              style={{ width: '130px', fontSize: '12px', padding: '5px 8px' }}
              value={selectedTag}
              onChange={(e) => setSelectedTag(e.target.value)}
            >
              <option value="all">All Tags</option>
              {allTags.map((tag) => (
                <option key={tag} value={tag}>{tag}</option>
              ))}
            </select>
          </div>

          {/* Proxy pool mini-table */}
          <div style={{
            flex: 1,
            overflowY: 'auto',
            maxHeight: '280px',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'var(--bg-surface)',
          }}>
            {/* Table header */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 120px 50px 72px',
              gap: '0',
              padding: '6px 10px',
              borderBottom: '1px solid var(--border)',
              backgroundColor: 'var(--bg-elevated)',
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              fontWeight: 600,
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              position: 'sticky',
              top: 0,
              zIndex: 1,
            }}>
              <span>Proxy</span>
              <span>Tags</span>
              <span style={{ textAlign: 'center' }}>Status</span>
              <span style={{ textAlign: 'right' }}>Action</span>
            </div>

            {/* Table body */}
            {loading ? (
              <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                Loading...
              </div>
            ) : filteredProxies.length === 0 ? (
              <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                No proxies found
              </div>
            ) : (
              filteredProxies.map((p) => (
                <div
                  key={p.id}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 120px 50px 72px',
                    gap: '0',
                    padding: '7px 10px',
                    borderBottom: '1px solid var(--border)',
                    alignItems: 'center',
                    transition: 'background var(--fast)',
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--bg-hover)'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                >
                  {/* Proxy server */}
                  <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px',
                    color: 'var(--text-primary)',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}>
                    {p.server}
                  </span>

                  {/* Tags */}
                  <div style={{ display: 'flex', gap: '3px', overflow: 'hidden', flexWrap: 'nowrap' }}>
                    {p.tags && p.tags.length > 0 ? (
                      <>
                        {p.tags.slice(0, 2).map((t) => (
                          <span key={t} className="tag">{t}</span>
                        ))}
                        {p.tags.length > 2 && (
                          <span className="tag">+{p.tags.length - 2}</span>
                        )}
                      </>
                    ) : (
                      <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>—</span>
                    )}
                  </div>

                  {/* Status */}
                  <span style={{
                    textAlign: 'center',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '11px',
                    color: statusColor(p),
                    fontWeight: 500,
                  }}>
                    {statusDot(p)}
                  </span>

                  {/* Action */}
                  <div style={{ textAlign: 'right' }}>
                    <button
                      className="btn btn-ghost btn-xs"
                      onClick={() => handleSelectPool(p.id)}
                    >
                      Select
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* ── Section 4: Footer ────────────────────────────── */}
        <div style={{
          display: 'flex',
          justifyContent: 'flex-end',
          paddingTop: '10px',
          borderTop: '1px solid var(--border)',
        }}>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </>,
    document.body
  );
}
