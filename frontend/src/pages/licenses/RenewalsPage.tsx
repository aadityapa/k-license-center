import { useState } from 'react';
import { Link } from 'react-router-dom';
import { DataTable } from '../../components/DataTable';
import type { Column } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import { SearchInput } from '../../components/SearchInput';
import { ErrorState } from '../../components/ErrorState';
import { Icon } from '../../components/Icon';
import { RowDelete } from '../../components/RowDelete';
import { PendingBanner } from '../../components/PendingBanner';
import { Avatar } from '../../components/Viz';
import { productsApi, renewalsApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { useAuth } from '../../auth/AuthContext';
import { formatCurrency, formatDate } from '../../utils/format';
import type { Renewal } from '../../types';

/** Validity of the expiry the renewal produced, relative to today. */
function expiryTone(iso?: string | null): { label: string; tone: string } {
  if (!iso) return { label: 'Lifetime', tone: 'badge-grayblue' };
  const days = Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return { label: 'Expired', tone: 'badge-red' };
  if (days <= 30) return { label: 'Due soon', tone: 'badge-amber' };
  return { label: 'Valid', tone: 'badge-green' };
}

export function RenewalsPage() {
  const list = useListState({ sort: 'renewalDate:desc' });
  const { data, loading, error, reload } = useApi(() => renewalsApi.list(list.params), [list.depsKey]);
  const products = useApi(() => productsApi.list({ pageSize: 100 }), []);
  const summary = data?.summary;
  const { hasPermission } = useAuth();
  const [pending, setPending] = useState<string | null>(null);

  const columns: Array<Column<Renewal>> = [
    {
      key: 'renewalDate',
      header: 'Date',
      sortable: true,
      render: (r) => <span className="nowrap">{formatDate(r.renewalDate)}</span>,
    },
    {
      key: 'licenseNo',
      header: 'License',
      render: (r) => (
        <Link to={`/licenses/${r.licenseId}`} className="mono code-cell">
          {r.licenseNo ?? `#${r.licenseId}`}
        </Link>
      ),
    },
    {
      key: 'customerName',
      header: 'Customer',
      render: (r) => (
        <span className="name-cell">
          <Avatar name={String(r.customerName ?? '?')} size={24} />
          <span>{r.customerName ?? '—'}</span>
        </span>
      ),
    },
    { key: 'productName', header: 'Product' },
    {
      key: 'newPlanName',
      header: 'Plan',
      render: (r) =>
        r.prevPlanId && r.newPlanId && r.prevPlanId !== r.newPlanId ? (
          <span className="icon-cell">
            <span className="muted">{r.prevPlanName ?? r.prevPlanId}</span>
            <Icon name="chevron-right" size={12} />
            <span className="badge badge-grayblue badge-plain">{r.newPlanName ?? r.newPlanId}</span>
          </span>
        ) : (
          <span className="badge badge-grayblue badge-plain">{r.newPlanName ?? r.newPlanId ?? '—'}</span>
        ),
    },
    {
      key: 'newExpiryDate',
      header: 'New Expiry',
      sortable: true,
      render: (r) => {
        const tone = expiryTone(r.newExpiryDate);
        return (
          <div className="flex flex-col items-start gap-[3px]">
            <span className="nowrap">{r.newExpiryDate ? formatDate(r.newExpiryDate) : 'Lifetime'}</span>
            <span className={`badge ${tone.tone}`}>{tone.label}</span>
          </div>
        );
      },
    },
    {
      key: 'amount',
      header: 'Amount',
      align: 'right',
      render: (r) => <span className="font-semibold tabular-nums text-success">{formatCurrency(r.amount, r.currency)}</span>,
    },
    {
      key: 'paymentRef',
      header: 'Payment Ref',
      render: (r) => (r.paymentRef ? <span className="mono">{r.paymentRef}</span> : <span className="muted">—</span>),
    },
    { key: 'performedByName', header: 'By', render: (r) => r.performedByName ?? r.performedBy ?? '—' },
    ...(hasPermission('LICENSE_MANAGE')
      ? [
          {
            key: '_actions',
            header: 'Actions',
            align: 'right' as const,
            render: (r: Renewal) => (
              <div className="row-actions">
                <RowDelete
                  what={`renewal of ${r.licenseNo ?? `licence #${r.licenseId}`}`}
                  detail="Only the renewal record is removed; the licence keeps its current plan and expiry."
                  onDelete={() => {
                    setPending(null);
                    return renewalsApi.remove(r.renewalId);
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
          <h1>
            Renewals <span className="ml-2 inline-block rounded-full border border-solid border-primary-border bg-primary-soft px-[9px] py-0.5 align-middle text-2xs font-bold uppercase tracking-[0.12em] text-primary">History</span>
          </h1>
          <div className="subtitle">Licence renewal history</div>
        </div>
      </div>

      <PendingBanner message={pending} />

      {summary && summary.ytdCount !== undefined && (
        <div className="metric-grid">
          <div className="metric-card accent-blue">
            <div className="metric-main">
              <div className="metric-top">
                <div>
                  <div className="metric-label">Renewals this year</div>
                  <div className="metric-value">{summary.ytdCount}</div>
                </div>
                <div className="metric-icon">
                  <Icon name="refresh" size={18} />
                </div>
              </div>
            </div>
          </div>
          <div className="metric-card accent-green">
            <div className="metric-main">
              <div className="metric-top">
                <div>
                  <div className="metric-label">Renewal revenue (YTD)</div>
                  <div className="metric-value">{formatCurrency(summary.ytdAmount ?? 0, 'INR')}</div>
                </div>
                <div className="metric-icon">
                  <Icon name="trending-up" size={18} />
                </div>
              </div>
            </div>
          </div>
          <div className="metric-card accent-amber">
            <div className="metric-main">
              <div className="metric-top">
                <div>
                  <div className="metric-label">Pending renewals</div>
                  <div className="metric-value">{summary.pending ?? 0}</div>
                  <div className="metric-hint">Active licences expiring within 30 days</div>
                </div>
                <div className="metric-icon">
                  <Icon name="clock" size={18} />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="adv-filter">
          <div className="filter-item">
            <label htmlFor="ren-search">Search</label>
            <SearchInput
              id="ren-search"
              value={list.state.q}
              onChange={list.setQ}
              placeholder="Licence no, customer, payment ref…"
            />
          </div>
          <div className="filter-item">
            <label>Product</label>
            <select
              className="input"
              value={list.state.filters['productId'] ?? ''}
              onChange={(e) => list.setFilter('productId', e.target.value)}
            >
              <option value="">All products</option>
              {(products.data?.items ?? []).map((p) => (
                <option key={p.productId} value={p.productId}>
                  {p.productName}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-item">
            <label htmlFor="ren-from">From</label>
            <input
              id="ren-from"
              className="input"
              type="date"
              value={list.state.filters['createdFrom'] ?? ''}
              onChange={(e) => list.setFilter('createdFrom', e.target.value)}
            />
          </div>
          <div className="filter-item">
            <label htmlFor="ren-to">To</label>
            <input
              id="ren-to"
              className="input"
              type="date"
              value={list.state.filters['createdTo'] ?? ''}
              onChange={(e) => list.setFilter('createdTo', e.target.value)}
            />
          </div>
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
              rows={data?.items ?? []}
              rowKey={(r) => r.renewalId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              emptyTitle="No renewals"
              emptyMessage="Renewal transactions will appear here."
            />
            <div className="table-foot">
              <span className="foot-count">
                Showing <strong>{data?.items.length ?? 0}</strong> of <strong>{data?.total ?? 0}</strong>
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
    </div>
  );
}
