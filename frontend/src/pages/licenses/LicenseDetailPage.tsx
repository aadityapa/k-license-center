import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState, ErrorBanner } from '../../components/ErrorState';
import { PendingBanner } from '../../components/PendingBanner';
import { Spinner } from '../../components/Spinner';
import { CopyButton } from '../../components/CopyButton';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { Icon } from '../../components/Icon';
import { RowDelete } from '../../components/RowDelete';
import { LicenseActionButtons } from './LicenseActions';
import { VbsKeyPanel } from './VbsKeyPanel';
import { LicFilePanel } from './LicFilePanel';
import { activationsApi, auditApi, licensesApi } from '../../services/api/endpoints';
import { isPendingApproval } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import { useAuth } from '../../auth/AuthContext';
import { formatCurrency, formatDate, formatDateTime, expiryLabel } from '../../utils/format';
import type { Activation } from '../../types';

export function LicenseDetailPage() {
  const { id } = useParams();
  const licenseId = Number(id);
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const license = useApi(() => licensesApi.get(licenseId), [licenseId]);
  const audit = useApi(
    () => auditApi.list({ entity: 'LICENSE', entityId: licenseId, pageSize: 20, sort: 'createdAt:desc' }),
    [licenseId],
  );
  const [deactivating, setDeactivating] = useState<Activation | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  if (license.loading) {
    return (
      <div className="fullpage-center h-[50vh]">
        <Spinner size={30} />
      </div>
    );
  }

  if (license.error) {
    return (
      <div className="card">
        <ErrorState error={license.error} onRetry={license.reload} />
      </div>
    );
  }

  const l = license.data;
  if (!l) return null;

  const activeKey = l.licenseKey ?? l.keys?.find((k) => k.status === 'ACTIVE')?.licenseKey ?? null;
  // Vehicle SIM keys carry the entitlement, so they get their own issuance form
  // and need to wrap when displayed. Driven by the product's key format rather
  // than its code, so a future product with the same shape just works.
  const isVbs = l.keyFormat === 'VBS_KEY';
  const activations = l.activations ?? [];
  const renewals = l.renewals ?? [];
  const history = l.history ?? [];

  const reloadAll = () => {
    setPending(null);
    license.reload();
    audit.reload();
  };

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: 'Licenses', to: '/licenses' }, { label: l.licenseNo }]}
        title={
          <>
            <span className="mono">{l.licenseNo}</span> <StatusBadge status={l.status} />
          </>
        }
        subtitle={
          <>
            {l.customerName && (
              <>
                <Link to={`/customers/${l.customerId}`}>{l.customerName}</Link> ·{' '}
              </>
            )}
            {l.productName ?? l.productCode} — {l.planName ?? `Plan #${l.planId}`}
          </>
        }
        actions={
          <>
          <LicenseActionButtons
            license={l}
            onChanged={reloadAll}
            onPending={setPending}
            /*
             * Regenerate mints a typed PREF-XXXX-XXXX-XXXX key, which a Vehicle
             * SIM install cannot parse at all — it would hand the customer a key
             * that simply fails to activate. Vehicle SIM reissues through the
             * Vehicle SIM Key panel below instead, which supersedes the old key
             * the same way.
             */
            showRegenerate={!isVbs}
          />
          {hasPermission('LICENSE_MANAGE') && (
            <RowDelete
              compact={false}
              what={`licence ${l.licenseNo}`}
              confirmText={l.licenseNo}
              detail="Its keys, activations, renewals and history are deleted too. Apps using it stop working immediately."
              onDelete={() => {
                setPending(null);
                return licensesApi.remove(l.licenseId);
              }}
              onDeleted={() => navigate('/licenses', { replace: true })}
              onPending={setPending}
            />
          )}
          </>
        }
      />

      <ErrorBanner error={actionError} />
      <PendingBanner message={pending} />

      {activeKey && (
        <div className="card mb-4">
          <div className="card-header">
            <h2>License Key</h2>
          </div>
          <div className="card-body">
            {/* A Vehicle SIM key is ~180 characters, so it has to wrap rather
                than overflow the card the way a 19-character key never does. */}
            <div className={isVbs ? 'key-display break-all' : 'key-display'}>
              <span className={isVbs ? 'mono' : undefined}>{activeKey}</span>
              <CopyButton text={activeKey} />
            </div>
          </div>
        </div>
      )}

      {isVbs && l.status === 'ACTIVE' && (
        <VbsKeyPanel license={l} onChanged={reloadAll} onPending={setPending} />
      )}

      {l.keyFormat === 'LIC_FILE' && l.status === 'ACTIVE' && (
        <LicFilePanel license={l} onChanged={reloadAll} onPending={setPending} />
      )}

      <div className="card mb-4">
        <div className="card-header">
          <h2>License Information</h2>
        </div>
        <div className="card-body">
          <div className="def-grid">
            <div className="def-item">
              <div className="def-label">Serial Number</div>
              <div className="def-value">
                {l.serialNo ? (
                  <span className="inline-flex items-center gap-2">
                    <span className="mono">{l.serialNo}</span>
                    <CopyButton text={l.serialNo} />
                  </span>
                ) : '—'}
              </div>
            </div>
            <div className="def-item">
              <div className="def-label">Unique ID</div>
              <div className="def-value">
                {l.licenseUid ? (
                  <span className="inline-flex items-center gap-2">
                    <span className="mono text-sm">{l.licenseUid}</span>
                    <CopyButton text={l.licenseUid} />
                  </span>
                ) : '—'}
              </div>
            </div>
            <div className="def-item">
              <div className="def-label">Customer</div>
              <div className="def-value">
                <Link to={`/customers/${l.customerId}`}>{l.customerName ?? `#${l.customerId}`}</Link>
              </div>
            </div>
            <div className="def-item">
              <div className="def-label">Product</div>
              <div className="def-value">
                <Link to={`/products/${l.productId}`}>{l.productName ?? l.productCode ?? `#${l.productId}`}</Link>
              </div>
            </div>
            <div className="def-item">
              <div className="def-label">Plan</div>
              <div className="def-value">{l.planName ?? `#${l.planId}`}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Amount</div>
              <div className="def-value">{l.amount == null ? <span className="muted">Not recorded</span> : formatCurrency(Number(l.amount), l.currency ?? 'INR')}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Start Date</div>
              <div className="def-value">{formatDate(l.startDate)}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Expiry</div>
              <div className="def-value">{expiryLabel(l.expiryDate)}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Activations</div>
              <div className="def-value">
                {l.currentActivations} of {l.maxActivations} used
              </div>
            </div>
            <div className="def-item">
              <div className="def-label">Max Users</div>
              <div className="def-value">{l.maxUsers ?? 'Unlimited'}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Max Branches</div>
              <div className="def-value">{l.maxBranches ?? 'Unlimited'}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Auto Renewal</div>
              <div className="def-value">{l.autoRenewal ? 'Yes' : 'No'}</div>
            </div>
            <div className="def-item">
              <div className="def-label">Created</div>
              <div className="def-value">{formatDateTime(l.createdAt)}</div>
            </div>
          </div>
          {l.notes && (
            <div className="mt-3">
              <div className="def-label">Notes</div>
              <div>{l.notes}</div>
            </div>
          )}
        </div>
      </div>

      {(l.computers?.length ?? 0) > 0 && (
        <div className="card mb-4">
          <div className="card-header">
            <h2>Computer{(l.computers?.length ?? 0) > 1 ? `s (${l.computers?.length})` : ''}</h2>
            <span className="text-muted text-sm">Hardware reported by the app in its licence request</span>
          </div>
          <div className="card-body">
            {l.computers?.map((c, i) => (
              <div key={c.machineId} className={i > 0 ? 'mt-4 border-0 border-t border-solid border-line pt-4' : undefined}>
                <div className="def-grid">
                  {(
                    [
                      ['Machine ID', c.machineId, true],
                      ['MAC address', c.macAddress, true],
                      ['CPU ID', c.cpuId, true],
                      ['BIOS serial', c.biosSerial, true],
                      ['Motherboard', c.motherboardId, true],
                      ['Computer name', c.hostName, false],
                      ['Operating system', c.osName, false],
                      ['App version', c.appVersion, false],
                    ] as [string, string | null | undefined, boolean][]
                  ).map(([label, value, mono]) => (
                    <div className="def-item" key={label}>
                      <div className="def-label">{label}</div>
                      <div className="def-value">
                        {value ? (
                          <span className="inline-flex items-center gap-2">
                            <span className={mono ? 'mono' : undefined}>{value}</span>
                            {label === 'Machine ID' && <CopyButton text={value} label="" />}
                            {label === 'Machine ID' && c.boundToKey && <span className="badge badge-green">key bound</span>}
                          </span>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                {!c.requestId && (
                  <div className="text-muted text-sm mt-2">
                    No licence request from this computer, so only its Machine ID is known.
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card mb-4">
        <div className="card-header">
          <h2>Activations ({activations.length})</h2>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Device</th>
                <th>Installation ID</th>
                <th>OS</th>
                <th>App Version</th>
                <th>Status</th>
                <th>Activated</th>
                <th>Last Heartbeat</th>
                {hasPermission('ACTIVATION_MANAGE') && <th />}
              </tr>
            </thead>
            <tbody>
              {activations.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <div className="table-empty">No activations yet.</div>
                  </td>
                </tr>
              )}
              {activations.map((a) => (
                <tr key={a.activationId}>
                  <td>{a.deviceName ?? '—'}</td>
                  <td className="mono text-[11.5px]">{a.installationId}</td>
                  <td>{a.osInfo ?? '—'}</td>
                  <td>{a.appVersion ?? '—'}</td>
                  <td>
                    <StatusBadge status={a.status} />
                  </td>
                  <td className="nowrap">{formatDateTime(a.activatedAt)}</td>
                  <td className="nowrap">{formatDateTime(a.lastHeartbeatAt)}</td>
                  {hasPermission('ACTIVATION_MANAGE') && (
                    <td>
                      <div className="row-actions">
                      {a.licFileIssuedAt && (
                        <button
                          type="button"
                          className="btn btn-sm"
                          title="Download the signed .lic issued to this machine"
                          onClick={() =>
                            void activationsApi.downloadLicFile(a.activationId).catch((e: Error) => setActionError(e))
                          }
                        >
                          <Icon name="download" size={14} />
                          .lic
                        </button>
                      )}
                      {a.status === 'ACTIVE' && (
                        <button type="button" className="btn btn-sm btn-danger-outline" onClick={() => setDeactivating(a)}>
                          <Icon name="ban" size={14} />
                          Deactivate
                        </button>
                      )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-2 mb-4 gap-4">
        <div className="card">
          <div className="card-header">
            <h2>Renewal History</h2>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Plan</th>
                  <th>New Expiry</th>
                  <th className="num">Amount</th>
                  <th>Payment Ref</th>
                </tr>
              </thead>
              <tbody>
                {renewals.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      <div className="table-empty">No renewals recorded.</div>
                    </td>
                  </tr>
                )}
                {renewals.map((r) => (
                  <tr key={r.renewalId}>
                    <td className="nowrap">{formatDate(r.renewalDate)}</td>
                    <td>{r.newPlanName ?? r.newPlanId ?? '—'}</td>
                    <td className="nowrap">{r.newExpiryDate ? formatDate(r.newExpiryDate) : 'Lifetime'}</td>
                    <td className="num">{formatCurrency(r.amount, r.currency)}</td>
                    <td>{r.paymentRef ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h2>Status History</h2>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Transition</th>
                  <th>By</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {history.length === 0 && (
                  <tr>
                    <td colSpan={4}>
                      <div className="table-empty">No status changes recorded.</div>
                    </td>
                  </tr>
                )}
                {history.map((h) => (
                  <tr key={h.historyId}>
                    <td className="nowrap">{formatDateTime(h.changedAt)}</td>
                    <td>
                      {h.oldStatus ? <StatusBadge status={h.oldStatus} /> : <span className="muted">new</span>}{' '}
                      <Icon name="chevron-right" size={12} className="muted align-middle" />{' '}
                      <StatusBadge status={h.newStatus} />
                    </td>
                    <td>{h.changedBy ?? '—'}</td>
                    <td>{h.reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {l.keys && l.keys.length > 0 && (
        <div className="card mb-4">
          <div className="card-header">
            <h2>Key History</h2>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Status</th>
                  <th>Generated</th>
                  <th>Revoked</th>
                </tr>
              </thead>
              <tbody>
                {l.keys.map((k) => (
                  <tr key={k.keyId}>
                    <td className="mono">{k.licenseKey}</td>
                    <td>
                      <StatusBadge status={k.status} />
                    </td>
                    <td className="nowrap">{formatDateTime(k.generatedAt)}</td>
                    <td className="nowrap">{formatDateTime(k.revokedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <h2>Audit Trail</h2>
          <Link to={`/audit-logs?entity=LICENSE&entityId=${l.licenseId}`} className="btn-link">
            View all
          </Link>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Request ID</th>
              </tr>
            </thead>
            <tbody>
              {audit.loading && (
                <tr>
                  <td colSpan={4}>
                    <div className="table-empty">
                      <Spinner size={18} />
                    </div>
                  </td>
                </tr>
              )}
              {!audit.loading && (audit.data?.items ?? []).length === 0 && (
                <tr>
                  <td colSpan={4}>
                    <div className="table-empty">No audit events for this license.</div>
                  </td>
                </tr>
              )}
              {(audit.data?.items ?? []).map((a) => (
                <tr key={a.auditId}>
                  <td className="nowrap">{formatDateTime(a.createdAt)}</td>
                  <td>
                    <span className="badge badge-grayblue badge-plain">{a.action}</span>
                  </td>
                  <td>{a.actor}</td>
                  <td className="mono text-xs">{a.requestId ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <ConfirmDialog
        open={deactivating !== null}
        title="Deactivate Installation"
        danger
        requireReason
        message={
          <>
            Deactivate <strong>{deactivating?.deviceName ?? deactivating?.installationId}</strong>? The activation slot
            is freed and the installation will be denied on its next validation.
          </>
        }
        confirmLabel="Deactivate"
        onConfirm={async (reason) => {
          if (!deactivating) return;
          try {
            const res = await activationsApi.deactivate(deactivating.activationId, reason);
            setDeactivating(null);
            setActionError(null);
            if (isPendingApproval(res)) setPending(res.message);
            else reloadAll();
          } catch (err) {
            setDeactivating(null);
            setActionError(err instanceof Error ? err : new Error('Deactivation failed'));
          }
        }}
        onClose={() => setDeactivating(null)}
      />
    </div>
  );
}
