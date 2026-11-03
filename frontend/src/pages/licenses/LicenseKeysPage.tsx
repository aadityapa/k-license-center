import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { PendingBanner } from '../../components/PendingBanner';
import { isPendingApproval } from '../../services/api/http';
import { useAuth } from '../../auth/AuthContext';
import { Pagination } from '../../components/Pagination';
import { SearchInput } from '../../components/SearchInput';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState } from '../../components/ErrorState';
import { CopyButton } from '../../components/CopyButton';
import { Icon } from '../../components/Icon';
import { Avatar } from '../../components/Viz';
import { licenseKeysApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { formatDateTime } from '../../utils/format';
import type { LicenseKey } from '../../types';

/** Key card shell; the grid collapses to two/three columns on narrower screens. */
const KEY_CARD =
  'items-center gap-4 rounded-lg border border-solid px-4 py-3 transition-[border-color,box-shadow] duration-ui ease-ui max-[1200px]:grid-cols-[46px_1fr_1fr] max-[1200px]:gap-y-3 max-[700px]:grid-cols-[46px_1fr]';
const KEY_CARD_COLS = 'grid grid-cols-[52px_minmax(240px,1.4fr)_repeat(3,minmax(110px,0.8fr))_minmax(190px,1fr)]';
const KEY_CARD_IDLE = 'border-line bg-glass-sunken hover:border-primary-border hover:shadow-glow';
const KEY_LABEL = 'mb-[3px] text-[9px] font-bold uppercase tracking-[0.12em]';

function productIcon(code?: string): 'layers' | 'activity' | 'package' {
  if (code?.includes('STACK')) return 'layers';
  if (code?.includes('FLASH')) return 'activity';
  return 'package';
}

export function LicenseKeysPage() {
  const list = useListState({ sort: 'generatedAt:desc' });
  const { data, loading, error, reload } = useApi(() => licenseKeysApi.list(list.params), [list.depsKey]);
  const rows = data?.items ?? [];
  const { hasPermission } = useAuth();
  const canDelete = hasPermission('LICENSE_MANAGE');
  const [deleting, setDeleting] = useState<LicenseKey | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  return (
    <div>
      <div className="overview-head">
        <div>
          <h1>License Keys</h1>
          <div className="subtitle">All generated keys, including revoked history</div>
        </div>
      </div>

      <PendingBanner message={pending} />

      <div className="card">
        <div className="adv-filter">
          <div className="filter-item">
            <label htmlFor="key-search">Search</label>
            <SearchInput
              id="key-search"
              value={list.state.q}
              onChange={list.setQ}
              placeholder="Key or licence no…"
            />
          </div>
          <div className="filter-item">
            <label htmlFor="key-status">Status</label>
            <select
              id="key-status"
              className="input"
              value={list.state.filters['status'] ?? ''}
              onChange={(e) => list.setFilter('status', e.target.value)}
            >
              <option value="">All</option>
              <option value="ACTIVE">Active</option>
              <option value="REVOKED">Revoked</option>
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
            <div className="flex flex-col gap-3 p-4 max-[700px]:p-3">
              {loading && rows.length === 0 && (
                <div className={`block ${KEY_CARD} ${KEY_CARD_IDLE}`}>
                  <div className="skeleton-bar w-2/5" />
                </div>
              )}
              {!loading && rows.length === 0 && (
                <div className="table-empty">
                  <div className="empty-icon">
                    <Icon name="key" size={32} />
                  </div>
                  <div className="empty-title">No license keys</div>
                  <div className="empty-hint">Keys are generated when licenses are activated.</div>
                </div>
              )}
              {rows.map((k: LicenseKey) => {
                const revoked = k.status === 'REVOKED';
                return (
                  <article
                    key={k.keyId}
                    className={`key-card${revoked ? ' is-revoked' : ''} ${KEY_CARD_COLS} ${KEY_CARD} ${
                      revoked
                        ? 'border-danger-border bg-[linear-gradient(140deg,var(--danger-soft),var(--glass-sunken)_55%)] hover:border-danger hover:shadow-[0_0_18px_rgba(251,113,133,0.22)]'
                        : KEY_CARD_IDLE
                    }`}
                  >
                    <div
                      className={`flex size-[46px] items-center justify-center rounded-md border border-solid ${
                        revoked ? 'border-danger-border bg-danger-soft text-danger' : 'border-primary-border bg-primary-soft text-primary'
                      }`}
                    >
                      <Icon name={productIcon(k.productCode)} size={20} />
                    </div>

                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`break-all font-mono text-lg font-bold tracking-[0.08em] ${
                            revoked ? 'text-danger line-through opacity-85' : 'text-ink'
                          }`}
                        >{k.licenseKey}</span>
                        <CopyButton text={k.licenseKey} label="" />
                      </div>
                    </div>

                    <div className="min-w-0">
                      <div className={`${KEY_LABEL} text-muted`}>License</div>
                      <Link to={`/licenses/${k.licenseId}`} className="mono">
                        {k.licenseNo ?? `#${k.licenseId}`}
                      </Link>
                    </div>

                    <div className="min-w-0">
                      <div className={`${KEY_LABEL} text-muted`}>Customer</div>
                      <span className="name-cell">
                        <Avatar name={String(k.customerName ?? '?')} size={22} />
                        <span>{k.customerName ?? '—'}</span>
                      </span>
                    </div>

                    <div className="min-w-0">
                      <div className={`${KEY_LABEL} text-muted`}>Status</div>
                      <StatusBadge status={k.status} />
                      {canDelete && (
                        <button
                          type="button"
                          className="btn btn-sm btn-danger mt-1.5"
                          onClick={() => {
                            setPending(null);
                            setDeleting(k);
                          }}
                          title="Delete this key record"
                        >
                          <Icon name="trash" size={13} />
                          Delete
                        </button>
                      )}
                    </div>

                    {/* Lifecycle: generated → (revoked). The rail fills red once revoked. */}
                    <div className="min-w-0 max-[1200px]:col-span-full">
                      <div className="flex justify-between gap-2">
                        <span className={`${KEY_LABEL} text-muted`}>Generated</span>
                        {revoked && <span className={`${KEY_LABEL} text-danger`}>Revoked</span>}
                      </div>
                      <div className="my-[5px] flex items-center gap-1">
                        <span className="size-2 shrink-0 rounded-[50%] bg-primary shadow-[0_0_8px_var(--primary-glow)]" />
                        <span
                          className={`h-0.5 flex-1 rounded-[2px] ${
                            revoked ? 'bg-[linear-gradient(90deg,var(--primary),var(--danger))]' : 'bg-line-strong'
                          }`}
                        />
                        <span
                          className={`size-2 shrink-0 rounded-[50%] ${
                            revoked ? 'bg-danger shadow-[0_0_8px_rgba(251,113,133,0.6)]' : 'bg-line-strong'
                          }`}
                        />
                      </div>
                      <div className="flex justify-between gap-2">
                        <span className="whitespace-nowrap text-xs text-ink-2">{formatDateTime(k.generatedAt)}</span>
                        {revoked && <span className="whitespace-nowrap text-xs text-ink-2">{formatDateTime(k.revokedAt)}</span>}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>

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

      <ConfirmDialog
        open={deleting !== null}
        title="Delete Key"
        danger
        confirmText={deleting?.licenseNo ?? undefined}
        confirmLabel="Delete key"
        message={
          <>
            Delete this key of licence <strong className="mono">{deleting?.licenseNo}</strong> (
            {deleting?.customerName})? This only removes the key record from the list; the licence and the audit log
            are not affected. Only revoked keys can be deleted — a key still in use is refused with the reason.
          </>
        }
        onConfirm={async () => {
          if (!deleting) return;
          const res = await licenseKeysApi.remove(deleting.keyId);
          setDeleting(null);
          if (isPendingApproval(res)) setPending(res.message);
          else reload();
        }}
        onClose={() => setDeleting(null)}
      />
    </div>
  );
}
