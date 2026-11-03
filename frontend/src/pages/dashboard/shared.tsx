/**
 * Pieces shared by the four role dashboards.
 *
 * Every variant (admin / maker / checker / viewer) composes these rather than
 * repeating the markup, so the lifecycle pipeline, the integrity donut and the
 * recent-activity tables stay identical wherever they appear.
 */
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Donut } from '../../components/Viz';
import type { DonutSlice } from '../../components/Viz';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState } from '../../components/ErrorState';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import type { IconName } from '../../components/Icon';
import type { ApiError } from '../../services/api/http';
import { formatDate, formatDateTime, formatNumber, expiryLabel } from '../../utils/format';
import type { Activation, AuditLog, AuthUser, DashboardData, License } from '../../types';

/** Neon status ramp — readable on both the glass-dark and frosted-light themes. */
export const STATUS_CHART_COLORS: Record<string, string> = {
  ACTIVE: '#34d399',
  DRAFT: '#38bdf8',
  SUSPENDED: '#fbbf24',
  EXPIRED: '#fb923c',
  REVOKED: '#fb7185',
  CANCELLED: '#a78bfa',
};

/**
 * Rail colour for a change-request status, reusing the same ramp as the licence
 * statuses above so a PENDING request and a DRAFT licence read the same way.
 */
export const REQUEST_STATUS_COLORS: Record<string, string> = {
  PENDING: '#fbbf24',
  APPROVED: '#34d399',
  REJECTED: '#fb923c',
  CANCELLED: '#a78bfa',
  FAILED: '#fb7185',
};

export function requestStatusColor(status: string): string {
  return REQUEST_STATUS_COLORS[status] ?? '#64748b';
}

/**
 * Colour an audit action by what it means: destructive actions read red,
 * cautionary ones amber, creations green, everything else neutral.
 */
function auditTone(action: string): string {
  if (/REVOK|DELET|FAIL|LOCK/.test(action)) return 'badge-red';
  if (/SUSPEND|DEACTIVAT|REGENERAT|EXPIR/.test(action)) return 'badge-amber';
  if (/CREATED|ACTIVATED|RENEWED|GENERATED/.test(action)) return 'badge-green';
  return 'badge-grayblue';
}

/* ------------------------------------------------------------------ */
/* Shared class strings                                                */
/* ------------------------------------------------------------------ */

/** Pill in the dashboard header ("3 pending", "Queue clear"). */
export const STATUS_CHIP =
  'inline-flex items-center gap-1.5 rounded-full border border-solid px-3 py-1 text-xs font-bold uppercase tracking-[0.06em]';
export const CHIP_TONE = {
  ok: 'border-success-border bg-success-soft text-success',
  warn: 'border-warning-border bg-warning-soft text-warning',
  alert: 'border-danger-border bg-danger-soft text-danger',
} as const;

/** Dashed "nothing here" panel (maker feed, checker queue and reading pane). */
export const EMPTY_PANEL =
  'flex flex-col items-center gap-1 rounded-md border border-dashed border-line-strong px-4 py-10 text-center text-muted';
/** Icon at the top of an EMPTY_PANEL. */
export const EMPTY_PANEL_ICON = 'mb-2 text-muted';

/* ------------------------------------------------------------------ */
/* Small helpers                                                       */
/* ------------------------------------------------------------------ */

/**
 * "Karan Singh · Maker, Checker" from whatever the session actually carries.
 * Returns '' when the server sent neither a name nor roles — callers then omit
 * the line entirely rather than printing a made-up label.
 */
export function identityLine(user: AuthUser | null): string {
  const name = (user?.fullName ?? '').trim() || user?.username || '';
  const roles = (user?.roles ?? []).filter((r) => r && r.trim() !== '').join(', ');
  if (name && roles) return `${name} · ${roles}`;
  return name || roles;
}

/** Joins the identity line with a page description, skipping whichever is empty. */
export function subtitleFor(user: AuthUser | null, description: string): string {
  const who = identityLine(user);
  return who ? `${who} — ${description}` : description;
}

/** True when the timestamp falls on the viewer's current local calendar day. */
export function isToday(value?: string | null): boolean {
  if (!value) return false;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return false;
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
  );
}

/** Elapsed time since a timestamp, as hours plus a compact "3d 4h" label. */
export function waitingSince(value?: string | null): { hours: number; label: string } | null {
  if (!value) return null;
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return null;
  const ms = Math.max(0, Date.now() - then);
  const hours = ms / 3_600_000;
  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    return { hours, label: `${days}d ${Math.floor(hours % 24)}h` };
  }
  if (hours >= 1) return { hours, label: `${Math.floor(hours)}h` };
  return { hours, label: `${Math.max(1, Math.round(ms / 60_000))}m` };
}

/* ------------------------------------------------------------------ */
/* Loading / error gate                                                */
/* ------------------------------------------------------------------ */

/**
 * The spinner / error-card treatment every dashboard variant uses.
 * Returns null once the request has settled successfully.
 */
export function dashboardGate(
  loading: boolean,
  error: ApiError | null,
  reload: () => void,
): JSX.Element | null {
  if (loading) {
    return (
      <div className="fullpage-center" style={{ height: '60vh' }}>
        <Spinner size={32} />
      </div>
    );
  }
  if (error) {
    return (
      <div className="card">
        <ErrorState error={error} onRetry={reload} />
      </div>
    );
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Header                                                              */
/* ------------------------------------------------------------------ */

interface DashboardHeadProps {
  title: string;
  subtitle: string;
  /** Status chips rendered on the right of the header. */
  children?: ReactNode;
}

export function DashboardHead({ title, subtitle, children }: DashboardHeadProps) {
  return (
    <div className="overview-head">
      <div>
        <h1>{title}</h1>
        <div className="subtitle">{subtitle}</div>
      </div>
      {children && <div className="flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Lifecycle pipeline                                                  */
/* ------------------------------------------------------------------ */

/**
 * Lifecycle stages, in the order a licence actually moves through them.
 * SUSPENDED and REVOKED are terminal branches, not later stages — marked apart.
 */
export function LifecyclePipeline({ totals }: { totals: DashboardData['totals'] }) {
  const stages: Array<{ label: string; value: number; color: string; icon: IconName }> = [
    { label: 'Active', value: totals.activeLicenses, color: '#34d399', icon: 'check' },
    { label: 'Expiring Soon', value: totals.expiringSoon, color: '#fbbf24', icon: 'clock' },
    { label: 'Expired', value: totals.expiredLicenses, color: '#fb923c', icon: 'alert-triangle' },
    { label: 'Suspended', value: totals.suspendedLicenses, color: '#c084fc', icon: 'pause' },
    { label: 'Revoked', value: totals.revokedLicenses, color: '#fb7185', icon: 'ban' },
  ];

  return (
    <div className="mb-4 flex items-stretch gap-1.5 overflow-x-auto pb-0.5">
      <div className="flex min-w-[132px] flex-none flex-col justify-center rounded-md border border-solid border-primary-border bg-[linear-gradient(150deg,rgba(34,211,238,0.14),var(--glass-solid)_70%)] px-4 py-3 shadow-[inset_0_1px_0_var(--glass-edge-top)]">
        <div>Total Licences</div>
        <div className="mt-0.5 text-2xl font-bold leading-[1.1] tracking-[-0.03em] text-primary">{formatNumber(totals.licenses)}</div>
      </div>
      {stages.map((stage, i) => (
        <div
          key={stage.label}
          className={`pipeline-stage${i >= 3 ? ' opacity-[0.82]' : ''}`}
          style={{ ['--stage' as string]: stage.color }}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-2xs font-bold uppercase tracking-[0.09em] text-muted">{stage.label}</span>
            <Icon name={stage.icon} size={13} />
          </div>
          <div className="mt-0.5 text-2xl font-bold leading-[1.15] tracking-[-0.03em] [text-shadow:0_0_22px_currentColor]">
            {formatNumber(stage.value)}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Licensing integrity donut                                           */
/* ------------------------------------------------------------------ */

interface IntegrityDonutProps {
  data: DashboardData;
  /** Extra rows rendered under the donut (the checker's key totals). */
  children?: ReactNode;
}

export function IntegrityDonut({ data, children }: IntegrityDonutProps) {
  const slices: DonutSlice[] = (data.licensesByStatus ?? []).map((s) => ({
    label: s.status,
    value: s.count,
    color: STATUS_CHART_COLORS[s.status] ?? '#64748b',
  }));

  return (
    <div className="card">
      <div className="card-header">
        <h2>Licensing Integrity</h2>
      </div>
      <div className="card-body">
        {slices.length === 0 ? (
          <div className="table-empty">No license data yet.</div>
        ) : (
          <div className="flex flex-wrap items-center justify-center gap-6 py-2">
            <Donut
              slices={slices}
              centerValue={formatNumber(data.totals.licenses)}
              centerLabel="Total licenses"
            />
            <ul className="m-0 min-w-[168px] list-none p-0">
              {slices.map((s) => (
                <li key={s.label} className="flex items-center gap-2 py-[5px] text-base">
                  <span
                    className="h-[9px] w-[9px] shrink-0 rounded-[50%]"
                    style={{ background: s.color, boxShadow: `0 0 8px ${s.color}` }}
                  />
                  <span className="flex-1 text-ink-2">{s.label.charAt(0) + s.label.slice(1).toLowerCase()}</span>
                  <span className="font-bold tabular-nums">{formatNumber(s.value)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Recent-activity tables                                              */
/* ------------------------------------------------------------------ */

export function RecentLicencesTable({ rows }: { rows: License[] }) {
  return (
    <div className="card">
      <div className="card-header">
        <h2>Recent Licenses</h2>
        <Link to="/licenses" className="btn-link">
          View all
        </Link>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>License</th>
              <th>Customer</th>
              <th>Product</th>
              <th>Status</th>
              <th>Expiry</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={5}>
                  <div className="table-empty">No licenses yet.</div>
                </td>
              </tr>
            )}
            {rows.map((l) => (
              <tr key={l.licenseId}>
                <td>
                  <Link to={`/licenses/${l.licenseId}`} className="mono">
                    {l.licenseNo}
                  </Link>
                </td>
                <td>{l.customerName ?? l.customerId}</td>
                <td>{l.productName ?? l.productCode}</td>
                <td>
                  <StatusBadge status={l.status} />
                </td>
                <td className="nowrap">{expiryLabel(l.expiryDate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RecentActivationsTable({ rows }: { rows: Activation[] }) {
  return (
    <div className="card">
      <div className="card-header">
        <h2>Recent Activations</h2>
        <Link to="/activations" className="btn-link">
          View all
        </Link>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>License</th>
              <th>Device</th>
              <th>Product</th>
              <th>Activated</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={4}>
                  <div className="table-empty">No activations yet.</div>
                </td>
              </tr>
            )}
            {rows.map((a) => (
              <tr key={a.activationId}>
                <td>
                  <Link to={`/licenses/${a.licenseId}`} className="mono">
                    {a.licenseNo ?? a.licenseId}
                  </Link>
                </td>
                <td>{a.deviceName ?? a.installationId}</td>
                <td>{a.productName ?? a.productCode}</td>
                <td className="nowrap">{formatDateTime(a.activatedAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RecentAuditTable({ rows }: { rows: AuditLog[] }) {
  return (
    <div className="card">
      <div className="card-header">
        <h2>Recent Audit Events</h2>
        <Link to="/audit-logs" className="btn-link">
          View all
        </Link>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Action</th>
              <th>Entity</th>
              <th>Actor</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={4}>
                  <div className="table-empty">No audit events.</div>
                </td>
              </tr>
            )}
            {rows.map((a) => (
              <tr key={a.auditId}>
                <td>
                  <span className={`badge badge-plain ${auditTone(a.action)}`}>{a.action}</span>
                </td>
                <td>
                  {a.entityType} {a.entityId != null && <span className="muted">#{a.entityId}</span>}
                </td>
                <td>{a.actor}</td>
                <td className="nowrap">{formatDate(a.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
