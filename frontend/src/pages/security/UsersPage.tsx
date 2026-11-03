import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { DataTable } from '../../components/DataTable';
import type { Column } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import { SearchInput } from '../../components/SearchInput';
import { FilterBar, FilterItem } from '../../components/FilterBar';
import { StatusBadge } from '../../components/StatusBadge';
import { ErrorState, ErrorBanner } from '../../components/ErrorState';
import { Modal } from '../../components/Modal';
import { FormField } from '../../components/FormField';
import { Spinner } from '../../components/Spinner';
import { Icon } from '../../components/Icon';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { asItems, rolesApi, usersApi } from '../../services/api/endpoints';
import { useApi } from '../../hooks/useApi';
import { useListState } from '../../hooks/useListState';
import { formatDateTime } from '../../utils/format';
import type { AdminUser, Role } from '../../types';
import { useAuth } from '../../auth/AuthContext';

/** The main admin account: never locked, deactivated or stripped of ADMIN (enforced by the API and the database). */
const PROTECTED_USERNAME = 'admin';
const isProtectedUser = (u: { username?: string } | null | undefined): boolean =>
  (u?.username ?? '').toLowerCase() === PROTECTED_USERNAME;

interface UserFormState {
  username: string;
  fullName: string;
  email: string;
  password: string;
  status: string;
  roleIds: number[];
}

export function UsersPage() {
  const { user: me } = useAuth();
  const list = useListState({ sort: 'username:asc' });
  const { data, loading, error, reload } = useApi(() => usersApi.list(list.params), [list.depsKey]);
  const roles = useApi(() => rolesApi.list(), []);
  const allRoles: Role[] = roles.data ? asItems(roles.data) : [];

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [form, setForm] = useState<UserFormState>({
    username: '',
    fullName: '',
    email: '',
    password: '',
    status: 'ACTIVE',
    roleIds: [],
  });
  const [deleting, setDeleting] = useState<AdminUser | null>(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<Error | null>(null);

  useEffect(() => {
    if (modalOpen) {
      setFormError(null);
      setForm({
        username: editing?.username ?? '',
        fullName: editing?.fullName ?? '',
        email: editing?.email ?? '',
        password: '',
        status: editing?.status ?? 'ACTIVE',
        roleIds: editing?.roles?.map((r) => r.roleId) ?? editing?.roleIds ?? [],
      });
    }
  }, [modalOpen, editing]);

  const isProtected = isProtectedUser(editing);
  // Only the admin may change the admin's own name, email or password.
  const detailsLocked = isProtected && me?.userId !== editing?.userId;

  const toggleRole = (roleId: number) =>
    setForm((f) => ({
      ...f,
      roleIds: f.roleIds.includes(roleId) ? f.roleIds.filter((id) => id !== roleId) : [...f.roleIds, roleId],
    }));

  const valid =
    form.username.trim() !== '' &&
    form.fullName.trim() !== '' &&
    form.email.trim() !== '' &&
    (editing !== null || form.password.length >= 8);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setFormError(null);
    try {
      if (editing) {
        await usersApi.update(editing.userId, {
          fullName: form.fullName.trim() || undefined,
          email: form.email.trim(),
          status: form.status as AdminUser['status'],
          ...(form.password ? { password: form.password } : {}),
        });
        await usersApi.setRoles(editing.userId, form.roleIds);
      } else {
        await usersApi.create({
          username: form.username.trim(),
          fullName: form.fullName.trim() || undefined,
          email: form.email.trim(),
          password: form.password,
          status: form.status as AdminUser['status'],
          roleIds: form.roleIds,
        });
      }
      setModalOpen(false);
      reload();
    } catch (err) {
      setFormError(err instanceof Error ? err : new Error('Save failed'));
    } finally {
      setBusy(false);
    }
  };

  const columns: Array<Column<AdminUser>> = [
    {
      key: 'username',
      header: 'Username',
      sortable: true,
      render: (u) => (
        <span className="inline-flex items-center gap-1.5">
          <span className="mono">{u.username}</span>
          {isProtectedUser(u) && (
            <span className="badge badge-grayblue badge-plain" title="Main admin account: cannot be locked, deactivated or lose the ADMIN role">
              Protected
            </span>
          )}
        </span>
      ),
    },
    { key: 'fullName', header: 'Full Name', sortable: true },
    { key: 'email', header: 'Email' },
    {
      key: 'roles',
      header: 'Roles',
      render: (u) =>
        u.roles && u.roles.length > 0 ? (
          <span className="inline-flex flex-wrap gap-1">
            {u.roles.map((r) => (
              <span key={r.roleId} className="badge badge-grayblue badge-plain">
                {r.roleCode}
              </span>
            ))}
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    { key: 'status', header: 'Status', render: (u) => <StatusBadge status={u.status} /> },
    { key: 'lastLoginAt', header: 'Last Login', sortable: true, render: (u) => <span className="nowrap">{formatDateTime(u.lastLoginAt)}</span> },
    {
      key: '_actions',
      header: '',
      render: (u) => (
        <span className="row-actions">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              setEditing(u);
              setModalOpen(true);
            }}
          >
            <Icon name="edit" size={14} />
            Edit
          </button>
          {!isProtectedUser(u) && u.userId !== me?.userId && (
            <button type="button" className="btn btn-sm btn-danger" onClick={() => setDeleting(u)}>
              <Icon name="trash" size={14} />
              Delete
            </button>
          )}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle="Admin console users and their roles"
        actions={
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setEditing(null);
              setModalOpen(true);
            }}
          >
            <Icon name="plus" size={15} />
            New User
          </button>
        }
      />
      <div className="card">
        <FilterBar showClear={list.hasFilters} onClear={list.clearFilters}>
          <FilterItem label="Search">
            <SearchInput value={list.state.q} onChange={list.setQ} placeholder="Username or email…" />
          </FilterItem>
          <FilterItem label="Status">
            <select
              className="input"
              value={list.state.filters['status'] ?? ''}
              onChange={(e) => list.setFilter('status', e.target.value)}
            >
              <option value="">All</option>
              <option value="ACTIVE">ACTIVE</option>
              <option value="LOCKED">LOCKED</option>
              <option value="INACTIVE">INACTIVE</option>
            </select>
          </FilterItem>
        </FilterBar>
        {error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(u) => u.userId}
              loading={loading}
              sort={list.state.sort}
              onSortChange={list.setSort}
              emptyTitle="No users"
              emptyMessage="Create an admin user to grant console access."
            />
            <Pagination
              page={data?.page ?? list.state.page}
              pageSize={data?.pageSize ?? list.state.pageSize}
              total={data?.total ?? 0}
              onPageChange={list.setPage}
              onPageSizeChange={list.setPageSize}
            />
          </>
        )}
      </div>

      <Modal title={editing ? `Edit User — ${editing.username}` : 'New User'} open={modalOpen} onClose={() => setModalOpen(false)}>
        <ErrorBanner error={formError} />
        <form onSubmit={submit}>
          <div className="form-grid">
            <FormField label="Username" required>
              <input
                className="input mono"
                value={form.username}
                onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                disabled={Boolean(editing)}
                maxLength={50}
              />
            </FormField>
            <FormField label="Status" hint={isProtected ? 'The main admin account always stays ACTIVE.' : undefined}>
              <select
                className="input"
                value={form.status}
                onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
                disabled={isProtected}
              >
                <option value="ACTIVE">ACTIVE</option>
                <option value="LOCKED">LOCKED</option>
                <option value="INACTIVE">INACTIVE</option>
              </select>
            </FormField>
          </div>
          {detailsLocked && (
            <div className="field-hint mb-2">
              This is the main admin account. Its name, email and password can only be changed by signing in as admin.
            </div>
          )}
          <FormField label="Full Name" required>
            <input
              className="input"
              value={form.fullName}
              onChange={(e) => setForm((f) => ({ ...f, fullName: e.target.value }))}
              disabled={detailsLocked}
            />
          </FormField>
          <FormField label="Email" required>
            <input
              className="input"
              type="email"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              disabled={detailsLocked}
            />
          </FormField>
          <FormField
            label={editing ? 'New Password' : 'Password'}
            required={!editing}
            hint={editing ? 'Leave blank to keep the current password.' : 'Minimum 8 characters.'}
          >
            <input
              className="input"
              type="password"
              value={form.password}
              onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              autoComplete="new-password"
              disabled={detailsLocked}
            />
          </FormField>
          <FormField label="Roles">
            <div className="stack-8">
              {allRoles.length === 0 && <span className="muted">No roles defined.</span>}
              {allRoles.map((r) => (
                <label key={r.roleId} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={form.roleIds.includes(r.roleId)}
                    onChange={() => toggleRole(r.roleId)}
                    disabled={isProtected && r.roleCode === 'ADMIN'}
                    title={isProtected && r.roleCode === 'ADMIN' ? 'The main admin account always keeps the ADMIN role' : undefined}
                  />
                  <span>
                    <strong>{r.roleCode}</strong>
                    {r.description && <span className="muted"> — {r.description}</span>}
                  </span>
                </label>
              ))}
            </div>
          </FormField>
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => setModalOpen(false)} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={!valid || busy}>
              {busy && <Spinner size={13} />}
              {!busy && !editing && <Icon name="plus" size={15} />}
              {editing ? 'Save Changes' : 'Create User'}
            </button>
          </div>
        </form>
      </Modal>
      <ConfirmDialog
        open={deleting !== null}
        title="Delete User"
        danger
        confirmText={deleting?.username}
        confirmLabel="Delete user"
        message={
          <>
            Delete <strong>{deleting?.fullName}</strong> (<span className="mono">{deleting?.username}</span>)? They are
            signed out at once and can no longer sign in, their roles are removed, and any changes they submitted
            that are still waiting for approval are cancelled. Their past actions stay in the audit log and history
            under their name. The username and email can be used again for a new account.
          </>
        }
        onConfirm={async () => {
          if (!deleting) return;
          await usersApi.remove(deleting.userId);
          setDeleting(null);
          reload();
        }}
        onClose={() => setDeleting(null)}
      />
    </div>
  );
}
