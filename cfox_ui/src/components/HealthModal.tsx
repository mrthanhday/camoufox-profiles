import type { HealthReport } from '../api';


interface HealthModalProps {
  report: HealthReport | null;
  profileName: string;
  onClose: () => void;
}

export function HealthModal({ report, profileName, onClose }: HealthModalProps) {
  if (!report) return null;

  const scoreColor =
    report.score >= 80 ? 'var(--green)' : report.score >= 50 ? 'var(--yellow)' : 'var(--red)';

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title">Health: {profileName}</h3>

        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div style={{ fontSize: 48, fontWeight: 700, color: scoreColor }}>
            {report.score}
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            {report.status === 'healthy' ? '✅ Healthy' :
             report.status === 'degraded' ? '⚠️ Degraded' : '❌ Unhealthy'}
          </div>
        </div>

        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Check</th>
                <th>Status</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {report.checks.map((c, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 500 }}>{c.name}</td>
                  <td>
                    <span className={`health-badge ${c.passed ? 'pass' : c.severity === 'warning' ? 'warn' : 'fail'}`}>
                      {c.passed ? '✓' : c.severity === 'warning' ? '⚠' : '✗'}
                    </span>
                  </td>
                  <td style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{c.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="modal-actions">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
