import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { DataTable } from '../../components/DataTable';
import type { Column } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import { FilterBar, FilterItem } from '../../components/FilterBar';
import { SearchInput } from '../../components/SearchInput';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState, ErrorBanner } from '../../components/ErrorState';
import { Modal } from '../../components/Modal';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { FormField } from '../../components/FormField';
import { Spinner } from '../../components/Spinner';
import { CopyButton } from '../../components/CopyButton';
import { Icon } from '../../components/Icon';
import { RowDelete } from '../../components/RowDelete';
import { PendingBanner } from '../../components/PendingBanner';
import { apiClientsApi, productsApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { useAuth } from '../../auth/AuthContext';
import { formatDateTime } from '../../utils/format';
import type { ApiClient, ApiClientCreated } from '../../types';

export function ApiClientsPage() {
  const list = useListState({ sort: 'createdAt:desc' });
  const { data, loading, error, reload } = useApi(() => apiClientsApi.list(list.params), [list.depsKey]);
  const products = useApi(() => productsApi.list({ pageSize: 100 }), []);
  const { hasPermission } = useAuth();
  const canDelete = hasPermission('APICLIENT_MANAGE');
  const [pending, setPending] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<ApiClientCreated | null>(null);
  const [revoking, setRevoking] = useState<ApiClient | null>(null);
  const [form, setForm] = useState({ productId: '', name: '' });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<Error | null>(null);

  useEffect(() => {
    if (createOpen) {
      setForm({ productId: '', name: '' });
      setFormError(null);
    }
  }, [createOpen]);

  const submitCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.productId || !form.name.trim()) return;
    setBusy(true);
    setFormError(null);
    try {
      const client = await apiClientsApi.create({ productId: Number(form.productId), name: form.name.trim() });
      setCreateOpen(false);
      setCreated(client);
      reload();
    } catch (err) {
      setFormError(err instanceof Error ? err : new Error('Create failed'));
    } finally {
      setBusy(false);
    }
  };

  const columns: Array<Column<ApiClient>> = [
    { key: 'name', header: 'Name', sortable: true },
    { key: 'productName', header: 'Product', render: (c) => c.productName ?? c.productCode ?? c.productId },
    { key: 'clientKey', header: 'Client Key', render: (c) => <span className="mono !text-[11.5px]">{c.clientKey}</span> },
    { key: 'status', header: 'Status', render: (c) => <StatusBadge status={c.status} /> },
    { key: 'lastUsedAt', header: 'Last Used', sortable: true, render: (c) => <span className="nowrap">{formatDateTime(c.lastUsedAt)}</span> },
    { key: 'createdAt', header: 'Created', sortable: true, render: (c) => <span className="nowrap">{formatDateTime(c.createdAt)}</span> },
    {
      key: '_actions',
      header: 'Actions',
      align: 'right',
      render: (c) => (
        <div className="row-actions">
          {c.status === 'ACTIVE' && (
            <button type="button" className="btn btn-sm btn-danger-outline" onClick={() => setRevoking(c)}>
              <Icon name="ban" size={14} />
              Revoke
            </button>
          )}
          {canDelete && (
            <RowDelete
              what={`API client ${c.name}`}
              confirmText={c.name}
              detail="Apps using this client key and secret stop working immediately."
              onDelete={() => {
                setPending(null);
                return apiClientsApi.remove(c.clientId);
              }}
              onDeleted={reload}
              onPending={setPending}
            />
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="API Clients"
        subtitle="Credentials used by products (KStack, KFlash, …) to call the license API"
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setCreateOpen(true)}>
            <Icon name="plus" size={15} />
            New API Client
          </button>
        }
      />
      <PendingBanner message={pending} />
      <div className="card">
        <FilterBar showClear={list.hasFilters} onClear={list.clearFilters}>
          <FilterItem label="Search">
            <SearchInput value={list.state.q} onChange={list.setQ} placeholder="Name or client key…" />
          </FilterItem>
          <FilterItem label="Product">
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
          </FilterItem>
          <FilterItem label="Status">
            <select
              className="input"
              value={list.state.filters['status'] ?? ''}
              onChange={(e) => list.setFilter('status', e.target.value)}
            >
              <option value="">All</option>
              <option value="ACTIVE">ACTIVE</option>
              <option value="REVOKED">REVOKED</option>
            </select>
          </FilterItem>
        </FilterBar>
        {error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(c) => c.clientId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              emptyTitle="No API clients"
              emptyMessage="Create a client so a product can authenticate against the license API."
            />
            <Pagination
              page={data?.page ?? list.state.page}
              pageSize={data?.pageSize ?? list.state.pageSize}
              total={data?.total ?? 0}
              onPageChange={list.setPage}
              onPageSizeChange={list.setPageSize}
            />
          </>
        )}
      </div>

      {/* Create modal */}
      <Modal title="New API Client" open={createOpen} onClose={() => setCreateOpen(false)}>
        <ErrorBanner error={formError} />
        <form onSubmit={submitCreate}>
          <FormField label="Product" required hint="The client can only authorize licenses of this product.">
            <select
              className="input"
              value={form.productId}
              onChange={(e) => setForm((f) => ({ ...f, productId: e.target.value }))}
            >
              <option value="">Select product…</option>
              {(products.data?.items ?? []).map((p) => (
                <option key={p.productId} value={p.productId}>
                  {p.productName} ({p.productCode})
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Client Name" required hint="e.g. KStack Production">
            <input className="input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} maxLength={100} />
          </FormField>
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => setCreateOpen(false)} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy || !form.productId || !form.name.trim()}>
              {busy ? <Spinner size={13} /> : <Icon name="plus" size={15} />}
              Create Client
            </button>
          </div>
        </form>
      </Modal>

      {/* One-time secret display */}
      <Modal title="API Client Created" open={created !== null} onClose={() => setCreated(null)} locked>
        <div className="alert alert-warning">
          <Icon name="alert-triangle" size={16} />
          <div>
            <strong>Save these credentials now.</strong> The client secret is shown only once and cannot be retrieved
            later — only regenerated by creating a new client.
          </div>
        </div>
        {created && (
          <div className="secret-box">
            <div className="def-label">Client Key</div>
            <div className="secret-row">
              <span>{created.clientKey}</span>
              <CopyButton text={created.clientKey} />
            </div>
            <div className="def-label mt-2.5">
              Client Secret
            </div>
            <div className="secret-row">
              <span>{created.clientSecret}</span>
              <CopyButton text={created.clientSecret} />
            </div>
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-primary" onClick={() => setCreated(null)}>
            I have saved the credentials
          </button>
        </div>
      </Modal>

      <ConfirmDialog
        open={revoking !== null}
        title="Revoke API Client"
        danger
        requireReason
        message={
          <>
            Revoke <strong>{revoking?.name}</strong>? The product using this client key will immediately stop being able
            to activate or validate licenses. This cannot be undone.
          </>
        }
        confirmLabel="Revoke Client"
        onConfirm={async (reason) => {
          if (!revoking) return;
          await apiClientsApi.revoke(revoking.clientId, reason);
          setRevoking(null);
          reload();
        }}
        onClose={() => setRevoking(null)}
      />
    </div>
  );
}
