import { ApiError } from '../services/api/http';
import { Icon } from './Icon';

interface ErrorStateProps {
  error: ApiError | Error;
  onRetry?: () => void;
}

export function ErrorState({ error, onRetry }: ErrorStateProps) {
  const apiErr = error instanceof ApiError ? error : null;
  return (
    <div className="px-4 py-8 text-center">
      <div className="mb-3 text-danger drop-shadow-[0_0_12px_rgba(251,113,133,0.4)]">
        <Icon name="alert-circle" size={30} />
      </div>
      <div className="mb-1 text-md font-semibold text-ink">{apiErr ? apiErr.code : 'Error'}</div>
      <div className="mb-3 text-ink-2">{error.message}</div>
      {apiErr?.requestId && <div className="mb-3 font-mono text-xs text-muted">Request ID: {apiErr.requestId}</div>}
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          <Icon name="refresh" size={15} />
          Retry
        </button>
      )}
    </div>
  );
}

/** Inline banner variant, for errors during actions (form submits etc.) */
export function ErrorBanner({ error }: { error: ApiError | Error | string | null }) {
  if (!error) return null;
  const message = typeof error === 'string' ? error : error.message;
  const requestId = error instanceof ApiError ? error.requestId : null;
  const code = error instanceof ApiError ? error.code : null;
  return (
    <div className="alert alert-error" role="alert">
      <Icon name="alert-circle" size={16} />
      <div>
        {code && <strong>{code}: </strong>}
        {message}
        {requestId && <span className="mt-1 block font-mono text-xs opacity-85">Request ID: {requestId}</span>}
      </div>
    </div>
  );
}
