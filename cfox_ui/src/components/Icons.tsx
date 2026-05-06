/**
 * Inline SVG icons for OS and Source columns.
 * Monochrome, 16×16, matching the monospace theme.
 */

// ── OS Icons ─────────────────────────────────────────────────

function WindowsIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style={{ opacity: 0.7 }}>
      <path d="M0 2.3l6.5-.9v6.3H0V2.3zm7.3-1l8.7-1.3v7.7H7.3V1.3zM16 8.7v7.6l-8.7-1.2V8.7H16zM6.5 15l-6.5-.9V8.7h6.5V15z" />
    </svg>
  );
}

function MacIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style={{ opacity: 0.7 }}>
      <path d="M12.2 4.2c-.7.8-1 1.7-1 2.7 0 1.2.5 2.1 1.4 2.8-.3.9-.8 1.8-1.4 2.6-.8 1.1-1.6 1.7-2.5 1.7-.5 0-1.1-.2-1.8-.5-.6-.3-1.2-.4-1.6-.4-.5 0-1 .2-1.6.5-.7.3-1.2.5-1.6.5-1 0-2-1-2.9-2.8C.4 9.8 0 8.2 0 6.8c0-1.4.4-2.5 1.1-3.4.8-.9 1.7-1.4 2.9-1.4.6 0 1.3.2 2 .6.6.3 1 .5 1.2.5.3 0 .7-.2 1.4-.5.8-.4 1.5-.6 2.1-.6 1.3.1 2.3.7 2.9 1.7-.5.3-.9.6-1.2 1.1l-.2.4zM10 0c0 .8-.3 1.5-.8 2.2-.6.8-1.3 1.2-2.2 1.3 0-.1 0-.2 0-.3 0-.7.3-1.5.8-2.1C8.4.4 9.2 0 10 0z" />
    </svg>
  );
}

function LinuxIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style={{ opacity: 0.7 }}>
      <path d="M8 0C5.2 0 4 3.1 4 5.5c0 1.5.5 2.8.5 4-.3.3-.8.6-1.5 1.1-1 .7-1.5 1.3-1.5 2.2 0 .3.1.5.3.7.5.5 1.3.5 2.5.5h7.4c1.2 0 2-.1 2.5-.5.2-.2.3-.4.3-.7 0-.9-.5-1.5-1.5-2.2-.7-.5-1.2-.8-1.5-1.1 0-1.2.5-2.5.5-4C12 3.1 10.8 0 8 0zm-1.5 4c.3 0 .5.2.5.5s-.2.5-.5.5-.5-.2-.5-.5.2-.5.5-.5zm3 0c.3 0 .5.2.5.5s-.2.5-.5.5-.5-.2-.5-.5.2-.5.5-.5zM6.5 7h3c0 .5-.7 1-1.5 1s-1.5-.5-1.5-1z" />
    </svg>
  );
}

export function OsIcon({ os }: { os: string }) {
  const title = os === 'windows' ? 'Windows' : os === 'macos' ? 'macOS' : 'Linux';
  return (
    <span className="cell-icon" title={title}>
      {os === 'windows' ? <WindowsIcon /> : os === 'macos' ? <MacIcon /> : <LinuxIcon />}
    </span>
  );
}

// ── Source Icons ─────────────────────────────────────────────

function LocalIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style={{ opacity: 0.7 }}>
      <path d="M2 2h12v8H2V2zm0-1a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h5v2H5v1h6v-1H9v-2h5a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H2z" />
    </svg>
  );
}

function CloudIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style={{ opacity: 0.7 }}>
      <path d="M4.5 13h7a3.5 3.5 0 0 0 .5-6.97A5 5 0 0 0 2.1 8.03 3 3 0 0 0 4.5 13zM12 7a4 4 0 0 0-7.9-.87A2 2 0 0 0 4.5 10h7a2.5 2.5 0 0 0 .5-4.95V7z" />
    </svg>
  );
}

export function SourceIcon({ source }: { source: string }) {
  const isCloud = source === 'cloud';
  return (
    <span className={`cell-icon source-icon ${source}`} title={isCloud ? 'Cloud' : 'Local'}>
      {isCloud ? <CloudIcon /> : <LocalIcon />}
    </span>
  );
}
