const STATUS_COLORS: Record<string, string> = {
  ACTIVE: 'badge-green',
  TRIAL: 'badge-grayblue',
  DRAFT: 'badge-grayblue',
  SUSPENDED: 'badge-amber',
  EXPIRED: 'badge-orange',
  REVOKED: 'badge-red',
  CANCELLED: 'badge-red',
  DEACTIVATED: 'badge-gray',
  INACTIVE: 'badge-gray',
  ARCHIVED: 'badge-gray',
  LOCKED: 'badge-amber',
  PENDING: 'badge-grayblue',
  SENT: 'badge-green',
  FAILED: 'badge-red',
  // Maker-checker change requests
  APPROVED: 'badge-green',
  REJECTED: 'badge-orange',
  // Licence requests
  INVITED: 'badge-grayblue',
  SUBMITTED: 'badge-grayblue',
  UNDER_REVIEW: 'badge-amber',
  AUTO_ISSUED: 'badge-green',
  // Email outbox
  QUEUED: 'badge-grayblue',
  SKIPPED: 'badge-gray',
};

export function StatusBadge({ status }: { status?: string | null }) {
  if (!status) return <span className="muted">—</span>;
  const cls = STATUS_COLORS[status.toUpperCase()] ?? 'badge-gray';
  return <span className={`badge ${cls}`}>{status}</span>;
}
