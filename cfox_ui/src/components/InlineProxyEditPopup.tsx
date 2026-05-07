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

export function InlineProxyEditPopup({
  initialValue,
  anchorRect,
  onSave,
  onClose,
}: InlineProxyEditPopupProps) {
  const [draft, setDraft] = useState(initialValue || '');
  const [proxies, setProxies] = useState<ProxyEntry[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);

  const popupRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Focus the input
    setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 20);

    // Load proxies
    api.listProxies().then((res) => {
      setProxies(res.proxies);
      setLoading(false);
    }).catch((err) => {
      console.error('Failed to load proxies', err);
      setLoading(false);
    });
  }, []);

  // Position popup below the anchor, clamped to viewport
  const popupWidth = 350;
  const popupHeight = 400; // Estimated max height
  
  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - popupHeight - 20);
  const left = Math.min(anchorRect.left, window.innerWidth - popupWidth - 20);

  const handleCustomSave = () => {
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

  const filteredProxies = proxies.filter((p) => {
    const s = search.toLowerCase();
    if (p.server.toLowerCase().includes(s)) return true;
    if (p.username && p.username.toLowerCase().includes(s)) return true;
    if (p.tags && p.tags.some((t) => t.toLowerCase().includes(s))) return true;
    return false;
  });

  return createPortal(
    <>
      <div className="inline-edit-overlay" onClick={onClose} />
      <div
        ref={popupRef}
        className="inline-edit-popup"
        style={{ top, left, width: popupWidth, padding: '12px', display: 'flex', flexDirection: 'column', gap: '16px' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div className="inline-edit-label" style={{ marginBottom: 0 }}>Custom Proxy</div>
            <button 
              className="btn-ghost" 
              style={{ fontSize: '11px', padding: '2px 6px', color: 'var(--text-muted)' }}
              onClick={handleClear}
              title="Clear Proxy"
            >
              [x] Clear
            </button>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <input
              ref={inputRef}
              type="text"
              className="inline-edit-input"
              style={{ flex: 1, margin: 0 }}
              placeholder="http://user:pass@ip:port"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
            />
            <button className="btn-primary" style={{ padding: '0 12px' }} onClick={handleCustomSave}>
              Save
            </button>
          </div>
        </div>

        <div style={{ height: '1px', backgroundColor: 'var(--hairline)' }} />

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', flex: 1, minHeight: 0 }}>
          <div className="inline-edit-label" style={{ marginBottom: 0 }}>Select from Proxy Pool</div>
          
          <input
            type="text"
            className="input"
            style={{ width: '100%', fontSize: '12px', padding: '4px 8px' }}
            placeholder="Search pool by ip, user, or tag..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />

          <div style={{ 
            flex: 1, 
            overflowY: 'auto', 
            maxHeight: '200px', 
            border: '1px solid var(--hairline)', 
            borderRadius: '4px',
            backgroundColor: 'var(--canvas)'
          }}>
            {loading ? (
              <div style={{ padding: '12px', textAlign: 'center', color: 'var(--text-muted)' }}>Loading...</div>
            ) : filteredProxies.length === 0 ? (
              <div style={{ padding: '12px', textAlign: 'center', color: 'var(--text-muted)' }}>No proxies found</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                {filteredProxies.map((p) => (
                  <div 
                    key={p.id}
                    style={{ 
                      display: 'flex', 
                      justifyContent: 'space-between', 
                      alignItems: 'center',
                      padding: '8px 12px',
                      borderBottom: '1px solid var(--hairline)'
                    }}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', overflow: 'hidden' }}>
                      <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {p.server}
                      </div>
                      {p.tags && p.tags.length > 0 && (
                        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                          {p.tags.map(t => (
                            <span key={t} style={{ 
                              fontSize: '10px', 
                              backgroundColor: 'var(--surface-hover)', 
                              padding: '2px 4px', 
                              borderRadius: '2px',
                              color: 'var(--text-muted)'
                            }}>
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <button 
                      className="btn-ghost" 
                      style={{ fontSize: '11px', padding: '4px 8px', marginLeft: '8px', flexShrink: 0 }}
                      onClick={() => handleSelectPool(p.id)}
                    >
                      [ Select ]
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </>,
    document.body
  );
}
