/**
 * Viewer — "Insights".
 *
 * A printed report rather than a console: a typographic hero band, a two-column
 * report body, the lifecycle pipeline, then clean read-only tables. There are no
 * buttons, links or row actions anywhere on this page — a viewer holds no
 * mutating permission, so offering an affordance would only mislead.
 */
import { Donut, MiniBars } from '../../components/Viz';
import type { DonutSlice } from '../../components/Viz';
import { StatusBadge } from '../../components/StatusBadge';
import { dashboardApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useAuth } from '../../auth/AuthContext';
import { useRoleIdentity } from '../../auth/useRoleIdentity';
import { formatDateTime, formatNumber, expiryLabel } from '../../utils/format';
import type { DashboardData } from '../../types';
import { LifecyclePipeline, STATUS_CHART_COLORS, dashboardGate, identityLine } from './shared';

export function ViewerDashboard() {
  const { user } = useAuth();
  const role = useRoleIdentity();
  const { data, loading, error, reload } = useApi<DashboardData>(() => dashboardApi.get(), []);

  const gate = dashboardGate(loading, error, reload);
  if (gate) return gate;
  if (!data) return null;

  const t = data.totals;
  const who = identityLine(user);

  const slices: DonutSlice[] = (data.licensesByStatus ?? []).map((s) => ({
    label: s.status,
    value: s.count,
    color: STATUS_CHART_COLORS[s.status] ?? '#64748b',
  }));

  /* The three headline figures are totals straight from /admin/dashboard. */
  const headline: Array<{ label: string; value: number; note: string }> = [
    { label: 'Total licences', value: t.licenses, note: 'Issued across every product' },
    { label: 'Active', value: t.activeLicenses, note: `${formatNumber(t.expiringSoon)} expiring in 30 days` },
    { label: 'Activations', value: t.totalActivations, note: 'Devices currently recorded' },
  ];

  const products = data.products ?? [];

  return (
    <div className="mx-auto max-w-[1080px]">
      <header className="pb-8 pt-4">
        <h1 className="text-[34px] font-bold leading-[1.15] tracking-[-0.03em]">{role.workspace}</h1>
        <p className="m-0 mt-2 text-lg text-ink-2">{role.purpose}</p>
        {who && <p className="m-0 mt-1 text-sm text-muted">{who}</p>}
      </header>

      <section className="mb-10 grid grid-cols-3 gap-8 border-0 border-y border-solid border-line py-8 max-[900px]:grid-cols-[1fr] max-[900px]:gap-6">
        {headline.map((h) => (
          <div key={h.label} className="min-w-0">
            <div className="text-[56px] font-bold leading-none tracking-[-0.04em] text-primary tabular-nums max-[900px]:text-[44px]">
              {formatNumber(h.value)}
            </div>
            <div className="mt-3 text-md font-[650] tracking-[0.02em]">{h.label}</div>
            <div className="mt-0.5 text-sm text-muted">{h.note}</div>
          </div>
        ))}
      </section>

      <div className="mb-10 grid grid-cols-2 gap-10 max-[900px]:grid-cols-[1fr] max-[900px]:gap-8">
        <section className="min-w-0">
          <h2 className="text-xl font-[650] tracking-[-0.01em]">Licensing integrity</h2>
          <p className="m-0 mb-5 mt-1 text-md text-ink-2">How the estate divides across licence status today.</p>
          {slices.length === 0 ? (
            <div className="py-6 text-md text-muted">No licence data yet.</div>
          ) : (
            <div className="flex flex-wrap items-center justify-center gap-6 py-2">
              <Donut
                slices={slices}
                centerValue={formatNumber(t.licenses)}
                centerLabel="Total licenses"
              />
              <ul className="m-0 min-w-[168px] list-none p-0">
                {slices.map((s) => (
                  <li key={s.label} className="flex items-center gap-2 py-[5px] text-base">
                    <span
                      className="h-[9px] w-[9px] shrink-0 rounded-[50%]"
                      style={{ background: s.color, boxShadow: `0 0 8px ${s.color}` }}
                    />
                    <span className="flex-1 text-ink-2">
                      {s.label.charAt(0) + s.label.slice(1).toLowerCase()}
                    </span>
                    <span className="font-bold tabular-nums">{formatNumber(s.value)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section className="min-w-0">
          <h2 className="text-xl font-[650] tracking-[-0.01em]">By product</h2>
          <p className="m-0 mb-5 mt-1 text-md text-ink-2">
            Active, expiring, expired and installed counts for each licensable product.
          </p>
          {products.length === 0 ? (
            <div className="py-6 text-md text-muted">No products yet.</div>
          ) : (
            <ul className="m-0 list-none p-0">
              {products.map((p) => (
                <li key={p.productId} className="border-0 border-b border-solid border-line py-4 last:border-b-0">
                  <div className="mb-3 flex items-baseline justify-between gap-3">
                    <span className="min-w-0 text-md font-semibold">{p.productName}</span>
                    <span className="mono text-xs text-muted">{p.productCode}</span>
                  </div>
                  <MiniBars
                    height={52}
                    bars={[
                      { label: 'Active', value: p.activeLicenses, color: '#34d399' },
                      { label: 'Expiring', value: p.expiringSoon, color: '#fbbf24' },
                      { label: 'Expired', value: p.expiredLicenses, color: '#fb7185' },
                      { label: 'Installs', value: p.activations, color: '#22d3ee' },
                    ]}
                  />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="mb-10 [&>div]:mt-2">
        <h2 className="text-xl font-[650] tracking-[-0.01em]">Licence lifecycle</h2>
        <p className="m-0 mb-5 mt-1 text-md text-ink-2">Where every licence currently sits in its life.</p>
        <LifecyclePipeline totals={t} />
      </section>

      <section className="mb-10">
        <h2 className="text-xl font-[650] tracking-[-0.01em]">Recent licences</h2>
        <div className="table-wrap mt-4">
          <table className="data-table [&_td]:py-[13px] [&_th]:text-xs">
            <thead>
              <tr>
                <th>License</th>
                <th>Customer</th>
                <th>Product</th>
                <th>Status</th>
                <th>Expiry</th>
              </tr>
            </thead>
            <tbody>
              {(data.recentLicenses ?? []).length === 0 && (
                <tr>
                  <td colSpan={5}>
                    <div className="table-empty">No licenses yet.</div>
                  </td>
                </tr>
              )}
              {(data.recentLicenses ?? []).map((l) => (
                <tr key={l.licenseId}>
                  <td className="mono">{l.licenseNo}</td>
                  <td>{l.customerName ?? l.customerId}</td>
                  <td>{l.productName ?? l.productCode}</td>
                  <td>
                    <StatusBadge status={l.status} />
                  </td>
                  <td className="nowrap">{expiryLabel(l.expiryDate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-10">
        <h2 className="text-xl font-[650] tracking-[-0.01em]">Recent activations</h2>
        <div className="table-wrap mt-4">
          <table className="data-table [&_td]:py-[13px] [&_th]:text-xs">
            <thead>
              <tr>
                <th>License</th>
                <th>Device</th>
                <th>Product</th>
                <th>Activated</th>
              </tr>
            </thead>
            <tbody>
              {(data.recentActivations ?? []).length === 0 && (
                <tr>
                  <td colSpan={4}>
                    <div className="table-empty">No activations yet.</div>
                  </td>
                </tr>
              )}
              {(data.recentActivations ?? []).map((a) => (
                <tr key={a.activationId}>
                  <td className="mono">{a.licenseNo ?? a.licenseId}</td>
                  <td>{a.deviceName ?? a.installationId}</td>
                  <td>{a.productName ?? a.productCode}</td>
                  <td className="nowrap">{formatDateTime(a.activatedAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
