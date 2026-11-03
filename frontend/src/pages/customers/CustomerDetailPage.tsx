import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState } from '../../components/ErrorState';
import { PendingBanner } from '../../components/PendingBanner';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { isPendingApproval } from '../../services/api/http';
import { CustomerFormModal } from './CustomerFormModal';
import { CreateLicenseModal, LicenseActionButtons } from '../licenses/LicenseActions';
import { customersApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useAuth } from '../../auth/AuthContext';
import { formatCurrency, formatDate, formatDateTime, expiryLabel } from '../../utils/format';
import type { License } from '../../types';

function LicenseCard({
  license,
  onChanged,
  onPending,
}: {
  license: License;
  onChanged: () => void;
  onPending: (message: string) => void;
}) {
  return (
    <div className="card shadow-none">
      <div className="card-body px-3.5 py-3">
        <div className="flex-between">
          <div>
            <Link to={`/licenses/${license.licenseId}`} className="mono font-semibold">
              {license.licenseNo}
            </Link>{' '}
            <StatusBadge status={license.status} />
          </div>
          <LicenseActionButtons license={license} onChanged={onChanged} onPending={onPending} small />
        </div>
        <div className="def-grid mt-2.5">
          <div className="def-item">
            <div className="def-label">Product / Plan</div>
            <div className="def-value">
              {license.productName ?? license.productCode} — {license.planName ?? license.planId}
            </div>
          </div>
          <div className="def-item">
            <div className="def-label">Expiry</div>
            <div className="def-value">{expiryLabel(license.expiryDate)}</div>
          </div>
          <div className="def-item">
            <div className="def-label">Activations</div>
            <div className="def-value">
              {license.currentActivations} / {license.maxActivations}
            </div>
          </div>
          {license.licenseKey && (
            <div className="def-item">
              <div className="def-label">Key</div>
              <div className="def-value mono !text-sm">{license.licenseKey}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function CustomerDetailPage() {
  const { id } = useParams();
  const customerId = Number(id);
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const customer = useApi(() => customersApi.get(customerId), [customerId]);
  const detail = useApi(() => customersApi.licenses(customerId), [customerId]);
  const [editOpen, setEditOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [tab, setTab] = useState<'licenses' | 'keys' | 'activations' | 'renewals' | 'history'>('licenses');

  if (customer.loading) {
    return (
      <div className="fullpage-center h-[50vh]">
        <Spinner size={30} />
      </div>
    );
  }

  if (customer.error) {
    return (
      <div className="card">
        <ErrorState error={customer.error} onRetry={customer.reload} />
      </div>
    );
  }

  const c = customer.data;
  if (!c) return null;

  const licenses = detail.data?.licenses ?? [];
  const keys = detail.data?.keys ?? [];
  const activations = detail.data?.activations ?? [];
  const renewals = detail.data?.renewals ?? [];
  const history = detail.data?.history ?? [];

  // Group licenses by product for readability
  const byProduct = new Map<string, License[]>();
  for (const l of licenses) {
    const key = l.productName ?? l.productCode ?? String(l.productId);
    const arr = byProduct.get(key) ?? [];
    arr.push(l);
    byProduct.set(key, arr);
  }

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: 'Customers', to: '/customers' }, { label: c.companyName }]}
        title={
          <>
            {c.companyName} <StatusBadge status={c.status} />
          </>
        }
        subtitle={<span className="mono">{c.customerCode}</span>}
        actions={
          <>
            {hasPermission('LICENSE_CREATE') && (
              <button type="button" className="btn btn-primary" onClick={() => setCreateOpen(true)}>
                <Icon name="plus" size={15} />
                Create License
              </button>
            )}
            {hasPermission('CUSTOMER_MANAGE') && (
              <button type="button" className="btn" onClick={() => setEditOpen(true)}>
                <Icon name="edit" size={15} />
                Edit Customer
              </button>
            )}
            {hasPermission('CUSTOMER_MANAGE') && (
              <button type="button" className="btn btn-danger-outline" onClick={() => setDeleting(true)}>
                <Icon name="trash" size={15} />
                Delete
              </button>
            )}
          </>
        }
      />

      <PendingBanner message={pending} />

      <div className="card mb-4">
        <div className="card-header">
          <h2>Contact Information</h2>
        </div>
        <div className="card-body">
          <div className="def-grid">
            <div className="def-item">
              <div className="def-label">Contact Person</div>
              <div className="def-value">{c.contactPerson ?? '—'}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Email</div>
              <div className="def-value">{c.email ? <a href={`mailto:${c.email}`}>{c.email}</a> : '—'}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Mobile</div>
              <div className="def-value">{c.mobile ?? '—'}</div>
            </div>
            <div className="def-item">
              <div className="def-label">WhatsApp</div>
              <div className="def-value">{c.whatsapp ?? '—'}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Address</div>
              <div className="def-value">
                {[c.addressLine1, c.addressLine2, c.city, c.state, c.country].filter(Boolean).join(', ') || '—'}
              </div>
            </div>
            <div className="def-item">
              <div className="def-label">GST Number</div>
              <div className="def-value mono">{c.gstNumber ?? '—'}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Customer Since</div>
              <div className="def-value">{formatDate(c.createdAt)}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="tabs">
        {(
          [
            ['licenses', `Licenses (${licenses.length})`],
            ['keys', `Keys (${keys.length})`],
            ['activations', `Activations (${activations.length})`],
            ['renewals', `Renewals (${renewals.length})`],
            ['history', `History (${history.length})`],
          ] as const
        ).map(([key, label]) => (
          <button key={key} type="button" className={`tab ${tab === key ? 'active' : ''}`} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>

      {detail.loading && (
        <div className="card">
          <div className="table-empty">
            <Spinner size={22} />
          </div>
        </div>
      )}
      {detail.error && (
        <div className="card">
          <ErrorState error={detail.error} onRetry={detail.reload} />
        </div>
      )}

      {!detail.loading && !detail.error && tab === 'licenses' && (
        <>
          {licenses.length === 0 && (
            <div className="card">
              <div className="table-empty">
                <div className="empty-icon">
                  <Icon name="inbox" size={32} />
                </div>
                <div className="empty-title">No licenses yet</div>
                <div className="empty-hint">Create a license for this customer to get started.</div>
              </div>
            </div>
          )}
          {[...byProduct.entries()].map(([productName, productLicenses]) => (
            <div key={productName} className="mb-4">
              <h3 className="mx-0 mb-2 mt-0 text-[13.5px] text-ink-2">{productName}</h3>
              <div className="stack-8">
                {productLicenses.map((l) => (
                  <LicenseCard key={l.licenseId} license={l} onChanged={detail.reload} onPending={setPending} />
                ))}
              </div>
            </div>
          ))}
        </>
      )}

      {!detail.loading && !detail.error && tab === 'keys' && (
        <div className="card">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>License</th>
                  <th>Status</th>
                  <th>Generated</th>
                </tr>
              </thead>
              <tbody>
                {keys.length === 0 && (
                  <tr>
                    <td colSpan={4}>
                      <div className="table-empty">No keys generated yet.</div>
                    </td>
                  </tr>
                )}
                {keys.map((k) => (
                  <tr key={k.keyId}>
                    <td className="mono">{k.licenseKey}</td>
                    <td>
                      <Link to={`/licenses/${k.licenseId}`} className="mono">
                        {k.licenseNo ?? `#${k.licenseId}`}
                      </Link>
                    </td>
                    <td>
                      <StatusBadge status={k.status} />
                    </td>
                    <td className="nowrap">{formatDateTime(k.generatedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!detail.loading && !detail.error && tab === 'activations' && (
        <div className="card">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>License</th>
                  <th>Device</th>
                  <th>OS</th>
                  <th>Status</th>
                  <th>Activated</th>
                  <th>Last Heartbeat</th>
                </tr>
              </thead>
              <tbody>
                {activations.length === 0 && (
                  <tr>
                    <td colSpan={6}>
                      <div className="table-empty">No activations.</div>
                    </td>
                  </tr>
                )}
                {activations.map((a) => (
                  <tr key={a.activationId}>
                    <td>
                      <Link to={`/licenses/${a.licenseId}`} className="mono">
                        {a.licenseNo ?? `#${a.licenseId}`}
                      </Link>
                    </td>
                    <td>{a.deviceName ?? a.installationId}</td>
                    <td>{a.osInfo ?? '—'}</td>
                    <td>
                      <StatusBadge status={a.status} />
                    </td>
                    <td className="nowrap">{formatDateTime(a.activatedAt)}</td>
                    <td className="nowrap">{formatDateTime(a.lastHeartbeatAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!detail.loading && !detail.error && tab === 'renewals' && (
        <div className="card">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>License</th>
                  <th>Plan</th>
                  <th>New Expiry</th>
                  <th className="num">Amount</th>
                  <th>Payment Ref</th>
                </tr>
              </thead>
              <tbody>
                {renewals.length === 0 && (
                  <tr>
                    <td colSpan={6}>
                      <div className="table-empty">No renewals.</div>
                    </td>
                  </tr>
                )}
                {renewals.map((r) => (
                  <tr key={r.renewalId}>
                    <td className="nowrap">{formatDate(r.renewalDate)}</td>
                    <td>
                      <Link to={`/licenses/${r.licenseId}`} className="mono">
                        {r.licenseNo ?? `#${r.licenseId}`}
                      </Link>
                    </td>
                    <td>{r.newPlanName ?? r.newPlanId ?? '—'}</td>
                    <td className="nowrap">{r.newExpiryDate ? formatDate(r.newExpiryDate) : 'Lifetime'}</td>
                    <td className="num">{formatCurrency(r.amount, r.currency)}</td>
                    <td>{r.paymentRef ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!detail.loading && !detail.error && tab === 'history' && (
        <div className="card">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>License</th>
                  <th>Transition</th>
                  <th>By</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {history.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      <div className="table-empty">No license state changes.</div>
                    </td>
                  </tr>
                )}
                {history.map((h) => (
                  <tr key={h.historyId}>
                    <td className="nowrap">{formatDateTime(h.changedAt)}</td>
                    <td>
                      <Link to={`/licenses/${h.licenseId}`} className="mono">
                        #{h.licenseId}
                      </Link>
                    </td>
                    <td>
                      {h.oldStatus ? <StatusBadge status={h.oldStatus} /> : <span className="muted">new</span>}{' '}
                      <Icon name="chevron-right" size={12} className="muted align-middle" />{' '}
                      <StatusBadge status={h.newStatus} />
                    </td>
                    <td>{h.changedBy ?? '—'}</td>
                    <td>{h.reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Typing the customer code guards against deleting the wrong one. A
          customer with licences is refused by the server with the reason, which
          the dialog shows; mark them Inactive via Edit instead. */}
      <ConfirmDialog
        open={deleting}
        title="Delete Customer"
        danger
        confirmText={c.customerCode}
        confirmLabel="Delete customer"
        message={
          <>
            Permanently delete <strong>{c.companyName}</strong>? This is only possible for a customer
            with no licences. A customer who has licences should be set to <strong>Inactive</strong> instead,
            so the record of who holds them is kept.
          </>
        }
        onConfirm={async () => {
          const res = await customersApi.remove(c.customerId);
          setDeleting(false);
          if (isPendingApproval(res)) {
            setPending(res.message);
          } else {
            navigate('/customers', { replace: true });
          }
        }}
        onClose={() => setDeleting(false)}
      />

      <CustomerFormModal
        open={editOpen}
        customer={c}
        onClose={() => setEditOpen(false)}
        onSaved={customer.reload}
        onPending={setPending}
      />
      <CreateLicenseModal
        open={createOpen}
        customerId={c.customerId}
        onClose={() => setCreateOpen(false)}
        onCreated={(licenseId) => navigate(`/licenses/${licenseId}`)}
        onPending={setPending}
      />
    </div>
  );
}
