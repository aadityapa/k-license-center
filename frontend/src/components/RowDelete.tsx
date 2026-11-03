import { useState } from 'react';
import type { ReactNode } from 'react';
import { ConfirmDialog } from './ConfirmDialog';
import { Icon } from './Icon';
import { isPendingApproval } from '../services/api/http';

interface RowDeleteProps {
  /** What is being deleted, e.g. "licence LIC-2026-100001" — used in the title and button tooltip. */
  what: string;
  /** Text the user must type to confirm (the record's number/code/name). */
  confirmText?: string;
  /** Extra explanation in the dialog: what else goes with it. */
  detail?: ReactNode;
  onDelete: () => Promise<unknown>;
  /** Called after the record was deleted. */
  onDeleted: () => void;
  /** Called with the server's message when a maker's delete was queued for approval. */
  onPending?: (message: string) => void;
  /** Icon-only button (tables) or labelled button (detail pages). */
  compact?: boolean;
  disabled?: boolean;
}

/**
 * Delete button + type-to-confirm dialog. An admin's delete applies at once; a
 * maker's comes back 202 and is shown as "submitted for approval".
 */
export function RowDelete({ what, confirmText, detail, onDelete, onDeleted, onPending, compact = true, disabled }: RowDeleteProps) {
  const [open, setOpen] = useState(false);
  return (
    // Clicks inside the dialog must not reach a clickable table row behind it.
    <span className="contents" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={`btn btn-sm btn-danger-outline ${compact ? 'px-2' : ''}`}
        onClick={() => setOpen(true)}
        disabled={disabled}
        title={`Delete ${what}`}
        aria-label={`Delete ${what}`}
      >
        <Icon name="trash" size={13} />
        {!compact && 'Delete'}
      </button>
      <ConfirmDialog
        open={open}
        title={`Delete ${what}`}
        danger
        confirmText={confirmText}
        confirmLabel="Delete"
        message={
          <div>
            <p className="mt-0">
              Permanently delete <strong>{what}</strong>? This cannot be undone.
            </p>
            {detail && <p className="mb-0 text-ink-2">{detail}</p>}
          </div>
        }
        onConfirm={async () => {
          const res = await onDelete();
          setOpen(false);
          if (isPendingApproval(res)) onPending?.(res.message);
          else onDeleted();
        }}
        onClose={() => setOpen(false)}
      />
    </span>
  );
}
