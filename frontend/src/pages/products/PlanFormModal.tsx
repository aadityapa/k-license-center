import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Modal } from '../../components/Modal';
import { FormField } from '../../components/FormField';
import { ErrorBanner } from '../../components/ErrorState';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { plansApi, productsApi } from '../../services/api/endpoints';
import { isPendingApproval } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import type { ProductPlan } from '../../types';

interface PlanFormModalProps {
  open: boolean;
  plan?: ProductPlan | null;
  fixedProductId?: number;
  onClose: () => void;
  onSaved: () => void;
  /** Called instead of onSaved when the write was queued for a checker (HTTP 202). */
  onPending?: (message: string) => void;
}

export function PlanFormModal({ open, plan, fixedProductId, onClose, onSaved, onPending }: PlanFormModalProps) {
  const products = useApi(() => productsApi.list({ pageSize: 100, status: 'ACTIVE' }), [open]);
  const [form, setForm] = useState({
    productId: '',
    planCode: '',
    planName: '',
    isLifetime: false,
    durationDays: '',
    price: '',
    currency: 'INR',
    maxActivations: '1',
    maxUsers: '',
    maxBranches: '',
    status: 'ACTIVE',
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (open) {
      setError(null);
      setForm({
        productId: String(plan?.productId ?? fixedProductId ?? ''),
        planCode: plan?.planCode ?? '',
        planName: plan?.planName ?? '',
        isLifetime: plan?.isLifetime ?? false,
        durationDays: plan?.durationDays != null ? String(plan.durationDays) : '',
        price: plan?.price != null ? String(plan.price) : '',
        currency: plan?.currency ?? 'INR',
        maxActivations: String(plan?.maxActivations ?? 1),
        maxUsers: plan?.maxUsers != null ? String(plan.maxUsers) : '',
        maxBranches: plan?.maxBranches != null ? String(plan.maxBranches) : '',
        status: plan?.status ?? 'ACTIVE',
      });
    }
  }, [open, plan, fixedProductId]);

  const set = (key: keyof typeof form, value: string | boolean) => setForm((f) => ({ ...f, [key]: value }));

  const valid =
    form.productId !== '' &&
    form.planCode.trim() !== '' &&
    form.planName.trim() !== '' &&
    Number(form.maxActivations) >= 1 &&
    (form.isLifetime || Number(form.durationDays) > 0);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    const body = {
      productId: Number(form.productId),
      planCode: form.planCode.trim().toUpperCase(),
      planName: form.planName.trim(),
      isLifetime: form.isLifetime,
      durationDays: form.isLifetime ? null : Number(form.durationDays),
      price: form.price === '' ? null : Number(form.price),
      currency: form.currency,
      maxActivations: Number(form.maxActivations),
      maxUsers: form.maxUsers === '' ? null : Number(form.maxUsers),
      maxBranches: form.maxBranches === '' ? null : Number(form.maxBranches),
      status: form.status as ProductPlan['status'],
    };
    try {
      const res = plan ? await plansApi.update(plan.planId, body) : await plansApi.create(body);
      if (isPendingApproval(res)) {
        onPending?.(res.message);
      } else {
        onSaved();
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Save failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={plan ? `Edit Plan — ${plan.planCode}` : 'New Plan'} open={open} onClose={onClose} size="lg">
      <ErrorBanner error={error} />
      <form onSubmit={submit}>
        <div className="form-grid">
          <FormField label="Product" required>
            <select
              className="input"
              value={form.productId}
              onChange={(e) => set('productId', e.target.value)}
              disabled={Boolean(plan) || Boolean(fixedProductId)}
            >
              <option value="">Select product…</option>
              {(products.data?.items ?? []).map((p) => (
                <option key={p.productId} value={p.productId}>
                  {p.productName} ({p.productCode})
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Plan Code" required hint="Unique per product, e.g. TRIAL, ANNUAL">
            <input
              className="input mono"
              value={form.planCode}
              onChange={(e) => set('planCode', e.target.value)}
              disabled={Boolean(plan)}
              maxLength={30}
            />
          </FormField>
        </div>
        <FormField label="Plan Name" required>
          <input className="input" value={form.planName} onChange={(e) => set('planName', e.target.value)} maxLength={100} />
        </FormField>
        <div className="form-grid">
          <div className="form-field">
            <label>Duration</label>
            <div className="checkbox-row mb-1.5">
              <input
                id="plan-lifetime"
                type="checkbox"
                checked={form.isLifetime}
                onChange={(e) => set('isLifetime', e.target.checked)}
              />
              <label htmlFor="plan-lifetime" className="!m-0 !font-normal">
                Lifetime (never expires)
              </label>
            </div>
            {!form.isLifetime && (
              <input
                className="input"
                type="number"
                min={1}
                placeholder="Duration in days, e.g. 365"
                value={form.durationDays}
                onChange={(e) => set('durationDays', e.target.value)}
              />
            )}
          </div>
          <FormField label="Price">
            <div className="flex gap-2">
              <input
                className="input"
                type="number"
                min={0}
                step="0.01"
                value={form.price}
                onChange={(e) => set('price', e.target.value)}
                placeholder="0.00"
              />
              <select className="input !w-[90px]" value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                <option value="INR">INR</option>
                <option value="USD">USD</option>
                <option value="EUR">EUR</option>
                <option value="AED">AED</option>
              </select>
            </div>
          </FormField>
        </div>
        <div className="form-grid">
          <FormField label="Max Activations" required hint="Devices allowed per license">
            <input
              className="input"
              type="number"
              min={1}
              value={form.maxActivations}
              onChange={(e) => set('maxActivations', e.target.value)}
            />
          </FormField>
          <FormField label="Status">
            <select className="input" value={form.status} onChange={(e) => set('status', e.target.value)}>
              <option value="ACTIVE">ACTIVE</option>
              <option value="INACTIVE">INACTIVE</option>
            </select>
          </FormField>
        </div>
        <div className="form-grid">
          <FormField label="Max Users" hint="Blank = unlimited">
            <input className="input" type="number" min={1} value={form.maxUsers} onChange={(e) => set('maxUsers', e.target.value)} />
          </FormField>
          <FormField label="Max Branches" hint="Blank = unlimited">
            <input
              className="input"
              type="number"
              min={1}
              value={form.maxBranches}
              onChange={(e) => set('maxBranches', e.target.value)}
            />
          </FormField>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={!valid || busy}>
            {busy && <Spinner size={13} />}
            {!busy && !plan && <Icon name="plus" size={15} />}
            {plan ? 'Save Changes' : 'Create Plan'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
