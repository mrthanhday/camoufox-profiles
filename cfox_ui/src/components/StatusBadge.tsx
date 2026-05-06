interface StatusBadgeProps {
  status: string;
}

const STATUS_LABELS: Record<string, string> = {
  idle: 'Idle',
  running: 'Running',
  launching: 'Launching',
  stopping: 'Stopping',
  downloading: 'Downloading',
  uploading: 'Uploading',
  error: 'Error',
  sync_failed: 'Sync Failed',
};

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`status-badge ${status}`}>
      <span className="dot" />
      {STATUS_LABELS[status] || status}
    </span>
  );
}
