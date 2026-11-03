import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState } from '../../components/ErrorState';
import { PendingBanner } from '../../components/PendingBanner';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { RowDelete } from '../../components/RowDelete';
import { ProductFormModal } from './ProductFormModal';
import { PlanFormModal } from './PlanFormModal';
import { activationsApi, licensesApi, plansApi, productsApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useAuth } from '../../auth/AuthContext';
import { formatCurrency, formatDate, formatDateTime, formatNumber, expiryLabel } from '../../utils/format';
import type { ProductPlan } from '../../types';

export function ProductDetailPage() {
  const { id } = useParams();
  const productId = Number(id);
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const [editOpen, setEditOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [planModal, setPlanModal] = useState<{ open: boolean; plan: ProductPlan | null }>({ open: false, plan: null });

  const product = useApi(() => productsApi.get(productId), [productId]);
  const plans = useApi(() => plansApi.list({ productId, pageSize: 100 }), [productId]);
  const licenses = useApi(() => licensesApi.list({ productId, pageSize: 10, sort: 'createdAt:desc' }), [productId]);
  const activations = useApi(
    () => activationsApi.list({ productId, pageSize: 10, sort: 'activatedAt:desc' }),
    [productId],
  );

  if (product.loading) {
    return (
      <div className="fullpage-center h-[50vh]">
        <Spinner size={30} />
      </div>
    );
  }

  if (product.error) {
    return (
      <div className="card">
        <ErrorState error={product.error} onRetry={product.reload} />
      </div>
    );
  }

  const p = product.data;
  if (!p) return null;

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: 'Products', to: '/products' }, { label: p.productName }]}
        title={
          <>
            {p.productName} <StatusBadge status={p.status} />
          </>
        }
        subtitle={
          <>
            <span className="mono">{p.productCode}</span> · Key prefix <span className="mono">{p.keyPrefix}</span>
            {p.version && <> · v{p.version}</>}
          </>
        }
        actions={
          hasPermission('PRODUCT_MANAGE') && (
            <>
              <button type="button" className="btn" onClick={() => setEditOpen(true)}>
                <Icon name="edit" size={15} />
                Edit Product
              </button>
              <RowDelete
                compact={false}
                what={`product ${p.productName}`}
                confirmText={p.productCode}
                detail="Its plans and API clients are deleted with it. A product that still has licences cannot be deleted."
                onDelete={() => {
                  setPending(null);
                  return productsApi.remove(p.productId);
                }}
                onDeleted={() => navigate('/products', { replace: true })}
                onPending={setPending}
              />
            </>
          )
        }
      />

      <PendingBanner message={pending} />

      <div className="metric-grid">
        <div className="metric-card">
          <div>
            <div className="metric-label">Total Licenses</div>
            <div className="metric-value">{licenses.loading ? '…' : formatNumber(licenses.data?.total ?? 0)}</div>
          </div>
          <div className="metric-icon">
            <Icon name="file-text" size={18} />
          </div>
        </div>
        <div className="metric-card">
          <div>
            <div className="metric-label">Plans</div>
            <div className="metric-value">
              {plans.loading ? '…' : formatNumber(plans.data?.total ?? plans.data?.items.length ?? 0)}
            </div>
          </div>
          <div className="metric-icon">
            <Icon name="layers" size={18} />
          </div>
        </div>
        <div className="metric-card accent-purple">
          <div>
            <div className="metric-label">Activations</div>
            <div className="metric-value">{activations.loading ? '…' : formatNumber(activations.data?.total ?? 0)}</div>
          </div>
          <div className="metric-icon">
            <Icon name="activity" size={18} />
          </div>
        </div>
      </div>

      {p.description && (
        <div className="card mb-4">
          <div className="card-body">{p.description}</div>
        </div>
      )}

      <div className="card mb-4">
        <div className="card-header">
          <h2>Plans</h2>
          {hasPermission('PLAN_MANAGE') && (
            <button type="button" className="btn btn-sm btn-primary" onClick={() => setPlanModal({ open: true, plan: null })}>
              <Icon name="plus" size={14} />
              New Plan
            </button>
          )}
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Duration</th>
                <th className="num">Price</th>
                <th className="num">Max Activations</th>
                <th className="num">Max Users</th>
                <th className="num">Max Branches</th>
                <th>Status</th>
                {hasPermission('PLAN_MANAGE') && <th />}
              </tr>
            </thead>
            <tbody>
              {plans.loading && (
                <tr>
                  <td colSpan={9}>
                    <div className="table-empty">
                      <Spinner size={20} />
                    </div>
                  </td>
                </tr>
              )}
              {!plans.loading && (plans.data?.items ?? []).length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="table-empty">No plans for this product yet.</div>
                  </td>
                </tr>
              )}
              {(plans.data?.items ?? []).map((plan) => (
                <tr key={plan.planId}>
                  <td className="mono">{plan.planCode}</td>
                  <td>{plan.planName}</td>
                  <td>{plan.isLifetime ? 'Lifetime' : `${plan.durationDays} days`}</td>
                  <td className="num">{formatCurrency(plan.price, plan.currency)}</td>
                  <td className="num">{plan.maxActivations}</td>
                  <td className="num">{plan.maxUsers ?? '—'}</td>
                  <td className="num">{plan.maxBranches ?? '—'}</td>
                  <td>
                    <StatusBadge status={plan.status} />
                  </td>
                  {hasPermission('PLAN_MANAGE') && (
                    <td>
                      <button type="button" className="btn btn-sm" onClick={() => setPlanModal({ open: true, plan })}>
                        <Icon name="edit" size={14} />
                        Edit
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-2 gap-4">
        <div className="card">
          <div className="card-header">
            <h2>Recent Licenses</h2>
            <Link to={`/licenses?productId=${p.productId}`} className="btn-link">
              View all
            </Link>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>License</th>
                  <th>Customer</th>
                  <th>Status</th>
                  <th>Expiry</th>
                </tr>
              </thead>
              <tbody>
                {!licenses.loading && (licenses.data?.items ?? []).length === 0 && (
                  <tr>
                    <td colSpan={4}>
                      <div className="table-empty">No licenses.</div>
                    </td>
                  </tr>
                )}
                {(licenses.data?.items ?? []).map((l) => (
                  <tr key={l.licenseId}>
                    <td>
                      <Link to={`/licenses/${l.licenseId}`} className="mono">
                        {l.licenseNo}
                      </Link>
                    </td>
                    <td>{l.customerName ?? l.customerId}</td>
                    <td>
                      <StatusBadge status={l.status} />
                    </td>
                    <td className="nowrap">{expiryLabel(l.expiryDate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h2>Recent Activations</h2>
            <Link to={`/activations?productId=${p.productId}`} className="btn-link">
              View all
            </Link>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>License</th>
                  <th>Device</th>
                  <th>Status</th>
                  <th>Activated</th>
                </tr>
              </thead>
              <tbody>
                {!activations.loading && (activations.data?.items ?? []).length === 0 && (
                  <tr>
                    <td colSpan={4}>
                      <div className="table-empty">No activations.</div>
                    </td>
                  </tr>
                )}
                {(activations.data?.items ?? []).map((a) => (
                  <tr key={a.activationId}>
                    <td>
                      <Link to={`/licenses/${a.licenseId}`} className="mono">
                        {a.licenseNo ?? a.licenseId}
                      </Link>
                    </td>
                    <td>{a.deviceName ?? a.installationId}</td>
                    <td>
                      <StatusBadge status={a.status} />
                    </td>
                    <td className="nowrap">{formatDateTime(a.activatedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="muted mt-3.5 text-sm">
        Created {formatDate(p.createdAt)} · Updated {formatDate(p.updatedAt)}
      </div>

      <ProductFormModal
        open={editOpen}
        product={p}
        onClose={() => setEditOpen(false)}
        onSaved={product.reload}
        onPending={setPending}
      />
      <PlanFormModal
        open={planModal.open}
        plan={planModal.plan}
        fixedProductId={p.productId}
        onClose={() => setPlanModal({ open: false, plan: null })}
        onSaved={plans.reload}
        onPending={setPending}
      />
    </div>
  );
}
