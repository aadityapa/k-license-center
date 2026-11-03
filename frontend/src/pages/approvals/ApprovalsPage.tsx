import { useEffect, useState } from 'react';
import { DataTable } from '../../components/DataTable';
import type { Column } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState, ErrorBanner } from '../../components/ErrorState';
import { Modal } from '../../components/Modal';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { RowDelete } from '../../components/RowDelete';
import { PendingBanner } from '../../components/PendingBanner';
import { changeRequestsApi } from '../../services/api/endpoints';
import type { ChangeRequestListParams } from '../../services/api/endpoints';
import { ApiError } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { useAuth } from '../../auth/AuthContext';
import { formatDateTime } from '../../utils/format';
import type { ChangeRequest, ChangeRequestDetail, ChangeRequestStatus } from '../../types';

type Scope = 'pending' | 'mine' | 'all';

const SCOPES: Array<{ key: Scope; label: string }> = [
  { key: 'pending', label: 'Pending' },
  { key: 'mine', label: 'My requests' },
  { key: 'all', label: 'All' },
];

const ENTITY_TYPES = [
  'CUSTOMER',
  'PRODUCT',
  'PLAN',
  'LICENSE',
  'ACTIVATION',
  'API_CLIENT',
  'USER',
  'ROLE',
  'SETTING',
];

/** Pretty-prints a payload/before snapshot for the reviewer's diff. */
function jsonText(value: Record<string, unknown> | null): string {
  if (value === null || value === undefined) return '—';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/* ------------------------------------------------------------------ */
/* Detail modal                                                        */
/* ------------------------------------------------------------------ */

interface DetailModalProps {
  requestId: number | null;
  onClose: () => void;
  /** Reload the list after a successful approve / reject / cancel. */
  onReviewed: () => void;
}

function RequestDetailModal({ requestId, onClose, onReviewed }: DetailModalProps) {
  const { user, hasPermission } = useAuth();
  const detail = useApi<ChangeRequestDetail | null>(
    () => (requestId === null ? Promise.resolve(null) : changeRequestsApi.get(requestId)),
    [requestId],
  );
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<ApiError | Error | null>(null);
  const [rejecting, setRejecting] = useState(false);

  // A fresh request clears whatever the previous one left behind.
  useEffect(() => {
    setActionError(null);
    setRejecting(false);
    setBusy(false);
  }, [requestId]);

  const cr = detail.data;
  const isOwn = cr != null && user != null && cr.requestedBy === user.userId;
  const isPending = cr?.status === 'PENDING';
  const canApprove = hasPermission('REQUEST_APPROVE') && isPending && !isOwn;
  const canCancel = hasPermission('REQUEST_SUBMIT') && isPending && isOwn;

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      onReviewed();
      onClose();
    } catch (err) {
      // 403 (own request) and 409 (already reviewed) arrive here with the
      // server's own wording — show it rather than inventing one.
      setActionError(err instanceof Error ? err : new Error('Action failed'));
      detail.reload();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Modal
        title={cr ? `Change Request #${cr.requestId}` : 'Change Request'}
        open={requestId !== null}
        onClose={onClose}
        size="lg"
      >
        {detail.loading && (
          <div className="fullpage-center h-40">
            <Spinner size={26} />
          </div>
        )}
        {detail.error && <ErrorBanner error={detail.error} />}
        <ErrorBanner error={actionError} />

        {cr && (
          <>
            <div className="def-grid">
              <div className="def-item">
                <div className="def-label">Summary</div>
                <div className="def-value">{cr.summary}</div>
              </div>
              <div className="def-item">
                <div className="def-label">Status</div>
                <div className="def-value">
                  <StatusBadge status={cr.status} />
                </div>
              </div>
              <div className="def-item">
                <div className="def-label">Entity</div>
                <div className="def-value">
                  {cr.entityType}
                  {cr.entityId != null && <span className="mono"> #{cr.entityId}</span>}
                </div>
              </div>
              <div className="def-item">
                <div className="def-label">Operation</div>
                <div className="def-value mono">{cr.operation}</div>
              </div>
              <div className="def-item">
                <div className="def-label">Requested by</div>
                <div className="def-value">
                  {cr.requestedByName ?? `User #${cr.requestedBy}`}
                  {isOwn && <span className="muted"> (you)</span>}
                </div>
              </div>
              <div className="def-item">
                <div className="def-label">Requested at</div>
                <div className="def-value">{formatDateTime(cr.requestedAt)}</div>
              </div>
              {cr.requestNote && (
                <div className="def-item">
                  <div className="def-label">Maker's note</div>
                  <div className="def-value">{cr.requestNote}</div>
                </div>
              )}
              {cr.reviewedBy != null && (
                <>
                  <div className="def-item">
                    <div className="def-label">Reviewed by</div>
                    <div className="def-value">{cr.reviewedByName ?? `User #${cr.reviewedBy}`}</div>
                  </div>
                  <div className="def-item">
                    <div className="def-label">Reviewed at</div>
                    <div className="def-value">{formatDateTime(cr.reviewedAt)}</div>
                  </div>
                </>
              )}
              {cr.reviewComment && (
                <div className="def-item">
                  <div className="def-label">Review comment</div>
                  <div className="def-value">{cr.reviewComment}</div>
                </div>
              )}
            </div>

            {cr.errorMessage && (
              <div className="alert alert-error mt-3">
                <Icon name="alert-circle" size={16} />
                <div>
                  <strong>Apply failed: </strong>
                  {cr.errorMessage}
                </div>
              </div>
            )}

            <div className="card-header px-0 pb-2 pt-[14px]">
              <h2>{cr.beforeState ? 'Before / Requested' : 'Requested change'}</h2>
            </div>
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

            {isOwn && isPending && hasPermission('REQUEST_APPROVE') && (
              <div className="alert alert-info mt-[14px]">
                <Icon name="info" size={16} />
                <div>You submitted this request, so another checker has to review it.</div>
              </div>
            )}

            <div className="form-actions">
              <button type="button" className="btn" onClick={onClose} disabled={busy}>
                Close
              </button>
              {canCancel && (
                <button
                  type="button"
                  className="btn btn-danger-outline"
                  disabled={busy}
                  onClick={() => void run(() => changeRequestsApi.cancel(cr.requestId))}
                >
                  {busy && <Spinner size={13} />}
                  <Icon name="ban" size={15} />
                  Cancel Request
                </button>
              )}
              {canApprove && (
                <>
                  <button
                    type="button"
                    className="btn btn-danger-outline"
                    disabled={busy}
                    onClick={() => setRejecting(true)}
                  >
                    <Icon name="close" size={15} />
                    Reject
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy}
                    onClick={() => void run(() => changeRequestsApi.approve(cr.requestId))}
                  >
                    {busy && <Spinner size={13} />}
                    <Icon name="check" size={15} />
                    Approve
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </Modal>

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
          await changeRequestsApi.reject(cr.requestId, reason);
          setRejecting(false);
          onReviewed();
          onClose();
        }}
        onClose={() => setRejecting(false)}
      />
    </>
  );
}

/* ------------------------------------------------------------------ */
/* List page                                                           */
/* ------------------------------------------------------------------ */

export function ApprovalsPage() {
  const list = useListState({ sort: 'requestId:desc' });
  const [scope, setScope] = useState<Scope>('pending');
  const [openId, setOpenId] = useState<number | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const { hasPermission } = useAuth();
  const canDelete = hasPermission('APPROVAL_BYPASS');

  const { setPage } = list;
  useEffect(() => {
    setPage(1);
  }, [scope, setPage]);

  const params: ChangeRequestListParams = {
    ...list.params,
    ...(scope === 'pending' ? { status: 'PENDING' as ChangeRequestStatus } : {}),
    ...(scope === 'mine' ? { mine: '1' as const } : {}),
  };
  // The list has no free-text search; keep the shared param bag honest.
  delete params.q;

  const { data, loading, error, reload } = useApi(
    () => changeRequestsApi.list(params),
    [list.depsKey, scope],
  );

  const rows = data?.items ?? [];

  const columns: Array<Column<ChangeRequest>> = [
    {
      key: 'requestId',
      header: 'Request #',
      sortable: true,
      width: 100,
      render: (r) => <span className="mono code-cell">#{r.requestId}</span>,
    },
    { key: 'summary', header: 'Summary', render: (r) => r.summary },
    {
      key: 'entityType',
      header: 'Entity',
      sortable: true,
      render: (r) => (
        <span className="icon-cell">
          <Icon name="package" size={13} />
          {r.entityType}
          {r.entityId != null && <span className="muted mono"> #{r.entityId}</span>}
        </span>
      ),
    },
    { key: 'operation', header: 'Operation', render: (r) => <span className="mono">{r.operation}</span> },
    {
      key: 'requestedByName',
      header: 'Requested by',
      render: (r) => r.requestedByName ?? `User #${r.requestedBy}`,
    },
    {
      key: 'requestedAt',
      header: 'Requested at',
      sortable: true,
      render: (r) => <span className="nowrap">{formatDateTime(r.requestedAt)}</span>,
    },
    { key: 'status', header: 'Status', sortable: true, render: (r) => <StatusBadge status={r.status} /> },
    ...(canDelete
      ? [
          {
            key: '_actions',
            header: 'Actions',
            align: 'right' as const,
            render: (r: ChangeRequest) =>
              r.status === 'PENDING' ? null : (
                <div className="row-actions">
                  <RowDelete
                    what={`change request #${r.requestId}`}
                    detail="Only the finished request record is removed; the change it made (if any) stays."
                    onDelete={() => {
                      setPending(null);
                      return changeRequestsApi.remove(r.requestId);
                    }}
                    onDeleted={reload}
                    onPending={setPending}
                  />
                </div>
              ),
          },
        ]
      : []),
  ];

  return (
    <div>
      <div className="overview-head">
        <div>
          <h1>Approvals</h1>
          <div className="subtitle">Changes submitted by makers, awaiting a checker</div>
        </div>
        <div className="head-meta">
          <span className="meta-item">
            Pending overall: <strong>{data?.pendingTotal ?? 0}</strong>
          </span>
          <button type="button" className="btn btn-sm" onClick={reload}>
            <Icon name="refresh" size={14} />
            Refresh
          </button>
        </div>
      </div>

      <PendingBanner message={pending} />

      <div className="tabs">
        {SCOPES.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`tab${scope === s.key ? ' active' : ''}`}
            onClick={() => setScope(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="card">
        <div className="adv-filter">
          <div className="filter-item">
            <label htmlFor="cr-entity">Entity type</label>
            <select
              id="cr-entity"
              className="input"
              value={list.state.filters['entityType'] ?? ''}
              onChange={(e) => list.setFilter('entityType', e.target.value)}
            >
              <option value="">All entities</option>
              {ENTITY_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          {scope !== 'pending' && (
            <div className="filter-item">
              <label htmlFor="cr-status">Status</label>
              <select
                id="cr-status"
                className="input"
                value={list.state.filters['status'] ?? ''}
                onChange={(e) => list.setFilter('status', e.target.value)}
              >
                <option value="">All statuses</option>
                <option value="PENDING">Pending</option>
                <option value="APPROVED">Approved</option>
                <option value="REJECTED">Rejected</option>
                <option value="CANCELLED">Cancelled</option>
                <option value="FAILED">Failed</option>
              </select>
            </div>
          )}
          {list.hasFilters && (
            <div className="adv-filter-right">
              <button type="button" className="btn btn-sm btn-ghost" onClick={list.clearFilters}>
                Clear
              </button>
            </div>
          )}
        </div>

        {error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(r) => r.requestId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              onRowClick={(r) => setOpenId(r.requestId)}
              emptyTitle="Nothing to review"
              emptyMessage={
                scope === 'mine'
                  ? 'You have not submitted any changes for approval.'
                  : 'Changes submitted by makers appear here.'
              }
            />
            <div className="table-foot">
              <span className="foot-count">
                Showing <strong>{rows.length}</strong> of <strong>{data?.total ?? 0}</strong>
              </span>
              <Pagination
                page={data?.page ?? list.state.page}
                pageSize={data?.pageSize ?? list.state.pageSize}
                total={data?.total ?? 0}
                onPageChange={list.setPage}
                onPageSizeChange={list.setPageSize}
              />
            </div>
          </>
        )}
      </div>

      <RequestDetailModal requestId={openId} onClose={() => setOpenId(null)} onReviewed={reload} />
    </div>
  );
}
