interface StatusBadgeProps {
  status: string;
}

const statusLabels: Record<string, string> = {
  idle: 'Idle',
  running: 'Running',
  launching: 'Launching…',
  stopping: 'Stopping…',
  downloading: 'Downloading…',
  uploading: 'Uploading…',
  sync_failed: 'Sync Failed',
  error: 'Error',
};

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`status-badge ${status}`}>
      <span className="dot" />
      {statusLabels[status] || status}
    </span>
  );
}
