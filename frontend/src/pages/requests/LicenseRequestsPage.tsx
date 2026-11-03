/**
 * Admin review screen for the self-service flow.
 *
 * Trials are issued by the backend without anyone touching them; what lands
 * here are the paid-plan submissions sitting in UNDER_REVIEW, plus the history
 * of everything that came through the public form or a staff invite.
 */
import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { DataTable } from '../../components/DataTable';
import type { Column } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import { SearchInput } from '../../components/SearchInput';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState, ErrorBanner } from '../../components/ErrorState';
import { Modal } from '../../components/Modal';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { FormField } from '../../components/FormField';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { Avatar } from '../../components/Viz';
import { RowDelete } from '../../components/RowDelete';
import { PendingBanner } from '../../components/PendingBanner';
import { licenseRequestsApi, plansApi, productsApi } from '../../services/api/endpoints';
import type { LicenseRequestListParams } from '../../services/api/endpoints';
import { ApiError } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { useAuth } from '../../auth/AuthContext';
import { formatDate, formatDateTime } from '../../utils/format';
import { VBS_EDITIONS, VBS_FEATURES, VBS_MODES } from '../../types';
import type {
  ApproveRequestBody,
  LicenseRequest,
  LicenseRequestDetail,
  LicenseRequestStatus,
  Product,
  VbsFeature,
} from '../../types';

const STATUSES: LicenseRequestStatus[] = [
  'INVITED',
  'SUBMITTED',
  'UNDER_REVIEW',
  'AUTO_ISSUED',
  'APPROVED',
  'REJECTED',
  'EXPIRED',
];

/** One definition cell; renders an em dash when the API sent nothing. */
function Def({ label, value }: { label: string; value: React.ReactNode }) {
  const empty = value === null || value === undefined || value === '';
  return (
    <div className="def-item">
      <div className="def-label">{label}</div>
      <div className="def-value">{empty ? <span className="muted">—</span> : value}</div>
    </div>
  );
}

function SourceChip({ source }: { source: string }) {
  return (
    <span className="inline-flex items-center gap-[5px] whitespace-nowrap rounded-full border border-solid border-line bg-surface-sunken px-2 py-0.5 text-xs font-semibold text-ink-2">
      <Icon name={source === 'INVITE' ? 'user' : 'external'} size={12} />
      {source === 'INVITE' ? 'Invited' : 'Public'}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Vehicle SIM requests                                                 */
/* ------------------------------------------------------------------ */

interface VbsAsk {
  machineId: string;
  mode?: number;
  edition?: number;
  features?: VbsFeature[];
}

/** The suggestion the Vehicle SIM app posted; null for every other kind of request. */
function parseVbsAsk(raw: string | null | undefined): VbsAsk | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Partial<VbsAsk> & { kind?: string };
    if (v.kind !== 'VBS_KEY' || typeof v.machineId !== 'string') return null;
    const features = Array.isArray(v.features)
      ? (v.features.filter((f): f is VbsFeature => (VBS_FEATURES as readonly string[]).includes(String(f))))
      : undefined;
    return {
      machineId: v.machineId,
      ...(typeof v.mode === 'number' ? { mode: v.mode } : {}),
      ...(typeof v.edition === 'number' ? { edition: v.edition } : {}),
      ...(features ? { features } : {}),
    };
  } catch {
    return null;
  }
}

const editionLabel = (v?: number) => VBS_EDITIONS.find((e) => e.value === v)?.label ?? 'any edition';
const modeLabel = (v?: number) => VBS_MODES.find((m) => m.value === v)?.label ?? 'any mode';

/* ------------------------------------------------------------------ */
/* Invite modal                                                        */
/* ------------------------------------------------------------------ */

function InviteModal({
  open,
  onClose,
  onInvited,
}: {
  open: boolean;
  onClose: () => void;
  onInvited: (message: string) => void;
}) {
  const products = useApi(() => productsApi.list({ pageSize: 200, status: 'ACTIVE' }), []);
  const [email, setEmail] = useState('');
  const [productCode, setProductCode] = useState('');
  const [planCode, setPlanCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);

  useEffect(() => {
    if (!open) return;
    setEmail('');
    setProductCode('');
    setPlanCode('');
    setError(null);
    setBusy(false);
  }, [open]);

  const items: Product[] = products.data?.items ?? [];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !productCode) return;
    setBusy(true);
    setError(null);
    try {
      const res = await licenseRequestsApi.invite({
        email: email.trim(),
        productCode,
        ...(planCode.trim() === '' ? {} : { planCode: planCode.trim().toUpperCase() }),
      });
      onInvited(res.message);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Could not send the invitation.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Invite a requester" open={open} onClose={onClose}>
      <ErrorBanner error={error ?? products.error} />
      <form onSubmit={submit}>
        <FormField
          label="Email"
          required
          htmlFor="inv-email"
          hint="They receive a private link to the request form."
        >
          <input
            id="inv-email"
            className="input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            maxLength={255}
            placeholder="person@company.com"
          />
        </FormField>
        <FormField label="Product" required htmlFor="inv-product">
          <select
            id="inv-product"
            className="input"
            value={productCode}
            onChange={(e) => setProductCode(e.target.value)}
          >
            <option value="">Select a product…</option>
            {items.map((p) => (
              <option key={p.productId} value={p.productCode}>
                {p.productName} ({p.productCode})
              </option>
            ))}
          </select>
        </FormField>
        <FormField
          label="Plan code"
          htmlFor="inv-plan"
          hint="Leave blank to let the requester choose from the published plans."
        >
          <input
            id="inv-plan"
            className="input mono"
            value={planCode}
            onChange={(e) => setPlanCode(e.target.value)}
            maxLength={30}
            placeholder="Optional — e.g. TRIAL"
          />
        </FormField>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || !email.trim() || !productCode}
          >
            {busy && <Spinner size={13} />}
            <Icon name="inbox" size={15} />
            Send invite
          </button>
        </div>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/* Detail modal                                                        */
/* ------------------------------------------------------------------ */

function RequestDetailModal({
  requestId,
  onClose,
  onChanged,
  onDeleted,
  onPending,
}: {
  requestId: number | null;
  onClose: () => void;
  onChanged: (message: string) => void;
  onDeleted: () => void;
  onPending: (message: string) => void;
}) {
  const { hasPermission } = useAuth();
  const detail = useApi<LicenseRequestDetail | null>(
    () => (requestId === null ? Promise.resolve(null) : licenseRequestsApi.get(requestId)),
    [requestId],
  );
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<ApiError | Error | null>(null);
  const [rejecting, setRejecting] = useState(false);

  useEffect(() => {
    setActionError(null);
    setRejecting(false);
    setBusy(false);
  }, [requestId]);

  const r = detail.data;
  const canManage = hasPermission('REQUEST_LICENSE_MANAGE');
  const underReview = r?.status === 'UNDER_REVIEW';
  const invited = r?.status === 'INVITED';

  // A request the Vehicle SIM app raised itself carries its Machine ID and a
  // suggested grant. The reviewer decides the plan, edition and protocols.
  const vbsAsk = useMemo(() => parseVbsAsk(r?.licRequestJson), [r?.licRequestJson]);
  const isVbs = r?.keyFormat === 'VBS_KEY';
  const needsPlan = underReview && r?.planId == null;

  const plans = useApi(
    () =>
      r?.productId && underReview
        ? plansApi.list({ productId: r.productId, status: 'ACTIVE', pageSize: 100 })
        : Promise.resolve(null),
    [r?.productId, underReview],
  );
  const [amount, setAmount] = useState('');
  const [planCode, setPlanCode] = useState('');
  const [vbsMode, setVbsMode] = useState(1);
  const [vbsEdition, setVbsEdition] = useState(2);
  const [vbsFeatures, setVbsFeatures] = useState<VbsFeature[]>(['Can', 'Lin']);

  useEffect(() => {
    setAmount('');
    // Prefill from what the app asked for, so approving as-is is one click and
    // granting less is a visible, deliberate change.
    setVbsMode(vbsAsk?.mode ?? 0);
    setVbsEdition(vbsAsk?.edition ?? 2);
    setVbsFeatures(vbsAsk?.features ?? ['Can', 'Lin']);
  }, [requestId, vbsAsk]);

  // Plan: what the requester asked for (once the request has loaded) — unless it
  // is a trial this computer has already used. The reviewer can change it.
  const askedPlan = r?.planCode ?? '';
  const trialUsed = !!r?.priorTrial;
  useEffect(() => {
    setPlanCode(trialUsed && /^TRIAL/i.test(askedPlan) ? '' : askedPlan);
  }, [requestId, askedPlan, trialUsed]);

  const amountNum = amount.trim() === '' ? NaN : Number(amount);
  const amountOk = Number.isFinite(amountNum) && amountNum >= 0;
  const approveBody = (): ApproveRequestBody => ({
    planCode,
    amount: Math.round(amountNum * 100) / 100,
    ...(isVbs ? { vbs: { mode: vbsMode, edition: vbsEdition, features: vbsFeatures, keyVersion: 'V3' } } : {}),
  });
  const approveBlocked = !planCode || !amountOk;

  const run = async (fn: () => Promise<{ message: string }>) => {
    setBusy(true);
    setActionError(null);
    try {
      const res = await fn();
      onChanged(res.message);
      onClose();
    } catch (err) {
      // 403 (permission) and 409 (wrong status) arrive with the server's own
      // wording — show that rather than inventing an explanation.
      setActionError(err instanceof Error ? err : new Error('Action failed'));
      detail.reload();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Modal
        title={r ? `Licence Request #${r.requestId}` : 'Licence Request'}
        open={requestId !== null}
        onClose={onClose}
        size="lg"
      >
        {detail.loading && (
          <div className="fullpage-center h-40">
            <Spinner size={26} />
          </div>
        )}
        {detail.error && <ErrorBanner error={detail.error} />}
        <ErrorBanner error={actionError} />

        {r && (
          <>
            <div className="def-grid">
              <Def label="Email" value={<span className="mono">{r.email}</span>} />
              <Def label="Status" value={<StatusBadge status={r.status} />} />
              <Def label="Source" value={<SourceChip source={r.source} />} />
              <Def
                label="Product"
                value={
                  r.productName ? (
                    <>
                      {r.productName} <span className="muted mono">{r.productCode}</span>
                    </>
                  ) : null
                }
              />
              <Def
                label="Plan"
                value={
                  r.planName ? (
                    <>
                      {r.planName} <span className="muted mono">{r.planCode}</span>
                    </>
                  ) : null
                }
              />
              <Def label="Created" value={formatDateTime(r.createdAt)} />
              <Def
                label="Submitted"
                value={r.submittedAt ? formatDateTime(r.submittedAt) : null}
              />
              <Def
                label="Link expires"
                value={r.tokenExpiresAt ? formatDateTime(r.tokenExpiresAt) : null}
              />
              <Def label="Invited by" value={r.invitedByName} />
            </div>

            <div className="card-header px-0 pb-2 pt-4">
              <h2>Company</h2>
            </div>
            <div className="def-grid">
              <Def label="Company name" value={r.companyName} />
              <Def label="Domain" value={r.domainName} />
              <Def label="Contact person" value={r.contactPerson} />
              <Def label="Contact phone" value={r.contactPhone} />
              <Def
                label="Customer record"
                value={
                  r.customerId == null ? null : (
                    <Link to={`/customers/${r.customerId}`}>
                      {r.customerName ?? `Customer #${r.customerId}`}
                    </Link>
                  )
                }
              />
              <Def label="Request IP" value={r.ipAddress ? <span className="mono">{r.ipAddress}</span> : null} />
            </div>

            <div className="card-header px-0 pb-2 pt-4">
              <h2>System details</h2>
            </div>
            <div className="def-grid">
              <Def label="Operating system" value={r.osName} />
              <Def label="OS version" value={r.osVersion} />
              <Def label="Host name" value={r.hostName ? <span className="mono">{r.hostName}</span> : null} />
              <Def label="App version" value={r.appVersion} />
              <Def label="Intended installations" value={r.intendedInstalls} />
              <Def label="Intended users" value={r.intendedUsers} />
              <Def label="Intended branches" value={r.intendedBranches} />
            </div>
            {r.notes && (
              <div className="def-item mt-[14px]">
                <div className="def-label">Notes from the requester</div>
                <div className="def-value">{r.notes}</div>
              </div>
            )}

            {(vbsAsk || r.hwFingerprint) && (
              <>
                <div className="card-header px-0 pb-2 pt-4">
                  <h2>{vbsAsk ? 'Requested from the Vehicle SIM app' : 'Machine'}</h2>
                </div>
                <div className="def-grid">
                  <Def
                    label={vbsAsk ? 'Machine ID' : 'Hardware fingerprint'}
                    value={r.hwFingerprint ? <span className="mono">{r.hwFingerprint}</span> : null}
                  />
                  <Def label="MAC address" value={r.macAddress ? <span className="mono">{r.macAddress}</span> : null} />
                  <Def label="CPU ID" value={r.cpuId ? <span className="mono">{r.cpuId}</span> : null} />
                  <Def label="BIOS serial" value={r.biosSerial ? <span className="mono">{r.biosSerial}</span> : null} />
                  <Def label="Motherboard ID" value={r.motherboardId ? <span className="mono">{r.motherboardId}</span> : null} />
                  {vbsAsk && (
                    <>
                      <Def label="Asked for" value={`${editionLabel(vbsAsk.edition)} · ${modeLabel(vbsAsk.mode)}`} />
                      <Def label="Protocols asked for" value={vbsAsk.features?.join(', ') ?? '—'} />
                    </>
                  )}
                </div>
              </>
            )}

            {canManage && underReview && (
              <>
                <div className="card-header px-0 pb-2 pt-4">
                  <h2>What to grant</h2>
                </div>
                {r.priorTrial && (
                  <div className="alert alert-warning" role="status">
                    <Icon name="alert-triangle" size={16} />
                    <div>
                      This computer has already had a trial of this product (licence{' '}
                      <Link to={`/licenses/${r.priorTrial.licenseId}`} className="mono">{r.priorTrial.licenseNo}</Link>).
                      Trial plans cannot be granted to it again — choose a paid plan.
                    </div>
                  </div>
                )}
                <div className="form-grid">
                  <FormField
                    label="Plan"
                    required
                    htmlFor="apr-plan"
                    hint={needsPlan ? 'The request arrived without a plan; the expiry and seat count come from this.' : 'Prefilled with what was requested. Expiry and seat count come from this.'}
                  >
                    <select
                      id="apr-plan"
                      className="input"
                      value={planCode}
                      onChange={(e) => {
                        const code = e.target.value;
                        const pl = (plans.data?.items ?? []).find((p) => p.planCode === code);
                        setPlanCode(code);
                        if (amount === '' && pl?.price != null && pl.price > 0) setAmount(String(pl.price));
                      }}
                    >
                      <option value="">Select a plan…</option>
                      {(plans.data?.items ?? []).map((p) => {
                        const trialBlocked = !!r.priorTrial && /^TRIAL/i.test(p.planCode);
                        return (
                          <option key={p.planId} value={p.planCode} disabled={trialBlocked}>
                            {p.planName} ({p.planCode}){trialBlocked ? ' — trial already used on this computer' : ''}
                          </option>
                        );
                      })}
                    </select>
                  </FormField>
                  <FormField
                    label="Amount (₹)"
                    required
                    htmlFor="apr-amount"
                    error={amount !== '' && !amountOk ? 'Enter an amount of 0 or more.' : undefined}
                    hint="What the customer pays. 0 for a free licence."
                  >
                    <input
                      id="apr-amount"
                      className="input"
                      type="number"
                      inputMode="decimal"
                      min={0}
                      step="0.01"
                      placeholder="e.g. 25000"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                    />
                  </FormField>
                </div>
                {isVbs && (
                  <>
                    <div className="form-grid">
                      <FormField label="Mode" htmlFor="apr-mode" hint={VBS_MODES.find((m) => m.value === vbsMode)?.hint}>
                        <select id="apr-mode" className="input" value={vbsMode} onChange={(e) => setVbsMode(Number(e.target.value))}>
                          {VBS_MODES.map((m) => (
                            <option key={m.value} value={m.value}>{m.label}</option>
                          ))}
                        </select>
                      </FormField>
                      <FormField label="Edition" htmlFor="apr-edition">
                        <select id="apr-edition" className="input" value={vbsEdition} onChange={(e) => setVbsEdition(Number(e.target.value))}>
                          {VBS_EDITIONS.map((ed) => (
                            <option key={ed.value} value={ed.value}>{ed.label}</option>
                          ))}
                        </select>
                      </FormField>
                    </div>
                    <FormField
                      label="Licensed protocols"
                      hint={
                        vbsFeatures.length === 0
                          ? 'Nothing selected — the app will refuse to start any run.'
                          : 'Signed into the key; the app enforces exactly this set, online or offline.'
                      }
                    >
                      <div className="toggle-row">
                        {VBS_FEATURES.map((f) => (
                          <button
                            type="button"
                            key={f}
                            className={vbsFeatures.includes(f) ? 'toggle-chip is-on' : 'toggle-chip'}
                            aria-pressed={vbsFeatures.includes(f)}
                            onClick={() =>
                              setVbsFeatures((prev) =>
                                prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f],
                              )
                            }
                          >
                            {f}
                          </button>
                        ))}
                      </div>
                    </FormField>
                    <div className="alert alert-info mt-1.5">
                      <Icon name="info" size={16} />
                      <div>
                        On approval the key is bound to Machine ID{' '}
                        <span className="mono">{r.hwFingerprint}</span> and the app on that machine
                        activates itself the next time it checks in. Nobody has to type anything.
                      </div>
                    </div>
                  </>
                )}
              </>
            )}

            <div className="card-header px-0 pb-2 pt-4">
              <h2>Outcome</h2>
            </div>
            <div className="def-grid">
              <Def
                label="Licence"
                value={
                  r.licenseNo == null ? null : r.licenseId == null ? (
                    <span className="mono">{r.licenseNo}</span>
                  ) : (
                    <Link className="mono" to={`/licenses/${r.licenseId}`}>
                      {r.licenseNo}
                    </Link>
                  )
                }
              />
              <Def label="Licence status" value={<StatusBadge status={r.licenseStatus ?? null} />} />
              <Def
                label="Expiry"
                value={r.licenseNo == null ? null : r.expiryDate ? formatDate(r.expiryDate) : 'Lifetime'}
              />
              <Def label="Issued at" value={r.issuedAt ? formatDateTime(r.issuedAt) : null} />
              <Def label="Reviewed by" value={r.reviewedByName} />
              <Def label="Reviewed at" value={r.reviewedAt ? formatDateTime(r.reviewedAt) : null} />
              <Def label="Review comment" value={r.reviewComment} />
            </div>
            {r.licenseNo != null && (
              <div className="alert alert-info mt-[14px]">
                <Icon name="key" size={16} />
                <div>The licence key was emailed to the requester; it is never shown here.</div>
              </div>
            )}

            <div className="form-actions">
              <button type="button" className="btn" onClick={onClose} disabled={busy}>
                Close
              </button>
              {canManage && (
                <RowDelete
                  compact={false}
                  what={`licence request #${r.requestId}`}
                  confirmText={r.email}
                  detail="Only the request record is removed; a licence already issued from it is not affected."
                  onDelete={() => licenseRequestsApi.remove(r.requestId)}
                  onDeleted={() => {
                    onClose();
                    onDeleted();
                  }}
                  onPending={(message) => {
                    onClose();
                    onPending(message);
                  }}
                />
              )}
              {canManage && invited && (
                <button
                  type="button"
                  className="btn"
                  disabled={busy}
                  onClick={() => void run(() => licenseRequestsApi.resend(r.requestId))}
                >
                  {busy && <Spinner size={13} />}
                  <Icon name="refresh" size={15} />
                  Resend invite
                </button>
              )}
              {canManage && underReview && (
                <>
                  <button
                    type="button"
                    className="btn btn-danger-outline"
                    disabled={busy}
                    onClick={() => setRejecting(true)}
                  >
                    <Icon name="close" size={15} />
                    Reject
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy || approveBlocked}
                    title={approveBlocked ? 'Choose a plan and enter the amount first' : undefined}
                    onClick={() => void run(() => licenseRequestsApi.approve(r.requestId, approveBody()))}
                  >
                    {busy && <Spinner size={13} />}
                    <Icon name="check" size={15} />
                    Approve &amp; issue
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </Modal>

      {/* requireReason enforces the 3-character minimum the endpoint demands. */}
      <ConfirmDialog
        open={rejecting && r !== null}
        title="Reject Licence Request"
        danger
        requireReason
        reasonLabel="Rejection comment"
        message={
          <>
            Reject the request from <strong>{r?.email}</strong>? No licence is issued and the
            comment is emailed to the requester.
          </>
        }
        confirmLabel="Reject"
        onConfirm={async (reason) => {
          if (!r) return;
          const res = await licenseRequestsApi.reject(r.requestId, reason);
          setRejecting(false);
          onChanged(res.message);
          onClose();
        }}
        onClose={() => setRejecting(false)}
      />
    </>
  );
}

/* ------------------------------------------------------------------ */
/* List page                                                           */
/* ------------------------------------------------------------------ */

export function LicenseRequestsPage() {
  const { hasPermission } = useAuth();
  const list = useListState({ sort: 'requestId:desc' });
  const { data, loading, error, reload } = useApi(
    () => licenseRequestsApi.list(list.params as LicenseRequestListParams),
    [list.depsKey],
  );
  // Product filter options. A reviewer without PRODUCT_VIEW simply does not
  // get the filter rather than seeing an error for a secondary call.
  const products = useApi(() => productsApi.list({ pageSize: 200, status: 'ACTIVE' }), []);
  const [openId, setOpenId] = useState<number | null>(null);
  const [inviting, setInviting] = useState(false);

  // The bell links here as /license-requests?open=<id>: open that request
  // straight away, then drop the param so a refresh does not reopen it.
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const raw = searchParams.get('open');
    if (!raw) return;
    const id = Number(raw);
    if (Number.isFinite(id) && id > 0) setOpenId(id);
    searchParams.delete('open');
    setSearchParams(searchParams, { replace: true });
  }, [searchParams, setSearchParams]);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const canManage = hasPermission('REQUEST_LICENSE_MANAGE');
  const rows = data?.items ?? [];
  const productOptions = products.data?.items ?? [];

  const columns: Array<Column<LicenseRequest>> = [
    {
      key: 'requestId',
      header: 'Request #',
      sortable: true,
      width: 110,
      render: (r) => <span className="mono code-cell">#{r.requestId}</span>,
    },
    {
      key: 'email',
      header: 'Email',
      sortable: true,
      render: (r) => (
        <span className="name-cell">
          <Avatar name={r.companyName ?? r.email} size={26} />
          <span className="mono">{r.email}</span>
        </span>
      ),
    },
    {
      key: 'companyName',
      header: 'Company',
      sortable: true,
      render: (r) => r.companyName ?? <span className="muted">—</span>,
    },
    {
      key: 'productName',
      header: 'Product',
      render: (r) => r.productName ?? <span className="muted">—</span>,
    },
    {
      key: 'planName',
      header: 'Plan',
      render: (r) => r.planName ?? <span className="muted">—</span>,
    },
    { key: 'status', header: 'Status', sortable: true, render: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'source',
      header: 'Source',
      sortable: true,
      render: (r) => <SourceChip source={r.source} />,
    },
    {
      key: 'createdAt',
      header: 'Created',
      sortable: true,
      render: (r) => <span className="nowrap">{formatDateTime(r.createdAt)}</span>,
    },
    ...(canManage
      ? [
          {
            key: '_actions',
            header: 'Actions',
            align: 'right' as const,
            render: (r: LicenseRequest) => (
              <div className="row-actions">
                <RowDelete
                  what={`licence request #${r.requestId}`}
                  confirmText={r.email}
                  detail="Only the request record is removed; a licence already issued from it is not affected."
                  onDelete={() => {
                    setPending(null);
                    return licenseRequestsApi.remove(r.requestId);
                  }}
                  onDeleted={reload}
                  onPending={setPending}
                />
              </div>
            ),
          },
        ]
      : []),
  ];

  return (
    <div>
      <div className="overview-head">
        <div>
          <h1>Licence Requests</h1>
          <div className="subtitle">Self-service requests and staff invitations</div>
        </div>
        <div className="head-meta">
          <button type="button" className="btn btn-sm" onClick={reload}>
            <Icon name="refresh" size={14} />
            Refresh
          </button>
          {canManage && (
            <button type="button" className="btn btn-primary" onClick={() => setInviting(true)}>
              <Icon name="plus" size={15} />
              Invite
            </button>
          )}
        </div>
      </div>

      {notice && (
        <div className="alert alert-success mb-4">
          <Icon name="check" size={16} />
          <div>{notice}</div>
        </div>
      )}

      <PendingBanner message={pending} />

      <div className="card">
        <div className="adv-filter">
          <span className="adv-filter-label">Advanced Filtering</span>
          <SearchInput value={list.state.q} onChange={list.setQ} placeholder="Email or company…" />
          <select
            className="input"
            aria-label="Status"
            value={list.state.filters['status'] ?? ''}
            onChange={(e) => list.setFilter('status', e.target.value)}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          <select
            className="input"
            aria-label="Source"
            value={list.state.filters['source'] ?? ''}
            onChange={(e) => list.setFilter('source', e.target.value)}
          >
            <option value="">All sources</option>
            <option value="PUBLIC">Public</option>
            <option value="INVITE">Invited</option>
          </select>
          {productOptions.length > 0 && (
            <select
              className="input"
              aria-label="Product"
              value={list.state.filters['productId'] ?? ''}
              onChange={(e) => list.setFilter('productId', e.target.value)}
            >
              <option value="">All products</option>
              {productOptions.map((p) => (
                <option key={p.productId} value={String(p.productId)}>
                  {p.productName}
                </option>
              ))}
            </select>
          )}
          <div className="filter-item">
            <label htmlFor="lr-from">Created from</label>
            <input
              id="lr-from"
              className="input"
              type="date"
              value={list.state.filters['createdFrom'] ?? ''}
              onChange={(e) => list.setFilter('createdFrom', e.target.value)}
            />
          </div>
          <div className="filter-item">
            <label htmlFor="lr-to">Created to</label>
            <input
              id="lr-to"
              className="input"
              type="date"
              value={list.state.filters['createdTo'] ?? ''}
              onChange={(e) => list.setFilter('createdTo', e.target.value)}
            />
          </div>
          {list.hasFilters && (
            <div className="adv-filter-right">
              <button type="button" className="btn btn-sm btn-ghost" onClick={list.clearFilters}>
                Clear
              </button>
            </div>
          )}
        </div>

        {error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(r) => r.requestId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              onRowClick={(r) => setOpenId(r.requestId)}
              emptyTitle="No licence requests"
              emptyMessage="Requests from the public form and staff invitations appear here."
            />
            <div className="table-foot">
              <span className="foot-count">
                Total requests: <strong>{data?.total ?? 0}</strong>
                {rows.length > 0 && ` (showing ${rows.length})`}
              </span>
              <Pagination
                page={data?.page ?? list.state.page}
                pageSize={data?.pageSize ?? list.state.pageSize}
                total={data?.total ?? 0}
                onPageChange={list.setPage}
                onPageSizeChange={list.setPageSize}
              />
            </div>
          </>
        )}
      </div>

      <RequestDetailModal
        requestId={openId}
        onClose={() => setOpenId(null)}
        onChanged={(message) => {
          setNotice(message);
          reload();
        }}
        onDeleted={reload}
        onPending={setPending}
      />

      <InviteModal
        open={inviting}
        onClose={() => setInviting(false)}
        onInvited={(message) => {
          setNotice(message);
          reload();
        }}
      />
    </div>
  );
}
