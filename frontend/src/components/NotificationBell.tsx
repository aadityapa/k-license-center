import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from './Icon';
import { notificationsApi } from '../services/api/endpoints';
import type { NotificationItem } from '../types';
import { formatDateTime } from '../utils/format';

/** How often the bell asks the server. A reviewer should see a new request within half a minute. */
const POLL_MS = 20_000;

/**
 * The portal bell. Shows the unread count, lists recent events, and takes the
 * reviewer straight to the thing that needs them. Opening the list
 * acknowledges what was unread — for everyone, since this is one shared desk.
 */
export function NotificationBell() {
  const navigate = useNavigate();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await notificationsApi.list(15);
      setItems(res.items);
      setUnread(res.unread);
    } catch {
      // A failed poll is not worth a banner; the next one is 20 seconds away.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => void refresh(), POLL_MS);
    // Catch up immediately when the tab comes back into view.
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(t);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [refresh]);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && unread > 0) {
      // Seen is seen: clear the count as soon as the list is on screen.
      setUnread(0);
      try {
        await notificationsApi.ack();
      } catch {
        /* the next poll will show the true state */
      }
    }
  };

  const go = (n: NotificationItem) => {
    setOpen(false);
    if (n.entityType === 'LICENSE_REQUEST' && n.entityId != null) {
      navigate(`/license-requests?open=${n.entityId}`);
    } else if (n.entityType === 'LICENSE' && n.entityId != null) {
      navigate(`/licenses/${n.entityId}`);
    } else if (n.eventType === 'CLOCK_TAMPER') {
      // Where the computer can be reactivated.
      navigate('/activations#clock-alerts');
    } else {
      navigate('/license-requests');
    }
  };

  const criticalUnread = items.some((n) => n.status === 'PENDING' && isCritical(n));

  return (
    <div className="relative" ref={wrapRef}>
      <button
        type="button"
        className={`notif-btn icon-btn relative${criticalUnread ? ' has-critical' : ''}`}
        onClick={() => void toggle()}
        aria-label={unread > 0 ? `${unread} new notifications` : 'Notifications'}
        aria-expanded={open}
        title="Notifications"
      >
        <Icon name="inbox" size={17} />
        {unread > 0 && (
          <span
            className={`notif-count absolute right-0.5 top-0.5 h-[17px] min-w-[17px] rounded-full border-[1.5px] border-solid border-surface px-[5px] text-center text-[10.5px] font-bold leading-[17px] text-white shadow-[0_0_8px_var(--danger-soft)] ${
              criticalUnread ? 'animate-notif-pulse bg-[#ef4444] motion-reduce:animate-none' : 'bg-danger'
            }`}
          >
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        // Opaque: the glass tint is layered over the page colour so text on the
        // cards underneath cannot show through a menu that is read line by line.
        <div
          className="absolute right-0 top-[calc(100%+8px)] z-[60] w-[360px] max-w-[calc(100vw-32px)] overflow-hidden rounded-lg border border-solid border-line-strong bg-base bg-[linear-gradient(var(--glass-solid),var(--glass-solid))] shadow-[0_18px_48px_rgba(0,0,0,0.45)]"
          role="menu"
        >
          <div className="flex items-center justify-between border-0 border-b border-solid border-line px-3.5 py-2.5 font-semibold">
            <span>Notifications</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void refresh()}>
              <Icon name="refresh" size={13} /> Refresh
            </button>
          </div>
          {items.length === 0 ? (
            <div className="px-3.5 py-[22px] text-sm text-muted">Nothing needs your attention.</div>
          ) : (
            <ul className="m-0 max-h-[380px] list-none overflow-y-auto p-0">
              {items.map((n) => (
                <li key={n.eventId}>
                  <button
                    type="button"
                    className={`notif-item${isCritical(n) ? ' is-critical' : ''} block w-full cursor-pointer border-0 border-b border-l-[3px] border-solid border-line px-3.5 py-2.5 text-left text-ink ${
                      isCritical(n)
                        ? 'border-l-[#ef4444] bg-[color-mix(in_srgb,#ef4444_8%,transparent)]'
                        : `bg-transparent hover:bg-surface-hover ${n.status === 'PENDING' ? 'border-l-primary' : 'border-l-transparent'}`
                    }`}
                    onClick={() => go(n)}
                    role="menuitem"
                  >
                    <div className="text-sm leading-[1.4]">
                      {isCritical(n) && (
                        <span className="mr-1.5 inline-block rounded-[4px] bg-[#ef4444] px-1.5 align-[1px] text-2xs font-extrabold tracking-[.06em] text-white">
                          CRITICAL
                        </span>
                      )}
                      {describe(n)}
                    </div>
                    <div className="mt-0.5 text-xs text-muted">{formatDateTime(n.createdAt)}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function isCritical(n: NotificationItem): boolean {
  const p = (n.payload ?? {}) as Record<string, unknown>;
  return n.eventType === 'CLOCK_TAMPER' || p.severity === 'CRITICAL';
}

function humanDelta(seconds: unknown): string {
  const s = Math.abs(Number(seconds));
  if (!Number.isFinite(s) || s === 0) return '';
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d} day${d === 1 ? '' : 's'}${h ? ` ${h} hr` : ''}`;
  return h > 0 ? `${h} hr${m ? ` ${m} min` : ''}` : `${Math.max(1, m)} min`;
}

/** One readable line per event type; unknown types fall back to the raw code. */
function describe(n: NotificationItem): string {
  const p = (n.payload ?? {}) as Record<string, unknown>;
  switch (n.eventType) {
    case 'LICENSE_REQUEST_RECEIVED': {
      const product = typeof p.product === 'string' ? p.product : 'a product';
      const who = typeof p.email === 'string' ? p.email : 'someone';
      const host = typeof p.hostName === 'string' && p.hostName ? ` on ${p.hostName}` : '';
      return `${product} licence requested by ${who}${host}`;
    }
    case 'CLOCK_TAMPER': {
      const where = [p.deviceName, p.licenseNo].filter((x) => typeof x === 'string' && x).join(' · ');
      const by = humanDelta(p.deltaSeconds);
      const what =
        p.kind === 'MOVED_BACK' ? `date/time moved back${by ? ` ${by}` : ''}`
        : p.kind === 'MOVED_FORWARD' ? `date/time moved forward${by ? ` ${by}` : ''}`
        : `clock wrong by ${by || 'a lot'} vs the server`;
      const product = typeof p.productCode === 'string' ? p.productCode : 'An app';
      return `${product}: ${what}${where ? ` on ${where}` : ''} — app blocked`;
    }
    case 'LICENSE_EXPIRING':
      return 'A licence is about to expire';
    case 'LICENSE_EXPIRED':
      return 'A licence has expired';
    default:
      return n.eventType.replace(/_/g, ' ').toLowerCase();
  }
}
