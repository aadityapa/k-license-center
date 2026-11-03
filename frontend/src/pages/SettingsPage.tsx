import { useEffect, useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { ErrorState, ErrorBanner } from '../components/ErrorState';
import { PendingBanner } from '../components/PendingBanner';
import { Spinner } from '../components/Spinner';
import { Icon } from '../components/Icon';
import { asItems, settingsApi } from '../services/api/endpoints';
import { isPendingApproval } from '../services/api/http';
import { useAuth } from '../auth/AuthContext';
import { useApi } from '../hooks/useApi';
import { formatDateTime } from '../utils/format';
import type { Setting } from '../types';

export function SettingsPage() {
  const { hasPermission } = useAuth();
  const { data, loading, error, reload } = useApi(() => settingsApi.list(), []);
  const settings: Setting[] = data ? asItems(data) : [];

  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<Error | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState<string | null>(null);

  const canManage = hasPermission('SETTINGS_MANAGE');

  useEffect(() => {
    const next: Record<string, string> = {};
    for (const s of settings) next[s.settingKey] = s.settingValue;
    setValues(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const dirtyKeys = settings.filter((s) => (values[s.settingKey] ?? '') !== s.settingValue).map((s) => s.settingKey);

  const save = async () => {
    setBusy(true);
    setSaveError(null);
    setSaved(false);
    setPending(null);
    try {
      const res = await settingsApi.update(
        dirtyKeys.map((key) => ({ settingKey: key, settingValue: values[key] ?? '' })),
      );
      if (isPendingApproval(res)) {
        setPending(res.message);
      } else {
        setSaved(true);
        reload();
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err : new Error('Save failed'));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="fullpage-center h-[50vh]">
        <Spinner size={30} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <ErrorState error={error} onRetry={reload} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="System configuration (grace periods, heartbeat intervals, expiry warnings)"
        actions={
          <>
            {saved && dirtyKeys.length === 0 && (
              <span className="badge badge-green badge-plain self-center">
                <Icon name="check" size={11} />
                Saved
              </span>
            )}
            {canManage && (
              <button type="button" className="btn btn-primary" onClick={save} disabled={busy || dirtyKeys.length === 0}>
                {busy && <Spinner size={13} />} Save Changes {dirtyKeys.length > 0 && `(${dirtyKeys.length})`}
              </button>
            )}
          </>
        }
      />
      <ErrorBanner error={saveError} />
      <PendingBanner message={pending} />
      <div className="card">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-60">Key</th>
                <th className="w-[260px]">Value</th>
                <th>Description</th>
                <th className="w-[170px]">Last Updated</th>
              </tr>
            </thead>
            <tbody>
              {settings.length === 0 && (
                <tr>
                  <td colSpan={4}>
                    <div className="table-empty">No settings found.</div>
                  </td>
                </tr>
              )}
              {settings.map((s) => (
                <tr key={s.settingKey}>
                  <td className="mono">{s.settingKey}</td>
                  <td>
                    <input
                      className={`input mono${
                        (values[s.settingKey] ?? '') !== s.settingValue ? ' !border-warning !bg-warning-soft' : ''
                      }`}
                      value={values[s.settingKey] ?? ''}
                      onChange={(e) => setValues((v) => ({ ...v, [s.settingKey]: e.target.value }))}
                    />
                  </td>
                  <td className="text-secondary">{s.description ?? '—'}</td>
                  <td className="nowrap">{formatDateTime(s.updatedAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
