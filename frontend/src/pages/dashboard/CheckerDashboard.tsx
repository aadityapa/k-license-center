/**
 * Checker — "Review Desk".
 *
 * Built as an inbox, not a dashboard: the queue is the page. Selecting a row
 * loads its diff into the reading pane beside it and the decision is taken
 * right there, so a checker never leaves this screen to do their job. There are
 * no unrelated panels below — reviewing is the whole role.
 */
import { useEffect, useState } from 'react';
import { Avatar } from '../../components/Viz';
import { Icon } from '../../components/Icon';
import { Spinner } from '../../components/Spinner';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorBanner } from '../../components/ErrorState';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { changeRequestsApi, dashboardApi } from '../../services/api/endpoints';
import { ApiError } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import { useAuth } from '../../auth/AuthContext';
import { useRoleIdentity } from '../../auth/useRoleIdentity';
import { formatDateTime } from '../../utils/format';
import type { ChangeRequestDetail, ChangeRequestPage, DashboardData } from '../../types';
import {
  CHIP_TONE, DashboardHead, EMPTY_PANEL, EMPTY_PANEL_ICON, STATUS_CHIP, dashboardGate, isToday, subtitleFor, waitingSince,
} from './shared';

interface CheckerPayload {
  /** Oldest-first pending queue — item 0 is the longest-waiting request. */
  pending: ChangeRequestPage;
  /** Newest-first slice of all requests, used to count today's decisions. */
  recent: ChangeRequestPage;
  dash: DashboardData;
}

const QUEUE_PAGE_SIZE = 100;

/** A request older than this is late; older than AMBER_HOURS it is merely warm. */
const AMBER_HOURS = 24;
const RED_HOURS = 48;

/** Pretty-prints a payload/before snapshot for the reviewer's diff. */
function jsonText(value: Record<string, unknown> | null): string {
  if (value === null || value === undefined) return '—';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Waiting-time pill: neutral, amber past 24h, red past 48h. */
const WAIT_BADGE = 'shrink-0 rounded-full border border-solid px-[7px] py-px text-xs font-bold tabular-nums';
const WAIT_NEUTRAL = 'border-line bg-surface-sunken text-muted';

function waitTone(hours: number): string {
  if (hours > RED_HOURS) return 'border-danger-border bg-danger-soft text-danger';
  if (hours > AMBER_HOURS) return 'border-warning-border bg-warning-soft text-warning';
  return WAIT_NEUTRAL;
}

/** One reading in the strip above the desk. */
const DESK_STAT = 'flex min-w-0 flex-[1_1_180px] flex-col border-0 border-r border-solid border-line px-4 py-3 last:border-r-0';
const DESK_STAT_VALUE = 'text-2xl font-bold leading-[1.05] tabular-nums';
const DESK_STAT_LABEL = 'mt-0.5 text-sm text-ink-2';
const DESK_STAT_HINT = 'mt-px truncate text-xs text-muted';

/** Small uppercase caption (reading-pane eyebrow, fact labels, sub-heads). */
const CAPTION = 'text-xs font-bold uppercase text-muted';

/** Glass panel behind the queue and the reading pane. */
const DESK_PANEL = 'rounded-md border border-solid border-line bg-surface [backdrop-filter:var(--glass-blur)]';

export function CheckerDashboard() {
  const { user } = useAuth();
  const role = useRoleIdentity();

  const { data, loading, error, reload } = useApi<CheckerPayload>(async () => {
    const [pending, recent, dash] = await Promise.all([
      changeRequestsApi.list({ status: 'PENDING', pageSize: QUEUE_PAGE_SIZE, sort: 'requestedAt:asc' }),
      changeRequestsApi.list({ pageSize: QUEUE_PAGE_SIZE, sort: 'requestId:desc' }),
      dashboardApi.get(),
    ]);
    return { pending, recent, dash };
  }, []);

  /** Requests decided in this sitting — removed from the queue without a refetch. */
  const [decided, setDecided] = useState<number[]>([]);
  const [decidedHere, setDecidedHere] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<ApiError | Error | null>(null);
  const [rejecting, setRejecting] = useState(false);

  const queue = (data?.pending.items ?? []).filter((r) => !decided.includes(r.requestId));
  const firstId = queue[0]?.requestId ?? null;
  const selectionValid = selectedId !== null && queue.some((r) => r.requestId === selectedId);

  // Nothing selected, or the selection just left the queue → fall to the next
  // (oldest) item, which is what a triage inbox does after you decide.
  useEffect(() => {
    if (!selectionValid) setSelectedId(firstId);
  }, [selectionValid, firstId]);

  useEffect(() => {
    setActionError(null);
    setRejecting(false);
  }, [selectedId]);

  const detail = useApi<ChangeRequestDetail | null>(
    () => (selectedId === null ? Promise.resolve(null) : changeRequestsApi.get(selectedId)),
    [selectedId],
  );

  const gate = dashboardGate(loading, error, reload);
  if (gate) return gate;
  if (!data) return null;

  // Awaiting count comes from the server's global pendingTotal, less whatever
  // this sitting has already cleared.
  const awaiting = Math.max(0, data.pending.pendingTotal - decided.length);

  // "Today" is counted from the newest page of requests we fetched, plus the
  // decisions taken on this screen. Say so when that page does not cover
  // every request in the system.
  const reviewed = data.recent.items;
  const recentTruncated = data.recent.total > reviewed.length;
  const decidedToday =
    reviewed.filter((r) => (r.status === 'APPROVED' || r.status === 'REJECTED') && isToday(r.reviewedAt))
      .length + decidedHere;
  const decidedHint = recentTruncated
    ? `All reviewers · last ${reviewed.length} requests`
    : 'All reviewers';

  const oldest = queue[0] ? waitingSince(queue[0].requestedAt) : null;

  const cr = detail.data;
  const isOwn = cr != null && user != null && cr.requestedBy === user.userId;
  const canDecide = cr != null && cr.status === 'PENDING' && !isOwn && !busy;

  /** Clears a request from the queue after the server accepted the decision. */
  const settle = (id: number) => {
    setDecided((prev) => (prev.includes(id) ? prev : [...prev, id]));
    setDecidedHere((n) => n + 1);
  };

  const approve = async (id: number) => {
    setBusy(true);
    setActionError(null);
    try {
      await changeRequestsApi.approve(id);
      settle(id);
    } catch (err) {
      // 403 (own request) and 409 (already reviewed) arrive with the server's
      // own wording — show it and resync rather than inventing a message.
      setActionError(err instanceof Error ? err : new Error('Approve failed'));
      setDecided([]);
      setDecidedHere(0);
      reload();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="review-desk">
      <DashboardHead title={role.workspace} subtitle={subtitleFor(user, role.purpose)}>
        <span className={`${STATUS_CHIP} ${awaiting > 0 ? CHIP_TONE.warn : CHIP_TONE.ok}`}>
          <Icon name={awaiting > 0 ? 'clipboard' : 'check'} size={13} />
          {awaiting > 0 ? `${awaiting} pending` : 'Queue clear'}
        </span>
      </DashboardHead>

      <div className="mb-4 flex flex-wrap overflow-hidden rounded border border-solid border-line bg-surface">
        <div className={DESK_STAT}>
          <span className={DESK_STAT_VALUE}>{awaiting}</span>
          <span className={DESK_STAT_LABEL}>Awaiting review</span>
          <span className={DESK_STAT_HINT}>Pending across all makers</span>
        </div>
        <div className={DESK_STAT}>
          <span className={`${DESK_STAT_VALUE}${oldest && oldest.hours > RED_HOURS ? ' text-danger' : ''}`}>
            {oldest ? oldest.label : '—'}
          </span>
          <span className={DESK_STAT_LABEL}>Oldest waiting</span>
          <span className={DESK_STAT_HINT}>
            {queue[0] ? `Submitted ${formatDateTime(queue[0].requestedAt)}` : 'Nothing is waiting'}
          </span>
        </div>
        <div className={DESK_STAT}>
          <span className={DESK_STAT_VALUE}>{decidedToday}</span>
          <span className={DESK_STAT_LABEL}>Decided today</span>
          <span className={DESK_STAT_HINT}>{decidedHint}</span>
        </div>
      </div>

      <div className="grid grid-cols-[minmax(300px,360px)_minmax(0,1fr)] items-start gap-4 max-[1000px]:grid-cols-[1fr]">
        <div className={`${DESK_PANEL} flex max-h-[calc(100vh-260px)] flex-col overflow-hidden max-[1000px]:max-h-[460px]`}>
          <div className="flex items-baseline justify-between gap-2 border-0 border-b border-solid border-line bg-surface-sunken px-4 py-3">
            <h2 className="text-md font-[650]">Queue</h2>
            <span className="muted text-xs">Oldest first</span>
          </div>

          {queue.length === 0 ? (
            <div className={EMPTY_PANEL}>
              <Icon name="check" size={24} className={EMPTY_PANEL_ICON} />
              <div className="empty-title">Queue clear</div>
              <div className="empty-hint">No change requests are waiting for review.</div>
            </div>
          ) : (
            <ul className="m-0 list-none overflow-y-auto p-0">
              {queue.map((r) => {
                const wait = waitingSince(r.requestedAt);
                const who = r.requestedByName ?? `User ${r.requestedBy}`;
                return (
                  <li key={r.requestId}>
                    <button
                      type="button"
                      className={`flex w-full cursor-pointer items-start gap-3 border-0 border-b border-l-[3px] border-solid border-b-line px-4 py-3 text-left text-inherit [font:inherit] transition-[background,border-color] duration-ui ease-ui focus-visible:shadow-focus ${
                        r.requestId === selectedId
                          ? 'border-l-primary bg-primary-soft'
                          : 'border-l-transparent bg-transparent hover:bg-surface-hover'
                      }`}
                      onClick={() => setSelectedId(r.requestId)}
                      aria-current={r.requestId === selectedId}
                    >
                      <Avatar name={who} size={30} />
                      <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
                        <span className="flex items-start justify-between gap-2">
                          <span className="line-clamp-2 min-w-0 text-base font-semibold leading-[1.35]">{r.summary}</span>
                          <span className={`${WAIT_BADGE} ${wait ? waitTone(wait.hours) : WAIT_NEUTRAL}`}>
                            {wait ? wait.label : '—'}
                          </span>
                        </span>
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="truncate text-sm text-ink-2">{who}</span>
                          <span className="shrink-0 rounded-full border border-solid border-line bg-surface-sunken px-1.5 py-px text-xs text-muted">
                            {r.entityType}
                            {r.entityId != null && <span className="mono"> #{r.entityId}</span>}
                          </span>
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className={`${DESK_PANEL} min-w-0 p-5 shadow-sm`}>
          <ErrorBanner error={actionError} />

          {detail.loading && (
            <div className="fullpage-center" style={{ height: 200 }}>
              <Spinner size={28} />
            </div>
          )}
          {detail.error && <ErrorBanner error={detail.error} />}

          {!detail.loading && !cr && (
            <div className={EMPTY_PANEL}>
              <Icon name="inbox" size={24} className={EMPTY_PANEL_ICON} />
              <div className="empty-title">Nothing selected</div>
              <div className="empty-hint">Pick a request from the queue to review it.</div>
            </div>
          )}

          {cr && (
            <>
              <div className="flex items-start justify-between gap-3 border-0 border-b border-solid border-line pb-3">
                <div>
                  <div className={`${CAPTION} tracking-[0.08em]`}>
                    Request <span className="mono">#{cr.requestId}</span>
                  </div>
                  <h2 className="mt-0.5 text-xl font-[650] tracking-[-0.01em]">{cr.summary}</h2>
                </div>
                <StatusBadge status={cr.status} />
              </div>

              <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3 py-4">
                <div className="flex min-w-0 flex-col gap-[3px]">
                  <span className={`${CAPTION} tracking-[0.07em]`}>Requested by</span>
                  <span className="flex min-w-0 items-center gap-1.5 text-base">
                    <Avatar name={cr.requestedByName ?? `User ${cr.requestedBy}`} size={22} />
                    {cr.requestedByName ?? `User #${cr.requestedBy}`}
                    {isOwn && <span className="muted"> (you)</span>}
                  </span>
                </div>
                <div className="flex min-w-0 flex-col gap-[3px]">
                  <span className={`${CAPTION} tracking-[0.07em]`}>Submitted</span>
                  <span className="flex min-w-0 items-center gap-1.5 text-base">{formatDateTime(cr.requestedAt)}</span>
                </div>
                <div className="flex min-w-0 flex-col gap-[3px]">
                  <span className={`${CAPTION} tracking-[0.07em]`}>Entity</span>
                  <span className="flex min-w-0 items-center gap-1.5 text-base">
                    {cr.entityType}
                    {cr.entityId != null && <span className="mono"> #{cr.entityId}</span>}
                  </span>
                </div>
                <div className="flex min-w-0 flex-col gap-[3px]">
                  <span className={`${CAPTION} tracking-[0.07em]`}>Operation</span>
                  <span className="flex min-w-0 items-center gap-1.5 text-base mono">{cr.operation}</span>
                </div>
              </div>

              {cr.requestNote && (
                <p className="m-0 mb-4 rounded-r border-0 border-l-[3px] border-solid border-primary bg-surface-sunken p-3 text-sm italic text-ink-2">
                  “{cr.requestNote}”
                </p>
              )}

              <div className={`${CAPTION} mb-2 tracking-[0.08em]`}>{cr.beforeState ? 'Before / Requested' : 'Requested change'}</div>
              <div className="json-diff">
                {cr.beforeState && (
                  <div className="json-block">
                    <div className="json-title">Before</div>
                    <pre>{jsonText(cr.beforeState)}</pre>
                  </div>
                )}
                <div className="json-block">
                  <div className="json-title">Requested</div>
                  <pre>{jsonText(cr.payload)}</pre>
                </div>
              </div>

              {isOwn && cr.status === 'PENDING' && (
                <div className="alert alert-info" style={{ marginTop: 14 }}>
                  <Icon name="info" size={16} />
                  <div>You submitted this request, so another checker has to review it.</div>
                </div>
              )}

              <div className="mt-5 flex justify-end gap-2 border-0 border-t border-solid border-line pt-4">
                <button
                  type="button"
                  className="btn btn-danger-outline"
                  disabled={!canDecide}
                  onClick={() => setRejecting(true)}
                >
                  <Icon name="close" size={15} />
                  Reject
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!canDecide}
                  onClick={() => void approve(cr.requestId)}
                >
                  {busy && <Spinner size={13} />}
                  <Icon name="check" size={15} />
                  Approve
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ConfirmDialog's requireReason already enforces the 3-character minimum
          the reject endpoint demands. */}
      <ConfirmDialog
        open={rejecting && cr !== null}
        title="Reject Change Request"
        danger
        requireReason
        reasonLabel="Rejection comment"
        message={
          <>
            Reject <strong>{cr?.summary}</strong>? Nothing is applied and the maker sees your comment.
          </>
        }
        confirmLabel="Reject"
        onConfirm={async (reason) => {
          if (!cr) return;
          try {
            await changeRequestsApi.reject(cr.requestId, reason);
          } catch (err) {
            // ConfirmDialog renders the server's message; resync the queue too.
            setDecided([]);
            setDecidedHere(0);
            reload();
            throw err;
          }
          setRejecting(false);
          settle(cr.requestId);
        }}
        onClose={() => setRejecting(false)}
      />
    </div>
  );
}
