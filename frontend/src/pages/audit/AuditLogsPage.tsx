import { Fragment, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { Pagination } from '../../components/Pagination';
import { SearchInput } from '../../components/SearchInput';
import { FilterBar, FilterItem } from '../../components/FilterBar';
import { ErrorState } from '../../components/ErrorState';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { auditApi, usersApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { formatDateTime, prettyJson } from '../../utils/format';

const ENTITY_TYPES = ['LICENSE', 'CUSTOMER', 'PRODUCT', 'PLAN', 'USER', 'ROLE', 'API_CLIENT', 'ACTIVATION', 'SETTING'];

export function AuditLogsPage() {
  const [searchParams] = useSearchParams();
  const list = useListState({
    sort: 'createdAt:desc',
    filters: {
      entity: searchParams.get('entity') ?? searchParams.get('entityType') ?? '',
      entityId: searchParams.get('entityId') ?? '',
    },
  });
  const { data, loading, error, reload } = useApi(() => auditApi.list(list.params), [list.depsKey]);
  const users = useApi(() => usersApi.list({ pageSize: 100, sort: 'username:asc' }), []);
  const [expanded, setExpanded] = useState<number | null>(null);

  return (
    <div>
      <PageHeader title="Audit Logs" subtitle="Append-only trail of every administrative change" />
      <div className="card">
        <FilterBar showClear={list.hasFilters} onClear={list.clearFilters}>
          <FilterItem label="Search">
            <SearchInput value={list.state.q} onChange={list.setQ} placeholder="Action, actor, request ID…" />
          </FilterItem>
          <FilterItem label="Action">
            <input
              className="input !min-w-[170px]"
              placeholder="e.g. LICENSE_REVOKED"
              value={list.state.filters['action'] ?? ''}
              onChange={(e) => list.setFilter('action', e.target.value.toUpperCase())}
            />
          </FilterItem>
          <FilterItem label="Entity Type">
            <select
              className="input"
              value={list.state.filters['entity'] ?? ''}
              onChange={(e) => list.setFilter('entity', e.target.value)}
            >
              <option value="">All</option>
              {ENTITY_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </FilterItem>
          <FilterItem label="User">
            <select
              className="input"
              value={list.state.filters['userId'] ?? ''}
              onChange={(e) => list.setFilter('userId', e.target.value)}
            >
              <option value="">All users</option>
              {(users.data?.items ?? []).map((u) => (
                <option key={u.userId} value={u.userId}>
                  {u.username}
                </option>
              ))}
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
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th className="w-[30px]" />
                    <th>When</th>
                    <th>Action</th>
                    <th>Entity</th>
                    <th>Actor</th>
                    <th>IP</th>
                    <th>Request ID</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && (
                    <tr>
                      <td colSpan={7}>
                        <div className="table-empty">
                          <Spinner size={22} />
                        </div>
                      </td>
                    </tr>
                  )}
                  {!loading && (data?.items ?? []).length === 0 && (
                    <tr>
                      <td colSpan={7}>
                        <div className="table-empty">
                          <div className="empty-icon">
                            <Icon name="inbox" size={32} />
                          </div>
                          <div className="empty-title">No audit events</div>
                          <div className="empty-hint">Administrative actions will be recorded here.</div>
                        </div>
                      </td>
                    </tr>
                  )}
                  {!loading &&
                    (data?.items ?? []).map((a) => {
                      const isOpen = expanded === a.auditId;
                      const hasDiff = Boolean(a.beforeState) || Boolean(a.afterState);
                      return (
                        <Fragment key={a.auditId}>
                          <tr
                            className={hasDiff ? 'clickable' : undefined}
                            onClick={hasDiff ? () => setExpanded(isOpen ? null : a.auditId) : undefined}
                          >
                            <td className="muted">
                              {hasDiff && <Icon name={isOpen ? 'chevron-down' : 'chevron-right'} size={13} />}
                            </td>
                            <td className="nowrap">{formatDateTime(a.createdAt)}</td>
                            <td>
                              <span className="badge badge-grayblue badge-plain">{a.action}</span>
                            </td>
                            <td>
                              {a.entityType ?? '—'}
                              {a.entityId != null && <span className="muted"> #{a.entityId}</span>}
                            </td>
                            <td>{a.actor ?? '—'}</td>
                            <td>{a.ipAddress ?? '—'}</td>
                            <td className="mono text-xs">{a.requestId ?? '—'}</td>
                          </tr>
                          {isOpen && (
                            <tr>
                              <td colSpan={7} className="bg-surface-sunken">
                                <div className="json-diff px-1 py-2">
                                  <div className="json-block">
                                    <div className="json-title">Before</div>
                                    <pre>{prettyJson(a.beforeState) || '(empty)'}</pre>
                                  </div>
                                  <div className="json-block">
                                    <div className="json-title">After</div>
                                    <pre>{prettyJson(a.afterState) || '(empty)'}</pre>
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                </tbody>
              </table>
            </div>
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
