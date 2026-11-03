import { useState } from 'react';
import { Icon } from './Icon';
import { ErrorBanner } from './ErrorState';
import { ConfirmDialog } from './ConfirmDialog';
import { clockAlertsApi } from '../services/api/endpoints';
import type { ClockAlert } from '../services/api/endpoints';
import { isPendingApproval } from '../services/api/http';
import { useApi } from '../hooks/useApi';
import { useAuth } from '../auth/AuthContext';
import { formatDateTime } from '../utils/format';

const STATE: Record<ClockAlert['state'], { label: string; cls: string }> = {
  BLOCKED: { label: 'Blocked — needs reactivation', cls: 'border-danger-border bg-danger-soft text-danger' },
  RELEASE_SENT: { label: 'Reactivation sent — waiting for the app', cls: 'border-warning-border bg-warning-soft text-warning' },
  REACTIVATED: { label: 'Reactivated', cls: 'border-success-border bg-success-soft text-success' },
  ALLOWED: { label: 'Date moved forward — still licensed', cls: 'border-info-border bg-info-soft text-info' },
};

function amount(seconds: number | null): string {
  if (seconds == null) return '';
  const s = Math.abs(seconds);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return [d ? `${d} day${d === 1 ? '' : 's'}` : '', h ? `${h} hr${h === 1 ? '' : 's'}` : '', !d && m ? `${m} min` : '']
    .filter(Boolean)
    .join(' ') || 'under a minute';
}

function what(a: ClockAlert): string {
  const by = amount(a.deltaSeconds);
  if (a.kind === 'MOVED_FORWARD') return `Date moved forward by ${by}`;
  if (a.kind === 'MOVED_BACK') return `Date set back by ${by}`;
  return `Clock ${by} behind the licence server`;
}

/**
 * Computers whose date/time was changed. Setting the date back blocks the
 * licence in the app until it is reactivated — by the user (Reactivate, checked
 * against the server's time) or here by Karnex.
 */
export function ClockAlertsPanel({ onPending }: { onPending?: (message: string) => void }) {
  const { hasPermission } = useAuth();
  const canReactivate = hasPermission('ACTIVATION_MANAGE');
  const { data, loading, error, reload } = useApi(() => clockAlertsApi.list(30), []);
  const [target, setTarget] = useState<ClockAlert | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const items = data?.items ?? [];
  if (loading && !data) return null;
  if (!error && items.length === 0) return null;
  const blocked = items.filter((i) => i.state === 'BLOCKED').length;

  return (
    <div className="card mb-4" id="clock-alerts">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <Icon name="clock" size={16} className={blocked ? 'text-danger' : 'text-primary'} />
          <h3 className="m-0 text-md">Date / time changes</h3>
          {blocked > 0 && (
            <span className="rounded-full bg-danger px-2 text-xs font-bold text-white">{blocked} blocked</span>
          )}
        </div>
        <span className="text-sm text-muted">Last 30 days · licence server time {data ? formatDateTime(data.serverTime) : ''}</span>
      </div>
      <div className="card-body p-0">
        {(error || done) && <div className="px-4 pt-4">
        <ErrorBanner error={error} />
        {done && (
          <div className="alert alert-success mb-3" role="status">
            <Icon name="check" size={16} />
            <div>{done}</div>
          </div>
        )}
        </div>}
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Computer</th>
                <th>Licence</th>
                <th>Change</th>
                <th>Computer time / server time</th>
                <th>Reported</th>
                <th>Status</th>
                {canReactivate && <th className="text-right">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.installationId}>
                  <td>
                    <div className="font-semibold">{a.deviceName ?? '—'}</div>
                    <div className="mono text-xs text-muted">{a.installationId}</div>
                  </td>
                  <td>
                    <div className={a.licenseNo ? 'mono' : 'text-muted'}>{a.licenseNo ?? 'Not licensed yet'}</div>
                    <div className="text-xs text-muted">
                      {a.customerName ?? ''} {a.productCode ? `· ${a.productCode}` : ''}
                    </div>
                  </td>
                  <td>{what(a)}</td>
                  <td className="text-sm">
                    <div>{a.localTime ? formatDateTime(a.localTime) : '—'}</div>
                    <div className="text-muted">{a.referenceTime ? formatDateTime(a.referenceTime) : '—'}</div>
                  </td>
                  <td className="text-sm">{formatDateTime(a.alertAt)}</td>
                  <td>
                    <span className={`inline-block rounded-full border border-solid px-2 py-0.5 text-xs font-semibold ${STATE[a.state].cls}`}>
                      {STATE[a.state].label}
                    </span>
                    {a.state === 'REACTIVATED' && a.reactivatedBy && (
                      <div className="mt-0.5 text-xs text-muted">
                        by {a.reactivatedBy}
                        {a.reactivatedAt ? ` · ${formatDateTime(a.reactivatedAt)}` : ''}
                      </div>
                    )}
                  </td>
                  {canReactivate && (
                    <td className="text-right">
                      {(a.state === 'BLOCKED') && a.productCode && (
                        <button type="button" className="btn btn-sm btn-primary" onClick={() => setTarget(a)}>
                          <Icon name="refresh" size={13} /> Reactivate
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <ConfirmDialog
        open={target !== null}
        title="Reactivate this computer"
        confirmLabel="Reactivate"
        requireReason
        reasonLabel="Note"
        message={
          <p className="mt-0">
            Reactivate <strong>{target?.productCode}</strong> on <strong>{target?.deviceName ?? target?.installationId}</strong>
            {target?.licenseNo ? <> (licence <span className="mono">{target.licenseNo}</span>)</> : null}? The app picks it up within
            seconds while it is open and connected, and then works with the computer's current date and time, even if
            that is not correct.
          </p>
        }
        onConfirm={async (note) => {
          if (!target) return;
          const res = await clockAlertsApi.reactivate(target.installationId, target.productCode ?? '', note);
          setTarget(null);
          if (isPendingApproval(res)) onPending?.(res.message);
          else setDone(`Reactivation sent to ${target.deviceName ?? target.installationId}. It is applied when the app next contacts the licence server.`);
          reload();
        }}
        onClose={() => setTarget(null)}
      />
    </div>
  );
}
