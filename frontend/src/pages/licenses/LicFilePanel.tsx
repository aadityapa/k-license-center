import { useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { ErrorBanner } from '../../components/ErrorState';
import { Icon } from '../../components/Icon';
import { Spinner } from '../../components/Spinner';
import { useAuth } from '../../auth/AuthContext';
import { licensesApi } from '../../services/api/endpoints';
import { isPendingApproval, saveText } from '../../services/api/http';
import type { IssuedLicFile, LicenseDetail } from '../../types';

interface Props {
  license: LicenseDetail;
  onChanged: () => void;
  onPending: (message: string) => void;
}

/** Same ceiling the server enforces; a real request file is well under 1 KB. */
const MAX_BYTES = 20_000;

/**
 * Issue a signed .lic for a KStack/KFlash machine that cannot reach the portal.
 *
 * The customer runs the product, which writes a request file with the
 * machine's hardware IDs, and emails it. Upload it here; the signed file comes
 * straight back to download and send. It takes a seat, so a maker's upload
 * goes to a checker first and the file is then downloadable from the machine's
 * row under Activations.
 */
export function LicFilePanel({ license, onChanged, onPending }: Props) {
  const { hasPermission } = useAuth();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [issued, setIssued] = useState<IssuedLicFile | null>(null);

  if (!hasPermission('LICENSE_MANAGE')) return null;

  const seatsLeft = Math.max(0, license.maxActivations - license.currentActivations);

  const pick = async (e: ChangeEvent<HTMLInputElement>) => {
    setError(null);
    setIssued(null);
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > MAX_BYTES) {
      setError(new Error(`${f.name} is ${Math.round(f.size / 1024)} KB — a .lic request is under 1 KB. Is this the right file?`));
      return;
    }
    setFileName(f.name);
    setText(await f.text());
  };

  const submit = async () => {
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      const res = await licensesApi.issueLicFile(license.licenseId, text);
      if (isPendingApproval(res)) {
        onPending(res.message);
      } else {
        setIssued(res);
        saveText(res.licFile, res.fileName);   // straight to the user's Downloads
        onChanged();
      }
      setText(null);
      setFileName(null);
      if (inputRef.current) inputRef.current.value = '';
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card mb-4">
      <div className="card-header">
        <h2>Issue Activation File</h2>
        <span className="muted text-[13px]">
          For a machine that cannot reach the portal · {seatsLeft} of {license.maxActivations} seats free
        </span>
      </div>
      <div className="card-body">
        <ErrorBanner error={error} />
        <p className="muted mt-0 text-[13px]">
          The customer’s product writes a <span className="mono">.lic</span> request file holding that
          machine’s hardware IDs. Upload it here and a signed file bound to that machine comes back to send
          them. Uploading the same machine’s file again re-issues it without using another seat.
        </p>

        <div className="flex flex-wrap items-center gap-2.5">
          <input
            ref={inputRef}
            type="file"
            accept=".lic,.json,.txt"
            onChange={(e) => void pick(e)}
            disabled={busy}
            aria-label="Choose the customer’s .lic request file"
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void submit()}
            disabled={busy || !text}
          >
            {busy ? <Spinner size={14} /> : <Icon name="key" size={15} />}
            {busy ? 'Signing…' : 'Issue signed file'}
          </button>
          {fileName && !busy && <span className="muted text-[13px]">{fileName}</span>}
        </div>

        {issued && (
          <div className="alert alert-success mt-4 block">
            <div className="mb-1.5 font-semibold">
              {issued.reissued ? 'Re-issued' : 'Issued'} {issued.fileName}
            </div>
            <div className="text-[13px]">
              Bound to machine <span className="mono">{issued.fingerprint.slice(0, 16)}…</span>. It has been
              downloaded; send it to the customer to place next to the product.{' '}
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => saveText(issued.licFile, issued.fileName)}
              >
                <Icon name="download" size={13} /> Download again
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
