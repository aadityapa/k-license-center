import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Modal } from '../../components/Modal';
import { FormField } from '../../components/FormField';
import { ErrorBanner } from '../../components/ErrorState';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { customersApi } from '../../services/api/endpoints';
import { isPendingApproval } from '../../services/api/http';
import type { Customer } from '../../types';

interface CustomerFormModalProps {
  open: boolean;
  customer?: Customer | null;
  onClose: () => void;
  onSaved: () => void;
  /** Called instead of onSaved when the write was queued for a checker (HTTP 202). */
  onPending?: (message: string) => void;
}

const EMPTY = {
  customerCode: '',
  companyName: '',
  contactPerson: '',
  email: '',
  mobile: '',
  whatsapp: '',
  addressLine1: '',
  addressLine2: '',
  city: '',
  state: '',
  country: 'India',
  gstNumber: '',
  status: 'ACTIVE',
};

export function CustomerFormModal({ open, customer, onClose, onSaved, onPending }: CustomerFormModalProps) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (open) {
      setError(null);
      setForm({
        customerCode: customer?.customerCode ?? '',
        companyName: customer?.companyName ?? '',
        contactPerson: customer?.contactPerson ?? '',
        email: customer?.email ?? '',
        mobile: customer?.mobile ?? '',
        whatsapp: customer?.whatsapp ?? '',
        addressLine1: customer?.addressLine1 ?? '',
        addressLine2: customer?.addressLine2 ?? '',
        city: customer?.city ?? '',
        state: customer?.state ?? '',
        country: customer?.country ?? 'India',
        gstNumber: customer?.gstNumber ?? '',
        status: customer?.status ?? 'ACTIVE',
      });
    }
  }, [open, customer]);

  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const valid = form.customerCode.trim() !== '' && form.companyName.trim() !== '';

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    const trim = (v: string) => v.trim() || undefined;
    const body = {
      customerCode: form.customerCode.trim().toUpperCase(),
      companyName: form.companyName.trim(),
      contactPerson: trim(form.contactPerson),
      email: trim(form.email),
      mobile: trim(form.mobile),
      whatsapp: trim(form.whatsapp),
      addressLine1: trim(form.addressLine1),
      addressLine2: trim(form.addressLine2),
      city: trim(form.city),
      state: trim(form.state),
      country: trim(form.country),
      gstNumber: trim(form.gstNumber),
      status: form.status as Customer['status'],
    };
    try {
      const res = customer
        ? await customersApi.update(customer.customerId, body)
        : await customersApi.create(body);
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
    <Modal
      title={customer ? `Edit Customer — ${customer.customerCode}` : 'New Customer'}
      open={open}
      onClose={onClose}
      size="lg"
    >
      <ErrorBanner error={error} />
      <form onSubmit={submit}>
        <div className="form-grid">
          <FormField label="Customer Code" required hint="Unique identifier, e.g. CUST-0001">
            <input
              className="input mono"
              value={form.customerCode}
              onChange={(e) => set('customerCode', e.target.value)}
              disabled={Boolean(customer)}
              maxLength={30}
            />
          </FormField>
          <FormField label="Status">
            <select className="input" value={form.status} onChange={(e) => set('status', e.target.value)}>
              <option value="ACTIVE">ACTIVE</option>
              <option value="INACTIVE">INACTIVE</option>
            </select>
          </FormField>
        </div>
        <FormField label="Company Name" required>
          <input className="input" value={form.companyName} onChange={(e) => set('companyName', e.target.value)} maxLength={200} />
        </FormField>
        <div className="form-grid">
          <FormField label="Contact Person">
            <input className="input" value={form.contactPerson} onChange={(e) => set('contactPerson', e.target.value)} />
          </FormField>
          <FormField label="Email">
            <input className="input" type="email" value={form.email} onChange={(e) => set('email', e.target.value)} />
          </FormField>
          <FormField label="Mobile">
            <input className="input" value={form.mobile} onChange={(e) => set('mobile', e.target.value)} maxLength={20} />
          </FormField>
          <FormField label="WhatsApp">
            <input className="input" value={form.whatsapp} onChange={(e) => set('whatsapp', e.target.value)} maxLength={20} />
          </FormField>
          <FormField label="Address Line 1">
            <input className="input" value={form.addressLine1} onChange={(e) => set('addressLine1', e.target.value)} />
          </FormField>
          <FormField label="Address Line 2">
            <input className="input" value={form.addressLine2} onChange={(e) => set('addressLine2', e.target.value)} />
          </FormField>
          <FormField label="City">
            <input className="input" value={form.city} onChange={(e) => set('city', e.target.value)} />
          </FormField>
          <FormField label="State">
            <input className="input" value={form.state} onChange={(e) => set('state', e.target.value)} />
          </FormField>
          <FormField label="Country">
            <input className="input" value={form.country} onChange={(e) => set('country', e.target.value)} />
          </FormField>
          <FormField label="GST Number">
            <input className="input mono" value={form.gstNumber} onChange={(e) => set('gstNumber', e.target.value)} maxLength={20} />
          </FormField>
        </div>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={!valid || busy}>
            {busy && <Spinner size={13} />}
            {!busy && !customer && <Icon name="plus" size={15} />}
            {customer ? 'Save Changes' : 'Create Customer'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
