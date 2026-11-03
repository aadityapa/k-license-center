/**
 * Product Plans — one card per product; open a product to see and manage all
 * of its plans. ?product=<id> opens that product directly.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { SearchInput } from '../../components/SearchInput';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState } from '../../components/ErrorState';
import { PendingBanner } from '../../components/PendingBanner';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { PlanFormModal } from './PlanFormModal';
import { plansApi, productsApi } from '../../services/api/endpoints';
import { isPendingApproval } from '../../services/api/http';
import { useAuth } from '../../auth/AuthContext';
import { useApi } from '../../hooks/useApi';
import { formatCurrency } from '../../utils/format';
import type { Product, ProductPlan } from '../../types';

const KEY_FORMAT_LABEL: Record<string, string> = {
  KSTK_KEY: 'Typed key',
  LIC_FILE: '.lic file',
  VBS_KEY: 'Signed key',
};

/** Plan table cells: header and body, plus the right-aligned number columns. */
const PP_TH = 'whitespace-nowrap border-0 border-b border-solid border-line px-2 py-2.5 text-xs font-bold uppercase tracking-[0.05em] text-muted';
const PP_TD = 'whitespace-nowrap border-0 border-b border-solid border-line px-2 py-2.5 [tr:last-child>&]:border-b-0';

const PALETTE = ['#3b82f6', '#22c55e', '#f97316', '#8b5cf6', '#ec4899', '#14b8a6', '#f59e0b', '#0ea5e9'];

/** All plans, across as many pages as the API needs (it caps a page at 100). */
async function loadAllPlans(): Promise<ProductPlan[]> {
  const out: ProductPlan[] = [];
  for (let page = 1; page <= 50; page += 1) {
    const r = await plansApi.list({ page, pageSize: 100, sort: 'planName:asc' });
    out.push(...r.items);
    if (out.length >= r.total || r.items.length === 0) break;
  }
  return out;
}

const durationLabel = (p: ProductPlan) => (p.isLifetime ? 'Lifetime' : `${p.durationDays} days`);
/** Lifetime last, otherwise shortest first. */
const planOrder = (a: ProductPlan, b: ProductPlan) =>
  (a.isLifetime ? 1e9 : a.durationDays ?? 0) - (b.isLifetime ? 1e9 : b.durationDays ?? 0) || a.planName.localeCompare(b.planName);

export function PlansPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission('PLAN_MANAGE');
  const [params, setParams] = useSearchParams();

  const plansRes = useApi(loadAllPlans, []);
  const productsRes = useApi(() => productsApi.list({ pageSize: 100, sort: 'productName:asc' }), []);
  const plans = plansRes.data ?? [];
  const products: Product[] = productsRes.data?.items ?? [];

  const [q, setQ] = useState('');
  const [statusFilter, setStatusFilter] = useState<'' | 'ACTIVE' | 'INACTIVE'>('');
  const [open, setOpen] = useState<Set<number>>(() => {
    const id = Number(params.get('product'));
    return new Set(Number.isInteger(id) && id > 0 ? [id] : []);
  });
  const [modal, setModal] = useState<{ open: boolean; plan: ProductPlan | null; productId?: number }>({ open: false, plan: null });
  const [deleting, setDeleting] = useState<ProductPlan | null>(null);
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const reload = () => {
    plansRes.reload();
    productsRes.reload();
  };

  useEffect(() => {
    if (menuFor === null) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuFor(null);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setMenuFor(null);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuFor]);

  const toggle = (productId: number) => {
    setOpen((cur) => {
      const next = new Set(cur);
      if (next.has(productId)) next.delete(productId);
      else next.add(productId);
      // Keep the URL pointing at the last product opened, so a link can be shared.
      if (next.has(productId)) setParams({ product: String(productId) }, { replace: true });
      else if (params.get('product') === String(productId)) setParams({}, { replace: true });
      return next;
    });
  };

  /** Products with their plans, after search and status filters. */
  const groups = useMemo(() => {
    const term = q.trim().toLowerCase();
    return products
      .map((product, i) => {
        const all = plans.filter((p) => p.productId === product.productId).sort(planOrder);
        const byStatus = statusFilter ? all.filter((p) => p.status === statusFilter) : all;
        const productHit =
          !term || product.productName.toLowerCase().includes(term) || product.productCode.toLowerCase().includes(term);
        const shown = productHit
          ? byStatus
          : byStatus.filter((p) => p.planName.toLowerCase().includes(term) || p.planCode.toLowerCase().includes(term));
        return { product, all, shown, color: PALETTE[i % PALETTE.length]!, matches: productHit || shown.length > 0 };
      })
      .filter((g) => g.matches);
  }, [products, plans, q, statusFilter]);

  // A search that matches plans opens their products, so the hits are visible.
  const searching = q.trim() !== '';

  const setStatus = async (plan: ProductPlan, status: 'ACTIVE' | 'INACTIVE') => {
    setMenuFor(null);
    setBusyId(plan.planId);
    setPending(null);
    setNotice(null);
    try {
      const res = await plansApi.update(plan.planId, { status });
      if (isPendingApproval(res)) setPending(res.message);
      else reload();
    } finally {
      setBusyId(null);
    }
  };

  const totalActive = plans.filter((p) => p.status === 'ACTIVE').length;
  const loading = plansRes.loading || productsRes.loading;
  const error = plansRes.error ?? productsRes.error;

  return (
    <div>
      <div className="overview-head">
        <div>
          <h1>Product Plans</h1>
          <div className="subtitle">Open a product to see and manage all of its plans</div>
        </div>
        <div className="head-meta">
          <span className="meta-item">
            Products: <strong>{products.length}</strong>
          </span>
          <span className="meta-item">
            Active plans: <strong>{totalActive}</strong>
          </span>
          {canManage && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setPending(null);
                setNotice(null);
                setModal({ open: true, plan: null });
              }}
            >
              <Icon name="plus" size={15} />
              New Plan
            </button>
          )}
        </div>
      </div>

      <PendingBanner message={pending} />
      {notice && (
        <div className="alert alert-success" role="status">
          <Icon name="check" size={16} />
          <div>{notice}</div>
        </div>
      )}

      <div className="card">
        <div className="adv-filter">
          <div className="filter-item">
            <label htmlFor="plan-search">Search</label>
            <SearchInput id="plan-search" value={q} onChange={setQ} placeholder="Product, plan code or name…" />
          </div>
          <div className="filter-item">
            <label htmlFor="plan-status">Plans</label>
            <select
              id="plan-status"
              className="input"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as '' | 'ACTIVE' | 'INACTIVE')}
            >
              <option value="">All</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Archived</option>
            </select>
          </div>
          <div className="adv-filter-right">
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setOpen(new Set(groups.map((g) => g.product.productId)))}>
              Expand all
            </button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setOpen(new Set())}>
              Collapse all
            </button>
          </div>
        </div>

        {error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : loading && products.length === 0 ? (
          <div className="fullpage-center h-[200px]">
            <Spinner size={26} />
          </div>
        ) : groups.length === 0 ? (
          <div className="table-empty">
            <div className="empty-icon">
              <Icon name="layers" size={32} />
            </div>
            <div className="empty-title">{q ? 'Nothing matches the search' : 'No products yet'}</div>
            <div className="empty-hint">{q ? 'Try another product or plan name.' : 'Create a product first, then add its plans.'}</div>
          </div>
        ) : (
          <div className="flex flex-col gap-2.5 p-3.5">
            {groups.map(({ product, all, shown, color }) => {
              const isOpen = open.has(product.productId) || (searching && shown.length > 0);
              const active = all.filter((p) => p.status === 'ACTIVE').length;
              const prices = all.map((p) => p.price).filter((v): v is number => v != null);
              const priceText =
                prices.length === 0
                  ? 'No prices set'
                  : Math.min(...prices) === Math.max(...prices)
                    ? formatCurrency(prices[0], 'INR')
                    : `${formatCurrency(Math.min(...prices), 'INR')} – ${formatCurrency(Math.max(...prices), 'INR')}`;
              return (
                <section
                  key={product.productId}
                  className={`pp-product ${isOpen ? 'is-open ' : ''}overflow-visible rounded-[14px] border border-solid bg-surface transition-[box-shadow,border-color] duration-150 ease-[ease] ${
                    isOpen ? 'border-[color:color-mix(in_srgb,var(--primary)_45%,var(--border))] shadow-sm' : 'border-line'
                  }`}
                >
                  <button
                    type="button"
                    className="pp-head m-0 box-border grid w-full cursor-pointer appearance-none grid-cols-[44px_1fr_auto_24px] items-center gap-3.5 rounded-[14px] border-0 bg-transparent px-4 py-3.5 text-inherit shadow-none [font:inherit] [letter-spacing:inherit] [text-align:inherit] hover:bg-[color:color-mix(in_srgb,var(--primary)_5%,transparent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary max-[760px]:grid-cols-[40px_1fr_20px]"
                    onClick={() => toggle(product.productId)}
                    aria-expanded={isOpen}
                    aria-controls={`pp-body-${product.productId}`}
                  >
                    <span className="flex size-11 items-center justify-center rounded-[12px] text-md font-extrabold text-white" style={{ background: color }}>
                      {product.productName.slice(0, 2).toUpperCase()}
                    </span>
                    <span className="flex min-w-0 flex-col gap-[3px]">
                      <span className="pp-name flex items-center gap-2 text-[15.5px] font-bold text-ink">
                        {product.productName}
                        {product.status !== 'ACTIVE' && <StatusBadge status={product.status} />}
                      </span>
                      <span className="flex items-center gap-2 text-sm text-muted">
                        <span className="mono">{product.productCode}</span>
                        {product.keyFormat && <span className="rounded-full border border-solid border-line px-2 py-px text-xs">{KEY_FORMAT_LABEL[product.keyFormat] ?? product.keyFormat}</span>}
                      </span>
                    </span>
                    <span className="flex items-center gap-[18px] whitespace-nowrap text-[13px] text-ink-2 max-[760px]:col-[2/-1] max-[760px]:row-[2] max-[760px]:gap-3">
                      <span>
                        <b className="text-[15px] text-ink">{all.length}</b> plan{all.length === 1 ? '' : 's'}
                      </span>
                      <span>
                        <b className="text-[15px] text-ink">{active}</b> active
                      </span>
                      <span className="text-[12.5px] text-muted">{priceText}</span>
                    </span>
                    <span
                      className={`flex text-muted transition-transform duration-200 ease-[ease] max-[760px]:col-[3] max-[760px]:row-[1] ${isOpen ? 'rotate-180' : ''}`}
                      aria-hidden="true"
                    >
                      <Icon name="chevron-down" size={18} />
                    </span>
                  </button>

                  {isOpen && (
                    <div className="border-0 border-t border-solid border-line px-4 pb-3.5 pt-1" id={`pp-body-${product.productId}`}>
                      {shown.length === 0 ? (
                        <div className="px-1 py-[18px] text-sm text-muted">
                          {all.length === 0 ? 'This product has no plans yet.' : 'No plans match the filter.'}
                        </div>
                      ) : (
                        <div className="overflow-x-auto">
                          <table className="pp-table w-full border-collapse text-[13.5px]">
                            <thead>
                              <tr>
                                <th className={`${PP_TH} text-left`}>Plan</th>
                                <th className={`${PP_TH} text-left`}>Code</th>
                                <th className={`${PP_TH} text-left`}>Duration</th>
                                <th className={`${PP_TH} text-right`}>Price</th>
                                <th className={`${PP_TH} text-right`}>Activations</th>
                                <th className={`${PP_TH} text-right`}>Users</th>
                                <th className={`${PP_TH} text-right`}>Branches</th>
                                <th className={`${PP_TH} text-left`}>Status</th>
                                {canManage && <th className={`${PP_TH} text-right`}>Actions</th>}
                              </tr>
                            </thead>
                            <tbody>
                              {shown.map((p) => (
                                <tr key={p.planId} className={p.status !== 'ACTIVE' ? '[&>td]:text-muted' : ''}>
                                  <td className={`pp-plan-name ${PP_TD} font-semibold`}>{p.planName}</td>
                                  <td className={PP_TD}>
                                    <span className="font-mono text-xs font-bold uppercase tracking-[0.1em] text-muted">{p.planCode}</span>
                                  </td>
                                  <td className={PP_TD}>
                                    <span className="inline-flex items-center gap-1.5 whitespace-nowrap [&_svg]:text-primary [&_svg]:opacity-85">
                                      <Icon name={p.isLifetime ? 'shield' : 'clock'} size={13} />
                                      {durationLabel(p)}
                                    </span>
                                  </td>
                                  <td className={`${PP_TD} text-right`}>{p.price == null ? <span className="muted">—</span> : formatCurrency(p.price, p.currency)}</td>
                                  <td className={`${PP_TD} text-right`}>{p.maxActivations}</td>
                                  <td className={`${PP_TD} text-right`}>{p.maxUsers ?? '—'}</td>
                                  <td className={`${PP_TD} text-right`}>{p.maxBranches ?? '—'}</td>
                                  <td className={PP_TD}>
                                    <StatusBadge status={p.status === 'INACTIVE' ? 'ARCHIVED' : p.status} />
                                  </td>
                                  {canManage && (
                                    <td className={`${PP_TD} text-right`}>
                                      <div className="row-actions justify-end" onClick={(e) => e.stopPropagation()}>
                                        <button
                                          type="button"
                                          className="round-btn"
                                          title="Edit plan"
                                          aria-label={`Edit ${p.planName}`}
                                          onClick={() => setModal({ open: true, plan: p })}
                                        >
                                          <Icon name="edit" size={14} />
                                        </button>
                                        <button
                                          type="button"
                                          className="round-btn"
                                          title="More actions"
                                          aria-label={`More actions for ${p.planName}`}
                                          aria-expanded={menuFor === p.planId}
                                          disabled={busyId === p.planId}
                                          onClick={() => setMenuFor(menuFor === p.planId ? null : p.planId)}
                                        >
                                          <Icon name="more" size={14} />
                                        </button>
                                        {menuFor === p.planId && (
                                          <div className="row-menu" ref={menuRef} role="menu">
                                            <button type="button" role="menuitem" onClick={() => setModal({ open: true, plan: p })}>
                                              <Icon name="edit" size={13} />
                                              Edit plan
                                            </button>
                                            {p.status === 'ACTIVE' ? (
                                              <button type="button" role="menuitem" onClick={() => void setStatus(p, 'INACTIVE')}>
                                                <Icon name="ban" size={13} />
                                                Archive plan
                                              </button>
                                            ) : (
                                              <button type="button" role="menuitem" onClick={() => void setStatus(p, 'ACTIVE')}>
                                                <Icon name="check" size={13} />
                                                Restore plan
                                              </button>
                                            )}
                                            <button
                                              type="button"
                                              role="menuitem"
                                              className="danger"
                                              onClick={() => {
                                                setMenuFor(null);
                                                setPending(null);
                                                setNotice(null);
                                                setDeleting(p);
                                              }}
                                            >
                                              <Icon name="trash" size={13} />
                                              Delete plan
                                            </button>
                                          </div>
                                        )}
                                      </div>
                                    </td>
                                  )}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      <div className="flex flex-wrap items-center justify-between gap-2.5 pt-3">
                        <Link to={`/products/${product.productId}`} className="dk-viewall">
                          Open product details
                        </Link>
                        {canManage && (
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => {
                              setPending(null);
                              setNotice(null);
                              setModal({ open: true, plan: null, productId: product.productId });
                            }}
                          >
                            <Icon name="plus" size={14} />
                            Add plan to {product.productName}
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        )}
      </div>

      <PlanFormModal
        open={modal.open}
        plan={modal.plan}
        fixedProductId={modal.productId}
        onClose={() => setModal({ open: false, plan: null })}
        onSaved={reload}
        onPending={setPending}
      />

      <ConfirmDialog
        open={deleting !== null}
        title="Delete Plan"
        danger
        confirmText={deleting?.planCode}
        confirmLabel="Delete plan"
        message={
          <>
            Delete the plan <strong>{deleting?.planName}</strong> ({deleting?.planCode}) of {deleting?.productName}? This is
            only possible while no licence uses it. A plan that licences use should be <strong>archived</strong> instead —
            it then can no longer be chosen for new licences, and existing ones keep it.
          </>
        }
        onConfirm={async () => {
          if (!deleting) return;
          const res = await plansApi.remove(deleting.planId);
          const name = deleting.planName;
          setDeleting(null);
          if (isPendingApproval(res)) setPending(res.message);
          else {
            setNotice(`Plan "${name}" deleted.`);
            reload();
          }
        }}
        onClose={() => setDeleting(null)}
      />
    </div>
  );
}
