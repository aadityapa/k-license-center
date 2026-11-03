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
import { ProductFormModal } from './ProductFormModal';
import { productsApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { useAuth } from '../../auth/AuthContext';
import { formatDate } from '../../utils/format';
import type { Product } from '../../types';

/** Per-product glyph, keyed off the product code so new products still get one. */
function productIcon(code: string): 'layers' | 'activity' | 'package' {
  if (code.includes('STACK')) return 'layers';
  if (code.includes('FLASH')) return 'activity';
  return 'package';
}

/** Quote a CSV cell only when it needs it. */
function csvCell(value: unknown): string {
  const s = value == null ? '' : String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function ProductsListPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { hasPermission } = useAuth();
  const list = useListState({ sort: 'productName:asc' });
  const { data, loading, error, reload } = useApi(() => productsApi.list(list.params), [list.depsKey]);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const canManage = hasPermission('PRODUCT_MANAGE');
  const rows = data?.items ?? [];
  const versions = data?.versions ?? [];

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

  // Close the row menu on any outside click or Escape.
  useEffect(() => {
    if (menuFor === null) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuFor(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuFor(null);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuFor]);

  const openEdit = (p: Product) => {
    setPending(null);
    setEditing(p);
    setFormOpen(true);
    setMenuFor(null);
  };

  /** Exports the rows currently loaded — the page you can see, not a silent full dump. */
  const exportCsv = () => {
    const header = ['Code', 'Name', 'Key Prefix', 'Version', 'Status', 'Created'];
    const body = rows.map((p) =>
      [p.productCode, p.productName, p.keyPrefix, p.version ?? '', p.status, formatDate(p.createdAt)]
        .map(csvCell)
        .join(','),
    );
    const blob = new Blob([[header.join(','), ...body].join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `products-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns: Array<Column<Product>> = [
    {
      key: 'productCode',
      header: 'Code',
      sortable: true,
      render: (p) => <span className="mono code-cell">{p.productCode}</span>,
    },
    {
      key: 'productName',
      header: 'Name',
      sortable: true,
      render: (p) => (
        <span className="name-cell">
          <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm border border-solid border-primary-border bg-primary-soft text-primary">
            <Icon name={productIcon(p.productCode)} size={15} />
          </span>
          {p.productName}
        </span>
      ),
    },
    { key: 'keyPrefix', header: 'Key Prefix', render: (p) => <span className="mono muted">{p.keyPrefix}</span> },
    { key: 'version', header: 'Version', render: (p) => p.version ?? <span className="muted">—</span> },
    { key: 'status', header: 'Status', render: (p) => <StatusBadge status={p.status} /> },
    { key: 'createdAt', header: 'Created', sortable: true, render: (p) => formatDate(p.createdAt) },
    ...(canManage
      ? [
          {
            key: '_actions',
            header: 'Actions',
            align: 'right' as const,
            render: (p: Product) => (
              <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                <button
                  type="button"
                  className="round-btn"
                  title="Edit product"
                  aria-label={`Edit ${p.productName}`}
                  onClick={() => openEdit(p)}
                >
                  <Icon name="edit" size={14} />
                </button>
                <button
                  type="button"
                  className="round-btn"
                  title="More actions"
                  aria-label={`More actions for ${p.productName}`}
                  aria-expanded={menuFor === p.productId}
                  onClick={() => setMenuFor(menuFor === p.productId ? null : p.productId)}
                >
                  <Icon name="more" size={14} />
                </button>
                {menuFor === p.productId && (
                  <div className="row-menu" ref={menuRef} role="menu">
                    <button type="button" role="menuitem" onClick={() => openEdit(p)}>
                      <Icon name="edit" size={13} />
                      Edit product
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenuFor(null);
                        navigate(`/products/${p.productId}`);
                      }}
                    >
                      <Icon name="external" size={13} />
                      Open details
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenuFor(null);
                        navigate(`/plans?productId=${p.productId}`);
                      }}
                    >
                      <Icon name="layers" size={13} />
                      View plans
                    </button>
                  </div>
                )}
                <RowDelete
                  what={`product ${p.productName}`}
                  confirmText={p.productCode}
                  detail="Its plans and API clients are deleted with it. A product that still has licences cannot be deleted."
                  onDelete={() => {
                    setPending(null);
                    return productsApi.remove(p.productId);
                  }}
                  onDeleted={reload}
                  onPending={setPending}
                />
              </div>
            ),
          } as Column<Product>,
        ]
      : []),
  ];

  return (
    <div>
      <div className="overview-head">
        <div>
          <h1>Products</h1>
          <div className="subtitle">Licensed software products</div>
        </div>
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
            New Product
          </button>
        )}
      </div>

      <PendingBanner message={pending} />

      <div className="card">
        <div className="adv-filter">
          <span className="adv-filter-label">Advanced Filtering</span>
          <SearchInput value={list.state.q} onChange={list.setQ} placeholder="Product code or name…" />
          <select
            className="input"
            aria-label="Status"
            value={list.state.filters['status'] ?? ''}
            onChange={(e) => list.setFilter('status', e.target.value)}
          >
            <option value="">All statuses</option>
            <option value="ACTIVE">Active</option>
            <option value="INACTIVE">Deactivated</option>
          </select>
          {advanced && (
            <select
              className="input"
              aria-label="Version"
              value={list.state.filters['version'] ?? ''}
              onChange={(e) => list.setFilter('version', e.target.value)}
            >
              <option value="">All versions</option>
              {versions.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          )}
          <div className="adv-filter-right">
            {list.hasFilters && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={list.clearFilters}>
                Clear
              </button>
            )}
            <button
              type="button"
              className={`toggle-switch${advanced ? ' on' : ''}`}
              onClick={() => {
                if (advanced) list.setFilter('version', '');
                setAdvanced(!advanced);
              }}
              aria-pressed={advanced}
            >
              <span className="toggle-track">
                <span className="toggle-knob" />
              </span>
              Advanced Options
              <Icon name="settings" size={14} />
            </button>
          </div>
        </div>

        {error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(p) => p.productId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              onRowClick={(p) => navigate(`/products/${p.productId}`)}
              emptyTitle="No products"
              emptyMessage="Create your first product to start issuing licenses."
            />
            <div className="table-foot">
              <span className="foot-count">
                Total products: <strong>{data?.total ?? 0}</strong>
                {rows.length > 0 && ` (showing ${rows.length})`}
              </span>
              <Pagination
                page={data?.page ?? list.state.page}
                pageSize={data?.pageSize ?? list.state.pageSize}
                total={data?.total ?? 0}
                onPageChange={list.setPage}
                onPageSizeChange={list.setPageSize}
              />
              <button type="button" className="btn btn-sm" onClick={exportCsv} disabled={rows.length === 0}>
                <Icon name="download" size={14} />
                Export
              </button>
            </div>
          </>
        )}
      </div>

      <ProductFormModal
        open={formOpen}
        product={editing}
        onClose={() => setFormOpen(false)}
        onSaved={reload}
        onPending={setPending}
      />
    </div>
  );
}
