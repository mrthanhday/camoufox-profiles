import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

interface InlineEditPopupProps {
  label: string;
  value: string;
  multiline?: boolean;
  anchorRect: DOMRect;
  onSave: (value: string) => void;
  onClose: () => void;
}

export function InlineEditPopup({
  label,
  value,
  multiline = false,
  anchorRect,
  onSave,
  onClose,
}: InlineEditPopupProps) {
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Focus + select on mount
    setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 20);
  }, []);

  // Position popup below the anchor, clamped to viewport
  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - 200);
  const left = Math.min(anchorRect.left, window.innerWidth - 280);

  const handleSave = () => {
    if (draft !== value) {
      onSave(draft);
    }
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !multiline) {
      e.preventDefault();
      handleSave();
    }
    if (e.key === 'Enter' && multiline && e.ctrlKey) {
      e.preventDefault();
      handleSave();
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  return createPortal(
    <>
      <div className="inline-edit-overlay" onClick={onClose} />
      <div
        ref={popupRef}
        className="inline-edit-popup"
        style={{ top, left }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="inline-edit-label">{label}</div>
        {multiline ? (
          <textarea
            ref={inputRef as React.RefObject<HTMLTextAreaElement>}
            className="inline-edit-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={3}
          />
        ) : (
          <input
            ref={inputRef as React.RefObject<HTMLInputElement>}
            type="text"
            className="inline-edit-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
          />
        )}
        <div className="inline-edit-actions">
          <button className="btn-cancel" onClick={onClose}>
            Esc
          </button>
          <button className="btn-save" onClick={handleSave}>
            Save
          </button>
        </div>
      </div>
    </>,
    document.body
  );
}
