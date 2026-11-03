import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { Modal } from '../../components/Modal';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { FormField } from '../../components/FormField';
import { ErrorBanner } from '../../components/ErrorState';
import { Spinner } from '../../components/Spinner';
import { CopyButton } from '../../components/CopyButton';
import { Icon } from '../../components/Icon';
import { customersApi, licensesApi, plansApi, productsApi } from '../../services/api/endpoints';
import { isPendingApproval } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import { useAuth } from '../../auth/AuthContext';
import type { License } from '../../types';

/* ------------------------------------------------------------------ */
/* Renew modal                                                         */
/* ------------------------------------------------------------------ */

interface RenewModalProps {
  open: boolean;
  license: Pick<License, 'licenseId' | 'licenseNo' | 'productId' | 'planId' | 'planName'>;
  onClose: () => void;
  onDone: () => void;
  /** Called instead of onDone when the renewal was queued for a checker. */
  onPending?: (message: string) => void;
}

export function RenewLicenseModal({ open, license, onClose, onDone, onPending }: RenewModalProps) {
  const plans = useApi(
    () => plansApi.list({ productId: license.productId, pageSize: 100, status: 'ACTIVE' }),
    [license.productId, open],
  );
  const [form, setForm] = useState({ planId: '', amount: '', paymentRef: '', notes: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (open) {
      setForm({ planId: String(license.planId), amount: '', paymentRef: '', notes: '' });
      setError(null);
    }
  }, [open, license.planId]);

  const selectedPlan = useMemo(
    () => (plans.data?.items ?? []).find((p) => String(p.planId) === form.planId),
    [plans.data, form.planId],
  );

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await licensesApi.renew(license.licenseId, {
        planId: form.planId ? Number(form.planId) : undefined,
        amount: form.amount === '' ? undefined : Number(form.amount),
        paymentRef: form.paymentRef.trim() || undefined,
        notes: form.notes.trim() || undefined,
      });
      if (isPendingApproval(res)) onPending?.(res.message);
      else onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Renewal failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Renew License — ${license.licenseNo}`} open={open} onClose={onClose}>
      <ErrorBanner error={error} />
      <form onSubmit={submit}>
        <FormField label="Plan" required hint="Renewing on a different plan changes limits and duration.">
          <select className="input" value={form.planId} onChange={(e) => setForm((f) => ({ ...f, planId: e.target.value }))}>
            {(plans.data?.items ?? []).map((p) => (
              <option key={p.planId} value={p.planId}>
                {p.planName} ({p.isLifetime ? 'Lifetime' : `${p.durationDays} days`})
              </option>
            ))}
          </select>
        </FormField>
        <div className="form-grid">
          <FormField label={`Amount${selectedPlan?.currency ? ` (${selectedPlan.currency})` : ''}`}>
            <input
              className="input"
              type="number"
              min={0}
              step="0.01"
              value={form.amount}
              onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
              placeholder={selectedPlan?.price != null ? String(selectedPlan.price) : '0.00'}
            />
          </FormField>
          <FormField label="Payment Reference">
            <input
              className="input"
              value={form.paymentRef}
              onChange={(e) => setForm((f) => ({ ...f, paymentRef: e.target.value }))}
              placeholder="Invoice / UTR number"
            />
          </FormField>
        </div>
        <FormField label="Notes">
          <textarea className="input" value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} rows={2} />
        </FormField>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !form.planId}>
            {busy ? <Spinner size={13} /> : <Icon name="refresh" size={15} />}
            Renew License
          </button>
        </div>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/* Create license modal (product -> plan)                              */
/* ------------------------------------------------------------------ */

interface CreateLicenseModalProps {
  open: boolean;
  customerId?: number; // when opened from a customer page
  onClose: () => void;
  onCreated: (licenseId: number) => void;
  /** Called instead of onCreated when the licence was queued for a checker. */
  onPending?: (message: string) => void;
}

export function CreateLicenseModal({ open, customerId, onClose, onCreated, onPending }: CreateLicenseModalProps) {
  const products = useApi(() => productsApi.list({ pageSize: 100, status: 'ACTIVE' }), [open]);
  const [form, setForm] = useState({ customerId: '', productId: '', planId: '', amount: '', notes: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const customers = useApi(
    () => (customerId ? Promise.resolve(null) : customersApi.list({ pageSize: 100, status: 'ACTIVE', sort: 'companyName:asc' })),
    [open, customerId],
  );

  const plans = useApi(
    () =>
      form.productId
        ? plansApi.list({ productId: Number(form.productId), pageSize: 100, status: 'ACTIVE' })
        : Promise.resolve(null),
    [form.productId, open],
  );

  useEffect(() => {
    if (open) {
      setForm({ customerId: customerId ? String(customerId) : '', productId: '', planId: '', amount: '', notes: '' });
      setError(null);
    }
  }, [open, customerId]);

  const selectedPlan = (plans.data?.items ?? []).find((p) => String(p.planId) === form.planId);
  const amountNum = form.amount.trim() === '' ? NaN : Number(form.amount);
  const amountOk = Number.isFinite(amountNum) && amountNum >= 0;
  const valid = form.customerId !== '' && form.productId !== '' && form.planId !== '' && amountOk;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      const created = await licensesApi.create({
        customerId: Number(form.customerId),
        productId: Number(form.productId),
        planId: Number(form.planId),
        amount: Math.round(amountNum * 100) / 100,
        notes: form.notes.trim() || undefined,
      });
      if (isPendingApproval(created)) onPending?.(created.message);
      else onCreated(created.licenseId);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Create failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Create License" open={open} onClose={onClose}>
      <ErrorBanner error={error} />
      <form onSubmit={submit}>
        {!customerId && (
          <FormField label="Customer" required>
            <select
              className="input"
              value={form.customerId}
              onChange={(e) => setForm((f) => ({ ...f, customerId: e.target.value }))}
            >
              <option value="">Select customer…</option>
              {(customers.data?.items ?? []).map((c) => (
                <option key={c.customerId} value={c.customerId}>
                  {c.companyName} ({c.customerCode})
                </option>
              ))}
            </select>
          </FormField>
        )}
        <FormField label="Product" required>
          <select
            className="input"
            value={form.productId}
            onChange={(e) => setForm((f) => ({ ...f, productId: e.target.value, planId: '' }))}
          >
            <option value="">Select product…</option>
            {(products.data?.items ?? []).map((p) => (
              <option key={p.productId} value={p.productId}>
                {p.productName} ({p.productCode})
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Plan" required hint={form.productId ? undefined : 'Choose a product first'}>
          <select
            className="input"
            value={form.planId}
            onChange={(e) => {
              const pid = e.target.value;
              const pl = (plans.data?.items ?? []).find((p) => String(p.planId) === pid);
              // Prefill with the plan's list price when it has one; still editable.
              setForm((f) => ({ ...f, planId: pid, amount: f.amount === '' && pl?.price != null && pl.price > 0 ? String(pl.price) : f.amount }));
            }}
            disabled={!form.productId || plans.loading}
          >
            <option value="">{plans.loading ? 'Loading plans…' : 'Select plan…'}</option>
            {(plans.data?.items ?? []).map((p) => (
              <option key={p.planId} value={p.planId}>
                {p.planName} — {p.isLifetime ? 'Lifetime' : `${p.durationDays} days`}, {p.maxActivations} activation(s)
              </option>
            ))}
          </select>
        </FormField>
        {selectedPlan && (
          <div className="alert alert-info">
            <Icon name="info" size={16} />
            <div>
              {selectedPlan.planName}: {selectedPlan.isLifetime ? 'lifetime' : `${selectedPlan.durationDays} days`} ·{' '}
              {selectedPlan.maxActivations} activation(s)
              {selectedPlan.maxUsers != null && <> · {selectedPlan.maxUsers} users</>}
              {selectedPlan.maxBranches != null && <> · {selectedPlan.maxBranches} branches</>}
            </div>
          </div>
        )}
        <FormField
          label="Amount (₹)"
          required
          error={form.amount !== '' && !amountOk ? 'Enter an amount of 0 or more.' : undefined}
          hint="What the customer pays for this licence. Enter 0 for a free licence. Counted as revenue on the dashboard."
        >
          <input
            id="lic-amount"
            className="input"
            type="number"
            inputMode="decimal"
            min={0}
            step="0.01"
            placeholder="e.g. 25000"
            value={form.amount}
            onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
          />
        </FormField>
        <FormField label="Notes">
          <textarea className="input" value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} rows={2} />
        </FormField>
        <div className="alert alert-warning mb-0">
          <Icon name="alert-triangle" size={16} />
          <div>The license is created in DRAFT status. Activate it to generate the license key.</div>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={!valid || busy}>
            {busy ? <Spinner size={13} /> : <Icon name="plus" size={15} />}
            Create License
          </button>
        </div>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/* Action buttons + confirm dialogs for a license                      */
/* ------------------------------------------------------------------ */

type ActionKind = 'activate' | 'suspend' | 'reactivate' | 'revoke' | 'regenerate' | null;

interface LicenseActionButtonsProps {
  license: Pick<License, 'licenseId' | 'licenseNo' | 'status' | 'productId' | 'planId' | 'planName'>;
  onChanged: () => void;
  /**
   * Called instead of onChanged when a lifecycle action came back as HTTP 202 —
   * nothing changed yet, a checker has to approve it first.
   */
  onPending?: (message: string) => void;
  /** Show the regenerate-key action (license detail page). */
  showRegenerate?: boolean;
  small?: boolean;
}

export function LicenseActionButtons({
  license,
  onChanged,
  onPending,
  showRegenerate = false,
  small = false,
}: LicenseActionButtonsProps) {
  const { hasPermission } = useAuth();
  const [action, setAction] = useState<ActionKind>(null);
  const [renewOpen, setRenewOpen] = useState(false);
  const [newKey, setNewKey] = useState<string | null>(null);

  /** Either the action applied (reload) or it is now waiting for a checker. */
  const settle = (res: unknown): void => {
    if (isPendingApproval(res)) onPending?.(res.message);
    else onChanged();
  };

  const canManage = hasPermission('LICENSE_MANAGE');
  const canRevoke = hasPermission('LICENSE_REVOKE', 'LICENSE_MANAGE');
  const s = license.status;
  const btn = small ? 'btn btn-sm' : 'btn';
  const iconSize = small ? 14 : 15;

  if (!canManage && !canRevoke) return null;

  return (
    <>
      <div className="actions btn-group">
        {canManage && s === 'DRAFT' && (
          <button type="button" className={`${btn} btn-primary`} onClick={() => setAction('activate')}>
            <Icon name="play" size={iconSize} />
            Activate
          </button>
        )}
        {canManage && (s === 'ACTIVE' || s === 'EXPIRED') && (
          <button type="button" className={`${btn} btn-primary`} onClick={() => setRenewOpen(true)}>
            <Icon name="refresh" size={iconSize} />
            Renew
          </button>
        )}
        {canManage && s === 'ACTIVE' && (
          <button type="button" className={btn} onClick={() => setAction('suspend')}>
            <Icon name="pause" size={iconSize} />
            Suspend
          </button>
        )}
        {canManage && s === 'SUSPENDED' && (
          <button type="button" className={btn} onClick={() => setAction('reactivate')}>
            <Icon name="play" size={iconSize} />
            Reactivate
          </button>
        )}
        {canManage && showRegenerate && s === 'ACTIVE' && (
          <button type="button" className={btn} onClick={() => setAction('regenerate')}>
            <Icon name="key" size={iconSize} />
            Regenerate Key
          </button>
        )}
        {canRevoke && (s === 'ACTIVE' || s === 'SUSPENDED' || s === 'EXPIRED') && (
          <button type="button" className={`${btn} btn-danger-outline`} onClick={() => setAction('revoke')}>
            <Icon name="ban" size={iconSize} />
            Revoke
          </button>
        )}
      </div>

      <ConfirmDialog
        open={action === 'activate'}
        title="Activate License"
        message={
          <>
            Activate license <strong className="mono">{license.licenseNo}</strong>? A license key will be generated and
            the license becomes usable by the customer.
          </>
        }
        confirmLabel="Activate"
        onConfirm={async () => {
          const res = await licensesApi.activate(license.licenseId);
          setAction(null);
          settle(res);
        }}
        onClose={() => setAction(null)}
      />

      <ConfirmDialog
        open={action === 'suspend'}
        title="Suspend License"
        danger
        requireReason
        message={
          <>
            Suspend license <strong className="mono">{license.licenseNo}</strong>? The product will stop authorizing on
            the next validation until the license is reactivated.
          </>
        }
        confirmLabel="Suspend"
        onConfirm={async (reason) => {
          const res = await licensesApi.suspend(license.licenseId, reason);
          setAction(null);
          settle(res);
        }}
        onClose={() => setAction(null)}
      />

      <ConfirmDialog
        open={action === 'reactivate'}
        title="Reactivate License"
        message={
          <>
            Reactivate suspended license <strong className="mono">{license.licenseNo}</strong>? Authorization resumes
            immediately.
          </>
        }
        confirmLabel="Reactivate"
        onConfirm={async (reason) => {
          const res = await licensesApi.reactivate(license.licenseId, reason || undefined);
          setAction(null);
          settle(res);
        }}
        onClose={() => setAction(null)}
      />

      <ConfirmDialog
        open={action === 'revoke'}
        title="Revoke License"
        danger
        requireReason
        confirmText={license.licenseNo}
        message={
          <>
            <div className="alert alert-error">
              <Icon name="alert-circle" size={16} />
              <div>
                Revoking is <strong>permanent</strong>. License <span className="mono">{license.licenseNo}</span> can
                never be used again and all activations will be denied.
              </div>
            </div>
          </>
        }
        confirmLabel="Revoke Permanently"
        onConfirm={async (reason) => {
          const res = await licensesApi.revoke(license.licenseId, reason);
          setAction(null);
          settle(res);
        }}
        onClose={() => setAction(null)}
      />

      <ConfirmDialog
        open={action === 'regenerate'}
        title="Regenerate License Key"
        danger
        requireReason
        message={
          <>
            The current key of <strong className="mono">{license.licenseNo}</strong> will be revoked and replaced with a
            new one. Installations using the old key must be updated. The new key is shown <strong>once</strong>.
          </>
        }
        confirmLabel="Regenerate Key"
        onConfirm={async (reason) => {
          const res = await licensesApi.regenerateKey(license.licenseId, reason);
          setAction(null);
          // A queued regeneration has no key to show — the checker's approval mints it.
          if (isPendingApproval(res)) {
            onPending?.(res.message);
          } else {
            setNewKey(res.licenseKey);
            onChanged();
          }
        }}
        onClose={() => setAction(null)}
      />

      <Modal title="New License Key" open={newKey !== null} onClose={() => setNewKey(null)} locked>
        <div className="alert alert-warning">
          <Icon name="alert-triangle" size={16} />
          <div>Copy this key now — it is displayed here only once. The previous key has been revoked.</div>
        </div>
        {newKey && (
          <div className="key-display">
            <span>{newKey}</span>
            <CopyButton text={newKey} />
          </div>
        )}
        <div className="form-actions">
          <button type="button" className="btn btn-primary" onClick={() => setNewKey(null)}>
            I have copied the key
          </button>
        </div>
      </Modal>

      <RenewLicenseModal
        open={renewOpen}
        license={license}
        onClose={() => setRenewOpen(false)}
        onDone={onChanged}
        onPending={onPending}
      />
    </>
  );
}
