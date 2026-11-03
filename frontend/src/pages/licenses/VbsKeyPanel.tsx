import { useState } from 'react';
import { CopyButton } from '../../components/CopyButton';
import { ErrorBanner } from '../../components/ErrorState';
import { FormField } from '../../components/FormField';
import { Icon } from '../../components/Icon';
import { Spinner } from '../../components/Spinner';
import { useAuth } from '../../auth/AuthContext';
import { licensesApi } from '../../services/api/endpoints';
import { isPendingApproval } from '../../services/api/http';
import { VBS_EDITIONS, VBS_FEATURES, VBS_MODES } from '../../types';
import type { IssuedVbsKey, LicenseDetail, VbsFeature } from '../../types';

interface Props {
  license: LicenseDetail;
  onChanged: () => void;
  onPending: (message: string) => void;
}

/**
 * Issues a Vehicle SIM key.
 *
 * Vehicle SIM is unlike the other products: its key is not a lookup token, it
 * IS the licence. Mode, edition and the per-protocol feature set are signed
 * into the key so the app can enforce them with no connection. That is why they
 * are chosen here rather than derived from the plan.
 *
 * What this form deliberately does NOT ask for is the expiry or the seat count.
 * Those come from the licence record on the server, so nothing entered here can
 * grant more than was actually sold.
 */
export function VbsKeyPanel({ license, onChanged, onPending }: Props) {
  const { hasPermission } = useAuth();
  const [mode, setMode] = useState(1);
  const [edition, setEdition] = useState(2);
  const [features, setFeatures] = useState<VbsFeature[]>(['Can', 'Lin']);
  // The computer the current key is bound to (or the one that asked for this licence),
  // so re-issuing for the same PC needs no typing.
  const [machineId, setMachineId] = useState(
    license.vbsMachineId ?? license.computers?.find((c) => c.boundToKey)?.machineId ?? license.computers?.[0]?.machineId ?? '',
  );
  const [licensedTo, setLicensedTo] = useState('');
  const [keyVersion, setKeyVersion] = useState<'V2' | 'V3'>('V3');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [issued, setIssued] = useState<IssuedVbsKey | null>(null);

  if (!hasPermission('LICENSE_MANAGE')) return null;

  const machine = machineId.trim();
  // Mirrors the server's rules so the button explains itself rather than
  // bouncing off a 400. The server still enforces both.
  // Every key is bound to one computer, whatever the mode.
  const machineMissing = machine.length === 0;
  const machineMalformed = machine.length > 0 && !/^[0-9A-Fa-f]{8,64}$/.test(machine);
  const hasActiveKey = license.keys?.some((k) => k.status === 'ACTIVE') ?? false;

  const toggle = (f: VbsFeature) =>
    setFeatures((prev) => (prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f]));

  async function submit() {
    setBusy(true);
    setError(null);
    setIssued(null);
    try {
      const res = await licensesApi.issueVbsKey(license.licenseId, {
        mode,
        edition,
        features,
        keyVersion,
        ...(machine ? { machineId: machine } : {}),
        ...(licensedTo.trim() ? { licensedTo: licensedTo.trim() } : {}),
      });

      if (isPendingApproval(res)) {
        // A maker's request mints nothing until a checker approves it, so
        // there is no key to show yet.
        onPending(res.message);
      } else {
        setIssued(res);
        onChanged();
      }
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card mb-4">
      <div className="card-header">
        <h2>Vehicle SIM Key</h2>
        <span className="muted text-[13px]">
          The entitlement is signed into the key, so the app enforces it offline
        </span>
      </div>

      <div className="card-body">
        <ErrorBanner error={error} />

        <div className="form-grid">
          <FormField
            label="Mode"
            htmlFor="vbs-mode"
            hint={VBS_MODES.find((m) => m.value === mode)?.hint}
          >
            <select
              id="vbs-mode"
              className="input"
              value={mode}
              onChange={(e) => setMode(Number(e.target.value))}
              disabled={busy}
            >
              {VBS_MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </FormField>

          <FormField label="Edition" htmlFor="vbs-edition">
            <select
              id="vbs-edition"
              className="input"
              value={edition}
              onChange={(e) => setEdition(Number(e.target.value))}
              disabled={busy}
            >
              {VBS_EDITIONS.map((ed) => (
                <option key={ed.value} value={ed.value}>
                  {ed.label}
                </option>
              ))}
            </select>
          </FormField>

          <FormField
            label="Machine ID"
            htmlFor="vbs-machine"
            required
            error={machineMalformed ? 'Should be the 16 hex characters shown in the app.' : undefined}
            hint="Read it from the Machine ID line in the customer’s Licence window. The key works on that computer only."
          >
            <input
              id="vbs-machine"
              className="input mono"
              value={machineId}
              onChange={(e) => setMachineId(e.target.value)}
              placeholder="A1B2C3D4E5F60718"
              disabled={busy}
              aria-invalid={machineMissing || machineMalformed}
            />
          </FormField>

          <FormField
            label="Licensed to"
            htmlFor="vbs-licensed-to"
            hint="Shown in the app. Defaults to the customer’s company name."
          >
            <input
              id="vbs-licensed-to"
              className="input"
              value={licensedTo}
              onChange={(e) => setLicensedTo(e.target.value)}
              placeholder={license.customerName ?? ''}
              disabled={busy}
            />
          </FormField>
        </div>

        <FormField
          label="Licensed protocols"
          hint={
            features.length === 0
              ? 'Nothing selected — the app will refuse to start any run.'
              : 'The app blocks any run needing a protocol outside this set.'
          }
        >
          <div className="toggle-row">
            {VBS_FEATURES.map((f) => (
              <button
                type="button"
                key={f}
                className={features.includes(f) ? 'toggle-chip is-on' : 'toggle-chip'}
                onClick={() => toggle(f)}
                disabled={busy}
                aria-pressed={features.includes(f)}
              >
                {f}
              </button>
            ))}
          </div>
        </FormField>

        <FormField
          label="Signature"
          hint={
            keyVersion === 'V3'
              ? 'Signed with a key that never leaves this server. The app holds only the public half, so it can check a key but nobody can forge one.'
              : 'Only for installs on a build that predates V3. V2 is signed with a secret that ships inside the app, so anyone who extracts it can mint their own Enterprise key. Reissue as V3 once the machine is updated.'
          }
        >
          <div className="toggle-row">
            <button
              type="button"
              className={keyVersion === 'V3' ? 'toggle-chip is-on' : 'toggle-chip'}
              onClick={() => setKeyVersion('V3')}
              disabled={busy}
              aria-pressed={keyVersion === 'V3'}
            >
              V3 — asymmetric
            </button>
            <button
              type="button"
              className={keyVersion === 'V2' ? 'toggle-chip is-warn' : 'toggle-chip'}
              onClick={() => setKeyVersion('V2')}
              disabled={busy}
              aria-pressed={keyVersion === 'V2'}
            >
              {keyVersion === 'V2' && <Icon name="alert-triangle" size={13} />}
              V2 — legacy
            </button>
          </div>
        </FormField>

        <div className="mt-2 flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="btn btn-primary"
            onClick={submit}
            disabled={busy || machineMissing || machineMalformed}
          >
            {busy ? <Spinner size={14} /> : <Icon name="key" size={15} />}
            {busy ? 'Issuing…' : 'Issue key'}
          </button>
          {hasActiveKey && (
            <span className="muted text-[13px]">
              This replaces the current key — the existing one stops working.
            </span>
          )}
        </div>

        {issued && (
          <div className="alert alert-success mt-4 block">
            <div className="mb-2 font-semibold">
              {issued.keyVersion} key issued for {issued.licenceNo}
            </div>
            <div className="key-display break-all">
              <span className="mono">{issued.licenseKey}</span>
              <CopyButton text={issued.licenseKey} />
            </div>
            <div className="mt-2 text-[13px]">
              Licensed to {issued.licensedTo} ·{' '}
              {issued.expiry ? `expires ${issued.expiry}` : 'perpetual'}. Send this to the customer
              to paste into the app’s Licence window.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
