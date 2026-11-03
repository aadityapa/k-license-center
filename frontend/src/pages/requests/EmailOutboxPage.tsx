/**
 * Every outgoing message is written to the outbox before delivery is attempted,
 * so this screen is both the delivery log and — while SMTP is unconfigured —
 * the only place the invite links and keys can actually be read.
 *
 * Retry is honest: when SMTP is not configured the server answers SKIPPED with
 * `delivered: false`, and that is shown as a warning, never as "sent".
 */
import { useState } from 'react';
import { DataTable } from '../../components/DataTable';
import type { Column } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import { SearchInput } from '../../components/SearchInput';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState, ErrorBanner } from '../../components/ErrorState';
import { Modal } from '../../components/Modal';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { RowDelete } from '../../components/RowDelete';
import { PendingBanner } from '../../components/PendingBanner';
import { emailOutboxApi } from '../../services/api/endpoints';
import type { EmailOutboxListParams, EmailRetryResult } from '../../services/api/endpoints';
import { ApiError } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { useAuth } from '../../auth/AuthContext';
import { formatDateTime } from '../../utils/format';
import type { EmailOutboxItem, EmailStatus } from '../../types';

const STATUSES: EmailStatus[] = ['QUEUED', 'SENT', 'FAILED', 'SKIPPED'];

/** QUEUED and FAILED are the only states the server will re-attempt. */
function retryable(status: EmailStatus): boolean {
  return status === 'QUEUED' || status === 'FAILED';
}

function MessageModal({
  emailId,
  onClose,
  onRetried,
}: {
  emailId: number | null;
  onClose: () => void;
  onRetried: () => void;
}) {
  const { hasPermission } = useAuth();
  const detail = useApi<EmailOutboxItem | null>(
    () => (emailId === null ? Promise.resolve(null) : emailOutboxApi.get(emailId)),
    [emailId],
  );
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<EmailRetryResult | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);

  const m = detail.data;
  const canRetry = hasPermission('REQUEST_LICENSE_MANAGE');

  const retry = async () => {
    if (!m) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await emailOutboxApi.retry(m.emailId);
      setResult(res);
      detail.reload();
      onRetried();
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Retry failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={m ? `Message #${m.emailId}` : 'Message'}
      open={emailId !== null}
      onClose={onClose}
      size="lg"
    >
      {detail.loading && (
        <div className="fullpage-center h-40">
          <Spinner size={26} />
        </div>
      )}
      {detail.error && <ErrorBanner error={detail.error} />}
      <ErrorBanner error={error} />

      {/* The outcome is reported exactly as the server described it. */}
      {result && (
        <div
          className={`alert ${result.delivered ? 'alert-success' : 'alert-warning'}`}
          role="status"
        >
          <Icon name={result.delivered ? 'check' : 'alert-triangle'} size={16} />
          <div>
            <strong>{result.status}: </strong>
            {result.message}
          </div>
        </div>
      )}

      {m && (
        <>
          <div className="def-grid">
            <div className="def-item">
              <div className="def-label">To</div>
              <div className="def-value mono">{m.toAddress}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Status</div>
              <div className="def-value">
                <StatusBadge status={m.status} />
              </div>
            </div>
            <div className="def-item">
              <div className="def-label">Template</div>
              <div className="def-value mono">{m.template ?? '—'}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Attempts</div>
              <div className="def-value">{m.attempts ?? 0}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Created</div>
              <div className="def-value">{formatDateTime(m.createdAt)}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Sent</div>
              <div className="def-value">
                {m.sentAt ? formatDateTime(m.sentAt) : <span className="muted">—</span>}
              </div>
            </div>
            <div className="def-item">
              <div className="def-label">Related</div>
              <div className="def-value">
                {m.relatedType ? (
                  <>
                    {m.relatedType}
                    {m.relatedId != null && <span className="mono"> #{m.relatedId}</span>}
                  </>
                ) : (
                  <span className="muted">—</span>
                )}
              </div>
            </div>
          </div>

          {m.errorMessage && (
            <div className="alert alert-error mt-3">
              <Icon name="alert-circle" size={16} />
              <div>{m.errorMessage}</div>
            </div>
          )}

          <div className="card-header px-0 pb-2 pt-4">
            <h2>{m.subject}</h2>
          </div>
          <div className="json-block">
            <div className="json-title">Message body</div>
            <pre>{m.bodyText ?? ''}</pre>
          </div>

          <div className="form-actions">
            <button type="button" className="btn" onClick={onClose} disabled={busy}>
              Close
            </button>
            {canRetry && retryable(m.status) && (
              <button type="button" className="btn btn-primary" disabled={busy} onClick={retry}>
                {busy && <Spinner size={13} />}
                <Icon name="refresh" size={15} />
                Retry delivery
              </button>
            )}
          </div>
        </>
      )}
    </Modal>
  );
}

export function EmailOutboxPage() {
  const list = useListState({ sort: 'emailId:desc' });
  const { data, loading, error, reload } = useApi(
    () => emailOutboxApi.list(list.params as EmailOutboxListParams),
    [list.depsKey],
  );
  const [openId, setOpenId] = useState<number | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const { hasPermission } = useAuth();
  const canDelete =
    hasPermission('EMAIL_OUTBOX_VIEW') && (hasPermission('APPROVAL_BYPASS') || hasPermission('REQUEST_SUBMIT'));

  const rows = data?.items ?? [];

  const columns: Array<Column<EmailOutboxItem>> = [
    {
      key: 'emailId',
      header: '#',
      sortable: true,
      width: 80,
      render: (m) => <span className="mono code-cell">#{m.emailId}</span>,
    },
    {
      key: 'toAddress',
      header: 'To',
      sortable: true,
      render: (m) => <span className="mono">{m.toAddress}</span>,
    },
    { key: 'subject', header: 'Subject', render: (m) => m.subject },
    {
      key: 'template',
      header: 'Template',
      sortable: true,
      render: (m) => <span className="mono muted">{m.template ?? '—'}</span>,
    },
    { key: 'status', header: 'Status', sortable: true, render: (m) => <StatusBadge status={m.status} /> },
    {
      key: 'createdAt',
      header: 'Created',
      sortable: true,
      render: (m) => <span className="nowrap">{formatDateTime(m.createdAt)}</span>,
    },
    {
      key: 'sentAt',
      header: 'Sent',
      sortable: true,
      render: (m) =>
        m.sentAt ? <span className="nowrap">{formatDateTime(m.sentAt)}</span> : <span className="muted">—</span>,
    },
    ...(canDelete
      ? [
          {
            key: '_actions',
            header: 'Actions',
            align: 'right' as const,
            render: (m: EmailOutboxItem) => (
              <div className="row-actions">
                <RowDelete
                  what={`email #${m.emailId}`}
                  detail="Only the outbox record is removed."
                  onDelete={() => {
                    setPending(null);
                    return emailOutboxApi.remove(m.emailId);
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
          <h1>Email Outbox</h1>
          <div className="subtitle">Every message the system has composed, and what became of it</div>
        </div>
        <div className="head-meta">
          <button type="button" className="btn btn-sm" onClick={reload}>
            <Icon name="refresh" size={14} />
            Refresh
          </button>
        </div>
      </div>

      <PendingBanner message={pending} />

      <div className="card">
        <div className="adv-filter">
          <span className="adv-filter-label">Advanced Filtering</span>
          <SearchInput value={list.state.q} onChange={list.setQ} placeholder="Recipient or subject…" />
          <select
            className="input"
            aria-label="Status"
            value={list.state.filters['status'] ?? ''}
            onChange={(e) => list.setFilter('status', e.target.value)}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
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
              rowKey={(m) => m.emailId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              onRowClick={(m) => setOpenId(m.emailId)}
              emptyTitle="No messages"
              emptyMessage="Invitations, receipts and licence emails appear here as they are composed."
            />
            <div className="table-foot">
              <span className="foot-count">
                Total messages: <strong>{data?.total ?? 0}</strong>
                {rows.length > 0 && ` (showing ${rows.length})`}
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

      <MessageModal emailId={openId} onClose={() => setOpenId(null)} onRetried={reload} />
    </div>
  );
}
