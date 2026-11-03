/**
 * Step 1 of the self-service flow, for someone who is not a user of this
 * console: pick a product, leave an address, and wait for the emailed link.
 *
 * Renders outside RequireAuth and outside AppLayout — there is no sidebar,
 * no topbar and no session. Every call goes through publicApi, which sends no
 * Authorization header and never redirects to /login.
 */
import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '../../components/ErrorState';
import { FormField } from '../../components/FormField';
import { Icon } from '../../components/Icon';
import { Spinner } from '../../components/Spinner';
import { publicApi } from '../../services/api/endpoints';
import { ApiError } from '../../services/api/http';
import { useApi } from '../../hooks/useApi';
import type { PublicCataloguePlan, PublicRequestStarted } from '../../types';
import {
  BRAND, CARD, FOOTER, LOADING, LOGO, OUTCOME, OUTCOME_BODY, OUTCOME_TITLE, PAGE, PICK_BODY, PICK_LIST, PICK_META, PICK_NAME,
  SECTION_TITLE, outcomeIcon, pickOption, pickRadio,
} from './publicStyles';

/** Human wording for a plan's term, straight from the catalogue values. */
function planTerm(plan: PublicCataloguePlan): string {
  if (plan.isLifetime) return 'lifetime';
  if (plan.durationDays === null) return plan.planName;
  return `${plan.durationDays} days`;
}

const INTRO = 'mb-4 text-md leading-[1.65] text-ink-2';

export function RequestLicensePage() {
  const catalogue = useApi(() => publicApi.catalogue(), []);
  const [productCode, setProductCode] = useState('');
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [done, setDone] = useState<PublicRequestStarted | null>(null);

  const products = catalogue.data?.products ?? [];
  // 403 is the "requests are closed" setting, not a failure to explain away.
  const closed = catalogue.error instanceof ApiError && catalogue.error.status === 403;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !productCode) return;
    setBusy(true);
    setError(null);
    try {
      setDone(await publicApi.start(email.trim(), productCode));
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Could not submit the request.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={PAGE}>
      <div className={`${CARD} max-w-[560px]`}>
        <div className={BRAND}>
          <div className={LOGO}>K</div>
          <div>
            <h1 className="text-lg tracking-[-0.02em]">Request a licence</h1>
            <div className="mt-px text-sm text-ink-2">Karnex License Center · self-service</div>
          </div>
        </div>

        {closed ? (
          <>
            <div className="alert alert-warning block">
              <div className="mb-1 font-semibold">Requests are closed</div>
              {catalogue.error?.message}
            </div>
            <p className={INTRO}>
              Licences are not being issued through this page at the moment. If you already have a
              contact at Karnex License Center, please reach out to them directly.
            </p>
          </>
        ) : done ? (
          <div className={OUTCOME}>
            <div className={outcomeIcon()}>
              <Icon name="inbox" size={26} />
            </div>
            <div className={OUTCOME_TITLE}>Check your inbox</div>
            {/* The server deliberately says the same thing whether or not the
                address is known, so we show its wording verbatim. */}
            <p className={OUTCOME_BODY}>{done.message}</p>
            <p className={`${OUTCOME_BODY} muted`}>
              The link opens a short form and expires after a while. If nothing arrives, check your
              spam folder before requesting again.
            </p>
            <div className="mt-4 text-sm text-muted">
              Reference <span className="mono">#{done.requestId}</span>
            </div>
          </div>
        ) : (
          <>
            <p className={INTRO}>
              Choose the product you need and tell us where to send the form. We will email you a
              private link to complete the details — the licence key itself always goes to that
              mailbox.
            </p>
            <ErrorBanner error={catalogue.error ?? error} />

            <form onSubmit={submit}>
              <div className="mt-5">
                <div className={SECTION_TITLE}>Product</div>
                {catalogue.loading ? (
                  <div className={LOADING}>
                    <Spinner size={18} /> Loading products…
                  </div>
                ) : products.length === 0 ? (
                  <div className="alert alert-info">
                    <Icon name="info" size={16} />
                    <div>No products are available for self-service requests right now.</div>
                  </div>
                ) : (
                  <div className={PICK_LIST} role="radiogroup" aria-label="Product">
                    {products.map((p) => (
                      <button
                        type="button"
                        key={p.productCode}
                        role="radio"
                        aria-checked={productCode === p.productCode}
                        className={pickOption(productCode === p.productCode)}
                        onClick={() => setProductCode(p.productCode)}
                      >
                        <span className={pickRadio(productCode === p.productCode)} aria-hidden />
                        <span className={PICK_BODY}>
                          <span className={PICK_NAME}>{p.productName}</span>
                          <span className={`${PICK_META} mono`}>{p.productCode}</span>
                          {p.plans.length > 0 && (
                            <span className={PICK_META}>
                              Plans: {p.plans.map((pl) => `${pl.planName} (${planTerm(pl)})`).join(' · ')}
                            </span>
                          )}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="mt-5">
                <div className={SECTION_TITLE}>Where to send the form</div>
                <FormField
                  label="Work email"
                  required
                  htmlFor="req-email"
                  hint="The licence key is only ever sent to this address."
                >
                  <input
                    id="req-email"
                    className="input"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                    maxLength={255}
                    placeholder="you@company.com"
                  />
                </FormField>
              </div>

              <button
                type="submit"
                className="btn btn-primary btn-lg btn-block mt-1.5"
                disabled={busy || !email.trim() || !productCode}
              >
                {busy && <Spinner size={14} />} Send me the form
              </button>
            </form>
          </>
        )}

        <div className="mt-5 pt-4 text-center text-sm text-muted [border-top:1px_solid_var(--border)]">
          Already a team member? <Link to="/login">Sign in to the console</Link>
        </div>
        <div className={FOOTER}>Karnex License Center · Licence Requests</div>
      </div>
    </div>
  );
}
