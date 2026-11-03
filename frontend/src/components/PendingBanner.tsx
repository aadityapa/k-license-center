import { Icon } from './Icon';

/**
 * Confirmation shown when a maker's mutation came back as HTTP 202 — the change
 * was queued for a checker instead of applied. Nothing changed on screen, so the
 * message is the only feedback the user gets.
 */
export function PendingBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="alert alert-info" role="status">
      <Icon name="clock" size={16} />
      <div>
        <strong>Submitted for approval. </strong>
        {message}
      </div>
    </div>
  );
}
