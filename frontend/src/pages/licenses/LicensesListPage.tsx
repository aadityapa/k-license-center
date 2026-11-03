import { useNavigate, useSearchParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { DataTable } from '../../components/DataTable';
import type { Column } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import { SearchInput } from '../../components/SearchInput';
import { Avatar, UsageBar } from '../../components/Viz';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState } from '../../components/ErrorState';
import { Icon } from '../../components/Icon';
import { CreateLicenseModal } from './LicenseActions';
import { PendingBanner } from '../../components/PendingBanner';
import { RowDelete } from '../../components/RowDelete';
import { customersApi, licensesApi, plansApi, productsApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { useAuth } from '../../auth/AuthContext';
import { expiryLabel } from '../../utils/format';
import type { License, LicenseStatus } from '../../types';

const LICENSE_STATUSES: LicenseStatus[] = ['DRAFT', 'ACTIVE', 'SUSPENDED', 'EXPIRED', 'REVOKED', 'CANCELLED'];

function productIcon(code?: string): 'layers' | 'activity' | 'package' {
  if (code?.includes('STACK')) return 'layers';
  if (code?.includes('FLASH')) return 'activity';
  return 'package';
}

export function LicensesListPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { hasPermission } = useAuth();
  const [createOpen, setCreateOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);

  // The maker dashboard's quick action links here with ?new=1. Open the form,
  // then drop the flag so closing it does not leave a URL that reopens it.
  useEffect(() => {
    if (searchParams.get('new') !== '1') return;
    setPending(null);
    setCreateOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete('new');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const list = useListState({
    sort: 'createdAt:desc',
    filters: {
      productId: searchParams.get('productId') ?? '',
      customerId: searchParams.get('customerId') ?? '',
      status: searchParams.get('status') ?? '',
    },
  });

  const { data, loading, error, reload } = useApi(() => licensesApi.list(list.params), [list.depsKey]);
  const products = useApi(() => productsApi.list({ pageSize: 100 }), []);
  const customers = useApi(() => customersApi.list({ pageSize: 100, sort: 'companyName:asc' }), []);
  const productFilter = list.state.filters['productId'] ?? '';
  const plans = useApi(
    () => (productFilter ? plansApi.list({ productId: Number(productFilter), pageSize: 100 }) : Promise.resolve(null)),
    [productFilter],
  );

  const columns: Array<Column<License>> = [
    {
      key: 'licenseNo',
      header: 'License No',
      sortable: true,
      render: (l) => <span className="mono code-cell">{l.licenseNo}</span>,
    },
    {
      key: 'serialNo',
      header: 'Serial No',
      render: (l) => <span className="mono code-cell">{l.serialNo ?? '—'}</span>,
    },
    {
      key: 'customerName',
      header: 'Customer',
      render: (l) => (
        <span className="name-cell">
          <Avatar name={String(l.customerName ?? l.customerId)} size={26} />
          <span>{l.customerName ?? l.customerId}</span>
        </span>
      ),
    },
    {
      key: 'productName',
      header: 'Product',
      render: (l) => (
        <span className="name-cell">
          <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm border border-solid border-primary-border bg-primary-soft text-primary">
            <Icon name={productIcon(l.productCode)} size={13} />
          </span>
          {l.productName ?? l.productCode ?? l.productId}
        </span>
      ),
    },
    { key: 'planName', header: 'Plan', render: (l) => l.planName ?? l.planId },
    { key: 'status', header: 'Status', sortable: true, render: (l) => <StatusBadge status={l.status} /> },
    {
      key: 'currentActivations',
      header: 'Activations',
      width: 130,
      render: (l) => <UsageBar used={l.currentActivations} max={l.maxActivations} />,
    },
    {
      key: 'expiryDate',
      header: 'Expiry',
      sortable: true,
      render: (l) => (
        <span className="nowrap inline-flex items-center gap-1.5 [&_svg]:text-muted">
          <Icon name={l.expiryDate ? 'clock' : 'shield'} size={13} />
          {expiryLabel(l.expiryDate)}
        </span>
      ),
    },
    ...(hasPermission('LICENSE_MANAGE')
      ? [
          {
            key: '_actions',
            header: 'Actions',
            align: 'right' as const,
            render: (l: License) => (
              <div className="row-actions">
                <RowDelete
                  what={`licence ${l.licenseNo}`}
                  confirmText={l.licenseNo}
                  detail="Its keys, activations, renewals and history are deleted too. Apps using it stop working immediately."
                  onDelete={() => {
                    setPending(null);
                    return licensesApi.remove(l.licenseId);
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
          <h1>All Licences</h1>
          <div className="subtitle">Every licence across products and customers</div>
        </div>
        {hasPermission('LICENSE_CREATE') && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setPending(null);
              setCreateOpen(true);
            }}
          >
            <Icon name="plus" size={15} />
            Create License
          </button>
        )}
      </div>
      <PendingBanner message={pending} />
      <div className="card">
        <div className="adv-filter">
          <div className="filter-item">
            <label htmlFor="lic-search">Search</label>
            <SearchInput id="lic-search" value={list.state.q} onChange={list.setQ} placeholder="Licence no, serial, unique ID, key or customer…" />
          </div>
          <div className="filter-item">
            <label>Product</label>
            <select
              className="input"
              value={productFilter}
              onChange={(e) => {
                list.setFilter('productId', e.target.value);
                list.setFilter('planId', '');
              }}
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
            <label>Plan</label>
            <select
              className="input"
              value={list.state.filters['planId'] ?? ''}
              onChange={(e) => list.setFilter('planId', e.target.value)}
              disabled={!productFilter}
            >
              <option value="">All plans</option>
              {(plans.data?.items ?? []).map((p) => (
                <option key={p.planId} value={p.planId}>
                  {p.planName}
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
              {LICENSE_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-item">
            <label>Customer</label>
            <select
              className="input"
              value={list.state.filters['customerId'] ?? ''}
              onChange={(e) => list.setFilter('customerId', e.target.value)}
            >
              <option value="">All customers</option>
              {(customers.data?.items ?? []).map((c) => (
                <option key={c.customerId} value={c.customerId}>
                  {c.companyName}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-item">
            <label htmlFor="lic-from">Expiry from</label>
            <input
              id="lic-from"
              className="input"
              type="date"
              value={list.state.filters['expiryFrom'] ?? ''}
              onChange={(e) => list.setFilter('expiryFrom', e.target.value)}
            />
          </div>
          <div className="filter-item">
            <label htmlFor="lic-to">Expiry to</label>
            <input
              id="lic-to"
              className="input"
              type="date"
              value={list.state.filters['expiryTo'] ?? ''}
              onChange={(e) => list.setFilter('expiryTo', e.target.value)}
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
              rowKey={(l) => l.licenseId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              onRowClick={(l) => navigate(`/licenses/${l.licenseId}`)}
              emptyTitle="No licenses"
              emptyMessage="No licenses match the current filters."
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
      <CreateLicenseModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(licenseId) => navigate(`/licenses/${licenseId}`)}
        onPending={setPending}
      />
    </div>
  );
}
