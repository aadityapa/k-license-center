import { PageHeader } from '../../components/PageHeader';
import { DataTable } from '../../components/DataTable';
import type { Column } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import { SearchInput } from '../../components/SearchInput';
import { FilterBar, FilterItem } from '../../components/FilterBar';
import { ErrorState } from '../../components/ErrorState';
import { apiClientsApi, apiLogsApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { formatDateTime } from '../../utils/format';
import type { ApiRequestLog } from '../../types';

function httpStatusClass(status: number): string {
  if (status >= 500) return 'badge badge-plain badge-red';
  if (status >= 400) return 'badge badge-plain badge-amber';
  return 'badge badge-plain badge-green';
}

export function ApiLogsPage() {
  const list = useListState({ sort: 'createdAt:desc' });
  const { data, loading, error, reload } = useApi(() => apiLogsApi.list(list.params), [list.depsKey]);
  const clients = useApi(() => apiClientsApi.list({ pageSize: 100 }), []);

  const columns: Array<Column<ApiRequestLog>> = [
    { key: 'createdAt', header: 'Time', sortable: true, render: (l) => <span className="nowrap">{formatDateTime(l.createdAt)}</span> },
    { key: 'method', header: 'Method', render: (l) => <span className="mono">{l.method}</span> },
    { key: 'endpoint', header: 'Endpoint', render: (l) => <span className="mono !text-sm">{l.endpoint}</span> },
    { key: 'clientName', header: 'Client', render: (l) => l.clientName ?? l.clientKey ?? '—' },
    { key: 'resultCode', header: 'Result', render: (l) => l.resultCode ?? '—' },
    {
      key: 'httpStatus',
      header: 'HTTP',
      render: (l) => <span className={httpStatusClass(l.httpStatus)}>{l.httpStatus}</span>,
    },
    { key: 'ipAddress', header: 'IP' },
    { key: 'durationMs', header: 'Duration', align: 'right', render: (l) => (l.durationMs != null ? `${l.durationMs} ms` : '—') },
    { key: 'requestId', header: 'Request ID', render: (l) => <span className="mono !text-xs">{l.requestId ?? '—'}</span> },
  ];

  return (
    <div>
      <PageHeader title="API Logs" subtitle="License API requests from product clients" />
      <div className="card">
        <FilterBar showClear={list.hasFilters} onClear={list.clearFilters}>
          <FilterItem label="Search">
            <SearchInput value={list.state.q} onChange={list.setQ} placeholder="Endpoint, request ID, IP…" />
          </FilterItem>
          <FilterItem label="Client">
            <select
              className="input"
              value={list.state.filters['clientId'] ?? ''}
              onChange={(e) => list.setFilter('clientId', e.target.value)}
            >
              <option value="">All clients</option>
              {(clients.data?.items ?? []).map((c) => (
                <option key={c.clientId} value={c.clientId}>
                  {c.name}
                </option>
              ))}
            </select>
          </FilterItem>
          <FilterItem label="Result">
            <select
              className="input"
              value={list.state.filters['resultCode'] ?? ''}
              onChange={(e) => list.setFilter('resultCode', e.target.value)}
            >
              <option value="">All</option>
              <option value="OK">OK</option>
              <option value="INVALID_LICENSE">INVALID_LICENSE</option>
              <option value="LICENSE_EXPIRED">LICENSE_EXPIRED</option>
              <option value="LICENSE_SUSPENDED">LICENSE_SUSPENDED</option>
              <option value="LICENSE_REVOKED">LICENSE_REVOKED</option>
              <option value="ACTIVATION_LIMIT_REACHED">ACTIVATION_LIMIT_REACHED</option>
              <option value="UNAUTHORIZED_CLIENT">UNAUTHORIZED_CLIENT</option>
              <option value="RATE_LIMITED">RATE_LIMITED</option>
            </select>
          </FilterItem>
          <FilterItem label="From">
            <input
              className="input"
              type="date"
              value={list.state.filters['createdFrom'] ?? ''}
              onChange={(e) => list.setFilter('createdFrom', e.target.value)}
            />
          </FilterItem>
          <FilterItem label="To">
            <input
              className="input"
              type="date"
              value={list.state.filters['createdTo'] ?? ''}
              onChange={(e) => list.setFilter('createdTo', e.target.value)}
            />
          </FilterItem>
        </FilterBar>
        {error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(l) => l.logId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              emptyTitle="No API requests"
              emptyMessage="Requests from product clients will appear here."
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
    </div>
  );
}
