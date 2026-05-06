import { useEffect, useRef } from 'react';

interface ConfirmModalProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  danger = false,
  onConfirm,
  onClose,
}: ConfirmModalProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  // Focus confirm button on open
  useEffect(() => {
    if (open) {
      setTimeout(() => confirmRef.current?.focus(), 50);
    }
  }, [open]);

  if (!open) return null;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose} onKeyDown={handleKeyDown}>
      <div
        className="modal"
        style={{ maxWidth: 360 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-title">{title}</div>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          {message}
        </p>
        <div className="modal-actions">
          <button
            className="btn btn-ghost btn-sm"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            ref={confirmRef}
            className={`btn btn-sm ${danger ? 'btn-danger-outline' : 'btn-primary'}`}
            onClick={() => { onConfirm(); onClose(); }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
