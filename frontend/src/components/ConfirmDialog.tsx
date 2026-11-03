import { useState } from 'react';
import { Modal } from './Modal';
import { FormField } from './FormField';
import { ErrorBanner } from './ErrorState';
import { Spinner } from './Spinner';
import { ApiError } from '../services/api/http';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: React.ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  /** When true, a non-empty reason is required (sent to the API). */
  requireReason?: boolean;
  reasonLabel?: string;
  /** Double confirmation: the user must type this exact text (e.g. the license number). */
  confirmText?: string;
  onConfirm: (reason: string) => Promise<void> | void;
  onClose: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  danger = false,
  requireReason = false,
  reasonLabel = 'Reason',
  confirmText,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const [reason, setReason] = useState('');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);

  const reset = () => {
    setReason('');
    setTyped('');
    setError(null);
    setBusy(false);
  };

  const close = () => {
    reset();
    onClose();
  };

  const canConfirm =
    (!requireReason || reason.trim().length >= 3) && (!confirmText || typed === confirmText) && !busy;

  const handleConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
      reset();
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Action failed'));
      setBusy(false);
    }
  };

  return (
    <Modal title={title} open={open} onClose={close}>
      <ErrorBanner error={error} />
      <div className="mb-[14px]">{message}</div>
      {requireReason && (
        <FormField label={reasonLabel} required hint="Minimum 3 characters. Recorded in the audit log.">
          <textarea
            className="input"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            placeholder="Why is this action being taken?"
          />
        </FormField>
      )}
      {confirmText && (
        <FormField label={`Type "${confirmText}" to confirm`} required>
          <input
            className="input mono"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={confirmText}
            autoComplete="off"
          />
        </FormField>
      )}
      <div className="form-actions">
        <button type="button" className="btn" onClick={close} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
          disabled={!canConfirm}
          onClick={handleConfirm}
        >
          {busy && <Spinner size={13} />} {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
