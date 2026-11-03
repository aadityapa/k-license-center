/**
 * Admin dashboard — widget layout the admin can rearrange (see WidgetGrid).
 *
 * Every figure comes from GET /admin/dashboard/overview, which computes it from
 * real records. Where the system has no data (no plan prices set, no
 * activations yet) the widget says so instead of drawing invented numbers.
 */
import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Area, Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, BarChart,
} from 'recharts';
import { Donut } from '../../components/Viz';
import { Icon } from '../../components/Icon';
import type { IconName } from '../../components/Icon';
import { StatusBadge } from '../../components/StatusBadge';
import { Spinner } from '../../components/Spinner';
import { ErrorState } from '../../components/ErrorState';
import { dashboardApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useAuth } from '../../auth/AuthContext';
import { formatCurrency, formatDate, formatDateTime, formatNumber } from '../../utils/format';
import type { DashboardOverview, OverviewKpi } from '../../types';
import { WidgetGrid } from './WidgetGrid';
import type { WidgetDef, WidgetSize } from './WidgetGrid';

const PERIODS = [7, 30, 90, 180, 365] as const;
const PERIOD_LABEL: Record<number, string> = { 7: 'Last 7 days', 30: 'Last 30 days', 90: 'Last 90 days', 180: 'Last 6 months', 365: 'Last 12 months' };

const C = {
  blue: '#3b82f6', sky: '#38bdf8', green: '#22c55e', orange: '#f97316', violet: '#8b5cf6',
  pink: '#ec4899', amber: '#f59e0b', red: '#ef4444', slate: '#94a3b8', teal: '#14b8a6',
};
const PRODUCT_COLORS = [C.blue, C.green, C.orange, C.violet, C.pink, C.teal, C.amber, C.sky];

/** KPI icon chip tints, keyed by the tile's tone (also the sparkline gradient id). */
const KPI_TONE: Record<string, string> = {
  't-green': 'bg-[color-mix(in_srgb,#22c55e_15%,transparent)] text-[#16a34a]',
  't-blue': 'bg-[color-mix(in_srgb,#3b82f6_15%,transparent)] text-[#2563eb]',
  't-violet': 'bg-[color-mix(in_srgb,#8b5cf6_15%,transparent)] text-[#7c3aed]',
  't-orange': 'bg-[color-mix(in_srgb,#f97316_15%,transparent)] text-[#ea580c]',
};

/** Pending-action icon tint: red for security alerts, blue for requests, amber otherwise. */
function actionTone(key: string): string {
  if (key === 'security' || key === 'failedActs' || key === 'clock') return 'bg-[color-mix(in_srgb,#ef4444_14%,transparent)] text-[#dc2626]';
  if (key === 'requests' || key === 'changes') return 'bg-[color-mix(in_srgb,#3b82f6_14%,transparent)] text-[#2563eb]';
  return 'bg-[color-mix(in_srgb,#f59e0b_15%,transparent)] text-[#d97706]';
}

/** Widget body when there is nothing to show. */
const EMPTY = 'px-2 py-[26px] text-center text-sm text-muted';

/** Donut + legend side by side (licence status, revenue by product). */
const DONUT_ROW = 'flex flex-wrap items-center justify-center gap-[18px]';
const LEGEND = 'm-0 grid min-w-[190px] flex-1 list-none gap-1.5 p-0';
const LEGEND_ROW =
  'grid cursor-pointer grid-cols-[12px_1fr_auto_52px] items-center gap-2 rounded px-1.5 py-1 text-base hover:bg-[color-mix(in_srgb,var(--primary)_8%,transparent)]';
const LEGEND_DOT = 'h-2.5 w-2.5 rounded-[50%]';

/** System-health link tiles; the icon turns amber/red when something needs a look. */
const TILE =
  'grid grid-cols-[auto_1fr] grid-rows-[auto_auto] items-center gap-x-2 gap-y-0 rounded-[12px] border border-solid border-line p-2.5 text-ink no-underline';
const TILE_LABEL = 'text-xs leading-[1.2] text-muted';
const tileIcon = (tone: '' | 'warn' | 'bad') =>
  `row-[1/span_2] ${tone === 'bad' ? 'text-[#ef4444]' : tone === 'warn' ? 'text-[#f59e0b]' : 'text-[#3b82f6]'}`;

/** Thin progress track (top products, top customers). */
const TRACK = 'h-1.5 overflow-hidden rounded-[4px] bg-line';

const inr = (v: number) => formatCurrency(v, 'INR').replace(/\.00$/, '');
const shortInr = (v: number) =>
  v >= 1e7 ? `₹${(v / 1e7).toFixed(1)}Cr` : v >= 1e5 ? `₹${(v / 1e5).toFixed(1)}L` : v >= 1e3 ? `₹${(v / 1e3).toFixed(0)}K` : `₹${v}`;
const shortDay = (iso: string) => {
  const d = new Date(`${iso}T00:00:00`);
  return `${d.toLocaleString('en', { month: 'short' })} ${String(d.getDate()).padStart(2, '0')}`;
};

/* ------------------------------------------------------------------ */
/* KPI card                                                            */
/* ------------------------------------------------------------------ */
function Delta({ k, suffix }: { k: OverviewKpi; suffix: string }) {
  if (k.changePct === null) return <span className="text-[12.5px] font-semibold text-[#16a34a]">new {suffix}</span>;
  const up = k.changePct > 0;
  const flat = k.changePct === 0;
  return (
    <span className={`text-[12.5px] ${flat ? 'font-medium text-muted' : up ? 'font-semibold text-[#16a34a]' : 'font-semibold text-[#dc2626]'}`}>
      {!flat && <span aria-hidden="true">{up ? '↑' : '↓'}</span>}
      {flat ? 'no change' : `${Math.abs(k.changePct)}%`} <span className="font-normal text-muted">{suffix}</span>
    </span>
  );
}

function Kpi({ icon, tone, label, value, kpi, series, color, note, to }: {
  icon: IconName; tone: string; label: string; value: string; kpi: OverviewKpi;
  series: number[]; color: string; note?: string; to?: string;
}) {
  const data = series.map((v, i) => ({ i, v }));
  const body = (
    <div data-kpi className="grid grid-cols-[auto_1fr] grid-rows-[auto_auto] items-start gap-x-3.5 gap-y-1">
      <span className={`row-[1/span_2] flex h-12 w-12 items-center justify-center rounded-lg ${KPI_TONE[tone] ?? ''}`}><Icon name={icon} size={22} /></span>
      <div className="dk-kpi-main">
        <div className="text-base text-ink-2">{label}</div>
        <div className="my-0.5 text-[26px] font-extrabold leading-[1.2] tracking-[-0.02em]">{value}</div>
        <Delta k={kpi} suffix="vs previous period" />
        {note && <div className="mt-[3px] text-[11.5px] text-muted">{note}</div>}
      </div>
      <div className="col-[1/-1] mt-1.5" aria-hidden="true">
        <ResponsiveContainer width="100%" height={46}>
          <ComposedChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={`g-${tone}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area type="monotone" dataKey="v" stroke={color} strokeWidth={2} fill={`url(#g-${tone})`} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
  return to ? <Link to={to} className="block text-inherit no-underline">{body}</Link> : body;
}

/* ------------------------------------------------------------------ */
/* Sortable table                                                      */
/* ------------------------------------------------------------------ */
interface Col<T> { key: string; header: string; value: (r: T) => string | number | null; render?: (r: T) => ReactNode; align?: 'right' }

function SortTable<T>({ rows, cols, empty, onRow, initial }: {
  rows: T[]; cols: Col<T>[]; empty: string; onRow?: (r: T) => void; initial?: { key: string; dir: 1 | -1 };
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(initial ?? null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = cols.find((c) => c.key === sort.key);
    if (!col) return rows;
    return [...rows].sort((a, b) => {
      const x = col.value(a);
      const y = col.value(b);
      if (x === y) return 0;
      if (x === null || x === undefined || x === '') return 1;
      if (y === null || y === undefined || y === '') return -1;
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))) * sort.dir;
    });
  }, [rows, cols, sort]);
  if (rows.length === 0) return <div className={EMPTY}>{empty}</div>;
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="dk-table w-full border-collapse text-base">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className="border-0 border-b border-solid border-line bg-[color-mix(in_srgb,var(--border)_35%,transparent)] p-0 text-left">
                <button
                  type="button"
                  className={c.align === 'right' ? 'justify-end' : ''}
                  onClick={() => setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === 1 ? -1 : 1 } : { key: c.key, dir: 1 }))}
                  aria-label={`Sort by ${c.header}`}
                >
                  {c.header}
                  <span className="text-[9px] opacity-60">{sort?.key === c.key ? (sort.dir === 1 ? '▲' : '▼') : '↕'}</span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr
              key={i}
              className={`[&:last-child>td]:border-b-0 ${onRow ? 'cursor-pointer [&:hover>td]:bg-[color-mix(in_srgb,var(--primary)_6%,transparent)]' : ''}`}
              onClick={onRow ? () => onRow(r) : undefined}
            >
              {cols.map((c) => (
                <td
                  key={c.key}
                  className={`whitespace-nowrap border-0 border-b border-solid border-line px-2 py-[9px] ${c.align === 'right' ? 'text-right' : ''}`}
                >{c.render ? c.render(r) : (c.value(r) ?? '—')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const ViewAll = ({ to }: { to: string }) => <Link className="dk-viewall" to={to}>View all</Link>;

/* ------------------------------------------------------------------ */
/* Dashboard                                                           */
/* ------------------------------------------------------------------ */
export function AdminDashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [days, setDays] = useState<number>(() => {
    try {
      const v = Number(localStorage.getItem('klc.dash.days'));
      return PERIODS.includes(v as (typeof PERIODS)[number]) ? v : 30;
    } catch {
      return 30;
    }
  });
  const { data, loading, error, reload } = useApi(() => dashboardApi.overview(days), [days]);
  const pickDays = (d: number) => {
    setDays(d);
    try { localStorage.setItem('klc.dash.days', String(d)); } catch { /* ignore */ }
  };

  const widgets = useMemo<WidgetDef[]>(() => (data ? buildWidgets(data, navigate) : []), [data, navigate]);

  const firstName = user?.fullName || user?.username || 'Admin';
  const head = (
    <div className="mb-3.5 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="m-0 text-[26px] tracking-[-0.02em]">Dashboard</h1>
        <p className="m-0 mt-1 text-sm text-ink-2">Welcome back, {firstName}! Here's what's happening with your licences.</p>
      </div>
      <div className="flex items-center gap-2.5">
        {/* text-sm here sizes the select, which inherits its font */}
        <label className="inline-flex h-9 items-center gap-1.5 rounded-md border border-solid border-line bg-surface px-2.5 text-sm text-ink-2">
          <Icon name="clock" size={15} />
          <select
            className="cursor-pointer border-0 bg-transparent text-ink [font:inherit] [outline:0]"
            value={days} onChange={(e) => pickDays(Number(e.target.value))} aria-label="Period">
            {PERIODS.map((p) => <option key={p} value={p}>{PERIOD_LABEL[p]}</option>)}
          </select>
        </label>
        {loading && data && <Spinner size={16} />}
        <Link to="/licenses?new=1" className="btn btn-primary">
          <Icon name="plus" size={15} /> Issue Licence
        </Link>
      </div>
    </div>
  );

  if (!data) {
    return (
      <div className="dk">
        {head}
        {error ? <div className="card"><ErrorState error={error} onRetry={reload} /></div> : <div className="fullpage-center" style={{ height: '50vh' }}><Spinner size={32} /></div>}
      </div>
    );
  }

  return (
    <div className="dk">
      {head}
      <WidgetGrid storageKey={`klc.dash.layout.${user?.userId ?? 'anon'}`} widgets={widgets} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Widgets                                                             */
/* ------------------------------------------------------------------ */
function buildWidgets(d: DashboardOverview, navigate: (to: string) => void): WidgetDef[] {
  const k = d.kpis;
  const s = d.series;
  const ls = d.licenseStatus;
  const noRevenue = k.revenue.value === 0 && k.revenue.previous === 0;
  const priced = d.products.filter((p) => p.revenue > 0);
  const totalRev = priced.reduce((a, p) => a + p.revenue, 0);
  const chartData = s.map((p) => ({ ...p, label: shortDay(p.date) }));
  const tick = Math.max(1, Math.ceil(s.length / 10));

  const kpi = (id: string, el: ReactNode): WidgetDef => ({ id, title: '', bare: true, defaultSize: 1, sizes: [1, 2], render: () => el });

  const widgets: WidgetDef[] = [
    {
      ...kpi('kpi-revenue', null),
      title: 'Total Revenue',
      render: () => (
        <Kpi icon="trending-up" tone="t-green" color={C.green} label={`Revenue · ${PERIOD_LABEL[d.period.days]?.toLowerCase()}`} value={inr(k.revenue.value)}
          kpi={k.revenue} series={s.map((p) => p.revenue)} to="/renewals"
          note={noRevenue ? 'Enter the amount when issuing a licence to see revenue' : undefined} />
      ),
    },
    {
      ...kpi('kpi-licenses', null),
      title: 'Total Licences',
      render: () => (
        <Kpi icon="file-text" tone="t-blue" color={C.blue} label="Total licences" value={formatNumber(k.licenses.value)}
          kpi={k.licenses} series={s.map((p) => p.licenses)} to="/licenses" note={`${k.licenses.periodNew ?? 0} new in this period`} />
      ),
    },
    {
      ...kpi('kpi-customers', null),
      title: 'Active Customers',
      render: () => (
        <Kpi icon="users" tone="t-violet" color={C.violet} label="Active customers" value={formatNumber(k.activeCustomers.value)}
          kpi={k.activeCustomers} series={d.customerGrowth.map((m) => m.newCustomers)} to="/customers"
          note={`${k.activeCustomers.periodNew ?? 0} new customers in this period`} />
      ),
    },
    {
      ...kpi('kpi-activations', null),
      title: 'Activations',
      render: () => (
        <Kpi icon="activity" tone="t-orange" color={C.orange} label="Activations in period" value={formatNumber(k.activations.value)}
          kpi={k.activations} series={s.map((p) => p.activations)} to="/activations" />
      ),
    },

    {
      id: 'trend', title: 'Revenue & Sales Trend', defaultSize: 3, sizes: [2, 3, 4],
      subtitle: PERIOD_LABEL[d.period.days],
      render: () => (
        <div className="w-full">
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" interval={tick - 1} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} />
              <YAxis yAxisId="rev" tickFormatter={shortInr} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} width={52} />
              <YAxis yAxisId="cnt" orientation="right" allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} width={30} />
              <Tooltip
                contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, fontSize: 12 }}
                formatter={(v: number, name: string) => (name === 'Revenue (₹)' ? inr(v) : v)}
              />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Bar yAxisId="rev" dataKey="revenue" name="Revenue (₹)" fill={C.blue} radius={[4, 4, 0, 0]} maxBarSize={14} />
              <Line yAxisId="cnt" type="monotone" dataKey="licenses" name="Licences issued" stroke={C.green} strokeWidth={2} dot={false} />
              <Line yAxisId="cnt" type="monotone" dataKey="activations" name="Activations" stroke={C.orange} strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ),
    },

    {
      id: 'top-products', title: 'Top Products', defaultSize: 1, sizes: [1, 2, 3, 4],
      actions: <ViewAll to="/products" />,
      render: () => {
        const max = Math.max(1, ...d.products.map((p) => (totalRev > 0 ? p.revenue : p.total)));
        if (d.products.length === 0) return <div className={EMPTY}>No products yet.</div>;
        return (
          <ol className="m-0 grid list-none gap-3 p-0">
            {d.products.slice(0, 6).map((p, i) => {
              const metric = totalRev > 0 ? p.revenue : p.total;
              return (
                <li key={p.productCode} className="grid grid-cols-[22px_36px_1fr_auto] items-center gap-2.5">
                  <span
                    className={`flex h-[22px] w-[22px] items-center justify-center rounded-[6px] text-sm font-bold ${
                      i === 0 ? 'bg-[#fef3c7] text-[#b45309]' : 'bg-line text-ink-2'
                    }`}
                  >
                    {i + 1}
                  </span>
                  <span className="flex h-9 w-9 items-center justify-center rounded-md text-sm font-extrabold text-white" style={{ background: PRODUCT_COLORS[i % PRODUCT_COLORS.length] }}>
                    {p.productName.slice(0, 2).toUpperCase()}
                  </span>
                  <span className="flex min-w-0 flex-col gap-[3px]">
                    <span className="text-md font-semibold">{p.productName}</span>
                    <span className="text-[11.5px] text-muted">{p.licenses} new · {p.active} active of {p.total}</span>
                    <span className={TRACK}><span className="block h-full rounded-[4px]" style={{ width: `${(metric / max) * 100}%`, background: PRODUCT_COLORS[i % PRODUCT_COLORS.length] }} /></span>
                  </span>
                  <span className="flex flex-col text-right text-[13.5px] font-bold">
                    {totalRev > 0 ? inr(p.revenue) : `${p.total} licences`}
                    {totalRev > 0 && <span className="text-xs font-medium text-muted">{Math.round((p.revenue / totalRev) * 100)}%</span>}
                  </span>
                </li>
              );
            })}
          </ol>
        );
      },
    },

    {
      id: 'customer-growth', title: 'Customer Growth', subtitle: 'Last 6 months', defaultSize: 1, sizes: [1, 2, 3, 4],
      render: () => (
        <div className="w-full">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={d.customerGrowth} margin={{ top: 8, right: 4, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, fontSize: 12 }} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="newCustomers" name="New customers" fill={C.sky} radius={[4, 4, 0, 0]} maxBarSize={18} />
              <Bar dataKey="totalCustomers" name="Total customers" fill={C.blue} radius={[4, 4, 0, 0]} maxBarSize={18} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ),
    },

    {
      id: 'status', title: 'Licence Status Overview', defaultSize: 1, sizes: [1, 2],
      actions: <ViewAll to="/licenses" />,
      render: () => {
        const rows = [
          { label: 'Active', value: ls.active, color: C.green, status: 'ACTIVE' },
          { label: 'Suspended', value: ls.suspended, color: C.amber, status: 'SUSPENDED' },
          { label: 'Expired', value: ls.expired, color: C.red, status: 'EXPIRED' },
          { label: 'Revoked', value: ls.revoked, color: C.pink, status: 'REVOKED' },
          { label: 'Draft', value: ls.draft, color: C.slate, status: 'DRAFT' },
        ];
        return (
          <div className={DONUT_ROW}>
            <div className="flex-none">
              <Donut slices={rows.filter((r) => r.value > 0).map((r) => ({ label: r.label, value: r.value, color: r.color }))} size={168} thickness={22} centerValue={formatNumber(ls.total)} centerLabel="Total licences" />
            </div>
            <ul className={LEGEND}>
              {rows.map((r) => (
                <li key={r.label} className={LEGEND_ROW} onClick={() => navigate(`/licenses?status=${r.status}`)}>
                  <span className={LEGEND_DOT} style={{ background: r.color }} />
                  <span className="dk-legend-label">{r.label}</span>
                  <span className="font-bold">{r.value}</span>
                  <span className="text-right text-sm text-muted">{ls.total ? `${((r.value / ls.total) * 100).toFixed(1)}%` : '—'}</span>
                </li>
              ))}
              <li className={LEGEND_ROW} onClick={() => navigate('/licenses?status=ACTIVE&sort=expiryDate')}>
                <span className={LEGEND_DOT} style={{ background: C.blue }} />
                <span className="dk-legend-label">Expiring in 30 days</span>
                <span className="font-bold">{ls.expiringSoon}</span>
                <span className="text-right text-sm text-muted">{ls.total ? `${((ls.expiringSoon / ls.total) * 100).toFixed(1)}%` : '—'}</span>
              </li>
            </ul>
          </div>
        );
      },
    },

    {
      id: 'top-customers', title: 'Top Customers by Seats in Use', defaultSize: 1, sizes: [1, 2, 3, 4],
      actions: <ViewAll to="/customers" />,
      render: () => {
        const max = Math.max(1, ...d.topCustomers.map((c) => c.seats));
        if (d.topCustomers.length === 0) return <div className={EMPTY}>No active licences yet.</div>;
        return (
          <ul className="m-0 grid list-none gap-3 p-0">
            {d.topCustomers.map((c) => (
              <li
                key={c.customerId}
                className="grid cursor-pointer grid-cols-[1fr_auto] gap-x-2.5 gap-y-1 text-base"
                onClick={() => navigate(`/customers/${c.customerId}`)}
              >
                <span className="truncate font-semibold">{c.customerName}</span>
                <span className="text-sm text-muted">{c.seats} seat{c.seats === 1 ? '' : 's'} · {c.licenses} lic.</span>
                <span className={`col-[1/-1] ${TRACK}`}><span className="block h-full rounded-[4px] bg-[linear-gradient(90deg,#38bdf8,#3b82f6)]" style={{ width: `${Math.max(4, (c.seats / max) * 100)}%` }} /></span>
              </li>
            ))}
          </ul>
        );
      },
    },

    {
      id: 'health', title: 'System Health', defaultSize: 1, sizes: [1, 2],
      actions: <Link className="dk-viewall" to="/api-logs">View details</Link>,
      render: () => {
        const h = d.health;
        const ring = (pct: number, label: string, ok: string) => {
          const color = pct >= 98 ? C.green : pct >= 90 ? C.amber : C.red;
          const r = 34;
          const c = 2 * Math.PI * r;
          return (
            <div className="relative flex flex-col items-center text-center">
              <svg width="86" height="86" viewBox="0 0 86 86" aria-hidden="true">
                <circle cx="43" cy="43" r={r} fill="none" stroke="var(--border)" strokeWidth="7" />
                <circle cx="43" cy="43" r={r} fill="none" stroke={color} strokeWidth="7" strokeLinecap="round"
                  strokeDasharray={`${(pct / 100) * c} ${c}`} transform="rotate(-90 43 43)" />
              </svg>
              <span className="absolute top-[30px] text-[17px] font-extrabold">{Math.round(pct)}%</span>
              <span className="mt-1 text-sm text-ink-2">{label}</span>
              <span className="text-[11.5px] font-semibold" style={{ color }}>{pct >= 90 ? '✓' : '!'} {ok}</span>
            </div>
          );
        };
        return (
          <div className="flex flex-col gap-3.5">
            <div className="grid grid-cols-[repeat(3,1fr)] gap-1.5">
              {ring(h.apiSuccessPct, 'API (24h)', h.requests24h ? `${h.requests24h} calls` : 'Online')}
              {ring(h.authSuccessPct, 'Licence checks OK', h.requests24h ? 'last 24h' : 'No calls yet')}
              {ring(100, 'Database', 'Connected')}
            </div>
            <div className="grid grid-cols-[repeat(3,1fr)] gap-2">
              <Link to="/license-requests" className={TILE}><Icon name="inbox" size={16} className={tileIcon('')} /><b className="text-[17px]">{h.pendingRequests}</b><span className={TILE_LABEL}>Pending requests</span></Link>
              <Link to="/audit-logs" className={TILE} title="Unauthorised API calls (24h) + clock-tampering alerts (7 days)"><Icon name="alert-triangle" size={16} className={tileIcon((h.clockAlerts7d ?? 0) > 0 ? 'bad' : h.securityAlerts ? 'warn' : '')} /><b className="text-[17px]">{h.securityAlerts + (h.clockAlerts7d ?? 0)}</b><span className={TILE_LABEL}>Security alerts</span></Link>
              <Link to="/api-logs" className={TILE}><Icon name="ban" size={16} className={tileIcon(h.failedActivations24h ? 'bad' : '')} /><b className="text-[17px]">{h.failedActivations24h}</b><span className={TILE_LABEL}>Failed activations</span></Link>
            </div>
          </div>
        );
      },
    },

    {
      id: 'recent-licenses', title: 'Recent Licences', defaultSize: 3, sizes: [2, 3, 4],
      actions: <ViewAll to="/licenses" />,
      render: () => (
        <SortTable
          rows={d.recentLicenses}
          empty="No licences yet."
          onRow={(r) => navigate(`/licenses/${r.licenseId}`)}
          cols={[
            { key: 'no', header: 'Licence no', value: (r) => r.licenseNo, render: (r) => <span className="mono">{r.licenseNo}</span> },
            { key: 'cust', header: 'Customer', value: (r) => r.customerName },
            { key: 'prod', header: 'Product', value: (r) => r.productName },
            { key: 'plan', header: 'Plan', value: (r) => r.planName },
            { key: 'status', header: 'Status', value: (r) => r.status, render: (r) => <StatusBadge status={r.status} /> },
            { key: 'created', header: 'Created', value: (r) => r.createdAt, render: (r) => formatDate(r.createdAt) },
            { key: 'exp', header: 'Expiry', value: (r) => r.expiryDate, render: (r) => (r.expiryDate ? formatDate(r.expiryDate) : '—') },
          ]}
        />
      ),
    },

    {
      id: 'recent-activations', title: 'Recent Activations', defaultSize: 3, sizes: [2, 3, 4],
      actions: <ViewAll to="/activations" />,
      render: () => (
        <SortTable
          rows={d.recentActivations}
          empty="No activations yet — they appear when an app registers a machine."
          onRow={(r) => navigate(`/licenses/${r.licenseId}`)}
          cols={[
            { key: 'lic', header: 'Licence', value: (r) => r.licenseNo, render: (r) => <span className="mono">{r.licenseNo}</span> },
            { key: 'dev', header: 'Device', value: (r) => r.deviceName },
            { key: 'prod', header: 'Product', value: (r) => r.productName },
            { key: 'at', header: 'Activated', value: (r) => r.activatedAt, render: (r) => formatDateTime(r.activatedAt) },
            { key: 'status', header: 'Status', value: (r) => r.status, render: (r) => <StatusBadge status={r.status} /> },
          ]}
        />
      ),
    },

    {
      id: 'pending', title: 'Pending Actions', defaultSize: 1, sizes: [1, 2],
      render: () => {
        const open = d.pendingActions.filter((a) => a.count > 0);
        if (open.length === 0) {
          return (
            <div className="flex items-center justify-center gap-2 px-2 py-[26px] text-center text-sm text-[#16a34a]">
              <Icon name="check" size={18} /> Nothing waiting — all clear.
            </div>
          );
        }
        return (
          <ul className="m-0 grid list-none gap-1.5 p-0">
            {open.map((a) => (
              <li key={a.key}>
                <Link
                  to={a.to}
                  className="grid grid-cols-[30px_1fr_auto] items-center gap-2.5 rounded-md border border-solid border-line px-2.5 py-2 text-[13.5px] text-ink no-underline hover:border-primary hover:text-ink hover:no-underline"
                >
                  <span className={`flex h-[30px] w-[30px] items-center justify-center rounded ${actionTone(a.key)}`}><Icon name={a.key === 'security' || a.key === 'clock' ? 'alert-triangle' : a.key === 'expiring' ? 'clock' : a.key === 'emails' ? 'inbox' : 'clipboard'} size={15} /></span>
                  <span><b>{a.count}</b> {a.label}</span>
                  <Icon name="chevron-right" size={15} />
                </Link>
              </li>
            ))}
          </ul>
        );
      },
    },

    {
      id: 'revenue-by-product', title: 'Revenue by Product', subtitle: PERIOD_LABEL[d.period.days], defaultSize: 1, sizes: [1, 2],
      render: () => {
        if (totalRev === 0) {
          return <div className={EMPTY}>No revenue recorded in this period. Revenue comes from the amount entered when a licence is issued or renewed.</div>;
        }
        return (
          <div className={DONUT_ROW}>
            <div className="flex-none">
              <Donut slices={priced.map((p, i) => ({ label: p.productName, value: p.revenue, color: PRODUCT_COLORS[i % PRODUCT_COLORS.length]! }))}
                size={160} thickness={22} centerValue={shortInr(totalRev)} centerLabel="Revenue" />
            </div>
            <ul className={LEGEND}>
              {priced.map((p, i) => (
                <li key={p.productCode} className={LEGEND_ROW}>
                  <span className={LEGEND_DOT} style={{ background: PRODUCT_COLORS[i % PRODUCT_COLORS.length] }} />
                  <span className="dk-legend-label">{p.productName}</span>
                  <span className="font-bold">{inr(p.revenue)}</span>
                  <span className="text-right text-sm text-muted">{((p.revenue / totalRev) * 100).toFixed(1)}%</span>
                </li>
              ))}
            </ul>
          </div>
        );
      },
    },

    {
      id: 'recent-customers', title: 'Recent Customers', defaultSize: 3, sizes: [2, 3, 4],
      actions: <ViewAll to="/customers" />,
      render: () => (
        <SortTable
          rows={d.recentCustomers}
          empty="No customers yet."
          onRow={(r) => navigate(`/customers/${r.customerId}`)}
          cols={[
            { key: 'co', header: 'Company', value: (r) => r.companyName },
            { key: 'contact', header: 'Contact', value: (r) => r.contactPerson },
            { key: 'email', header: 'Email', value: (r) => r.email },
            { key: 'lic', header: 'Active lic.', value: (r) => r.activeLicenses, align: 'right' },
            { key: 'status', header: 'Status', value: (r) => r.status, render: (r) => <StatusBadge status={r.status} /> },
            { key: 'joined', header: 'Joined', value: (r) => r.createdAt, render: (r) => formatDate(r.createdAt) },
          ]}
        />
      ),
    },
  ];
  return widgets;
}

export type { WidgetSize };
