import { useEffect, useState } from 'react';
import { Icon } from './Icon';
import { systemApi } from '../services/api/endpoints';

/**
 * The licence server's date and time (the same clock the installed apps trust),
 * shown in the top bar. Read from the server every 5 minutes and advanced locally
 * every second, so it is right even when this browser's own clock is not.
 */
export function ServerClock() {
  const [offset, setOffset] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    const sync = () => {
      const sent = Date.now();
      systemApi
        .time()
        .then((t) => {
          if (cancelled) return;
          const received = Date.now();
          const server = Date.parse(t.serverTime) + (received - sent) / 2;
          setOffset(server - received);
        })
        .catch(() => undefined);
    };
    sync();
    const s = window.setInterval(sync, 5 * 60 * 1000);
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(s);
      window.clearInterval(t);
    };
  }, []);

  if (offset === null) return null;
  const d = new Date(now + offset);
  const date = d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }).replace(/ /g, '-');
  const time = d.toLocaleTimeString('en-GB', { hour12: false });
  const drift = Math.abs(offset) > 60_000;
  return (
    <div
      className="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-solid border-line bg-surface px-3 py-1 text-sm text-ink-2 max-[1100px]:hidden"
      title={
        drift
          ? `Licence server time. This computer's clock differs from it by ${Math.round(Math.abs(offset) / 60000)} min.`
          : 'Licence server time — the clock the installed apps are checked against'
      }
    >
      <Icon name="clock" size={14} className={drift ? 'text-warning' : 'text-primary'} />
      <span className="text-muted">Server</span>
      <span className="font-mono text-ink">{date} {time}</span>
    </div>
  );
}
