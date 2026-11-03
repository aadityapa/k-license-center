import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { DataTable } from '../../components/DataTable';
import type { Column } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import { SearchInput } from '../../components/SearchInput';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState } from '../../components/ErrorState';
import { PendingBanner } from '../../components/PendingBanner';
import { Icon } from '../../components/Icon';
import { RowDelete } from '../../components/RowDelete';
import { Avatar } from '../../components/Viz';
import { CustomerFormModal } from './CustomerFormModal';
import { customersApi } from '../../services/api/endpoints';
import { isPendingApproval } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { useAuth } from '../../auth/AuthContext';
import { formatDate } from '../../utils/format';
import type { Customer } from '../../types';

function csvCell(value: unknown): string {
  const s = value == null ? '' : String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function CustomersListPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { hasPermission } = useAuth();
  const list = useListState({ sort: 'companyName:asc' });
  const { data, loading, error, reload } = useApi(() => customersApi.list(list.params), [list.depsKey]);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const bulkRef = useRef<HTMLDivElement | null>(null);

  const canManage = hasPermission('CUSTOMER_MANAGE');
  const rows = data?.items ?? [];

  // The maker dashboard's quick action links here with ?new=1. Open the form,
  // then drop the flag so closing it does not leave a URL that reopens it.
  useEffect(() => {
    if (searchParams.get('new') !== '1') return;
    setPending(null);
    setEditing(null);
    setFormOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete('new');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (!bulkOpen) return;
    const onDown = (e: MouseEvent) => {
      if (bulkRef.current && !bulkRef.current.contains(e.target as Node)) setBulkOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setBulkOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [bulkOpen]);

  const toggleRow = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const allOnPageSelected = rows.length > 0 && rows.every((c) => selected.has(c.customerId));

  /** Bulk status change — the only bulk operation the API genuinely supports. */
  const bulkStatus = async (status: 'ACTIVE' | 'INACTIVE') => {
    setBulkOpen(false);
    setBulkBusy(true);
    setPending(null);
    try {
      // A maker's bulk edit becomes one change request per customer; count them
      // so the confirmation reflects what actually happened.
      let queued = 0;
      for (const id of selected) {
        const res = await customersApi.update(id, { status });
        if (isPendingApproval(res)) queued += 1;
      }
      setSelected(new Set());
      if (queued > 0) {
        setPending(
          `${queued} customer status change${queued === 1 ? '' : 's'} submitted for approval.`,
        );
      }
      reload();
    } finally {
      setBulkBusy(false);
    }
  };

  const exportCsv = () => {
    const scope = selected.size > 0 ? rows.filter((c) => selected.has(c.customerId)) : rows;
    const header = ['Code', 'Company', 'Contact', 'Email', 'Mobile', 'City', 'Status', 'Created'];
    const body = scope.map((c) =>
      [c.customerCode, c.companyName, c.contactPerson ?? '', c.email ?? '', c.mobile ?? '', c.city ?? '', c.status, formatDate(c.createdAt)]
        .map(csvCell)
        .join(','),
    );
    const blob = new Blob([[header.join(','), ...body].join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `customers-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns: Array<Column<Customer>> = [
    ...(canManage
      ? [
          {
            key: '_select',
            width: 36,
            header: (
              <input
                type="checkbox"
                aria-label="Select all on page"
                className="size-[15px] cursor-pointer accent-primary"
                checked={allOnPageSelected}
                onChange={(e) =>
                  setSelected(e.target.checked ? new Set(rows.map((c) => c.customerId)) : new Set())
                }
              />
            ),
            render: (c: Customer) => (
              <input
                type="checkbox"
                aria-label={`Select ${c.companyName}`}
                className="size-[15px] cursor-pointer accent-primary"
                checked={selected.has(c.customerId)}
                onClick={(e) => e.stopPropagation()}
                onChange={() => toggleRow(c.customerId)}
              />
            ),
          } as Column<Customer>,
        ]
      : []),
    { key: 'customerCode', header: 'Code', sortable: true, render: (c) => <span className="mono code-cell">{c.customerCode}</span> },
    {
      key: 'companyName',
      header: 'Company',
      sortable: true,
      render: (c) => (
        <span className="name-cell">
          <Avatar name={c.companyName} size={28} />
          <span>{c.companyName}</span>
        </span>
      ),
    },
    { key: 'contactPerson', header: 'Contact' },
    {
      key: 'email',
      header: 'Email',
      render: (c) =>
        c.email ? (
          <span className="icon-cell">
            <Icon name="inbox" size={13} />
            {c.email}
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    { key: 'mobile', header: 'Mobile', render: (c) => c.mobile ?? <span className="muted">—</span> },
    { key: 'city', header: 'City', render: (c) => c.city ?? <span className="muted">—</span> },
    { key: 'status', header: 'Status', render: (c) => <StatusBadge status={c.status} /> },
    { key: 'createdAt', header: 'Created', sortable: true, render: (c) => formatDate(c.createdAt) },
    ...(canManage
      ? [
          {
            key: '_actions',
            header: 'Actions',
            align: 'right' as const,
            render: (c: Customer) => (
              <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                <button
                  type="button"
                  className="round-btn"
                  title="Edit customer"
                  aria-label={`Edit ${c.companyName}`}
                  onClick={() => {
                    setPending(null);
                    setEditing(c);
                    setFormOpen(true);
                  }}
                >
                  <Icon name="edit" size={14} />
                </button>
                <button
                  type="button"
                  className="round-btn"
                  title="Open customer"
                  aria-label={`Open ${c.companyName}`}
                  onClick={() => navigate(`/customers/${c.customerId}`)}
                >
                  <Icon name="external" size={14} />
                </button>
                <RowDelete
                  what={`customer ${c.companyName}`}
                  confirmText={c.customerCode}
                  detail="A customer that still has licences cannot be deleted until those licences are deleted."
                  onDelete={() => {
                    setPending(null);
                    return customersApi.remove(c.customerId);
                  }}
                  onDeleted={reload}
                  onPending={setPending}
                />
              </div>
            ),
          } as Column<Customer>,
        ]
      : []),
  ];

  return (
    <div>
      <div className="overview-head">
        <div>
          <h1>Customers</h1>
          <div className="subtitle">Companies holding product licences</div>
        </div>
      </div>

      <PendingBanner message={pending} />

      {/* Action bar */}
      <div className="card mb-4 flex flex-wrap items-center justify-between gap-4 px-4 py-3">
        <span className="text-2xs font-bold uppercase tracking-[0.14em] text-muted">Action bar</span>
        <div className="flex flex-wrap items-center gap-2">
          {canManage && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setPending(null);
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Icon name="plus" size={15} />
              New Customer
            </button>
          )}
          <button type="button" className="btn" onClick={exportCsv} disabled={rows.length === 0}>
            <Icon name="download" size={14} />
            Export {selected.size > 0 ? `(${selected.size})` : 'Data'}
          </button>
          {canManage && (
            <div className="relative" ref={bulkRef}>
              <button
                type="button"
                className="btn"
                disabled={selected.size === 0 || bulkBusy}
                aria-expanded={bulkOpen}
                onClick={() => setBulkOpen(!bulkOpen)}
                title={selected.size === 0 ? 'Select rows to enable bulk actions' : undefined}
              >
                <Icon name="list" size={14} />
                Bulk Actions{selected.size > 0 ? ` (${selected.size})` : ''}
                <Icon name="chevron-down" size={13} />
              </button>
              {bulkOpen && (
                <div className="row-menu" role="menu">
                  <button type="button" role="menuitem" onClick={() => void bulkStatus('ACTIVE')}>
                    <Icon name="check" size={13} />
                    Mark active
                  </button>
                  <button type="button" role="menuitem" onClick={() => void bulkStatus('INACTIVE')}>
                    <Icon name="ban" size={13} />
                    Mark inactive
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <button
          type="button"
          className="flex w-full cursor-pointer items-center justify-between border-0 border-b border-solid border-line bg-transparent px-4 py-3 font-sans text-2xs font-bold uppercase tracking-[0.14em] text-muted transition-[color] duration-ui ease-ui hover:text-primary"
          onClick={() => setFiltersOpen(!filtersOpen)}
          aria-expanded={filtersOpen}
        >
          <span>Filter panel</span>
          <Icon name={filtersOpen ? 'chevron-up' : 'chevron-down'} size={15} />
        </button>

        {filtersOpen && (
          <div className="adv-filter">
            <div className="filter-item">
              <label htmlFor="cust-search">Search</label>
              <SearchInput
                id="cust-search"
                value={list.state.q}
                onChange={list.setQ}
                placeholder="Name, email or mobile…"
              />
            </div>
            <div className="filter-item">
              <label htmlFor="cust-status">Status</label>
              <select
                id="cust-status"
                className="input"
                value={list.state.filters['status'] ?? ''}
                onChange={(e) => list.setFilter('status', e.target.value)}
              >
                <option value="">All</option>
                <option value="ACTIVE">Active</option>
                <option value="INACTIVE">Inactive</option>
              </select>
            </div>
            <div className="filter-item">
              <label htmlFor="cust-from">Created from</label>
              <input
                id="cust-from"
                type="date"
                className="input"
                value={list.state.filters['createdFrom'] ?? ''}
                onChange={(e) => list.setFilter('createdFrom', e.target.value)}
              />
            </div>
            <div className="filter-item">
              <label htmlFor="cust-to">Created to</label>
              <input
                id="cust-to"
                type="date"
                className="input"
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
        )}

        {error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(c) => c.customerId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              onRowClick={(c) => navigate(`/customers/${c.customerId}`)}
              emptyTitle="No customers"
              emptyMessage="Add a customer before issuing licenses."
            />
            <div className="table-foot">
              <span className="foot-count">
                Showing <strong>{rows.length}</strong> of <strong>{data?.total ?? 0}</strong>
                {selected.size > 0 && ` · ${selected.size} selected`}
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

      <CustomerFormModal
        open={formOpen}
        customer={editing}
        onClose={() => setFormOpen(false)}
        onSaved={reload}
        onPending={setPending}
      />
    </div>
  );
}
