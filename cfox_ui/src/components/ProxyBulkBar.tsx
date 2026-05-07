interface ProxyBulkBarProps {
  count: number;
  onCheckSelected: () => void;
  onDeleteSelected: () => void;
  onClearSelection: () => void;
  checking: boolean;
}

export function ProxyBulkBar({
  count,
  onCheckSelected,
  onDeleteSelected,
  onClearSelection,
  checking,
}: ProxyBulkBarProps) {
  if (count === 0) return null;

  return (
    <div className="bulk-bar">
      <span className="bulk-bar-count">{count} selected</span>
      <div className="bulk-bar-actions">
        <button className="btn btn-ghost btn-sm" onClick={onCheckSelected} disabled={checking}>
          {checking ? 'Checking...' : '[↻] Check'}
        </button>
        <button className="btn btn-danger btn-sm" onClick={onDeleteSelected}>
          [x] Delete
        </button>
      </div>
      <button
        className="bulk-bar-clear"
        onClick={onClearSelection}
        title="Clear selection"
      >
        [x]
      </button>
    </div>
  );
}
