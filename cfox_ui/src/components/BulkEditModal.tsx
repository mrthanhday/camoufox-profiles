import { useState, useEffect, useRef } from 'react';
import { TagInput } from './TagInput';

interface BulkEditModalProps {
  open: boolean;
  title: string;
  label: string;
  placeholder: string;
  hint?: string;
  initialValue?: string;
  allowEmpty?: boolean;
  mode?: 'text' | 'tags';
  onSubmit: (value: string) => void;
  onClose: () => void;
}

export function BulkEditModal({
  open,
  title,
  label,
  placeholder,
  hint,
  initialValue = '',
  allowEmpty = false,
  mode = 'text',
  onSubmit,
  onClose,
}: BulkEditModalProps) {
  const [value, setValue] = useState(initialValue);
  const [tags, setTags] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setValue(initialValue);
      setTags([]);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open, initialValue]);

  if (!open) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === 'tags') {
      onSubmit(JSON.stringify(tags));
    } else {
      if (!allowEmpty && !value.trim()) return;
      onSubmit(value.trim());
    }
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose} onKeyDown={handleKeyDown}>
      <form
        className="modal"
        style={{ maxWidth: 400 }}
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
      >
        <div className="modal-title">{title}</div>

        <div className="form-group">
          <label className="form-label">{label}</label>
          {mode === 'tags' ? (
            <TagInput
              value={tags}
              onChange={setTags}
              placeholder={placeholder}
            />
          ) : (
            <input
              ref={inputRef}
              type="text"
              className="input"
              placeholder={placeholder}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          )}
          {hint && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
              {hint}
            </div>
          )}
        </div>

        <div className="modal-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary btn-sm"
            disabled={mode !== 'tags' && !allowEmpty && !value.trim()}
          >
            Apply
          </button>
        </div>
      </form>
    </div>
  );
}
