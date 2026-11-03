/**
 * Step 2 of the self-service flow: the form behind the emailed link.
 *
 * Also runs with no session and no app shell. The token in the URL is the only
 * credential, and it is single-use, so the three ways it can fail (not valid /
 * already used / expired) each get their own plain explanation rather than a
 * generic error box.
 */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ErrorBanner } from '../../components/ErrorState';
import { FormField } from '../../components/FormField';
import { Icon } from '../../components/Icon';
import { Spinner } from '../../components/Spinner';
import { publicApi } from '../../services/api/endpoints';
import { ApiError } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import { formatDate, formatDateTime } from '../../utils/format';
import type { PublicFormPlan, PublicRequestFormBody, PublicRequestOutcome } from '../../types';
import {
  BRAND, CARD, FOOTER, LOADING, LOGO, OUTCOME, OUTCOME_BODY, OUTCOME_TITLE, PAGE, PICK_BODY, PICK_LIST, PICK_META, PICK_NAME,
  SECTION_TITLE, outcomeIcon, pickOption, pickRadio,
} from './publicStyles';

/** The plan the flow is built around: a trial issues straight away. */
function isTrial(plan: PublicFormPlan): boolean {
  return plan.planCode.toUpperCase() === 'TRIAL';
}

function planTerm(plan: PublicFormPlan): string {
  if (plan.isLifetime) return 'Lifetime';
  if (plan.durationDays === null) return '—';
  return `${plan.durationDays} days`;
}

/** Caps the plan carries, so the requester knows what they are asking for. */
function planCaps(plan: PublicFormPlan): string {
  const parts = [`${plan.maxActivations} installation${plan.maxActivations === 1 ? '' : 's'}`];
  if (plan.maxUsers !== null) parts.push(`${plan.maxUsers} users`);
  if (plan.maxBranches !== null) parts.push(`${plan.maxBranches} branches`);
  return parts.join(' · ');
}

/** A link failure the requester can act on, instead of a raw status code. */
function linkProblem(error: ApiError): { title: string; body: string } {
  switch (error.status) {
    case 404:
      return {
        title: 'This link is not valid',
        body: 'The address may have been copied incompletely. Open the link straight from the email, or start a new request.',
      };
    case 409:
      return {
        title: 'This link has already been used',
        body: 'The form behind it was submitted once and cannot be reopened. If you still need a licence, start a new request.',
      };
    case 410:
      return {
        title: 'This link has expired',
        body: 'Links are short-lived on purpose. Request a new one and we will email a fresh link.',
      };
    case 403:
      return { title: 'Requests are closed', body: error.message };
    default:
      return { title: 'We could not open this form', body: error.message };
  }
}

/** Blank string → undefined, so optional fields are omitted rather than sent empty. */
function opt(value: string): string | undefined {
  const v = value.trim();
  return v === '' ? undefined : v;
}

/** A count field only travels if it is a usable positive integer. */
function optCount(value: string): number | undefined {
  const v = value.trim();
  if (v === '') return undefined;
  const n = Number(v);
  return Number.isInteger(n) && n > 0 ? n : undefined;
}

const EMPTY_FORM = {
  companyName: '',
  domainName: '',
  contactPerson: '',
  contactPhone: '',
  osName: '',
  osVersion: '',
  hostName: '',
  appVersion: '',
  intendedInstalls: '',
  intendedUsers: '',
  intendedBranches: '',
  notes: '',
};

const READONLY = 'text-md [word-break:break-word]';

export function CompleteRequestPage() {
  const { token } = useParams<{ token: string }>();
  const load = useApi(() => publicApi.form(token ?? ''), [token]);
  const [planCode, setPlanCode] = useState('');
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [outcome, setOutcome] = useState<PublicRequestOutcome | null>(null);

  const data = load.data;
  const plans = data?.plans ?? [];

  // Pre-select the trial — it is the recommended path and the only one that
  // issues immediately. Falls back to the first plan the product offers.
  // Keyed on the plan codes so the effect does not re-run on every render.
  const planKey = plans.map((p) => p.planCode).join('|');
  useEffect(() => {
    const codes = planKey === '' ? [] : planKey.split('|');
    if (codes.length === 0) return;
    setPlanCode((current) => {
      if (current !== '' && codes.includes(current)) return current;
      return codes.find((c) => c.toUpperCase() === 'TRIAL') ?? codes[0]!;
    });
  }, [planKey]);

  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const valid =
    form.companyName.trim().length >= 2 &&
    form.contactPerson.trim().length >= 2 &&
    form.contactPhone.trim().length >= 5 &&
    planCode !== '';

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid || !token) return;
    setBusy(true);
    setError(null);
    const body: PublicRequestFormBody = {
      companyName: form.companyName.trim(),
      domainName: opt(form.domainName),
      contactPerson: form.contactPerson.trim(),
      contactPhone: form.contactPhone.trim(),
      planCode,
      osName: opt(form.osName),
      osVersion: opt(form.osVersion),
      hostName: opt(form.hostName),
      appVersion: opt(form.appVersion),
      intendedInstalls: optCount(form.intendedInstalls),
      intendedUsers: optCount(form.intendedUsers),
      intendedBranches: optCount(form.intendedBranches),
      notes: opt(form.notes),
    };
    try {
      setOutcome(await publicApi.submit(token, body));
    } catch (err) {
      // 409 here is the active-trial guard; the server's wording explains it.
      setError(err instanceof Error ? err : new Error('Could not submit the form.'));
    } finally {
      setBusy(false);
    }
  };

  const problem = load.error instanceof ApiError ? linkProblem(load.error) : null;
  const selected = plans.find((p) => p.planCode === planCode) ?? null;

  return (
    <div className={PAGE}>
      <div className={`${CARD} max-w-[760px]`}>
        <div className={BRAND}>
          <div className={LOGO}>K</div>
          <div>
            <h1 className="text-lg tracking-[-0.02em]">Complete your licence request</h1>
            <div className="mt-px text-sm text-ink-2">
              {data ? data.productName : 'Karnex License Center · self-service'}
            </div>
          </div>
        </div>

        {load.loading && (
          <div className={LOADING}>
            <Spinner size={18} /> Opening your form…
          </div>
        )}

        {problem && (
          <>
            <div className="alert alert-warning block">
              <div className="mb-1 font-semibold">{problem.title}</div>
              {problem.body}
            </div>
            <Link className="btn btn-primary btn-block mt-2.5" to="/request">
              Start a new request
            </Link>
          </>
        )}

        {/* Issued or queued — either way the form is finished. */}
        {outcome && outcome.issued && (
          <div className={OUTCOME}>
            <div className={outcomeIcon(true)}>
              <Icon name="check" size={26} />
            </div>
            <div className={OUTCOME_TITLE}>Your licence has been issued</div>
            <p className={OUTCOME_BODY}>{outcome.message}</p>
            <div className="def-grid mt-5 text-left">
              <div className="def-item">
                <div className="def-label">Licence number</div>
                <div className="def-value mono">{outcome.licenseNo}</div>
              </div>
              <div className="def-item">
                <div className="def-label">Valid until</div>
                <div className="def-value">
                  {outcome.expiryDate === null ? 'Lifetime' : formatDate(outcome.expiryDate)}
                </div>
              </div>
            </div>
            <div className="alert alert-info mt-[14px]">
              <Icon name="key" size={16} />
              <div>
                The licence key is not shown here. It has been emailed to{' '}
                <strong>{data?.email}</strong> — that mailbox is the only place it is sent.
              </div>
            </div>
          </div>
        )}

        {outcome && !outcome.issued && (
          <div className={OUTCOME}>
            <div className={outcomeIcon()}>
              <Icon name="clock" size={26} />
            </div>
            <div className={OUTCOME_TITLE}>With our team for review</div>
            <p className={OUTCOME_BODY}>{outcome.message}</p>
            <p className={`${OUTCOME_BODY} muted`}>
              We will email <strong>{data?.email}</strong> as soon as a decision is made.
            </p>
          </div>
        )}

        {data && !outcome && (
          <>
            <ErrorBanner error={error} />
            <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-4 rounded border border-solid border-line bg-surface-sunken p-4">
              <div>
                <div className={SECTION_TITLE}>Your email</div>
                <div className={`${READONLY} mono`}>{data.email}</div>
              </div>
              <div>
                <div className={SECTION_TITLE}>Product</div>
                <div className={READONLY}>
                  {data.productName} <span className="muted mono">{data.productCode}</span>
                </div>
              </div>
            </div>
            {data.expiresAt !== null && (
              <div className="mt-2 flex items-center gap-1.5 text-sm text-muted">
                <Icon name="clock" size={13} /> This link stops working on{' '}
                {formatDateTime(data.expiresAt)}
              </div>
            )}

            <form onSubmit={submit}>
              <div className="mt-5">
                <div className={SECTION_TITLE}>Plan</div>
                {plans.length === 0 ? (
                  <div className="alert alert-info">
                    <Icon name="info" size={16} />
                    <div>No plans are currently published for this product.</div>
                  </div>
                ) : (
                  <div className={PICK_LIST} role="radiogroup" aria-label="Plan">
                    {plans.map((p) => (
                      <button
                        type="button"
                        key={p.planCode}
                        role="radio"
                        aria-checked={planCode === p.planCode}
                        className={pickOption(planCode === p.planCode, isTrial(p))}
                        onClick={() => setPlanCode(p.planCode)}
                      >
                        <span className={pickRadio(planCode === p.planCode)} aria-hidden />
                        <span className={PICK_BODY}>
                          <span className={PICK_NAME}>
                            {p.planName}
                            {isTrial(p) && <span className="rounded-full border border-solid border-primary-border bg-primary-soft px-[7px] py-0.5 text-[9px] font-bold uppercase tracking-[0.08em] text-primary">Recommended</span>}
                          </span>
                          <span className={PICK_META}>
                            {planTerm(p)} · {planCaps(p)}
                          </span>
                          {isTrial(p) && (
                            <span className={PICK_META}>Issued immediately, no review needed.</span>
                          )}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {selected !== null && !isTrial(selected) && (
                  <div className="field-hint mt-2">
                    This plan is reviewed by our team before the licence is issued.
                  </div>
                )}
              </div>

              <div className="mt-5">
                <div className={SECTION_TITLE}>Company</div>
                <div className="form-grid">
                  <FormField label="Company name" required htmlFor="rq-company">
                    <input
                      id="rq-company"
                      className="input"
                      value={form.companyName}
                      onChange={(e) => set('companyName', e.target.value)}
                      maxLength={200}
                      autoComplete="organization"
                    />
                  </FormField>
                  <FormField label="Domain" htmlFor="rq-domain" hint="e.g. company.com">
                    <input
                      id="rq-domain"
                      className="input"
                      value={form.domainName}
                      onChange={(e) => set('domainName', e.target.value)}
                      maxLength={255}
                    />
                  </FormField>
                  <FormField label="Contact person" required htmlFor="rq-contact">
                    <input
                      id="rq-contact"
                      className="input"
                      value={form.contactPerson}
                      onChange={(e) => set('contactPerson', e.target.value)}
                      maxLength={150}
                      autoComplete="name"
                    />
                  </FormField>
                  <FormField label="Contact phone" required htmlFor="rq-phone">
                    <input
                      id="rq-phone"
                      className="input"
                      value={form.contactPhone}
                      onChange={(e) => set('contactPhone', e.target.value)}
                      maxLength={30}
                      autoComplete="tel"
                    />
                  </FormField>
                </div>
              </div>

              <div className="mt-5">
                <div className={SECTION_TITLE}>System details</div>
                <div className="form-grid">
                  <FormField label="Operating system" htmlFor="rq-os">
                    <input
                      id="rq-os"
                      className="input"
                      value={form.osName}
                      onChange={(e) => set('osName', e.target.value)}
                      maxLength={100}
                      placeholder="Windows Server"
                    />
                  </FormField>
                  <FormField label="OS version" htmlFor="rq-osv">
                    <input
                      id="rq-osv"
                      className="input"
                      value={form.osVersion}
                      onChange={(e) => set('osVersion', e.target.value)}
                      maxLength={60}
                      placeholder="2022"
                    />
                  </FormField>
                  <FormField label="Host name" htmlFor="rq-host">
                    <input
                      id="rq-host"
                      className="input"
                      value={form.hostName}
                      onChange={(e) => set('hostName', e.target.value)}
                      maxLength={150}
                    />
                  </FormField>
                  <FormField label="KStack version" htmlFor="rq-appv">
                    <input
                      id="rq-appv"
                      className="input"
                      value={form.appVersion}
                      onChange={(e) => set('appVersion', e.target.value)}
                      maxLength={30}
                    />
                  </FormField>
                </div>
                <div className="form-grid grid-cols-3 max-[680px]:grid-cols-1">
                  <FormField label="Intended installations" htmlFor="rq-installs">
                    <input
                      id="rq-installs"
                      className="input"
                      type="number"
                      min={1}
                      max={9999}
                      value={form.intendedInstalls}
                      onChange={(e) => set('intendedInstalls', e.target.value)}
                    />
                  </FormField>
                  <FormField label="Intended users" htmlFor="rq-users">
                    <input
                      id="rq-users"
                      className="input"
                      type="number"
                      min={1}
                      max={99999}
                      value={form.intendedUsers}
                      onChange={(e) => set('intendedUsers', e.target.value)}
                    />
                  </FormField>
                  <FormField label="Intended branches" htmlFor="rq-branches">
                    <input
                      id="rq-branches"
                      className="input"
                      type="number"
                      min={1}
                      max={9999}
                      value={form.intendedBranches}
                      onChange={(e) => set('intendedBranches', e.target.value)}
                    />
                  </FormField>
                </div>
                <FormField label="Anything else we should know?" htmlFor="rq-notes">
                  <textarea
                    id="rq-notes"
                    className="input"
                    rows={3}
                    value={form.notes}
                    onChange={(e) => set('notes', e.target.value)}
                    maxLength={1000}
                  />
                </FormField>
              </div>

              <button
                type="submit"
                className="btn btn-primary btn-lg btn-block mt-1.5"
                disabled={busy || !valid}
              >
                {busy && <Spinner size={14} />} Submit request
              </button>
            </form>
          </>
        )}

        <div className={FOOTER}>Karnex License Center · Licence Requests</div>
      </div>
    </div>
  );
}
