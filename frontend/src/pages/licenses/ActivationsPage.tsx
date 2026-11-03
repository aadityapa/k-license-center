import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { DataTable } from '../../components/DataTable';
import type { Column } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import { SearchInput } from '../../components/SearchInput';
import { ArcGauge, Avatar } from '../../components/Viz';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState, ErrorBanner } from '../../components/ErrorState';
import { PendingBanner } from '../../components/PendingBanner';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { Icon } from '../../components/Icon';
import { RowDelete } from '../../components/RowDelete';
import { ClockAlertsPanel } from '../../components/ClockAlertsPanel';
import { activationsApi, productsApi } from '../../services/api/endpoints';
import { isPendingApproval } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { useAuth } from '../../auth/AuthContext';
import { formatDateTime } from '../../utils/format';
import type { Activation } from '../../types';

function productIcon(code?: string): 'layers' | 'activity' | 'package' {
  if (code?.includes('STACK')) return 'layers';
  if (code?.includes('FLASH')) return 'activity';
  return 'package';
}

export function ActivationsPage() {
  const [searchParams] = useSearchParams();
  const { hasPermission } = useAuth();
  const list = useListState({
    sort: 'activatedAt:desc',
    filters: { productId: searchParams.get('productId') ?? '' },
  });
  const { data, loading, error, reload } = useApi(() => activationsApi.list(list.params), [list.depsKey]);
  const products = useApi(() => productsApi.list({ pageSize: 100 }), []);
  const [deactivating, setDeactivating] = useState<Activation | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const canManage = hasPermission('ACTIVATION_MANAGE');
  const summary = data?.summary;

  const columns: Array<Column<Activation>> = [
    {
      key: 'licenseNo',
      header: 'License',
      render: (a) => (
        <Link to={`/licenses/${a.licenseId}`} className="mono">
          {a.licenseNo ?? `#${a.licenseId}`}
        </Link>
      ),
    },
    {
      key: 'customerName',
      header: 'Customer',
      render: (a) => (
        <span className="name-cell">
          <Avatar name={String(a.customerName ?? '?')} size={24} />
          <span>{a.customerName ?? '—'}</span>
        </span>
      ),
    },
    {
      key: 'productName',
      header: 'Product',
      render: (a) => (
        <span className="name-cell">
          <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm border border-solid border-primary-border bg-primary-soft text-primary">
            <Icon name={productIcon(a.productCode)} size={13} />
          </span>
          {a.productName ?? a.productCode}
        </span>
      ),
    },
    {
      key: 'deviceName',
      header: 'Device',
      render: (a) => (
        <span className="icon-cell">
          <Icon name="package" size={14} />
          <span className="mono">{a.deviceName ?? a.installationId}</span>
        </span>
      ),
    },
    { key: 'osInfo', header: 'OS', render: (a) => a.osInfo ?? <span className="muted">—</span> },
    { key: 'appVersion', header: 'Version', render: (a) => a.appVersion ?? <span className="muted">—</span> },
    { key: 'status', header: 'Status', render: (a) => <StatusBadge status={a.status} /> },
    { key: 'activatedAt', header: 'Activated', sortable: true, render: (a) => <span className="nowrap">{formatDateTime(a.activatedAt)}</span> },
    { key: 'lastHeartbeatAt', header: 'Heartbeat', sortable: true, render: (a) => <span className="nowrap">{formatDateTime(a.lastHeartbeatAt)}</span> },
    ...(canManage
      ? [
          {
            key: '_actions',
            header: 'Actions',
            align: 'right',
            render: (a: Activation) => (
              <div className="row-actions">
                {a.status === 'ACTIVE' && (
                  <button type="button" className="btn btn-sm btn-danger-outline" onClick={() => setDeactivating(a)}>
                    <Icon name="ban" size={14} />
                    Deactivate
                  </button>
                )}
                <RowDelete
                  what={`activation ${a.deviceName ?? a.installationId}`}
                  detail="An active installation is signed out at once and its seat is freed."
                  onDelete={() => {
                    setPending(null);
                    return activationsApi.remove(a.activationId);
                  }}
                  onDeleted={reload}
                  onPending={setPending}
                />
              </div>
            ),
          } as Column<Activation>,
        ]
      : []),
  ];

  return (
    <div>
      <div className="overview-head">
        <div>
          <h1>Activations</h1>
          <div className="subtitle">Device installations across all licences</div>
        </div>
      </div>
      <ErrorBanner error={actionError} />
      <PendingBanner message={pending} />
      <ClockAlertsPanel onPending={setPending} />

      {summary && summary.total !== undefined && (
        <div className="metric-grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))]">
          <div className="metric-card accent-blue">
            <div className="metric-main">
              <div className="metric-top">
                <div>
                  <div className="metric-label">Total Activations</div>
                  <div className="metric-value">{summary.total}</div>
                </div>
                <div className="metric-icon">
                  <Icon name="activity" size={18} />
                </div>
              </div>
            </div>
          </div>
          <div className="metric-card accent-green">
            <div className="metric-main">
              <div className="metric-top">
                <div>
                  <div className="metric-label">Active Devices</div>
                  <div className="metric-value">{summary.active}</div>
                </div>
                <div className="metric-icon">
                  <Icon name="check" size={18} />
                </div>
              </div>
            </div>
          </div>
          {/* Health = active installs that checked in within twice the heartbeat
              interval. Stale devices are not necessarily gone — just quiet. */}
          <div className="card col-span-2 flex items-center gap-4 px-4 py-3 max-[900px]:col-span-1">
            <div className="shrink-0">
              <ArcGauge
                score={summary.healthPercent ?? 100}
                color={
                  (summary.healthPercent ?? 100) >= 90
                    ? '#34d399'
                    : (summary.healthPercent ?? 100) >= 60
                      ? '#fbbf24'
                      : '#fb7185'
                }
                size={110}
              />
            </div>
            <div className="min-w-0">
              <div className="metric-label">Device Health</div>
              <div className="mt-[3px] text-md font-semibold">
                {summary.stale === 0 ? 'All devices reporting' : `${summary.stale} not reporting`}
              </div>
              <div className="mt-0.5 text-sm text-muted">
                {summary.healthy} of {summary.active} active installs sent a recent heartbeat
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="adv-filter">
          <div className="filter-item">
            <label htmlFor="act-search">Device or installation ID</label>
            <SearchInput
              id="act-search"
              value={list.state.q}
              onChange={list.setQ}
              placeholder="Device or installation ID…"
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
            <label>Status</label>
            <select
              className="input"
              value={list.state.filters['status'] ?? ''}
              onChange={(e) => list.setFilter('status', e.target.value)}
            >
              <option value="">All</option>
              <option value="ACTIVE">Active</option>
              <option value="DEACTIVATED">Deactivated</option>
            </select>
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
              rowKey={(a) => a.activationId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              emptyTitle="No activations"
              emptyMessage="Product installations will appear here after activation."
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
      <ConfirmDialog
        open={deactivating !== null}
        title="Deactivate Installation"
        danger
        requireReason
        message={
          <>
            Deactivate <strong>{deactivating?.deviceName ?? deactivating?.installationId}</strong> on license{' '}
            <span className="mono">{deactivating?.licenseNo ?? deactivating?.licenseId}</span>? The activation slot is
            freed and the installation will be denied on its next validation.
          </>
        }
        confirmLabel="Deactivate"
        onConfirm={async (reason) => {
          if (!deactivating) return;
          try {
            const res = await activationsApi.deactivate(deactivating.activationId, reason);
            setDeactivating(null);
            setActionError(null);
            if (isPendingApproval(res)) {
              setPending(res.message);
            } else {
              setPending(null);
              reload();
            }
          } catch (err) {
            setDeactivating(null);
            setActionError(err instanceof Error ? err : new Error('Deactivation failed'));
          }
        }}
        onClose={() => setDeactivating(null)}
      />
    </div>
  );
}
