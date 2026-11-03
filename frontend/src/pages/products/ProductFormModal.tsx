import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Modal } from '../../components/Modal';
import { FormField } from '../../components/FormField';
import { ErrorBanner } from '../../components/ErrorState';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { productsApi } from '../../services/api/endpoints';
import { isPendingApproval } from '../../services/api/http';
import type { Product } from '../../types';

interface ProductFormModalProps {
  open: boolean;
  product?: Product | null; // null/undefined = create
  onClose: () => void;
  onSaved: () => void;
  /** Called instead of onSaved when the write was queued for a checker (HTTP 202). */
  onPending?: (message: string) => void;
}

export function ProductFormModal({ open, product, onClose, onSaved, onPending }: ProductFormModalProps) {
  const [form, setForm] = useState({
    productCode: '',
    productName: '',
    keyPrefix: '',
    description: '',
    version: '',
    status: 'ACTIVE',
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (open) {
      setError(null);
      setForm({
        productCode: product?.productCode ?? '',
        productName: product?.productName ?? '',
        keyPrefix: product?.keyPrefix ?? '',
        description: product?.description ?? '',
        version: product?.version ?? '',
        status: product?.status ?? 'ACTIVE',
      });
    }
  }, [open, product]);

  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const valid = form.productCode.trim() && form.productName.trim() && form.keyPrefix.trim();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    const body = {
      productCode: form.productCode.trim().toUpperCase(),
      productName: form.productName.trim(),
      keyPrefix: form.keyPrefix.trim().toUpperCase(),
      description: form.description.trim() || undefined,
      version: form.version.trim() || undefined,
      status: form.status as Product['status'],
    };
    try {
      const res = product ? await productsApi.update(product.productId, body) : await productsApi.create(body);
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
    <Modal title={product ? `Edit Product — ${product.productCode}` : 'New Product'} open={open} onClose={onClose}>
      <ErrorBanner error={error} />
      <form onSubmit={submit}>
        <div className="form-grid">
          <FormField label="Product Code" required hint="e.g. KSTACK — immutable identifier">
            <input
              className="input mono"
              value={form.productCode}
              onChange={(e) => set('productCode', e.target.value)}
              disabled={Boolean(product)}
              maxLength={30}
            />
          </FormField>
          <FormField label="Key Prefix" required hint="Used in license keys, e.g. KSTK">
            <input
              className="input mono"
              value={form.keyPrefix}
              onChange={(e) => set('keyPrefix', e.target.value)}
              disabled={Boolean(product)}
              maxLength={6}
            />
          </FormField>
        </div>
        <FormField label="Product Name" required>
          <input className="input" value={form.productName} onChange={(e) => set('productName', e.target.value)} maxLength={100} />
        </FormField>
        <div className="form-grid">
          <FormField label="Version">
            <input className="input" value={form.version} onChange={(e) => set('version', e.target.value)} maxLength={30} />
          </FormField>
          <FormField label="Status">
            <select className="input" value={form.status} onChange={(e) => set('status', e.target.value)}>
              <option value="ACTIVE">ACTIVE</option>
              <option value="INACTIVE">INACTIVE</option>
            </select>
          </FormField>
        </div>
        <FormField label="Description">
          <textarea className="input" value={form.description} onChange={(e) => set('description', e.target.value)} maxLength={1000} />
        </FormField>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={!valid || busy}>
            {busy && <Spinner size={13} />}
            {!busy && !product && <Icon name="plus" size={15} />}
            {product ? 'Save Changes' : 'Create Product'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
