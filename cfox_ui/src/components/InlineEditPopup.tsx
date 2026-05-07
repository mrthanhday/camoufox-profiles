import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { TagInput } from './TagInput';

interface InlineEditPopupProps {
  label: string;
  value: string;
  multiline?: boolean;
  mode?: 'text' | 'tags';
  anchorRect: DOMRect;
  onSave: (value: string) => void;
  onClose: () => void;
}

export function InlineEditPopup({
  label,
  value,
  multiline = false,
  mode = 'text',
  anchorRect,
  onSave,
  onClose,
}: InlineEditPopupProps) {
  const [draft, setDraft] = useState(value);
  const [draftTags, setDraftTags] = useState<string[]>(() => {
    if (mode === 'tags') {
      try { return JSON.parse(value); } catch { return value ? value.split(',').map(t => t.trim()).filter(Boolean) : []; }
    }
    return [];
  });
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Focus + select on mount (only for text mode)
    if (mode !== 'tags') {
      setTimeout(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      }, 20);
    }
  }, [mode]);

  // Position popup below the anchor, clamped to viewport
  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - 200);
  const left = Math.min(anchorRect.left, window.innerWidth - 280);

  const handleSave = () => {
    if (mode === 'tags') {
      const newVal = JSON.stringify(draftTags);
      onSave(newVal);
    } else if (draft !== value) {
      onSave(draft);
    }
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !multiline && mode !== 'tags') {
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
        {mode === 'tags' ? (
          <TagInput
            value={draftTags}
            onChange={setDraftTags}
            placeholder="Add tags..."
          />
        ) : multiline ? (
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
