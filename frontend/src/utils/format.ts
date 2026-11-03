const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** DD-Mon-YYYY, e.g. 26-Aug-2026. Returns '—' for empty values. */
export function formatDate(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const day = String(d.getDate()).padStart(2, '0');
  return `${day}-${MONTHS[d.getMonth()]}-${d.getFullYear()}`;
}

/** DD-Mon-YYYY HH:mm */
export function formatDateTime(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${formatDate(value)} ${hh}:${mm}`;
}

export function formatCurrency(amount?: number | null, currency?: string | null): string {
  if (amount === null || amount === undefined) return '—';
  const cur = currency || 'INR';
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: cur,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${cur} ${amount.toFixed(2)}`;
  }
}

export function formatNumber(n?: number | null): string {
  if (n === null || n === undefined) return '—';
  return new Intl.NumberFormat('en-IN').format(n);
}

/** Days until a date; negative if past. null for lifetime/no date. */
export function daysUntil(value?: string | null): number | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  d.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / 86400000);
}

export function expiryLabel(expiryDate?: string | null): string {
  if (!expiryDate) return 'Lifetime';
  const days = daysUntil(expiryDate);
  if (days === null) return formatDate(expiryDate);
  if (days < 0) return `${formatDate(expiryDate)} (expired)`;
  if (days === 0) return `${formatDate(expiryDate)} (today)`;
  if (days <= 30) return `${formatDate(expiryDate)} (${days}d left)`;
  return formatDate(expiryDate);
}

export function prettyJson(value: string | Record<string, unknown> | null | undefined): string {
  if (value === null || value === undefined || value === '') return '';
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  return JSON.stringify(value, null, 2);
}
