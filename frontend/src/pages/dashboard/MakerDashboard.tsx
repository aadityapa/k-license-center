/**
 * Maker — "My Workspace".
 *
 * Deliberately not a metrics dashboard. A maker's day is: start something, then
 * find out what a checker did with it. So the page is an action bar over a
 * vertical feed of their own submissions, with a narrow rail of counts beside it.
 * Nothing here can approve anything — a maker holds REQUEST_SUBMIT, not
 * REQUEST_APPROVE.
 */
import { Link } from 'react-router-dom';
import { StatusBadge } from '../../components/StatusBadge';
import { Icon } from '../../components/Icon';
import { changeRequestsApi, dashboardApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useAuth } from '../../auth/AuthContext';
import { useRoleIdentity } from '../../auth/useRoleIdentity';
import { formatDateTime, formatNumber } from '../../utils/format';
import type { ChangeRequest, ChangeRequestPage, DashboardData } from '../../types';
import {
  CHIP_TONE, DashboardHead, EMPTY_PANEL, EMPTY_PANEL_ICON, STATUS_CHIP, dashboardGate, requestStatusColor, subtitleFor, waitingSince,
} from './shared';

interface MakerPayload {
  dash: DashboardData;
  mine: ChangeRequestPage;
}

/** The most recent page of a maker's own submissions; 100 is the server's cap. */
const MINE_PAGE_SIZE = 100;

/** How many feed entries are rendered before the "view all" link takes over. */
const FEED_LIMIT = 12;

/** A "Start something" tile; the first (New Licence) is tinted with the accent. */
const START_ACTION =
  'flex flex-[1_1_200px] items-center gap-3 rounded-md border border-solid p-4 text-ink no-underline ' +
  'transition-[transform,border-color,box-shadow] duration-ui ease-ui ' +
  'hover:-translate-y-[2px] hover:border-primary-border hover:no-underline hover:shadow-glow focus-visible:shadow-focus';
const START_ACTION_PLAIN = `${START_ACTION} border-line-strong bg-surface-raised`;
const START_ACTION_PRIMARY = `${START_ACTION} border-primary-border bg-[linear-gradient(140deg,var(--primary-soft),var(--surface-raised))]`;

/** Small pill in a feed entry's meta line. */
const FEED_CHIP =
  'inline-flex items-center gap-1 rounded-full border border-solid border-line bg-surface-sunken px-[7px] py-0.5 text-xs text-ink-2';

/** A reviewer's verdict (or an apply failure) under a feed entry. */
const VERDICT = 'mt-3 flex gap-2 rounded border border-solid p-3 text-sm leading-[1.5]';
const VERDICT_OK = `${VERDICT} border-line bg-surface-sunken`;
const VERDICT_REJECT = `${VERDICT} border-danger-border bg-danger-soft`;

/** Counts and estate rows in the right-hand rail. */
const KV_ROW = 'flex items-center gap-2 border-0 border-b border-solid border-line py-1.5 text-sm last:border-b-0';

/* ------------------------------------------------------------------ */
/* Feed entry                                                          */
/* ------------------------------------------------------------------ */

function FeedEntry({ r }: { r: ChangeRequest }) {
  const wait = waitingSince(r.requestedAt);
  const rejected = r.status === 'REJECTED';
  const failed = r.status === 'FAILED';

  return (
    <li
      className={`flex min-w-0 overflow-hidden rounded-md border border-solid bg-surface [backdrop-filter:var(--glass-blur)] ${
        rejected || failed ? 'border-danger-border' : 'border-line'
      }`}
      style={{ ['--rail' as string]: requestStatusColor(r.status) }}
    >
      <span className="w-1 shrink-0 bg-[color:var(--rail,var(--border-strong))]" aria-hidden />
      <div className="min-w-0 flex-1 p-4">
        <div className="flex items-start justify-between gap-3">
          <h3 className="m-0 min-w-0 text-md font-semibold leading-[1.4]">{r.summary}</h3>
          <StatusBadge status={r.status} />
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
          <span className={FEED_CHIP}>
            <Icon name="package" size={12} />
            {r.entityType}
            {r.entityId != null && <span className="mono"> #{r.entityId}</span>}
          </span>
          <span className={`${FEED_CHIP} mono`}>{r.operation}</span>
          <span className="text-muted">
            Submitted {formatDateTime(r.requestedAt)}
            {r.status === 'PENDING' && wait && ` · waiting ${wait.label}`}
          </span>
        </div>

        {r.requestNote && <p className="m-0 mt-2 text-sm italic text-ink-2">“{r.requestNote}”</p>}

        {/* The reviewer's verdict is the whole point of this feed, so a rejection
            comment is a block of its own rather than a muted second line. */}
        {r.reviewComment && (
          <div className={rejected ? VERDICT_REJECT : VERDICT_OK}>
            <Icon name={rejected ? 'close' : 'check'} size={14} className={`mt-px shrink-0 ${rejected ? 'text-danger' : 'text-success'}`} />
            <div className="flex min-w-0 flex-col gap-0.5">
              <strong className={`font-[650] ${rejected ? 'text-danger' : 'text-ink-2'}`}>
                {rejected ? 'Rejected' : 'Reviewer'}
                {r.reviewedByName ? ` by ${r.reviewedByName}` : ''}
                {r.reviewedAt ? ` · ${formatDateTime(r.reviewedAt)}` : ''}
              </strong>
              <span>{r.reviewComment}</span>
            </div>
          </div>
        )}

        {!r.reviewComment && r.errorMessage && (
          <div className={VERDICT_REJECT}>
            <Icon name="alert-circle" size={14} className="mt-px shrink-0 text-danger" />
            <div className="flex min-w-0 flex-col gap-0.5">
              <strong className="font-[650] text-danger">Apply failed</strong>
              <span>{r.errorMessage}</span>
            </div>
          </div>
        )}
      </div>
    </li>
  );
}

/* ------------------------------------------------------------------ */

export function MakerDashboard() {
  const { user, hasPermission } = useAuth();
  const role = useRoleIdentity();

  const { data, loading, error, reload } = useApi<MakerPayload>(async () => {
    const [dash, mine] = await Promise.all([
      dashboardApi.get(),
      changeRequestsApi.list({ mine: '1', pageSize: MINE_PAGE_SIZE, sort: 'requestId:desc' }),
    ]);
    return { dash, mine };
  }, []);

  const gate = dashboardGate(loading, error, reload);
  if (gate) return gate;
  if (!data) return null;

  const rows = data.mine.items;
  const pendingCount = rows.filter((r) => r.status === 'PENDING').length;
  const approvedCount = rows.filter((r) => r.status === 'APPROVED').length;
  const rejectedCount = rows.filter((r) => r.status === 'REJECTED').length;

  // The counts above are computed over the page we actually fetched. Say so
  // whenever the maker has submitted more than that page holds.
  const truncated = data.mine.total > rows.length;
  const scopeHint = truncated
    ? `of your ${rows.length} most recent submissions`
    : 'of all your submissions';

  const canCreateLicence = hasPermission('LICENSE_CREATE');
  const canManageCustomers = hasPermission('CUSTOMER_MANAGE');
  const canManageProducts = hasPermission('PRODUCT_MANAGE');
  const showStartBar = canCreateLicence || canManageCustomers || canManageProducts;

  const t = data.dash.totals;

  const tallies: Array<{ label: string; value: number; status: string }> = [
    { label: 'Waiting on a checker', value: pendingCount, status: 'PENDING' },
    { label: 'Approved', value: approvedCount, status: 'APPROVED' },
    { label: 'Rejected', value: rejectedCount, status: 'REJECTED' },
  ];

  return (
    <div className="maker-workspace">
      <DashboardHead title={role.workspace} subtitle={subtitleFor(user, role.purpose)}>
        {pendingCount > 0 && (
          <span className={`${STATUS_CHIP} ${CHIP_TONE.warn}`}>
            <Icon name="clock" size={13} />
            {pendingCount} awaiting a checker
          </span>
        )}
        {rejectedCount > 0 && (
          <span className={`${STATUS_CHIP} ${CHIP_TONE.alert}`}>
            <Icon name="alert-circle" size={13} />
            {rejectedCount} rejected
          </span>
        )}
      </DashboardHead>

      {showStartBar && (
        <div className="mb-5 flex flex-wrap items-center gap-6 rounded-lg border border-solid border-primary-border bg-surface bg-[linear-gradient(120deg,var(--primary-soft),transparent_70%)] p-5 shadow-sm [backdrop-filter:var(--glass-blur)]">
          <div className="min-w-[150px]">
            <div className="text-lg font-bold tracking-[-0.01em]">Start something</div>
            <div className="mt-0.5 text-sm text-ink-2">Every change goes to a checker before it applies</div>
          </div>
          <div className="flex flex-1 flex-wrap gap-3">
            {canCreateLicence && (
              <Link to="/licenses?new=1" className={START_ACTION_PRIMARY}>
                <Icon name="file-text" size={20} className="shrink-0 text-primary" />
                <span className="flex min-w-0 flex-col">
                  <strong className="text-md font-[650]">New Licence</strong>
                  <em className="text-sm not-italic text-muted">Issue a key for a customer</em>
                </span>
              </Link>
            )}
            {canManageCustomers && (
              <Link to="/customers?new=1" className={START_ACTION_PLAIN}>
                <Icon name="users" size={20} className="shrink-0 text-primary" />
                <span className="flex min-w-0 flex-col">
                  <strong className="text-md font-[650]">New Customer</strong>
                  <em className="text-sm not-italic text-muted">Register an organisation</em>
                </span>
              </Link>
            )}
            {canManageProducts && (
              <Link to="/products?new=1" className={START_ACTION_PLAIN}>
                <Icon name="package" size={20} className="shrink-0 text-primary" />
                <span className="flex min-w-0 flex-col">
                  <strong className="text-md font-[650]">New Product</strong>
                  <em className="text-sm not-italic text-muted">Add a licensable product</em>
                </span>
              </Link>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)_260px] items-start gap-5 max-[1000px]:grid-cols-[1fr]">
        <section className="maker-feed">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 className="text-lg font-[650] tracking-[-0.01em]">My submissions</h2>
            <Link to="/approvals" className="btn-link">
              View all
            </Link>
          </div>

          {rows.length === 0 ? (
            <div className={EMPTY_PANEL}>
              <Icon name="inbox" size={26} className={EMPTY_PANEL_ICON} />
              <div className="empty-title">Nothing submitted yet</div>
              <div className="empty-hint">
                Changes you make are queued here until a checker reviews them.
              </div>
            </div>
          ) : (
            <>
              <ol className="m-0 flex list-none flex-col gap-3 p-0">
                {rows.slice(0, FEED_LIMIT).map((r) => (
                  <FeedEntry key={r.requestId} r={r} />
                ))}
              </ol>
              <div className="mt-3 text-sm text-muted">
                Showing <strong>{Math.min(rows.length, FEED_LIMIT)}</strong> of{' '}
                <strong>{data.mine.total}</strong> submissions
              </div>
            </>
          )}
        </section>

        <aside className="flex flex-col gap-3">
          <div className="flex flex-col gap-2">
            {tallies.map((c) => (
              <div
                key={c.status}
                className="flex flex-col rounded border border-l-[3px] border-solid border-line border-l-[color:var(--rail,var(--border-strong))] bg-surface px-4 py-3"
                style={{ ['--rail' as string]: requestStatusColor(c.status) }}
              >
                <span className="text-2xl font-bold leading-[1.05] tabular-nums">{formatNumber(c.value)}</span>
                <span className="mt-0.5 text-sm text-ink-2">{c.label}</span>
                <span className="mt-px text-xs text-muted">{scopeHint}</span>
              </div>
            ))}
          </div>

          <div className="rounded border border-solid border-line bg-surface p-4">
            <div className="text-xs font-bold uppercase tracking-[0.09em] text-muted">Estate I work on</div>
            <ul className="m-0 mt-2 list-none p-0">
              <li className={KV_ROW}>
                <span className="min-w-0 flex-1 text-ink-2">Total licences</span>
                <span className="font-bold tabular-nums">{formatNumber(t.licenses)}</span>
              </li>
              <li className={KV_ROW}>
                <span className="min-w-0 flex-1 text-ink-2">Active</span>
                <span className="font-bold tabular-nums">{formatNumber(t.activeLicenses)}</span>
              </li>
              <li className={KV_ROW}>
                <span className="min-w-0 flex-1 text-ink-2">Expiring in 30 days</span>
                <span className="font-bold tabular-nums">{formatNumber(t.expiringSoon)}</span>
              </li>
              <li className={KV_ROW}>
                <span className="min-w-0 flex-1 text-ink-2">Customers</span>
                <span className="font-bold tabular-nums">{formatNumber(t.customers)}</span>
              </li>
              <li className={KV_ROW}>
                <span className="min-w-0 flex-1 text-ink-2">Products</span>
                <span className="font-bold tabular-nums">{formatNumber(t.products)}</span>
              </li>
            </ul>
          </div>
        </aside>
      </div>
    </div>
  );
}
