import { useEffect, useMemo, useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { ErrorState, ErrorBanner } from '../../components/ErrorState';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { asItems, rolesApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import type { Permission, Role } from '../../types';

export function RolesPage() {
  const roles = useApi(() => rolesApi.list(), []);
  const perms = useApi(() => rolesApi.permissions(), []);

  const roleList: Role[] = useMemo(() => (roles.data ? asItems(roles.data) : []), [roles.data]);
  const permList: Permission[] = useMemo(() => (perms.data ? asItems(perms.data) : []), [perms.data]);

  const [selectedRoleId, setSelectedRoleId] = useState<number | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [saved, setSaved] = useState(false);

  const selectedRole = roleList.find((r) => r.roleId === selectedRoleId) ?? null;

  useEffect(() => {
    if (selectedRoleId === null && roleList.length > 0) {
      setSelectedRoleId(roleList[0]?.roleId ?? null);
    }
  }, [roleList, selectedRoleId]);

  useEffect(() => {
    setChecked(new Set(selectedRole?.permissions ?? []));
    setDirty(false);
    setSaved(false);
    setError(null);
  }, [selectedRole]);

  const togglePerm = (code: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
    setDirty(true);
    setSaved(false);
  };

  const save = async () => {
    if (!selectedRole) return;
    setBusy(true);
    setError(null);
    try {
      await rolesApi.setPermissions(selectedRole.roleId, [...checked].sort());
      setDirty(false);
      setSaved(true);
      roles.reload();
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Save failed'));
    } finally {
      setBusy(false);
    }
  };

  // Group permissions by prefix (LICENSE_, CUSTOMER_, ...)
  const groups = useMemo(() => {
    const map = new Map<string, Permission[]>();
    for (const p of permList) {
      const prefix = p.permCode.split('_')[0] ?? 'OTHER';
      const arr = map.get(prefix) ?? [];
      arr.push(p);
      map.set(prefix, arr);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [permList]);

  if (roles.loading || perms.loading) {
    return (
      <div className="fullpage-center h-[50vh]">
        <Spinner size={30} />
      </div>
    );
  }

  if (roles.error) {
    return (
      <div className="card">
        <ErrorState error={roles.error} onRetry={roles.reload} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Roles & Permissions" subtitle="Control which permissions each role grants" />
      <div className="grid grid-cols-[220px_1fr] items-start gap-4">
        <div className="card">
          <div className="card-header">
            <h2>Roles</h2>
          </div>
          <div>
            {roleList.map((r) => (
              <button
                key={r.roleId}
                type="button"
                // important: these replaced inline styles, which the .btn / .btn-ghost hover rules must not override
                className={`btn btn-ghost btn-block justify-start !rounded-none !border-0 !border-l-[3px] !border-solid text-left ${
                  r.roleId === selectedRoleId
                    ? '!border-l-primary !bg-primary-soft font-semibold !text-primary'
                    : '!border-l-transparent !bg-transparent font-normal !text-ink'
                }`}
                onClick={() => setSelectedRoleId(r.roleId)}
              >
                {r.roleCode}
              </button>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h2>{selectedRole ? `Permissions — ${selectedRole.roleCode}` : 'Permissions'}</h2>
            <div className="flex items-center gap-2">
              {saved && (
                <span className="badge badge-green badge-plain">
                  <Icon name="check" size={11} />
                  Saved
                </span>
              )}
              <button type="button" className="btn btn-primary btn-sm" onClick={save} disabled={!dirty || busy || !selectedRole}>
                {busy && <Spinner size={12} />} Save Permissions
              </button>
            </div>
          </div>
          <div className="card-body">
            <ErrorBanner error={error} />
            {selectedRole?.description && <p className="text-secondary mt-0">{selectedRole.description}</p>}
            {permList.length === 0 && <div className="table-empty">No permissions defined.</div>}
            {groups.map(([prefix, groupPerms]) => (
              <div key={prefix} className="mb-4">
                <div className="def-label mb-1.5">
                  {prefix}
                </div>
                <div className="grid grid-3 gap-1.5">
                  {groupPerms.map((p) => (
                    <label key={p.permId} className="checkbox-row">
                      <input type="checkbox" checked={checked.has(p.permCode)} onChange={() => togglePerm(p.permCode)} />
                      <span>
                        <span className="mono text-sm">{p.permCode}</span>
                        {p.description && <span className="muted"> — {p.description}</span>}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
